# Agent Memory Domain Design

## Goal

Add `agent-memory` as a first-class PaperHunt domain for papers whose primary contribution is memory for agents. The domain must cover memory construction, use, evolution, and evaluation without drifting into generic retrieval, long-context modeling, model memorization, or security research. Existing published papers must continue to have exactly one primary domain, and historical Agent Memory papers currently under Agent Harness Evolution must be migrated and re-evaluated with the new rubric.

## Scope

### Included

The new domain includes reusable methods, systems, datasets, and evaluations for:

- writing, extracting, organizing, compressing, merging, consolidating, and structuring Agent memory;
- retrieving, routing, arbitrating, and reinstating memory during Agent action or reasoning;
- maintaining memory across sessions, tasks, and long-running Agent execution;
- feedback-, trace-, or experience-driven memory update, correction, forgetting, rewriting, and adaptation;
- evaluating Agent memory recall, consistency, behavioral impact, update effectiveness, and long-term personalization;
- Agent-native memory systems, services, shared memory, event-sourced memory, and verifiable memory management;
- personalized and conversational Agents whose core contribution is long-term user memory;
- Coding, Search, multimodal, and other Agents when memory is the primary contribution.

### Excluded

The domain excludes:

- generic LLM memory, parametric memory, memorization, and knowledge editing without an Agent behavior loop;
- long-context modeling, KV caches, state-space sequence memory, and context-window efficiency by themselves;
- ordinary RAG, GraphRAG, knowledge bases, and retrieval augmentation without an Agent-memory lifecycle;
- papers that merely use memory as a supporting component while primarily contributing Agent training, coding, search, realtime multimodality, or harness infrastructure;
- attacks, poisoning, privacy leakage, cryptographic protection, prompt injection, and other security-first work;
- medical, financial, or other vertical applications without a reusable Agent-memory method;
- surveys without a concrete reusable taxonomy, evaluation protocol, dataset, or system contribution.

Research on false-memory promotion, conflict resolution, consolidation correctness, provenance, or verifier-backed memory remains in scope when its primary goal is memory quality rather than attack or security defense. Governance primitives such as scoped retrieval, tenant isolation, provenance, contradiction handling, and propagation policy also remain in scope when they are supporting parts of a reusable Agent-memory service rather than the paper's primary security contribution.

## Domain Configuration

Create `pipeline/domains/agent-memory/` with the same five-file contract as existing domains:

- `domain.yaml`
- `selection_policy.yaml`
- `filter_keywords.yaml`
- `topic_keywords.yaml`
- `scoring_criteria.md`

The arXiv source categories are `cs.AI`, `cs.CL`, `cs.LG`, `cs.IR`, and `cs.SE`. `cs.CR` is intentionally omitted to reduce security-first noise. The domain-fit publication threshold is `0.70`, stricter than the other domains' current `0.65` threshold.

The deterministic selector uses title-scoped high-precision standalone phrases and title-scoped required signal groups. Generic words such as `memory`, `retrieval`, `context`, `personalization`, and `long-term` are never sufficient alone. Group qualification requires both:

1. explicit Agent context; and
2. a concrete memory lifecycle, system, or evaluation contribution.

The policy receives a priority above the existing domains and a small configurable primary-ownership score bonus. The bonus applies only after the strict Memory policy independently qualifies; it lets three-part contextual Memory evidence outrank broad standalone phrases such as `coding agents` or `search agents`. Priority remains the final deterministic tie breaker.

## Unique Primary-Domain Ownership

Agent Harness Evolution currently treats memory systems and services as an allowed trunk. Remove Memory-only standalone phrases and Memory lifecycle terms that independently satisfy its reusable-capability group. Harness may retain context assembly, runtime state, workflow state, and orchestration signals, but a paper must not enter Harness solely because it mentions Agent memory.

For a paper that qualifies for multiple domains:

- if the primary contribution constructs, updates, manages, or evaluates memory, `agent-memory` wins;
- if memory is only an implementation detail, the paper remains in Coding/Search Agent, realtime multimodal, e-commerce, or Harness as appropriate;
- security and medical exclusions override all positive Memory signals.

No domain-specific branch is added to `choose_primary_domain`; ownership continues to be data-driven through strict policies, scores, and priority.

## Gold Set and Tests

Build the initial Agent Memory gold set from checked-in historical detail data. It contains 15–20 required inclusions and 15–20 required exclusions; implementation must select exact examples before the policy is accepted.

Required inclusions span:

- Agent-native memory systems and services;
- memory construction and consolidation;
- memory evolution and correction;
- long-term personalized or conversational memory;
- memory benchmarks and evaluation methodology;
- Coding/Search/multimodal Agent work whose core contribution is memory.

