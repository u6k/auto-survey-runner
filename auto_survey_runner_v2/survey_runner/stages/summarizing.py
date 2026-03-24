"""Summarizing stage.

This stage creates a task-level summary. If extraction produced no claims, it
still writes a durable fallback summary so downstream integration can continue.
"""

from __future__ import annotations

from typing import Any

from ..models import Task
from ..prompts import (
    SYNTHESIZER_SYSTEM_PROMPT,
    TASK_SUMMARY_BRIEFING_INSTRUCTION,
    TASK_SUMMARY_SCHEMA,
)
from ..utils import read_json, write_json


def summarizing_stage(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    """Summarize extracted claims for the task."""
    path = context["task_work_dir"] / "summary.json"
    if path.exists():
        return read_json(path, {})

    config = context["config"]
    client = context["client"]
    logger = context["logger"]
    claims = read_json(context["task_work_dir"] / "claims.json", [])
    extraction_meta = read_json(context["task_work_dir"] / "extraction_meta.json", {})
    if not claims:
        failed_source_count = int(extraction_meta.get("failed_source_count", 0))
        source_count = int(extraction_meta.get("source_count", 0))
        if failed_source_count:
            summary_text = "extractor の応答が不安定で claim を構造化抽出できなかったため、暫定サマリーのみを出力しました。"
            open_questions = [
                "Ollama extractor モデルが空応答を返した原因（モデル容量・負荷・structured output 対応）を確認する必要があります。",
                f"抽出対象 {source_count} 件のうち {failed_source_count} 件で抽出エラーが発生しており、source 自体は取得できていても claim 化に失敗しています。",
            ]
        else:
            summary_text = "十分な source / claim を収集できなかったため、暫定サマリーのみを出力しました。"
            open_questions = [
                "Brave Search API の検索結果やローカル文書が取得できていない原因を確認する必要があります。",
                "対象トピックに対して利用可能な一次情報を追加収集する必要があります。",
            ]
        summary_row = {
            "task_id": task.task_id,
            "task_title": task.title,
            "summary": summary_text,
            "key_findings": [],
            "open_questions": open_questions,
        }
        logger.log_event(
            "task_summary_fallback",
            message="Generated fallback summary because no claims were available",
            task_id=task.task_id,
            stage="summarizing",
            payload={"claim_count": 0, "failed_source_count": failed_source_count},
        )
        context["store"].append_task_summary(summary_row)
        write_json(path, summary_row)
        return summary_row

    claim_lines = [f"- {claim['text']}" for claim in claims[:100]]
    user_prompt = (
        f"{TASK_SUMMARY_BRIEFING_INSTRUCTION}\n\n"
        "Use the claims below as source material and return valid JSON matching the schema.\n"
        "- summary: include heading and bullet-point structure in Japanese prose.\n"
        "- key_findings: provide concise bullet-ready findings in Japanese.\n"
        "- open_questions: list unresolved items in Japanese.\n\n"
        "Claims:\n"
        + "\n".join(claim_lines)
    )
    result = client.chat_json(
        model=config["llm"]["model_map"]["synthesizer"],
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=TASK_SUMMARY_SCHEMA,
        temperature=float(config["llm"]["temperature"]["synthesizer"]),
        log_context={"task_id": task.task_id, "stage": "summarizing"},
    )
    summary_row = {"task_id": task.task_id, "task_title": task.title, **result}
    logger.log_event(
        "task_summary",
        message="Generated task summary",
        task_id=task.task_id,
        stage="summarizing",
        payload={"claim_count": len(claims), "summary_keys": sorted(summary_row.keys())},
    )
    context["store"].append_task_summary(summary_row)
    write_json(path, summary_row)
    return summary_row
