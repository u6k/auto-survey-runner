"""Dataclasses shared across the survey runner pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """Unit of work for the orchestrated survey pipeline."""

    task_id: str
    title: str
    slug: str
    description: str
    priority: float
    depth: int
    status: str = "pending"
    current_stage: str = "planning"
    parent_task_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    retry_count: int = 0
    error_message: str | None = None
    planned_queries: list[str] = field(default_factory=list)
    collected_source_ids: list[str] = field(default_factory=list)
    extracted_claim_ids: list[str] = field(default_factory=list)
    summary_id: str | None = None
    spawned_task_ids: list[str] = field(default_factory=list)
    dedupe_key: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to a dictionary."""
        return asdict(self)


@dataclass
class SourceDoc:
    """Source document representation for local or web content."""

    source_id: str
    task_id: str
    kind: str
    title: str
    uri: str
    content: str
    mime_type: str
    rank_score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize source to a dictionary."""
        return asdict(self)


@dataclass
class Claim:
    """Atomic claim extracted from sources."""

    claim_id: str
    task_id: str
    source_id: str
    text: str
    normalized_text: str
    confidence: float
    evidence: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize claim to a dictionary."""
        return asdict(self)
