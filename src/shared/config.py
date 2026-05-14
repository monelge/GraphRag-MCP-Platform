"""
Merkezi uygulama yapılandırması.
Tüm env var okumaları bu modül üzerinden yönetilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Uygulama genelinde kullanılan merkezi konfigürasyon modeli."""

    postgres_dsn: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    qdrant_host: str
    qdrant_port: int
    redis_url: str
    openai_api_key: str
    openai_model: str
    embedding_model: str
    log_level: str
    data_dir: str
    default_collection: str
    project_registry_path: str
    llm_base_url: str
    llm_timeout_seconds: int
    llm_max_retries: int
    llm_max_retry_wait_seconds: int
    log_format: str
    log_file: str
    analysis_model: str
    reasoning_model: str


def load_config() -> AppConfig:
    """Ortam değişkenlerinden AppConfig yükler."""
    return AppConfig(
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgresql://graphmcp:graphmcp@postgres:5432/graphmcp"),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "graphmcp"),
        qdrant_host=os.getenv("QDRANT_HOST", "qdrant"),
        qdrant_port=int(os.getenv("QDRANT_PORT", "6333")),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        openai_api_key=os.getenv("OPENAI_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        data_dir=os.getenv("DATA_DIR", "/app/data"),
        default_collection=os.getenv("DEFAULT_COLLECTION", "codebase"),
        project_registry_path=os.getenv("PROJECT_REGISTRY_PATH", "/app/data/project_registry.json"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        llm_max_retry_wait_seconds=int(os.getenv("LLM_MAX_RETRY_WAIT_SECONDS", "10")),
        log_format=os.getenv("LOG_FORMAT", "json"),
        log_file=os.getenv("LOG_FILE", "/app/data/graph-mcp.log"),
        analysis_model=os.getenv("ANALYSIS_MODEL", "openai/gpt-4o-mini"),
        reasoning_model=os.getenv("REASONING_MODEL", "openai/o4-mini"),
    )


config = load_config()
