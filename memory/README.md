# Context Memory Module

Structured context storage for multi-robot VLA coordination.

## Quick Start

```bash
# Install dependencies
pip install transformers torch accelerate

# See context without LLM
python test_llm_context.py --dry-run

# Run with Qwen2.5-1.5B
python test_llm_context.py
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Context Memory                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │   Robots    │  │    Tasks    │  │   Regions   │     │
│  │ id,x,y,... │  │ id,loc,...  │  │ id,jam,...  │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                      Selector                            │
│  - scan_robots_within(x, y, radius)                     │
│  - get_available_tasks()                                │
│  - get_congested_regions()                              │
│  - format as text / JSON                                │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   LLM / VLA                              │
│  - Receives: context text + camera image                │
│  - Returns: action decision                             │
└─────────────────────────────────────────────────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `schema.py` | Data structures (RobotState, TaskState, etc.) |
| `context_memory.py` | In-memory storage with spatial queries |
| `selector.py` | Converts memory to text for LLM |
| `test_llm_context.py` | Standalone test script |

## Example Output

```
I am Robot 1 at (2.0, 3.0), status: moving, working on Task 5

Nearby robots:
  - Robot 4 at (2.5, 2.5), moving (Task 7), dist=0.7
  - Robot 2 at (3.0, 3.5), working (Task 3), dist=1.1

Available tasks:
  - Task 9 at node 10 (0.0, 2.0), priority=3, dist=2.2
  - Task 11 at node 19 (4.0, 4.0), priority=1, dist=2.2

Congestion warnings:
  - aisle-2: HIGH (0.8)
```

## Selectors

| Selector | Format | Use Case |
|----------|--------|----------|
| `ContextSelector` | Verbose text | General purpose, debugging |
| `MinimalSelector` | Compact text | Token-limited models |
| `JSONSelector` | Structured JSON | Models that prefer JSON |

## Future: C++ Pinned Memory

This Python version will be replaced with C++ pinned memory for:
- Deterministic access latency (no GC)
- Cache-friendly layout (struct-of-arrays)
- Zero-copy GPU access on Jetson
- eBPF fast-path for network updates

Same interface, different backend.
