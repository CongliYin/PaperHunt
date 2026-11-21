"""Generate or replay a Paper Hunt edition. One atomic index per successful run."""

import argparse
import fcntl
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from legacy_daily import discover_arxiv_categories
from lib.arxiv_cache import build_arxiv_cache
from lib.blob_uploader import FigureStorage
from lib.edition_publish import EditionPublisher
from lib.edition_review import EditionReviewer, load_scopes, reconcile
from lib.edition_sources import digest, fetch_hf, paper_id, read_json, save_json

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    scopes = load_scopes(args.domains_dir)
    domains = sorted(set(args.domains.split(",")) if args.domains else scopes)
    if set(domains) - scopes.keys():
        raise ValueError(f"Unknown domains: {set(domains) - scopes.keys()}")
    end = args.date or (
        datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    )
    state = args.state_dir
    index = read_json(args.output / "index.json", {})
    start = end
    if args.date is None:
        # Persist the first attempted date even if the first job fails before publication.
        # Separate shadow and production clocks so promotion never rewrites shadow dates.
        clock_key = digest(str(args.output.resolve()))
        origin_path = state / "start" / f"{clock_key}.json"
        first = date.fromisoformat(
            index.get("scheduled_from") or read_json(origin_path, end.isoformat())
        )
        if not args.skip_llm and not args.domains:
            save_json(origin_path, first.isoformat())
        cursor = date.fromisoformat(
            index.get("scheduled_through", (first - timedelta(days=1)).isoformat())
        )
        start = max(first, min(end - timedelta(days=6), cursor + timedelta(days=1)))
    # Fetch with contextual dates even for a single quiet day. An empty target is
    # legitimate only after a complete, nonempty surrounding source window succeeds.
    fetch_start = start - timedelta(days=2)
    blob = build_arxiv_cache(
        state / "arxiv.json",
        start_date=fetch_start.isoformat(),
        end_date=end.isoformat(),
        categories=discover_arxiv_categories(args.domains_dir, scopes),
        raw_cache_dir=args.arxiv_raw_cache_dir,
        refresh=args.refresh_arxiv or args.date is None,
    )
    by_day = {}
    for papers in blob["categories"].values():
        for p in papers:
            key = paper_id(p["arxiv_id"])
            by_day.setdefault(p["published_at"][:10], {})[key] = p
    reviewer = EditionReviewer(scopes, state, batch_size=args.llm_batch_size)
    pub = EditionPublisher(
        args.output,
        state,
        scopes,
        FigureStorage(backend=args.storage_backend, public_dir=args.output.parent),
        translate=not args.skip_translation,
        figures=not args.skip_figures,
    )
    for offset in range((end - start).days + 1):
        started = time.monotonic()
        usage_before = reviewer.client.usage.copy()
        day = (start + timedelta(days=offset)).isoformat()
        arxiv = by_day.get(day, {})
        hf = fetch_hf(day)
        snap_path = state / "sources" / f"{day}.json"
        previous = read_json(snap_path, {})
        if not hf and (date.fromisoformat(day).weekday() < 5 or previous.get("hf")):
            time.sleep(2)
            hf = fetch_hf(day)
            if not hf and previous.get("hf"):
                raise RuntimeError(f"Previously nonempty HF feed disappeared for {day}")
        snapshot = {"day": day, "hf": hf, "arxiv": arxiv}
        save_json(state / "snapshots" / f"{digest(snapshot)}.json", snapshot)
        save_json(snap_path, snapshot)
        if args.skip_llm:
            print(f"[sources] {day} arXiv={len(arxiv)} HF={len(hf)}")
            continue
        primary, reviews = reconcile(arxiv, hf, reviewer)
        ledger = pub.edition(day, domains, arxiv, hf, primary, reviews)
        if hf.keys() - ledger.keys():
            raise RuntimeError("Incomplete HF reconciliation")
        supplements = [
            p for p in ledger.values() if p["path"] == "hf" and p["published"]
        ]
        report = {
            "day": day,
            "source_snapshot": digest(snapshot),
            "review_policy": reviewer.config,
            "score_version": 3,
            "domains": domains,
            "arxiv_ids": sorted(arxiv),
            "arxiv_count": len(arxiv),
            "hf_count": len(hf),
            "arxiv_screened_in": len(primary),
            "hf_supplement_papers": len(supplements),
            "hf_supplement_pairs": sum(len(p["published"]) for p in supplements),
            "seconds": round(time.monotonic() - started, 2),
            "model_usage": {
                k: n - usage_before[k] for k, n in reviewer.client.usage.items()
            },
            "hf_screen_rescues": sum(p["arxiv_input"] for p in supplements),
            "decisions": ledger,
        }
        save_json(state / "runs" / f"{day}-{'_'.join(domains)}.json", report)
        print(
            f"[edition] {day} arXiv={len(arxiv)} HF={len(hf)} supplements={len(supplements)}",
            flush=True,
        )
    if not args.skip_llm:
        if args.date is None and not args.domains:
            pub.index["scheduled_from"] = first.isoformat()
            pub.index["scheduled_through"] = end.isoformat()
        pub.commit(datetime.now(UTC).isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=date.fromisoformat,
        help="Replay one issue (YYYY-MM-DD). By default, catch up through yesterday in Shanghai.",
    )
    parser.add_argument(
        "--domains",
        help="Comma-separated domain IDs to publish. Retrieval and review use all configured domains.",
    )
    parser.add_argument("--domains-dir", type=Path, default=ROOT / "pipeline/domains")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "tmp/edition-state")
    parser.add_argument("--output", type=Path, default=ROOT / "web/public/data")
    parser.add_argument(
        "--arxiv-raw-cache-dir", type=Path, default=ROOT / "tmp/arxiv-raw"
    )
    parser.add_argument(
        "--refresh-arxiv", action="store_true",
        help="Refetch arXiv for a dated replay. Scheduled runs always refresh.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Fetch and validate sources without publishing",
    )
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--skip-figures", action="store_true")
    parser.add_argument("--llm-batch-size", type=int, default=12)
    parser.add_argument(
        "--storage-backend",
        choices=["blob", "repo"],
        default=os.getenv("STORAGE_BACKEND", "blob"),
    )
    args = parser.parse_args()
    if not 1 <= args.llm_batch_size <= 32:
        parser.error("batch size must be between 1 and 32")
    args.output.mkdir(parents=True, exist_ok=True)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    # Lock the destination, even when separate jobs specify different state directories.
    with open(args.output.parent / f".{args.output.name}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run(args)


if __name__ == "__main__":
    main()
