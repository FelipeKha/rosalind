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

    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000


settings = Settings()