Required exclusions span:

- generic LLM memorization and long-context methods;
- pure RAG and GraphRAG;
- security, poisoning, privacy, and cryptographic Memory work;
- medical or narrow vertical applications;
- papers where memory is secondary to training, search, coding, or realtime multimodality.

Memory papers previously labeled as required Harness inclusions are transferred to the new domain when Memory is their primary contribution. Existing gold labels for the other domains must still pass after the policy split.

Focused selector tests cover the agreed boundaries and prove that a Memory-centric Coding, Search, or multimodal paper routes to `agent-memory`, while a paper merely using memory stays in its original domain. The quality evaluator must report zero cross-domain duplicate IDs.

## Historical Migration

### Source corpus

The migration reads currently published list entries from every domain in `web/public/data`. Each list entry is joined with its retained detail JSON. Unpublished retained candidate details are not migrated.

### Candidate selection

For each published paper, construct the selector input from its title and `abstract_en`, then run all current policies. A paper is a migration candidate only when the new deterministic primary domain is `agent-memory`.

Security-first, generic non-Agent memory, and other rejected papers are not placed in the new domain. This migration changes only papers whose new primary owner is `agent-memory`; unrelated historical cleanup remains outside its scope so the operation cannot silently rewrite hundreds of older editorial decisions.

### Re-evaluation

Historical candidates must be scored again with `agent-memory/scoring_criteria.md`. Old Harness `domain_fit`, comments, and generic-dimension scores are not reused. The migration uses the repository's configured `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL_SCORING` secrets through the existing scoring client.

Candidates below the new `0.70` domain-fit threshold do not migrate into Agent Memory and remain in their old historical list. New daily runs apply the new deterministic and LLM gates normally.

Existing titles, Chinese summaries, key points, author/enrichment metadata, links, and figure URLs are reused. The migration does not request arXiv, Hugging Face, Semantic Scholar, PDFs, translation, or Blob uploads.

### Two-phase and atomic behavior

Add a migration command with two explicit phases:

1. `prepare` writes a deterministic manifest and a scoring input file without changing published data;
2. `apply` validates a complete LLM score file, stages the full rewritten data tree in a temporary directory, checks invariants, and then replaces affected files.

`apply` fails before touching published data when any candidate assessment is missing or malformed. It also fails if a source detail is missing, an arXiv ID appears in more than one resulting domain, a list points to a missing detail, a detail path disagrees with its domain/date, or the rebuilt index disagrees with the lists.

The migration creates Agent Memory lists only for dates containing accepted papers. It removes accepted migrated papers and their old details from source domains, resolves existing cross-domain duplicate copies through the current deterministic primary-owner policy, recalculates affected list counts, and rebuilds `web/public/data/index.json` from the resulting lists. Other unrelated historical papers are left untouched. An explicit diagnostic-only option may report or clean broader stale ownership, but the production workflow does not enable it.

### GitHub Actions execution

Add a manually dispatchable migration workflow. It:

1. checks out `main`;
2. installs pipeline dependencies;
3. runs tests and selection-quality evaluation;
4. prepares the migration manifest;
5. scores all candidates with repository LLM secrets;
6. applies and validates the migration;
7. runs the full test suite, quality evaluation, migration invariant checks, and frontend build;
8. commits generated historical data and pushes to `main` with the same pull/rebase retry discipline as the daily workflow.

The workflow is safe to rerun. With unchanged policies and already migrated data, it skips LLM scoring when the candidate set is empty and produces no duplicate entries or unintended changes.

## Daily Pipeline Behavior

Because domain discovery is automatic, `agent-memory` joins scheduled daily runs after its configuration is committed. The union of arXiv categories is still fetched through the shared daily cache, so the new domain does not add a separate fetch sequence. Selection remains primary-domain-first, then enrichment, Agent Memory LLM scoring, translation, figures, and JSON output.

## Verification and Acceptance Criteria

The change is complete when:

- all domain configs validate;
- all existing and new unit tests pass;
- every required Agent Memory inclusion routes to `agent-memory`;
- every required exclusion does not route to `agent-memory`;
- existing approved labels for e-commerce, Harness, and realtime multimodal remain correct after intentional Memory transfers;
- the quality evaluator retains at least 0.90 precision and recall for every gold-backed domain and at least 0.95 overall;
- resulting historical output contains no cross-domain duplicate arXiv IDs;
- every list/detail/index reference is valid;
- migrated papers contain new Agent Memory LLM assessments and preserve reusable Chinese content and figures;
- the frontend production build succeeds;
- the migration workflow commits the generated historical data to `main`.
