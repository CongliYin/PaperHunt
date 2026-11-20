"""Run the configured scorer against the four agreed real-paper regression cases."""

import argparse
from pathlib import Path

from lib.edition_review import EditionReviewer, load_scopes, reconcile
from lib.fetcher import NS, ArxivClient, _parse_entry

EXPECTED = {
    "2603.19461": {"agent-harness-evolution"},
    "2606.04536": {"agent-memory", "agent-harness-evolution"},
    "2508.09736": {"agent-multimodal", "agent-memory"},
    "2606.24194": {"agent-e-commerce"},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("tmp/seed-review"))
    args = parser.parse_args()
    feed = ArxivClient().fetch_feed(
        params={"id_list": ",".join(EXPECTED), "max_results": len(EXPECTED)},
        category="labelled seed papers",
        offset=0,
    )
    records = [_parse_entry(node) for node in feed.findall("atom:entry", NS)]
    papers = {p["arxiv_id"]: p for p in records}
    if papers.keys() != EXPECTED.keys():
        raise SystemExit("Incomplete arXiv seed response")
    reviewer = EditionReviewer(
        load_scopes(Path(__file__).parent / "domains"), args.state_dir
    )
    primary, reviews = reconcile(papers, {}, reviewer)
    failures = []
    for key, expected in EXPECTED.items():
        if key not in primary:
            failures.append(f"{key} missed by arXiv screening")
            continue
        rows = reviews[key]["domains"]
        for domain in sorted(expected):
            row = rows[domain]
            print(key, domain, row["F"], row["reason"])
            if row["F"] < 3 or row["needs_text"]:
                failures.append(f"{key} missed {domain}")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
