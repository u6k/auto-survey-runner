"""Task queue selection and derived task generation logic."""

from __future__ import annotations

import hashlib
from typing import Any

from .dedupe import normalize_claim_text
from .models import Task
from .utils import slugify


def pick_next_task(tasks: list[Task], queue: list[str]) -> Task | None:
    """Pick the queued task with the highest priority."""
    task_map = {task.task_id: task for task in tasks}
    queued = [task_map[task_id] for task_id in queue if task_id in task_map and task_map[task_id].status in {"pending", "running"}]
    if not queued:
        return None
    return sorted(queued, key=lambda task: (-task.priority, task.created_at))[0]


def derive_tasks(parent_task: Task, planner_output: dict[str, Any], tasks: list[Task], config: dict[str, Any]) -> list[Task]:
    """Create child tasks under depth, count, priority, and dedupe constraints."""
    max_tasks = int(config["runtime"]["max_tasks"])
    max_depth = int(config["runtime"]["max_depth"])
    min_priority = float(config["runtime"]["min_priority"])
    if parent_task.depth >= max_depth or len(tasks) >= max_tasks:
        return []

    existing_dedupe_keys = {task.dedupe_key for task in tasks if task.dedupe_key}
    derived: list[Task] = []
    for item in planner_output.get("subtasks", []):
        priority = float(item.get("priority", 0.0))
        if priority < min_priority or len(tasks) + len(derived) >= max_tasks:
            continue
        title = item["title"].strip()
        dedupe_key = normalize_claim_text(title + " " + item.get("description", ""))
        if dedupe_key in existing_dedupe_keys:
            continue
        task_id = hashlib.sha1(f"{parent_task.task_id}:{dedupe_key}".encode()).hexdigest()[:12]
        derived.append(
            Task(
                task_id=task_id,
                title=title,
                slug=slugify(title),
                description=item.get("description", ""),
                priority=priority,
                depth=parent_task.depth + 1,
                parent_task_id=parent_task.task_id,
                dedupe_key=dedupe_key,
            )
        )
        existing_dedupe_keys.add(dedupe_key)
    return derived
