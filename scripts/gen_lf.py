#!/usr/bin/env python3
"""
Generate an N-federate Lingua Franca coordinator program.

The LF federation size is fixed at compile time, so to emulate
N robots we generate one self-contained ``coordinator_<N>.lf`` per
fleet size and compile each with ``lfc``.

Design (vs. the original hand-written 2-federate file):
  * ``CoordinatorFederate`` takes a ``num_peers`` parameter and uses a
    **multiport** input ``input[num_peers] proposal_in`` instead of the
    hard-coded ``proposal_from_fed1`` / ``proposal_from_fed2`` ports.
  * The ``federated reactor`` instantiates ``f1..fN`` (``device_id=i``)
    and wires an explicit **all-to-all** proposal mesh into each
    federate's multiport. Explicit connections (rather than a bank +
    interleaved ``(c.out)+ -> c.in``) keep the output predictable across
    lfc versions and give stable binary names ``federate__f{i}``.

Each federate ``f{i}`` binds TCP port ``9000 + device_id`` for its ROS
bridge, exactly as before, so ``i`` maps cleanly to a robot container.

Usage:
    python3 gen_lf.py --sizes 2,4,8,16            # write coordinator_<N>.lf
    python3 gen_lf.py --sizes 3 --compile         # also run lfc
    python3 gen_lf.py --sizes 2 --out coordinator.lf  # canonical default
"""

import argparse
import os
import subprocess
import sys

# Directory that holds the .lf files (relative ``files:`` paths resolve from here).
LF_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src", "coord", "lf"))

TARGET_AND_PREAMBLE = '''target Python {
  coordination: centralized,
  files: ["../coord/lease_manager.py", "../coord/task_registry.py", "../coord/coordinator.py"]
}

preamble {=
  import sys
  import os
  import socket
  import json
  import select

  # Add local path for imports
  sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../coord"))
  from coordinator import Coordinator
=}
'''

