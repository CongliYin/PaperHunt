import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import sync_conferences as library
from lib.conference_sources import acl_volume, iclr, record, safe_pdf
from lib.edition_policy import SHOP
from lib.edition_sources import read_json, save_json

XML = """<collection id="2025.emnlp"><volume id="industry"><meta><year>2025</year></meta>
<frontmatter/><paper id="25"><title>ProductAgent: Benchmarking Conversational Product Search Agent with Asking Clarification Questions</title>
<author><first>A</first><last>B</last></author><abstract>A shopping assistant uses natural language preferences for product retrieval.</abstract>
<doi>10.18653/v1/2025.emnlp-industry.25</doi></paper>
<paper id="26"><title>Withdrawn: Study</title></paper></volume>
<volume id="demo"><paper id="1"><title>Demo</title></paper></volume></collection>"""


class ConferenceTests(unittest.TestCase):
    def test_track_and_membership(self):
        rows = acl_volume(XML, "EMNLP", 2025)
        self.assertEqual(len(rows), 1)
        p = rows[0]
        self.assertEqual(p["track"], "Industry")
        self.assertEqual(p["arxiv"], "")
        self.assertEqual(
            p["pdf"], "https://aclanthology.org/2025.emnlp-industry.25.pdf"
        )
        self.assertFalse(safe_pdf("https://aclanthology.org.evil.example/paper"))
        self.assertFalse(safe_pdf("http://127.0.0.1/paper"))
        self.assertFalse(acl_volume(XML, "EMNLP", 2025, True))

    def test_openreview_requires_exact_accepted_venue_and_complete_pagination(self):
        vid = "ICLR.cc/2025/Conference"

        def note(name, venue, decision):
            c = {
                "venueid": venue,
                "venue": decision,
                "title": name,
                "authors": ["AA"],
                "abstract": "A",
            }
            return {"content": {k: {"value": v} for k, v in c.items()}, "forum": name}

        pages = [
            {
                "count": 3,
                "notes": [
                    note("one", vid, "ICLR 2025 oral"),
                    note("two", vid + "/Submission", "Submitted"),
                ],
            },
            {"count": 3, "notes": [note("three", vid, "Withdrawn")]},
        ]
        with patch(
            "lib.conference_sources.get",
            side_effect=[Mock(json=lambda d=d: d) for d in pages],
        ):
            r = iclr(2025)
            self.assertEqual([(v["forum"], v["track"]) for v in r], [("one", "Oral")])
        with patch(
            "lib.conference_sources.get",
            return_value=Mock(json=lambda: {"notes": [], "count": 2}),
        ):
            with self.assertRaises(ValueError):
                iclr(2025)

    def test_neurips_track_allowlist(self):
        from lib.conference_sources import proceedings

        html = "".join(
            f'<li><a href="/paper_files/paper/2025/hash/id-Abstract-{track}.html">{track}</a></li>'
            for track in (
                "Conference",
                "Datasets_and_Benchmarks_Track",
                "Position_Paper_Track",
                "Workshop",
            )
        )
        with patch(
            "lib.conference_sources.get",
            side_effect=[Mock(content=html), Mock(json=lambda: {"results": []})],
        ):
            rows = proceedings("NeurIPS", 2025)
        self.assertEqual(
            [r["track"] for r in rows], ["Main", "Datasets and Benchmarks"]
        )

    def test_identity_and_daily_links(self):
        a = acl_volume(XML, "EMNLP", 2025)[0]
        a.update(
            domain=SHOP,
            score=75,
            reason="R",
            evidence="Q",
            result="S",
            first_seen="today",
        )
        b = {**a, "venue": "ACL", "id": "other", "arxiv": "2606.00001"}
        c = {
            **a,
            "id": "third",
            "authors": ["different"],
            "doi": "",
            "url": "https://aclanthology.org/example/",
        }
        groups = library.aggregate(
            {"sample": {"papers": [a, b, c]}}, {"2606.00001": "/daily"}
        )
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(next(p for p in groups if p["daily"])["publications"]), 2)

    def test_resume_refresh_and_failure_preserve_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(
                venue="EMNLP",
                year=2025,
                batch=2,
                seconds=15,
                state=root / "state",
                output=root / "conferences",
                daily_data=root / "data",
            )
            save_json(args.daily_data / "index.json", {"entries": []})
            original = (args.daily_data / "index.json").read_bytes()
            rows = acl_volume(XML, "EMNLP", 2025)
            rows.append(
                record(
                    "EMNLP",
                    2025,
                    "Main",
                    "Robotic 3D agent memory",
                    ["A"],
                    "https://aclanthology.org/ex/",
                    abstract="Robot memory.",
                )
            )
            reviewer = Mock(config="test", scopes={SHOP: {}})

            def adjudicate(papers, hf, reviewer):
                r = {
                    "F": 4,
                    "M": 4,
                    "E": 3,
                    "U": 4,
                    "needs_text": False,
                    "reason": "有商品检索证据",
                    "quote": "shopping assistant",
                    "result_quote": "product retrieval",
                }
                return set(), {k: {"domains": {SHOP: r}} for k in papers}

            with (
                patch.object(library, "catalogue", return_value=rows),
                patch.object(library, "EditionReviewer", return_value=reviewer),
                patch.object(library, "reconcile", side_effect=adjudicate) as review,
            ):
                library.sync(args)
                first = read_json(args.output / "index.json")
                self.assertEqual(len(first["papers"]), 1)
                detail = read_json(args.output / first["papers"][0]["file"])
                self.assertEqual(detail["publications"][0]["track"], "Industry")
                self.assertNotIn("abstract", first["papers"][0])
                self.assertEqual(detail["abstract"], rows[0]["abstract"])
                self.assertEqual(first["volumes"]["EMNLP-2025"]["processed"], 2)
                library.sync(args)
                self.assertEqual(review.call_count, 1)
                path = args.state / "EMNLP-2025.json"
                cache = read_json(path)
                cache["snapshot_date"] = "old"
                save_json(path, cache)
                with patch.object(
                    library, "catalogue", side_effect=ValueError("broken page")
                ):
                    library.sync(args)
                failed = read_json(args.output / "index.json")
                self.assertEqual(failed["papers"], first["papers"])
                self.assertEqual(failed["volumes"]["EMNLP-2025"]["status"], "retry")
                with patch.object(library, "catalogue", return_value=rows[1:]):
                    library.sync(args)
                self.assertEqual(read_json(args.output / "index.json")["papers"], [])
            self.assertEqual((args.daily_data / "index.json").read_bytes(), original)
