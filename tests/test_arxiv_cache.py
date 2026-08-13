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
    raw_category_cache_path,
)
from pipeline.lib.fetcher import ArxivFetchError


def paper(
    arxiv_id: str,
    published_at: str = "2026-08-05T00:00:00Z",
    *,
    categories: tuple[str, ...] = ("cs.AI",),
) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "published_at": published_at,
        "title": arxiv_id,
        "categories": list(categories),
        "primary_category": categories[0] if categories else "",
    }


class ArxivCacheTests(unittest.TestCase):
    def test_build_fetches_all_missing_categories_in_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            response = [
                paper("2608.00001", categories=("cs.AI",)),
                paper("2608.00002", categories=("cs.CL",)),
            ]

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=response,
            ) as fetch:
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.CL", "cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.kwargs["categories"], ["cs.AI", "cs.CL"])
            self.assertEqual(sorted(payload["categories"]), ["cs.AI", "cs.CL"])
            self.assertEqual(payload["categories"]["cs.AI"][0]["arxiv_id"], "2608.00001")
            self.assertEqual(payload["categories"]["cs.CL"][0]["arxiv_id"], "2608.00002")
            self.assertEqual(json.loads(target.read_text())["schema_version"], 1)

    def test_combined_response_is_partitioned_and_cross_lists_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            cross_listed = paper("2608.00001", categories=("cs.AI", "cs.CL"))

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[cross_listed],
            ):
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    verbose=False,
                )

            self.assertEqual(payload["categories"]["cs.AI"], [cross_listed])
            self.assertEqual(payload["categories"]["cs.CL"], [cross_listed])

    def test_failure_preserves_existing_raw_category_without_publishing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            ai_path = raw_category_cache_path(
                raw_root,
                start_date="2026-08-05",
                end_date=None,
                category="cs.AI",
            )
            cl_path = raw_category_cache_path(
                raw_root,
                start_date="2026-08-05",
                end_date=None,
                category="cs.CL",
            )

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ):
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                side_effect=ArxivFetchError("HTTP 429"),
            ):
                with self.assertRaises(ArxivFetchError):
                    build_arxiv_cache(
                        target,
                        start_date="2026-08-05",
                        end_date=None,
                        categories=["cs.AI", "cs.CL"],
                        raw_cache_dir=raw_root,
                        verbose=False,
                    )

            self.assertFalse(target.exists())
            self.assertTrue(ai_path.exists())
            self.assertFalse(cl_path.exists())

    def test_all_empty_response_is_rejected_without_writing_any_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[],
            ):
                with self.assertRaisesRegex(ArxivCacheError, "zero papers"):
                    build_arxiv_cache(
                        target,
                        start_date="2026-08-05",
                        end_date=None,
                        categories=["cs.AI", "cs.CL"],
                        raw_cache_dir=raw_root,
                        verbose=False,
                    )

            self.assertFalse(target.exists())
            self.assertFalse(raw_root.exists())

    def test_all_empty_existing_cache_is_treated_as_suspect_and_refetched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001", categories=("cs.AI",))],
            ):
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00002", categories=("cs.CL",))],
            ) as fetch:
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(payload["categories"]["cs.CL"][0]["arxiv_id"], "2608.00002")

    def test_partial_all_empty_cache_refetches_the_full_required_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            ai_path = raw_category_cache_path(
                raw_root,
                start_date="2026-08-05",
                end_date=None,
                category="cs.AI",
            )

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001", categories=("cs.AI",))],
            ):
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )
            ai_path.unlink()

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00002", categories=("cs.AI",))],
            ) as fetch:
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.kwargs["categories"], ["cs.AI", "cs.CL"])

    def test_empty_missing_category_is_valid_when_existing_category_has_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ):
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[],
            ) as fetch:
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.kwargs["categories"], ["cs.CL"])
            self.assertEqual(payload["categories"]["cs.CL"], [])

    def test_valid_existing_cache_is_reused_without_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ) as fetch:
                first = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )
                second = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            self.assertEqual(first["categories"], second["categories"])
            self.assertEqual(fetch.call_count, 1)

    def test_adding_category_fetches_only_the_missing_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            responses = [
                [paper("2608.00001", categories=("cs.AI",))],
                [paper("2608.00002", categories=("cs.CL",))],
            ]
            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                side_effect=responses,
            ) as fetch:
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )
                fetch.reset_mock()

                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI", "cs.CL"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.kwargs["categories"], ["cs.CL"])
            self.assertEqual(sorted(payload["categories"]), ["cs.AI", "cs.CL"])

    def test_stale_query_fingerprint_refetches_affected_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            raw_path = raw_category_cache_path(
                raw_root,
                start_date="2026-08-05",
                end_date=None,
                category="cs.AI",
            )
            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ) as fetch:
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )
                stale = json.loads(raw_path.read_text(encoding="utf-8"))
                stale["query_fingerprint"] = "stale"
                raw_path.write_text(json.dumps(stale), encoding="utf-8")
                fetch.reset_mock()

                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()

    def test_forced_refresh_refetches_existing_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ) as fetch:
                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )
                fetch.reset_mock()

                build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    refresh=True,
                    verbose=False,
                )

            fetch.assert_called_once()

    def test_malformed_raw_category_is_repaired_by_refetching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "2026-08-05.json"
            raw_root = Path(temp_dir) / "raw"
            raw_path = raw_category_cache_path(
                raw_root,
                start_date="2026-08-05",
                end_date=None,
                category="cs.AI",
            )
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text("not-json", encoding="utf-8")

            with mock.patch(
                "pipeline.lib.arxiv_cache.fetch_papers_by_date_multi_category",
                return_value=[paper("2608.00001")],
            ) as fetch:
                payload = build_arxiv_cache(
                    target,
                    start_date="2026-08-05",
                    end_date=None,
                    categories=["cs.AI"],
                    raw_cache_dir=raw_root,
                    verbose=False,
                )

            fetch.assert_called_once()
            self.assertEqual(payload["categories"]["cs.AI"][0]["arxiv_id"], "2608.00001")
            self.assertTrue(json.loads(raw_path.read_text(encoding="utf-8"))["complete"])

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

            self.assertEqual(
                [item["arxiv_id"] for item in papers],
                ["2608.00002v1", "2608.00001v1"],
            )

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
