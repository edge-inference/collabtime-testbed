"""
Context Memory Schema Definitions

Defines the structure of data stored in context memory.
Same schema will be used for:
- Python prototype (dicts/dataclasses)
- C++ pinned memory (struct-of-arrays)
- Shared memory (mmap)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import IntEnum


class RobotIntent(IntEnum):
    IDLE = 0
    MOVING = 1
    WORKING = 2
    CHARGING = 3


class TaskStatus(IntEnum):
    PENDING = 0
    CLAIMED = 1
    IN_PROGRESS = 2
    COMPLETED = 3
    FAILED = 4


@dataclass
class RobotState:
    id: int
    x: float
    y: float
    theta: float = 0.0
    intent: RobotIntent = RobotIntent.IDLE
    current_task: Optional[int] = None
    timestamp_ms: int = 0


@dataclass
class TaskState:
    id: int
    location_x: float
    location_y: float
    location_node: int
    status: TaskStatus = TaskStatus.PENDING
    assigned_robot: Optional[int] = None
    priority: int = 0
    timestamp_ms: int = 0


@dataclass
class RegionState:
    id: str
    jam_signal: float = 0.0  # 0.0 = clear, 1.0 = blocked
    blocked_until_ms: int = 0
    timestamp_ms: int = 0


@dataclass
class ContextSnapshot:
    """Full snapshot of context memory at a point in time."""
    robots: List[RobotState] = field(default_factory=list)
    tasks: List[TaskState] = field(default_factory=list)
    regions: List[RegionState] = field(default_factory=list)
    snapshot_time_ms: int = 0


# Schema limits (for C++ struct-of-arrays sizing)
MAX_ROBOTS = 64
MAX_TASKS = 256
MAX_REGIONS = 128
DELTA_RING_SIZE = 64 * 1024  # 64KB
