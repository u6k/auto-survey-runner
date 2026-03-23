"""Small Ollama HTTP client wrapper for text and structured chat responses."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

try:
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    requests = None


class OllamaClient:
    """Client for Ollama chat endpoints."""

    def __init__(self, base_url: str, timeout: int = 120, logger: Any | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logger

    def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if requests is not None:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        req = request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

    def _log_ollama_request(self, payload: dict[str, Any], log_context: dict[str, Any] | None = None) -> None:
        """Log the full request payload sent to the Ollama HTTP API."""
        if self.logger is None:
            return
        self.logger.log_event(
            "ollama_http_request",
            message=f"Sending raw Ollama request to model {payload.get('model', 'unknown')}",
            task_id=(log_context or {}).get("task_id"),
            stage=(log_context or {}).get("stage"),
            payload={"request_payload": payload},
        )

    def _log_ollama_response(self, response_payload: Any, log_context: dict[str, Any] | None = None, *, model: str | None = None) -> None:
        """Log the full response payload returned by the Ollama HTTP API."""
        if self.logger is None:
            return
        self.logger.log_event(
            "ollama_http_response",
            message=f"Received raw Ollama response from model {model or 'unknown'}",
            task_id=(log_context or {}).get("task_id"),
            stage=(log_context or {}).get("stage"),
            payload={"response_payload": response_payload},
        )

    def _parse_json_content(self, content: Any) -> tuple[str, dict[str, Any]]:
        """Parse structured output content, tolerating fenced or wrapped JSON."""
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False), content
        if content is None:
            raise ValueError("Ollama returned null content for structured output")

        raw_text = str(content)
        candidate = raw_text.strip()
        if not candidate:
            raise ValueError("Ollama returned empty content for structured output")
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
        """Retry structured output as plain text JSON when Ollama returns empty schema content."""
        fallback_prompt = (
            f"{user_prompt}\n\n"
            "Return a valid JSON object that matches this schema exactly.\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = {
            "model": model,
            "stream": False,
            "options": {"temperature": temperature, **(extra_options or {})},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": fallback_prompt},
            ],
        }
        self._log_ollama_request(payload, log_context)
        result = self._chat(payload)
        self._log_ollama_response(result, log_context, model=model)
        content = result.get("message", {}).get("content", "")
        return self._parse_json_content(content)

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
        """Call Ollama chat with JSON schema structured output enabled."""
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
            "format": schema,
            "stream": False,
            "options": {"temperature": temperature, **(extra_options or {})},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        raw_text = ""
        raw_result: Any = None
        try:
            self._log_ollama_request(payload, log_context)
            result = self._chat(payload)
            raw_result = result
            self._log_ollama_response(result, log_context, model=model)
            content = result.get("message", {}).get("content", "{}")
            try:
                raw_text, parsed = self._parse_json_content(content)
            except ValueError as exc:
                if "empty content" not in str(exc).lower() and "null content" not in str(exc).lower():
                    raise
                if self.logger is not None:
                    self.logger.log_event(
                        "llm_structured_output_fallback",
                        message="Retrying JSON call without Ollama schema mode after empty structured response",
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
                    payload={"model": model, "temperature": temperature, "raw_response_text": raw_text, "raw_response_payload": raw_result},
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
        """Call Ollama chat and return plain text."""
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
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            self._log_ollama_request(payload, log_context)
            result = self._chat(payload)
            self._log_ollama_response(result, log_context, model=model)
            response_text = result.get("message", {}).get("content", "")
            if self.logger is not None:
                self.logger.log_llm_response(
                    task_id=(log_context or {}).get("task_id"),
                    stage=(log_context or {}).get("stage"),
                    model=model,
                    response_text=response_text,
                )
            return response_text
        except Exception as exc:
            if self.logger is not None:
                self.logger.log_exception(
                    message=f"LLM text call failed for model {model}",
                    exc=exc,
                    task_id=(log_context or {}).get("task_id"),
                    stage=(log_context or {}).get("stage"),
                    payload={"model": model, "temperature": temperature},
                )
            raise
