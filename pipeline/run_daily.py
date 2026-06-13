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


def local_yesterday(run_tz: str) -> str:
    tz = ZoneInfo(run_tz)
    return (datetime.now(tz).date() - timedelta(days=1)).isoformat()


def run_domain(args: argparse.Namespace, domain: str, date: str) -> DomainResult:
    date_folder = date
    report_dir = ROOT / "reports" / domain / date_folder
    tmp_dir = report_dir / "tmp"
    phase1_json = tmp_dir / "phase1.json"
    llm_scores_json = tmp_dir / "llm_scores.json"

    try:
        _run(
            [
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
            + _optional_phase1_args(args)
        )
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
    parser.add_argument("--domains", default=None, help="Comma-separated domain ids")
    parser.add_argument("--domains-dir", default=str(PIPELINE_DIR / "domains"))
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
    date = args.date or local_yesterday(run_tz)
    domains_dir = Path(args.domains_dir)
    domains = (
        [d.strip() for d in args.domains.split(",") if d.strip()]
        if args.domains
        else discover_domains(domains_dir)
    )
    if not domains:
        raise SystemExit(f"No domains found in {domains_dir}")

    print(f"[daily] date={date} run_tz={run_tz} domains={', '.join(domains)}")
    results = [run_domain(args, domain, date) for domain in domains]

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

