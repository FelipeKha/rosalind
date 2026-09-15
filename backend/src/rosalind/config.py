"""Backend configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROSALIND_")

    database_url: str = "postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind"
    s3_bucket: str = "rosalind"


settings = Settings()
