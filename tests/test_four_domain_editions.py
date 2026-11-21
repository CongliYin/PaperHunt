import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import run_daily
from evaluate_editions import evaluate
from lib.edition_policy import MM, SHOP, eligible, value, winner
from lib.edition_publish import EditionPublisher
from lib.edition_review import (
    EditionReviewer,
    load_scopes,
    reconcile,
    valid_review,
)
from lib.edition_sources import HF_API_URL, fetch_hf, read_json

DAY = "2026-11-19"
SCOPES = load_scopes(run_daily.ROOT / "pipeline/domains")
MEM = "agent-memory"
EVO = "agent-harness-evolution"


def paper(key):
    return {
        "arxiv_id": key,
        "title": "Self-evolving agent memory",
        "abstract": "Experience changes later behaviour. A controlled trial showed improved retention.",
        "published_at": DAY + "T00:00:00Z",
        "authors": ["Author"],
    }


def scores(fit=0):
    return {
        "F": fit,
        "M": 3,
        "E": 3,
        "U": 3,
        "reason": "经验改变后续行为",
        "quote": "Experience changes later behaviour." if fit else "",
        "result_quote": "A controlled trial showed improved retention." if fit else "",
        "needs_text": False,
    }


def record():
    return {
        "domains": {d: scores(4 if d in (EVO, MEM) else 0) for d in SCOPES},
        "evidence_scope": "title/abstract",
    }


def response(rows, next_url=None):
    result = Mock()
    result.json.return_value = rows
    result.links = {"next": {"url": next_url}} if next_url else {}
    return result


