"""Provider-agnostic LLM client using LiteLLM."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

try:
    import litellm  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    litellm = None


class BaseLlmClient(Protocol):
    """Common LLM client interface consumed by pipeline stages."""

    def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float,
        log_context: dict[str, Any] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call chat completion and return parsed JSON."""

    def chat_text(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        log_context: dict[str, Any] | None = None,
    ) -> str:
        """Call chat completion and return plain text."""


class LiteLlmClient:
    """Client for LiteLLM completion APIs."""

    def __init__(self, timeout: int = 120, logger: Any | None = None) -> None:
        if litellm is None:
            raise RuntimeError("litellm is required. Install dependencies from requirements.txt.")
        self.timeout = timeout
        self.logger = logger

    def _to_jsonable(self, value: Any) -> Any:
        """Best-effort conversion for structured logging payloads."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_jsonable(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return self._to_jsonable(model_dump())
            except Exception:
                pass
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return self._to_jsonable(to_dict())
            except Exception:
                pass
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except TypeError:
            return repr(value)

    def _log_raw_request(self, payload: dict[str, Any], log_context: dict[str, Any] | None = None) -> None:
        if self.logger is None:
            return
        self.logger.log_event(
            "llm_http_request",
            message=f"Sending raw LLM request to model {payload.get('model', 'unknown')}",
            task_id=(log_context or {}).get("task_id"),
            stage=(log_context or {}).get("stage"),
            payload={"request_payload": self._to_jsonable(payload)},
        )

    def _log_raw_response(self, payload: Any, log_context: dict[str, Any] | None = None, *, model: str | None = None) -> None:
        if self.logger is None:
            return
        self.logger.log_event(
            "llm_http_response",
            message=f"Received raw LLM response from model {model or 'unknown'}",
            task_id=(log_context or {}).get("task_id"),
            stage=(log_context or {}).get("stage"),
            payload={"response_payload": self._to_jsonable(payload)},
        )

    def _completion(self, payload: dict[str, Any]) -> Any:
        assert litellm is not None
        return litellm.completion(**payload)

    def _extract_content(self, result: Any) -> str:
        choices = getattr(result, "choices", None)
        if choices is None and isinstance(result, dict):
            choices = result.get("choices")
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if message is None and isinstance(first, dict):
            message = first.get("message", {})
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content", "")
        return "" if content is None else str(content)

    def _parse_json_content(self, content: Any) -> tuple[str, dict[str, Any]]:
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False), content
        if content is None:
            raise ValueError("LLM returned null content for structured output")

        raw_text = str(content)
        candidate = raw_text.strip()
        if not candidate:
            raise ValueError("LLM returned empty content for structured output")
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```$", "", candidate)
        try:
            return raw_text, json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = candidate[start : end + 1]
                return raw_text, json.loads(snippet)
            raise

    def _chat_json_with_prompt_fallback(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float,
        log_context: dict[str, Any] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        fallback_prompt = (
            f"{user_prompt}\n\n"
            "Return a valid JSON object that matches this schema exactly.\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": fallback_prompt},
            ],
            "temperature": temperature,
            "timeout": self.timeout,
            **(extra_options or {}),
        }
        self._log_raw_request(payload, log_context)
        result = self._completion(payload)
        self._log_raw_response(result, log_context, model=model)
        return self._parse_json_content(self._extract_content(result))

    def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float,
        log_context: dict[str, Any] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call completion with structured output and parse JSON."""
        if self.logger is not None:
            self.logger.log_llm_request(
                task_id=(log_context or {}).get("task_id"),
                stage=(log_context or {}).get("stage"),
                model=model,
                temperature=temperature,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
            )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "timeout": self.timeout,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema},
            },
            **(extra_options or {}),
        }
        raw_text = ""
        raw_result: Any = None
        try:
            self._log_raw_request(payload, log_context)
            result = self._completion(payload)
            raw_result = result
            self._log_raw_response(result, log_context, model=model)
            content = self._extract_content(result)
            try:
                raw_text, parsed = self._parse_json_content(content)
            except ValueError as exc:
                if "empty content" not in str(exc).lower() and "null content" not in str(exc).lower():
                    raise
                if self.logger is not None:
                    self.logger.log_event(
                        "llm_structured_output_fallback",
                        message="Retrying JSON call without schema mode after empty structured response",
                        task_id=(log_context or {}).get("task_id"),
                        stage=(log_context or {}).get("stage"),
                        payload={"model": model},
                    )
                raw_text, parsed = self._chat_json_with_prompt_fallback(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=schema,
                    temperature=temperature,
                    log_context=log_context,
                    extra_options=extra_options,
                )
            if self.logger is not None:
                self.logger.log_llm_response(
                    task_id=(log_context or {}).get("task_id"),
                    stage=(log_context or {}).get("stage"),
                    model=model,
                    response_text=raw_text,
                    parsed_payload=parsed,
                )
            return parsed
        except Exception as exc:
            if self.logger is not None:
                self.logger.log_exception(
                    message=f"LLM JSON call failed for model {model}",
                    exc=exc,
                    task_id=(log_context or {}).get("task_id"),
                    stage=(log_context or {}).get("stage"),
                    payload={
                        "model": model,
                        "temperature": temperature,
                        "raw_response_text": raw_text,
                        "raw_response_payload": self._to_jsonable(raw_result),
                    },
                )
            raise

    def chat_text(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        log_context: dict[str, Any] | None = None,
    ) -> str:
        """Call completion and return text content."""
        if self.logger is not None:
            self.logger.log_llm_request(
                task_id=(log_context or {}).get("task_id"),
                stage=(log_context or {}).get("stage"),
                model=model,
                temperature=temperature,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=None,
            )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "timeout": self.timeout,
        }
        self._log_raw_request(payload, log_context)
        result = self._completion(payload)
        self._log_raw_response(result, log_context, model=model)
        response_text = self._extract_content(result)
        if self.logger is not None:
            self.logger.log_llm_response(
                task_id=(log_context or {}).get("task_id"),
                stage=(log_context or {}).get("stage"),
                model=model,
                response_text=response_text,
                parsed_payload=None,
            )
        return response_text


def create_llm_client(config: dict[str, Any], logger: Any | None = None) -> BaseLlmClient:
    """Create an LLM client from configuration."""
    provider = str(config["llm"]["provider"]).strip().lower()
    timeout = int(config["llm"].get("timeout_seconds", 1800))
    if provider == "litellm":
        return LiteLlmClient(timeout=timeout, logger=logger)
    raise ValueError(f"Unsupported llm.provider: {provider}")
