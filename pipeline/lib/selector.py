"""Gold-backed, deterministic primary-domain selection for paper candidates."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .filter import _build_pattern, _find_matches


class SelectionPolicyError(RuntimeError):
    """Raised when domain selection policies are missing or malformed."""


@dataclass(frozen=True)
class SignalGroup:
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class SelectionPolicy:
    domain: str
    priority: int
    minimum_selection_score: float
    minimum_llm_domain_fit: float
    standalone_signal_scope: str
    required_group_scope: str
    standalone_signals: tuple[str, ...]
    required_groups: tuple[SignalGroup, ...]
    supporting_signals: tuple[str, ...]
    exclusions: tuple[str, ...]


@dataclass(frozen=True)
class PolicyEvaluation:
    domain: str
    qualified: bool
    score: float
    standalone_hits: tuple[str, ...]
    group_hits: tuple[tuple[str, tuple[str, ...]], ...]
    title_group_hits: tuple[tuple[str, tuple[str, ...]], ...]
    supporting_hits: tuple[str, ...]
    exclusion_hits: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "qualified": self.qualified,
            "score": self.score,
            "standalone_hits": list(self.standalone_hits),
            "group_hits": {name: list(hits) for name, hits in self.group_hits},
            "title_group_hits": {
                name: list(hits) for name, hits in self.title_group_hits
            },
            "supporting_hits": list(self.supporting_hits),
            "exclusion_hits": list(self.exclusion_hits),
        }


@dataclass(frozen=True)
class PrimaryDomainDecision:
    primary_domain: str | None
    evaluations: Mapping[str, PolicyEvaluation]


def load_selection_policies(domains_dir: str | Path) -> dict[str, SelectionPolicy]:
    """Load every domain policy found below ``domains_dir``."""
    root = Path(domains_dir)
    if not root.is_dir():
        raise SelectionPolicyError(f"Domain directory does not exist: {root}")

    policies: dict[str, SelectionPolicy] = {}
    for domain_dir in sorted(root.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith(("_", ".")):
            continue
        policy_path = domain_dir / "selection_policy.yaml"
        if not policy_path.exists():
            raise SelectionPolicyError(f"Required selection policy missing: {policy_path}")
        policies[domain_dir.name] = load_selection_policy(policy_path, domain=domain_dir.name)

    if not policies:
        raise SelectionPolicyError(f"No selection policies found in {root}")
    return policies


def load_selection_policy(path: str | Path, *, domain: str) -> SelectionPolicy:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise SelectionPolicyError(f"Selection policy does not exist: {source}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise SelectionPolicyError(f"Cannot read selection policy {source}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SelectionPolicyError(f"Selection policy must be a mapping: {source}")

    priority = payload.get("priority", 0)
    selection_threshold = payload.get("minimum_selection_score", 0.0)
    llm_threshold = payload.get("minimum_llm_domain_fit", 0.65)
    standalone_signal_scope = str(
        payload.get("standalone_signal_scope", "all")
    ).strip().lower()
    required_group_scope = str(payload.get("required_group_scope", "all")).strip().lower()
    try:
        priority = int(priority)
        selection_threshold = float(selection_threshold)
        llm_threshold = float(llm_threshold)
    except (TypeError, ValueError) as exc:
        raise SelectionPolicyError(f"Invalid priority or threshold in {source}") from exc
    if not math.isfinite(selection_threshold) or selection_threshold < 0.0:
        raise SelectionPolicyError(f"minimum_selection_score must be non-negative: {source}")
    if not math.isfinite(llm_threshold) or not 0.0 <= llm_threshold <= 1.0:
        raise SelectionPolicyError(f"minimum_llm_domain_fit must be between 0 and 1: {source}")
    if standalone_signal_scope not in {"all", "title"}:
        raise SelectionPolicyError(
            f"standalone_signal_scope must be 'all' or 'title': {source}"
        )
    if required_group_scope not in {"all", "title"}:
        raise SelectionPolicyError(f"required_group_scope must be 'all' or 'title': {source}")

    groups_payload = payload.get("required_groups")
    if not isinstance(groups_payload, dict) or not groups_payload:
        raise SelectionPolicyError(f"required_groups must be a non-empty mapping: {source}")
    groups_list: list[SignalGroup] = []
    for name, keywords in groups_payload.items():
        normalized_name = str(name).strip()
        if not normalized_name:
            raise SelectionPolicyError(f"required_groups contains an empty name: {source}")
        normalized_keywords = _string_list(keywords, source, normalized_name)
        if not normalized_keywords:
            raise SelectionPolicyError(
                f"required group {normalized_name} must not be empty: {source}"
            )
        groups_list.append(SignalGroup(name=normalized_name, keywords=normalized_keywords))
    groups = tuple(groups_list)

    standalone = _string_list(payload.get("standalone_signals", []), source, "standalone_signals")
    supporting = _string_list(payload.get("supporting_signals", []), source, "supporting_signals")
    exclusions = _string_list(payload.get("exclusions", []), source, "exclusions")
    if not standalone:
        raise SelectionPolicyError(f"standalone_signals must not be empty: {source}")

    return SelectionPolicy(
        domain=domain,
        priority=priority,
        minimum_selection_score=selection_threshold,
        minimum_llm_domain_fit=llm_threshold,
        standalone_signal_scope=standalone_signal_scope,
        required_group_scope=required_group_scope,
        standalone_signals=standalone,
        required_groups=groups,
        supporting_signals=supporting,
        exclusions=exclusions,
    )


def evaluate_policy(paper: Mapping[str, Any], policy: SelectionPolicy) -> PolicyEvaluation:
    """Evaluate one paper against one explainable domain policy."""
    text = _paper_text(paper)
    title = str(paper.get("title", ""))
    standalone_text = title if policy.standalone_signal_scope == "title" else text
    group_text = title if policy.required_group_scope == "title" else text
    exclusion_hits = _matches(text, policy.exclusions)
    standalone_hits = _matches(standalone_text, policy.standalone_signals)
    group_hits = tuple(
        (group.name, _matches(group_text, group.keywords))
        for group in policy.required_groups
    )
    title_group_hits = tuple(
        (group.name, _matches(title, group.keywords))
        for group in policy.required_groups
    )
    supporting_hits = _matches(text, policy.supporting_signals)

    has_all_groups = all(hits for _, hits in group_hits)
    has_required_evidence = bool(standalone_hits) or has_all_groups
    score = 0.0
    if not exclusion_hits and standalone_hits:
        score = 10.0 + min(max(len(standalone_hits) - 1, 0), 5) * 0.5
    elif not exclusion_hits and has_all_groups:
        score = 6.0 + sum(min(len(hits), 3) * 0.4 for _, hits in group_hits)
        score += sum(bool(hits) for _, hits in title_group_hits) * 0.5
    if not exclusion_hits and has_required_evidence:
        score += min(len(supporting_hits), 6) * 0.2
    qualified = (
        not exclusion_hits
        and has_required_evidence
        and score >= policy.minimum_selection_score
    )

    return PolicyEvaluation(
        domain=policy.domain,
        qualified=qualified,
        score=round(score, 4),
        standalone_hits=standalone_hits,
        group_hits=group_hits,
        title_group_hits=title_group_hits,
        supporting_hits=supporting_hits,
        exclusion_hits=exclusion_hits,
    )


def choose_primary_domain(
    paper: Mapping[str, Any],
    policies: Mapping[str, SelectionPolicy],
) -> PrimaryDomainDecision:
    """Choose exactly one primary domain, or ``None`` when no policy qualifies."""
    evaluations = {
        domain: evaluate_policy(paper, policy)
        for domain, policy in policies.items()
    }
    qualified = [evaluation for evaluation in evaluations.values() if evaluation.qualified]
    if not qualified:
        return PrimaryDomainDecision(primary_domain=None, evaluations=evaluations)

    winner = min(
        qualified,
        key=lambda item: (
            -item.score,
            -policies[item.domain].priority,
            item.domain,
        ),
    )
    return PrimaryDomainDecision(primary_domain=winner.domain, evaluations=evaluations)


def select_papers_for_domain(
    papers: Sequence[dict],
    *,
    domain: str,
    policies: Mapping[str, SelectionPolicy],
    verbose: bool = True,
) -> list[dict]:
    """Keep only papers whose deterministic primary domain is ``domain``."""
    if domain not in policies:
        raise SelectionPolicyError(f"No selection policy loaded for domain {domain}")

    kept: list[dict] = []
    decisions: Counter[str] = Counter()
    for paper in papers:
        decision = choose_primary_domain(paper, policies)
        decisions[decision.primary_domain or "none"] += 1
        if decision.primary_domain != domain:
            continue

        winner = decision.evaluations[domain]
        paper["selection"] = {
            **winner.to_dict(),
            "primary_domain": domain,
            "policy": {
                "minimum_selection_score": policies[domain].minimum_selection_score,
                "minimum_llm_domain_fit": policies[domain].minimum_llm_domain_fit,
                "standalone_signal_scope": policies[domain].standalone_signal_scope,
                "required_group_scope": policies[domain].required_group_scope,
            },
            "domain_scores": {
                candidate: evaluation.score
                for candidate, evaluation in decision.evaluations.items()
                if evaluation.qualified
            },
        }
        kept.append(paper)

    if verbose:
        routed = ", ".join(f"{name}={count}" for name, count in sorted(decisions.items()))
        print(f"  [selector] kept={len(kept)} / total={len(papers)}; primary: {routed}")
    return kept


def _paper_text(paper: Mapping[str, Any]) -> str:
    abstract = paper.get("abstract") or paper.get("abstract_en") or ""
    return f"{paper.get('title', '')}\n{abstract}"


@lru_cache(maxsize=512)
def _cached_pattern(keywords: tuple[str, ...]):
    return _build_pattern(list(keywords))


def _matches(text: str, keywords: tuple[str, ...]) -> tuple[str, ...]:
    if not keywords:
        return ()
    return tuple(_find_matches(text, _cached_pattern(keywords)))


def _string_list(value: Any, source: Path, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SelectionPolicyError(f"{field} must be a list in {source}")
    if any(not isinstance(item, str) for item in value):
        raise SelectionPolicyError(f"{field} must contain only strings in {source}")
    normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
    return normalized
