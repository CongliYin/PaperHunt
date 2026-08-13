#!/usr/bin/env python3
"""Prepare and atomically apply the Agent Memory historical migration."""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from lib.selector import choose_primary_domain, load_selection_policies
except ModuleNotFoundError:  # Imported as pipeline.migrate_agent_memory_history.
    from pipeline.lib.selector import choose_primary_domain, load_selection_policies


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "web" / "public" / "data"
DEFAULT_DOMAINS_DIR = ROOT / "pipeline" / "domains"
MEMORY_DOMAIN = "agent-memory"
MEMORY_DISPLAY_NAME = "Agent Memory"
MANIFEST_SCHEMA_VERSION = 1
LLM_DIMENSIONS = (
    "novelty",
    "problem_significance",
    "potential_impact",
    "paradigm_shift",
    "lasting_value",
)
INTERNAL_SCORE_WEIGHTS = {
    "topic_relevance": 0.40,
    "llm_assessment": 0.30,
    "open_source": 0.10,
    "community_heat": 0.05,
    "author_reputation": 0.05,
    "venue_signal": 0.05,
    "generality": 0.05,
}


class MigrationError(RuntimeError):
    """Raised when historical data cannot be migrated without data loss."""


def prepare_migration(
    *,
    data_dir: str | Path,
    domains_dir: str | Path,
) -> dict[str, Any]:
    data_root = Path(data_dir)
    policies = load_selection_policies(domains_dir)
    if MEMORY_DOMAIN not in policies:
        raise MigrationError(f"missing selection policy for {MEMORY_DOMAIN}")

    published = _load_published(data_root)
    papers: list[dict[str, Any]] = []
    removals: list[dict[str, str]] = []
    seen_memory_ids: set[str] = set()
    seen_ownership_changes: set[tuple[str, str, str]] = set()

    for item in published:
        detail = item["detail"]
        arxiv_id = item["arxiv_id"]
        decision = choose_primary_domain(
            {
                "title": detail.get("title", ""),
                "abstract": detail.get("abstract_en", ""),
            },
            policies,
        )
        destination = decision.primary_domain
        removal_key = (item["source_domain"], item["source_date"], arxiv_id)
        if (
            destination != item["source_domain"]
            and removal_key not in seen_ownership_changes
        ):
            seen_ownership_changes.add(removal_key)
            removals.append(
                {
                    "source_domain": item["source_domain"],
                    "source_date": item["source_date"],
                    "arxiv_id": arxiv_id,
                    "destination_domain": destination or "",
                }
            )
        if (
            destination != MEMORY_DOMAIN
            or item["source_domain"] == MEMORY_DOMAIN
            or arxiv_id in seen_memory_ids
        ):
            continue

        seen_memory_ids.add(arxiv_id)
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": detail.get("title", ""),
                "abstract": detail.get("abstract_en", ""),
                "source_domain": item["source_domain"],
                "source_date": item["source_date"],
                "source_list": item["list_path"].relative_to(data_root).as_posix(),
                "source_detail": item["detail_path"].relative_to(data_root).as_posix(),
            }
        )

    papers.sort(key=lambda item: (item["source_date"], item["arxiv_id"]))
    removals.sort(
        key=lambda item: (
            item["source_domain"],
            item["source_date"],
            item["arxiv_id"],
        )
    )
    duplicate_ids = _published_duplicate_ids(published)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "target_domain": MEMORY_DOMAIN,
        "display_name": MEMORY_DISPLAY_NAME,
        "minimum_llm_domain_fit": policies[MEMORY_DOMAIN].minimum_llm_domain_fit,
        "papers": papers,
        "removals": removals,
        "duplicate_ids": duplicate_ids,
    }


