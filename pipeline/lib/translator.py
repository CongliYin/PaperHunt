"""Chinese summary enrichment for ranked papers."""

from __future__ import annotations

import json
import os
from typing import Any

from .llm_client import LLMClient


def enrich_zh(
    paper: dict[str, Any],
    *,
    client: LLMClient | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Translate title/abstract and extract Chinese key points in one LLM call."""
    client = client or LLMClient()
    model = model or os.getenv("LLM_MODEL_TRANSLATION")
    payload = {
        "title": paper.get("title", ""),
        "abstract": paper.get("abstract", ""),
        "comments": paper.get("comments", ""),
        "categories": paper.get("categories", []),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是面向 AI/计算机视觉研究者的中文论文速读编辑。"
                "保留模型名、方法名、数据集名、机构名等专有名词英文；"
                "必要时用中文解释并在括号中保留英文原词。只输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请为这篇论文生成中文精华，JSON 字段必须包含："
                "title_zh, abstract_zh, tldr_zh, key_points_zh。"
                "tldr_zh 不超过 40 个汉字；key_points_zh 为 3 到 5 条。"
                "\n\n论文："
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]
    data = client.chat_json(messages, model=model, max_tokens=2048)
    return normalize_zh(data)


def normalize_zh(data: dict[str, Any]) -> dict[str, Any]:
    points = data.get("key_points_zh") or []
    if isinstance(points, str):
        points = [p.strip("- 0123456789.、") for p in points.splitlines() if p.strip()]
    points = [str(p).strip() for p in points if str(p).strip()][:5]
    return {
        "title_zh": str(data.get("title_zh") or "").strip(),
        "abstract_zh": str(data.get("abstract_zh") or "").strip(),
        "tldr_zh": str(data.get("tldr_zh") or "").strip(),
        "key_points_zh": points,
    }

