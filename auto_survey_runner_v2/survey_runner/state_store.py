"""Persistent state management for run state, queue, tasks, and knowledge files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Claim, SourceDoc, Task
from .utils import append_jsonl, ensure_dir, read_json, read_jsonl, write_json


class StateStore:
    """Read and write all persisted state for the pipeline."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.state_dir = Path(config["paths"]["state_dir"])
        self.knowledge_dir = Path(config["paths"]["knowledge_dir"])
        self.output_dir = Path(config["paths"]["output_dir"])
        self.task_work_dir = self.state_dir / "task_work"

        self.run_state_path = self.state_dir / "run_state.json"
        self.tasks_path = self.state_dir / "tasks.json"
        self.queue_path = self.state_dir / "queue.json"
        self.claims_path = self.knowledge_dir / "claims.jsonl"
        self.sources_path = self.knowledge_dir / "sources.jsonl"
        self.task_summaries_path = self.knowledge_dir / "task_summaries.jsonl"
        self.global_digest_path = self.knowledge_dir / "global_digest.json"

    def ensure_layout(self) -> None:
        """Ensure required directories and baseline files exist."""
        for path in [self.state_dir, self.knowledge_dir, self.output_dir, self.task_work_dir]:
            ensure_dir(path)
        if not self.run_state_path.exists():
            self.write_run_state({"status": "idle", "current_task_id": None, "stats": {}, "root_task_id": None})
        if not self.tasks_path.exists():
            self.write_tasks([])
        if not self.queue_path.exists():
            self.write_queue([])
        if not self.global_digest_path.exists():
            write_json(self.global_digest_path, {"highlights": [], "open_questions": [], "updated_at": None})
        for path in [self.claims_path, self.sources_path, self.task_summaries_path]:
            path.touch(exist_ok=True)

    def task_work_path(self, task_id: str) -> Path:
        """Return the task-specific work directory path."""
        path = self.task_work_dir / task_id
        ensure_dir(path)
        return path

    def read_run_state(self) -> dict[str, Any]:
        """Load run state."""
        return read_json(self.run_state_path, {"status": "idle", "current_task_id": None, "stats": {}, "root_task_id": None})

    def write_run_state(self, payload: dict[str, Any]) -> None:
        """Persist run state."""
        write_json(self.run_state_path, payload)

    def read_tasks(self) -> list[Task]:
        """Load all tasks."""
        rows = read_json(self.tasks_path, [])
        return [Task(**row) for row in rows]

    def write_tasks(self, tasks: list[Task | dict[str, Any]]) -> None:
        """Persist all tasks."""
        rows = [task.to_dict() if isinstance(task, Task) else task for task in tasks]
        write_json(self.tasks_path, rows)

    def read_queue(self) -> list[str]:
        """Load queued task IDs."""
        return read_json(self.queue_path, [])

    def write_queue(self, queue: list[str]) -> None:
        """Persist queued task IDs."""
        write_json(self.queue_path, queue)

    def append_claims(self, claims: list[Claim]) -> None:
        """Append claims to the knowledge store."""
        append_jsonl(self.claims_path, [claim.to_dict() for claim in claims])

    def append_sources(self, sources: list[SourceDoc]) -> None:
        """Append sources to the knowledge store."""
        append_jsonl(self.sources_path, [source.to_dict() for source in sources])

    def append_task_summary(self, summary: dict[str, Any]) -> None:
        """Append a task summary record."""
        append_jsonl(self.task_summaries_path, [summary])

    def read_claims(self) -> list[dict[str, Any]]:
        """Read all persisted claims."""
        return read_jsonl(self.claims_path)

    def read_sources(self) -> list[dict[str, Any]]:
        """Read all persisted sources."""
        return read_jsonl(self.sources_path)

    def read_task_summaries(self) -> list[dict[str, Any]]:
        """Read all persisted task summaries."""
        return read_jsonl(self.task_summaries_path)

    def read_global_digest(self) -> dict[str, Any]:
        """Read global digest."""
        return read_json(self.global_digest_path, {"highlights": [], "open_questions": [], "updated_at": None})

    def write_global_digest(self, payload: dict[str, Any]) -> None:
        """Persist global digest."""
        write_json(self.global_digest_path, payload)
