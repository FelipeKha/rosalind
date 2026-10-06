"""Backend configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROSALIND_")

    database_url: str = "postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind"
    s3_bucket: str = "rosalind"
    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = "rosalind"
    s3_secret_key: str = "rosalind"
    s3_region: str = "us-east-1"

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    google_auth_prompt: str | None = None
    google_token_uri: str = "https://oauth2.googleapis.com/token"  # nosec B105
    google_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"

    token_encryption_key: str | None = None

    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "rosalind"
    keycloak_audience: str = "rosalind"

    auth_enabled: bool = True

    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    enrich_min_language_length: int = 15
    enrich_batch_size: int = 500
    enrich_budget_seconds: float | None = None
    enrich_language_min_confidence: float = 0.0
    enrich_languages: list[str] = [
        "en",
        "fr",
        "es",
        "de",
        "pt",
        "it",
        "nl",
        "zh",
        "ja",
        "ko",
        "ru",
        "ar",
    ]

    attachment_budget_seconds: float | None = None
    attachment_max_bytes: int = 50 * 1024 * 1024
    attachment_max_output_chars: int = 1_000_000
    attachment_timeout_seconds: float = 120.0

    chunk_target_tokens: int = 400
    chunk_max_tokens: int = 480
    chunk_overlap_tokens: int = 50
    chunk_min_tail_tokens: int = 80
    chunk_max_quote_tokens_per_email: int = 1200
    chunk_max_chunks_per_attachment: int = 20
    chunk_include_signature: bool = True
    chunk_batch_size: int = 500
    chunk_tokenizer_path: str = "backend/assets/bge-m3/tokenizer.json"
    chunk_tokenizer_sha256: str | None = None

    embedding_space: str = "bge_m3_v1"
    embedder_url: str = ""
    embed_window: int = 2048
    embed_batch_tokens: int = 4096
    embed_concurrency: int = 2
    embed_timeout: float = 60.0
    embed_retries: int = 3
    embed_quotes: bool = False
    embed_trash_spam: bool = False
    allow_remote_embedding: bool = False
    embed_inline_budget_seconds: float = 60.0

    # Online search (Prepare step). Budgets and fusion settings are
    # configuration-controlled: they participate in the plan fingerprint, so the
    # agent never chooses them.
    search_index_version: str = "v1"
    search_reranker: str | None = None
    search_cursor_key: str | None = None
    search_max_query_chars: int = 2000
    search_max_list_values: int = 50
    search_default_timezone: str = "UTC"
    search_lexical_k: int = 50
    search_semantic_k: int = 50
    search_fused_k: int = 40
    search_rerank_k: int = 30
    search_window_k: int = 25
    search_rrf_k: int = 60
    search_lexical_weight: float = 1.0
    search_semantic_weight: float = 1.0
    search_max_chunks_per_item: int = 2

    # Semantic retrieval (step 2.2). Placeholders until the benchmark in
    # backend/scripts/bench_semantic_retrieval.py sets them.
    search_semantic_exact_threshold: int | None = None
    search_hnsw_iterative_scan: str = "strict_order"
    search_hnsw_max_scan_tuples: int | None = None
    search_hnsw_scan_mem_multiplier: float | None = None
    search_hnsw_ef_search: int | None = None
    search_semantic_statement_timeout_ms: int | None = None


settings = Settings()
