"""
LLM Client — OpenRouter (TIER_CHEAP/REASON) ve Ollama (TIER_LOCAL) için unified istemci.

OpenAI-uyumlu /chat/completions endpoint'ini kullanır.
Ollama için base_url override edilir.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT     = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))


class LLMClient:
    """
    OpenAI-uyumlu tamamlama istemcisi.

    model:    OpenRouter model adı (ör. google/gemini-2.5-flash)
    base_url: None → OpenRouter; str → Ollama/yerel endpoint
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    async def complete(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 2000,
        temperature: float = 0.1,
        base_url: Optional[str] = None,
    ) -> str:
        url  = f"{base_url or OPENROUTER_BASE_URL}/chat/completions"
        hdrs = self._headers(base_url)

        payload = {
            "model":      model,
            "messages":   messages,
            "max_tokens": max_tokens,
            "temperature":temperature,
        }

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=hdrs)
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            logger.warning("LLM yanıt parse hatası: %s — raw: %s", exc, str(data)[:200])
            return str(data)

    def _headers(self, base_url: Optional[str]) -> dict:
        hdrs: dict = {"Content-Type": "application/json"}
        if not base_url:
            # OpenRouter
            hdrs["Authorization"] = f"Bearer {self._key}"
            hdrs["HTTP-Referer"]  = os.getenv("LLM_REFERER", "https://graphragmcp.local")
            hdrs["X-Title"]       = "GraphRagMCP Agent"
        return hdrs
