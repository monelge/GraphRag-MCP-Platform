from __future__ import annotations

from openai import AsyncOpenAI

from src.shared.config import config


class LLMClient:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.llm_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/GraphMCP",
                "X-Title": "GraphMCP",
            },
        )


def get_llm_client() -> AsyncOpenAI:
    return LLMClient.get_instance().client
