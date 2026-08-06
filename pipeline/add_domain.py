#!/usr/bin/env python3
"""Create a new domain config from the template."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parent


def display_name(domain_id: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", domain_id))


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a paper-hunt domain")
    parser.add_argument("domain_id")
    args = parser.parse_args()

    domain_id = args.domain_id.strip()
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", domain_id):
        raise SystemExit("domain-id must use lowercase letters, numbers, and hyphens")

    template = PIPELINE_DIR / "domains" / "_template"
    target = PIPELINE_DIR / "domains" / domain_id
    if target.exists():
        raise SystemExit(f"Domain already exists: {target}")
    if not template.exists():
        raise SystemExit(f"Template directory missing: {template}")

    shutil.copytree(template, target)
    replacements = {
        "__DOMAIN_ID__": domain_id,
        "__DISPLAY_NAME__": display_name(domain_id),
        "__OUTPUT_SUFFIX__": f"{domain_id.replace('-', '_')}_paper_rank",
    }
    for path in target.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for old, new in replacements.items():
                text = text.replace(old, new)
            path.write_text(text, encoding="utf-8")

    print(f"Created {target}")
    print("Next: edit the five config files, then run:")
    print(f"  python {PIPELINE_DIR / 'validate_domain.py'} {domain_id}")


if __name__ == "__main__":
    main()