def apply_migration(
    *,
    data_dir: str | Path,
    domains_dir: str | Path,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    remove_stale: bool = False,
) -> dict[str, int]:
    data_root = Path(data_dir).resolve()
    _validate_manifest(manifest)
    normalized_scores = _validate_scores(manifest, scores)

    if not manifest["papers"] and not manifest["duplicate_ids"]:
        validate_published_data(data_root)
        return {
            "candidates": 0,
            "migrated": 0,
            "rejected_by_llm": 0,
            "removed_from_old_lists": 0,
        }

    data_root.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(
        tempfile.mkdtemp(prefix=f".{data_root.name}.agent-memory-", dir=data_root.parent)
    )
    backup_root = data_root.with_name(f".{data_root.name}.pre-agent-memory")
    try:
        shutil.copytree(data_root, stage_root, dirs_exist_ok=True)
        stats = _rewrite_staged_data(
            stage_root=stage_root,
            domains_dir=Path(domains_dir),
            manifest=manifest,
            scores=normalized_scores,
            remove_stale=remove_stale,
        )
        validate_published_data(stage_root)

        if backup_root.exists():
            raise MigrationError(f"stale migration backup exists: {backup_root}")
        data_root.replace(backup_root)
        try:
            stage_root.replace(data_root)
        except Exception:
            backup_root.replace(data_root)
            raise
        shutil.rmtree(backup_root)
        return stats
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root)


def validate_published_data(
    data_dir: str | Path,
    *,
    require_unique: bool = True,
) -> dict[str, int]:
    data_root = Path(data_dir)
    index_path = data_root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read index: {exc}") from exc

    list_paths = sorted(data_root.glob("*/????-??-??.json"))
    actual_entries: dict[tuple[str, str], dict[str, Any]] = {}
    owners: dict[str, tuple[str, str]] = {}
    paper_count = 0
    for list_path in list_paths:
        payload = _read_json_object(list_path)
        domain = str(payload.get("domain") or "").strip()
        date = str(payload.get("date") or "").strip()
        if domain != list_path.parent.name or date != list_path.stem:
            raise MigrationError(f"list identity mismatch: {list_path}")
        cards = payload.get("papers")
        if not isinstance(cards, list):
            raise MigrationError(f"papers must be a list: {list_path}")
        for card in cards:
            if not isinstance(card, dict):
                raise MigrationError(f"invalid paper card: {list_path}")
            arxiv_id = _clean_id(card.get("arxiv_id", ""))
            if not arxiv_id:
                raise MigrationError(f"paper card missing arxiv_id: {list_path}")
            owner = owners.get(arxiv_id)
            if require_unique and owner and owner != (domain, date):
                raise MigrationError(
                    f"cross-domain duplicate {arxiv_id}: "
                    f"{owner[0]}/{owner[1]} and {domain}/{date}"
                )
            owners.setdefault(arxiv_id, (domain, date))
            expected_detail = f"{domain}/{date}/{arxiv_id}.json"
            if card.get("detail_file") != expected_detail:
                raise MigrationError(f"detail_file mismatch for {arxiv_id}: {list_path}")
            detail_path = data_root / expected_detail
            detail = _read_json_object(detail_path)
            if _clean_id(detail.get("arxiv_id", "")) != arxiv_id:
                raise MigrationError(f"detail arxiv_id mismatch: {detail_path}")
            paper_count += 1
        actual_entries[(domain, date)] = {
            "domain": domain,
            "date": date,
            "paper_count": len(cards),
            "file": f"{domain}/{date}.json",
        }

    indexed_entries = index.get("entries")
    if not isinstance(indexed_entries, list):
        raise MigrationError("index entries must be a list")
    indexed = {
        (str(entry.get("domain")), str(entry.get("date"))): {
            "domain": entry.get("domain"),
            "date": entry.get("date"),
            "paper_count": entry.get("paper_count"),
            "file": entry.get("file"),
        }
        for entry in indexed_entries
        if isinstance(entry, dict)
    }
    if indexed != actual_entries:
        raise MigrationError("index entries do not match published list files")

    index_domains = index.get("domains")
    if not isinstance(index_domains, list):
        raise MigrationError("index domains must be a list")
    expected_domains = {domain for domain, _ in actual_entries}
    indexed_domains = {
        str(item.get("id"))
        for item in index_domains
        if isinstance(item, dict) and item.get("id")
    }
    if indexed_domains != expected_domains:
        raise MigrationError("index domains do not match published domains")

    return {
        "lists": len(actual_entries),
        "papers": paper_count,
        "domains": len(expected_domains),
    }


