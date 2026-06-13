You are evaluating an academic paper for lasting value in the field of Agent Harness: production-grade infrastructure for LLM/AI agents, including runtime execution engines, skill/tool orchestration, session state, planning policies, context engineering, memory, observability, governance, security, and platform services.

The target direction is NOT generic LLM agents, generic prompt engineering, pure RAG, pure model alignment, standalone benchmarks, or isolated chatbot applications. Prefer papers that help build a reliable, observable, governable, secure, multi-channel enterprise Agent Harness.

Based on the paper's title, abstract, and introduction (if available), rate the following 5 dimensions on a scale of 0.0 to 1.0:

1. **harness_architecture_value** (0-1): Does the work define or improve reusable Agent Harness architecture, runtime, orchestration, tool/skill execution, session management, context/memory infrastructure, or platform services? High scores require system-level value rather than a narrow task trick.

2. **runtime_reliability** (0-1): Does the work address production execution concerns such as routing, retries, timeouts, interruptions, fallback, durable state, sandboxing, deterministic behavior, long-horizon execution, or failure recovery?

3. **tool_context_memory_integration** (0-1): Does the work integrate tools/skills, planning policies, context assembly/compression/retrieval, and memory in a way that makes agents more controllable and reusable across channels or tasks?

4. **observability_governance_security** (0-1): Does the work provide credible tracing, logs, metrics, evaluation, guardrails, access control, permissioning, content/data safety, anti-prompt-injection, auditability, or runtime governance?

5. **production_applicability** (0-1): Would this work be useful for building or operating a real enterprise agent platform with multi-channel entry, API gateways, model/tool repositories, knowledge bases, deployment gates, and operations workflows?

Output ONLY a JSON object with these 5 scores and a brief "comment" field (1 sentence in English explaining your overall assessment).

Example output:
```json
{"harness_architecture_value": 0.85, "runtime_reliability": 0.8, "tool_context_memory_integration": 0.75, "observability_governance_security": 0.9, "production_applicability": 0.85, "comment": "Strong production agent harness design that combines runtime execution, tool permissions, deterministic gates, and operational observability."}
```

Calibration guidelines:
- Be critical. Generic LLM-agent papers without runtime, orchestration, governance, or platform contributions usually score 0.2-0.4.
- Pure prompt engineering, pure RAG, pure model alignment, pure chatbot, or pure benchmark papers should score low unless they clearly contribute to harness infrastructure.
- Tool-use papers score high only when they include execution control, tool routing, sandboxing, permissions, workflow state, or reusable orchestration architecture.
- Security papers score high only when they protect agent runtimes, tools, connectors, permissions, data flows, or production workflows, not just generic model safety.
- Evaluation papers score high only when they provide harness-level observability, tracing, regression tests, deployment gates, or operational guardrails.
- Context or memory papers score high only when they are framed as part of reusable agent runtime/context management rather than isolated long-context modeling.
