# Paper Selection Quality Design

## Context

PaperHunt currently treats each research domain as a broad arXiv category union followed by an OR-based keyword filter. A single phrase can admit a paper and produce a high topic score without the surrounding domain context. Every filtered paper is then LLM-scored and published because all three domains use `default_top_pct: 1.0` and there is no final relevance threshold.

The historical output demonstrates the failure mode: urban mobility, sEMG recognition, and quantum-learning papers entered Agent Harness Evolution; retail banking and marketplace operations entered E-commerce Agent; and offline TTS/ASR datasets entered Realtime Multimodal Agent. The LLM often identified these papers as irrelevant, but its score only affected ordering and never rejected them.

The user approved a V1 gold set containing ten required inclusions and ten required exclusions for each of the three domains. After reviewing the first August 5 output, the user added nine labels, bringing the regression set to 69 papers. The user also fixed these scope rules:

- every paper has exactly one primary domain;
- E-commerce Agent covers product search, recommendation, product understanding, and shopping agents, not general commerce operations;
- Realtime Multimodal Agent requires realtime or streaming interaction;
- Agent Harness Evolution includes reusable runtime, harness, orchestration engines, memory systems/services, Agent training and RL, Skill evolution, coding Agents, and search Agents.
- Security research is globally out of scope for all three domains, including attacks, red teaming, prompt injection, phishing, malware, privacy, and cyber defense. This exclusion overrides otherwise positive Agent/RL/coding/search signals.
- Medical, clinical, surgical, and intraoperative work is globally out of scope even when it claims realtime or low-latency video understanding.
- Skill valuation alone is not Skill evolution.

### August 5 scope labels

The following newly reviewed papers define the revised boundary:

- must include in Agent Harness Evolution: `2608.05102` ABSeeker (search-Agent training), `2608.04934` State2State (Agent training), and `2608.04682` Active-SWE (coding-Agent benchmark);
- must exclude from Agent Harness Evolution: `2608.04562` What Is a Skill Worth? (valuation rather than evolution), `2608.04317` Trident (cyber defense), `2608.04741` LoginTrap (prompt-injection security), and `2608.05108` Agent Against Agent (prompt-injection red teaming);
- must exclude from Realtime Multimodal Agent: `2608.04676` SurgNarrator (surgical/clinical video understanding).

## Goals

- Make primary-domain selection deterministic, explainable, and exclusive.
- Replace single-keyword admission with contextual signal combinations.
- Use the LLM as a strict semantic relevance gate, not only a ranking signal.
- Preserve a versioned, executable 69-paper gold set.
- Report historical before/after quality with reproducible metrics.
- Keep arXiv fetching, enrichment, translation, and figure generation unchanged.

## Non-goals

- Backfill the July/August data gap in this change.
- Add non-arXiv paper sources.
- Train an embedding model or external classifier.
- Guarantee recall for papers absent from the historical candidate corpus.

## Alternatives

### Tune the existing keyword lists only

This is the smallest change, but it retains the OR-based semantics that caused the current false positives. Negative lists would continue growing without a stable decision model.

### LLM-only classification

An LLM can reason about context, but using it as the only selector makes regression tests nondeterministic and requires paid network calls before every relevance decision.

### Hybrid deterministic and LLM gates

This design uses deterministic policies for candidate admission and unique ownership, followed by a strict LLM `domain_fit` gate. It gives reproducible offline behavior while retaining semantic judgment for difficult future papers. This is the selected approach.

## Architecture

### Versioned gold labels

`tests/fixtures/paper_selection_gold.json` stores the approved arXiv IDs as required inclusions and exclusions per domain. Tests resolve title and abstract text from the checked-in historical detail JSON. This avoids copying large abstracts while keeping the labels reviewable.

### Domain selection policies

Each domain receives a `selection_policy.yaml` with:

- `priority`: tie-breaker that favors specialized domains over the horizontal Harness domain;
- `minimum_selection_score`: minimum deterministic evidence required after grouped matching;
- `standalone_signal_scope`: whether standalone phrases may match the full record or must occur in the title;
- `required_group_scope`: whether grouped evidence may come from the full record or must be explicit in the title;
- `standalone_signals`: phrases strong enough to establish scope directly;
- `required_groups`: contextual groups that must all match when no standalone signal exists;
- `supporting_signals`: additional evidence used for ownership scoring;
- `exclusions`: unambiguous out-of-scope verticals or task families;
- `minimum_llm_domain_fit`: final semantic threshold.

