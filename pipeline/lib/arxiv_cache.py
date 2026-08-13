"""Complete, atomic daily cache for shared arXiv category fetches."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .fetcher import ARXIV_API_BASE, ArxivClient, fetch_papers_by_date_multi_category


SCHEMA_VERSION = 1
RAW_CACHE_SCHEMA_VERSION = 1
RAW_FETCH_PROFILE = "legacy-submitted-date-v1"
RAW_MAX_RESULTS_PER_PAGE = 200
RAW_QUERY_SPEC = {
    "source": ARXIV_API_BASE,
    "date_field": "submittedDate",
    "max_results_per_page": RAW_MAX_RESULTS_PER_PAGE,
    "sort_by": "submittedDate",
    "sort_order": "ascending",
    "parser_profile": "atom-metadata-v1",
}


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
    raw_cache_dir: str | Path | None = None,
    refresh: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Build a complete daily bundle from persistent per-category raw caches."""
    target = Path(path)
    resolved_end_date = end_date or start_date
    required_categories = normalize_categories(categories)
    if not required_categories:
        raise ArxivCacheError("at least one arXiv category is required")

    if verbose:
        print(
            f"[arxiv-cache] building {target} for {start_date} → {resolved_end_date}; "
            f"categories={', '.join(required_categories)}"
        )

    # A stale bundle must never survive a failed rebuild. Completed raw category
    # files remain independently reusable and are written atomically below.
    target.unlink(missing_ok=True)
    raw_root = Path(raw_cache_dir) if raw_cache_dir is not None else target.parent / "raw"
    category_payloads: dict[str, list[dict]] = {}
    raw_paths: dict[str, Path] = {}
    missing_categories: list[str] = []
    for category in required_categories:
        raw_path = raw_category_cache_path(
            raw_root,
            start_date=start_date,
            end_date=resolved_end_date,
            category=category,
        )
        raw_paths[category] = raw_path
        papers: list[dict] | None = None
        if refresh:
            if verbose:
                print(f"[arxiv-raw] refresh {raw_path}")
        else:
            try:
                papers = load_raw_category_cache(
                    raw_path,
                    start_date=start_date,
                    end_date=resolved_end_date,
                    category=category,
                )
            except ArxivCacheError as exc:
                if verbose:
                    print(f"[arxiv-raw] miss {raw_path}: {exc}")
            else:
                if verbose:
                    print(f"[arxiv-raw] hit {raw_path} ({len(papers)} papers)")

        if papers is None:
            missing_categories.append(category)
        else:
            category_payloads[category] = papers

    # arXiv occasionally answers a valid-looking HTTP 200/Atom feed containing
    # no entries while the export service is unhealthy. An all-empty cache for
    # the broad daily category set is therefore not trustworthy and must be
    # retried rather than silently reused forever.
    if category_payloads and not _has_any_papers(category_payloads):
        missing_categories = list(required_categories)
        category_payloads.clear()
        if verbose:
            print("[arxiv-raw] cached categories are all empty; refetching the full set")

    fetched_categories: dict[str, list[dict]] = {}
    if missing_categories:
        shared_client = client or ArxivClient()
        fetched_papers = fetch_papers_by_date_multi_category(
            start_date,
            resolved_end_date,
            categories=missing_categories,
            max_results_per_page=RAW_MAX_RESULTS_PER_PAGE,
            verbose=verbose,
            client=shared_client,
        )
        _validate_papers(fetched_papers, context="combined arXiv response")
        fetched_categories = _partition_papers_by_category(
            fetched_papers,
            missing_categories,
        )
        category_payloads.update(fetched_categories)

    if not _has_any_papers(category_payloads):
        raise ArxivCacheError(
            "arXiv returned zero papers across all required categories; "
            "source data may not be ready"
        )

    # Publish newly fetched category files only after the complete result has
    # passed the all-empty guard. This prevents a transient empty response from
    # poisoning both raw and bundled caches.
    for category in missing_categories:
        papers = fetched_categories[category]
        raw_path = raw_paths[category]
        raw_payload = _raw_category_payload(
            start_date=start_date,
            end_date=resolved_end_date,
            category=category,
            papers=papers,
        )
        _write_atomic_json(raw_path, raw_payload)
        if verbose:
            print(f"[arxiv-raw] wrote {raw_path} ({len(papers)} papers)")

    for category in required_categories:
        if category not in category_payloads:
            raise ArxivCacheError(f"arXiv cache build is missing category {category}")

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


