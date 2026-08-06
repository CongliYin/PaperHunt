"""Complete, atomic daily cache for shared arXiv category fetches."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .fetcher import ArxivClient, fetch_papers_by_date


SCHEMA_VERSION = 1


class ArxivCacheError(RuntimeError):
    """Raised when an arXiv cache is incomplete, stale, or malformed."""


def normalize_categories(categories: Sequence[str]) -> list[str]:
    """Return a deterministic list with empty and duplicate categories removed."""
    normalized = {str(category).strip() for category in categories if str(category).strip()}
    return sorted(normalized)


def build_arxiv_cache(
    path: str | Path,
    *,
    start_date: str,
    end_date: str | None,
    categories: Sequence[str],
    client: ArxivClient | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Build a complete category cache, or reuse an already valid one."""
    target = Path(path)
    resolved_end_date = end_date or start_date
    required_categories = normalize_categories(categories)
    if not required_categories:
        raise ArxivCacheError("at least one arXiv category is required")

    if target.exists():
        payload = load_arxiv_cache(
            target,
            start_date=start_date,
            end_date=resolved_end_date,
            required_categories=required_categories,
        )
        if verbose:
            print(f"[arxiv-cache] hit {target} ({len(required_categories)} categories)")
        return payload

    if verbose:
        print(
            f"[arxiv-cache] building {target} for {start_date} → {resolved_end_date}; "
            f"categories={', '.join(required_categories)}"
        )

    shared_client = client or ArxivClient()
    category_payloads: dict[str, list[dict]] = {}
    for category in required_categories:
        category_payloads[category] = fetch_papers_by_date(
            start_date,
            resolved_end_date,
            category=category,
            verbose=verbose,
            client=shared_client,
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "start_date": start_date,
        "end_date": resolved_end_date,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "categories": category_payloads,
    }
    _write_atomic_json(target, payload)
    if verbose:
        total = sum(len(papers) for papers in category_payloads.values())
        print(
            f"[arxiv-cache] wrote {target} "
            f"({len(required_categories)} categories, {total} category entries)"
        )
    return payload


def load_arxiv_cache(
    path: str | Path,
    *,
    start_date: str,
    end_date: str | None,
    required_categories: Sequence[str],
) -> dict[str, Any]:
    """Load and strictly validate a complete arXiv category cache."""
    source = Path(path)
    resolved_end_date = end_date or start_date
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArxivCacheError(f"arXiv cache does not exist: {source}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ArxivCacheError(f"cannot read arXiv cache {source}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ArxivCacheError(f"arXiv cache root must be an object: {source}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ArxivCacheError(
            f"unsupported arXiv cache schema in {source}: {payload.get('schema_version')!r}"
        )
    if payload.get("start_date") != start_date or payload.get("end_date") != resolved_end_date:
        raise ArxivCacheError(
            f"arXiv cache date mismatch in {source}: expected "
            f"{start_date} → {resolved_end_date}"
        )

    cached_categories = payload.get("categories")
    if not isinstance(cached_categories, dict):
        raise ArxivCacheError(f"arXiv cache categories must be an object: {source}")

    for category in normalize_categories(required_categories):
        if category not in cached_categories:
            raise ArxivCacheError(f"arXiv cache {source} is missing category {category}")
        papers = cached_categories[category]
        if not isinstance(papers, list):
            raise ArxivCacheError(f"arXiv cache category {category} must be a list")
        for index, paper in enumerate(papers):
            if not isinstance(paper, dict) or not str(paper.get("arxiv_id") or "").strip():
                raise ArxivCacheError(
                    f"arXiv cache category {category} has invalid paper at index {index}"
                )

    return payload


def load_papers_from_cache(
    path: str | Path,
    *,
    start_date: str,
    end_date: str | None,
    categories: Sequence[str],
    hard_limit: int | None = None,
) -> list[dict]:
    """Load selected cached categories and de-duplicate papers by arXiv ID."""
    required_categories = normalize_categories(categories)
    payload = load_arxiv_cache(
        path,
        start_date=start_date,
        end_date=end_date,
        required_categories=required_categories,
    )

    if hard_limit is not None and hard_limit <= 0:
        return []

    by_id: dict[str, dict] = {}
    cached_categories = payload["categories"]
    reached_limit = False
    for category in required_categories:
        for paper in cached_categories[category]:
            arxiv_id = _clean_id(paper.get("arxiv_id", ""))
            if arxiv_id and arxiv_id not in by_id:
                by_id[arxiv_id] = paper
                if hard_limit is not None and len(by_id) >= hard_limit:
                    reached_limit = True
                    break
        if reached_limit:
            break

    return sorted(by_id.values(), key=lambda paper: paper.get("published_at", ""))


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise ArxivCacheError(f"cannot write arXiv cache {path}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _clean_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", str(arxiv_id).strip())
