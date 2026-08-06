#!/usr/bin/env python3
"""arXiv paper ranker v2.

Two-phase pipeline:
  Phase 1 (--phase1-only):
    Fetch → Select primary domain → Enrich → Automated scoring
    Output: Temporary phase1.json for LLM evaluation

  Finalize (--finalize):
    Merge LLM scores → Final HTML report → Cleanup intermediates

Usage:
  python rank_pipeline.py --phase1-only --domain 3d-vision --start-date 2026-05-19 --end-date 2026-05-22 --work-dir /path/to/project
  python rank_pipeline.py --finalize --domain 3d-vision --phase1-json reports/.../tmp/phase1.json --llm-scores reports/.../tmp/llm_scores.json --work-dir /path/to/project
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, SCRIPT_DIR)

from lib.fetcher import fetch_papers_by_date_multi_category
from lib.arxiv_cache import load_papers_from_cache
from lib.selector import load_selection_policies, select_papers_for_domain
from lib.enricher import fetch_hf_daily_papers, enrich_papers, AuthorMetricsCache
from lib.utils import log_normalize, clamp
from lib.scorer import score_phase1_json
from lib.translator import enrich_zh
from lib.figures import extract_figures
from lib.blob_uploader import FigureStorage


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
WEIGHTS = {
    "topic_relevance":   0.40,
    "llm_assessment":    0.30,
    "open_source":       0.10,
    "community_heat":    0.05,
    "author_reputation": 0.05,
    "venue_signal":      0.05,
    "generality":        0.05,
}


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_domain_config(domain: str, domains_dir: str) -> dict:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency PyYAML. Install dependencies with: pip install requests PyYAML"
        ) from exc

    domain_dir = os.path.join(domains_dir, domain)
    if not os.path.isdir(domain_dir):
        available = []
        if os.path.isdir(domains_dir):
            available = sorted(
                name for name in os.listdir(domains_dir)
                if os.path.isdir(os.path.join(domains_dir, name))
            )
        hint = f" Available domains: {', '.join(available)}." if available else ""
        raise FileNotFoundError(f"Domain '{domain}' not found at {domain_dir}.{hint}")

    domain_yaml = os.path.join(domain_dir, "domain.yaml")
    topic_yaml = os.path.join(domain_dir, "topic_keywords.yaml")
    scoring_md = os.path.join(domain_dir, "scoring_criteria.md")
    for path in (domain_yaml, topic_yaml, scoring_md):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Required domain file missing: {path}")

    with open(domain_yaml, "r", encoding="utf-8") as f:
        meta = yaml.safe_load(f) or {}
    with open(topic_yaml, "r", encoding="utf-8") as f:
        topic_cfg = yaml.safe_load(f) or {}
    categories = meta.get("arxiv_categories") or [meta.get("arxiv_category") or "cs.CV"]
    if isinstance(categories, str):
        categories = [categories]

    return {
        "id": domain,
        "dir": domain_dir,
        "display_name": meta.get("display_name") or domain.replace("-", " ").title(),
        "description": meta.get("description", ""),
        "arxiv_categories": categories,
        "output_suffix": meta.get("output_suffix") or f"{domain}_paper_rank",
        "default_top_pct": float(meta.get("default_top_pct", 0.4)),
        "topic_cfg": topic_cfg,
        "scoring_criteria_path": scoring_md,
    }


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------
def _normalize_kw_to_regex(kw: str) -> str:
    chunks: list[str] = []
    i = 0
    while i < len(kw):
        ch = kw[i]
        if ch.isspace() or ch == "-":
            chunks.append(r"[\s\-]+")
            while i < len(kw) and (kw[i].isspace() or kw[i] == "-"):
                i += 1
            continue
        chunks.append(ch if ch.isalnum() else re.escape(ch))
        i += 1
    body = "".join(chunks)
    return rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])"


def _compile_kw_pattern(keywords: list) -> re.Pattern:
    parts = [_normalize_kw_to_regex(kw.strip()) for kw in keywords if kw.strip()]
    if not parts:
        return re.compile(r"$^")
    return re.compile("|".join(parts), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Phase 1 scoring
# ---------------------------------------------------------------------------
def score_topic_relevance(paper: dict, topic_cfg: dict) -> Tuple[float, Optional[str]]:
    title = paper.get("title", "") or ""
    abstract = paper.get("abstract", "") or ""
    text = f"{title}\n{abstract}"

    tiers = topic_cfg.get("tiers", {})
    best_coeff = 0.0
    best_cat: str | None = None
    hit_count = 0

    for tier_spec in tiers.values():
        coeff = float(tier_spec.get("coefficient", 0.0))
        for cat_name, keywords in tier_spec.get("categories", {}).items():
            if not keywords:
                continue
            matches = set(m.lower() for m in _compile_kw_pattern(keywords).findall(text))
            if matches:
                hit_count += len(matches)
                if coeff > best_coeff:
                    best_coeff = coeff
                    best_cat = cat_name

    if best_coeff == 0.0:
        return 0.0, None

    base = best_coeff * 0.8
    bonus = min(max(hit_count - 1, 0) * 0.04, 0.2)
    return clamp(base + bonus), best_cat


def score_venue_signal(paper: dict) -> float:
    comments = paper.get("comments", "") or ""
    if not comments:
        return 0.0
    m = re.search(
        r"\b(?:accepted|published|appear(?:s|ing)?|oral|spotlight|poster)\b"
        r".*?\b(CVPR|ICCV|ECCV|NeurIPS|ICML|ICLR|AAAI|IJCAI|"
        r"SIGGRAPH|3DV|WACV|BMVC|ACCV|CoRL|RSS|ICRA|IROS|"
        r"ACM\s*MM|TPAMI|TIP|TOG|IJCV)\b",
        comments, re.IGNORECASE,
    )
    if not m:
        return 0.0
    top = {"CVPR","ICCV","ECCV","NEURIPS","ICML","ICLR","SIGGRAPH","TOG","TPAMI"}
    return 1.0 if m.group(1).upper() in top else 0.7


def score_community_heat(paper: dict) -> float:
    enriched = paper.get("enriched", {})
    if not enriched.get("hf_listed", False):
        return 0.0
    return clamp(0.6 + log_normalize(enriched.get("hf_upvotes", 0) or 0, max_val=200) * 0.4)


def score_author_reputation(paper: dict) -> float:
    enriched = paper.get("enriched", {})
    h_first = enriched.get("first_author_h_index")
    h_last = enriched.get("last_author_h_index")
    fs = log_normalize(h_first, max_val=50) if enriched.get("first_author_found") and h_first and h_first >= 0 else 0.3
    ls = log_normalize(h_last, max_val=50) if enriched.get("last_author_found") and h_last and h_last >= 0 else 0.3
    return clamp(0.4 * fs + 0.6 * ls)


def score_open_source(paper: dict) -> float:
    e = paper.get("enriched", {})
    s = 0.0
    if e.get("github_url"):       s += 0.5
    if e.get("project_page_url"): s += 0.4
    if e.get("code_promised") and not e.get("github_url"): s += 0.2
    if e.get("has_video_demo"):   s += 0.1
    return clamp(s)


def score_generality(paper: dict, topic_cfg: dict) -> float:
    title = paper.get("title", "") or ""
    abstract = paper.get("abstract", "") or ""
    text = f"{title}\n{abstract}"
    for level_cfg in topic_cfg.get("generality", {}).values():
        if not isinstance(level_cfg, dict):
            continue
        kw = level_cfg.get("keywords", [])
        if kw and _compile_kw_pattern(kw).search(text):
            return clamp(float(level_cfg.get("score", 0.4)))
    return 0.4


def compute_domain_multiplier(paper: dict, topic_cfg: dict, topic_score: float) -> float:
    penalty_cfg = topic_cfg.get("domain_penalties", {})
    if not penalty_cfg:
        return 1.0
    text = f"{paper.get('title','')}\n{paper.get('abstract','')}"
    min_mult = 1.0
    matched: list[str] = []
    for cat, spec in penalty_cfg.items():
        kw = spec.get("keywords", [])
        if kw and _compile_kw_pattern(kw).search(text):
            mult = float(spec.get("multiplier", 1.0))
            if mult < min_mult:
                min_mult = mult
            matched.append(cat)
    if topic_score >= 0.85:
        min_mult = max(min_mult, 0.9)
    elif topic_score >= 0.7:
        min_mult = max(min_mult, 0.85)
    if matched:
        paper["domain_penalties"] = matched
    return clamp(min_mult)


def compute_phase1_scores(papers: list, topic_cfg: dict) -> list:
    for p in papers:
        ts, cat = score_topic_relevance(p, topic_cfg)
        if cat:
            p["strategic_category"] = cat
        dm = compute_domain_multiplier(p, topic_cfg, ts)
        scores = {
            "topic_relevance":   ts,
            "open_source":       score_open_source(p),
            "community_heat":    score_community_heat(p),
            "author_reputation": score_author_reputation(p),
            "venue_signal":      score_venue_signal(p),
            "generality":        score_generality(p, topic_cfg),
            "llm_assessment":    0.5,  # neutral default
            "domain_multiplier": dm,
        }
        weighted = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
        p["scores"] = scores
        p["phase1_score"] = weighted * dm
    return papers


# ---------------------------------------------------------------------------
# Final score computation (after LLM scores are merged)
# ---------------------------------------------------------------------------
def compute_final_scores(papers: list) -> list:
    for p in papers:
        scores = p.get("scores", {})
        dm = scores.get("domain_multiplier", 1.0)
        weighted = sum(scores.get(k, 0) * WEIGHTS[k] for k in WEIGHTS)
        p["total_score"] = weighted * dm
    return sorted(papers, key=lambda p: p.get("total_score", 0), reverse=True)


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------
def _paper_to_json_safe(paper: dict) -> dict:
    """Strip non-serializable fields for JSON output."""
    safe = {}
    for k, v in paper.items():
        if k == "filter_hits":
            safe[k] = v
        elif isinstance(v, (str, int, float, bool, type(None), list, dict)):
            safe[k] = v
    return safe


def save_phase1_json(papers: list, path: str, metadata: dict) -> None:
    data = {
        "metadata": metadata,
        "papers": [_paper_to_json_safe(p) for p in papers],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_phase1_json(path: str) -> Tuple[dict, list]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("metadata", {}), data.get("papers", [])


def load_llm_scores(path: str) -> dict:
    """Load LLM scores JSON: {arxiv_id: {novelty, ..., llm_avg, comment}}."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_llm_scores(papers: list, llm_scores: dict) -> int:
    """Merge LLM assessments into paper records in-place."""
    merged_count = 0
    for p in papers:
        arxiv_id = re.sub(r"v\d+$", "", p.get("arxiv_id", ""))
        if arxiv_id in llm_scores:
            assessment = llm_scores[arxiv_id]
            p["llm_assessment"] = assessment
            p.setdefault("scores", {})["llm_assessment"] = float(assessment.get("llm_avg", 0.5))
            merged_count += 1
    return merged_count


