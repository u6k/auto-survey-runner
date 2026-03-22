"""Small Ollama HTTP client wrapper for text and structured chat responses."""

from __future__ import annotations

import json
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

try:
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    requests = None


class OllamaClient:
    """Client for Ollama chat endpoints."""

    def __init__(self, base_url: str, timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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

    def chat_json(self, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any], temperature: float) -> dict[str, Any]:
        """Call Ollama chat with JSON schema structured output enabled."""
        payload = {
            "model": model,
            "format": schema,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        result = self._chat(payload)
        content = result.get("message", {}).get("content", "{}")
        if isinstance(content, dict):
            return content
        return json.loads(content)

    def chat_text(self, model: str, system_prompt: str, user_prompt: str, temperature: float) -> str:
        """Call Ollama chat and return plain text."""
        payload = {
            "model": model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        result = self._chat(payload)
        return result.get("message", {}).get("content", "")
