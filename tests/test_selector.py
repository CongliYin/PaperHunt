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
        primary_score_bonus=0.0,
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

    def test_policy_score_bonus_applies_only_after_qualification(self) -> None:
        specialized = policy("specialized", priority=2)
        specialized = SelectionPolicy(
            **{
                **specialized.__dict__,
                "primary_score_bonus": 3.0,
            }
        )
        policies = {
            "specialized": specialized,
            "horizontal": policy("horizontal", standalone=("horizontal phrase",)),
        }

        qualified = choose_primary_domain(
            {"title": "exact domain phrase horizontal phrase"},
            policies,
        )
        unqualified = choose_primary_domain(
            {"title": "horizontal phrase"},
            policies,
        )

        self.assertEqual(qualified.primary_domain, "specialized")
        self.assertEqual(unqualified.primary_domain, "horizontal")


class EcommerceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policies = load_selection_policies(DOMAINS_DIR)

    def _primary(self, title: str, abstract: str = "") -> str | None:
        return choose_primary_domain(
            {"title": title, "abstract": abstract},
            self.policies,
        ).primary_domain

    def test_generic_item_recommendation_is_not_commerce_grounding(self) -> None:
        primary = self._primary(
            "Efficient Long-Sequence Recommendation",
            "A model ranks candidate items from long user histories.",
        )

        self.assertNotEqual(primary, "agent-e-commerce")

    def test_product_search_rl_method_is_in_scope(self) -> None:
        primary = self._primary(
            "Policy Optimization for E-Commerce Product Search",
            "We train the ranking model with reinforcement learning and GRPO.",
        )

        self.assertEqual(primary, "agent-e-commerce")

    def test_transaction_agent_without_guidance_is_out_of_scope(self) -> None:
        primary = self._primary(
            "Agentic Commerce Transaction Environment",
            "Buyer and merchant agents execute auditable payments in a catalog.",
        )

        self.assertNotEqual(primary, "agent-e-commerce")

    def test_recommendation_security_paper_is_out_of_scope(self) -> None:
        primary = self._primary(
            "Attacking and Defending Product Recommendation Agents",
            "We evaluate attacks against an e-commerce recommender system.",
        )

        self.assertNotEqual(primary, "agent-e-commerce")


class AgentMemoryScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policies = load_selection_policies(DOMAINS_DIR)

    def _primary(self, title: str, abstract: str = "") -> str | None:
        return choose_primary_domain(
            {"title": title, "abstract": abstract},
            self.policies,
        ).primary_domain

    def test_memory_centric_coding_agent_routes_to_agent_memory(self) -> None:
        primary = self._primary(
            "Artifact-Anchored Verification Memory for Coding Agents",
            "We persist and update verification claims across sessions.",
        )

        self.assertEqual(primary, "agent-memory")

    def test_memory_centric_search_agent_routes_to_agent_memory(self) -> None:
        primary = self._primary(
            "Evolving Long-Term Memory for Search Agents",
            "A memory system consolidates retrieved experience between tasks.",
        )

        self.assertEqual(primary, "agent-memory")

    def test_memory_centric_multimodal_agent_routes_to_agent_memory(self) -> None:
        primary = self._primary(
            "Agent Memory System for Realtime Multimodal Assistants",
            "The contribution is cross-session memory construction and correction.",
        )

        self.assertEqual(primary, "agent-memory")

    def test_search_agent_that_only_mentions_parametric_memory_stays_harness(self) -> None:
        primary = self._primary(
            "Training Search Agents via Evidence-Grounded Reinforcement Learning",
            "The agent searches beyond static parametric memory using external evidence.",
        )

        self.assertEqual(primary, "agent-harness-evolution")

    def test_generic_long_context_memory_is_out_of_scope(self) -> None:
        primary = self._primary(
            "Hierarchical Memory for Long Sequence Modeling",
            "A state space model improves long-context language modeling.",
        )

        self.assertNotEqual(primary, "agent-memory")

    def test_memory_attack_is_out_of_scope(self) -> None:
        primary = self._primary(
            "Query-Only Memory Attacks against Audited LLM Agents",
            "We study factual injection and privacy attacks.",
        )

        self.assertNotEqual(primary, "agent-memory")

    def test_personalized_agent_memory_is_in_scope(self) -> None:
        primary = self._primary(
            "Executable User Memory for Personalized Agents",
            "The persistent user model is updated across conversations.",
        )

        self.assertEqual(primary, "agent-memory")


class GoldSelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policies = load_selection_policies(DOMAINS_DIR)
        cls.gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))["domains"]

    def _history(self, domain: str) -> dict[str, dict]:
        records = {}
        # Gold labels describe expected ownership, not where a historical
        # detail currently lives after duplicate cleanup or migration.
        history_domains = [
            path.name
            for path in sorted(DATA_DIR.iterdir())
            if path.is_dir()
        ]
        for history_domain in history_domains:
            for detail_path in (DATA_DIR / history_domain).glob("????-??-??/*.json"):
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
