# Context-Fabric testbed: emulated N-robot results

Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task stream, robot policy (state machine). Values are mean ± sd over 3 seeds.

| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | T_claim mean (ms) | AoI mean (ms) |
|---|---|---|---|---|---|---|---|
| 2 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15 | 137 ± 53 | 0.37 ± 0.10 | 4.5 ± 1.0 | 0.0 |
| 4 | 0.97 ± 0.05 | 0.030 ± 0.005 | 97 ± 16 | 148 ± 52 | 0.35 ± 0.06 | 5.6 ± 1.1 | 0.0 |
| 8 | 1.00 | 0.057 ± 0.010 | 82 ± 3 | 101 ± 8 | 0.32 ± 0.05 | 4.4 ± 0.8 | 0.0 |
