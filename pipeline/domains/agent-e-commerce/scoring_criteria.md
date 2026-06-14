You are evaluating an academic paper for lasting value in the field of E-commerce Agents: e-commerce search, recommendation, product understanding, shopping assistants, LLM-powered commerce workflows, and e-commerce-specific multi-agent collaboration.

The target direction is NOT generic multi-agent systems, generic recommendation, generic RAG, or generic chatbots. Prefer papers where search, recommendation, LLMs, tools, agents, simulators, or evaluation loops are clearly grounded in product catalogs, shopping intent, product comparison, buyer/seller workflows, marketplace operations, or e-commerce conversion/user satisfaction.

Based on the paper's title, abstract, and introduction (if available), rate the following 5 dimensions on a scale of 0.0 to 1.0:

1. **commerce_domain_fit** (0-1): Does the work clearly target e-commerce, online shopping, retail marketplaces, product catalogs, product search, product recommendation, shopping assistance, or buyer/seller workflows?

2. **search_recommendation_value** (0-1): Does it improve product retrieval, ranking, reranking, recommendation, preference elicitation, user intent modeling, product matching, or product comparison in a way useful for e-commerce systems?

3. **llm_agent_integration** (0-1): Does it use LLMs or agents for grounded shopping workflows such as product QA, conversational recommendation, tool calling, catalog grounding, comparison, explanation, recommendation, or purchase decision support?

4. **ecommerce_multi_agent_collaboration** (0-1): Does it propose e-commerce-specific multi-agent coordination such as buyer/seller/merchant/search/recommendation/evaluation/product agents collaborating on shopping or marketplace tasks? Generic multi-agent collaboration without commerce grounding should score low.

5. **production_applicability** (0-1): Would the work help build a real e-commerce shopping/search/recommendation product, with measurable gains in relevance, conversion, CTR, user satisfaction, catalog quality, evaluation, or operational robustness?

Output ONLY a JSON object with these 5 scores and a brief "comment" field (1 sentence in English explaining your overall assessment).

Example output:
```json
{"commerce_domain_fit": 0.9, "search_recommendation_value": 0.85, "llm_agent_integration": 0.8, "ecommerce_multi_agent_collaboration": 0.7, "production_applicability": 0.85, "comment": "Strong commerce-agent paper connecting product search, LLM-grounded shopping assistance, and measurable recommendation quality."}
```

Calibration guidelines:
- Be critical. Generic recommendation or ranking papers without product/shopping/e-commerce grounding usually score 0.2-0.4.
- Generic multi-agent papers score low unless agents represent commerce roles or collaborate on product search, recommendation, comparison, marketplace, or purchase tasks.
- Generic RAG or chatbot papers score high only when grounded in product catalogs, shopping intent, product QA, recommendation, or measurable commerce outcomes.
- Product understanding papers score high when they improve search, recommendation, comparison, attribute extraction, catalog quality, review summarization, or shopping decisions.
- Evaluation papers score high when they measure commerce-specific outcomes such as relevance, conversion, CTR, satisfaction, product match quality, preference accuracy, or grounded recommendation quality.
