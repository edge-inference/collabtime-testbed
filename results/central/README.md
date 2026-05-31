# Context-Fabric testbed results

Quantitative validation of the federated coordination architecture, emulating **one Lingua Franca federate per robot** in Docker. Tasks arrive as a Poisson stream; the robot **policy is a state machine**. Values below are **mean ± sd over 3 seeds** (1, 7, 42).

## Metric definitions (match the thesis simulation)
- **Completion rate** = completed / created   - **Throughput** = completed / wall-second
- **Latency** = create->complete (avg/P50/P90/P99 s)   - **Utilization** = per-robot %WORKING, fleet-avg
- **T_claim** = ROS->LF->RTI claim round-trip (ms)   - **AoI** = data-plane gossip staleness (ms)

## Results

| N | Completion | Throughput | Avg/P90 lat (s) | Util | T_claim (ms) | AoI (ms) |
|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15/137 ± 53 | 0.37 ± 0.11 | 5.3 ± 1.0 | 0.9 ± 0.1 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 96 ± 18/147 ± 53 | 0.35 ± 0.06 | 6.1 ± 1.5 | 1.1 ± 0.2 |
| 8 | 1.00 | 0.057 ± 0.010 | 86 ± 2/108 ± 7 | 0.32 ± 0.06 | 4.4 ± 0.4 | 1.7 ± 0.1 |
| 16 | 1.00 | 0.103 ± 0.024 | 81 ± 2/104 ± 3 | 0.29 ± 0.07 | 4.9 ± 0.5 | 3.5 ± 0.1 |

## What the data shows
- **Coordination stays cheap through N=16**: completion 100%, claim overhead 5.3->4.9 ms, AoI <= 3.5 ms (<< 300 ms gossip period) -- all far below the ~75 s task service time.
- **Latency bounded** in this range (avg 81-97 s); throughput grows with the fleet.

## Artifacts
- `results/testbed_metrics.csv` (per-seed) and `results/testbed_metrics_agg.csv` (per-N mean/sd)
- `results/testbed_table.md` / `.tex` (drop-in tables)
- `figures/testbed/metrics_vs_n.*`, `claim_overhead_vs_n.*`, `aoi_distribution.*`
- `figures/testbed/architecture_*.{png,svg,pdf}` (architecture diagrams)