def filter_by_llm_domain_fit(
    papers: list,
    *,
    minimum_domain_fit: float,
    verbose: bool = True,
) -> list:
    """Keep only papers with a valid LLM assessment above the relevance gate."""
    kept = []
    rejected_missing = 0
    rejected_fit = 0
    for paper in papers:
        assessment = paper.get("llm_assessment")
        if not isinstance(assessment, dict):
            rejected_missing += 1
            continue
        try:
            domain_fit = float(assessment["domain_fit"])
        except (KeyError, TypeError, ValueError):
            rejected_missing += 1
            continue
        if not 0.0 <= domain_fit <= 1.0 or domain_fit < minimum_domain_fit:
            rejected_fit += 1
            continue
        kept.append(paper)

    if verbose:
        print(
            f"  [domain-fit] kept={len(kept)} / total={len(papers)} "
            f"(minimum={minimum_domain_fit:.2f}, missing={rejected_missing}, "
            f"below={rejected_fit})"
        )
    return kept


def _pdf_url_json(paper: dict) -> str:
    aid = re.sub(r"v\d+$", "", (paper.get("arxiv_id") or "").strip())
    return f"https://arxiv.org/pdf/{aid}" if aid else _pdf_url(paper)


def _author_affiliations_json(paper: dict) -> list[dict]:
    authors = paper.get("authors") or []
    raw_affiliations = paper.get("author_affiliations") or []
    by_name: dict[str, list[str]] = {}

    for item in raw_affiliations:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        affiliations = [
            str(value).strip()
            for value in item.get("affiliations") or []
            if str(value).strip()
        ]
        if name and affiliations:
            by_name[name] = affiliations

    enriched = paper.get("enriched") or {}
    if authors and not by_name.get(authors[0]):
        affiliations = [
            str(value).strip()
            for value in enriched.get("first_author_affiliations") or []
            if str(value).strip()
        ]
        if affiliations:
            by_name[authors[0]] = affiliations
    if len(authors) >= 2 and not by_name.get(authors[-1]):
        affiliations = [
            str(value).strip()
            for value in enriched.get("last_author_affiliations") or []
            if str(value).strip()
        ]
        if affiliations:
            by_name[authors[-1]] = affiliations

    return [
        {"name": name, "affiliations": by_name[name]}
        for name in authors
        if by_name.get(name)
    ]


