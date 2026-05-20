"""Storage primitives: Firestore client + GCS archive writer."""
import json
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore, storage

from .config import get_settings


@lru_cache
def db() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(project=settings.GCP_PROJECT, database=settings.FIRESTORE_DATABASE)


@lru_cache
def gcs() -> storage.Client:
    return storage.Client(project=get_settings().GCP_PROJECT)


def archive_bucket():
    return gcs().bucket(get_settings().GCS_ARCHIVE_BUCKET)


def now() -> datetime:
    return datetime.now(timezone.utc)


def append_to_archive(uid: str, conv_id: str, payload: dict) -> None:
    """Append a single NDJSON line to the conversation archive in GCS.

    Each conversation is one blob; we read, append, rewrite. For low volume this
    is fine. At scale, switch to a pubsub topic that batches into BigQuery.
    """
    bucket = archive_bucket()
    blob = bucket.blob(f"conversations/{uid}/{conv_id}.ndjson")
    existing = blob.download_as_text() if blob.exists() else ""
    line = json.dumps({**payload, "ts": now().isoformat()}, ensure_ascii=False)
    blob.upload_from_string(existing + line + "\n", content_type="application/x-ndjson")


def month_key(d: datetime | None = None) -> str:
    d = d or now()
    return f"{d.year:04d}-{d.month:02d}"


def get_global_settings() -> dict:
    """Admin-configurable settings stored in Firestore, seeded from env defaults.

    Lives at settings/global. Returns env-based defaults merged with any
    admin overrides, so missing keys always resolve to a sane value.
    """
    s = get_settings()
    defaults = {
        "default_model": s.CLAUDE_MODEL,
        "available_models": [s.CLAUDE_MODEL],
        "default_cap_tokens": s.DEFAULT_CAP_TOKENS,
        "flag_keywords": list(s.FLAG_KEYWORDS),
    }
    ref = db().collection("settings").document("global")
    snap = ref.get()
    if snap.exists:
        return {**defaults, **(snap.to_dict() or {})}
    ref.set(defaults)
    return defaults
