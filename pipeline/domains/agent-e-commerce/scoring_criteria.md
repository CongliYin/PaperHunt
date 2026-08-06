You are evaluating an academic paper for lasting value in E-commerce Agents. This domain has four trunks only: product search/retrieval/ranking, product recommendation, product/catalog understanding, and shopping agents or assistants.

The target direction is NOT generic multi-agent systems, generic RAG/chatbots, advertising, marketing attribution, pricing, demand or sales forecasting, payments, fraud, logistics, supply-side marketplace operations, or merchant operations. Buyer/seller or marketplace work belongs only when its primary contribution directly improves product search, recommendation, product understanding, or a shopping agent. Industrial recommender systems are in scope when they improve recommendation iteration or serving.

Set `domain_fit` from 0.0 to 1.0 first. It is a strict membership score, independent of novelty: a strong generic paper can still have low domain fit. Use these questions as evidence for `domain_fit`; do not emit them as separate fields:

1. **commerce_domain_fit** (0-1): Does the work clearly target online shopping, product catalogs, product search, product recommendation, product understanding, or shopping assistance?

2. **search_recommendation_value** (0-1): Does it improve product retrieval, ranking, reranking, recommendation, preference elicitation, user intent modeling, product matching, or product comparison in a way useful for e-commerce systems?

3. **llm_agent_integration** (0-1): Does it use LLMs or agents for grounded shopping workflows such as product QA, conversational recommendation, tool calling, catalog grounding, comparison, explanation, recommendation, or purchase decision support?

4. **ecommerce_multi_agent_collaboration** (0-1): Does it use agents to improve product retrieval, recommendation, catalog understanding, product comparison, or purchase decisions? Generic buyer/seller simulation and marketplace operations without one of those goals should score low.

5. **production_applicability** (0-1): Would the work help build a real e-commerce shopping/search/recommendation product, with measurable gains in relevance, conversion, CTR, user satisfaction, catalog quality, evaluation, or operational robustness?

Then score the generic value dimensions requested by the caller: `novelty`, `problem_significance`, `potential_impact`, `paradigm_shift`, and `lasting_value`.

Return exactly `domain_fit`, the five generic value dimensions, `comment`, and `comment_zh`. Do not return the five domain-fit questions as field names.

Example output:
```json
{"domain_fit": 0.95, "novelty": 0.82, "problem_significance": 0.9, "potential_impact": 0.88, "paradigm_shift": 0.75, "lasting_value": 0.86, "comment": "Strong commerce-agent paper connecting product search, LLM-grounded shopping assistance, and measurable recommendation quality.", "comment_zh": "该工作把商品搜索、LLM 购物助手与可衡量的推荐质量紧密结合。"}
```

Calibration guidelines:
- Be critical. Generic recommendation or ranking papers without product/shopping/e-commerce grounding usually score 0.2-0.4, except credible industrial recommender-system work with concrete iteration or serving value.
- Marketing, pricing, forecasting, payments, fraud, logistics, and general marketplace-operations papers should receive `domain_fit < 0.5` even when commercially relevant.
- Generic multi-agent papers score low unless agents represent commerce roles or collaborate on product search, recommendation, comparison, marketplace, or purchase tasks.
- Generic RAG or chatbot papers score high only when grounded in product catalogs, shopping intent, product QA, recommendation, or measurable commerce outcomes.
- Product understanding papers score high when they improve search, recommendation, comparison, attribute extraction, catalog quality, review summarization, or shopping decisions.
- Evaluation papers score high when they measure commerce-specific outcomes such as relevance, conversion, CTR, satisfaction, product match quality, preference accuracy, or grounded recommendation quality.
