"""Integrating stage.

This stage merges task summaries and accumulated claims into the global digest.
It also writes a fallback digest when the run does not yet have structured
claims so that external consumers always get a valid output artifact.
"""

from __future__ import annotations

from typing import Any

from ..models import Task, utc_now_iso
from ..prompts import GLOBAL_DIGEST_SCHEMA, SYNTHESIZER_SYSTEM_PROMPT
from ..utils import read_json, write_json


def integrating_stage(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    """Update the global digest from accumulated task summaries and claims."""
    path = context["task_work_dir"] / "global_digest.json"
    if path.exists():
        digest = read_json(path, {})
        context["store"].write_global_digest(digest)
        return digest

    config = context["config"]
    client = context["client"]
    logger = context["logger"]
    task_summaries = context["store"].read_task_summaries()
    claims = context["store"].read_claims()
    extraction_meta = read_json(context["task_work_dir"] / "extraction_meta.json", {})
    if not claims:
        failed_source_count = int(extraction_meta.get("failed_source_count", 0))
        result = {
            "highlights": ["まだ統合対象となる知見は蓄積されていません。"],
            "open_questions": [
                "抽出モデルが空応答を返して claim 化に失敗していないか確認が必要です。"
                if failed_source_count
                else "Brave Search API の検索結果やローカル文書が空だった原因調査が必要です。"
            ],
            "next_actions": [
                "extractor モデルやタイムアウト設定を見直し、必要ならより小さい入力で再実行してください。"
                if failed_source_count
                else "利用可能な source を増やして再実行してください。"
            ],
            "updated_at": utc_now_iso(),
        }
        logger.log_event(
            "global_digest_fallback",
            message="Generated fallback global digest because no claims were available",
            task_id=task.task_id,
            stage="integrating",
            payload={"failed_source_count": failed_source_count},
        )
        context["store"].write_global_digest(result)
        write_json(path, result)
        return result

    prompt_chunks = [summary.get("summary", "") for summary in task_summaries]
    prompt_chunks.extend(claim["text"] for claim in claims[:200])
    result = client.chat_json(
        model=config["llm"]["model_map"]["synthesizer"],
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt="\n".join(prompt_chunks)[:12000],
        schema=GLOBAL_DIGEST_SCHEMA,
        temperature=float(config["llm"]["temperature"]["synthesizer"]),
        log_context={"task_id": task.task_id, "stage": "integrating"},
    )
    result["updated_at"] = utc_now_iso()
    logger.log_event(
        "global_digest",
        message="Updated global digest",
        task_id=task.task_id,
        stage="integrating",
        payload={"task_summary_count": len(task_summaries), "claim_count": len(claims)},
    )
    context["store"].write_global_digest(result)
    write_json(path, result)
    return result
