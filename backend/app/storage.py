"""Storage primitives: Firestore client + GCS archive writer."""
import json
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore, storage

from .config import get_settings
from .providers.registry import PROVIDERS, seeded_available_models


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
        "default_model": s.DEFAULT_MODEL,
        "available_models": seeded_available_models(),
        "default_cap_tokens": s.DEFAULT_CAP_TOKENS,
        "flag_keywords": list(s.FLAG_KEYWORDS),
        # Editable in the admin Settings page. Budgets drive the org-spend
        # marker on each battery; 0 hides it. Not secrets — API keys go to
        # Secret Manager via `secrets_admin`, never here.
        "provider_budgets_usd": {p: 0.0 for p in PROVIDERS},
        "gcp_billing_export_table": "",
    }
    ref = db().collection("settings").document("global")
    snap = ref.get()
    if snap.exists:
        return {**defaults, **(snap.to_dict() or {})}
    ref.set(defaults)
    return defaults


# ---------------------- Per-provider usage accounting ----------------------
#
# The stored shape stays backwards-compatible: `tokens_used`, `input_tokens`,
# `output_tokens` and `requests` remain the all-provider totals they always
# were, so the existing admin metrics and any historical documents keep
# working. Per-agent figures live alongside them under `by_provider`.
#
#   usage/{uid}/months/{YYYY-MM} = {
#       tokens_used, input_tokens, output_tokens, requests,   # totals (existing)
#       by_provider: { anthropic: {...}, openai: {...}, google: {...} },
#       updated_at,
#   }

def usage_doc(uid: str, mkey: str | None = None):
    return (
        db()
        .collection("usage")
        .document(uid)
        .collection("months")
        .document(mkey or month_key())
    )


def _empty_counters() -> dict:
    return {"tokens_used": 0, "input_tokens": 0, "output_tokens": 0, "requests": 0}


def read_usage(uid: str, mkey: str | None = None) -> dict:
    """Current month's counters for a user, with `by_provider` always populated.

    Documents written before the multi-provider change have no `by_provider`
    key. Rather than backfill, those totals are reported under the provider
    that was live at the time (OpenAI), so historical consumption still counts
    against something rather than vanishing.
    """
    snap = usage_doc(uid, mkey).get()
    data = (snap.to_dict() or {}) if snap.exists else {}

    by_provider = data.get("by_provider")
    if not isinstance(by_provider, dict):
        by_provider = {}
        legacy_total = data.get("tokens_used", 0) or 0
        if legacy_total:
            from .providers.registry import OPENAI
            by_provider[OPENAI] = {
                "tokens_used": legacy_total,
                "input_tokens": data.get("input_tokens", 0) or 0,
                "output_tokens": data.get("output_tokens", 0) or 0,
                "requests": data.get("requests", 0) or 0,
            }

    return {
        **_empty_counters(),
        **{k: v for k, v in data.items() if k in _empty_counters()},
        "by_provider": {p: {**_empty_counters(), **(by_provider.get(p) or {})} for p in PROVIDERS},
    }


def cap_for(profile: dict, provider: str) -> int:
    """This user's monthly allowance for one agent.

    Falls back to the single `cap_tokens` field, which is what every existing
    user document has — so each agent gets a pool of that size unless an admin
    sets a narrower per-agent cap.
    """
    per_provider = profile.get("caps_by_provider")
    if isinstance(per_provider, dict):
        value = per_provider.get(provider)
        if isinstance(value, int) and value >= 0:
            return value
    fallback = profile.get("cap_tokens")
    if isinstance(fallback, int) and fallback >= 0:
        return fallback
    return get_settings().DEFAULT_CAP_TOKENS


def record_usage(uid: str, provider: str, input_tokens: int, output_tokens: int,
                 mkey: str | None = None) -> None:
    """Add one turn's tokens to both the totals and the provider's counters.

    Uses Firestore `Increment` so concurrent turns from the same user (two
    browser tabs, a retry) cannot clobber each other the way a read-modify-write
    would.
    """
    total = (input_tokens or 0) + (output_tokens or 0)
    inc = firestore.Increment
    usage_doc(uid, mkey).set(
        {
            "tokens_used": inc(total),
            "input_tokens": inc(input_tokens or 0),
            "output_tokens": inc(output_tokens or 0),
            "requests": inc(1),
            "by_provider": {
                provider: {
                    "tokens_used": inc(total),
                    "input_tokens": inc(input_tokens or 0),
                    "output_tokens": inc(output_tokens or 0),
                    "requests": inc(1),
                }
            },
            "updated_at": now(),
        },
        merge=True,
    )


def reset_usage(uid: str, mkey: str | None = None) -> None:
    """Clear a user's counters for a month, totals and per-agent alike."""
    usage_doc(uid, mkey).set(
        {
            **_empty_counters(),
            "by_provider": {p: _empty_counters() for p in PROVIDERS},
            "updated_at": now(),
        }
    )
