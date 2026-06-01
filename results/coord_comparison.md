# Distributed arm: centralized-RTI vs decentralized LF coordination

Same federation (one coordinator replica per robot, all-to-all proposal mesh, gossip); only the LF coordination mode differs. Mean ± sd across seeds.

| N | coordination | Completion | Throughput (tasks/min) | T_claim (ms) | Util |
|---|---|---|---|---|---|
| 2 | centralized RTI | 0.78 ± 0.19 | 0.92 ± 0.19 | 4.7 ± 1.2 | 0.37 ± 0.11 |
| 2 | decentralized | 0.78 ± 0.19 | 0.92 ± 0.19 | 4.4 ± 0.6 | 0.37 ± 0.11 |
| 4 | centralized RTI | 0.97 ± 0.05 | 1.78 ± 0.32 | 4.7 ± 0.4 | 0.35 ± 0.06 |
| 4 | decentralized | 0.97 ± 0.05 | 1.79 ± 0.33 | 4.6 ± 0.6 | 0.34 ± 0.06 |
| 8 | centralized RTI | 0.98 ± 0.03 | 3.35 ± 0.57 | 6.8 ± 0.4 | 0.32 ± 0.06 |
| 8 | decentralized | 1.00 | 3.41 ± 0.59 | 8.6 ± 3.0 | 0.33 ± 0.06 |
| 16 | centralized RTI | 0.30 ± 0.17 | 0.89 ± 0.58 | 7130.1 ± 113.4 | 0.09 ± 0.02 |
| 16 | decentralized | 0.99 ± 0.03 | 6.11 ± 1.51 | 8.6 ± 0.9 | 0.30 ± 0.07 |

## What it shows
- Identical federation; the only change is `coordination: centralized` -> `decentralized` (federates advance on their own clock via an `STP_offset` and exchange proposals peer-to-peer; the RTI only does startup/clock-sync).
- **At N=16, centralized RTI collapses** (completion 30%, T_claim 7130 ms): every federate's tag advance is gated by an all-to-all barrier the single RTI cannot keep up with. **Decentralized scales clean** (completion 99%, T_claim 8.6 ms, RTI idle).
- So the N=16 "frontier" was a property of the **centralized coordination mode**, not of the distributed architecture: peer-to-peer coordination removes it and the distributed Context-Fabric scales to N=16.
