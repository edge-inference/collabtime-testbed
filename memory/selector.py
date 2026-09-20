"""
Context Selector - Converts memory to text for LLM/VLA

The selector is the bridge between structured memory and the model.
It reads from context memory and produces text that gets tokenized.

Different selectors can produce different views:
- Full context (everything)
- Spatial context (nearby robots only)
- Task-focused context (relevant tasks only)
"""

from typing import Optional, List
from .context_memory import ContextMemory
from .schema import RobotState, TaskState, RegionState, RobotIntent, TaskStatus


class ContextSelector:
    """Base selector that converts context memory to text."""

    def __init__(self, ctx: ContextMemory):
        self.ctx = ctx

    def select(
        self,
        my_robot_id: int,
        my_x: float,
        my_y: float,
        radius: float = 10.0,
        include_tasks: bool = True,
        include_congestion: bool = True,
        max_nearby_robots: int = 5,
        max_tasks: int = 5
    ) -> str:
        """
        Select relevant context and format as text.

        Args:
            my_robot_id: ID of the querying robot
            my_x, my_y: Current position
            radius: How far to look for nearby robots
            include_tasks: Whether to include task info
            include_congestion: Whether to include region congestion
            max_nearby_robots: Limit on nearby robots to include
            max_tasks: Limit on tasks to include

        Returns:
            Formatted text suitable for LLM input
        """
        lines = []

        # Header - who am I
        my_robot = self.ctx.get_robot(my_robot_id)
        if my_robot:
            task_str = self._format_task_status(my_robot.intent, my_robot.current_task)
            lines.append(f"I am Robot {my_robot_id} at ({my_x:.1f}, {my_y:.1f}){task_str}")
        else:
            lines.append(f"I am Robot {my_robot_id} at ({my_x:.1f}, {my_y:.1f})")

        lines.append("")

        # Nearby robots
        nearby = self.ctx.scan_robots_within(my_x, my_y, radius, exclude_id=my_robot_id)
        if nearby:
            lines.append("Nearby robots:")
            for robot, dist in nearby[:max_nearby_robots]:
                status = self._format_task_status(robot.intent, robot.current_task)
                lines.append(f"  - Robot {robot.id} at ({robot.x:.1f}, {robot.y:.1f}){status}, dist={dist:.1f}")
            if len(nearby) > max_nearby_robots:
                lines.append(f"  - ... and {len(nearby) - max_nearby_robots} more")
        else:
            lines.append("No robots nearby.")

        # Available tasks
        if include_tasks:
            lines.append("")
            available = self.ctx.get_available_tasks()
            if available:
                lines.append("Available tasks:")
                for task in available[:max_tasks]:
                    dist = ((task.location_x - my_x)**2 + (task.location_y - my_y)**2)**0.5
                    lines.append(f"  - Task {task.id} at node {task.location_node} ({task.location_x:.1f}, {task.location_y:.1f}), priority={task.priority}, dist={dist:.1f}")
                if len(available) > max_tasks:
                    lines.append(f"  - ... and {len(available) - max_tasks} more")
            else:
                lines.append("No tasks available.")

        # Congestion
        if include_congestion:
            congested = self.ctx.get_congested_regions(threshold=0.5)
            if congested:
                lines.append("")
                lines.append("Congestion warnings:")
                for region in congested:
                    level = "HIGH" if region.jam_signal > 0.7 else "MODERATE"
                    lines.append(f"  - {region.id}: {level} ({region.jam_signal:.1f})")

        return "\n".join(lines)

    def _intent_to_str(self, intent: RobotIntent) -> str:
        return {
            RobotIntent.IDLE: "idle",
            RobotIntent.MOVING: "moving",
            RobotIntent.WORKING: "working",
            RobotIntent.CHARGING: "charging",
        }.get(intent, "unknown")

    def _format_task_status(self, intent: RobotIntent, task_id: Optional[int]) -> str:
        """Format robot status based on intent and task."""
        if task_id is None:
            return f", {self._intent_to_str(intent)}"

        if intent == RobotIntent.MOVING:
            return f", navigating to Task {task_id}"
        elif intent == RobotIntent.WORKING:
            return f", working on Task {task_id}"
        elif intent == RobotIntent.IDLE:
            return f", idle (assigned Task {task_id})"
        else:
            return f", {self._intent_to_str(intent)} (Task {task_id})"


class MinimalSelector(ContextSelector):
    """Minimal selector - just nearby robots, very compact."""

    def select(
        self,
        my_robot_id: int,
        my_x: float,
        my_y: float,
        radius: float = 5.0,
        **kwargs
    ) -> str:
        nearby = self.ctx.scan_robots_within(my_x, my_y, radius, exclude_id=my_robot_id)
        if not nearby:
            return f"Robot {my_robot_id} at ({my_x:.1f},{my_y:.1f}). No nearby robots."

        parts = [f"Robot {my_robot_id} at ({my_x:.1f},{my_y:.1f}). Nearby:"]
        for robot, dist in nearby[:3]:
            parts.append(f"R{robot.id}@({robot.x:.1f},{robot.y:.1f})")
        return " ".join(parts)


class JSONSelector(ContextSelector):
    """JSON selector - structured format for models that prefer JSON."""

    def select(
        self,
        my_robot_id: int,
        my_x: float,
        my_y: float,
        radius: float = 10.0,
        **kwargs
    ) -> str:
        import json

        nearby = self.ctx.scan_robots_within(my_x, my_y, radius, exclude_id=my_robot_id)
        available = self.ctx.get_available_tasks()
        congested = self.ctx.get_congested_regions()

        data = {
            "self": {"id": my_robot_id, "x": my_x, "y": my_y},
            "nearby_robots": [
                {"id": r.id, "x": r.x, "y": r.y, "intent": r.intent.name, "dist": round(d, 1)}
                for r, d in nearby[:5]
            ],
            "available_tasks": [
                {"id": t.id, "node": t.location_node, "priority": t.priority}
                for t in available[:5]
            ],
            "congestion": [
                {"region": r.id, "level": r.jam_signal}
                for r in congested
            ]
        }
        return json.dumps(data, indent=2)


def build_prompt(context_text: str, question: str, system_prompt: Optional[str] = None) -> str:
    """
    Build a full prompt for LLM with context.

    Args:
        context_text: Output from selector
        question: What to ask the model
        system_prompt: Optional system-level instructions

    Returns:
        Complete prompt string
    """
    if system_prompt is None:
        system_prompt = "You are a warehouse robot controller. Make decisions based on the current context."

    return f"""{system_prompt}

CURRENT CONTEXT:
{context_text}

QUESTION: {question}

ANSWER (be concise):"""