# The reactor body. Identical control logic to the original coordinator.lf,
# except the inputs are a single multiport ``proposal_in`` and the proposal
# reaction iterates over it.
REACTOR = '''reactor CoordinatorFederate(device_id=1, num_peers=1, lease_ttl_ms=300000, STP_offset = 0) {
  input[num_peers] proposal_in
  output proposal_out

  state coordinator
  state current_time_ms = 0

  state sock                     # Socket State (Single Threaded) - Initialized in startup
  state clients
  state client_buffers
  state request_queue
  state pending_responses

  state local_requests
  state next_req_seq = 0

  logical action next_microstep

  timer socket_poll(0, 10 msec)  # Timer for polling socket IO (approx 100Hz)
  timer tick(0, 100 msec)

  reaction(startup) {=
    # Initialize state variables FIRST (before any timer can fire)
    self.clients = {}
    self.client_buffers = {}
    self.request_queue = []
    self.pending_responses = {}
    self.local_requests = {}

    self.coordinator = Coordinator(default_lease_ttl_ms=self.lease_ttl_ms)
    self.debug = os.environ.get("LF_DEBUG", "0") == "1"
    print(f"[LF Coordinator Federate {self.device_id}] Started ({self.num_peers} peers)")

    # Initialize Non-Blocking Socket
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.setblocking(False)
    port = 9000 + self.device_id
    try:
        self.sock.bind(("0.0.0.0", port))
        self.sock.listen(5)
        print(f"[LF Fed {self.device_id}] Listening on port {port} (Non-Blocking)")
    except Exception as e:
        print(f"[LF Fed {self.device_id}] FATAL: Failed to bind port {port}: {e}")
        print(f"[LF Fed {self.device_id}] FATAL: Socket binding failed. Exiting.")
        import sys
        sys.exit(1)
  =}

  # 1. Poll Sockets (Input)
  reaction(socket_poll) -> next_microstep {=
    # Skip if socket not initialized yet (startup still running)
    if not hasattr(self, "sock") or self.sock is None:
      return

    # Handle New Connections and Incoming Data
    inputs = [self.sock] + list(self.clients.values())
    try:
        readable, _, _ = select.select(inputs, [], [], 0)
    except Exception as e:
        # Handle bad file descriptors by cleaning up
        to_remove = []
        for fd, s in self.clients.items():
            try:
                select.select([s], [], [], 0)
            except:
                to_remove.append(fd)
        for fd in to_remove:
            print(f"Removing bad client fd {fd}")
            del self.clients[fd]
            if fd in self.client_buffers: del self.client_buffers[fd]
        return

    for s in readable:
        if s is self.sock:
            # Accept new connection
            try:
                conn, addr = s.accept()
                conn.setblocking(False)
                fd = conn.fileno()
                self.clients[fd] = conn
                self.client_buffers[fd] = ""
                # print(f"New connection from {addr}, fd={fd}")
            except: pass
        else:
            # Read data
            fd = s.fileno()
            try:
                data = s.recv(4096)
                if data:
                    self.client_buffers[fd] += data.decode("utf-8")
                    # Process complete lines
                    while "\\n" in self.client_buffers[fd]:
                        line, rest = self.client_buffers[fd].split("\\n", 1)
                        self.client_buffers[fd] = rest
                        if not line.strip(): continue

                        try:
                            # Parse JSON
                            obj = json.loads(line)

                            # Read-only query: answer from the LOCAL replica
                            # (already consistent across all federates) instead of
                            # broadcasting through the RTI. This removes one
                            # federation round-trip per agent poll -- the largest
                            # source of RTI relay load at scale.
                            if obj.get("type") == "get_tasks":
                                tasks = self.coordinator.get_available_tasks()
                                reply = {
                                    "success": True,
                                    "tasks": [
                                        {"task_id": t.task_id, "location": t.location,
                                         "task_type": t.task_type, "priority": t.priority,
                                         "status": t.status.value}
                                        for t in tasks
                                    ],
                                }
                                try:
                                    s.sendall((json.dumps(reply) + "\\n").encode("utf-8"))
                                except Exception:
                                    pass
                                continue

                            req_id = str(id(obj)) + "_" + str(obj.get("agent_id", "0"))
                            # Queue mutating requests (create/claim/complete/locks) for broadcast
                            self.request_queue.append((req_id, obj, fd))
                            self.pending_responses[req_id] = fd
                        except Exception as e:
                            print(f"JSON Parse Error: {e}")
                else:
                    # EOF
                    # print(f"Client disconnected fd={fd}")
                    s.close()
                    del self.clients[fd]
                    if fd in self.client_buffers: del self.client_buffers[fd]
            except Exception as e:
                # Error reading
                print(f"Read error fd={fd}: {e}")
                try: s.close()
                except: pass
                if fd in self.clients: del self.clients[fd]
                if fd in self.client_buffers: del self.client_buffers[fd]

    # If we have pending requests, schedule processing immediately
    if self.request_queue:
        next_microstep.schedule(0, None)
  =}

  # 2. Timer Tick (Leases)
  reaction(tick) -> next_microstep {=
    try:
        self.current_time_ms = int(lf.time.logical_elapsed() / 1_000_000)
        self.coordinator.tick(self.current_time_ms)
    except Exception as e:
        print(f"Tick Error: {e}")
  =}

  # 3. Generate Proposals (Bundled)
  reaction(next_microstep) -> proposal_out {=
    if not self.request_queue:
        return

    # Drain queue
    # IMPORTANT: Copy and clear to avoid infinite processing if poll adds more
    current_batch = list(self.request_queue)
    self.request_queue.clear()

    bundled_data = []

    for req_id, data, origin_fd in current_batch:
        full_req_id = f"{self.device_id}_{self.next_req_seq}"
        self.next_req_seq += 1

        # Map global ID to (req_id, origin_fd)
        self.local_requests[full_req_id] = (req_id, origin_fd)

        bundled_data.append({
            "req_id": full_req_id,
            "data": data
        })

    proposal = {
        "origin_id": self.device_id,
        "bundled_requests": bundled_data,
        "logical_time": self.current_time_ms
    }

    if self.debug:
        print(f"[LF Fed {self.device_id}] Broadcasting bundle of {len(bundled_data)} requests")
    proposal_out.set(proposal)
  =}

  # 4. Process Proposals & Reply (all-to-all multiport: deterministic order)
  reaction(proposal_in) {=
    for i in range(proposal_in.width):
        proposal_input = proposal_in[i]
        if not proposal_input.is_present:
            continue

        proposal = proposal_input.value
        origin_id = proposal["origin_id"]

        request_list = proposal.get("bundled_requests", [])
        if not request_list and "data" in proposal:
             request_list = [{"req_id": proposal["req_id"], "data": proposal["data"]}]

        for req_item in request_list:
            req_id = req_item["req_id"]
            data = req_item["data"]
            req_type = data.get("type")

            response = {"success": False}

            if req_type == "create":
                tid = self.coordinator.create_task(
                    location=data["location"],
                    task_type=data.get("task_type", "pick"),
                    priority=data.get("priority", 1.0)
                )
                response = {"success": True, "task_id": tid}

            elif req_type == "claim":
                success = self.coordinator.try_claim(
                    task_id=data["task_id"],
                    agent_id=data["agent_id"],
                    ttl_ms=data.get("ttl_ms", None)
                )
                if self.debug:
                    print(f"[LF Fed {self.device_id}] Claim Task {data['task_id']} by Agent {data['agent_id']} -> {success}")
                response = {"success": success}

            elif req_type == "complete":
                success = self.coordinator.complete_task(
                    task_id=data["task_id"],
                    agent_id=data["agent_id"]
                )
                if self.debug:
                    print(f"[LF Fed {self.device_id}] Complete Task {data['task_id']} by Agent {data['agent_id']} -> {success}")
                response = {"success": success}

            elif req_type == "get_tasks":
                 tasks = self.coordinator.get_available_tasks()
                 response = {
                    "success": True,
                    "tasks": [
                        {
                            "task_id": t.task_id,
                            "location": t.location,
                            "task_type": t.task_type,
                            "priority": t.priority,
                            "status": t.status.value
                        } for t in tasks
                    ]
                }

            elif req_type == "acquire_node_lock":
                success = self.coordinator.acquire_node_lock(
                    node_id=data["node_id"],
                    agent_id=data["agent_id"],
                    ttl_ms=data.get("ttl_ms", 30000)
                )
                response = {"success": success}

            elif req_type == "release_node_lock":
                success = self.coordinator.release_node_lock(
                    node_id=data["node_id"],
                    agent_id=data["agent_id"]
                )
                response = {"success": success}

            # Send response if local
            if origin_id == self.device_id:
                if req_id in self.local_requests:
                    original_req_id, client_fd = self.local_requests.pop(req_id)

                    # Locate client socket
                    if client_fd in self.clients:
                        client_sock = self.clients[client_fd]
                        try:
                            client_sock.sendall((json.dumps(response) + "\\n").encode("utf-8"))
                        except Exception as e:
                            print(f"Error sending response to fd={client_fd}: {e}")
                            # Cleanup dead socket
                            try: client_sock.close()
                            except: pass
                            del self.clients[client_fd]
                            if client_fd in self.client_buffers: del self.client_buffers[client_fd]
  =} STP(0) {=
    # Decentralized safety net: a peer proposal arrived after this federate's
    # logical time advanced past it (tardy). With STP_offset set this is rare --
    # log it for visibility rather than failing. (Centralized never triggers it.)
    print(f"[LF Fed {self.device_id}] tardy proposal (STP violation)", flush=True)
  =}
}
'''


