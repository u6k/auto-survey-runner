"""Render integrated outputs for the full survey state at each completed task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Task
from .utils import ensure_dir, slugify, write_json


def render_integrated_outputs(output_dir: Path, task: Task, global_digest: dict[str, Any], task_summaries: list[dict[str, Any]], claims: list[dict[str, Any]]) -> Path:
    """Render full integrated outputs as of the current task completion."""
    folder = output_dir / f"task_{task.task_id}_{slugify(task.slug)}"
    ensure_dir(folder)

    report_json = {
        "task": task.to_dict(),
        "global_digest": global_digest,
        "task_summaries": task_summaries,
        "claims": claims,
    }
    write_json(folder / "integrated_report.json", report_json)

    md_lines = [
        f"# 統合レポート（{task.title}）",
        "",
        "## ハイライト",
        *[f"- {line}" for line in global_digest.get("highlights", [])],
        "",
        "## 未解決の問い",
        *[f"- {line}" for line in global_digest.get("open_questions", [])],
        "",
        "## 次のアクション",
        *[f"- {line}" for line in global_digest.get("next_actions", [])],
        "",
        "## タスク別サマリー",
    ]
    for summary in task_summaries:
        md_lines.extend([f"### {summary.get('task_title', '不明なタスク')}", summary.get("summary", ""), ""])
    (folder / "integrated_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    manifest = {
        "task_id": task.task_id,
        "task_title": task.title,
        "files": ["integrated_report.json", "integrated_report.md", "manifest.json"],
    }
    write_json(folder / "manifest.json", manifest)
    return folder
