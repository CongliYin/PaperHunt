from __future__ import annotations

import unittest

from pipeline.lib.scorer import _normalize_assessment
from pipeline.rank_pipeline import filter_by_llm_domain_fit


def assessment(**overrides):
    value = {
        "domain_fit": 0.8,
        "novelty": 0.7,
        "problem_significance": 0.7,
        "potential_impact": 0.7,
        "paradigm_shift": 0.7,
        "lasting_value": 0.7,
        "comment": "Relevant.",
        "comment_zh": "相关。",
    }
    value.update(overrides)
    return value


class ScorerContractTests(unittest.TestCase):
    def test_normalized_assessment_preserves_domain_fit(self) -> None:
        normalized = _normalize_assessment(assessment(domain_fit=0.91))

        self.assertEqual(normalized["domain_fit"], 0.91)
        self.assertAlmostEqual(normalized["llm_avg"], 0.7)

    def test_missing_domain_fit_is_rejected_instead_of_defaulting(self) -> None:
        value = assessment()
        del value["domain_fit"]

        with self.assertRaisesRegex(ValueError, "missing required score domain_fit"):
            _normalize_assessment(value)

    def test_out_of_range_score_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be between 0 and 1"):
            _normalize_assessment(assessment(domain_fit=1.2))

    def test_publication_gate_rejects_missing_and_low_domain_fit(self) -> None:
        papers = [
            {"arxiv_id": "keep", "llm_assessment": assessment(domain_fit=0.8)},
            {"arxiv_id": "low", "llm_assessment": assessment(domain_fit=0.4)},
            {"arxiv_id": "legacy", "llm_assessment": {"llm_avg": 0.9}},
        ]

        kept = filter_by_llm_domain_fit(
            papers,
            minimum_domain_fit=0.65,
            verbose=False,
        )

        self.assertEqual([paper["arxiv_id"] for paper in kept], ["keep"])


if __name__ == "__main__":
    unittest.main()
