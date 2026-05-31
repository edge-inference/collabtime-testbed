# Context-Fabric testbed results

Quantitative validation of the federated coordination architecture, emulating **one Lingua Franca federate per robot** in Docker. Tasks arrive as a Poisson stream; the robot **policy is a state machine**. Values below are **mean ± sd over 3 seeds** (1, 7, 42).

## Metric definitions (match the thesis simulation)
- **Completion rate** = completed / created   - **Throughput** = completed / wall-second
- **Latency** = create->complete (avg/P50/P90/P99 s)   - **Utilization** = per-robot %WORKING, fleet-avg
- **T_claim** = ROS->LF->RTI claim round-trip (ms)   - **AoI** = data-plane gossip staleness (ms)

## Results

| N | Completion | Throughput | Avg/P90 lat (s) | Util | T_claim (ms) | AoI (ms) |
|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15/134 ± 57 | 0.38 ± 0.10 | 25.8 ± 0.7 | 20.8 ± 0.2 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 97 ± 18/131 ± 41 | 0.35 ± 0.06 | 27.4 ± 0.8 | 21.0 ± 0.1 |
| 8 | 0.97 ± 0.05 | 0.055 ± 0.008 | 82 ± 8/108 ± 22 | 0.32 ± 0.05 | 28.4 ± 0.7 | 21.2 ± 0.1 |

## What the data shows
- **Coordination stays cheap through N=8**: completion 97%, claim overhead 25.8->28.4 ms, AoI <= 21.2 ms (<< 300 ms gossip period) -- all far below the ~75 s task service time.
- **Latency bounded** in this range (avg 82-97 s); throughput grows with the fleet.

## Artifacts
- `results/testbed_metrics.csv` (per-seed) and `results/testbed_metrics_agg.csv` (per-N mean/sd)
- `results/testbed_table.md` / `.tex` (drop-in tables)
- `figures/testbed/metrics_vs_n.*`, `claim_overhead_vs_n.*`, `aoi_distribution.*`
- `figures/testbed/architecture_*.{png,svg,pdf}` (architecture diagrams)
