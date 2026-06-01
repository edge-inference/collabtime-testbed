# Context-Fabric testbed: emulated N-robot results

Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task stream, robot policy (state machine). Values are mean ± sd over 3 seeds.

| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | T_claim mean (ms) | AoI mean (ms) |
|---|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 14 | 137 ± 53 | 0.37 ± 0.11 | 4.4 ± 0.6 | 1.0 ± 0.1 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 98 ± 18 | 146 ± 50 | 0.34 ± 0.06 | 4.6 ± 0.6 | 1.3 ± 0.2 |
| 8 | 1.00 | 0.057 ± 0.010 | 84 ± 8 | 104 ± 13 | 0.33 ± 0.06 | 8.6 ± 3.0 | 2.1 ± 0.1 |
| 16 | 0.99 ± 0.03 | 0.102 ± 0.025 | 86 ± 8 | 115 ± 16 | 0.30 ± 0.07 | 8.6 ± 0.9 | 3.6 ± 0.3 |
