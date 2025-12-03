# Context-Fabric: Distributed Coordination Architecture

## Overview

Context-Fabric implements a hybrid distributed coordination system for collaborative mobile robots, combining Lingua Franca (LF) federation for strong consistency in the control plane with ROS 2 for eventual consistency in the data plane.

---

## Architecture Components

### 1. Control Plane: LF Federated Coordination

**Purpose:** Task allocation, lease management, resource coordination

**Technology:** Lingua Franca Federation with Runtime Infrastructure (RTI)

**Consistency Model:** **Strong Consistency** (Deterministic)

#### How It Works:

The control plane uses a **Replicated State Machine** pattern where:

1. Each robot runs an **LF Federate** (Fed1, Fed2, etc.)
2. All federates maintain a replica of the Coordinator state
3. Requests (create task, claim task, complete task) are **broadcast** to all federates
4. The **RTI** ensures all federates process events in a deterministic order
5. State remains consistent across all replicas

**Example Flow:**
```
Agent 1 (Robot 1): "Claim Task X"
  ↓
Fed1: Broadcast proposal to all federates (via RTI)
  ↓
Both Fed1 and Fed2: Process proposal deterministically
  ↓
Result: Both have identical state (Task X owned by Agent 1)
```

#### Deterministic Processing Order

**What "Fed1 first, Fed2 second" means:**

This is **NOT** sequential processing or unfair priority. It's a **tie-breaking rule** for concurrent events.

**Scenario:**
```
Fed1 sends: "Agent 1 claims Task X" at logical time T=100
Fed2 sends: "Agent 2 claims Task X" at logical time T=100

Both federates receive BOTH messages at T=100.A
Processing order: Fed1's message first, Fed2's second.

Result:
- Both federates process: "Agent 1 claims X" → Success (owner=1)
- Both federates process: "Agent 2 claims X" → Fails (already owned)
- Final state on BOTH: Task X owned by Agent 1
```

**Important:** 
- If Agent 2 sends first (T=99) and Agent 1 sends later (T=101), **Agent 2 wins** (processed at T=99)
- The "Fed1 first" rule only applies when events happen at the **same** logical time (rare)
- This ensures **deterministic tie-breaking**, not sequential execution

#### Why LF for Control Plane?

1. **Deterministic Ordering:** RTI ensures total order of events across all federates
2. **No Central Server:** Unlike ZooKeeper, no single point of failure
3. **Logical Time:** Events are timestamped and processed in order, regardless of network delays
4. **Strong Consistency:** All replicas converge to the same state without complex consensus algorithms

---

### 2. Data Plane: ROS 2 DDS + DSM Gossip

**Purpose:** Sensor data sharing, environment state, cache synchronization

**Technology:** ROS 2 DDS (topics/messages) + Distributed Shared Memory (DSM) with CRDTs

**Consistency Model:** **Eventual Consistency**

#### DSM (Distributed Shared Memory) Node

Each robot runs a **DSM Node** that:

- Maintains a **local cache** of shared data (CRDTs for jam signals, flow traces, etc.)
- Periodically broadcasts updates via **gossip** (ROS 2 topics: `/dsm_gossip`)
- Merges incoming gossip from other robots using CRDT merge logic
- Provides **eventual consistency** for sensor data, environment state

**Why Eventual Consistency for Data Plane?**

- Sensor data updates don't need strict ordering
- Gossip + CRDTs handle conflicts naturally
- It's acceptable if Robot1 and Robot2 have slightly different views of jam signals for a few milliseconds
- **Performance:** No need to wait for coordination overhead for every sensor update

**Key Distinction:**
- **Control Plane (LF):** Strong consistency for tasks/leases (who owns what)
- **Data Plane (DSM):** Eventual consistency for sensor data (what the environment looks like)

---

### 3. Bridge: ROS ↔ LF Translation Layer

**Purpose:** Translate between ROS 2 services (used by agents) and LF reactors (used by coordination)

**Technology:** TCP Sockets + ROS 2 Services

#### Architecture:

```
┌─────────────┐                           ┌──────────────┐
│ Agent Node  │ ──ROS Service Call──────> │  LF Bridge   │
│ (Robot 1)   │                           │    Node      │
└─────────────┘                           └──────────────┘
                                                 │
                                                 │ TCP Socket
                                                 │ (port 9001)
                                                 ▼
                                          ┌──────────────┐
                                          │ LF Federate  │
                                          │   (Fed1)     │
                                          └──────────────┘
                                                 │
                                                 │ RTI Network
                                                 │
                                          ┌──────────────┐
                                          │ LF Federate  │
                                          │   (Fed2)     │
                                          └──────────────┘
```

#### Step-by-Step Flow:

1. **Agent** calls ROS service: `/coord/claim_task`
2. **Bridge Node** (Python ROS node) receives the service call
3. Bridge sends JSON over **TCP socket** to local LF Federate: 
   ```json
   {"type": "claim", "task_id": 0, "agent_id": 1}
   ```
4. **LF Federate** (Python LF reactor) schedules a physical action
5. LF reaction **broadcasts** the proposal to all federates via RTI
6. All federates **process** the proposal deterministically
7. Originating federate sends **response** back to Bridge via socket
8. Bridge returns **ROS service response** to Agent

