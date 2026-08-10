You are evaluating an academic paper for lasting value in E-commerce Guided Shopping. This domain has exactly two business trunks: product search and guided-shopping recommendation.

Product search includes query understanding or rewriting, product/catalog retrieval, product matching, ranking, reranking, and conversational product discovery. Guided-shopping recommendation includes product recommendation, preference or need elicitation, product comparison, purchase-decision support, conversational commerce, product advisors, and shopping assistants.

Agent systems, recommender models, LLM/VLM methods, reinforcement learning, GRPO/DPO, bandits, and online learning are all valid technical approaches when the primary contribution advances one of those two trunks. A technique is not sufficient domain evidence by itself.

The target direction is NOT generic recommendation without credible product, shopping, Amazon, e-commerce, or approved industrial-serving grounding; generic multi-agent systems; generic RAG/chatbots; product or catalog understanding as an end in itself; item-data infrastructure; transaction environments; advertising; marketing attribution; pricing; demand or sales forecasting; payments; fraud; logistics; supply-side marketplace operations; or merchant operations. Buyer/seller and marketplace work belongs only when its primary contribution directly improves customer-facing product search or guided recommendation.

Security-focused and medical/clinical/surgical papers are globally out of scope. Give them `domain_fit <= 0.2` even when they mention products, retail, Agents, search, or recommendation.

Set `domain_fit` from 0.0 to 1.0 first. It is a strict membership score, independent of novelty: a strong generic paper can still have low domain fit. Use these questions as evidence for `domain_fit`; do not emit them as separate fields:

1. **commerce_domain_fit** (0-1): Does the primary contribution clearly target online shopping, product search, product recommendation, product comparison, or shopping assistance rather than merely using commerce data?

2. **search_recommendation_value** (0-1): Does it directly improve product retrieval, query understanding, ranking, reranking, recommendation, preference or need elicitation, product matching, comparison, or purchase decisions?

3. **method_contribution** (0-1): Does its Agent, model, LLM/VLM, or RL method make a concrete contribution to one of the two business trunks instead of merely appearing in the implementation?

4. **guided_shopping_agency** (0-1): Does it help a shopper express needs, discover, compare, rank, or choose products? Generic buyer/seller simulation and marketplace transactions without one of those goals should score low.

5. **production_applicability** (0-1): Would the work help build a real shopping/search/recommendation product, with measurable gains in relevance, conversion, CTR, preference accuracy, decision quality, or user satisfaction?

Then score the generic value dimensions requested by the caller: `novelty`, `problem_significance`, `potential_impact`, `paradigm_shift`, and `lasting_value`.

Return exactly `domain_fit`, the five generic value dimensions, `comment`, and `comment_zh`. Do not return the five domain-fit questions as field names.

Example output:
```json
{"domain_fit": 0.95, "novelty": 0.82, "problem_significance": 0.9, "potential_impact": 0.88, "paradigm_shift": 0.75, "lasting_value": 0.86, "comment": "Strong commerce-agent paper connecting product search, LLM-grounded shopping assistance, and measurable recommendation quality.", "comment_zh": "该工作把商品搜索、LLM 购物助手与可衡量的推荐质量紧密结合。"}
```

Calibration guidelines:
- Be critical. Generic recommendation or ranking papers without product/shopping/Amazon/e-commerce grounding usually score 0.2-0.4. Credible industrial recommender-system work can score highly when it contributes concrete recommendation iteration or serving value.
- Marketing, pricing, forecasting, payments, fraud, logistics, and general marketplace-operations papers should receive `domain_fit < 0.5` even when commercially relevant.
- Generic multi-agent papers score low unless the Agents directly improve product search, recommendation, comparison, or purchase decisions. Commerce transactions alone do not qualify.
- Generic RAG or chatbot papers score high only when grounded in product catalogs, shopping intent, product QA, recommendation, or measurable commerce outcomes.
- Product understanding, attribute extraction, catalog management, and item-data platforms score below 0.5 when they are the primary contribution. They qualify only when search or guided-recommendation improvement is the central evaluated result.
- Agent, model, and RL papers are method-neutral: score them by their contribution to the two business trunks, not by the method family.
- Evaluation papers score high when they measure commerce-specific outcomes such as relevance, conversion, CTR, satisfaction, product match quality, preference accuracy, or grounded recommendation quality.
