# Context-Fabric Pinned Memory Subsystem

Hardware-aware distributed shared memory for VLA-driven robots on Jetson.

---

## Research Methodology

1. Define the schema (what context is)
2. Map it to memory layout (struct-of-arrays, pinned)
3. Measure the baseline (Tegra DRAM + caches)
4. Show the bottleneck (interference with VLA inference)
5. Propose hardware specialization (scratchpad, fast delta path)

---

## 1. The Core Problem: Cache Contention

**VLA inference and Context Memory fight for the same cache.**

When a VLA runs on Jetson:
- Model weights (hundreds of MB) flood L2
- KV cache (for attention) floods L2
- Your tiny 8MB context tables get evicted constantly

Every time the "selector" (code that assembles context for VLA) runs, it suffers cache misses because the VLA just blew away all context data.

**Measurable:** Use `perf` on Jetson to show L2 miss rates spike during inference.

**Hardware argument:** A small, QoS-protected scratchpad (even 1-2MB) that the VLA cannot evict would stabilize context access latency.

---

## 2. Current State: Python Software Memory

```
dsm_node.py (Python)

  self.flow_traces = {}      <-- Python dict (heap)
  self.jam_signals = {}      <-- Python dict (heap)
  self.agent_locations = {}  <-- Python dict (heap)

  - Lives in Python's managed heap
  - Subject to GC pauses
  - Competes with everything else for cache
```

**Problems:**
- Python dicts are scattered in heap memory (pointer chasing)
- No control over cache residency
- GC can pause DSM at bad times
- When VLA inference runs, this data gets evicted from L2

---

## 3. Target State: Pinned Context Memory

```
context_memory.cpp (C++)

  PINNED MEMORY BLOCK (mmap + mlock)
  Base: 0x7f8000000000
  Size: 8 MB

    robots.x[64], robots.y[64], ...
    tasks.id[256], tasks.status[256], ...
    regions.jam_signal[128], ...
    delta_ring[64KB]

  - Contiguous, cache-friendly layout
  - Pinned: never swapped out
  - Known address: can share with eBPF, GPU
```

---

## 4. C++ Implementation

### Header (`context_memory.h`)

```cpp
#pragma once
#include <cstdint>
#include <cstddef>

namespace ctx {

void init(size_t size_bytes = 8 * 1024 * 1024);
void* alloc(size_t size, size_t align = 64);
void* base();
size_t capacity();
void reset();

} // namespace ctx
```

### Implementation (`context_memory.cpp`)

```cpp
#include "context_memory.h"
#include <sys/mman.h>
#include <cstdlib>
#include <cstdio>

namespace ctx {

static void*  g_base = nullptr;
static size_t g_size = 0;
static size_t g_offset = 0;

void init(size_t size_bytes) {
    g_base = mmap(nullptr, size_bytes,
                  PROT_READ | PROT_WRITE,
                  MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE,
                  -1, 0);
    if (g_base == MAP_FAILED) {
        perror("ctx::init mmap");
        std::abort();
    }
    if (mlock(g_base, size_bytes) != 0) {
        perror("ctx::init mlock (continuing anyway)");
    }
    g_size = size_bytes;
    g_offset = 0;
}

void* alloc(size_t size, size_t align) {
    uintptr_t current = (uintptr_t)g_base + g_offset;
    uintptr_t aligned = (current + align - 1) & ~(align - 1);
    size_t new_offset = (aligned - (uintptr_t)g_base) + size;
    if (new_offset > g_size) return nullptr;
    g_offset = new_offset;
    return (void*)aligned;
}

void* base() { return g_base; }
size_t capacity() { return g_size; }
void reset() { g_offset = 0; }

} // namespace ctx
```

---

## 5. Schema: What Goes in Context Memory

Fits in ~1MB for 64 robots, 256 tasks, 1024 objects.

```cpp
struct ContextTables {
    struct {
        uint32_t id[64];
        float x[64], y[64], theta[64];
        uint16_t current_task[64];
        uint8_t intent[64];       // 0=idle, 1=moving, 2=working
        uint64_t timestamp[64];
    } robots;

    struct {
        uint32_t id[256];
        uint16_t location[256];
        uint8_t status[256];      // 0=pending, 1=claimed, 2=done
        uint32_t assigned_robot[256];
        uint64_t timestamp[256];
    } tasks;

    struct {
        uint16_t region_id[128];
        float jam_signal[128];    // 0.0 - 1.0
        uint64_t blocked_until[128];
    } regions;

    struct {
        uint8_t data[64 * 1024];  // 64KB ring
        uint32_t head;
        uint32_t tail;
    } delta_ring;
};
```

