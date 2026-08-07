from __future__ import annotations

import unittest

from pipeline.evaluate_selection_quality import load_detail_history, load_history


class SelectionEvaluatorTests(unittest.TestCase):
    def test_gold_corpus_keeps_excluded_details_after_publication_cleanup(self) -> None:
        domain = "agent-harness-evolution"
        excluded_id = "2608.04562"

        self.assertNotIn(excluded_id, load_history(domain))
        self.assertIn(excluded_id, load_detail_history(domain))


if __name__ == "__main__":
    unittest.main()
