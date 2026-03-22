"""Source loading, searching, fetching, and simple ranking utilities."""

from __future__ import annotations

import hashlib
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

try:
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    requests = None

from .models import SourceDoc
from .utils import slugify

SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm"}


def load_local_documents(local_docs_dir: Path, task_id: str) -> list[SourceDoc]:
    """Load supported local documents from disk."""
    sources: list[SourceDoc] = []
    if not local_docs_dir.exists():
        return sources
    for path in local_docs_dir.iterdir():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        source_id = hashlib.sha1(f"{task_id}:{path.resolve()}".encode()).hexdigest()[:12]
        sources.append(
            SourceDoc(
                source_id=source_id,
                task_id=task_id,
                kind="local",
                title=path.stem,
                uri=str(path.resolve()),
                content=content,
                mime_type="text/plain",
                rank_score=0.0,
                metadata={"path": str(path.resolve())},
            )
        )
    return sources


def score_source(query: str, content: str) -> float:
    """Score content with a simple lexical overlap heuristic."""
    query_terms = {term for term in re.findall(r"\w+", query.lower()) if len(term) > 2}
    content_terms = set(re.findall(r"\w+", content.lower()))
    if not query_terms:
        return 0.0
    return len(query_terms & content_terms) / len(query_terms)


def rank_sources(query: str, sources: list[SourceDoc], limit: int) -> list[SourceDoc]:
    """Rank sources by lexical overlap and return the top results."""
    ranked = []
    for source in sources:
        source.rank_score = score_source(query, source.content)
        ranked.append(source)
    return sorted(ranked, key=lambda item: item.rank_score, reverse=True)[:limit]


def _http_get_text(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[str, str]:
    if requests is not None:
        response = requests.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.text, response.headers.get("Content-Type", "text/plain").split(";")[0]

    if params:
        url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(url, headers=headers or {}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "text/plain").split(";")[0]
            return response.read().decode("utf-8", errors="ignore"), content_type
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"HTTP request failed: {exc}") from exc


def duckduckgo_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Run a simple DuckDuckGo HTML search scrape."""
    html, _ = _http_get_text(
        "https://duckduckgo.com/html/",
        params={"q": query},
        timeout=30,
        headers={"User-Agent": "auto-survey-runner/2.0"},
    )
    matches = re.findall(r'nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>', html, re.S)
    results = []
    for href, title in matches[:max_results]:
        results.append({"url": unescape(href), "title": re.sub(r"<.*?>", "", unescape(title))})
    return results


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch a URL and return content and detected mime type."""
    return _http_get_text(url, timeout=30, headers={"User-Agent": "auto-survey-runner/2.0"})


def collect_web_documents(task_id: str, queries: list[str], max_results: int) -> list[SourceDoc]:
    """Collect web documents for a set of queries."""
    sources: list[SourceDoc] = []
    seen_urls: set[str] = set()
    for query in queries:
        for result in duckduckgo_search(query, max_results=max_results):
            url = result["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                content, mime_type = fetch_url(url)
            except Exception:
                continue
            source_id = hashlib.sha1(f"{task_id}:{url}".encode()).hexdigest()[:12]
            sources.append(
                SourceDoc(
                    source_id=source_id,
                    task_id=task_id,
                    kind="web",
                    title=result.get("title") or slugify(url),
                    uri=url,
                    content=content,
                    mime_type=mime_type,
                    rank_score=0.0,
                    metadata={"query": query},
                )
            )
    return sources
