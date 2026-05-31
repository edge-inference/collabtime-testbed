# Context-Fabric testbed: emulated N-robot results

Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task stream, robot policy (state machine). Values are mean ± sd over 3 seeds.

| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | T_claim mean (ms) | AoI mean (ms) |
|---|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15 | 137 ± 53 | 0.37 ± 0.11 | 5.3 ± 1.0 | 0.9 ± 0.1 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 96 ± 18 | 147 ± 53 | 0.35 ± 0.06 | 6.1 ± 1.5 | 1.1 ± 0.2 |
| 8 | 1.00 | 0.057 ± 0.010 | 86 ± 2 | 108 ± 7 | 0.32 ± 0.06 | 4.4 ± 0.4 | 1.7 ± 0.1 |
| 16 | 1.00 | 0.103 ± 0.024 | 81 ± 2 | 104 ± 3 | 0.29 ± 0.07 | 4.9 ± 0.5 | 3.5 ± 0.1 |
