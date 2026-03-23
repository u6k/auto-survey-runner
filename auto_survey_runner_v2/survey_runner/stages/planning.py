"""Planning stage.

This stage asks the planner model to convert the root task into search queries
and candidate subtasks. The output becomes the durable checkpoint for the rest
of the task lifecycle.
"""

from __future__ import annotations

from typing import Any

from ..prompts import PLANNER_SYSTEM_PROMPT, QUERY_PLAN_SCHEMA
from ..utils import read_json, write_json


def planning_stage(task: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Generate query plan and candidate subtasks."""
    path = context["task_work_dir"] / "planning.json"
    if path.exists():
        return read_json(path, {})

    config = context["config"]
    client = context["client"]
    user_prompt = f"Task: {task.title}\nDescription: {task.description}"
    result = client.chat_json(
        model=config["ollama"]["planner_model"],
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=QUERY_PLAN_SCHEMA,
        temperature=float(config["models"]["planner_temperature"]),
        log_context={"task_id": task.task_id, "stage": "planning"},
    )
    write_json(path, result)
    return result