class EditionTests(unittest.TestCase):
    def test_hf_follows_last_page_and_preserves_issue_date(self):
        http = Mock()
        row = {
            "paper": {
                "id": "2611.12345v2",
                "publishedAt": "2026-11-02",
                "summary": "X",
                "title": "Y",
            }
        }
        url = HF_API_URL + "?date=" + DAY + "&p=1"
        http.get.side_effect = [response([row, row], url), response([])]
        items = fetch_hf(DAY, http)
        self.assertEqual(http.get.call_count, 2)
        self.assertEqual(list(items), ["2611.12345"])
        self.assertEqual(items["2611.12345"]["hf_date"], DAY)
        self.assertEqual(items["2611.12345"]["published_at"], "2026-11-02")

    def test_broken_pagination_and_bad_record_fail_closed(self):
        for rows, url in (
            ([], HF_API_URL + "?date=2026-11-18"),
            ([], HF_API_URL + "?date=" + DAY + "&limit=100"),
            ([{"paper": {"id": "unknown"}}], None),
            ({"error": "offline"}, None),
        ):
            session = Mock()
            session.get.return_value = response(rows, url)
            with (
                self.subTest(url=url),
                self.assertRaises((TypeError, ValueError, KeyError)),
            ):
                fetch_hf(DAY, session)

    def test_all_four_gates_and_quotes(self):
        row = scores(4)
        self.assertEqual(winner({MEM: row}), MEM)
        self.assertEqual(value(row), 60)
        for change in ({"F": 3}, {"M": 1}, {"E": 1}, {"U": 2}, {"needs_text": True}):
            self.assertIsNone(winner({MEM: dict(row, **change)}))
        rows = record()["domains"]
        valid_review(rows, SCOPES, paper("x")["abstract"])
        for change in ({"quote": "Invented"}, {"M": True}, {"F": 5}):
            with self.assertRaises(ValueError):
                valid_review(
                    {**rows, MEM: dict(row, **change)}, SCOPES, paper("x")["abstract"]
                )
        with self.assertRaises(ValueError):
            valid_review({MEM: row}, SCOPES, row["quote"])

    def test_screen_rejection_hf_rescue_reuse_and_cross_date_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary_id, rescued, hf_only = ["2611.0000" + n for n in "123"]
            arxiv = {k: paper(k) for k in (primary_id, rescued)}
            hf = {k: paper(k) for k in (primary_id, rescued, hf_only)}
            client = Mock(default_model="test")

            def chat(messages, **kwargs):
                data = json.loads(messages[1]["content"])
                if isinstance(data, dict):
                    return {
                        k: {
                            d: "uncertain" if k != rescued else "unrelated"
                            for d in SCOPES
                        }
                        for k in data
                    }
                return {d: r for d, r in record()["domains"].items() if d in (MEM, EVO)}

            client.chat_json.side_effect = chat
            reviewer = EditionReviewer(SCOPES, root / "state", client)
            primary, reviews = reconcile(arxiv, hf, reviewer)
            self.assertEqual(primary, {primary_id})
            self.assertEqual(set(reviews), hf.keys())
            reconcile(arxiv, hf, reviewer)
            self.assertEqual(client.chat_json.call_count, 3)

            pub = EditionPublisher(
                root / "data", root / "state", SCOPES, translate=False, figures=False
            )
            ledger = pub.edition(DAY, [MEM, EVO], arxiv, hf, primary, reviews)
            self.assertEqual(ledger[rescued]["path"], "hf")
            self.assertEqual(ledger[primary_id]["path"], "arxiv")
            pub.commit(DAY)
            index_path = root / "data/index.json"
            first = read_json(index_path)
            for e in first["entries"]:
                self.assertEqual(e["paper_count"], 2 if e["domain"] == MEM else 0)
            self.assertEqual(len(list((root / "data/v2/papers").glob("*.json"))), 2)
            pub.edition(DAY, [MEM], arxiv, hf, primary, reviews)
            pub.commit(DAY)
            self.assertEqual(first, read_json(index_path))
            pub.edition("2026-11-20", [MEM], arxiv, hf, primary, reviews)
            pub.commit("2026-11-20")
            self.assertEqual(pub.entries[MEM, "2026-11-20"]["paper_count"], 0)
            self.assertEqual(pub.events[hf_only], [DAY, "2026-11-20"])

    def test_domain_vetoes_apply_even_to_a_perfect_model_review(self):
        for term in (
            "robotics",
            "embodied",
            "3-D",
            "autonomous driving",
            "camera",
        ):
            p = dict(paper("x"), title=f"Agent memory for video {term}")
            for domain in (MEM, EVO, MM):
                self.assertFalse(eligible(domain, p), (domain, term))
        for domain in (MEM, EVO):
            self.assertFalse(
                eligible(
                    domain,
                    dict(
                        paper("x"), title="Self-evolving agent memory for world models"
                    ),
                )
            )
        for term in ("image", "speech", "video", "omnimodal", "multimodal"):
            p = dict(paper("x"), title=f"Self-evolving {term} agent memory")
            self.assertFalse(eligible(MEM, p))
            self.assertFalse(eligible(EVO, p))
            self.assertTrue(eligible(MM, p))
        self.assertFalse(
            eligible(SHOP, dict(paper("x"), title="Recommendation for image synthesis"))
        )

    def test_calibration_counts_screen_misses_hf_rescues_and_prior_publications(self):
        pairs = [("from-hf", True), ("missed", True), ("unrelated", False)]
        labels = [
            {
                "date": DAY,
                "arxiv_id": k,
                "domain": MEM,
                "relevant": good,
                "recommend": good,
            }
            for k, good in pairs
        ]
        report = {
            "arxiv_ids": ["missed"],
            "decisions": {
                "from-hf": {
                    "path": "hf",
                    "review": record(),
                    "previously_recommended": [],
                },
                "unrelated": {
                    "path": "arxiv",
                    "review": record(),
                    "previously_recommended": [MEM],
                },
            },
        }
        result = evaluate(labels, {DAY: report})[MEM]
        self.assertEqual(result["precision"]["rate"], 1)
        self.assertEqual(result["recall"]["rate"], 0.5)
        self.assertEqual(result["screen_recall"]["rate"], 0)
        self.assertEqual(result["arxiv_only_recall"]["rate"], 0)

    def test_perfect_abstract_cannot_be_published_as_100(self):
        row = dict(scores(4), M=5, E=5, U=5)
        client = Mock(default_model="test")
        client.chat_json.return_value = {MEM: row}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("lib.edition_review.supplemental_text", return_value=""),
        ):
            result = EditionReviewer(SCOPES, tmp, client).review(
                paper("2611.12345"), [MEM]
            )
        self.assertEqual(value(result["domains"][MEM]), 82)

    def test_pdf_followup_validates_against_supplement_and_caches_result(self):
        client = Mock(default_model="test")
        rows = record()["domains"]
        more = dict(rows, **{MEM: dict(rows[MEM], needs_text=True)})
        final = dict(rows, **{MEM: dict(rows[MEM], quote="measured ablation")})
        client.chat_json.side_effect = [more, final]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "lib.edition_review.supplemental_text", return_value="measured ablation"
            ) as pdf,
        ):
            reviewer = EditionReviewer(SCOPES, tmp, client)
            self.assertEqual(
                reviewer.review(paper("2611.12345"), SCOPES)["evidence_scope"],
                "title/abstract/PDF",
            )
            reviewer.review(paper("2611.12345"), SCOPES)
            self.assertEqual(pdf.call_count, 1)

    def test_real_orchestrator_keeps_index_on_error_and_publishes_empty_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(
                domains_dir=run_daily.ROOT / "pipeline/domains",
                date=date.fromisoformat(DAY),
                domains=None,
                state_dir=root / "state",
                output=root / "data",
                arxiv_raw_cache_dir=root,
                refresh_arxiv=False,
                reuse_snapshot=False,
                llm_batch_size=12,
                storage_backend="repo",
                skip_llm=False,
                skip_translation=True,
                skip_figures=True,
            )
            with (
                patch(
                    "run_daily.build_arxiv_cache",
                    return_value={"categories": {"cs.AI": []}},
                ),
                patch("run_daily.time.sleep"),
            ):
                with patch("run_daily.fetch_hf", return_value={}):
                    run_daily.run(args)
                index = (args.output / "index.json").read_bytes()
                self.assertEqual(len(json.loads(index)["entries"]), 4)
                with (
                    patch("run_daily.fetch_hf", side_effect=RuntimeError("HF failure")),
                    self.assertRaises(RuntimeError),
                ):
                    run_daily.run(args)
                self.assertEqual((args.output / "index.json").read_bytes(), index)
                args.reuse_snapshot = True
                with (
                    patch("run_daily.fetch_hf", side_effect=AssertionError),
                    patch("run_daily.build_arxiv_cache", side_effect=AssertionError),
                ):
                    run_daily.run(args)
                    args.date = date.fromisoformat("2026-11-18")
                    with self.assertRaises(ValueError):
                        run_daily.run(args)


if __name__ == "__main__":
    unittest.main()
