from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.lib.arxiv_cache import (
    ArxivCacheError,
    build_arxiv_cache,
    load_arxiv_cache,
    load_papers_from_cache,
)
from pipeline.lib.fetcher import ArxivFetchError


def paper(arxiv_id: str, published_at: str = "2026-08-05T00:00:00Z") -> dict:
    return {"arxiv_id": arxiv_id, "published_at": published_at, "title": arxiv_id}


class ArxivCacheTests(unittest.TestCase):
    def test_build_fetches_each_unique_category_once_and_writes_complete_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date",
                side_effect=lambda start, end, *, category, **kwargs: [paper(f"{category}-1")],
            ) as fetch:
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.CL", "cs.AI", "cs.CL"],
                    verbose=False,
                )

            self.assertEqual(fetch.call_count, 2)
            self.assertEqual([call.kwargs["category"] for call in fetch.call_args_list], ["cs.AI", "cs.CL"])
            self.assertEqual(sorted(payload["categories"]), ["cs.AI", "cs.CL"])
            self.assertEqual(json.loads(target.read_text())["schema_version"], 1)

    def test_failure_does_not_publish_partial_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date",
                side_effect=[[paper("2608.00001")], ArxivFetchError("HTTP 429")],
            ):
                with self.assertRaises(ArxivFetchError):
                    build_arxiv_cache(
                        target,
                        start_date="2026-08-05",
                        end_date="2026-08-05",
                        categories=["cs.AI", "cs.CL"],
                        verbose=False,
                    )

            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_valid_existing_cache_is_reused_without_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date",
                return_value=[paper("2608.00001")],
            ) as fetch:
                first = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    verbose=False,
                )
                second = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    verbose=False,
                )

            self.assertEqual(first, second)
            self.assertEqual(fetch.call_count, 1)

    def test_loading_selected_categories_deduplicates_versioned_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "cache.json"
            target.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "start_date": "2026-08-05",
                        "end_date": "2026-08-05",
                        "generated_at": "2026-08-06T00:00:00Z",
                        "categories": {
                            "cs.AI": [paper("2608.00001v1", "2026-08-05T02:00:00Z")],
                            "cs.CL": [
                                paper("2608.00001v2", "2026-08-05T02:00:00Z"),
                                paper("2608.00002v1", "2026-08-05T01:00:00Z"),
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            papers = load_papers_from_cache(
                target,
                start_date="2026-08-05",
                end_date=None,
                categories=["cs.CL", "cs.AI"],
            )

            self.assertEqual([item["arxiv_id"] for item in papers], ["2608.00002v1", "2608.00001v1"])

    def test_missing_required_category_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "cache.json"
            target.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "start_date": "2026-08-05",
                        "end_date": "2026-08-05",
                        "categories": {"cs.AI": []},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ArxivCacheError, "missing category cs.CL"):
                load_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    required_categories=["cs.AI", "cs.CL"],
                )


if __name__ == "__main__":
    unittest.main()
