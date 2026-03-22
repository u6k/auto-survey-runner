"""Configuration loading and validation for auto_survey_runner_v2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments.
    yaml = None

REQUIRED_KEYS = [
    "research.topic",
    "research.description",
    "paths.state_dir",
    "paths.knowledge_dir",
    "paths.output_dir",
    "paths.local_docs_dir",
    "ollama.base_url",
    "ollama.planner_model",
    "ollama.extractor_model",
    "ollama.synthesizer_model",
    "runtime.max_steps_per_run",
    "runtime.max_retry_per_task",
    "runtime.max_tasks",
    "runtime.max_depth",
    "runtime.min_priority",
    "runtime.default_priority",
    "collection.max_web_results",
    "collection.max_sources_per_task",
    "collection.chunk_size",
    "collection.chunk_overlap",
    "models.planner_temperature",
    "models.extractor_temperature",
    "models.synthesizer_temperature",
    "quality.claim_confidence_threshold",
    "quality.spawn_confidence_threshold",
]

NUMERIC_KEYS = [
    "runtime.max_steps_per_run",
    "runtime.max_retry_per_task",
    "runtime.max_tasks",
    "runtime.max_depth",
    "runtime.min_priority",
    "runtime.default_priority",
    "collection.max_web_results",
    "collection.max_sources_per_task",
    "collection.chunk_size",
    "collection.chunk_overlap",
    "models.planner_temperature",
    "models.extractor_temperature",
    "models.synthesizer_temperature",
    "quality.claim_confidence_threshold",
    "quality.spawn_confidence_threshold",
]

ZERO_ONE_KEYS = [
    "models.planner_temperature",
    "models.extractor_temperature",
    "models.synthesizer_temperature",
    "quality.claim_confidence_threshold",
    "quality.spawn_confidence_threshold",
    "runtime.min_priority",
    "runtime.default_priority",
]


def _coerce_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _fallback_yaml_load(text: str) -> dict[str, Any]:
    """Parse a small YAML subset covering nested mappings and scalar values."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, remainder = line.split(":", 1)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if remainder.strip() == "":
            new_map: dict[str, Any] = {}
            current[key.strip()] = new_map
            stack.append((indent, new_map))
        else:
            current[key.strip()] = _coerce_scalar(remainder)
    return root


def _load_yaml_text(text: str) -> dict[str, Any]:
    if yaml is not None:
        parsed = yaml.safe_load(text)
    else:
        parsed = _fallback_yaml_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("Top-level YAML config must be a mapping")
    return parsed


def _get(config: dict[str, Any], dotted_key: str) -> Any:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Missing required config key: {dotted_key}")
        current = current[part]
    return current


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate required keys and numeric constraints."""
    for key in REQUIRED_KEYS:
        _get(config, key)

    for key in NUMERIC_KEYS:
        value = _get(config, key)
        if not isinstance(value, (int, float)):
            raise ValueError(f"Config key must be numeric: {key}")
        if isinstance(value, bool):
            raise ValueError(f"Config key must not be boolean: {key}")
        if value < 0:
            raise ValueError(f"Config key must be non-negative: {key}")

    for key in ZERO_ONE_KEYS:
        value = float(_get(config, key))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Config key must be within 0..1: {key}")

    chunk_size = int(_get(config, "collection.chunk_size"))
    chunk_overlap = int(_get(config, "collection.chunk_overlap"))
    if chunk_overlap >= chunk_size:
        raise ValueError("collection.chunk_overlap must be smaller than collection.chunk_size")

    return config


def load_config(path: Path) -> dict[str, Any]:
    """Load and validate a YAML config file."""
    raw = _load_yaml_text(path.read_text(encoding="utf-8"))
    config = validate_config(raw)
    base_dir = path.parent.resolve()
    for key in ["state_dir", "knowledge_dir", "output_dir", "local_docs_dir"]:
        config["paths"][key] = str((base_dir / config["paths"][key]).resolve())
    return config
