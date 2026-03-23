"""Task stage implementations for the survey pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .dedupe import normalize_claim_text
from .models import Claim, Task, utc_now_iso
from .prompts import (
    CLAIM_EXTRACTION_SCHEMA,
    EXTRACTOR_SYSTEM_PROMPT,
    GLOBAL_DIGEST_SCHEMA,
    PLANNER_SYSTEM_PROMPT,
    QUERY_PLAN_SCHEMA,
    SYNTHESIZER_SYSTEM_PROMPT,
    TASK_SUMMARY_SCHEMA,
)
from .renderers import render_integrated_outputs
from .sources import collect_web_documents, load_local_documents, rank_sources
from .task_generation import derive_tasks
from .utils import read_json, write_json

STAGE_ORDER = ["planning", "collecting", "extracting", "summarizing", "spawning", "integrating", "snapshotting", "done"]


def _build_extraction_prompt(source: dict[str, Any]) -> str:
    """Build a compact extraction prompt that avoids flooding the model with raw HTML noise."""
    content = str(source.get("content", "")).strip()
    if not content:
        return ""
    compact_content = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    compact_content = compact_content[:6000]
    return (
        f"Source title: {source['title']}\n"
        f"Source URL: {source.get('uri', '')}\n"
        "Extract only factual claims that are explicitly supported by the source text below. "
        "Ignore navigation text, boilerplate, scripts, markup artifacts, and duplicated fragments.\n\n"
        f"Content:\n{compact_content}"
    )


# These stage functions are kept separate so the orchestrator can resume from any durable checkpoint
# instead of restarting a task from scratch after interruption or failure.
def planning_stage(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    """Generate query plan and candidate subtasks."""
    path = context["task_work_dir"] / "planning.json"
    if path.exists():
        return read_json(path, {})
    config = context["config"]
    client = context["client"]
    user_prompt = f"Task: {task.title}\nDescription: {task.description}"
    result = client.chat_json(
        model=config["ollama"]["planner_model"],
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=QUERY_PLAN_SCHEMA,
        temperature=float(config["models"]["planner_temperature"]),
        log_context={"task_id": task.task_id, "stage": "planning"},
    )
    write_json(path, result)
    return result


def collecting_stage(task: Task, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect local and web sources for the task."""
    path = context["task_work_dir"] / "collected_sources.json"
    if path.exists():
        return read_json(path, [])
    config = context["config"]
    logger = context["logger"]
    local_sources = load_local_documents(Path(config["paths"]["local_docs_dir"]), task.task_id)
    web_sources = collect_web_documents(task.task_id, task.planned_queries, int(config["collection"]["max_web_results"]), config, logger=logger)
    combined = local_sources + web_sources
    ranked = rank_sources(" ".join(task.planned_queries) or task.title, combined, int(config["collection"]["max_sources_per_task"]))
    logger.log_event(
        "source_collection",
        message="Collected and ranked sources",
        task_id=task.task_id,
        stage="collecting",
        payload={
            "local_source_count": len(local_sources),
            "web_source_count": len(web_sources),
            "ranked_source_count": len(ranked),
        },
    )
    context["store"].append_sources(ranked)
    serialized = [source.to_dict() for source in ranked]
    write_json(path, serialized)
    return serialized


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
    for source in source_rows:
        user_prompt = _build_extraction_prompt(source)
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
            )
        except Exception as exc:
            failures.append(
                {
                    "source_id": str(source.get("source_id", "")),
                    "title": str(source.get("title", "")),
                    "error_message": str(exc),
                }
            )
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

    user_prompt = "\n".join(claim["text"] for claim in claims[:100])
    result = client.chat_json(
        model=config["ollama"]["synthesizer_model"],
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=TASK_SUMMARY_SCHEMA,
        temperature=float(config["models"]["synthesizer_temperature"]),
        log_context={"task_id": task.task_id, "stage": "summarizing"},
    )
    summary_row = {
        "task_id": task.task_id,
        "task_title": task.title,
        **result,
    }
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


def spawning_stage(task: Task, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Create derived tasks if the planner proposed useful children."""
    path = context["task_work_dir"] / "spawned_tasks.json"
    if path.exists():
        return read_json(path, [])
    logger = context["logger"]
    planner_output = read_json(context["task_work_dir"] / "planning.json", {})
    derived = derive_tasks(task, planner_output, context["tasks"], context["config"])
    serialized = [child.to_dict() for child in derived]
    logger.log_event(
        "task_spawning",
        message="Evaluated derived tasks",
        task_id=task.task_id,
        stage="spawning",
        payload={"spawned_task_count": len(serialized)},
    )
    write_json(path, serialized)
    return serialized


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
        model=config["ollama"]["synthesizer_model"],
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt="\n".join(prompt_chunks)[:12000],
        schema=GLOBAL_DIGEST_SCHEMA,
        temperature=float(config["models"]["synthesizer_temperature"]),
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


def snapshotting_stage(task: Task, context: dict[str, Any]) -> dict[str, Any]:
    """Render integrated outputs for the current full survey state."""
    path = context["task_work_dir"] / "snapshot.json"
    if path.exists():
        return read_json(path, {})
    logger = context["logger"]
    global_digest = context["store"].read_global_digest()
    task_summaries = context["store"].read_task_summaries()
    claims = context["store"].read_claims()
    output_path = render_integrated_outputs(Path(context["config"]["paths"]["output_dir"]), task, global_digest, task_summaries, claims)
    payload = {"output_path": str(output_path)}
    logger.log_event("snapshot", message="Rendered integrated outputs", task_id=task.task_id, stage="snapshotting", payload=payload)
    write_json(path, payload)
    return payload