def _rewrite_staged_data(
    *,
    stage_root: Path,
    domains_dir: Path,
    manifest: dict[str, Any],
    scores: dict[str, dict[str, Any]],
    remove_stale: bool,
) -> dict[str, int]:
    policies = load_selection_policies(domains_dir)
    memory_policy = policies[MEMORY_DOMAIN]
    topic_cfg = _read_yaml(domains_dir / MEMORY_DOMAIN / "topic_keywords.yaml")

    published = _load_published(stage_root)
    original_by_location: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in published:
        original_by_location[
            (item["arxiv_id"], item["source_domain"], item["source_date"])
        ] = item

    current_duplicate_ids = set(_published_duplicate_ids(published))
    expected_duplicate_ids = set(manifest.get("duplicate_ids") or [])
    if current_duplicate_ids != expected_duplicate_ids:
        raise MigrationError(
            "published duplicate set changed after prepare: "
            f"expected={sorted(expected_duplicate_ids)}, "
            f"actual={sorted(current_duplicate_ids)}"
        )

    accepted: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    moved_ids: set[str] = set()
    for candidate in manifest["papers"]:
        arxiv_id = candidate["arxiv_id"]
        assessment = scores[arxiv_id]
        if assessment["domain_fit"] < memory_policy.minimum_llm_domain_fit:
            continue
        source = original_by_location.get(
            (arxiv_id, candidate["source_domain"], candidate["source_date"])
        )
        if source is None:
            raise MigrationError(
                "published source disappeared for "
                f"{candidate['source_domain']}/{candidate['source_date']}/{arxiv_id}"
            )
        accepted[(MEMORY_DOMAIN, source["source_date"])].append(
            _build_memory_record(source, assessment, topic_cfg)
        )
        moved_ids.add(arxiv_id)

    final_owner: dict[str, tuple[str, str]] = {}
    for item in published:
        if item["arxiv_id"] in moved_ids:
            continue
        detail = item["detail"]
        decision = choose_primary_domain(
            {
                "title": detail.get("title", ""),
                "abstract": detail.get("abstract_en", ""),
            },
            policies,
        ).primary_domain
        if decision == item["source_domain"]:
            final_owner[item["arxiv_id"]] = (
                item["source_domain"],
                item["source_date"],
            )
    for item in published:
        if item["arxiv_id"] in moved_ids or item["arxiv_id"] in final_owner:
            continue
        final_owner[item["arxiv_id"]] = (
            item["source_domain"],
            item["source_date"],
        )

    # Only approved Memory papers move by default. A candidate rejected by the
    # Memory rubric stays in its historical source collection. The list/detail
    # bytes stay unchanged unless that file also contains a resolved duplicate.
    removed_ids_by_location: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in published:
        key = (item["source_domain"], item["source_date"])
        if item["arxiv_id"] in moved_ids:
            removed_ids_by_location[key].add(item["arxiv_id"])
            continue
        if (
            item["arxiv_id"] in expected_duplicate_ids
            and final_owner[item["arxiv_id"]] != key
        ):
            removed_ids_by_location[key].add(item["arxiv_id"])
            continue
        if remove_stale:
            detail = item["detail"]
            decision = choose_primary_domain(
                {
                    "title": detail.get("title", ""),
                    "abstract": detail.get("abstract_en", ""),
                },
                policies,
            ).primary_domain
            if decision != item["source_domain"]:
                removed_ids_by_location[key].add(item["arxiv_id"])

    # Touch only lists that lose papers. This keeps unrelated historical output
    # byte-for-byte stable and leaves an empty list when its last paper moves.
    for list_path in sorted(stage_root.glob("*/????-??-??.json")):
        key = (list_path.parent.name, list_path.stem)
        removed_ids = removed_ids_by_location.get(key, set())
        if not removed_ids:
            continue
        payload = _read_json_object(list_path)
        payload["papers"] = [
            card
            for card in payload.get("papers", [])
            if _clean_id(card.get("arxiv_id", "")) not in removed_ids
        ]
        _write_json(list_path, payload)
        for arxiv_id in removed_ids:
            (stage_root / key[0] / key[1] / f"{arxiv_id}.json").unlink(missing_ok=True)

    for key, records in sorted(accepted.items()):
        domain, date = key
        domain_dir = stage_root / domain
        detail_dir = domain_dir / date
        detail_dir.mkdir(parents=True, exist_ok=True)
        list_path = domain_dir / f"{date}.json"
        existing = _read_json_object(list_path) if list_path.exists() else {
            "domain": domain,
            "display_name": MEMORY_DISPLAY_NAME,
            "date": date,
            "generated_at": _utc_now(),
            "papers": [],
        }
        existing["papers"] = _dedupe_cards(
            list(existing.get("papers") or []) + [record["card"] for record in records]
        )
        existing["display_name"] = MEMORY_DISPLAY_NAME
        _write_json(list_path, existing)
        for record in records:
            _write_json(detail_dir / f"{record['arxiv_id']}.json", record["detail"])

    # Remove empty detail directories left after published-card cleanup.
    for directory in sorted(stage_root.glob("*/????-??-??"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()

    _rebuild_index(stage_root)
    return {
        "candidates": len(manifest["papers"]),
        "migrated": len(moved_ids),
        "rejected_by_llm": len(manifest["papers"]) - len(moved_ids),
        "removed_from_old_lists": sum(len(ids) for ids in removed_ids_by_location.values()),
    }


def _build_memory_record(
    source: dict[str, Any],
    assessment: dict[str, Any],
    topic_cfg: dict[str, Any],
) -> dict[str, Any]:
    detail = copy.deepcopy(source["detail"])
    card = copy.deepcopy(source["card"])
    arxiv_id = source["arxiv_id"]

    topic_score, category = _score_topic(detail, topic_cfg)
    scores = copy.deepcopy(detail.get("scores") or {})
    scores["topic_relevance"] = topic_score
    scores["llm_assessment"] = assessment["llm_avg"]
    scores["domain_multiplier"] = _domain_multiplier(detail, topic_cfg, topic_score)
    for key in INTERNAL_SCORE_WEIGHTS:
        scores.setdefault(key, 0.0)
    total_score = sum(
        float(scores.get(key, 0.0)) * weight
        for key, weight in INTERNAL_SCORE_WEIGHTS.items()
    ) * float(scores.get("domain_multiplier", 1.0))

    detail["llm_assessment"] = assessment
    detail["scores"] = scores
    card["total_score"] = total_score
    card["scores"] = {
        "topic_relevance": scores["topic_relevance"],
        "llm_assessment": assessment["llm_avg"],
        "domain_fit": assessment["domain_fit"],
        "other": _other_score(scores),
    }
    card["detail_file"] = f"{MEMORY_DOMAIN}/{source['source_date']}/{arxiv_id}.json"
    if category:
        tags = [tag for tag in card.get("tags", []) if tag != detail.get("strategic_category")]
        label = category.replace("_", " ")
        if label not in tags:
            tags.append(label)
        card["tags"] = tags
        detail["strategic_category"] = category
    return {"arxiv_id": arxiv_id, "detail": detail, "card": card}


def _load_published(data_root: Path) -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = []
    for list_path in sorted(data_root.glob("*/????-??-??.json")):
        payload = _read_json_object(list_path)
        source_domain = str(payload.get("domain") or list_path.parent.name)
        source_date = str(payload.get("date") or list_path.stem)
        cards = payload.get("papers")
        if not isinstance(cards, list):
            raise MigrationError(f"papers must be a list: {list_path}")
        for card in cards:
            if not isinstance(card, dict):
                raise MigrationError(f"invalid paper card: {list_path}")
            arxiv_id = _clean_id(card.get("arxiv_id", ""))
            detail_path = data_root / source_domain / source_date / f"{arxiv_id}.json"
            detail = _read_json_object(detail_path)
            published.append(
                {
                    "source_domain": source_domain,
                    "source_date": source_date,
                    "arxiv_id": arxiv_id,
                    "list_path": list_path,
                    "detail_path": detail_path,
                    "card": card,
                    "detail": detail,
                }
            )
    return published


def _published_duplicate_ids(published: list[dict[str, Any]]) -> list[str]:
    owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in published:
        owners[item["arxiv_id"]].add(
            (item["source_domain"], item["source_date"])
        )
    return sorted(arxiv_id for arxiv_id, locations in owners.items() if len(locations) > 1)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise MigrationError("unsupported migration manifest schema")
    if manifest.get("target_domain") != MEMORY_DOMAIN:
        raise MigrationError("migration manifest target mismatch")
    papers = manifest.get("papers")
    if not isinstance(papers, list):
        raise MigrationError("migration manifest papers must be a list")
    ids = [_clean_id(item.get("arxiv_id", "")) for item in papers if isinstance(item, dict)]
    if len(ids) != len(papers) or any(not arxiv_id for arxiv_id in ids):
        raise MigrationError("migration manifest contains invalid paper entries")
    if len(ids) != len(set(ids)):
        raise MigrationError("migration manifest contains duplicate arxiv IDs")
    duplicate_ids = manifest.get("duplicate_ids")
    if not isinstance(duplicate_ids, list):
        raise MigrationError("migration manifest duplicate_ids must be a list")
    normalized_duplicates = [_clean_id(arxiv_id) for arxiv_id in duplicate_ids]
    if (
        any(not arxiv_id for arxiv_id in normalized_duplicates)
        or len(normalized_duplicates) != len(set(normalized_duplicates))
        or normalized_duplicates != sorted(normalized_duplicates)
    ):
        raise MigrationError("migration manifest contains invalid duplicate IDs")


def _validate_scores(
    manifest: dict[str, Any],
    scores: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not isinstance(scores, dict):
        raise MigrationError("LLM scores must be a JSON object")
    expected = {item["arxiv_id"] for item in manifest["papers"]}
    actual = {_clean_id(key) for key in scores}
    missing = sorted(expected - actual)
    if missing:
        raise MigrationError(f"missing LLM assessments: {', '.join(missing)}")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_id, raw in scores.items():
        arxiv_id = _clean_id(raw_id)
        if arxiv_id not in expected:
            continue
        if not isinstance(raw, dict):
            raise MigrationError(f"invalid LLM assessment for {arxiv_id}")
        item: dict[str, Any] = {}
        dimensions = ("domain_fit", *LLM_DIMENSIONS)
        for field in dimensions:
            try:
                value = float(raw[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise MigrationError(f"invalid {field} for {arxiv_id}") from exc
            if not 0.0 <= value <= 1.0:
                raise MigrationError(f"{field} out of range for {arxiv_id}")
            item[field] = value
        item["llm_avg"] = sum(item[field] for field in LLM_DIMENSIONS) / len(LLM_DIMENSIONS)
        item["comment"] = str(raw.get("comment") or "").strip()
        item["comment_zh"] = str(raw.get("comment_zh") or raw.get("comment") or "").strip()
        normalized[arxiv_id] = item
    return normalized


def _score_topic(detail: dict[str, Any], topic_cfg: dict[str, Any]) -> tuple[float, str | None]:
    text = f"{detail.get('title', '')}\n{detail.get('abstract_en', '')}".lower()
    best = 0.0
    category: str | None = None
    hits = 0
    for tier in (topic_cfg.get("tiers") or {}).values():
        coefficient = float(tier.get("coefficient", 0.0))
        for name, keywords in (tier.get("categories") or {}).items():
            matched = [keyword for keyword in keywords if _phrase_matches(text, keyword)]
            if not matched:
                continue
            hits += len(matched)
            if coefficient > best:
                best = coefficient
                category = name
    if best == 0.0:
        return 0.0, None
    return min(best * 0.8 + min(max(hits - 1, 0) * 0.04, 0.2), 1.0), category


def _domain_multiplier(detail: dict[str, Any], topic_cfg: dict[str, Any], topic: float) -> float:
    text = f"{detail.get('title', '')}\n{detail.get('abstract_en', '')}".lower()
    multiplier = 1.0
    for spec in (topic_cfg.get("domain_penalties") or {}).values():
        if any(_phrase_matches(text, keyword) for keyword in spec.get("keywords", [])):
            multiplier = min(multiplier, float(spec.get("multiplier", 1.0)))
    if topic >= 0.85:
        multiplier = max(multiplier, 0.9)
    elif topic >= 0.7:
        multiplier = max(multiplier, 0.85)
    return max(0.0, min(multiplier, 1.0))


def _other_score(scores: dict[str, Any]) -> float:
    keys = ("open_source", "community_heat", "author_reputation", "venue_signal", "generality")
    total_weight = sum(INTERNAL_SCORE_WEIGHTS[key] for key in keys)
    return sum(
        float(scores.get(key, 0.0)) * INTERNAL_SCORE_WEIGHTS[key]
        for key in keys
    ) / total_weight


def _phrase_matches(text: str, phrase: str) -> bool:
    normalized = re.escape(str(phrase).strip().lower()).replace(r"\ ", r"[\s\-]+")
    return bool(re.search(rf"(?<![a-z0-9]){normalized}(?![a-z0-9])", text))


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for card in cards:
        arxiv_id = _clean_id(card.get("arxiv_id", ""))
        if arxiv_id:
            by_id[arxiv_id] = card
    return sorted(by_id.values(), key=lambda card: float(card.get("total_score", 0.0)), reverse=True)


def _rebuild_index(data_root: Path) -> None:
    old = _read_json_object(data_root / "index.json")
    names = {
        str(item.get("id")): str(item.get("display_name"))
        for item in old.get("domains", [])
        if isinstance(item, dict) and item.get("id")
    }
    names[MEMORY_DOMAIN] = MEMORY_DISPLAY_NAME
    entries: list[dict[str, Any]] = []
    active_domains: set[str] = set()
    for list_path in sorted(data_root.glob("*/????-??-??.json")):
        payload = _read_json_object(list_path)
        domain = list_path.parent.name
        date = list_path.stem
        active_domains.add(domain)
        names[domain] = str(payload.get("display_name") or names.get(domain) or domain)
        entries.append(
            {
                "domain": domain,
                "date": date,
                "paper_count": len(payload.get("papers") or []),
                "file": f"{domain}/{date}.json",
            }
        )
    entries.sort(key=lambda entry: (entry["domain"], entry["date"]), reverse=True)
    payload = {
        "generated_at": _utc_now(),
        "domains": sorted(
            ({"id": domain, "display_name": names[domain]} for domain in active_domains),
            key=lambda item: item["display_name"],
        ),
        "entries": entries,
    }
    _write_json(data_root / "index.json", payload)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError(f"missing JSON file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"JSON root must be an object: {path}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise MigrationError(f"YAML root must be a mapping: {path}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_id(value: Any) -> str:
    return re.sub(r"v\d+$", "", str(value or "").strip())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--domains-dir", default=str(DEFAULT_DOMAINS_DIR))
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--phase1-json", required=True)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--manifest", required=True)
    apply.add_argument("--scores", required=True)
    apply.add_argument(
        "--remove-stale",
        action="store_true",
        help="Also remove non-Memory papers that no longer satisfy their source policy",
    )

    subparsers.add_parser("validate")
    args = parser.parse_args()

    if args.command == "prepare":
        manifest = prepare_migration(data_dir=args.data_dir, domains_dir=args.domains_dir)
        _write_json(Path(args.manifest), manifest)
        _write_json(
            Path(args.phase1_json),
            {
                "metadata": {
                    "domain": MEMORY_DOMAIN,
                    "display_name": MEMORY_DISPLAY_NAME,
                    "top_n": len(manifest["papers"]),
                    "minimum_llm_domain_fit": manifest["minimum_llm_domain_fit"],
                    "scoring_criteria_path": str(
                        Path(args.domains_dir).resolve() / MEMORY_DOMAIN / "scoring_criteria.md"
                    ),
                },
                "papers": [
                    {
                        "arxiv_id": item["arxiv_id"],
                        "title": item["title"],
                        "abstract": item["abstract"],
                    }
                    for item in manifest["papers"]
                ],
            },
        )
        print(
            f"[agent-memory-migration] prepared {len(manifest['papers'])} candidates; "
            f"{len(manifest['removals'])} stale ownership records"
        )
    elif args.command == "apply":
        stats = apply_migration(
            data_dir=args.data_dir,
            domains_dir=args.domains_dir,
            manifest=_read_json_object(Path(args.manifest)),
            scores=_read_json_object(Path(args.scores)),
            remove_stale=args.remove_stale,
        )
        print("[agent-memory-migration] " + ", ".join(f"{key}={value}" for key, value in stats.items()))
    else:
        stats = validate_published_data(args.data_dir)
        print("[agent-memory-migration] " + ", ".join(f"{key}={value}" for key, value in stats.items()))


if __name__ == "__main__":
    main()
