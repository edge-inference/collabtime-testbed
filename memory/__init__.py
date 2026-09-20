"""
Context Memory Module

Provides structured context storage and LLM-ready selectors
for multi-robot coordination with VLAs.

Components:
- schema: Data structure definitions (RobotState, TaskState, etc.)
- context_memory: In-memory storage with spatial queries
- selector: Converts memory to text for LLM/VLA input

Usage:
    from memory import ContextMemory, ContextSelector, RobotIntent

    ctx = ContextMemory()
    ctx.update_robot(1, x=2.3, y=4.1, intent=RobotIntent.MOVING)

    selector = ContextSelector(ctx)
    context_text = selector.select(my_robot_id=1, my_x=2.3, my_y=4.1)
"""

from .schema import (
    RobotState,
    TaskState,
    RegionState,
    ContextSnapshot,
    RobotIntent,
    TaskStatus,
    MAX_ROBOTS,
    MAX_TASKS,
    MAX_REGIONS,
)

from .context_memory import ContextMemory

from .selector import (
    ContextSelector,
    MinimalSelector,
    JSONSelector,
    build_prompt,
)

__all__ = [
    "ContextMemory",
    "ContextSelector",
    "MinimalSelector",
    "JSONSelector",
    "build_prompt",
    "RobotState",
    "TaskState",
    "RegionState",
    "ContextSnapshot",
    "RobotIntent",
    "TaskStatus",
    "MAX_ROBOTS",
    "MAX_TASKS",
    "MAX_REGIONS",
]