#### Why We Need the Bridge:

- **Agents** are ROS nodes (use ROS services/topics)
- **LF Federates** are LF reactors (use logical time, RTI network)
- **Bridge** translates between the two worlds

**Alternative (without bridge):**
- We could make Agent nodes directly use LF's Python API
- But then they wouldn't be "normal ROS nodes" anymore
- The bridge keeps the ROS ecosystem intact while using LF for coordination

---

## Complete System Architecture

### Component Summary

| Component | Purpose | Technology | Consistency |
|-----------|---------|-----------|-------------|
| **Control Plane** | Task allocation, leases | LF Federation (RTI) | **Strong** (deterministic) |
| **Data Plane** | Sensor data, environment state | ROS 2 DDS + DSM Gossip | **Eventual** (CRDTs) |
| **Bridge** | Translate ROS ↔ LF | TCP Sockets + ROS Services | N/A (just translation) |
| **Agent Node** | Robot logic, task execution | ROS 2 Node (Python) | N/A (stateless) |
| **RTI** | Logical time coordination | LF Runtime Infrastructure | N/A (infrastructure) |

### Per-Robot Components (Each Jetson/Robot):

```
Robot 1:
├── LF Coordinator Federate 1 (Control Plane)
├── LF Bridge Node (ROS ↔ LF translator)
├── DSM Node (Data Plane cache + gossip)
└── Agent Node (Robot behavior/logic)

Robot 2:
├── LF Coordinator Federate 2 (Control Plane)
├── LF Bridge Node (ROS ↔ LF translator)
├── DSM Node (Data Plane cache + gossip)
└── Agent Node (Robot behavior/logic)

Central (x86 Station):
└── RTI (Runtime Infrastructure for LF coordination)
```

---

## Comparison to Related Work

### vs. ZooKeeper

| Feature | ZooKeeper | Context-Fabric (LF) |
|---------|-----------|---------------------|
| Architecture | Centralized (leader + followers) | Fully distributed (federated) |
| Single Point of Failure | Yes (leader) | No (replicated state) |
| Consistency | Strong (Paxos/Raft) | Strong (Deterministic ordering) |
| Determinism | No | **Yes** (logical time) |
| Real-time | No | **Yes** (bounded latency) |

### vs. HPRM (High-Performance Robotic Middleware)

| Feature | HPRM | Context-Fabric |
|---------|------|----------------|
| LF Usage | **Full replacement** of ROS 2 DDS | **Hybrid:** LF for control, ROS 2 for data |
| Goal | **Performance** (low latency) | **Consistency** (deterministic coordination) |
| Data Plane | LF reactors (zero-copy) | ROS 2 DDS (standard ecosystem) |
| Control Plane | LF reactors | **LF Federation** (replicated state machine) |
| Compatibility | Requires rewriting ROS nodes | **Keeps existing ROS nodes** |

**Our Contribution:**
- Use LF's federation capabilities for **distributed coordination** (not just performance)
- Hybrid approach: Strong consistency where needed (control), eventual consistency where acceptable (data)
- Maintain ROS 2 ecosystem compatibility

---

## Experimental Validation

### Test Results

**Setup:**
- 2 Robots (Docker containers on x86, deployable to Jetson)
- LF RTI on x86 station
- Each robot: 1 LF Federate + 1 Bridge + 1 DSM + 1 Agent

**Test 1: Task Creation**
1. Created task 0 on Robot 1 (via ROS service)
2. **Result:** Both Fed1 and Fed2 saw the task in their replicated state ✅

**Test 2: Consistent Queries**
1. Query `/coord/get_available_tasks` on Robot 1
2. Query `/coord/get_available_tasks` on Robot 2
3. **Result:** Both returned identical task list ✅

**Test 3: Task Claim**
1. Agent 1 claimed task 0
2. **Logs showed:**
   - Fed1 broadcast proposal `1_2`
   - Fed2 received and processed proposal `1_2`
   - Both processed in deterministic order
3. **Result:** Both federates show task 0 as claimed (not available) ✅

**Conclusion:** Distributed LF coordination working correctly with strong consistency across replicas.

---

## Key Insights

1. **LF Federation provides ZooKeeper-like consistency without centralization**
   - Replicated State Machine pattern
   - Deterministic ordering via RTI
   - No single point of failure

2. **Hybrid architecture balances consistency and performance**
   - Control plane: Strong consistency (LF)
   - Data plane: Eventual consistency (ROS 2 + DSM)
   - Each gets the right consistency model for its requirements

3. **Bridge pattern maintains ROS ecosystem compatibility**
   - Agents remain standard ROS nodes
   - LF coordination happens transparently
   - Easy to integrate with existing ROS packages

4. **Deterministic tie-breaking ≠ Sequential execution**
   - Events still happen concurrently
   - Order is enforced only when necessary (same logical time)
   - Fairness is maintained (earliest timestamp wins)

---

## Future Work

2. **Performance Benchmarking:** Compare latency vs. ZooKeeper
3. **Fault Tolerance:** Test federate crash/recovery
4. **Scale Testing:** 3+ robots, larger task sets
5. **DSM Integration:** Connect DSM updates to LF coordination for consistency guarantees

