"""Spawning stage.

This stage converts planner-proposed subtasks into durable queued tasks after
deduplication and runtime limit checks.
"""

from __future__ import annotations

from typing import Any

from ..task_generation import derive_tasks
from ..utils import read_json, write_json


def spawning_stage(task: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Create derived tasks if the planner proposed useful children."""
    path = context["task_work_dir"] / "spawned_tasks.json"
    if path.exists():
        return read_json(path, [])

    logger = context["logger"]
    planner_output = read_json(context["task_work_dir"] / "planning.json", {})
    derived = derive_tasks(task, planner_output, context["tasks"], context["config"])
    serialized = [child.to_dict() for child in derived]
    logger.log_event(
        "task_spawning",
        message="Evaluated derived tasks",
        task_id=task.task_id,
        stage="spawning",
        payload={"spawned_task_count": len(serialized)},
    )
    write_json(path, serialized)
    return serialized