def build_federated_reactor(n: int, at_host=None) -> str:
    """Emit the ``federated reactor`` block with N federates + all-to-all mesh.

    ``at_host(i)`` -> hostname/IP for federate i. With host networking the
    default (localhost) is correct; on a Docker bridge each federate must
    advertise a peer-reachable address, so we emit ``... at "<ip>"``.
    """
    coord = os.environ.get("LF_COORD", "centralized")
    sta_ms = os.environ.get("LF_STA_MS", "100")   # decentralized safe-to-advance (maxwait) offset
    lines = ["federated reactor {"]
    for i in range(1, n + 1):
        # LF wants the `at` host UNQUOTED and the instantiation `;`-terminated.
        at = f" at {at_host(i)};" if at_host else ""
        # decentralized: each federate waits STP_offset (physical time) for peer
        # proposals before advancing -- no central RTI barrier. (Centralized
        # coordination ignores STP_offset and uses the RTI.)
        stp = f", STP_offset = {sta_ms} msec" if coord == "decentralized" else ""
        lines.append(f"  f{i} = new CoordinatorFederate(device_id={i}, num_peers={n}{stp}){at}")
    lines.append("")
    lines.append("  # All-to-all proposal mesh: every federate's output feeds every")
    lines.append("  # federate's multiport input (INCLUDING itself -- a federate applies")
    lines.append("  # its own requests to its replica only on receipt, so the self-loop")
    lines.append("  # is required for local consistency).")
    lines.append("  # O(N^2) connections, but 1 hop + clean ordering -- fine to N=16. For")
    lines.append("  # N>>16 a tree/star with flood-relay would cut connections at the cost of")
    lines.append("  # multi-hop ordering (tree) or a central hub (star): future work.")
    lines.append("  #")
    lines.append("  # `after 1 msec` is essential, not cosmetic: the mesh (self-loops +")
    lines.append("  # mutual edges) forms zero-delay cycles between federates. Under")
    lines.append("  # centralized coordination the RTI cannot compute a safe tag over a")
    lines.append("  # zero-delay cycle -- its tag_advance_grant_if_safe() walk SIGSEGVs")
    lines.append("  # (observed deterministically at N=4, intermittently at N=16). A")
    lines.append("  # small positive logical delay breaks every cycle and is negligible")
    lines.append("  # next to 2 s/cell + 45 s work; proposals are eventually-consistent.")
    # The `after` value is the RTI's per-grant horizon under centralized
    # coordination: each federate can be granted time up to
    # min(peer next-event-tags) + after. Too small (1 ms) at large N forces
    # thousands of all-to-all barrier rounds/s and logical time lags real time
    # (claims spiral to seconds at N=16). Tunable via LF_AFTER_MS.
    after_ms = os.environ.get("LF_AFTER_MS", "1")
    all_outputs = ", ".join(f"f{j}.proposal_out" for j in range(1, n + 1))
    for i in range(1, n + 1):
        lines.append(f"  {all_outputs} -> f{i}.proposal_in after {after_ms} msec")
    lines.append("}")
    return "\n".join(lines)


