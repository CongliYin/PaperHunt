#!/usr/bin/env python3
"""Validate a paper-hunt domain directory."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


PIPELINE_DIR = Path(__file__).resolve().parent
REQUIRED = [
    "domain.yaml",
    "filter_keywords.yaml",
    "topic_keywords.yaml",
    "scoring_criteria.md",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a paper-hunt domain")
    parser.add_argument("domain_id")
    args = parser.parse_args()

    domain_dir = PIPELINE_DIR / "domains" / args.domain_id
    errors: list[str] = []
    if not domain_dir.is_dir():
        raise SystemExit(f"Domain not found: {domain_dir}")

    for name in REQUIRED:
        if not (domain_dir / name).is_file():
            errors.append(f"missing {name}")

    if errors:
        _exit(errors)

    domain = _load_yaml(domain_dir / "domain.yaml", errors)
    filters = _load_yaml(domain_dir / "filter_keywords.yaml", errors)
    topics = _load_yaml(domain_dir / "topic_keywords.yaml", errors)
    scoring = (domain_dir / "scoring_criteria.md").read_text(encoding="utf-8").strip()

    if not domain.get("display_name"):
        errors.append("domain.yaml missing display_name")
    cats = domain.get("arxiv_categories")
    if not isinstance(cats, list) or not cats:
        errors.append("domain.yaml arxiv_categories must be a non-empty list")
    if not domain.get("output_suffix"):
        errors.append("domain.yaml missing output_suffix")

    for key in ("positive", "negative_strong", "weak_only_positive", "strong_signals"):
        if key not in filters:
            errors.append(f"filter_keywords.yaml missing {key}")

    tiers = topics.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        errors.append("topic_keywords.yaml tiers must be a non-empty mapping")
    else:
        for tier_name, spec in tiers.items():
            try:
                float(spec.get("coefficient"))
            except Exception:
                errors.append(f"{tier_name}.coefficient must be numeric")
            if not isinstance(spec.get("categories"), dict):
                errors.append(f"{tier_name}.categories must be a mapping")

    if not scoring:
        errors.append("scoring_criteria.md is empty")

    if errors:
        _exit(errors)
    print(f"OK: {args.domain_id}")


def _load_yaml(path: Path, errors: list[str]) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"{path.name} YAML parse error: {exc}")
        return {}


def _exit(errors: list[str]) -> None:
    for error in errors:
        print(f"ERROR: {error}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()

