"""LLM scoring for top-N papers from phase1.json."""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .llm_client import LLMClient
from .utils import clamp

LLM_DIMS = [
    "novelty",
    "problem_significance",
    "potential_impact",
    "paradigm_shift",
    "lasting_value",
]


def score_phase1_json(
    phase1_json: str,
    output_json: str,
    *,
    batch_size: int = 16,
    max_workers: int | None = None,
    model: str | None = None,
    client: LLMClient | None = None,
) -> dict[str, dict[str, Any]]:
    metadata, papers = _load_phase1(phase1_json)
    top_n = int(metadata.get("top_n") or len(papers))
    top_papers = papers[:top_n]
    criteria_path = metadata.get("scoring_criteria_path")
    if not criteria_path:
        raise RuntimeError("phase1 metadata missing scoring_criteria_path")
    criteria = Path(criteria_path).read_text(encoding="utf-8")

    batches = [
        top_papers[i : i + batch_size]
        for i in range(0, len(top_papers), batch_size)
    ]
    client = client or LLMClient()
    model = model or os.getenv("LLM_MODEL_SCORING")
    workers = max_workers or min(4, max(1, len(batches)))

    merged: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_score_batch, batch, criteria, client, model)
            for batch in batches
        ]
        for fut in as_completed(futures):
            merged.update(fut.result())

    ordered = {
        _clean_id(p["arxiv_id"]): merged[_clean_id(p["arxiv_id"])]
        for p in top_papers
        if _clean_id(p.get("arxiv_id", "")) in merged
    }
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(output_json).write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ordered


def _score_batch(
    papers: list[dict[str, Any]],
    criteria: str,
    client: LLMClient,
    model: str | None,
) -> dict[str, dict[str, Any]]:
    payload = [
        {
            "arxiv_id": _clean_id(p.get("arxiv_id", "")),
            "title": p.get("title", ""),
            "abstract": p.get("abstract", ""),
        }
        for p in papers
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You are a rigorous research-paper evaluator. Use the following "
                "domain rubric as the scoring criteria.\n\n"
                f"{criteria}\n\n"
                "Score each dimension from 0 to 1. Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Evaluate these papers. Return a JSON object mapping arxiv_id to "
                "an object with novelty, problem_significance, potential_impact, "
                "paradigm_shift, lasting_value, comment, and comment_zh. "
                "comment should be one concise English sentence. comment_zh "
                "should be one concise Chinese sentence.\n\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]
    raw = client.chat_json(messages, model=model, max_tokens=4096)
    out: dict[str, dict[str, Any]] = {}
    expected_ids = {_clean_id(p["arxiv_id"]) for p in payload}
    for key, value in raw.items():
        arxiv_id = _clean_id(key)
        if arxiv_id not in expected_ids or not isinstance(value, dict):
            continue
        normalized = _normalize_assessment(value)
        out[arxiv_id] = normalized
    return out


def _normalize_assessment(value: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    vals = []
    for dim in LLM_DIMS:
        score = clamp(float(value.get(dim, 0.5)))
        item[dim] = score
        vals.append(score)
    item["llm_avg"] = sum(vals) / len(vals)
    item["comment"] = str(value.get("comment") or "").strip()
    item["comment_zh"] = str(value.get("comment_zh") or value.get("comment") or "").strip()
    return item


def _load_phase1(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("metadata", {}), data.get("papers", [])


def _clean_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", str(arxiv_id).strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Score phase1 top papers with an LLM")
    parser.add_argument("--phase1-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-workers", type=int, default=None)
    args = parser.parse_args()
    score_phase1_json(
        args.phase1_json,
        args.output_json,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
    )


if __name__ == "__main__":
    main()

