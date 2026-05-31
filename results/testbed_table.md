# Context-Fabric testbed: emulated N-robot results

Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task stream, robot policy (state machine). Values are mean ± sd over 3 seeds.

| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | T_claim mean (ms) | AoI mean (ms) |
|---|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 98 ± 14 | 138 ± 53 | 0.37 ± 0.11 | 4.7 ± 1.2 | 1.0 ± 0.2 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 93 ± 17 | 129 ± 38 | 0.35 ± 0.06 | 4.7 ± 0.4 | 1.2 ± 0.2 |
| 8 | 0.98 ± 0.03 | 0.056 ± 0.010 | 85 ± 8 | 103 ± 13 | 0.32 ± 0.06 | 6.8 ± 0.4 | 1.9 ± 0.2 |
| 16 | 0.23 ± 0.18 | 0.011 ± 0.010 | 71 ± 2 | 79 ± 12 | 0.08 ± 0.02 | 6733.3 ± 691.9 | 3.0 ± 0.3 |
