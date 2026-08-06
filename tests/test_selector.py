from __future__ import annotations

import json
import unittest
from pathlib import Path

from pipeline.lib.selector import (
    SelectionPolicy,
    SignalGroup,
    choose_primary_domain,
    evaluate_policy,
    load_selection_policies,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAINS_DIR = ROOT / "pipeline" / "domains"
DATA_DIR = ROOT / "web" / "public" / "data"
GOLD_PATH = ROOT / "tests" / "fixtures" / "paper_selection_gold.json"


def policy(
    domain: str,
    *,
    priority: int = 0,
    minimum_selection_score: float = 0.0,
    standalone_signal_scope: str = "all",
    required_group_scope: str = "all",
    standalone: tuple[str, ...] = ("exact domain phrase",),
    groups: tuple[SignalGroup, ...] = (
        SignalGroup("context", ("domain",)),
        SignalGroup("capability", ("capability",)),
    ),
    exclusions: tuple[str, ...] = (),
) -> SelectionPolicy:
    return SelectionPolicy(
        domain=domain,
        priority=priority,
        minimum_selection_score=minimum_selection_score,
        minimum_llm_domain_fit=0.65,
        standalone_signal_scope=standalone_signal_scope,
        required_group_scope=required_group_scope,
        standalone_signals=standalone,
        required_groups=groups,
        supporting_signals=("support",),
        exclusions=exclusions,
    )


class SelectorUnitTests(unittest.TestCase):
    def test_all_required_groups_are_needed_without_standalone_signal(self) -> None:
        candidate = policy("one")
        missing = evaluate_policy({"title": "domain only", "abstract": ""}, candidate)
        complete = evaluate_policy(
            {"title": "domain capability", "abstract": "support"},
            candidate,
        )

        self.assertFalse(missing.qualified)
        self.assertTrue(complete.qualified)
        self.assertGreater(complete.score, 6.0)

    def test_exclusion_overrides_standalone_signal(self) -> None:
        candidate = policy("one", exclusions=("wrong vertical",))

        evaluation = evaluate_policy(
            {"title": "exact domain phrase", "abstract": "wrong vertical"},
            candidate,
        )

        self.assertFalse(evaluation.qualified)
        self.assertEqual(evaluation.score, 0.0)

    def test_minimum_selection_score_rejects_weak_group_match(self) -> None:
        candidate = policy("one", minimum_selection_score=6.9)

        weak = evaluate_policy(
            {"title": "study", "abstract": "domain capability"},
            candidate,
        )
        supported = evaluate_policy(
            {"title": "study", "abstract": "domain capability support"},
            candidate,
        )

        self.assertFalse(weak.qualified)
        self.assertTrue(supported.qualified)

    def test_title_evidence_scores_above_abstract_only_evidence(self) -> None:
        candidate = policy("one")

        title_evidence = evaluate_policy(
            {"title": "domain capability", "abstract": ""},
            candidate,
        )
        abstract_only = evaluate_policy(
            {"title": "study", "abstract": "domain capability"},
            candidate,
        )

        self.assertGreater(title_evidence.score, abstract_only.score)

    def test_title_group_scope_ignores_incidental_abstract_matches(self) -> None:
        candidate = policy("one", required_group_scope="title")

        evaluation = evaluate_policy(
            {"title": "domain study", "abstract": "capability"},
            candidate,
        )

        self.assertFalse(evaluation.qualified)

    def test_title_standalone_scope_ignores_incidental_abstract_matches(self) -> None:
        candidate = policy("one", standalone_signal_scope="title")

        evaluation = evaluate_policy(
            {"title": "unrelated study", "abstract": "exact domain phrase"},
            candidate,
        )

        self.assertFalse(evaluation.qualified)

    def test_standalone_signal_outranks_group_match(self) -> None:
        policies = {
            "specialized": policy("specialized", standalone=("exact phrase",)),
            "horizontal": policy("horizontal"),
        }
        paper = {"title": "exact phrase domain capability", "abstract": ""}

        decision = choose_primary_domain(paper, policies)

        self.assertEqual(decision.primary_domain, "specialized")

    def test_priority_breaks_equal_scores_deterministically(self) -> None:
        policies = {
            "low": policy("low", priority=1, standalone=("shared phrase",)),
            "high": policy("high", priority=2, standalone=("shared phrase",)),
        }

        decision = choose_primary_domain({"title": "shared phrase"}, policies)

        self.assertEqual(decision.primary_domain, "high")


class GoldSelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policies = load_selection_policies(DOMAINS_DIR)
        cls.gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))["domains"]

    def _history(self, domain: str) -> dict[str, dict]:
        records = {}
        for detail_path in (DATA_DIR / domain).glob("????-??-??/*.json"):
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
            records[detail["arxiv_id"]] = {
                "title": detail["title"],
                "abstract": detail["abstract_en"],
            }
        return records

    def test_all_user_approved_gold_labels(self) -> None:
        for domain, labels in self.gold.items():
            history = self._history(domain)
            for arxiv_id in labels["include"]:
                with self.subTest(domain=domain, label="include", arxiv_id=arxiv_id):
                    decision = choose_primary_domain(history[arxiv_id], self.policies)
                    self.assertEqual(decision.primary_domain, domain)
            for arxiv_id in labels["exclude"]:
                with self.subTest(domain=domain, label="exclude", arxiv_id=arxiv_id):
                    decision = choose_primary_domain(history[arxiv_id], self.policies)
                    self.assertNotEqual(decision.primary_domain, domain)


if __name__ == "__main__":
    unittest.main()
