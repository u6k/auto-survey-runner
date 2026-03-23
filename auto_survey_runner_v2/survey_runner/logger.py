"""Structured execution logging helpers for survey runs."""

from __future__ import annotations

import traceback
from typing import Any

from .models import utc_now_iso
from .utils import append_jsonl, ensure_dir


class ExecutionLogger:
    """Write structured execution logs to global and task-scoped JSONL files."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.global_log_path = store.logs_dir / "execution.jsonl"

    def _paths(self, task_id: str | None = None) -> list[Any]:
        paths = [self.global_log_path]
        if task_id:
            task_dir = self.store.task_work_path(task_id)
            ensure_dir(task_dir)
            paths.append(task_dir / "events.jsonl")
        return paths

    def log_event(
        self,
        event_type: str,
        *,
        message: str,
        level: str = "INFO",
        task_id: str | None = None,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist a generic structured log event."""
        row = {
            "timestamp": utc_now_iso(),
            "level": level,
            "event_type": event_type,
            "message": message,
            "task_id": task_id,
            "stage": stage,
            "payload": payload or {},
        }
        for path in self._paths(task_id):
            append_jsonl(path, [row])

    def log_llm_request(
        self,
        *,
        task_id: str | None,
        stage: str | None,
        model: str,
        temperature: float,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None,
    ) -> None:
        """Persist an LLM request with prompts and options."""
        self.log_event(
            "llm_request",
            message=f"LLM request for model {model}",
            task_id=task_id,
            stage=stage,
            payload={
                "model": model,
                "temperature": temperature,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": schema,
            },
        )

    def log_llm_response(
        self,
        *,
        task_id: str | None,
        stage: str | None,
        model: str,
        response_text: str,
        parsed_payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist an LLM response, including raw text and parsed payload when available."""
        self.log_event(
            "llm_response",
            message=f"LLM response from model {model}",
            task_id=task_id,
            stage=stage,
            payload={
                "model": model,
                "response_text": response_text,
                "parsed_payload": parsed_payload,
            },
        )

    def log_exception(
        self,
        *,
        message: str,
        exc: BaseException,
        task_id: str | None = None,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist an exception with traceback details."""
        self.log_event(
            "exception",
            message=message,
            level="ERROR",
            task_id=task_id,
            stage=stage,
            payload={
                **(payload or {}),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            },
        )
