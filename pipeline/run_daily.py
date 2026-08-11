#!/usr/bin/env python3
"""Daily orchestrator for all configured paper-hunt domains."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from lib.arxiv_cache import build_arxiv_cache


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = Path(__file__).resolve().parent
RANK_PIPELINE = PIPELINE_DIR / "rank_pipeline.py"


@dataclass
class DomainResult:
    domain: str
    ok: bool
    message: str


def discover_domains(domains_dir: Path) -> list[str]:
    if not domains_dir.exists():
        return []
    return sorted(
        p.name
        for p in domains_dir.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


def local_date_offset(run_tz: str, offset_days: int, *, rollback_weekends: bool = False) -> str:
    tz = ZoneInfo(run_tz)
    date = datetime.now(tz).date() - timedelta(days=offset_days)
    if rollback_weekends:
        while date.weekday() >= 5:
            date -= timedelta(days=1)
    return date.isoformat()


def discover_arxiv_categories(domains_dir: Path, domains: list[str]) -> list[str]:
    """Load the complete, de-duplicated arXiv category set for selected domains."""
    categories: set[str] = set()
    for domain in domains:
        domain_yaml = domains_dir / domain / "domain.yaml"
        try:
            payload = yaml.safe_load(domain_yaml.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise RuntimeError(f"Required domain file missing: {domain_yaml}") from exc
        except (OSError, yaml.YAMLError) as exc:
            raise RuntimeError(f"Cannot read domain config {domain_yaml}: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Domain config must be a mapping: {domain_yaml}")
        configured = payload.get("arxiv_categories")
        if configured is None:
            configured = [payload.get("arxiv_category") or "cs.CV"]
        elif isinstance(configured, str):
            configured = [configured]
        elif not isinstance(configured, list):
            raise RuntimeError(f"arxiv_categories must be a list: {domain_yaml}")

        normalized = {str(category).strip() for category in configured if str(category).strip()}
        if not normalized:
            raise RuntimeError(f"No arXiv categories configured: {domain_yaml}")
        categories.update(normalized)

    return sorted(categories)


def run_domain(
    args: argparse.Namespace,
    domain: str,
    date: str,
    *,
    arxiv_cache: Path | None = None,
) -> DomainResult:
    date_folder = date
    report_dir = ROOT / "reports" / domain / date_folder
    tmp_dir = report_dir / "tmp"
    phase1_json = tmp_dir / "phase1.json"
    llm_scores_json = tmp_dir / "llm_scores.json"

    # A previous local run must never make an empty or failed fetch look successful.
    phase1_json.unlink(missing_ok=True)
    llm_scores_json.unlink(missing_ok=True)

    try:
        phase1_cmd = [
            sys.executable,
            str(RANK_PIPELINE),
            "--phase1-only",
            "--domain",
            domain,
            "--start-date",
            date,
            "--work-dir",
            str(ROOT),
        ]
        if arxiv_cache is not None:
            phase1_cmd += ["--arxiv-cache", str(arxiv_cache)]
        _run(phase1_cmd + _optional_phase1_args(args))
        if not phase1_json.exists():
            return DomainResult(domain, True, "no phase1 output; likely no papers")

        if args.skip_llm:
            return DomainResult(domain, True, "phase1 complete; skipped LLM and JSON")

        _run(
            [
                sys.executable,
                str(RANK_PIPELINE),
                "--score-llm",
                "--phase1-json",
                str(phase1_json),
                "--llm-scores",
                str(llm_scores_json),
                "--llm-batch-size",
                str(args.llm_batch_size),
            ]
        )
        _run(
            [
                sys.executable,
                str(RANK_PIPELINE),
                "--emit-json-only",
                "--phase1-json",
                str(phase1_json),
                "--llm-scores",
                str(llm_scores_json),
                "--data-dir",
                str(ROOT / "web" / "public" / "data"),
                "--figures-work-dir",
                str(ROOT / "tmp" / "figures"),
                "--storage-backend",
                args.storage_backend,
            ]
            + (["--skip-translation"] if args.skip_translation else [])
            + (["--skip-figures"] if args.skip_figures else [])
        )
        return DomainResult(domain, True, "ok")
    except subprocess.CalledProcessError as exc:
        return DomainResult(domain, False, f"failed with exit code {exc.returncode}")


def _optional_phase1_args(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    if args.top_n:
        out += ["--top-n", str(args.top_n)]
    if args.top_pct:
        out += ["--top-pct", str(args.top_pct)]
    if args.limit:
        out += ["--limit", str(args.limit)]
    return out


def _run(cmd: list[str]) -> None:
    print("[run]", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paper hunt for all domains")
    parser.add_argument("--date", default=None, help="Date to process, YYYY-MM-DD")
    parser.add_argument(
        "--date-offset-days",
        type=int,
        default=int(os.getenv("RUN_DATE_OFFSET_DAYS", "1")),
        help="Days before today in RUN_TZ to process when --date is empty",
    )
    parser.add_argument(
        "--rollback-weekends",
        action="store_true",
        default=os.getenv("RUN_ROLLBACK_WEEKENDS", "").lower() in {"1", "true", "yes"},
        help="When --date is empty, roll Saturday/Sunday back to the previous Friday",
    )
    parser.add_argument("--domains", default=None, help="Comma-separated domain ids")
    parser.add_argument("--domains-dir", default=str(PIPELINE_DIR / "domains"))
    parser.add_argument(
        "--arxiv-raw-cache-dir",
        default=os.getenv("ARXIV_RAW_CACHE_DIR", str(ROOT / "tmp" / "arxiv-raw")),
        help="Persistent per-category raw arXiv cache directory",
    )
    parser.add_argument(
        "--refresh-arxiv",
        action="store_true",
        default=os.getenv("ARXIV_REFRESH", "").lower() in {"1", "true", "yes"},
        help="Refetch every required arXiv category instead of reusing raw cache entries",
    )
    parser.add_argument("--storage-backend", choices=["blob", "repo"], default=os.getenv("STORAGE_BACKEND", "blob"))
    parser.add_argument("--skip-figures", action="store_true")
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--skip-llm", action="store_true", help="Debug: stop after phase1")
    parser.add_argument("--llm-batch-size", type=int, default=int(os.getenv("LLM_BATCH_SIZE", "16")))
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--top-pct", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_tz = os.getenv("RUN_TZ", "Asia/Tokyo")
    date = args.date or local_date_offset(run_tz, args.date_offset_days, rollback_weekends=args.rollback_weekends)
    domains_dir = Path(args.domains_dir)
    domains = (
        [d.strip() for d in args.domains.split(",") if d.strip()]
        if args.domains
        else discover_domains(domains_dir)
    )
    if not domains:
        raise SystemExit(f"No domains found in {domains_dir}")

    print(f"[daily] date={date} run_tz={run_tz} domains={', '.join(domains)}")
    cache_path = ROOT / "tmp" / "arxiv-cache" / f"{date}.json"
    try:
        categories = discover_arxiv_categories(domains_dir, domains)
        build_arxiv_cache(
            cache_path,
            start_date=date,
            end_date=date,
            categories=categories,
            raw_cache_dir=Path(args.arxiv_raw_cache_dir),
            refresh=args.refresh_arxiv,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[daily] arXiv prefetch failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    results = [
        run_domain(args, domain, date, arxiv_cache=cache_path)
        for domain in domains
    ]

    print("\n[daily] summary")
    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"  {status:4s} {result.domain}: {result.message}")

    if not any(r.ok for r in results):
        raise SystemExit(1)
    if any(not r.ok for r in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
