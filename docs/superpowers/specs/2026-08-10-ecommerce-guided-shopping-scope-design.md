# E-commerce Guided-Shopping Scope Design

## Context

The current E-commerce Agent domain has four independent trunks: product search, recommendation, product/catalog understanding, and shopping Agents. The user has narrowed the intended collection to two customer-facing capabilities:

1. product search;
2. guided-shopping recommendation.

Agent systems, recommendation models, LLM/VLM methods, reinforcement learning, GRPO/DPO, bandits, and online learning are all in scope when their primary contribution advances one of those two capabilities. They are implementation methods, not independent admission reasons.

## Considered approaches

### A. Strict two-trunk deterministic gate plus semantic LLM gate — selected

Require explicit commerce/product context together with search or guided-recommendation capability, while retaining a small set of high-precision combined phrases. Use the LLM as a second semantic check for primary-contribution fit. This is explainable, testable, and keeps both precision and method diversity.

### B. LLM-prompt-only narrowing — rejected

Keep the broad deterministic candidate gate and rely on `domain_fit` to remove noise. This preserves recall but repeats the failure mode in which generic recommendation, commerce transactions, or security papers reach the expensive semantic stage and sometimes receive inflated scores.

### C. Title whitelist — rejected

Admit only papers whose titles contain approved phrases. Precision would be high, but papers such as A/B Agent describe the e-commerce recommendation contribution only in the abstract and would be missed.

## Membership contract

A paper belongs to E-commerce Guided Shopping only when its primary contribution improves at least one of these trunks:

### Product search

- product or catalog retrieval;
- e-commerce query understanding, rewriting, or reformulation;
- product matching, ranking, or reranking;
- conversational product search and product discovery.

### Guided-shopping recommendation

- product recommendation or recommender serving;
- preference or need elicitation;
- product comparison and purchase-decision support;
- conversational commerce, product advisors, and shopping assistants;
- industrial recommendation iteration with credible online or production relevance.

The following are not independent trunks:

- product or catalog understanding;
- attribute extraction and catalog management;
- item-data infrastructure;
- generic buyer/seller or transaction Agents;
- generic recommendation without credible product, shopping, Amazon, e-commerce, or approved industrial recommender grounding.

Upstream product understanding may enter only when the primary contribution directly improves search, recommendation, comparison, or shopping decisions.

## Deterministic policy

The selector will:

- remove generic `item` and `items` from commerce-context evidence;
- remove broad standalone admission for `agentic commerce`, `commerce agent`, product attributes, product understanding, item understanding, item fulfillment, product catalogs, and catalog grounding;
- retain high-precision combined phrases such as `e-commerce search`, `product search`, `product recommendation`, `shopping agent`, and approved industrial recommender-system work;
- add explicit guided-shopping phrases such as `guided shopping`, `product advisor`, `product comparison`, `conversational commerce`, and purchase-decision support;
- require commerce/product context plus a search or recommendation capability when no standalone phrase matches;
- treat Agent, model, LLM/VLM, RL, GRPO/DPO, bandit, and online-learning terms as supporting method evidence rather than domain evidence;
- reject security-focused recommendation work and item-center/catalog-infrastructure work whose primary contribution is outside the two trunks.

Primary-domain uniqueness remains unchanged.

## LLM semantic gate

The scoring rubric will define exactly two business trunks. `domain_fit` must be based on primary-contribution alignment, not broad applicability:

- generic recommender papers without product/shopping/commerce evidence score below `0.5`;
- catalog or product-understanding infrastructure scores below `0.5` unless search/recommendation improvement is the central evaluated contribution;
- transaction environments and generic buyer/seller Agents score below `0.5`;
- security papers score at most `0.2`;
- Agent, model, and RL work can score highly when tied to product search or guided recommendation.

The publication threshold remains `0.65`.

## Regression labels

The executable gold set will be revised to reflect the new scope.

New required inclusions cover:

- SPEAR for e-commerce query rewriting and retrieval;
- REAlign for e-commerce reranking with policy optimization;
- A/B Agent for recommendation-strategy iteration;
- DEGR for JD recommendation reranking with RL-style optimization;
- Cleo for conversational product advising;
- Digital Product Advisors for guided product search;
- ATLAS for product recommendation across Amazon domains.

New required exclusions cover:

- Agentic Commerce World, because it evaluates commerce transactions rather than guided search/recommendation;
- recommendation attack/defense work;
- generic next-item, long-sequence, and OOD recommender methods without sufficient commerce grounding;
- the JD Item Center, because its primary contribution is item-knowledge infrastructure;
- brand-impact measurement, generic search-grounding infrastructure, product-information markets, and paid-promotion revenue optimization;
- advertising-creative preference, federated graph imputation, and entertainment live-stream ranking;
- e-commerce image generation.

## Verification

Acceptance requires:

- all revised E-commerce gold labels pass;
- overall gold precision and recall remain at least `0.95`;
- no cross-domain duplicate IDs;
- replay of August 1–6 removes the identified generic/security/transaction papers while retaining the approved search, recommendation, Agent, model, and RL examples;
- all domain validation and unit tests pass.
