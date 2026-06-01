# Context-Fabric testbed results

Quantitative validation of the federated coordination architecture, emulating **one Lingua Franca federate per robot** in Docker. Tasks arrive as a Poisson stream; the robot **policy is a state machine**. Values below are **mean ± sd over 3 seeds** (1, 7, 42).

## Metric definitions (match the thesis simulation)
- **Completion rate** = completed / created   - **Throughput** = completed / wall-second
- **Latency** = create->complete (avg/P50/P90/P99 s)   - **Utilization** = per-robot %WORKING, fleet-avg
- **T_claim** = ROS->LF->RTI claim round-trip (ms)   - **AoI** = data-plane gossip staleness (ms)

## Results

| N | Completion | Throughput | Avg/P90 lat (s) | Util | T_claim (ms) | AoI (ms) |
|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 14/137 ± 53 | 0.37 ± 0.11 | 4.4 ± 0.6 | 1.0 ± 0.1 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 98 ± 18/146 ± 50 | 0.34 ± 0.06 | 4.6 ± 0.6 | 1.3 ± 0.2 |
| 8 | 1.00 | 0.057 ± 0.010 | 84 ± 8/104 ± 13 | 0.33 ± 0.06 | 8.6 ± 3.0 | 2.1 ± 0.1 |
| 16 | 0.99 ± 0.03 | 0.102 ± 0.025 | 86 ± 8/115 ± 16 | 0.30 ± 0.07 | 8.6 ± 0.9 | 3.6 ± 0.3 |

## What the data shows
- **Coordination stays cheap through N=16**: completion 99%, claim overhead 4.4->8.6 ms, AoI <= 3.6 ms (<< 300 ms gossip period) -- all far below the ~75 s task service time.
- **Latency bounded** in this range (avg 84-98 s); throughput grows with the fleet.

## Artifacts
- `results/testbed_metrics.csv` (per-seed) and `results/testbed_metrics_agg.csv` (per-N mean/sd)
- `results/testbed_table.md` / `.tex` (drop-in tables)
- `figures/testbed/metrics_vs_n.*`, `claim_overhead_vs_n.*`, `aoi_distribution.*`
- `figures/testbed/architecture_*.{png,svg,pdf}` (architecture diagrams)
