#!/usr/bin/env python3
"""Compare legacy and gold-backed paper selection on checked-in history."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.filter import filter_papers_by_keywords  # noqa: E402
from lib.selector import choose_primary_domain, load_selection_policies  # noqa: E402


DOMAINS_DIR = ROOT / "pipeline" / "domains"
DATA_DIR = ROOT / "web" / "public" / "data"
GOLD_PATH = ROOT / "tests" / "fixtures" / "paper_selection_gold.json"


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / total if total else 0.0

    def add(self, expected: bool, predicted: bool) -> None:
        if expected and predicted:
            self.tp += 1
        elif expected:
            self.fn += 1
        elif predicted:
            self.fp += 1
        else:
            self.tn += 1

    def merge(self, other: "Confusion") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.tn += other.tn
        self.fn += other.fn


def load_history(domain: str) -> dict[str, dict]:
    """Load papers referenced by published daily lists for historical metrics."""
    domain_dir = DATA_DIR / domain
    records: dict[str, dict] = {}
    for list_path in sorted(domain_dir.glob("????-??-??.json")):
        payload = json.loads(list_path.read_text(encoding="utf-8"))
        for item in payload.get("papers", []):
            arxiv_id = str(item.get("arxiv_id") or "").strip()
            detail_path = domain_dir / list_path.stem / f"{arxiv_id}.json"
            if not arxiv_id or not detail_path.exists():
                continue
            records[arxiv_id] = _history_record(detail_path)
    return records


def load_detail_history(domain: str) -> dict[str, dict]:
    """Load the retained detail corpus, including papers excluded from publication."""
    domain_dir = DATA_DIR / domain
    records: dict[str, dict] = {}
    for detail_path in sorted(domain_dir.glob("????-??-??/*.json")):
        record = _history_record(detail_path)
        arxiv_id = record["arxiv_id"]
        if arxiv_id:
            records[arxiv_id] = record
    return records


def _history_record(detail_path: Path) -> dict:
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    return {
        "arxiv_id": str(detail.get("arxiv_id") or "").strip(),
        "title": detail.get("title", ""),
        "abstract": detail.get("abstract_en", ""),
        "llm_avg": (detail.get("llm_assessment") or {}).get("llm_avg"),
    }


def evaluate_gold() -> tuple[dict[str, tuple[Confusion, Confusion]], Confusion]:
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    policies = load_selection_policies(DOMAINS_DIR)
    results: dict[str, tuple[Confusion, Confusion]] = {}
    overall_after = Confusion()

    for domain, labels in gold["domains"].items():
        history = load_detail_history(domain)
        filter_path = DOMAINS_DIR / domain / "filter_keywords.yaml"
        legacy_config = yaml.safe_load(filter_path.read_text(encoding="utf-8")) or {}
        before = Confusion()
        after = Confusion()

        for label in ("include", "exclude"):
            expected = label == "include"
            for arxiv_id in labels[label]:
                if arxiv_id not in history:
                    raise RuntimeError(f"Gold paper missing from history: {domain}/{arxiv_id}")
                paper = history[arxiv_id]
                legacy_selected = bool(
                    filter_papers_by_keywords([dict(paper)], legacy_config, verbose=False)
                )
                primary = choose_primary_domain(paper, policies).primary_domain
                selected = primary == domain
                before.add(expected, legacy_selected)
                after.add(expected, selected)

        results[domain] = (before, after)
        overall_after.merge(after)
    return results, overall_after


def historical_stats(records: list[dict]) -> dict[str, float | int]:
    scores = [float(record["llm_avg"]) for record in records if record.get("llm_avg") is not None]
    low = sum(score < 0.4 for score in scores)
    high = sum(score >= 0.7 for score in scores)
    return {
        "count": len(records),
        "mean_llm": sum(scores) / len(scores) if scores else 0.0,
        "low_count": low,
        "low_pct": low / len(scores) if scores else 0.0,
        "high_count": high,
    }


def evaluate_history() -> tuple[dict[str, tuple[dict, dict]], int, int]:
    policies = load_selection_policies(DOMAINS_DIR)
    comparisons: dict[str, tuple[dict, dict]] = {}
    before_domains: dict[str, set[str]] = defaultdict(set)
    after_domains: dict[str, set[str]] = defaultdict(set)

    for domain in sorted(policies):
        before_records = list(load_history(domain).values())
        after_records = []
        for paper in before_records:
            arxiv_id = paper["arxiv_id"]
            before_domains[arxiv_id].add(domain)
            primary = choose_primary_domain(paper, policies).primary_domain
            if primary == domain:
                after_records.append(paper)
                after_domains[arxiv_id].add(domain)
        comparisons[domain] = (
            historical_stats(before_records),
            historical_stats(after_records),
        )

    before_duplicates = sum(len(domains) > 1 for domains in before_domains.values())
    after_duplicates = sum(len(domains) > 1 for domains in after_domains.values())
    return comparisons, before_duplicates, after_duplicates


def print_report() -> bool:
    gold_results, overall = evaluate_gold()
    print("Gold-set comparison")
    print("domain                       system    TP FP TN FN  precision recall   F1 accuracy")
    for domain, (before, after) in gold_results.items():
        for name, metrics in (("before", before), ("after", after)):
            print(
                f"{domain:28s} {name:8s} {metrics.tp:2d} {metrics.fp:2d} "
                f"{metrics.tn:2d} {metrics.fn:2d}  {metrics.precision:8.3f} "
                f"{metrics.recall:6.3f} {metrics.f1:5.3f} {metrics.accuracy:8.3f}"
            )

    print(
        f"overall after: precision={overall.precision:.3f} "
        f"recall={overall.recall:.3f} f1={overall.f1:.3f} "
        f"accuracy={overall.accuracy:.3f}"
    )

    comparisons, before_duplicates, after_duplicates = evaluate_history()
    print("\nHistorical published-output proxy")
    print("domain                       system   count mean_llm low<0.4 low_pct high>=0.7")
    for domain, (before, after) in comparisons.items():
        for name, stats in (("before", before), ("after", after)):
            print(
                f"{domain:28s} {name:8s} {stats['count']:5d} "
                f"{stats['mean_llm']:8.3f} {stats['low_count']:7d} "
                f"{stats['low_pct']:7.1%} {stats['high_count']:9d}"
            )
        retained_high = (
            after["high_count"] / before["high_count"]
            if before["high_count"]
            else 0.0
        )
        print(f"  high-score retention: {retained_high:.1%}")
    print(f"cross-domain duplicate IDs: before={before_duplicates}, after={after_duplicates}")

    per_domain_pass = all(
        after.precision >= 0.90 and after.recall >= 0.90
        for _, after in gold_results.values()
    )
    return (
        overall.precision >= 0.95
        and overall.recall >= 0.95
        and per_domain_pass
        and after_duplicates == 0
    )


def main() -> None:
    if not print_report():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
