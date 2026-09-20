"""
Context Memory - Python Prototype

This is the pure Python version for testing.
Same interface will be used for C++ pinned memory later.

Usage:
    from memory.context_memory import ContextMemory

    ctx = ContextMemory()
    ctx.update_robot(1, x=2.3, y=4.1, intent=RobotIntent.MOVING)
    nearby = ctx.scan_robots_within(2.0, 4.0, radius=3.0)
"""

import time
from typing import List, Dict, Optional, Tuple
from dataclasses import asdict

from .schema import (
    RobotState, TaskState, RegionState, ContextSnapshot,
    RobotIntent, TaskStatus,
    MAX_ROBOTS, MAX_TASKS, MAX_REGIONS
)


class ContextMemory:
    """
    In-memory context storage with spatial queries.

    This Python version uses dicts for simplicity.
    C++ version will use struct-of-arrays in pinned memory.
    """

    def __init__(self):
        self._robots: Dict[int, RobotState] = {}
        self._tasks: Dict[int, TaskState] = {}
        self._regions: Dict[str, RegionState] = {}

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    # Robot operations
    def update_robot(
        self,
        robot_id: int,
        x: float,
        y: float,
        theta: float = 0.0,
        intent: RobotIntent = RobotIntent.IDLE,
        current_task: Optional[int] = None
    ) -> None:
        """Update or create robot state."""
        self._robots[robot_id] = RobotState(
            id=robot_id,
            x=x,
            y=y,
            theta=theta,
            intent=intent,
            current_task=current_task,
            timestamp_ms=self._now_ms()
        )

    def get_robot(self, robot_id: int) -> Optional[RobotState]:
        """Get robot state by ID."""
        return self._robots.get(robot_id)

    def get_all_robots(self) -> List[RobotState]:
        """Get all robot states."""
        return list(self._robots.values())

    def scan_robots_within(
        self,
        x: float,
        y: float,
        radius: float,
        exclude_id: Optional[int] = None
    ) -> List[Tuple[RobotState, float]]:
        """
        Find all robots within radius of (x, y).
        Returns list of (RobotState, distance) tuples, sorted by distance.
        """
        results = []
        r2 = radius * radius

        for robot in self._robots.values():
            if exclude_id is not None and robot.id == exclude_id:
                continue
            dx = robot.x - x
            dy = robot.y - y
            dist_sq = dx * dx + dy * dy
            if dist_sq <= r2:
                results.append((robot, dist_sq ** 0.5))

        results.sort(key=lambda x: x[1])
        return results

    # Task operations
    def update_task(
        self,
        task_id: int,
        location_x: float,
        location_y: float,
        location_node: int,
        status: TaskStatus = TaskStatus.PENDING,
        assigned_robot: Optional[int] = None,
        priority: int = 0
    ) -> None:
        """Update or create task state."""
        self._tasks[task_id] = TaskState(
            id=task_id,
            location_x=location_x,
            location_y=location_y,
            location_node=location_node,
            status=status,
            assigned_robot=assigned_robot,
            priority=priority,
            timestamp_ms=self._now_ms()
        )

    def get_task(self, task_id: int) -> Optional[TaskState]:
        """Get task state by ID."""
        return self._tasks.get(task_id)

    def get_available_tasks(self) -> List[TaskState]:
        """Get all pending tasks, sorted by priority."""
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        pending.sort(key=lambda t: -t.priority)
        return pending

    def get_all_tasks(self) -> List[TaskState]:
        """Get all task states."""
        return list(self._tasks.values())

    # Region operations
    def update_region(
        self,
        region_id: str,
        jam_signal: float,
        blocked_until_ms: int = 0
    ) -> None:
        """Update or create region state."""
        self._regions[region_id] = RegionState(
            id=region_id,
            jam_signal=jam_signal,
            blocked_until_ms=blocked_until_ms,
            timestamp_ms=self._now_ms()
        )

    def get_region(self, region_id: str) -> Optional[RegionState]:
        """Get region state by ID."""
        return self._regions.get(region_id)

    def get_congested_regions(self, threshold: float = 0.5) -> List[RegionState]:
        """Get all regions with jam_signal above threshold."""
        return [r for r in self._regions.values() if r.jam_signal >= threshold]

    # Snapshot operations
    def get_snapshot(self) -> ContextSnapshot:
        """Get full snapshot of current state."""
        return ContextSnapshot(
            robots=list(self._robots.values()),
            tasks=list(self._tasks.values()),
            regions=list(self._regions.values()),
            snapshot_time_ms=self._now_ms()
        )

    def clear(self) -> None:
        """Clear all state."""
        self._robots.clear()
        self._tasks.clear()
        self._regions.clear()

    # Stats
    def stats(self) -> Dict[str, int]:
        """Get memory usage stats."""
        return {
            "robots": len(self._robots),
            "tasks": len(self._tasks),
            "regions": len(self._regions),
            "max_robots": MAX_ROBOTS,
            "max_tasks": MAX_TASKS,
            "max_regions": MAX_REGIONS,
        }
