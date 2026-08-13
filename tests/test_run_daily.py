from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import run_daily  # noqa: E402
from lib.fetcher import ArxivFetchError  # noqa: E402


class RunDailyTests(unittest.TestCase):
    def _write_domain(self, root: Path, name: str, categories: list[str]) -> None:
        domain_dir = root / name
        domain_dir.mkdir(parents=True)
        category_lines = "\n".join(f'  - "{category}"' for category in categories)
        (domain_dir / "domain.yaml").write_text(
            f'display_name: "{name}"\narxiv_categories:\n{category_lines}\n',
            encoding="utf-8",
        )

    def test_category_discovery_is_deterministic_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            domains_dir = Path(temp_dir)
            self._write_domain(domains_dir, "one", ["cs.CL", "cs.AI"])
            self._write_domain(domains_dir, "two", ["cs.AI", "cs.LG"])

            categories = run_daily.discover_arxiv_categories(domains_dir, ["two", "one"])

            self.assertEqual(categories, ["cs.AI", "cs.CL", "cs.LG"])

    def test_default_date_offset_processes_two_days_ago(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            domains_dir = Path(temp_dir)
            self._write_domain(domains_dir, "one", ["cs.AI"])
            argv = [
                "run_daily.py",
                "--domains",
                "one",
                "--domains-dir",
                str(domains_dir),
            ]
            shanghai = ZoneInfo("Asia/Shanghai")
            frozen_now = datetime(2026, 8, 13, 4, 0, tzinfo=shanghai)

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.dict(os.environ, {"RUN_TZ": "Asia/Shanghai"}, clear=True),
                mock.patch.object(run_daily, "datetime") as mocked_datetime,
                mock.patch.object(run_daily, "build_arxiv_cache"),
                mock.patch.object(
                    run_daily,
                    "run_domain",
                    return_value=run_daily.DomainResult("one", True, "ok"),
                ) as run_domain,
            ):
                mocked_datetime.now.return_value = frozen_now
                run_daily.main()

            self.assertEqual(run_domain.call_args.args[2], "2026-08-11")

    def test_prefetch_failure_stops_before_any_domain_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            domains_dir = Path(temp_dir)
            self._write_domain(domains_dir, "one", ["cs.AI"])
            argv = [
                "run_daily.py",
                "--date",
                "2026-08-05",
                "--domains",
                "one",
                "--domains-dir",
                str(domains_dir),
            ]
            stderr = io.StringIO()

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    run_daily,
                    "build_arxiv_cache",
                    side_effect=ArxivFetchError("HTTP 429"),
                ),
                mock.patch.object(run_daily, "run_domain") as run_domain,
                contextlib.redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as raised:
                    run_daily.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertIn("arXiv prefetch failed: HTTP 429", stderr.getvalue())
            run_domain.assert_not_called()

    def test_refresh_and_raw_cache_directory_are_forwarded_to_prefetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            raw_cache_dir = root / "persistent-arxiv"
            self._write_domain(domains_dir, "one", ["cs.AI"])
            argv = [
                "run_daily.py",
                "--date",
                "2026-08-05",
                "--domains",
                "one",
                "--domains-dir",
                str(domains_dir),
                "--arxiv-raw-cache-dir",
                str(raw_cache_dir),
                "--refresh-arxiv",
            ]

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(run_daily, "build_arxiv_cache") as build,
                mock.patch.object(
                    run_daily,
                    "run_domain",
                    return_value=run_daily.DomainResult("one", True, "ok"),
                ),
            ):
                run_daily.main()

            self.assertEqual(build.call_args.kwargs["raw_cache_dir"], raw_cache_dir)
            self.assertTrue(build.call_args.kwargs["refresh"])

    def test_domain_receives_cache_and_stale_phase_files_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_tmp = root / "reports" / "one" / "2026-08-05" / "tmp"
            report_tmp.mkdir(parents=True)
            phase1 = report_tmp / "phase1.json"
            scores = report_tmp / "llm_scores.json"
            phase1.write_text("stale", encoding="utf-8")
            scores.write_text("stale", encoding="utf-8")
            cache = root / "tmp" / "arxiv-cache" / "2026-08-05.json"
            args = SimpleNamespace(
                top_n=None,
                top_pct=None,
                limit=None,
                skip_llm=True,
            )

            with (
                mock.patch.object(run_daily, "ROOT", root),
                mock.patch.object(run_daily, "_run") as execute,
            ):
                result = run_daily.run_domain(
                    args,
                    "one",
                    "2026-08-05",
                    arxiv_cache=cache,
                )

            command = execute.call_args.args[0]
            self.assertEqual(command[command.index("--arxiv-cache") + 1], str(cache))
            self.assertFalse(phase1.exists())
            self.assertFalse(scores.exists())
            self.assertTrue(result.ok)
            self.assertIn("no phase1 output", result.message)


if __name__ == "__main__":
    unittest.main()