def _build_tags_json(paper: dict) -> list[str]:
    tags: list[str] = []
    e = paper.get("enriched", {})
    if e.get("hf_upvotes") and e["hf_upvotes"] > 0:
        tags.append(f"HF Daily ★{e['hf_upvotes']}")
    if e.get("github_url"):
        tags.append("GitHub")
    if e.get("project_page_url"):
        tags.append("Project Page")
    if e.get("code_promised") and not e.get("github_url"):
        tags.append("Code soon")
    h_max = max(e.get("first_author_h_index") or 0, e.get("last_author_h_index") or 0)
    if h_max >= 30:
        tags.append(f"h={h_max}")
    cat = paper.get("strategic_category")
    if cat:
        tags.append(cat.replace("_", " "))
    if paper.get("scores", {}).get("venue_signal", 0) > 0:
        tags.append("Accepted")
    return tags


def _links_json(paper: dict) -> dict:
    enriched = paper.get("enriched", {})
    return {
        "github": enriched.get("github_url"),
        "project_page": enriched.get("project_page_url"),
    }


def _other_score(scores: dict) -> float:
    keys = ["open_source", "community_heat", "author_reputation", "venue_signal", "generality"]
    total_w = sum(WEIGHTS[k] for k in keys)
    return sum(scores.get(k, 0) * WEIGHTS[k] for k in keys) / total_w if total_w else 0.0


def _load_existing_figure_assets(data_dir: Path) -> dict[str, dict]:
    """Collect already-published figure URLs from generated JSON files."""
    assets: dict[str, dict] = {}
    if not data_dir.exists():
        return assets

    for path in data_dir.rglob("*.json"):
        if path.name == "index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - stale output must not block a run
            print(f"[figures-cache] skipped {path}: {exc}")
            continue

        figures = payload.get("figures")
        if isinstance(figures, list):
            arxiv_id = re.sub(r"v\d+$", "", str(payload.get("arxiv_id") or path.stem).strip())
            usable_figures = [
                figure
                for figure in figures
                if isinstance(figure, dict) and figure.get("src")
            ]
            if arxiv_id and usable_figures:
                record = assets.setdefault(arxiv_id, {})
                record.setdefault("figures", usable_figures)
                inferred_thumb = _infer_thumb_from_figures(usable_figures)
                if inferred_thumb:
                    record.setdefault("thumb", inferred_thumb)

        papers = payload.get("papers")
        if isinstance(papers, list):
            for paper in papers:
                if not isinstance(paper, dict):
                    continue
                arxiv_id = re.sub(r"v\d+$", "", str(paper.get("arxiv_id") or "").strip())
                thumb = str(paper.get("thumb") or "").strip()
                if arxiv_id and thumb:
                    record = assets.setdefault(arxiv_id, {})
                    record.setdefault("thumb", thumb)

    return assets


def _infer_thumb_from_figures(figures: list[dict]) -> str:
    for figure in figures:
        src = str(figure.get("src") or "").strip()
        if re.search(r"/fig\d+\.webp$", src):
            return re.sub(r"/fig\d+\.webp$", "/thumb.webp", src)
    return ""