def raw_category_cache_path(
    raw_cache_dir: str | Path,
    *,
    start_date: str,
    end_date: str | None,
    category: str,
) -> Path:
    """Return the versioned cache path for one date range and category."""
    resolved_end_date = end_date or start_date
    _validate_iso_date(start_date)
    _validate_iso_date(resolved_end_date)
    normalized_category = str(category).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", normalized_category):
        raise ArxivCacheError(f"unsafe arXiv category for cache path: {category!r}")
    return (
        Path(raw_cache_dir)
        / RAW_FETCH_PROFILE
        / f"{start_date}__{resolved_end_date}"
        / f"{normalized_category}.json"
    )


def load_raw_category_cache(
    path: str | Path,
    *,
    start_date: str,
    end_date: str | None,
    category: str,
) -> list[dict]:
    """Strictly validate and return one complete raw category cache."""
    source = Path(path)
    resolved_end_date = end_date or start_date
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArxivCacheError("not found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ArxivCacheError(f"cannot read cache: {exc}") from exc

    expected_fingerprint = _raw_query_fingerprint(
        start_date=start_date,
        end_date=resolved_end_date,
        category=category,
    )
    expected = {
        "schema_version": RAW_CACHE_SCHEMA_VERSION,
        "fetch_profile": RAW_FETCH_PROFILE,
        "query_fingerprint": expected_fingerprint,
        "start_date": start_date,
        "end_date": resolved_end_date,
        "category": category,
        "complete": True,
    }
    if not isinstance(payload, dict):
        raise ArxivCacheError("root must be an object")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ArxivCacheError(
                f"{key} mismatch: expected {value!r}, got {payload.get(key)!r}"
            )

    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise ArxivCacheError("papers must be a list")
    _validate_papers(papers, context=f"raw category {category}")
    return papers


def _raw_category_payload(
    *,
    start_date: str,
    end_date: str,
    category: str,
    papers: list[dict],
) -> dict[str, Any]:
    return {
        "schema_version": RAW_CACHE_SCHEMA_VERSION,
        "fetch_profile": RAW_FETCH_PROFILE,
        "query_fingerprint": _raw_query_fingerprint(
            start_date=start_date,
            end_date=end_date,
            category=category,
        ),
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "complete": True,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "papers": papers,
    }


def _raw_query_fingerprint(*, start_date: str, end_date: str, category: str) -> str:
    query = {
        **RAW_QUERY_SPEC,
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
    }
    encoded = json.dumps(query, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_iso_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ArxivCacheError(f"invalid cache date: {value!r}") from exc


def _validate_papers(papers: list[Any], *, context: str) -> None:
    for index, paper in enumerate(papers):
        if not isinstance(paper, dict) or not str(paper.get("arxiv_id") or "").strip():
            raise ArxivCacheError(f"{context} has invalid paper at index {index}")


def _partition_papers_by_category(
    papers: Sequence[dict],
    categories: Sequence[str],
) -> dict[str, list[dict]]:
    """Partition a combined OR-query response into compatible raw category caches."""
    normalized_categories = normalize_categories(categories)
    results: dict[str, list[dict]] = {category: [] for category in normalized_categories}
    seen_ids: dict[str, set[str]] = {category: set() for category in normalized_categories}

    for paper in papers:
        paper_categories = {
            str(category).strip()
            for category in paper.get("categories", [])
            if str(category).strip()
        }
        primary_category = str(paper.get("primary_category") or "").strip()
        if primary_category:
            paper_categories.add(primary_category)

        arxiv_id = _clean_id(paper.get("arxiv_id", ""))
        for category in normalized_categories:
            if category not in paper_categories or arxiv_id in seen_ids[category]:
                continue
            seen_ids[category].add(arxiv_id)
            results[category].append(paper)

    for category in normalized_categories:
        results[category].sort(key=lambda paper: paper.get("published_at", ""))
    return results


def _has_any_papers(category_payloads: dict[str, list[dict]]) -> bool:
    return any(category_payloads.values())


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
