"""Source loading, searching, fetching, and simple ranking utilities."""

from __future__ import annotations

import hashlib
import os
import re
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
BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


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


def _http_get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    text, _ = _http_get_text(url, params=params, headers=headers, timeout=timeout)
    import json

    return json.loads(text)


def resolve_brave_api_key(config: dict[str, Any]) -> str | None:
    """Resolve the Brave Search API key from config or environment."""
    search_config = config.get("search", {}) if isinstance(config.get("search", {}), dict) else {}
    return search_config.get("brave_api_key") or os.getenv("BRAVE_SEARCH_API_KEY")


def brave_search(query: str, max_results: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Call the Brave Search Web API and return normalized result rows."""
    api_key = resolve_brave_api_key(config)
    if not api_key:
        raise RuntimeError("Brave Search API key is not configured. Set search.brave_api_key or BRAVE_SEARCH_API_KEY.")

    search_config = config.get("search", {}) if isinstance(config.get("search", {}), dict) else {}
    params = {
        "q": query,
        "count": min(max_results, 20),
        "search_lang": search_config.get("search_lang", "ja"),
        "country": search_config.get("country", "JP"),
        "extra_snippets": "true",
    }
    payload = _http_get_json(
        BRAVE_SEARCH_ENDPOINT,
        params=params,
        timeout=30,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
            "User-Agent": "auto-survey-runner/2.0",
        },
    )
    results = []
    for item in payload.get("web", {}).get("results", [])[:max_results]:
        snippets = []
        if item.get("description"):
            snippets.append(item["description"])
        snippets.extend(item.get("extra_snippets", []) or [])
        results.append(
            {
                "url": item.get("url", ""),
                "title": item.get("title") or item.get("url", ""),
                "snippet": "\n".join(snippets).strip(),
            }
        )
    return results


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch a URL and return content and detected mime type."""
    return _http_get_text(url, timeout=30, headers={"User-Agent": "auto-survey-runner/2.0"})


def collect_web_documents(task_id: str, queries: list[str], max_results: int, config: dict[str, Any], logger: Any | None = None) -> list[SourceDoc]:
    """Collect web documents for a set of queries via Brave Search API."""
    sources: list[SourceDoc] = []
    seen_urls: set[str] = set()
    for query in queries:
        try:
            results = brave_search(query, max_results=max_results, config=config)
            if logger is not None:
                logger.log_event(
                    "web_search_query",
                    message="Executed Brave Search query",
                    task_id=task_id,
                    stage="collecting",
                    payload={"query": query, "result_count": len(results)},
                )
        except Exception as exc:
            if logger is not None:
                logger.log_exception(
                    message="Brave Search query failed",
                    exc=exc,
                    task_id=task_id,
                    stage="collecting",
                    payload={"query": query},
                )
            continue
        for result in results:
            url = result["url"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                content, mime_type = fetch_url(url)
            except Exception as exc:
                if logger is not None:
                    logger.log_exception(
                        message="Fetching Brave Search result failed",
                        exc=exc,
                        task_id=task_id,
                        stage="collecting",
                        payload={"query": query, "url": url},
                    )
                continue
            source_id = hashlib.sha1(f"{task_id}:{url}".encode()).hexdigest()[:12]
            merged_content = result.get("snippet", "")
            if merged_content and content:
                merged_content = f"{result['title']}\n{merged_content}\n\n{content}"
            else:
                merged_content = content or merged_content
            sources.append(
                SourceDoc(
                    source_id=source_id,
                    task_id=task_id,
                    kind="web",
                    title=result.get("title") or slugify(url),
                    uri=url,
                    content=merged_content,
                    mime_type=mime_type,
                    rank_score=0.0,
                    metadata={"query": query, "snippet": result.get("snippet", "")},
                )
            )
    return sources
