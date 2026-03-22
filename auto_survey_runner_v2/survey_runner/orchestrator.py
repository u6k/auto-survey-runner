"""Orchestration for initializing, running, resuming, and monitoring survey tasks."""

from __future__ import annotations

import hashlib
from typing import Any

from .models import Task, utc_now_iso
from .ollama_client import OllamaClient
from .state_store import StateStore
from .task_generation import pick_next_task
from .task_stages import (
    STAGE_ORDER,
    collecting_stage,
    extracting_stage,
    integrating_stage,
    planning_stage,
    snapshotting_stage,
    spawning_stage,
    summarizing_stage,
)
from .utils import slugify


class Orchestrator:
    """Coordinate task execution and persistence."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.store = StateStore(config)
        self.client = OllamaClient(config["ollama"]["base_url"])

    def init_workspace(self) -> None:
        """Initialize the workspace and root task."""
        self.store.ensure_layout()
        tasks = self.store.read_tasks()
        if tasks:
            return
        topic = self.config["research"]["topic"]
        root_task = Task(
            task_id=hashlib.sha1(topic.encode()).hexdigest()[:12],
            title=topic,
            slug=slugify(topic),
            description=self.config["research"]["description"],
            priority=float(self.config["runtime"]["default_priority"]),
            depth=0,
            dedupe_key=slugify(topic),
        )
        self.store.write_tasks([root_task])
        self.store.write_queue([root_task.task_id])
        self.store.write_run_state(
            {
                "status": "idle",
                "current_task_id": None,
                "stats": {"completed_tasks": 0, "failed_tasks": 0},
                "root_task_id": root_task.task_id,
                "updated_at": utc_now_iso(),
            }
        )

    def _persist_tasks(self, tasks: list[Task]) -> None:
        self.store.write_tasks(tasks)

    def _find_resume_task(self, tasks: list[Task], run_state: dict[str, Any], queue: list[str]) -> Task | None:
        current_task_id = run_state.get("current_task_id")
        if current_task_id:
            for task in tasks:
                if task.task_id == current_task_id and task.status == "running":
                    return task
        return pick_next_task(tasks, queue)

    # Stages are executed one at a time so each stage can leave a durable file checkpoint.
    # This makes resumability and retry handling explicit and easy to inspect on disk.
    def _run_task(self, task: Task, tasks: list[Task], queue: list[str]) -> None:
        task.status = "running"
        task.updated_at = utc_now_iso()
        run_state = self.store.read_run_state()
        run_state.update({"status": "running", "current_task_id": task.task_id, "updated_at": utc_now_iso()})
        self.store.write_run_state(run_state)
        self._persist_tasks(tasks)

        stage_functions = {
            "planning": planning_stage,
            "collecting": collecting_stage,
            "extracting": extracting_stage,
            "summarizing": summarizing_stage,
            "spawning": spawning_stage,
            "integrating": integrating_stage,
            "snapshotting": snapshotting_stage,
        }

        for stage_name in STAGE_ORDER:
            if stage_name == "done":
                continue
            if STAGE_ORDER.index(stage_name) < STAGE_ORDER.index(task.current_stage):
                continue
            context = {
                "config": self.config,
                "client": self.client,
                "store": self.store,
                "task_work_dir": self.store.task_work_path(task.task_id),
                "tasks": tasks,
            }
            result = stage_functions[stage_name](task, context)
            if stage_name == "planning":
                task.planned_queries = result.get("queries", [])
            elif stage_name == "collecting":
                task.collected_source_ids = [row["source_id"] for row in result]
            elif stage_name == "extracting":
                task.extracted_claim_ids = [row["claim_id"] for row in result]
            elif stage_name == "summarizing":
                task.summary_id = f"summary:{task.task_id}"
            elif stage_name == "spawning":
                new_tasks = [Task(**row) for row in result]
                tasks.extend(new_tasks)
                queue.extend([new_task.task_id for new_task in new_tasks])
                task.spawned_task_ids = [new_task.task_id for new_task in new_tasks]
                self.store.write_queue(queue)
            next_index = STAGE_ORDER.index(stage_name) + 1
            task.current_stage = STAGE_ORDER[next_index]
            task.updated_at = utc_now_iso()
            self._persist_tasks(tasks)

        task.status = "completed"
        task.current_stage = "done"
        task.updated_at = utc_now_iso()
        if task.task_id in queue:
            queue.remove(task.task_id)
            self.store.write_queue(queue)
        run_state = self.store.read_run_state()
        run_state["current_task_id"] = None
        run_state["stats"]["completed_tasks"] = run_state.get("stats", {}).get("completed_tasks", 0) + 1
        run_state["updated_at"] = utc_now_iso()
        self.store.write_run_state(run_state)
        self._persist_tasks(tasks)

    def run(self, steps: int | None = None) -> None:
        """Run or resume up to the requested number of tasks."""
        self.init_workspace()
        limit = steps if steps is not None else int(self.config["runtime"]["max_steps_per_run"])
        processed = 0
        while processed < limit:
            tasks = self.store.read_tasks()
            queue = self.store.read_queue()
            run_state = self.store.read_run_state()
            task = self._find_resume_task(tasks, run_state, queue)
            if not task:
                run_state.update({"status": "completed", "current_task_id": None, "updated_at": utc_now_iso()})
                self.store.write_run_state(run_state)
                break
            try:
                self._run_task(task, tasks, queue)
            except Exception as exc:
                task.error_message = str(exc)
                task.retry_count += 1
                task.status = "pending" if task.retry_count < int(self.config["runtime"]["max_retry_per_task"]) else "failed"
                task.updated_at = utc_now_iso()
                if task.status == "failed" and task.task_id in queue:
                    queue.remove(task.task_id)
                elif task.task_id not in queue:
                    queue.append(task.task_id)
                self.store.write_queue(queue)
                self._persist_tasks(tasks)
                run_state = self.store.read_run_state()
                run_state["status"] = "failed"
                run_state["current_task_id"] = None
                run_state.setdefault("stats", {})
                if task.status == "failed":
                    run_state["stats"]["failed_tasks"] = run_state["stats"].get("failed_tasks", 0) + 1
                run_state["updated_at"] = utc_now_iso()
                self.store.write_run_state(run_state)
            processed += 1

    def status(self) -> dict[str, Any]:
        """Return a status summary."""
        tasks = self.store.read_tasks()
        run_state = self.store.read_run_state()
        queue = self.store.read_queue()
        return {
            "run_state": run_state,
            "queue_length": len(queue),
            "tasks": [task.to_dict() for task in tasks],
        }
