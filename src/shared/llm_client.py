from __future__ import annotations
import os
from openai import AsyncOpenAI


class LLMClient:
    _instance: "LLMClient | None" = None

    @classmethod
    def get_instance(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            default_headers={
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            },
        )


def get_llm_client() -> AsyncOpenAI:
    return LLMClient.get_instance().client
