"""Build immutable list/detail objects; switch the single public index only on success."""

from pathlib import Path

from .edition_review import qualifies, value
from .edition_sources import digest, read_json, save_json
from .enricher import extract_links
from .figures import extract_figures
from .translator import enrich_zh


def object_file(root, kind, payload):
    name = f"v2/{kind}/{digest(payload)}.json"
    if not (root / name).exists():
        save_json(root / name, payload)
    return name


class EditionPublisher:
    def __init__(
        self, output, state, scopes, storage=None, translate=True, figures=True
    ):
        self.output = Path(output)
        self.state = Path(state)
        self.scopes = scopes
        self.storage = storage
        self.translate = translate
        self.figures = figures
        self.index = read_json(
            self.output / "index.json", {"domains": [], "entries": []}
        )
        self.entries = {(e["domain"], e["date"]): e for e in self.index["entries"]}
        self.owners = {}
        for key, entry in self.entries.items():
            listing = read_json(self.output / entry["file"])
            for card in listing["papers"]:
                self.owners[(card["arxiv_id"], key[0])] = key[1]
        self.events = (
            read_json(self.output / self.index["source_events"])
            if self.index.get("source_events")
            else {}
        )

    def assets(self, p):
        key = p["arxiv_id"]
        fingerprint = digest([key, p["title"], p["abstract"]])
        path = self.state / "assets" / f"{fingerprint}.json"
        assets = read_json(path, {})
        if self.translate and not assets.get("abstract_zh"):
            try:
                assets.update(enrich_zh(p))
            except (RuntimeError, ValueError, TypeError) as exc:
                print(f"[translation] pending {key}: {type(exc).__name__}")
        if self.figures and "figures" not in assets:
            extracted = extract_figures(
                key, self.state / "pdf" / fingerprint, storage=self.storage
            )
            if extracted.get("figures"):
                assets.update(extracted)
        save_json(path, assets)
        return assets

    def edition(self, day, domains, arxiv, hf, primary, reviews):
        cards = {d: [] for d in domains}
        ledger = {}
        papers = {**hf, **arxiv}
        for key in sorted(reviews):
            review = reviews[key]
            passed = {d: r for d, r in review["domains"].items() if qualifies(r)}
            reason = "arxiv" if key in primary else "hf"
            available = [
                d
                for d in domains
                if d in passed and self.owners.get((key, d), day) == day
            ]
            ledger[key] = {
                "path": reason,
                "arxiv_input": key in arxiv,
                "hf_input": key in hf,
                "passed": sorted(passed),
                "previously_recommended": sorted(
                    d for d in domains if self.owners.get((key, d), day) != day
                ),
                "published": available,
                "review": review,
            }
            if key in hf and (
                available or any((key, d) in self.owners for d in self.scopes)
            ):
                dates = self.events.setdefault(key, [])
                if day not in dates:
                    dates.append(day)
                    dates.sort()
            if not available:
                continue
            p = papers[key]
            assets = self.assets(p)
            links = extract_links(p.get("comments", ""), p["abstract"])
            detail = {
                "schema": 2,
                "arxiv_id": key,
                "title": p["title"],
                "title_zh": assets.get("title_zh", ""),
                "abstract_en": p["abstract"],
                "abstract_zh": assets.get("abstract_zh", ""),
                "authors": p.get("authors", []),
                "author_affiliations": p.get("author_affiliations", []),
                "published_at": p["published_at"],
                "abs_url": f"https://arxiv.org/abs/{key}",
                "pdf_url": f"https://arxiv.org/pdf/{key}",
                "figures": assets.get("figures", []),
                "key_points_zh": assets.get("key_points_zh", []),
                "links": {
                    "github": links["github_url"],
                    "project_page": links["project_page_url"],
                },
                "review_domains": passed,
                "evidence_scope": review["evidence_scope"],
                "primary_domain": min(
                    passed, key=lambda d: (-passed[d]["F"], -value(passed[d]), d)
                ),
                "source": reason,
            }
            detail_file = object_file(self.output, "papers", detail)
            for d in available:
                row = passed[d]
                card = {
                    k: detail[k] for k in ("arxiv_id", "title", "authors", "title_zh")
                }
                card.update(
                    schema=2,
                    source=reason,
                    edition=day,
                    domain=d,
                    fit=row["F"],
                    value=value(row),
                    reason=row["reason"],
                    tags=row.get("tags", [])
                    + [self.scopes[tag]["name"] for tag in sorted(passed)],
                    tldr_zh=assets.get("tldr_zh", ""),
                    thumb=assets.get("thumb", ""),
                    detail_file=detail_file,
                )
                cards[d].append(card)
        for d, items in cards.items():
            items.sort(key=lambda c: (-c["value"], -c["fit"], c["arxiv_id"]))
            payload = {
                "domain": d,
                "date": day,
                "display_name": self.scopes[d]["name"],
                "schema": 2,
                "papers": items,
            }
            path = object_file(self.output, "lists", payload)
            self.entries[d, day] = {
                "domain": d,
                "date": day,
                "paper_count": len(items),
                "file": path,
            }
            for owner in [k for k, v in self.owners.items() if k[1] == d and v == day]:
                del self.owners[owner]
            for card in items:
                self.owners[card["arxiv_id"], d] = day
        return ledger

    def commit(self, timestamp):
        names = {d["id"]: d for d in self.index["domains"]}
        for d, _ in self.entries:
            if d in self.scopes:
                names[d] = {"id": d, "display_name": self.scopes[d]["name"]}
        index = dict(
            self.index,
            generated_at=timestamp,
            domains=list(names.values()),
            entries=[self.entries[k] for k in sorted(self.entries, reverse=True)],
            source_events=object_file(self.output, "sources", self.events),
        )
        save_json(self.output / "index.json", index)
