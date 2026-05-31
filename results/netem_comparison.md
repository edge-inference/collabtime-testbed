# Context-Fabric testbed: baseline vs netem (20 ms)

Same emulation, two link conditions: **baseline** (Docker bridge, no added delay) and **netem** (`tc qdisc ... netem delay 20ms 5ms` on each robot container's `eth0`, i.e. egress impairment on the robot uplink). Values are mean ± sd across seeds.

## Per-N, both conditions

| N | cond | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Util | T_claim (ms) | AoI (ms) |
|---|---|---|---|---|---|---|---|---|
| 2 | baseline | 0.78 ± 0.19 | 0.015 ± 0.003 | 98 ± 14 | 138 ± 53 | 0.37 ± 0.11 | 4.7 ± 1.2 | 1.0 ± 0.2 |
| 2 | netem20 | 0.78 ± 0.19 | 0.015 ± 0.003 | 97 ± 15 | 134 ± 57 | 0.38 ± 0.10 | 25.8 ± 0.7 | 20.8 ± 0.2 |
| 4 | baseline | 0.97 ± 0.05 | 0.030 ± 0.005 | 93 ± 17 | 129 ± 38 | 0.35 ± 0.06 | 4.7 ± 0.4 | 1.2 ± 0.2 |
| 4 | netem20 | 0.97 ± 0.05 | 0.030 ± 0.005 | 97 ± 18 | 131 ± 41 | 0.35 ± 0.06 | 27.4 ± 0.8 | 21.0 ± 0.1 |
| 8 | baseline | 0.98 ± 0.03 | 0.056 ± 0.009 | 85 ± 8 | 103 ± 13 | 0.32 ± 0.06 | 6.8 ± 0.4 | 1.9 ± 0.2 |
| 8 | netem20 | 0.97 ± 0.05 | 0.055 ± 0.008 | 82 ± 8 | 108 ± 22 | 0.32 ± 0.05 | 28.4 ± 0.7 | 21.2 ± 0.1 |

## Network effect (netem − baseline)

| N | Δ T_claim (ms) | Δ AoI (ms) | Δ Avg lat (s) | Δ Completion | Δ Util |
|---|---|---|---|---|---|
| 2 | +21.1 | +19.8 | -1.1 | +0.00 | +0.01 |
| 4 | +22.6 | +19.9 | +3.6 | +0.00 | -0.00 |
| 8 | +21.6 | +19.4 | -2.8 | -0.01 | -0.00 |

## What it shows
- **Coordination overhead rises with the link**: T_claim +21.1 to +22.6 ms, AoI +19.4 to +19.9 ms under 20 ms egress delay — the round-trip crosses the impaired uplink several times, so the increase is a small multiple of the one-way delay.
- **Service metrics stay flat**: completion changes by at most 0.01; the 20 ms link is negligible next to the ~75 s task service time, so throughput/latency/utilization are unaffected.
- **Conclusion**: the measured overhead is network-bound (it tracks the link, not the fleet's work), confirming the Ch.3 model that coordination cost is communication-dominated rather than a throughput bottleneck at these N.
