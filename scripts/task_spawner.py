#!/usr/bin/env python3
"""
Poisson task generator for the Context-Fabric testbed.

Reproduces the simulation's central task stream: tasks arrive as a Poisson
process at rate ``lambda`` (tasks/sec) and are created at random ``work`` nodes
via the LF control plane (``/robot_<id>/coord/create_task``). All robots then
pull/claim from the replicated registry.

Runs inside the metrics container (has rclpy + interfaces + the graph mount):
    python3 task_spawner.py --rate 0.19 --duration 300 --seed 42

``run_sweep.sh`` computes ``--rate`` = arrival_rate_per_robot * N.
"""

import argparse
import random
import time

import yaml
import rclpy
from rclpy.node import Node

from interfaces.srv import CreateTask


def load_work_nodes(graph_path: str):
    with open(graph_path) as f:
        g = yaml.safe_load(f)
    return [int(nid) for nid, m in g["nodes"].items() if m.get("type") == "work"]


def main():
    ap = argparse.ArgumentParser(description="Poisson task spawner")
    ap.add_argument("--rate", type=float, required=True, help="lambda, tasks/sec")
    ap.add_argument("--duration", type=float, required=True, help="seconds to spawn for")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--graph", default="/ros2_ws/config/warehouse_graph.yaml")
    ap.add_argument("--service", default="/robot_1/coord/create_task")
    ap.add_argument("--task-type", default="pick")
    ap.add_argument("--priority", type=float, default=1.0)
    args = ap.parse_args()

    work_nodes = load_work_nodes(args.graph)
    if not work_nodes:
        raise SystemExit(f"No 'work' nodes found in {args.graph}")
    rng = random.Random(args.seed)

    rclpy.init()
    node = rclpy.create_node("task_spawner")
    cli = node.create_client(CreateTask, args.service)
    node.get_logger().info(f"Waiting for {args.service} ...")
    if not cli.wait_for_service(timeout_sec=60.0):
        node.get_logger().error(f"Service {args.service} unavailable; aborting.")
        rclpy.shutdown()
        raise SystemExit(1)

    node.get_logger().info(
        f"Spawning tasks: lambda={args.rate}/s for {args.duration}s, seed={args.seed}, "
        f"{len(work_nodes)} work nodes"
    )

    t_end = time.time() + args.duration
    created = 0
    pending = []
    while time.time() < t_end:
        # Poisson inter-arrival; keep spinning so async responses resolve.
        wake = min(time.time() + rng.expovariate(args.rate), t_end)
        while time.time() < wake:
            rclpy.spin_once(node, timeout_sec=0.05)
        if time.time() >= t_end:
            break
        req = CreateTask.Request()
        req.location = int(rng.choice(work_nodes))
        req.task_type = args.task_type
        req.priority = float(args.priority)
        pending.append(cli.call_async(req))
        created += 1
        # Drain resolved futures occasionally to avoid unbounded growth.
        if len(pending) > 50:
            pending = [f for f in pending if not f.done()]

    node.get_logger().info(f"Spawn window over: created {created} tasks.")
    # Give a moment for the last creates to be acknowledged.
    drain_end = time.time() + 3.0
    while time.time() < drain_end:
        rclpy.spin_once(node, timeout_sec=0.05)

    node.destroy_node()
    rclpy.shutdown()
    print(f"[task_spawner] created {created} tasks at lambda={args.rate}/s")


if __name__ == "__main__":
    main()
