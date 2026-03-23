"""Snapshotting stage.

This stage renders user-facing integrated outputs from the global knowledge
state accumulated so far.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..renderers import render_integrated_outputs
from ..utils import read_json, write_json


def snapshotting_stage(task: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Render integrated outputs for the current full survey state."""
    path = context["task_work_dir"] / "snapshot.json"
    if path.exists():
        return read_json(path, {})

    logger = context["logger"]
    global_digest = context["store"].read_global_digest()
    task_summaries = context["store"].read_task_summaries()
    claims = context["store"].read_claims()
    output_path = render_integrated_outputs(Path(context["config"]["paths"]["output_dir"]), task, global_digest, task_summaries, claims)
    payload = {"output_path": str(output_path)}
    logger.log_event("snapshot", message="Rendered integrated outputs", task_id=task.task_id, stage="snapshotting", payload=payload)
    write_json(path, payload)
    return payload
