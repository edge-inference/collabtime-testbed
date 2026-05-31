# Context-Fabric testbed: emulated N-robot results

Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task stream, robot policy (state machine). Values are mean ± sd over 3 seeds.

| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | T_claim mean (ms) | AoI mean (ms) |
|---|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15 | 134 ± 57 | 0.38 ± 0.10 | 25.8 ± 0.7 | 20.8 ± 0.2 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 97 ± 18 | 131 ± 41 | 0.35 ± 0.06 | 27.4 ± 0.8 | 21.0 ± 0.1 |
| 8 | 0.97 ± 0.05 | 0.055 ± 0.008 | 82 ± 8 | 108 ± 22 | 0.32 ± 0.05 | 28.4 ± 0.7 | 21.2 ± 0.1 |
