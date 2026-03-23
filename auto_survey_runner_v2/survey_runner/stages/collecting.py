"""Collecting stage.

This stage resolves local files and web pages into a normalized source list and
stores the ranked result as a task-local checkpoint plus a global knowledge log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..sources import collect_web_documents, load_local_documents, rank_sources
from ..utils import read_json, write_json


def collecting_stage(task: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect local and web sources for the task."""
    path = context["task_work_dir"] / "collected_sources.json"
    if path.exists():
        return read_json(path, [])

    config = context["config"]
    logger = context["logger"]
    local_sources = load_local_documents(Path(config["paths"]["local_docs_dir"]), task.task_id)
    web_sources = collect_web_documents(task.task_id, task.planned_queries, int(config["collection"]["max_web_results"]), config, logger=logger)
    combined = local_sources + web_sources
    ranked = rank_sources(" ".join(task.planned_queries) or task.title, combined, int(config["collection"]["max_sources_per_task"]))
    logger.log_event(
        "source_collection",
        message="Collected and ranked sources",
        task_id=task.task_id,
        stage="collecting",
        payload={
            "local_source_count": len(local_sources),
            "web_source_count": len(web_sources),
            "ranked_source_count": len(ranked),
        },
    )
    context["store"].append_sources(ranked)
    serialized = [source.to_dict() for source in ranked]
    write_json(path, serialized)
    return serialized