def update_index_json(data_dir: Path, domain: str, display_name: str, date: str, paper_count: int) -> None:
    index_path = data_dir / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"generated_at": "", "domains": [], "entries": []}

    domains = {d["id"]: d for d in index.get("domains", [])}
    domains[domain] = {"id": domain, "display_name": display_name}
    entries = [
        e for e in index.get("entries", [])
        if not (e.get("domain") == domain and e.get("date") == date)
    ]
    entries.append(
        {
            "domain": domain,
            "date": date,
            "paper_count": paper_count,
            "file": f"{domain}/{date}.json",
        }
    )
    entries.sort(key=lambda e: (e["domain"], e["date"]), reverse=True)
    index = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "domains": sorted(domains.values(), key=lambda d: d["display_name"]),
        "entries": entries,
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def emit_json_outputs(
    ranked_papers: list,
    metadata: dict,
    *,
    data_dir: str | Path,
    figures_work_dir: str | Path,
    skip_translation: bool = False,
    skip_figures: bool = False,
    storage_backend: str | None = None,
) -> tuple[Path, int]:
    """Emit index, list, and detail JSON files consumed by the Next.js frontend."""
    domain = metadata["domain"]
    display_name = metadata.get("display_name") or domain.replace("-", " ").title()
    date = metadata.get("start_date") or metadata.get("date") or datetime.utcnow().date().isoformat()
    generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    data_dir = Path(data_dir)
    domain_dir = data_dir / domain
    detail_dir = domain_dir / date
    detail_dir.mkdir(parents=True, exist_ok=True)

    storage = FigureStorage(
        backend=storage_backend,
        public_dir=Path.cwd() / "web" / "public",
    )
    existing_figure_assets = _load_existing_figure_assets(data_dir)

    list_items = []
    emitted = 0
    for paper in ranked_papers:
        if not paper.get("llm_assessment"):
            continue
        arxiv_id = re.sub(r"v\d+$", "", paper.get("arxiv_id", ""))
        zh = {}
        if not skip_translation:
            try:
                zh = enrich_zh(paper)
            except Exception as exc:  # noqa: BLE001 - one paper must not stop the run
                print(f"[emit-json] {arxiv_id}: translation skipped ({exc})")

        figures_payload = {"figures": [], "thumb": ""}
        if not skip_figures:
            cached_assets = existing_figure_assets.get(arxiv_id) or {}
            if cached_assets.get("figures"):
                print(f"[figures-cache] {arxiv_id}: reusing existing figures")
                figures_payload = {
                    "figures": cached_assets.get("figures", []),
                    "thumb": cached_assets.get("thumb", ""),
                }
            else:
                figures_payload = extract_figures(
                    arxiv_id,
                    figures_work_dir,
                    storage=storage,
                )
                if figures_payload.get("figures"):
                    existing_figure_assets[arxiv_id] = {
                        "figures": figures_payload.get("figures", []),
                        "thumb": figures_payload.get("thumb") or "",
                    }

        scores = paper.get("scores", {})
        detail_file = f"{domain}/{date}/{arxiv_id}.json"
        detail = {
            "arxiv_id": arxiv_id,
            "title": paper.get("title", ""),
            "title_zh": zh.get("title_zh") or paper.get("title", ""),
            "authors": paper.get("authors", []),
            "author_affiliations": _author_affiliations_json(paper),
            "published_at": paper.get("published_at", ""),
            "abs_url": paper.get("abs_url", f"https://arxiv.org/abs/{arxiv_id}"),
            "pdf_url": _pdf_url_json(paper),
            "links": _links_json(paper),
            "abstract_en": paper.get("abstract", ""),
            "abstract_zh": zh.get("abstract_zh") or "",
            "key_points_zh": zh.get("key_points_zh") or [],
            "llm_assessment": paper.get("llm_assessment", {}),
            "scores": scores,
            "enriched": paper.get("enriched", {}),
            "figures": figures_payload.get("figures", []),
        }
        (data_dir / detail_file).write_text(
            json.dumps(detail, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        list_scores = {
            "topic_relevance": scores.get("topic_relevance", 0),
            "llm_assessment": scores.get("llm_assessment", 0),
            "domain_fit": (paper.get("llm_assessment") or {}).get("domain_fit", 0),
            "other": _other_score(scores),
        }
        list_items.append(
            {
                "arxiv_id": arxiv_id,
                "title": paper.get("title", ""),
                "title_zh": detail["title_zh"],
                "authors": paper.get("authors", []),
                "total_score": paper.get("total_score", 0),
                "scores": list_scores,
                "tags": _build_tags_json(paper),
                "tldr_zh": zh.get("tldr_zh") or "",
                "detail_file": detail_file,
                "thumb": figures_payload.get("thumb") or "",
            }
        )
        emitted += 1

    list_payload = {
        "domain": domain,
        "display_name": display_name,
        "date": date,
        "generated_at": generated_at,
        "papers": list_items,
    }
    list_path = domain_dir / f"{date}.json"
    list_path.write_text(json.dumps(list_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    update_index_json(data_dir, domain, display_name, date, emitted)
    return list_path, emitted


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{display_name} arXiv Ranking v2 - {date_range}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    margin: 0; padding: 24px; background: #fafafa; color: #222; line-height: 1.5;
  }}
  .container {{ max-width: 1300px; margin: 0 auto; }}
  h1 {{ margin-bottom: 4px; font-size: 22px; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  table {{
    width: 100%; border-collapse: collapse; background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-radius: 6px; overflow: hidden;
  }}
  th, td {{ text-align: left; padding: 10px 12px; vertical-align: top; }}
  th {{
    background: #f0f0f0; font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; color: #555; border-bottom: 1px solid #ddd;
    cursor: pointer; user-select: none; position: sticky; top: 0; z-index: 1;
  }}
  th:hover {{ background: #e0e0e0; }}
  tr {{ border-bottom: 1px solid #eee; }}
  tr:last-child {{ border-bottom: none; }}
  .rank {{ font-size: 18px; font-weight: 700; color: #888; width: 36px; }}
  .score {{ font-size: 18px; font-weight: 700; color: #d9480f; width: 56px; text-align: right; }}
  .title-cell {{ width: 36%; }}
  .title {{ font-weight: 600; font-size: 14px; margin-bottom: 3px; line-height: 1.35; }}
  .title a {{ color: #1864ab; text-decoration: none; }}
  .title a:hover {{ text-decoration: underline; }}
  .authors {{ font-size: 12px; color: #666; margin-bottom: 4px; }}
  .tags {{ margin-top: 5px; }}
  .tag {{
    display: inline-block; font-size: 10px; padding: 1px 6px;
    border-radius: 3px; margin-right: 4px; margin-bottom: 2px;
    background: #e7f5ff; color: #1864ab; font-weight: 500;
  }}
  .tag.gold {{ background: #fff3bf; color: #845d00; }}
  .tag.green {{ background: #d3f9d8; color: #2b8a3e; }}
  .tag.purple {{ background: #f3d9fa; color: #862e9c; }}
  .tag.red {{ background: #ffe3e3; color: #c92a2a; }}
  .dim-cell {{ width: 34%; }}
  .dim {{ display: flex; align-items: center; font-size: 11px; margin-bottom: 3px; }}
  .dim-name {{ width: 110px; color: #666; flex-shrink: 0; }}
  .dim-bar {{ flex: 1; height: 8px; background: #eee; border-radius: 4px; overflow: hidden; }}
  .dim-fill {{ height: 100%; border-radius: 4px; }}
  .dim-fill.auto {{ background: linear-gradient(90deg, #4dabf7, #1864ab); }}
  .dim-fill.llm {{ background: linear-gradient(90deg, #f783ac, #c2255c); }}
  .dim-fill.domain {{ background: linear-gradient(90deg, #69db7c, #2b8a3e); }}
  .dim-val {{ width: 36px; text-align: right; color: #555; font-variant-numeric: tabular-nums; }}
  .llm-comment {{
    font-size: 11px; color: #862e9c; margin-top: 4px; font-style: italic;
    padding: 3px 6px; background: #faf0ff; border-radius: 3px;
  }}
  details {{ margin-top: 6px; }}
  details summary {{ cursor: pointer; font-size: 11px; color: #1864ab; user-select: none; padding: 2px 0; }}
  details[open] summary {{ margin-bottom: 4px; }}
  .abstract {{
    font-size: 12px; color: #555; padding: 8px; background: #f8f9fa;
    border-radius: 4px; border-left: 2px solid #adb5bd;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{display_name} arXiv Ranking v2</h1>
  <div class="meta">
    Date range: {date_range} &middot; Total candidates: {total}
    &middot; Showing top {showing} (LLM-evaluated)
    &middot; Weights: Topic {w_topic}% | LLM {w_llm}% | Other {w_other}%
    (open-source {w_os}% + community {w_ch}% + author {w_ar}% + venue {w_vs}% + generality {w_gen}%)
  </div>
  <table id="ranking-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">#</th>
        <th onclick="sortTable(1)">Score</th>
        <th>Paper</th>
        <th>Dimensions</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</div>
<script>
function sortTable(col) {{
  const table = document.getElementById("ranking-table");
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const asc = table.dataset.sortCol == col && table.dataset.sortDir !== "asc";
  rows.sort((a, b) => {{
    let va = parseFloat(a.cells[col].textContent.trim()) || 0;
    let vb = parseFloat(b.cells[col].textContent.trim()) || 0;
    return asc ? va - vb : vb - va;
  }});
  rows.forEach(r => tbody.appendChild(r));
  table.dataset.sortCol = col;
  table.dataset.sortDir = asc ? "asc" : "desc";
}}
</script>
</body>
</html>"""


def _fmt_authors(authors: list, max_n: int = 3) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) <= max_n:
        return ", ".join(authors)
    return ", ".join(authors[:max_n]) + f", et al. ({len(authors)} authors)"


def _pdf_url(paper: dict) -> str:
    aid = (paper.get("arxiv_id") or "").strip()
    if aid:
        return f"https://arxiv.org/pdf/{aid}"
    m = re.search(r"arxiv\.org/abs/([^?#\"']+)", paper.get("abs_url", ""))
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else paper.get("abs_url", "")


def _build_tags(paper: dict) -> str:
    tags: list[str] = []
    e = paper.get("enriched", {})
    if e.get("hf_upvotes") and e["hf_upvotes"] > 0:
        tags.append(f'<span class="tag gold">HF Daily ★{e["hf_upvotes"]}</span>')
    if e.get("github_url"):
        tags.append('<span class="tag green">GitHub</span>')
    if e.get("project_page_url"):
        tags.append('<span class="tag green">Project Page</span>')
    if e.get("code_promised") and not e.get("github_url"):
        tags.append('<span class="tag">Code soon</span>')
    h_max = max(e.get("first_author_h_index") or 0, e.get("last_author_h_index") or 0)
    if h_max >= 30:
        tags.append(f'<span class="tag purple">h={h_max}</span>')
    cat = paper.get("strategic_category")
    if cat:
        tags.append(f'<span class="tag purple">{escape(cat.replace("_", " "))}</span>')
    if paper.get("scores", {}).get("venue_signal", 0) > 0:
        tags.append('<span class="tag red">Accepted</span>')
    penalties = paper.get("domain_penalties") or []
    if penalties:
        tags.append(f'<span class="tag">Penalty: {escape(", ".join(p.replace("_"," ") for p in penalties[:2]))}</span>')
    return " ".join(tags)


def _build_dim_bars(paper: dict) -> str:
    scores = paper.get("scores", {})

    # Compute "Other" as weighted average of non-topic, non-LLM dimensions
    other_keys = ["open_source", "community_heat", "author_reputation", "venue_signal", "generality"]
    other_weights = {k: WEIGHTS[k] for k in other_keys}
    other_total_w = sum(other_weights.values())
    other_val = sum(scores.get(k, 0) * other_weights[k] for k in other_keys) / other_total_w if other_total_w else 0

    dims = [
        ("Topic Relevance", scores.get("topic_relevance", 0.0), "auto"),
        ("LLM Assessment",  scores.get("llm_assessment", 0.5),  "llm"),
        ("Other",            other_val,                          "domain"),
    ]
    parts: list[str] = []
    for label, val, cls in dims:
        pct = val * 100
        parts.append(
            f'<div class="dim">'
            f'<span class="dim-name">{label}</span>'
            f'<div class="dim-bar"><div class="dim-fill {cls}" style="width:{pct:.0f}%"></div></div>'
            f'<span class="dim-val">{pct:.0f}</span>'
            f'</div>'
        )
    # Domain multiplier — only show if penalized
    dm = scores.get("domain_multiplier", 1.0)
    if dm < 1.0:
        pct = dm * 100
        parts.append(
            f'<div class="dim">'
            f'<span class="dim-name" style="color:#c92a2a">Domain Penalty</span>'
            f'<div class="dim-bar"><div class="dim-fill domain" style="width:{pct:.0f}%"></div></div>'
            f'<span class="dim-val" style="color:#c92a2a">&times;{dm:.2f}</span>'
            f'</div>'
        )
    # LLM comment
    llm = paper.get("llm_assessment", {})
    comment = llm.get("comment", "")
    if comment:
        parts.append(f'<div class="llm-comment">{escape(comment)}</div>')
    return "".join(parts)


def _build_row(rank: int, paper: dict) -> str:
    title = escape(paper.get("title", "Untitled"))
    pdf = _pdf_url(paper)
    authors = _fmt_authors(paper.get("authors", []))
    abstract = escape(paper.get("abstract", "")).replace("\n", " ")
    total = paper.get("total_score", 0.0) * 100
    return f"""
      <tr>
        <td class="rank">{rank}</td>
        <td class="score">{total:.1f}</td>
        <td class="title-cell">
          <div class="title"><a href="{escape(pdf)}" target="_blank">{title}</a></div>
          <div class="authors">{escape(authors)}</div>
          <div class="tags">{_build_tags(paper)}</div>
          <details><summary>Abstract</summary><div class="abstract">{abstract}</div></details>
        </td>
        <td class="dim-cell">{_build_dim_bars(paper)}</td>
      </tr>"""


def generate_html_report(papers: list, output_path: str, *, date_range: str = "",
                         display_name: str = "Paper",
                         total_candidates: int = 0, top_n: int | None = None) -> None:
    show = papers if top_n is None else papers[:top_n]
    rows = "\n".join(_build_row(i + 1, p) for i, p in enumerate(show))
    w_other = int((WEIGHTS["open_source"] + WEIGHTS["community_heat"] +
                    WEIGHTS["author_reputation"] + WEIGHTS["venue_signal"] +
                    WEIGHTS["generality"]) * 100)
    html = _HTML_TEMPLATE.format(
        display_name=escape(display_name),
        date_range=escape(date_range), total=total_candidates, showing=len(show), rows=rows,
        w_topic=int(WEIGHTS["topic_relevance"]*100), w_llm=int(WEIGHTS["llm_assessment"]*100),
        w_other=w_other,
        w_os=int(WEIGHTS["open_source"]*100), w_ch=int(WEIGHTS["community_heat"]*100),
        w_ar=int(WEIGHTS["author_reputation"]*100), w_vs=int(WEIGHTS["venue_signal"]*100),
        w_gen=int(WEIGHTS["generality"]*100),
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Main: Phase 1
# ---------------------------------------------------------------------------
def run_phase1(args):
    verbose = not args.quiet
    domain_cfg = _load_domain_config(args.domain, args.domains_dir)

    end_date = args.end_date or args.start_date

    # Date-based report directory: reports/2026-05-19/ or reports/2026-05-19_2026-05-22/
    date_folder = (
        f"{args.start_date}_{end_date}"
        if end_date != args.start_date
        else args.start_date
    )
    work_dir = args.work_dir
    report_dir = os.path.join(work_dir, "reports", args.domain, date_folder)
    tmp_dir = os.path.join(report_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    json_path = args.output_json or os.path.join(tmp_dir, "phase1.json")
    Path(json_path).unlink(missing_ok=True)

    topic_cfg = domain_cfg["topic_cfg"]
    top_pct = args.top_pct if args.top_pct is not None else domain_cfg["default_top_pct"]
    selection_policies = load_selection_policies(args.domains_dir)
    if args.domain not in selection_policies:
        raise RuntimeError(f"No selection policy configured for domain {args.domain}")
    selection_policy = selection_policies[args.domain]

    # Step 1: Fetch
    print(
        f"[1/5] Fetching arXiv papers for {domain_cfg['display_name']} "
        f"({args.start_date} → {end_date}; categories={', '.join(domain_cfg['arxiv_categories'])})..."
    )
    if args.arxiv_cache:
        print(f"  [arxiv-cache] reading {args.arxiv_cache}")
        papers = load_papers_from_cache(
            args.arxiv_cache,
            start_date=args.start_date,
            end_date=args.end_date,
            categories=domain_cfg["arxiv_categories"],
            hard_limit=args.limit,
        )
    else:
        papers = fetch_papers_by_date_multi_category(
            args.start_date,
            args.end_date,
            categories=domain_cfg["arxiv_categories"],
            hard_limit=args.limit,
            verbose=verbose,
        )
    if not papers:
        print("No papers fetched. Exiting.")
        return

    # Step 2: Deterministic primary-domain selection
    print(f"[2/5] Selecting primary-domain {domain_cfg['display_name']} papers...")
    domain_papers = select_papers_for_domain(
        papers,
        domain=args.domain,
        policies=selection_policies,
        verbose=verbose,
    )
    if not domain_papers:
        print(f"No {domain_cfg['display_name']} papers after primary-domain selection. Exiting.")
        return

    # Step 3: HF Daily Papers
    print(f"[3/5] Fetching HF Daily Papers index...")
    hf_index = fetch_hf_daily_papers(args.start_date, args.end_date, verbose=verbose)

    # Step 4: Enrich (S2 author lookup)
    print(f"[4/5] Enriching {len(domain_papers)} papers...")
    s2_cache = AuthorMetricsCache(os.path.join(tmp_dir, "s2_authors.json"))
    enrich_papers(domain_papers, hf_index=hf_index, cache=s2_cache, verbose=verbose)

    # Step 5: Phase 1 scoring
    print(f"[5/5] Phase 1: automated scoring...")
    compute_phase1_scores(domain_papers, topic_cfg)
    domain_papers.sort(key=lambda p: p.get("phase1_score", 0), reverse=True)

    if args.top_n:
        top_n = args.top_n
    else:
        top_n = max(10, int(len(domain_papers) * top_pct))
    top_papers = domain_papers[:top_n]
    print(f"  Phase 1 done. Top {len(top_papers)} selected ({len(top_papers)}/{len(domain_papers)} = {len(top_papers)/len(domain_papers)*100:.0f}%).")

    # Step 6: (Skipped — introductions not needed for LLM evaluation)

    # Save Phase 1 JSON
    metadata = {
        "start_date": args.start_date,
        "end_date": end_date,
        "domain": args.domain,
        "display_name": domain_cfg["display_name"],
        "arxiv_categories": domain_cfg["arxiv_categories"],
        "output_suffix": domain_cfg["output_suffix"],
        "scoring_criteria_path": domain_cfg["scoring_criteria_path"],
        "minimum_llm_domain_fit": selection_policy.minimum_llm_domain_fit,
        "total_fetched": len(papers),
        "total_filtered": len(domain_papers),
        "top_n": top_n,
        "date_range": (
            args.start_date if end_date == args.start_date
            else f"{args.start_date} → {end_date}"
        ),
    }
    save_phase1_json(domain_papers, json_path, metadata)
    print(f"\n  Phase 1 JSON (temp): {json_path}")

    print(f"\nTotal {domain_cfg['display_name']} candidates: {len(domain_papers)}")
    print(f"\nPhase 1 Top 10:")
    for i, p in enumerate(domain_papers[:10]):
        print(f"  {i+1:2d}. [{p['phase1_score']*100:5.1f}] {p.get('title','')[:70]}")

    llm_scores_path = os.path.join(tmp_dir, "llm_scores.json")
    print(f"\n>> Next step: LLM assessment on top-{top_n} papers (top {top_n/len(domain_papers)*100:.0f}%).")
    print(f"   Read {json_path} and produce LLM scores JSON,")
    print(f"   then run: python {__file__} --finalize --domain {args.domain} --phase1-json {json_path} --llm-scores {llm_scores_path}")


# ---------------------------------------------------------------------------
# Main: Finalize (merge LLM scores + generate final HTML)
# ---------------------------------------------------------------------------
def run_finalize(args):
    print(f"[finalize] Reading Phase 1 data: {args.phase1_json}")
    metadata, papers = load_phase1_json(args.phase1_json)
    domain = metadata.get("domain") or args.domain
    domain_cfg = _load_domain_config(domain, args.domains_dir)
    display_name = metadata.get("display_name") or domain_cfg["display_name"]
    output_suffix = metadata.get("output_suffix") or domain_cfg["output_suffix"]

    print(f"[finalize] Reading LLM scores: {args.llm_scores}")
    llm_scores = load_llm_scores(args.llm_scores)

    # Merge LLM scores into papers
    merged_count = merge_llm_scores(papers, llm_scores)
    print(f"[finalize] Merged LLM scores for {merged_count} papers.")

    # Final ranking — a valid LLM domain-fit score is a hard publication gate.
    ranked_all = compute_final_scores(papers)
    minimum_domain_fit = float(metadata.get("minimum_llm_domain_fit", 0.65))
    ranked_llm = filter_by_llm_domain_fit(
        ranked_all,
        minimum_domain_fit=minimum_domain_fit,
    )

    # Output — same date-based directory as phase1
    date_range = metadata.get("date_range", "")
    start = metadata.get("start_date", "")
    end = metadata.get("end_date", start)
    date_folder = f"{start}_{end}" if end != start else start
    work_dir = args.work_dir
    report_dir = os.path.join(work_dir, "reports", domain, date_folder)
    os.makedirs(report_dir, exist_ok=True)
    html_path = args.output or os.path.join(report_dir, f"{date_folder}_{output_suffix}.html")

    generate_html_report(ranked_llm, html_path, date_range=date_range,
                         display_name=display_name,
                         total_candidates=len(ranked_all))

    if args.emit_json:
        list_path, emitted = emit_json_outputs(
            ranked_llm,
            metadata,
            data_dir=args.data_dir,
            figures_work_dir=args.figures_work_dir,
            skip_translation=args.skip_translation,
            skip_figures=args.skip_figures,
            storage_backend=args.storage_backend,
        )
        print(f"  JSON list: {list_path} ({emitted} papers)")

    # Cleanup: keep tmp by default for cache/re-runs.
    tmp_dir = os.path.join(report_dir, "tmp")
    if args.cleanup_tmp and os.path.isdir(tmp_dir):
        import shutil
        shutil.rmtree(tmp_dir)
        print(f"  Cleaned up: {tmp_dir}/")

    print(f"\n  Final HTML: {html_path}")
    print(
        f"  Total papers: {len(ranked_all)} "
        f"(showing {len(ranked_llm)} above the LLM domain-fit gate)"
    )
    print(f"\nFinal Top 10:")
    for i, p in enumerate(ranked_llm[:10]):
        llm = p.get("llm_assessment", {})
        llm_avg = llm.get("llm_avg", "-")
        if isinstance(llm_avg, float):
            llm_avg = f"{llm_avg:.2f}"
        print(f"  {i+1:2d}. [{p['total_score']*100:5.1f}] LLM={llm_avg}  {p.get('title','')[:65]}")


def run_score_llm(args):
    print(f"[score-llm] Reading Phase 1 data: {args.phase1_json}")
    scores = score_phase1_json(
        args.phase1_json,
        args.llm_scores,
        batch_size=args.llm_batch_size,
        max_workers=args.llm_workers,
    )
    print(f"[score-llm] Wrote {len(scores)} LLM assessments: {args.llm_scores}")


def run_emit_json(args):
    print(f"[emit-json] Reading Phase 1 data: {args.phase1_json}")
    metadata, papers = load_phase1_json(args.phase1_json)
    print(f"[emit-json] Reading LLM scores: {args.llm_scores}")
    llm_scores = load_llm_scores(args.llm_scores)
    merged = merge_llm_scores(papers, llm_scores)
    print(f"[emit-json] Merged LLM scores for {merged} papers.")
    minimum_domain_fit = float(metadata.get("minimum_llm_domain_fit", 0.65))
    ranked_llm = filter_by_llm_domain_fit(
        compute_final_scores(papers),
        minimum_domain_fit=minimum_domain_fit,
    )
    list_path, emitted = emit_json_outputs(
        ranked_llm,
        metadata,
        data_dir=args.data_dir,
        figures_work_dir=args.figures_work_dir,
        skip_translation=args.skip_translation,
        skip_figures=args.skip_figures,
        storage_backend=args.storage_backend,
    )
    print(f"[emit-json] Wrote {list_path} ({emitted} papers)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Configurable arXiv paper ranker v2")

    # Mode selection
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--phase1-only", action="store_true",
                      help="Run Phase 1 only: fetch → select → enrich → score → JSON")
    mode.add_argument("--score-llm", action="store_true",
                      help="Score top papers from Phase 1 with an OpenAI-compatible LLM")
    mode.add_argument("--finalize", action="store_true",
                      help="Merge LLM scores with Phase 1 data and generate final HTML")
    mode.add_argument("--emit-json-only", action="store_true",
                      help="Merge LLM scores and emit frontend JSON without HTML")

    # Phase 1 args
    parser.add_argument("--start-date", help="UTC start date YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="UTC end date YYYY-MM-DD")
    parser.add_argument("--top-pct", type=float, default=None,
                        help="Top percentage of papers for LLM assessment (default: domain config)")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Override: fixed number of top papers (overrides --top-pct)")
    parser.add_argument("--limit", type=int, default=None, help="Debug: hard limit on fetch")
    parser.add_argument(
        "--arxiv-cache",
        default=None,
        help="Strict daily arXiv cache created by run_daily.py",
    )
    parser.add_argument("--output-json", default=None, help="Phase 1 JSON output path")

    # Finalize args
    parser.add_argument("--phase1-json", help="Path to Phase 1 JSON file")
    parser.add_argument("--llm-scores", help="Path to LLM scores JSON file")
    parser.add_argument("--llm-batch-size", type=int, default=16)
    parser.add_argument("--llm-workers", type=int, default=None)

    # Frontend JSON args
    parser.add_argument("--emit-json", action="store_true",
                        help="When used with --finalize, also emit frontend JSON")
    parser.add_argument("--data-dir", default=os.path.join(os.getcwd(), "web", "public", "data"),
                        help="Frontend data output directory")
    parser.add_argument("--figures-work-dir", default=os.path.join(os.getcwd(), "tmp", "figures"),
                        help="Temporary figure extraction work directory")
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--skip-figures", action="store_true")
    parser.add_argument("--storage-backend", choices=["blob", "repo"], default=None)

    # Common
    parser.add_argument("--domain", default="3d-vision",
                        help="Domain config name under --domains-dir (default: 3d-vision)")
    parser.add_argument("--domains-dir", default=os.path.join(SCRIPT_DIR, "domains"),
                        help="Directory containing domain configs (default: paper-rank/domains)")
    parser.add_argument("--work-dir", default=os.getcwd(),
                        help="Working directory for reports output (default: cwd)")
    parser.add_argument("--output", default=None, help="HTML output path")
    parser.add_argument("--cleanup-tmp", action="store_true",
                        help="Delete report tmp directory after finalize")
    parser.add_argument("--quiet", action="store_true")

    args = parser.parse_args()

    if args.phase1_only:
        if not args.start_date:
            parser.error("--phase1-only requires --start-date")
        try:
            run_phase1(args)
        except RuntimeError as exc:
            parser.exit(1, f"error: {exc}\n")
    elif args.finalize:
        if not args.phase1_json or not args.llm_scores:
            parser.error("--finalize requires --phase1-json and --llm-scores")
        try:
            run_finalize(args)
        except RuntimeError as exc:
            parser.exit(1, f"error: {exc}\n")
    elif args.score_llm:
        if not args.phase1_json or not args.llm_scores:
            parser.error("--score-llm requires --phase1-json and --llm-scores")
        try:
            run_score_llm(args)
        except RuntimeError as exc:
            parser.exit(1, f"error: {exc}\n")
    elif args.emit_json_only:
        if not args.phase1_json or not args.llm_scores:
            parser.error("--emit-json-only requires --phase1-json and --llm-scores")
        try:
            run_emit_json(args)
        except RuntimeError as exc:
            parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
