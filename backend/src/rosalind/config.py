"""Backend configuration loaded from environment variables and an optional YAML file.

Precedence: explicit init args > environment variables > YAML file > defaults.
The YAML file is named by ``ROSALIND_CONFIG`` (default ``rosalind.yaml``); if it
does not exist the app behaves exactly as before (env-only). Nested settings
(such as ``eval``) may be set in YAML or via ``ROSALIND_<SECTION>__<FIELD>``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class EvalSettings(BaseModel):
    """Evaluation subsystem settings. Disabled unless explicitly enabled."""

    model_config = {"extra": "forbid"}

    enabled: bool = False
    runs_dir: Path = Path("runs")


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Load settings from the YAML file named by ``ROSALIND_CONFIG``.

    A missing file is not an error; a malformed or non-mapping file is.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        path = os.environ.get("ROSALIND_CONFIG", "rosalind.yaml")
        config_path = Path(path)
        if not config_path.is_file():
            self._data: dict[str, Any] = {}
            return
        loaded = yaml.safe_load(config_path.read_text())
        if loaded is None:
            self._data = {}
        elif isinstance(loaded, dict):
            self._data = loaded
        else:
            raise ValueError(f"config file must be a mapping: {config_path}")

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROSALIND_",
        env_nested_delimiter="__",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    eval: EvalSettings = EvalSettings()

    database_url: str = "postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind"
    s3_bucket: str = "rosalind"
    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = "rosalind"
    s3_secret_key: str = "rosalind"
    s3_region: str = "us-east-1"

    log_level: str = "INFO"
    log_format: str = "console"
    log_query_text: bool = False

    # How long rows in ``search.request_log`` are retained before pruning.
    search_request_log_retention_days: int = 30

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
    embedder_backend: str = "flagembedding"
    embedder_device: str = "auto"
    embedder_use_fp16: bool = False
    embedder_batch_size: int = 8
    embedder_max_length: int = 512
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
    search_reranker_backend: str = "flagembedding"
    search_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    search_reranker_device: str = "auto"
    search_reranker_use_fp16: bool = False
    search_reranker_url: str = ""
    search_reranker_timeout_ms: int = 20000
    search_reranker_max_input_tokens: int = 512
    search_reranker_text_mode: str = "index"
    search_reranker_max_concurrent_requests: int = 1
    search_reranker_max_batch_size: int = 32
    search_reranker_deadline_ms: int = 8000
    search_cursor_key: str | None = None
    search_max_query_chars: int = 2000
    search_max_list_values: int = 50
    search_default_timezone: str = "UTC"
    search_snippet_max_chars: int = 800
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
