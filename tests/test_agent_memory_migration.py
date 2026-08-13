from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.migrate_agent_memory_history import (
    MEMORY_DOMAIN,
    MigrationError,
    apply_migration,
    prepare_migration,
    validate_published_data,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAINS_DIR = ROOT / "pipeline" / "domains"
DATE = "2026-08-05"
MEMORY_ID = "2608.05095"
HARNESS_ID = "2608.05102"


class AgentMemoryMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name) / "data"
        self._write_source_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_finds_only_new_memory_owner(self) -> None:
        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )

        self.assertEqual([paper["arxiv_id"] for paper in manifest["papers"]], [MEMORY_ID])
        self.assertEqual(manifest["papers"][0]["source_domain"], "agent-harness-evolution")

    def test_missing_score_fails_before_published_data_changes(self) -> None:
        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        before = self._tree_hash()

        with self.assertRaisesRegex(MigrationError, "missing LLM assessments"):
            apply_migration(
                data_dir=self.data_dir,
                domains_dir=DOMAINS_DIR,
                manifest=manifest,
                scores={},
            )

        self.assertEqual(self._tree_hash(), before)

    def test_changed_duplicate_set_fails_before_published_data_changes(self) -> None:
        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        duplicate_card, duplicate_detail = self._paper(
            HARNESS_ID,
            "ABSeeker: Training Long-Horizon Search Agents via Credit Assignment",
            "We train search agents from environment trajectories.",
            domain="agent-e-commerce",
        )
        self._write_list("agent-e-commerce", [duplicate_card])
        self._write_json(
            self.data_dir / "agent-e-commerce" / DATE / f"{HARNESS_ID}.json",
            duplicate_detail,
        )
        self._rebuild_fixture_index()
        before = self._tree_hash()

        with self.assertRaisesRegex(MigrationError, "duplicate set changed"):
            apply_migration(
                data_dir=self.data_dir,
                domains_dir=DOMAINS_DIR,
                manifest=manifest,
                scores={MEMORY_ID: self._assessment(domain_fit=0.93)},
            )

        self.assertEqual(self._tree_hash(), before)

    def test_rejected_candidate_remains_in_original_collection(self) -> None:
        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        source_list = self.data_dir / "agent-harness-evolution" / f"{DATE}.json"
        source_detail = (
            self.data_dir
            / "agent-harness-evolution"
            / DATE
            / f"{MEMORY_ID}.json"
        )
        list_before = source_list.read_bytes()
        detail_before = source_detail.read_bytes()

        stats = apply_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
            manifest=manifest,
            scores={MEMORY_ID: self._assessment(domain_fit=0.69)},
        )

        self.assertEqual(stats["migrated"], 0)
        self.assertEqual(source_list.read_bytes(), list_before)
        self.assertEqual(source_detail.read_bytes(), detail_before)
        self.assertFalse((self.data_dir / MEMORY_DOMAIN).exists())
        validate_published_data(self.data_dir)

    def test_approved_candidate_moves_once_and_preserves_content(self) -> None:
        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )

        stats = apply_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
            manifest=manifest,
            scores={MEMORY_ID: self._assessment(domain_fit=0.93)},
        )

        self.assertEqual(stats["migrated"], 1)
        source = self._read_json(
            self.data_dir / "agent-harness-evolution" / f"{DATE}.json"
        )
        self.assertEqual(
            [paper["arxiv_id"] for paper in source["papers"]],
            [HARNESS_ID],
        )
        self.assertFalse(
            (
                self.data_dir
                / "agent-harness-evolution"
                / DATE
                / f"{MEMORY_ID}.json"
            ).exists()
        )

        memory_list = self._read_json(self.data_dir / MEMORY_DOMAIN / f"{DATE}.json")
        self.assertEqual(
            [paper["arxiv_id"] for paper in memory_list["papers"]],
            [MEMORY_ID],
        )
        self.assertEqual(
            memory_list["papers"][0]["detail_file"],
            f"{MEMORY_DOMAIN}/{DATE}/{MEMORY_ID}.json",
        )
        detail = self._read_json(
            self.data_dir / MEMORY_DOMAIN / DATE / f"{MEMORY_ID}.json"
        )
        self.assertEqual(detail["abstract_zh"], "保留这段中文摘要。")
        self.assertEqual(detail["figures"][0]["src"], "https://example.test/figure.webp")
        self.assertEqual(detail["llm_assessment"]["domain_fit"], 0.93)

        index = self._read_json(self.data_dir / "index.json")
        self.assertIn(MEMORY_DOMAIN, {item["id"] for item in index["domains"]})
        self.assertEqual(validate_published_data(self.data_dir)["papers"], 2)

        second_manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        self.assertEqual(second_manifest["papers"], [])
        before_rerun = self._tree_hash()
        rerun = apply_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
            manifest=second_manifest,
            scores={},
        )
        self.assertEqual(rerun["migrated"], 0)
        self.assertEqual(self._tree_hash(), before_rerun)

    def test_duplicate_source_owners_collapse_to_one_memory_record(self) -> None:
        ecommerce_card, ecommerce_detail = self._paper(
            MEMORY_ID,
            "Hierarchical Graph Memory for LLM Agents with Path-level Localization and Rewrite",
            "We build an evolving agent memory system.",
            domain="agent-e-commerce",
        )
        self._write_list("agent-e-commerce", [ecommerce_card])
        self._write_json(
            self.data_dir / "agent-e-commerce" / DATE / f"{MEMORY_ID}.json",
            ecommerce_detail,
        )
        self._rebuild_fixture_index()

        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        self.assertEqual(len(manifest["papers"]), 1)

        apply_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
            manifest=manifest,
            scores={MEMORY_ID: self._assessment(domain_fit=0.91)},
        )

        owners = []
        for list_path in self.data_dir.glob("*/????-??-??.json"):
            for paper in self._read_json(list_path)["papers"]:
                if paper["arxiv_id"] == MEMORY_ID:
                    owners.append(list_path.parent.name)
        self.assertEqual(owners, [MEMORY_DOMAIN])
        validate_published_data(self.data_dir)

    def test_unrelated_duplicate_uses_current_primary_owner(self) -> None:
        harness_card, harness_detail = self._paper(
            "2606.12984",
            "SkillChain: Closing the Loop on Skill Evolution for Image-Based E-Commerce AI Assistants",
            "We evolve reusable agent skills from tool-use trajectories.",
            domain="agent-harness-evolution",
        )
        commerce_card, commerce_detail = self._paper(
            "2606.12984",
            "SkillChain: Closing the Loop on Skill Evolution for Image-Based E-Commerce AI Assistants",
            "We evolve reusable agent skills from tool-use trajectories.",
            domain="agent-e-commerce",
        )
        harness_payload = self._read_json(
            self.data_dir / "agent-harness-evolution" / f"{DATE}.json"
        )
        harness_payload["papers"].append(harness_card)
        self._write_json(
            self.data_dir / "agent-harness-evolution" / f"{DATE}.json",
            harness_payload,
        )
        self._write_json(
            self.data_dir / "agent-harness-evolution" / DATE / "2606.12984.json",
            harness_detail,
        )
        self._write_list("agent-e-commerce", [commerce_card])
        self._write_json(
            self.data_dir / "agent-e-commerce" / DATE / "2606.12984.json",
            commerce_detail,
        )
        self._rebuild_fixture_index()

        manifest = prepare_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
        )
        apply_migration(
            data_dir=self.data_dir,
            domains_dir=DOMAINS_DIR,
            manifest=manifest,
            scores={MEMORY_ID: self._assessment(domain_fit=0.93)},
        )

        owners = []
        for list_path in self.data_dir.glob("*/????-??-??.json"):
            for paper in self._read_json(list_path)["papers"]:
                if paper["arxiv_id"] == "2606.12984":
                    owners.append(list_path.parent.name)
        self.assertEqual(owners, ["agent-harness-evolution"])
        validate_published_data(self.data_dir)

    def test_validation_rejects_duplicate_memory_ownership(self) -> None:
        card, detail = self._paper(
            MEMORY_ID,
            "Agent Memory System",
            "An agent memory system.",
            domain=MEMORY_DOMAIN,
        )
        self._write_list(MEMORY_DOMAIN, [card])
        self._write_json(
            self.data_dir / MEMORY_DOMAIN / DATE / f"{MEMORY_ID}.json",
            detail,
        )
        self._rebuild_fixture_index()

        with self.assertRaisesRegex(MigrationError, "cross-domain duplicate"):
            validate_published_data(self.data_dir)

    def _write_source_fixture(self) -> None:
        memory_card, memory_detail = self._paper(
            MEMORY_ID,
            "Hierarchical Graph Memory for LLM Agents with Path-level Localization and Rewrite",
            "We propose an evolving hierarchical graph memory framework for long-term agents.",
            domain="agent-harness-evolution",
        )
        harness_card, harness_detail = self._paper(
            HARNESS_ID,
            "ABSeeker: Training Long-Horizon Search Agents via Credit Assignment",
            "We train search agents from environment trajectories with reinforcement learning.",
            domain="agent-harness-evolution",
        )
        self._write_list("agent-harness-evolution", [memory_card, harness_card])
        self._write_json(
            self.data_dir
            / "agent-harness-evolution"
            / DATE
            / f"{MEMORY_ID}.json",
            memory_detail,
        )
        self._write_json(
            self.data_dir
            / "agent-harness-evolution"
            / DATE
            / f"{HARNESS_ID}.json",
            harness_detail,
        )
        self._rebuild_fixture_index()

    def _paper(
        self,
        arxiv_id: str,
        title: str,
        abstract: str,
        *,
        domain: str,
    ) -> tuple[dict, dict]:
        detail_file = f"{domain}/{DATE}/{arxiv_id}.json"
        card = {
            "arxiv_id": arxiv_id,
            "title": title,
            "title_zh": "保留标题",
            "authors": ["Ada Lovelace"],
            "total_score": 0.5,
            "scores": {
                "topic_relevance": 0.5,
                "llm_assessment": 0.5,
                "domain_fit": 0.8,
                "other": 0.5,
            },
            "tags": ["existing tag"],
            "tldr_zh": "保留摘要",
            "detail_file": detail_file,
            "thumb": "https://example.test/thumb.webp",
        }
        detail = {
            "arxiv_id": arxiv_id,
            "title": title,
            "title_zh": "保留标题",
            "authors": ["Ada Lovelace"],
            "published_at": "2026-08-05T00:00:00Z",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "links": {"github": None, "project_page": None},
            "abstract_en": abstract,
            "abstract_zh": "保留这段中文摘要。",
            "key_points_zh": ["保留关键点。"],
            "llm_assessment": self._assessment(domain_fit=0.8),
            "scores": {
                "topic_relevance": 0.5,
                "llm_assessment": 0.5,
                "open_source": 0.0,
                "community_heat": 0.0,
                "author_reputation": 0.3,
                "venue_signal": 0.0,
                "generality": 0.8,
                "domain_multiplier": 1.0,
            },
            "enriched": {},
            "figures": [
                {
                    "src": "https://example.test/figure.webp",
                    "page": 1,
                    "kind": "figure",
                    "confidence": 0.9,
                }
            ],
        }
        return card, detail

    @staticmethod
    def _assessment(*, domain_fit: float) -> dict:
        return {
            "domain_fit": domain_fit,
            "novelty": 0.8,
            "problem_significance": 0.8,
            "potential_impact": 0.8,
            "paradigm_shift": 0.7,
            "lasting_value": 0.8,
            "comment": "Agent-memory contribution.",
            "comment_zh": "Agent Memory 贡献。",
        }

    def _write_list(self, domain: str, papers: list[dict]) -> None:
        display = {
            "agent-harness-evolution": "Agent Harness Evolution",
            "agent-e-commerce": "E-commerce Agent",
            MEMORY_DOMAIN: "Agent Memory",
        }[domain]
        self._write_json(
            self.data_dir / domain / f"{DATE}.json",
            {
                "domain": domain,
                "display_name": display,
                "date": DATE,
                "generated_at": "2026-08-06T00:00:00Z",
                "papers": papers,
            },
        )

    def _rebuild_fixture_index(self) -> None:
        names: dict[str, str] = {}
        entries = []
        for list_path in sorted(self.data_dir.glob("*/????-??-??.json")):
            payload = self._read_json(list_path)
            names[payload["domain"]] = payload["display_name"]
            entries.append(
                {
                    "domain": payload["domain"],
                    "date": payload["date"],
                    "paper_count": len(payload["papers"]),
                    "file": f"{payload['domain']}/{payload['date']}.json",
                }
            )
        self._write_json(
            self.data_dir / "index.json",
            {
                "generated_at": "2026-08-06T00:00:00Z",
                "domains": [
                    {"id": domain, "display_name": names[domain]}
                    for domain in sorted(names)
                ],
                "entries": entries,
            },
        )

    def _tree_hash(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.data_dir.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(self.data_dir).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
