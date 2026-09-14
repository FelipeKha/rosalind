import os

DEFAULT_API_URL = "http://localhost:8000"


def api_url() -> str:
    return os.environ.get("ROSALIND_API_URL", DEFAULT_API_URL)
