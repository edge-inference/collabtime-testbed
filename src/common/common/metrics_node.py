"""
Central metrics aggregator for the Context-Fabric testbed.

Subscribes to the system topics (agent_state, dsm_gossip, task_events) and
computes the four thesis metrics with the *same definitions* as the warehouse
simulation, so testbed numbers are interpretable on the same scale:

  * completion_rate = tasks_completed / tasks_created
  * throughput_tps  = tasks_completed / elapsed_wall_seconds
  * latency         = create -> complete time (avg / p50 / p90 / p99), seconds
  * utilization     = per-agent fraction of time in the WORKING state,
                      averaged over the fleet

It writes two artifacts into the logs dir (mounted to the host):
  * summary_<config>_seed<seed>.json   - final metrics (overwritten each tick,
                                          so it survives even a SIGKILL)
  * timeseries_<config>_seed<seed>.csv - per-second time series (for figures)

Run identity comes from environment variables set by gen_compose.py:
  TESTBED_NUM_ROBOTS, TESTBED_SEED, TESTBED_MODE, TESTBED_CONFIG_NAME,
  TESTBED_LOGS_DIR (default /ros2_ws/logs).
"""

import csv
import json
import os
import time

import numpy as np
import rclpy
from rclpy.node import Node

from interfaces.msg import AgentState, DSMUpdate, TaskEvent

WORKING_STATE = "WORKING"


def _pct(samples, q):
    return float(np.percentile(samples, q)) if samples else 0.0


