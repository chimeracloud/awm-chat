"""Centralised configuration.

Secrets live in Google Secret Manager and are managed from the app's admin
Settings page (see `secrets_admin.py`) — nobody needs the GCP console for a
routine key rotation. An env var of the same name still wins, which keeps local
development working; the admin UI flags when that shadowing is in effect so a
saved key that appears to do nothing is explainable.

Non-secret settings that used to be env-only (per-agent budgets, the billing
export table) are now also editable in the app and stored in
`settings/global`; the env var remains the fallback.
"""
import os
import threading
import time
from functools import lru_cache

from google.cloud import secretmanager

from .providers.registry import ANTHROPIC, GOOGLE, OPENAI, PROVIDER_SECRET_NAMES, PROVIDERS

# Secret Manager reads are cached briefly. Before this, every chat turn made a
# round trip to fetch the vendor key — latency and API quota for a value that
# changes a few times a year. Writes through the admin UI bust the entry
# immediately, so a rotation still takes effect on the next request.
_SECRET_TTL_SECONDS = 300
_secret_cache: dict[str, tuple[float, str | None]] = {}
_secret_lock = threading.Lock()


def _fetch_secret(name: str) -> str | None:
    """Read a secret, env var first. Returns None when it isn't configured."""
    env_val = os.getenv(name)
    if env_val:
        return env_val
    project = os.getenv("GCP_PROJECT")
    if not project:
        return None
    try:
        client = secretmanager.SecretManagerServiceClient()
        resp = client.access_secret_version(
            request={"name": f"projects/{project}/secrets/{name}/versions/latest"}
        )
        return resp.payload.data.decode("utf-8")
    except Exception:
        # Not configured, disabled, or no permission — all mean "unavailable",
        # which callers handle by hiding the agent rather than erroring.
        return None


def read_secret_raw(name: str) -> str | None:
    """Cached secret read. None when unset — never raises."""
    with _secret_lock:
        hit = _secret_cache.get(name)
        if hit and (time.monotonic() - hit[0]) < _SECRET_TTL_SECONDS:
            return hit[1]
    value = _fetch_secret(name)
    with _secret_lock:
        _secret_cache[name] = (time.monotonic(), value)
    return value


def invalidate_secret_cache(name: str | None = None) -> None:
    """Drop cached secrets so a newly saved key takes effect immediately."""
    with _secret_lock:
        if name is None:
            _secret_cache.clear()
        else:
            _secret_cache.pop(name, None)
    # `available_providers()` reads through the cache cleared above, so it needs
    # no separate invalidation — that is the point of leaving it uncached.