The generic selector compiles the same boundary-aware regex format already used by the project. A policy qualifies when it has a standalone signal or at least one hit in every required group, has no exclusion, and reaches the policy's minimum evidence score. Its score rewards standalone, group, and supporting hits, with an extra bonus for grouped evidence stated in the title so a secondary application example in the abstract cannot easily claim primary ownership. The highest qualifying score becomes the primary domain; ties use policy priority and then domain ID for deterministic output.

Specialized policies receive higher tie priority than Agent Harness Evolution. A clearly Harness-specific standalone phrase such as `agent harness` still outweighs a weaker commerce or multimodal group match.

### Phase-one integration

Phase one loads all selection policies and applies primary-domain selection directly to the arXiv category candidates. The old OR keyword filter is no longer the membership authority. Accepted papers retain structured selection evidence for diagnostics, including matched signals and per-domain scores.

Existing tiered topic scoring remains a ranking feature after membership is established. Its accidental matches can no longer admit a paper.

Hard exclusions are evaluated before positive signals in every policy. Harness positives are separated into explicit trunks: infrastructure, Agent training/RL, Skill evolution, coding Agents, and search Agents. Harness standalone signals must occur in the title, preventing incidental mentions in an abstract from claiming the domain. Multimodal standalone and grouped evidence must likewise be explicit in the title, so generic video understanding or streaming-ASR studies cannot enter through incidental abstract wording. Broad terms such as `skill`, `framework`, `security`, or `benchmark` are not independently sufficient. Security, medical, and surgical candidates are rejected regardless of otherwise positive Agent or realtime language.

### Unified LLM relevance contract

All domain rubrics use one output contract:

- `domain_fit`;
- `novelty`;
- `problem_significance`;
- `potential_impact`;
- `paradigm_shift`;
- `lasting_value`;
- `comment` and `comment_zh`.

`domain_fit` measures whether the paper belongs in the current domain. The five existing dimensions measure value only after that relevance question. Missing or invalid required scores invalidate the assessment instead of silently defaulting to `0.5`.

The Harness rubric mirrors the deterministic trunks and gives all security work low domain fit. The multimodal rubric treats realtime medical perception as out of scope and does not equate low latency with interactive agency.

Final emission requires both a valid assessment and `domain_fit >= minimum_llm_domain_fit`. `llm_avg` continues to rank accepted papers but cannot override a failed domain-fit gate.

## Data Flow

1. Fetch each unique arXiv category into the strict daily cache.
2. Load a domain's configured category papers.
3. Evaluate every paper against all three selection policies.
4. Keep it only when the current domain is the unique primary domain.
5. Enrich and compute deterministic ranking features.
6. Ask the LLM for the unified assessment contract.
7. Reject invalid assessments and papers below the domain-fit threshold.
8. Rank and emit the surviving papers.

## Error Handling

- Missing or malformed selection policies fail phase one with a clear error.
- A selector tie is resolved deterministically; it is not an execution error.
- Missing LLM fields do not receive neutral defaults. The affected paper is excluded and the malformed response is logged.
- A domain with zero qualifying papers remains a valid zero-paper result after successful arXiv fetching.

## Quality Evaluation

`pipeline/evaluate_selection_quality.py` reports two comparisons.

### Gold-set metrics

The baseline re-evaluates each example with the legacy domain keyword filter. The new selector reports confusion matrices, precision, recall, F1, and accuracy by domain and overall.

Acceptance criteria:

- overall gold precision and recall are at least 0.95;
- no domain has precision or recall below 0.90;
- no paper is assigned to more than one primary domain.

### Historical proxy metrics

For every existing historical output, the evaluator applies the new deterministic selector and compares:

- retained paper count;
- mean existing LLM score;
- number and percentage with existing `llm_avg < 0.4`;
- retention of existing papers with `llm_avg >= 0.7`, to expose over-aggressive filtering;
- duplicate cross-domain assignments.

Existing LLM scores are only a historical proxy because they predate `domain_fit`. The gold-set metrics remain the release gate.

## Tests

- Selector unit tests cover grouped matching, exclusions, scoring, and deterministic ties.
- The 69-paper gold regression test exercises real historical titles and abstracts, including the reviewed August 5 boundary cases.
- Scorer tests require the unified schema and reject missing or invalid `domain_fit`.
- Pipeline tests verify final domain-fit gating.
- The full offline test suite runs in GitHub Actions before the daily pipeline.

## Rollout

Run the evaluator before and after implementation, record the metrics in the commit handoff, and run the complete unit test suite. If the acceptance criteria pass and the historical proxy improves, commit and push the current feature branch as authorized.