class MetricsNode(Node):
    def __init__(self):
        super().__init__("metrics_node")

        # --- run identity (from gen_compose env) ---------------------------
        self.num_robots = int(os.environ.get("TESTBED_NUM_ROBOTS", "0"))
        self.seed = int(os.environ.get("TESTBED_SEED", "0"))
        self.mode = os.environ.get("TESTBED_MODE", "lf")
        self.config_name = os.environ.get(
            "TESTBED_CONFIG_NAME", f"{self.mode}_{self.num_robots}robots"
        )
        self.logs_dir = os.environ.get("TESTBED_LOGS_DIR", "/ros2_ws/logs")
        os.makedirs(self.logs_dir, exist_ok=True)

        # --- subscriptions -------------------------------------------------
        self.create_subscription(AgentState, "agent_state", self.handle_agent_state, 10)
        self.create_subscription(DSMUpdate, "dsm_gossip", self.handle_dsm_gossip, 10)
        self.create_subscription(TaskEvent, "task_events", self.handle_task_event, 10)

        # --- state ---------------------------------------------------------
        # agents: id -> {state, node, task, last_seen}
        self.agents = {}
        # per-agent utilization counters (sampled at report cadence)
        self.util_total = {}     # id -> sample count
        self.util_working = {}   # id -> WORKING sample count
        # tasks: id -> {created_ms, claimed_ms, completed_ms, status}
        self.tasks = {}
        self.tasks_created = 0
        self.tasks_completed = 0
        self.tasks_failed = 0
        # create->complete and claim->complete latency samples (seconds)
        self.lat_create = []
        self.lat_claim = []
        # gossip volume
        self.gossip_count = 0
        self.gossip_bytes = 0

        self.start_time = time.time()

        # --- outputs -------------------------------------------------------
        self.summary_path = os.path.join(
            self.logs_dir, f"summary_{self.config_name}_seed{self.seed}.json"
        )
        self.ts_path = os.path.join(
            self.logs_dir, f"timeseries_{self.config_name}_seed{self.seed}.csv"
        )
        self.ts_file = open(self.ts_path, "w", newline="")
        self.ts_writer = csv.writer(self.ts_file)
        self.ts_writer.writerow(
            ["elapsed_s", "created", "completed", "failed",
             "completion_rate", "throughput_tps", "avg_latency_s",
             "p90_latency_s", "agent_utilization", "active_agents", "gossip_msgs"]
        )

        self.create_timer(1.0, self.tick)
        self.get_logger().info(
            f"Metrics node started: config={self.config_name} N={self.num_robots} "
            f"seed={self.seed} -> {self.summary_path}"
        )

    # ---- subscribers ------------------------------------------------------
    def handle_agent_state(self, msg):
        self.agents[msg.agent_id] = {
            "state": msg.state,
            "node": msg.current_node,
            "task": msg.active_task_id,
            "last_seen": time.time(),
        }

    def handle_dsm_gossip(self, msg):
        self.gossip_count += 1
        self.gossip_bytes += 20 + len(msg.node_ids) * 4 + len(msg.values) * 8 + len(msg.timestamps) * 8

    def handle_task_event(self, msg):
        tid = msg.task_id
        entry = self.tasks.setdefault(tid, {})
        if msg.event_type == "CREATED":
            if "created_ms" not in entry:
                entry["created_ms"] = msg.timestamp_ms
                self.tasks_created += 1
            entry["status"] = "AVAILABLE"
        elif msg.event_type == "CLAIMED":
            entry["claimed_ms"] = msg.timestamp_ms
            entry["status"] = "CLAIMED"
        elif msg.event_type == "COMPLETED":
            entry["completed_ms"] = msg.timestamp_ms
            entry["status"] = "COMPLETED"
            self.tasks_completed += 1
            if "created_ms" in entry:
                self.lat_create.append((msg.timestamp_ms - entry["created_ms"]) / 1000.0)
            if "claimed_ms" in entry:
                self.lat_claim.append((msg.timestamp_ms - entry["claimed_ms"]) / 1000.0)
        elif msg.event_type == "FAILED":
            entry["status"] = "FAILED"
            self.tasks_failed += 1

    # ---- periodic compute + persist --------------------------------------
    def _sample_utilization(self):
        for aid, data in self.agents.items():
            self.util_total[aid] = self.util_total.get(aid, 0) + 1
            if data["state"] == WORKING_STATE:
                self.util_working[aid] = self.util_working.get(aid, 0) + 1

    def _fleet_utilization(self):
        per_agent = [
            self.util_working.get(aid, 0) / self.util_total[aid]
            for aid in self.util_total if self.util_total[aid] > 0
        ]
        return (float(np.mean(per_agent)) if per_agent else 0.0), per_agent

    def compute_summary(self):
        elapsed = max(time.time() - self.start_time, 1e-9)
        completion_rate = (self.tasks_completed / self.tasks_created) if self.tasks_created else 0.0
        throughput = self.tasks_completed / elapsed
        util, per_agent = self._fleet_utilization()
        active = len([a for a in self.agents.values() if time.time() - a["last_seen"] < 5])
        return {
            "config_name": self.config_name,
            "mode": self.mode,
            "num_robots": self.num_robots,
            "seed": self.seed,
            "elapsed_s": round(elapsed, 1),
            "tasks_created": self.tasks_created,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "completion_rate": round(completion_rate, 4),
            "throughput_tps": round(throughput, 4),
            "avg_latency_s": round(float(np.mean(self.lat_create)), 2) if self.lat_create else 0.0,
            "p50_latency_s": round(_pct(self.lat_create, 50), 2),
            "p90_latency_s": round(_pct(self.lat_create, 90), 2),
            "p99_latency_s": round(_pct(self.lat_create, 99), 2),
            "avg_claim_to_complete_s": round(float(np.mean(self.lat_claim)), 2) if self.lat_claim else 0.0,
            "agent_utilization": round(util, 4),
            "active_agents": active,
            "gossip_msgs": self.gossip_count,
            "gossip_kb": round(self.gossip_bytes / 1024.0, 1),
            "latency_samples": len(self.lat_create),
        }

    def tick(self):
        self._sample_utilization()
        s = self.compute_summary()

        # Persist summary (atomic overwrite so a SIGKILL still leaves a valid file).
        tmp = self.summary_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, self.summary_path)

        # Append time-series row.
        self.ts_writer.writerow([
            s["elapsed_s"], s["tasks_created"], s["tasks_completed"], s["tasks_failed"],
            s["completion_rate"], s["throughput_tps"], s["avg_latency_s"],
            s["p90_latency_s"], s["agent_utilization"], s["active_agents"], s["gossip_msgs"],
        ])
        self.ts_file.flush()

        # Console snapshot.
        self.get_logger().info(
            f"[{s['elapsed_s']:.0f}s] N={s['num_robots']} active={s['active_agents']} | "
            f"created={s['tasks_created']} done={s['tasks_completed']} fail={s['tasks_failed']} "
            f"| compl={s['completion_rate']:.2f} thru={s['throughput_tps']:.3f}/s "
            f"lat(avg/p90)={s['avg_latency_s']:.0f}/{s['p90_latency_s']:.0f}s util={s['agent_utilization']:.2f}"
        )


def main(args=None):
    rclpy.init(args=args)
    node = MetricsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.ts_file.close()
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