---

## 6. Data Flow Architecture

```
WiFi Packet (UDP)
       |
       v
+-------------------------------+
|  XDP/eBPF (in kernel)         |
|  - Filter: is this a ctx delta|
|  - Write to delta_ring buffer |
+-------------------------------+
       |
       v
+-------------------------------+
|  User-space DSM Merger        |
|  - Read from delta_ring       |
|  - Apply LWW merge to tables  |
+-------------------------------+
       |
       v
+-------------------------------+
|  Selector (runs before VLA)   |
|  - Scan robots.x[], robots.y[]|
|  - Build "nearby context" list|
|  - Serialize to VLA input     |
+-------------------------------+
       |
       v
+-------------------------------+
|  VLA Inference (GPU)          |
|  - Receives context + camera  |
|  - Outputs action             |
+-------------------------------+
```

---

## 7. Implementation Stack (LeRobot + Jetson)

| Layer | Implementation |
|-------|----------------|
| Context Memory | Pinned mmap region (C++) |
| Schema | Struct-of-arrays tables |
| Delta Transport | UDP + eBPF (or UDP + userspace) |
| Merge Logic | LWW CRDT in C++ |
| Selector | C++ code that scans tables, builds context |
| VLA | LeRobot's policy network (context + image) |

---

## 8. Adaptation Path

### Step 1: Split Responsibilities

| Layer | Language | Role |
|-------|----------|------|
| Control Plane | Python (LF + ROS2) | Task claims, leases, high-level logic |
| Data Plane | C++ | Context tables, fast scans, delta merging |

Python calls C++ via pybind11 or shared memory.

### Step 2: New Module Structure

```
context-fabric/src/
  context_mem/           # NEW
    CMakeLists.txt
    context_memory.h
    context_memory.cpp
    tables.h
    py_bindings.cpp
  dsm/
    dsm_node.py          # Modified to use context_mem
```

### Step 3: Modify `dsm_node.py`

**Before (pure Python):**
```python
class DSMNode(Node):
    def __init__(self):
        self.flow_traces = {}
        self.agent_locations = {}
```

**After (backed by pinned C++ memory):**
```python
import context_mem

class DSMNode(Node):
    def __init__(self):
        context_mem.init(size_mb=8)
        self.ctx = context_mem.get_tables()

    def handle_agent_state(self, msg):
        context_mem.update_robot(
            robot_id=msg.agent_id,
            x=msg.x,
            y=msg.y,
            current_task=msg.active_task_id,
            timestamp=msg.timestamp_ms
        )

    def get_nearby_robots(self, my_x, my_y, radius):
        return context_mem.scan_robots_within(my_x, my_y, radius)
```

### Step 4: Schema Mapping

| Current Python | Pinned C++ Equivalent |
|----------------|----------------------|
| `self.flow_traces[node_id][agent_id]` | `tables.flow_traces.count[node_idx * MAX_AGENTS + agent_idx]` |
| `self.jam_signals[node_id]` | `tables.regions.jam_signal[node_idx]` |
| `self.agent_locations[agent_id]` | `tables.robots.x[agent_idx], tables.robots.y[agent_idx]` |

Semantics stay identical - only storage location changes.

---

## 9. Experimental Configurations

| Config | Description | What to Measure |
|--------|-------------|-----------------|
| A | Pure Python (current) | Context access latency, CPU usage |
| B | Pinned C++ Memory | Same metrics, compare |
| C | Pinned + eBPF delta path | Add network fast-path, compare |

**Expected Results:**
- A to B: Lower variance in access latency (no GC), better cache behavior
- B to C: Lower CPU overhead for delta ingestion

---

## 10. Hardware Paper Argument

> "We implemented a pinned context memory region on Jetson Orin. Even with software isolation, we observed X% improvement in p99 latency. However, during VLA inference, cache contention still causes Y ms spikes. A hardware-protected scratchpad would eliminate this."

Build the software baseline, collect traces, prove the hardware case.
