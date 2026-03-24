"""Prompt and schema definitions for planner, extractor, and synthesizer roles."""

from __future__ import annotations

QUERY_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "number"},
                },
                "required": ["title", "description", "priority"],
            },
        },
    },
    "required": ["queries", "subtasks"],
}

CLAIM_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                },
                "required": ["text", "confidence", "evidence"],
            },
        }
    },
    "required": ["claims"],
}

TASK_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_findings", "open_questions"],
}

GLOBAL_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["highlights", "open_questions", "next_actions"],
}

PLANNER_SYSTEM_PROMPT = (
    "You are a planning model for a Japanese-language research workflow. "
    "Produce concise search queries and candidate subtasks in valid JSON only. "
    "All natural-language string values in the JSON must be written in Japanese."
)
EXTRACTOR_SYSTEM_PROMPT = (
    "You are an extraction model for a Japanese-language research workflow. "
    "Read source text and output factual claims with confidence and evidence in valid JSON only. "
    "All natural-language string values in the JSON must be written in Japanese, even when the source is not Japanese."
)
SYNTHESIZER_SYSTEM_PROMPT = (
    "You are a synthesizer model for a Japanese-language research workflow. "
    "Merge claims into concise summaries and global digests in valid JSON only. "
    "All natural-language string values in the JSON must be written in Japanese."
)
