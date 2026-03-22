"""Normalization-based deduplication helpers for claims and tasks."""

from __future__ import annotations

import re


def normalize_claim_text(text: str) -> str:
    """Normalize claim text for duplicate detection."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text


def dedupe_claim_texts(claim_texts: list[str]) -> list[str]:
    """Return claim texts with normalization-based duplicates removed."""
    seen: set[str] = set()
    unique: list[str] = []
    for text in claim_texts:
        normalized = normalize_claim_text(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(text)
    return unique
