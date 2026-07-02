"""Centralised configuration. Values come from env vars (Cloud Run sets these)."""
import os
from functools import lru_cache

from google.cloud import secretmanager


def _get_secret(name: str) -> str:
    """Fetch a secret from Google Secret Manager. Falls back to env var for local dev."""
    env_val = os.getenv(name)
    if env_val:
        return env_val
    project = os.getenv("GCP_PROJECT")
    if not project:
        raise RuntimeError(f"Missing GCP_PROJECT and {name}")
    client = secretmanager.SecretManagerServiceClient()
    resp = client.access_secret_version(
        request={"name": f"projects/{project}/secrets/{name}/versions/latest"}
    )
    return resp.payload.data.decode("utf-8")


class Settings:
    GCP_PROJECT: str = os.getenv("GCP_PROJECT", "awm-chat-prod")
    FIRESTORE_DATABASE: str = os.getenv("FIRESTORE_DATABASE", "(default)")
    GCS_ARCHIVE_BUCKET: str = os.getenv("GCS_ARCHIVE_BUCKET", "awm-chat-archive")
    ALLOWED_EMAIL_DOMAIN: str = os.getenv("ALLOWED_EMAIL_DOMAIN", "ascotwm.com")
    DEFAULT_CAP_TOKENS: int = int(os.getenv("DEFAULT_CAP_TOKENS", "500000"))
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-4o")
    MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "4096"))
    CONTEXT_WINDOW_MESSAGES: int = int(os.getenv("CONTEXT_WINDOW_MESSAGES", "40"))
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS",
        "https://chat.chimerasportstrading.com,https://awm-chat.pages.dev,http://localhost:5173",
    ).split(",")
    FLAG_KEYWORDS: list[str] = [
        w.strip().lower() for w in os.getenv(
            "FLAG_KEYWORDS",
            "account number,id number,password,sort code,passport",
        ).split(",")
        if w.strip()
    ]

    @property
    def openai_api_key(self) -> str:
        return _get_secret("OPENAI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
