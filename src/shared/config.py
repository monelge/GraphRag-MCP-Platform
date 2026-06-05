"""
Merkezi uygulama yapılandırması.
Tüm env var okumaları bu modül üzerinden yönetilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppConfig:
    """Uygulama genelinde kullanılan merkezi konfigürasyon modeli."""

    # DB & Services
    postgres_dsn: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    qdrant_url: str
    qdrant_api_key: str | None
    redis_url: str

    # AI Models
    openai_api_key: str
    openai_model: str
    embedding_model: str
    embedding_dim: int
    analysis_model: str
    reasoning_model: str
    llm_base_url: str
    llm_timeout_seconds: int
    llm_max_retries: int
    llm_max_retry_wait_seconds: int

    # Paths
    data_dir: str
    project_registry_path: str
    log_file: str
    log_level: str
    log_format: str
    host_projects_root: str
    host_app_root: str
    container_projects_root: str

    # Retrieval & Context
    default_collection: str
    default_token_budget: int
    max_context_chunks: int
    min_final_score: float
    context_chars_per_token: float
    context_score_weights: dict[str, float]

    # Indexing
    repo_map_ttl: int
    repo_map_max_modules: int
    chunk_min_chars: int
    chunk_max_chars: int
    allow_secret_bypass: bool
    environment: str

    # Budget & Guardrails
    budget_task_max_tokens: int
    budget_task_max_llm_calls: int
    budget_daily_max_usd: float
    budget_daily_max_tokens: int
    guardrail_enabled: bool
    guardrail_token_hard_limit: int
    guardrail_max_total_llm_calls: int
    guardrail_max_aux_llm_calls: int
    guardrail_max_retrieval_retries: int
    compressor_enabled: bool
    compressor_max_ratio: float

    # Features
    hyde_budget_seconds: float
    hyde_expansion_count: int

    # Sandbox
    mount_readonly_paths: list[str]
    mount_readwrite_paths: list[str]
    tool_policy_extra_allowed: list[str]
    timezone: str

    # Observability
    otel_endpoint: str | None
    prometheus_enabled: bool

    # Security
    secret_bypass_files: frozenset[str]
    cross_encoder_enabled: bool
    cross_encoder_model: str


def _build_postgres_dsn() -> str:
    """Bireysel POSTGRES_* değişkenlerinden DSN oluşturur; POSTGRES_DSN varsa onu kullanır."""
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return dsn
    user = os.getenv("POSTGRES_USER", "graphmcp")
    password = os.getenv("POSTGRES_PASSWORD", "graphmcp")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "graphmcp")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def load_config() -> AppConfig:
    """Ortam değişkenlerinden AppConfig yükler."""
    
    # Pre-calculate some values
    chars_per_token = float(os.getenv("CONTEXT_CHARS_PER_TOKEN", "4.0"))
    
    return AppConfig(
        # DB & Services
        postgres_dsn=_build_postgres_dsn(),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "graphmcp"),
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6380/0"),

        # AI Models
        openai_api_key=os.getenv("OPENAI_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1536")),
        analysis_model=os.getenv("ANALYSIS_MODEL", "openai/gpt-4o-mini"),
        reasoning_model=os.getenv("REASONING_MODEL", "openai/o4-mini"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        llm_max_retry_wait_seconds=int(os.getenv("LLM_MAX_RETRY_WAIT_SECONDS", "10")),

        # Paths
        data_dir=os.getenv("DATA_DIR", "/app/data"),
        project_registry_path=os.getenv("PROJECT_REGISTRY_PATH", "/app/data/project_registry.json"),
        log_file=os.getenv("LOG_FILE", "/app/data/graph-mcp.log"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "json"),
        host_projects_root=os.getenv("HOST_PROJECTS_ROOT", "/Volumes/MacBook/RiderProjects"),
        host_app_root=os.getenv("HOST_APP_ROOT", "/Volumes/MacBook/RiderProjects/GraphRagMCP"),
        container_projects_root=os.getenv("CONTAINER_PROJECTS_ROOT", "/projects"),

        # Retrieval & Context
        default_collection=os.getenv("DEFAULT_COLLECTION", "codebase"),
        default_token_budget=int(os.getenv("DEFAULT_TOKEN_BUDGET", "1800")),
        max_context_chunks=int(os.getenv("MAX_CONTEXT_CHUNKS", "8")),
        min_final_score=float(os.getenv("MIN_FINAL_SCORE", "0.05")),
        context_chars_per_token=chars_per_token,
        context_score_weights={
            "retrieval": 0.51,
            "rerank": 0.30,
            "centrality": 0.15,
            "recency": 0.04
        },

        # Indexing
        repo_map_ttl=int(os.getenv("REPO_MAP_TTL", str(24 * 3600))),
        repo_map_max_modules=int(os.getenv("REPO_MAP_MAX_MODULES", "200")),
        chunk_min_chars=int(os.getenv("CHUNK_MIN_CHARS", str(int(300 * chars_per_token)))),
        chunk_max_chars=int(os.getenv("CHUNK_MAX_CHARS", str(int(800 * chars_per_token)))),
        allow_secret_bypass=os.getenv("ALLOW_SECRET_BYPASS", "false").lower() == "true",
        environment=os.getenv("ENVIRONMENT", "development").lower(),

        # Budget & Guardrails
        budget_task_max_tokens=int(os.getenv("BUDGET_TASK_MAX_TOKENS", "50000")),
        budget_task_max_llm_calls=int(os.getenv("BUDGET_TASK_MAX_LLM_CALLS", "20")),
        budget_daily_max_usd=float(os.getenv("BUDGET_DAILY_MAX_USD", "10.0")),
        budget_daily_max_tokens=int(os.getenv("BUDGET_DAILY_MAX_TOKENS", "1000000")),
        guardrail_enabled=os.getenv("GUARDRAIL_ENABLED", "true").lower() == "true",
        guardrail_token_hard_limit=int(os.getenv("GUARDRAIL_TOKEN_HARD_LIMIT", "5000")),
        guardrail_max_total_llm_calls=int(os.getenv("GUARDRAIL_MAX_TOTAL_LLM_CALLS", "2")),
        guardrail_max_aux_llm_calls=int(os.getenv("GUARDRAIL_MAX_AUX_LLM_CALLS", "1")),
        guardrail_max_retrieval_retries=int(os.getenv("GUARDRAIL_MAX_RETRIEVAL_RETRIES", "2")),
        compressor_enabled=os.getenv("COMPRESSOR_ENABLED", "true").lower() == "true",
        compressor_max_ratio=float(os.getenv("COMPRESSOR_MAX_RATIO", "0.6")),

        # Features
        hyde_budget_seconds=float(os.getenv("HYDE_BUDGET_SECONDS", "8.0")),
        hyde_expansion_count=int(os.getenv("HYDE_EXPANSION_COUNT", "3")),

        # Sandbox
        mount_readonly_paths=os.getenv("MOUNT_READONLY_PATHS", "/projects").split(":"),
        mount_readwrite_paths=os.getenv("MOUNT_READWRITE_PATHS", "/tmp").split(":"),
        tool_policy_extra_allowed=[item.strip() for item in os.getenv("TOOL_POLICY_EXTRA_ALLOWED", "").split(";") if item.strip()],
        timezone=os.getenv("TZ", "Europe/Istanbul"),

        # Observability
        otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        prometheus_enabled=os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true",

        # Security
        secret_bypass_files=frozenset(
            f.strip() for f in os.getenv("SECRET_BYPASS_FILES", "").split(",") if f.strip()
        ),
        cross_encoder_enabled=os.getenv("CROSS_ENCODER_ENABLED", "true").lower() == "true",
        cross_encoder_model=os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
    )


config = load_config()
