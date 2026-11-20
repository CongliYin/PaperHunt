"""Evaluate human-labelled (date, paper, domain) pairs against recorded daily decisions."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from lib.edition_review import value
from lib.edition_sources import read_json


def rate(hits, total):
    if not total:
        return {"hits": hits, "total": 0, "rate": None, "wilson95": None}
    p = hits / total
    z = 1.96
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return {
        "hits": hits,
        "total": total,
        "rate": p,
        "wilson95": [center - margin, center + margin],
    }


def evaluate(labels, reports, min_fit=3, min_value=4):
    pairs = set()
    counts = defaultdict(lambda: defaultdict(int))
    for label in labels:
        key = (label["date"], label["arxiv_id"], label["domain"])
        if key in pairs:
            raise ValueError(f"Duplicate label {key}")
        pairs.add(key)
        day, paper, domain = key
        report = reports[day]
        related, wanted = label["relevant"], label["recommend"]
        if (
            type(related) is not bool
            or type(wanted) is not bool
            or wanted
            and not related
        ):
            raise ValueError(f"Invalid human label for {key}")
        rec = report["decisions"].get(paper)
        row = rec["review"]["domains"][domain] if rec else None
        passed = bool(
            row
            and domain not in rec["previously_recommended"]
            and not row["needs_text"]
            and row["F"] >= min_fit
            and value(row) >= min_value
            and row["M"] >= 1
            and row["E"] >= 1
        )
        c = counts[domain]
        c["published"] += passed
        c["correct"] += passed and wanted
        c["wanted"] += wanted
        c["related"] += related and paper in report["arxiv_ids"]
        c["screen_hit"] += bool(rec and rec["path"] == "arxiv" and related)
        c["main_correct"] += bool(passed and wanted and rec["path"] == "arxiv")
        if rec and rec["path"] == "hf":
            c["supplement"] += passed
            c["correct_supplement"] += passed and wanted
    return {
        d: {
            "precision": rate(c["correct"], c["published"]),
            "recall": rate(c["correct"], c["wanted"]),
            "arxiv_only_recall": rate(c["main_correct"], c["wanted"]),
            "screen_recall": rate(c["screen_hit"], c["related"]),
            "hf_precision": rate(c["correct_supplement"], c["supplement"]),
        }
        for d, c in counts.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "labels",
        type=Path,
        help="JSON array with date, arxiv_id, domain, relevant, recommend",
    )
    parser.add_argument(
        "reports", nargs="+", type=Path, help="Full four-domain run manifests"
    )
    parser.add_argument(
        "--grid", action="store_true", help="Development-set sensitivity analysis"
    )
    args = parser.parse_args()
    labels = read_json(args.labels)
    reports = {}
    for path in args.reports:
        report = read_json(path)
        if report["day"] in reports:
            raise ValueError("Supply exactly one full manifest per date")
        reports[report["day"]] = report
    thresholds = (
        [(f, v) for f in (2, 3, 4) for v in (3, 4, 5)] if args.grid else [(3, 4)]
    )
    for f, v in thresholds:
        print(
            json.dumps(
                {"F": f, "V": v, "domains": evaluate(labels, reports, f, v)}, indent=2
            )
        )


if __name__ == "__main__":
    main()
