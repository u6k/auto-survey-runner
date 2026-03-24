"""Provider-agnostic LLM client interface and factory."""

from __future__ import annotations

from typing import Any, Protocol

from .ollama_client import OllamaClient


class BaseLlmClient(Protocol):
    """Common interface used by stages regardless of LLM provider."""

    def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float,
        log_context: dict[str, Any] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def chat_text(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        log_context: dict[str, Any] | None = None,
    ) -> str: ...


def create_llm_client(config: dict[str, Any], logger: Any | None = None) -> BaseLlmClient:
    """Create an LLM client from configuration.

    Current supported providers:
    - ollama / ollama_legacy / omitted: use existing Ollama HTTP client

    A dedicated LiteLLM-backed implementation will be added in a follow-up step.
    """

    llm_config = config.get("llm", {})
    provider = str(llm_config.get("provider", "ollama_legacy")).strip().lower()

    if provider in {"ollama", "ollama_legacy", ""}:
        ollama_cfg = config.get("ollama", {})
        base_url = str(ollama_cfg.get("base_url", "http://localhost:11434"))
        timeout_seconds = int(ollama_cfg.get("timeout_seconds", llm_config.get("timeout_seconds", 1800)))
        return OllamaClient(base_url=base_url, timeout=timeout_seconds, logger=logger)

    if provider == "litellm":
        raise NotImplementedError("llm.provider=litellm is not implemented yet. Set llm.provider to ollama_legacy for now.")

    raise ValueError(f"Unsupported llm.provider: {provider}")
