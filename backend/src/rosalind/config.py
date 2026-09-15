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


settings = Settings()
