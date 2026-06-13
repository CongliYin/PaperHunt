"""OpenAI-compatible chat client used by the paper ranking pipeline."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import requests


class LLMClient:
    """Small OpenAI-compatible chat-completions client.

    The provider is configured entirely with environment variables:
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_SCORING, LLM_MODEL_TRANSLATION.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: int = 90,
        max_retries: int = 3,
        concurrency: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY") or ""
        self.default_model = (
            default_model
            or os.getenv("LLM_MODEL_SCORING")
            or os.getenv("LLM_MODEL_TRANSLATION")
            or ""
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self._sem = threading.BoundedSemaphore(
            concurrency or int(os.getenv("LLM_CONCURRENCY", "4"))
        )

    def _validate(self, model: str | None) -> str:
        if not self.base_url:
            raise RuntimeError("LLM_BASE_URL is not configured")
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        resolved = model or self.default_model
        if not resolved:
            raise RuntimeError("LLM model is not configured")
        return resolved

    def chat(
        self,
        messages: str | list[dict[str, str]],
        model: str | None = None,
        *,
        temperature: float = 0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        """Call /chat/completions and return assistant text."""
        resolved_model = self._validate(model)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        with self._sem:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout,
                    )
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise requests.HTTPError(
                            f"retryable HTTP {resp.status_code}: {resp.text[:300]}",
                            response=resp,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                except Exception as exc:  # noqa: BLE001 - retry wrapper
                    last_error = exc
                    if attempt >= self.max_retries:
                        break
                    time.sleep(min(2 ** attempt, 8) + 0.25 * attempt)

        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def chat_json(
        self,
        messages: str | list[dict[str, str]],
        model: str | None = None,
        *,
        temperature: float = 0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Call chat in JSON mode and parse a JSON object.

        Some OpenAI-compatible providers still wrap JSON in fenced markdown even
        when response_format is requested, so we strip that before parsing.
        """
        last_error: Exception | None = None
        for attempt in range(2):
            text = self.chat(
                messages,
                model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )
            try:
                return _parse_json_object(text)
            except Exception as exc:  # noqa: BLE001 - one repair retry
                last_error = exc
                messages = _repair_messages(messages, text)
        raise RuntimeError(f"LLM returned invalid JSON: {last_error}") from last_error


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _repair_messages(
    messages: str | list[dict[str, str]],
    bad_text: str,
) -> list[dict[str, str]]:
    if isinstance(messages, str):
        fixed = [{"role": "user", "content": messages}]
    else:
        fixed = list(messages)
    fixed.append({"role": "assistant", "content": bad_text[:2000]})
    fixed.append(
        {
            "role": "user",
            "content": "The previous response was not valid JSON. Return only one valid JSON object.",
        }
    )
    return fixed