def _get_secret(name: str) -> str:
    """Secret read that raises when missing — for callers that cannot proceed."""
    value = read_secret_raw(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


class Settings:
    GCP_PROJECT: str = os.getenv("GCP_PROJECT", "awm-chat-prod")
    FIRESTORE_DATABASE: str = os.getenv("FIRESTORE_DATABASE", "(default)")
    GCS_ARCHIVE_BUCKET: str = os.getenv("GCS_ARCHIVE_BUCKET", "awm-chat-archive")
    ALLOWED_EMAIL_DOMAIN: str = os.getenv("ALLOWED_EMAIL_DOMAIN", "ascotwm.com")

    # Per-provider monthly allowance. Each agent gets its own pool of this size,
    # so exhausting one agent leaves the others usable — that is what makes the
    # "switch to an agent that still has tokens" flow meaningful. Admins can
    # override per user via `users/{uid}.caps_by_provider`.
    DEFAULT_CAP_TOKENS: int = int(os.getenv("DEFAULT_CAP_TOKENS", "500000"))

    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "claude-sonnet-5")
    MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "4096"))
    # Hard ceiling on replayed history. A message count alone is meaningless —
    # forty one-liners is nothing, forty with a report attached will exceed a
    # provider's per-minute limit on its own. The count is kept as a cheap
    # upper bound on Firestore reads; the token budget is what actually binds.
    CONTEXT_WINDOW_MESSAGES: int = int(os.getenv("CONTEXT_WINDOW_MESSAGES", "40"))
    HISTORY_TOKEN_BUDGET: int = int(os.getenv("HISTORY_TOKEN_BUDGET", "25000"))
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

    # --- Layer-2 battery: org-level spend against a budget -------------------
    # No vendor exposes a remaining-credit balance, so the secondary marker on
    # each agent's battery is month-to-date spend from that vendor's cost API
    # measured against a budget. Budgets are editable in the admin Settings
    # page (stored in `settings/global`); these env values are the fallback.
    # A budget of 0 hides the marker for that agent.
    PROVIDER_BUDGET_ENV = {
        ANTHROPIC: "ANTHROPIC_BUDGET_USD",
        OPENAI: "OPENAI_BUDGET_USD",
        GOOGLE: "GOOGLE_BUDGET_USD",
    }
    # Admin keys are separate credentials from the inference keys and are
    # optional — without them the app simply hides the org-spend marker.
    ANTHROPIC_ADMIN_KEY_SECRET: str = os.getenv(
        "ANTHROPIC_ADMIN_KEY_SECRET", "ANTHROPIC_ADMIN_KEY"
    )
    OPENAI_ADMIN_KEY_SECRET: str = os.getenv("OPENAI_ADMIN_KEY_SECRET", "OPENAI_ADMIN_KEY")
    # BigQuery table holding the GCP billing export, e.g.
    # "chiops.billing.gcp_billing_export_v1_XXXX". Gemini spend is only
    # readable this way — Google has no per-key cost endpoint.
    GCP_BILLING_EXPORT_TABLE: str = os.getenv("GCP_BILLING_EXPORT_TABLE", "")
    PROVIDER_SPEND_CACHE_SECONDS: int = int(os.getenv("PROVIDER_SPEND_CACHE_SECONDS", "300"))

    def api_key_for(self, provider: str) -> str:
        """Inference API key for a vendor, from Secret Manager or env."""
        name = PROVIDER_SECRET_NAMES.get(provider)
        if not name:
            raise ValueError(f"Unknown provider: {provider}")
        return _get_secret(name)

    def has_key_for(self, provider: str) -> bool:
        """Whether a vendor is usable. Drives the switcher greying out agents
        whose key is missing instead of letting the user pick one that 500s."""
        name = PROVIDER_SECRET_NAMES.get(provider)
        return bool(name and read_secret_raw(name))

    def budget_for(self, provider: str) -> float:
        """Admin-set budget, falling back to the env var.

        Imported lazily because `storage` imports this module — reading the
        Firestore settings at import time would be circular.
        """
        try:
            from .storage import get_global_settings
            budgets = get_global_settings().get("provider_budgets_usd") or {}
            value = budgets.get(provider)
            if value is not None:
                return float(value)
        except Exception:
            pass
        return float(os.getenv(self.PROVIDER_BUDGET_ENV.get(provider, ""), "0") or 0)

    def billing_export_table(self) -> str:
        """Admin-set BigQuery billing export table, falling back to the env var."""
        try:
            from .storage import get_global_settings
            value = get_global_settings().get("gcp_billing_export_table")
            if value:
                return str(value)
        except Exception:
            pass
        return self.GCP_BILLING_EXPORT_TABLE


@lru_cache
def get_settings() -> Settings:
    return Settings()


def available_providers() -> tuple[str, ...]:
    """Vendors with a usable key.

    Deliberately *not* cached here. It reads through `read_secret_raw`, which is
    already TTL-cached, so this is cheap — and an unbounded cache at this level
    was a live bug: the comment used to claim the set "does not change without a
    redeploy", but keys are added from the admin page at runtime. Cloud Run runs
    several instances; only the one that handled the write clears its own cache,
    so any other instance that had already computed this held a stale answer for
    the rest of its life. The symptom was an agent staying greyed out after its
    key was saved, until that instance happened to be recycled. Deriving from
    the TTL-cached read instead means every instance converges within the TTL.
    """
    s = get_settings()
    return tuple(p for p in PROVIDERS if s.has_key_for(p))
