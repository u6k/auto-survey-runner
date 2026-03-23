"""Extracting stage.

The extraction stage is intentionally defensive:
- source text is reduced to a focused excerpt before it is sent to the model
- failures are isolated per source so one bad page does not abort the task
- a companion metadata file records why claims may be missing downstream
"""

from __future__ import annotations

import html
import hashlib
import re
from typing import Any

from ..dedupe import normalize_claim_text
from ..models import Claim, Task
from ..prompts import CLAIM_EXTRACTION_SCHEMA, EXTRACTOR_SYSTEM_PROMPT
from ..utils import read_json, write_json


def _keyword_terms(*values: str) -> list[str]:
    """Extract stable keywords from task and source metadata for line scoring."""
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for term in re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]{2,}", value.lower()):
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _select_relevant_excerpt(content: str, keywords: list[str], max_chars: int = 3000) -> str:
    """Keep only the most relevant lines instead of sending full page text."""
    lines = [line.strip() for line in content.splitlines()]
    lines = [line for line in lines if line]
    scored: list[tuple[int, str]] = []
    for line in lines:
        unique_line = line[:300]
        score = sum(1 for keyword in keywords if keyword and keyword in unique_line.lower())
        if score > 0:
            scored.append((score, unique_line))

    excerpt_lines: list[str] = []
    seen_lines: set[str] = set()
    for _, line in sorted(scored, key=lambda item: (-item[0], len(item[1]))):
        if line in seen_lines:
            continue
        seen_lines.add(line)
        excerpt_lines.append(line)
        if len("\n".join(excerpt_lines)) >= max_chars:
            break

    if not excerpt_lines:
        excerpt_lines = lines[:20]
    excerpt = "\n".join(excerpt_lines)
    return excerpt[:max_chars].strip()


def _build_extraction_prompt(task: Task, source: dict[str, Any]) -> str:
    """Build a compact extraction prompt that avoids flooding the model."""
    content = html.unescape(str(source.get("content", "")).strip())
    if not content:
        return ""
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    keywords = _keyword_terms(task.title, source.get("title", ""), source.get("uri", ""))
    compact_content = _select_relevant_excerpt(content, keywords, max_chars=3000)
    return (
        f"Source title: {source['title']}\n"
        f"Source URL: {source.get('uri', '')}\n"
        "Extract only factual claims that are explicitly supported by the source text below. "
        "Ignore navigation text, category lists, menus, marketing slogans, and duplicated fragments. "
        "If the excerpt is too generic to support a factual claim, return an empty claims array.\n\n"
        f"Content:\n{compact_content}"
    )


def extracting_stage(task: Task, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract claims from collected sources."""
    path = context["task_work_dir"] / "claims.json"
    meta_path = context["task_work_dir"] / "extraction_meta.json"
    if path.exists():
        return read_json(path, [])

    config = context["config"]
    client = context["client"]
    logger = context["logger"]
    store = context["store"]
    source_rows = read_json(context["task_work_dir"] / "collected_sources.json", [])
    extracted: list[Claim] = []
    failures: list[dict[str, str]] = []
    threshold = float(config["quality"]["claim_confidence_threshold"])
    extractor_extra_options = {"think": False} if bool(config["ollama"].get("extractor_disable_thinking", True)) else {}

    for source in source_rows:
        user_prompt = _build_extraction_prompt(task, source)
        if not user_prompt:
            continue
        try:
            result = client.chat_json(
                model=config["ollama"]["extractor_model"],
                system_prompt=EXTRACTOR_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema=CLAIM_EXTRACTION_SCHEMA,
                temperature=float(config["models"]["extractor_temperature"]),
                log_context={"task_id": task.task_id, "stage": "extracting"},
                extra_options=extractor_extra_options,
            )
        except Exception as exc:
            failures.append(
                {
                    "source_id": str(source.get("source_id", "")),
                    "title": str(source.get("title", "")),
                    "error_message": str(exc),
                }
            )
            if "empty content for structured output" in str(exc).lower():
                logger.log_event(
                    "claim_extraction_empty_response",
                    message="Extractor returned empty content for source; continuing with remaining sources",
                    level="WARNING",
                    task_id=task.task_id,
                    stage="extracting",
                    payload={"source_id": source.get("source_id"), "source_title": source.get("title"), "source_uri": source.get("uri")},
                )
            else:
                logger.log_exception(
                    message="Claim extraction failed for source; continuing with remaining sources",
                    exc=exc,
                    task_id=task.task_id,
                    stage="extracting",
                    payload={"source_id": source.get("source_id"), "source_title": source.get("title"), "source_uri": source.get("uri")},
                )
            continue

        for item in result.get("claims", []):
            confidence = float(item.get("confidence", 0.0))
            if confidence < threshold:
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            normalized = normalize_claim_text(text)
            claim_id = hashlib.sha1(f"{task.task_id}:{source['source_id']}:{normalized}".encode()).hexdigest()[:12]
            extracted.append(
                Claim(
                    claim_id=claim_id,
                    task_id=task.task_id,
                    source_id=source["source_id"],
                    text=text,
                    normalized_text=normalized,
                    confidence=confidence,
                    evidence=str(item.get("evidence", "")).strip(),
                )
            )

    logger.log_event(
        "claim_extraction",
        message="Extracted claims from sources",
        task_id=task.task_id,
        stage="extracting",
        payload={"source_count": len(source_rows), "claim_count": len(extracted), "failed_source_count": len(failures)},
    )
    write_json(
        meta_path,
        {
            "source_count": len(source_rows),
            "claim_count": len(extracted),
            "failed_source_count": len(failures),
            "failures": failures,
        },
    )
    store.append_claims(extracted)
    serialized = [claim.to_dict() for claim in extracted]
    write_json(path, serialized)
    return serialized
