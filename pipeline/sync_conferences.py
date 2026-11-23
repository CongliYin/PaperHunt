"""Incremental proceedings library with its own public index and volume snapshots."""

import argparse
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import requests
import yaml
from lib.conference_sources import VENUES, catalogue, hydrate
from lib.edition_policy import eligible, value, winner
from lib.edition_review import EditionReviewer, load_scopes, reconcile
from lib.edition_sources import digest, read_json, save_json

ROOT = Path(__file__).resolve().parents[1]


def stamp():
    return datetime.now(UTC).isoformat(timespec="seconds")


def paper(row):
    return {
        "arxiv_id": row["arxiv"] or row["id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "version": digest([row["url"], row["pdf"], row["abstract"]]),
        "conference_pdf": row["pdf"],
    }


def sync_volume(venue, year, state, reviewer, limit, deadline):
    path = state / f"{venue}-{year}.json"
    cache = read_json(
        path,
        {
            "records": {},
            "decisions": {},
            "hydrated": {},
            "attempt": {},
            "first_seen": {},
        },
    )
    today = date.today().isoformat()
    if cache.get("snapshot_date") != today:
        rows = catalogue(venue, year)
        cache["records"] = {r["id"]: r for r in rows}
        cache["snapshot_date"] = today
        save_json(path, cache)
    if not cache["records"]:
        raise ValueError("Empty catalogue")
    if cache.get("policy") != reviewer.config:
        cache.update(policy=reviewer.config, decisions={})
    records = cache["records"]
    decisions = cache["decisions"]
    # Reconcile only after complete enumeration; changed publications need a fresh decision.
    for k in list(decisions):
        if k not in records or decisions[k]["input"] != digest(records[k]):
            del decisions[k]
    pending = [k for k in records if k not in decisions]

    def priority(k):
        r = records[k]
        signal = any(
            eligible(d, {"title": r["title"], "abstract": ""}) for d in reviewer.scopes
        )
        return (cache["attempt"].get(k, ""), not signal, not bool(r["abstract"]), k)

    # Cheap exclusions with complete abstracts don't consume the review budget.
    for k in list(pending):
        r = records[k]
        if r["abstract"] and not any(eligible(d, r) for d in reviewer.scopes):
            decisions[k] = {"input": digest(r), "card": None}
    pending = sorted((k for k in pending if k not in decisions), key=priority)
    for start in range(0, min(limit, len(pending)), 8):
        if time.monotonic() >= deadline:
            break
        batch = pending[start : min(start + 8, limit)]
        candidates = {}

        def resolve(k):
            r = records[k]
            saved = cache["hydrated"].get(k, {})
            if saved.get("input") == digest(r) and saved.get("date") == today:
                return saved["row"]
            try:
                return hydrate(r)
            except (requests.RequestException, ValueError):
                return r

        with ThreadPoolExecutor(3) as pool:
            for k, r in zip(batch, pool.map(resolve, batch)):
                cache["attempt"][k] = stamp()
                if r["abstract"]:
                    if not records[k]["abstract"]:
                        cache["hydrated"][k] = {
                            "input": digest(records[k]),
                            "date": today,
                            "row": r,
                        }
                    candidates[k] = r
        _, reviews = reconcile(
            {k: paper(r) for k, r in candidates.items()}, {}, reviewer
        )
        for k, r in candidates.items():
            row = reviews.get(k, {}).get("domains", {})
            domain = winner(row)
            card = None
            if domain:
                first = cache["first_seen"].setdefault(k, stamp())
                card = dict(
                    r,
                    domain=domain,
                    score=value(row[domain]),
                    reason=row[domain]["reason"],
                    evidence=row[domain]["quote"],
                    result=row[domain]["result_quote"],
                    first_seen=first,
                )
            decisions[k] = {"input": digest(records[k]), "card": card}
        save_json(path, cache)
    missing = sum(
        k in cache["attempt"] and k not in decisions and not r["abstract"]
        for k, r in records.items()
    )
    save_json(path, cache)
    return {
        "venue": venue,
        "year": year,
        "status": "complete" if len(decisions) == len(records) else "partial",
        "total": len(records),
        "processed": len(decisions),
        "missing": missing,
        "updated": stamp(),
        "papers": [v["card"] for v in decisions.values() if v["card"]],
    }


def daily_links(data):
    index = read_json(data / "index.json", {"entries": []})
    links = {}
    for e in index["entries"]:
        for card in read_json(data / e["file"])["papers"]:
            links.setdefault(
                card["arxiv_id"], f"/{e['domain']}/{e['date']}/{card['arxiv_id']}"
            )
    return links


def aggregate(volumes, links):
    # Union only explicit identifiers. Identical titles alone are not identifiers.
    parents = {}

    def root(k):
        while parents.setdefault(k, k) != k:
            parents[k] = parents[parents[k]]
            k = parents[k]
        return k

    groups = {}
    indexed = []
    for v in volumes.values():
        for p in v["papers"]:
            keys = [p["id"]] + [
                f"{f}:{p[f]}" for f in ("doi", "forum", "arxiv") if p[f]
            ]
            for k in keys[1:]:
                parents[root(k)] = root(keys[0])
            indexed.append(p)
    for p in indexed:
        groups.setdefault(root(p["id"]), []).append(p)
    out = []
    for papers in groups.values():
        p = min(papers, key=lambda r: (-r["score"], r["id"]))
        entry = {
            k: p[k]
            for k in (
                "title",
                "authors",
                "domain",
                "score",
                "reason",
                "abstract",
                "evidence",
                "result",
            )
        }
        entry.update(
            abstract_source=p.get("abstract_source") or p["url"],
            key=digest(min(r["id"] for r in papers)),
            daily=next(
                (links[r["arxiv"]] for r in papers if r["arxiv"] in links), None
            ),
            publications=[
                {
                    k: r[k]
                    for k in (
                        "venue",
                        "year",
                        "track",
                        "url",
                        "pdf",
                        "published",
                        "first_seen",
                    )
                }
                for r in papers
            ],
        )
        out.append(entry)
    return sorted(out, key=lambda r: (-r["score"], r["key"]))


def sync(args):
    reviewer = EditionReviewer(
        load_scopes(ROOT / "pipeline/domains"), args.state / "reviews"
    )
    public = args.output
    index = read_json(public / "index.json", {"volumes": {}, "papers": []})
    statuses = index["volumes"]
    volumes = {
        k: read_json(public / v["file"]) for k, v in statuses.items() if v.get("file")
    }
    years = [args.year] if args.year else range(2025, date.today().year + 1)
    editions = [
        (venue, year)
        for year in years
        for venue in ([args.venue] if args.venue else VENUES)
    ]
    editions.sort(
        key=lambda pair: statuses.get(f"{pair[0]}-{pair[1]}", {}).get("updated", "")
    )
    deadline = time.monotonic() + args.seconds
    for venue, year in editions:
        statuses.setdefault(
            f"{venue}-{year}",
            {"venue": venue, "year": year, "status": "queued", "updated": ""},
        )
    for pos, (venue, year) in enumerate(editions):
        if time.monotonic() >= deadline:
            break
        key = f"{venue}-{year}"
        try:
            now = time.monotonic()
            slice_end = now + (deadline - now) / (len(editions) - pos)
            vol = sync_volume(venue, year, args.state, reviewer, args.batch, slice_end)
            obj = f"volumes/{digest(vol)}.json"
            save_json(public / obj, vol)
            volumes[key] = vol
            statuses[key] = {k: v for k, v in vol.items() if k != "papers"} | {
                "file": obj,
                "accepted": len(vol["papers"]),
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            RuntimeError,
            ET.ParseError,
            yaml.YAMLError,
        ) as exc:
            statuses[key] = {
                **statuses.get(key, {}),
                "venue": venue,
                "year": year,
                "updated": stamp(),
                "status": "pending"
                if isinstance(exc, requests.HTTPError)
                and exc.response.status_code == 404
                else "retry",
            }
            print(f"[conference] {key}: {exc}", flush=True)
        print(
            key,
            statuses[key]["status"],
            statuses[key].get("processed", 0),
            statuses[key].get("accepted", 0),
            flush=True,
        )
    cards = []
    for detail in aggregate(volumes, daily_links(args.daily_data)):
        filename = f"papers/{digest(detail)}.json"
        if not (public / filename).exists():
            save_json(public / filename, detail)
        card = {k: detail[k] for k in ("key", "title", "domain", "score", "reason")}
        card["file"] = filename
        card["publications"] = [
            {k: v[k] for k in ("venue", "year", "track")}
            for v in detail["publications"]
        ]
        cards.append(card)
    index.update(updated=stamp(), papers=cards, volumes=statuses)
    save_json(public / "index.json", index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", choices=VENUES)
    parser.add_argument("--year", type=int)
    parser.add_argument(
        "--batch",
        type=int,
        default=32,
        help="Maximum metadata/review records per venue and year",
    )
    parser.add_argument("--seconds", type=int, default=480)
    parser.add_argument(
        "--state", type=Path, default=ROOT / "tmp/edition-state/conferences"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "web/public/conferences")
    parser.add_argument("--daily-data", type=Path, default=ROOT / "web/public/data")
    args = parser.parse_args()
    if (
        args.batch < 1
        or args.seconds < 1
        or (args.year and not 2025 <= args.year <= date.today().year)
    ):
        parser.error("Invalid batch, budget or year")
    if args.output.resolve().is_relative_to(args.daily_data.resolve()):
        parser.error("Conference output must be separate from the daily index")
    if args.state.resolve().is_relative_to(args.output.resolve()):
        parser.error("Private conference state must be outside the public library")
    sync(args)