def build_lf(n: int, at_host=None, docker=False) -> str:
    target = TARGET_AND_PREAMBLE
    coord = os.environ.get("LF_COORD", "centralized")   # or "decentralized"
    if coord != "centralized":
        target = target.replace("coordination: centralized,", f"coordination: {coord},")
    if docker:
        # LF native Docker support: lfc generates per-federate Dockerfiles + a
        # docker-compose.yml that runs RTI + federates as services on a shared
        # docker network, addressing each other by service-name DNS.
        target = target.replace(f"  coordination: {coord},",
                                f"  coordination: {coord},\n  docker: true,")
    return "\n".join([target, REACTOR, build_federated_reactor(n, at_host), ""])


def write_lf(n: int, out_path: str, at_host=None, docker=False) -> str:
    content = build_lf(n, at_host, docker)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(content)
    return out_path


def compile_lf(lf_path: str) -> int:
    """Run lfc on the given .lf file (cwd = its directory so fed-gen lands correctly)."""
    lf_dir = os.path.dirname(os.path.abspath(lf_path))
    lfc = os.environ.get("LFC", "lfc")
    print(f"[gen_lf] compiling {lf_path} ...", flush=True)
    return subprocess.call([lfc, "-f", os.path.basename(lf_path)], cwd=lf_dir)


def strip_pyc_from_dockerfiles(n: int) -> int:
    """Patch lfc-generated federate Dockerfiles so the image ships NO bytecode:
    disable .pyc writing + delete any __pycache__ the build left behind. Removes
    the stale-.pyc hazard at the source (a cached `RUN make` layer could otherwise
    bake an old task_registry.cpython-310.pyc), so the federate always compiles the
    current .py -- no runtime PYTHONPYCACHEPREFIX workaround needed."""
    import glob
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pats = [os.path.join(d, "fed-gen", f"coordinator_{n}", "src-gen", "federate__*", "Dockerfile")
            for d in (repo, LF_DIR)]
    inject = ("# strip baked bytecode (avoid stale .pyc from cached build layers)\n"
              "ENV PYTHONDONTWRITEBYTECODE=1\n"
              'RUN find /lingua-franca -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null; true\n')
    patched = 0
    for df in sorted({p for pat in pats for p in glob.glob(pat)}):
        with open(df) as f:
            txt = f.read()
        if "PYTHONDONTWRITEBYTECODE" in txt or "ENTRYPOINT" not in txt:
            continue
        with open(df, "w") as f:
            f.write(txt.replace("ENTRYPOINT", inject + "ENTRYPOINT", 1))
        patched += 1
    return patched


def main():
    ap = argparse.ArgumentParser(description="Generate N-federate LF coordinator programs")
    ap.add_argument("--sizes", default="2,4,8,16",
                    help="comma-separated fleet sizes, e.g. 2,4,8,16")
    ap.add_argument("--outdir", default=LF_DIR, help="directory to write coordinator_<N>.lf")
    ap.add_argument("--out", default=None,
                    help="explicit output path (only valid with a single size)")
    ap.add_argument("--compile", action="store_true", help="also run lfc on each file")
    ap.add_argument("--at-subnet", default=None,
                    help="(legacy) federate i advertises <subnet>.<10+i>; omit normally.")
    ap.add_argument("--docker", action="store_true",
                    help="emit `docker: true` so lfc generates the federated docker-compose "
                         "+ per-federate Dockerfiles (service-DNS addressing on a bridge net)")
    args = ap.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    if args.out and len(sizes) != 1:
        ap.error("--out requires exactly one --sizes value")

    at_host = (lambda i: f"{args.at_subnet}.{10 + i}") if args.at_subnet else None

    rc = 0
    for n in sizes:
        out_path = args.out if args.out else os.path.join(args.outdir, f"coordinator_{n}.lf")
        write_lf(n, out_path, at_host, args.docker)
        print(f"[gen_lf] wrote {out_path} (N={n})")
        if args.compile:
            c = compile_lf(out_path)
            rc |= c
            if c == 0:
                print(f"[gen_lf] stripped baked bytecode from "
                      f"{strip_pyc_from_dockerfiles(n)} federate Dockerfile(s)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
