"""Orchestration for initializing, running, resuming, and monitoring survey tasks."""

from __future__ import annotations

import hashlib
from typing import Any

from .logger import ExecutionLogger

from .llm_client import create_llm_client
from .models import Task, utc_now_iso
from .state_store import StateStore
from .task_generation import pick_next_task
from .stages import (
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
        self.logger = ExecutionLogger(self.store)
        self.client = create_llm_client(config, logger=self.logger)

    def init_workspace(self) -> None:
        """Initialize the workspace and root task."""
        self.store.ensure_layout()
        self.logger.log_event("workspace_init", message="Ensured workspace layout")
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
        self.logger.log_event("root_task_created", message="Created root task", task_id=root_task.task_id, payload={"title": root_task.title})
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
        self.logger.log_event("task_start", message="Starting task execution", task_id=task.task_id, payload={"current_stage": task.current_stage, "priority": task.priority})
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
            self.logger.log_event("stage_start", message=f"Starting stage {stage_name}", task_id=task.task_id, stage=stage_name)
            context = {
                "config": self.config,
                "client": self.client,
                "logger": self.logger,
                "store": self.store,
                "task_work_dir": self.store.task_work_path(task.task_id),
                "tasks": tasks,
            }
            result = stage_functions[stage_name](task, context)
            self.logger.log_event("stage_complete", message=f"Completed stage {stage_name}", task_id=task.task_id, stage=stage_name, payload={"next_stage": STAGE_ORDER[STAGE_ORDER.index(stage_name) + 1]})
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

        self.logger.log_event("task_complete", message="Completed task execution", task_id=task.task_id, payload={"spawned_task_ids": task.spawned_task_ids})
        task.status = "completed"
        task.current_stage = "done"
        task.updated_at = utc_now_iso()
        if task.task_id in queue:
            queue.remove(task.task_id)
            self.store.write_queue(queue)
        run_state = self.store.read_run_state()
        run_state["current_task_id"] = None
        run_state["stats"]["completed_tasks"] = run_state.get("stats", {}).get("completed_tasks", 0) + 1
        run_state["status"] = "completed" if not queue else "idle"
        run_state["updated_at"] = utc_now_iso()
        self.store.write_run_state(run_state)
        self._persist_tasks(tasks)

    def run(self, steps: int | None = None) -> None:
        """Run or resume up to the requested number of tasks."""
        self.init_workspace()
        self.logger.log_event("run_start", message="Starting orchestrator run", payload={"requested_steps": steps})
        limit = steps if steps is not None else int(self.config["runtime"]["max_steps_per_run"])
        processed = 0
        while processed < limit:
            tasks = self.store.read_tasks()
            queue = self.store.read_queue()
            run_state = self.store.read_run_state()
            task = self._find_resume_task(tasks, run_state, queue)
            if not task:
                has_failed_tasks = any(existing_task.status == "failed" for existing_task in tasks)
                run_state.update(
                    {
                        "status": "failed" if has_failed_tasks else "completed",
                        "current_task_id": None,
                        "updated_at": utc_now_iso(),
                    }
                )
                self.store.write_run_state(run_state)
                self.logger.log_event(
                    "run_complete",
                    message="No queued tasks remain; marking run finished",
                    level="ERROR" if has_failed_tasks else "INFO",
                    payload={"has_failed_tasks": has_failed_tasks},
                )
                break
            try:
                self._run_task(task, tasks, queue)
            except Exception as exc:
                self.logger.log_exception(message="Task execution failed", exc=exc, task_id=task.task_id, stage=task.current_stage, payload={"retry_count_before_increment": task.retry_count})
                task.error_message = str(exc)
                task.retry_count += 1
                retryable = task.retry_count < int(self.config["runtime"]["max_retry_per_task"])
                task.status = "pending" if retryable else "failed"
                task.updated_at = utc_now_iso()
                if retryable:
                    if task.task_id not in queue:
                        queue.append(task.task_id)
                elif task.task_id in queue:
                    queue.remove(task.task_id)
                self.store.write_queue(queue)
                self._persist_tasks(tasks)
                run_state = self.store.read_run_state()
                run_state.setdefault("stats", {})
                run_state["current_task_id"] = None
                run_state["last_error_message"] = str(exc)
                run_state["updated_at"] = utc_now_iso()
                if retryable:
                    run_state["status"] = "idle"
                else:
                    run_state["stats"]["failed_tasks"] = run_state["stats"].get("failed_tasks", 0) + 1
                    run_state["status"] = "failed" if not queue else "idle"
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
