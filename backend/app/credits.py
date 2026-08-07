"""Layer-2 battery: org-level month-to-date spend per vendor.

**No vendor exposes a remaining-credit-balance API.** Verified for all three:

* Anthropic — the Usage & Cost Admin API (`/v1/organizations/cost_report`)
  reports spend. There is no balance endpoint; an open feature request asks for
  `GET /v1/organizations/me/balance`.
* OpenAI — `/v1/organization/costs` reports spend. The old
  `/v1/dashboard/billing/credit_grants` is an undocumented console endpoint
  that needs a browser session token, not an API key.
* Google — Gemini billing runs through Cloud Billing. Spend is readable from
  the BigQuery billing export; the AI Studio prepay balance is console-only.

So this module reports **spend against a budget you configure**, not credits
remaining. That distinction is surfaced in the UI rather than papered over.

Everything here is best-effort: a vendor with no admin key, no budget, or a
failing API is reported as `available: False` and the frontend simply omits its
secondary marker. Nothing in this module can block a chat turn.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from .config import get_settings
from .providers.registry import ANTHROPIC, GOOGLE, OPENAI, PROVIDERS

log = logging.getLogger(__name__)

# provider -> (fetched_at_monotonic, payload)
_cache: dict[str, tuple[float, dict]] = {}


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _admin_key(secret_name: str) -> str | None:
    """Admin keys are optional — resolve quietly and treat absence as 'off'."""
    from .config import read_secret_raw
    return read_secret_raw(secret_name)


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


# ---------------------- Per-vendor spend readers ----------------------

def _anthropic_spend() -> dict:
    key = _admin_key(get_settings().ANTHROPIC_ADMIN_KEY_SECRET)
    if not key:
        return _unavailable("no admin key configured")
    try:
        resp = requests.get(
            "https://api.anthropic.com/v1/organizations/cost_report",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            params={
                "starting_at": _month_start().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ending_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.warning("Anthropic cost report failed: %s", e)
        return _unavailable("cost report unavailable")

    # Costs come back as decimal strings in cents, bucketed by day.
    cents = 0.0
    for bucket in payload.get("data", []) or []:
        for item in bucket.get("results", []) or []:
            try:
                cents += float(item.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
    return {"available": True, "spend_usd": round(cents / 100.0, 2)}


def _openai_spend() -> dict:
    key = _admin_key(get_settings().OPENAI_ADMIN_KEY_SECRET)
    if not key:
        return _unavailable("no admin key configured")
    try:
        resp = requests.get(
            "https://api.openai.com/v1/organization/costs",
            headers={"Authorization": f"Bearer {key}"},
            params={"start_time": int(_month_start().timestamp()), "limit": 180},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.warning("OpenAI costs endpoint failed: %s", e)
        return _unavailable("costs endpoint unavailable")

    total = 0.0
    for bucket in payload.get("data", []) or []:
        for item in bucket.get("results", []) or []:
            amount = (item or {}).get("amount") or {}
            try:
                total += float(amount.get("value", 0) or 0)
            except (TypeError, ValueError):
                continue
    return {"available": True, "spend_usd": round(total, 2)}


def _google_spend() -> dict:
    """Gemini spend from the GCP billing export in BigQuery.

    Google has no per-key cost endpoint, so this is the only programmatic path.
    It needs the billing export switched on and `GCP_BILLING_EXPORT_TABLE` set.
    """
    table = get_settings().billing_export_table()
    if not table:
        return _unavailable("no billing export table set")
    try:
        from google.cloud import bigquery
    except ImportError:
        return _unavailable("bigquery client not installed")

    try:
        client = bigquery.Client(project=get_settings().GCP_PROJECT)
        query = f"""
            SELECT SUM(cost) AS total
            FROM `{table}`
            WHERE usage_start_time >= @month_start
              AND LOWER(service.description) LIKE '%generative%'
        """
        job = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("month_start", "TIMESTAMP", _month_start()),
                ]
            ),
        )
        row = next(iter(job.result()), None)
        total = float(row["total"] or 0) if row else 0.0
    except Exception as e:
        log.warning("BigQuery billing export query failed: %s", e)
        return _unavailable("billing export query failed")

    return {"available": True, "spend_usd": round(total, 2)}


_READERS = {
    ANTHROPIC: _anthropic_spend,
    OPENAI: _openai_spend,
    GOOGLE: _google_spend,
}


def provider_spend(provider: str) -> dict:
    """Cached month-to-date spend for one vendor, plus its configured budget.

    Cached because the vendor APIs are rate-limited and lag ~5 minutes anyway,
    so there is nothing to gain from querying them per page load.
    """
    settings = get_settings()
    budget = settings.budget_for(provider)
    if budget <= 0:
        return _unavailable("no budget configured")

    ttl = settings.PROVIDER_SPEND_CACHE_SECONDS
    hit = _cache.get(provider)
    if hit and (time.monotonic() - hit[0]) < ttl:
        return hit[1]

    reader = _READERS.get(provider)
    result = reader() if reader else _unavailable("unsupported provider")
    if result.get("available"):
        spend = result["spend_usd"]
        result = {
            "available": True,
            "spend_usd": spend,
            "budget_usd": budget,
            "fraction_used": min(1.0, spend / budget) if budget else None,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    _cache[provider] = (time.monotonic(), result)
    return result


def all_provider_spend() -> dict[str, dict]:
    return {p: provider_spend(p) for p in PROVIDERS}


def invalidate_spend_cache() -> None:
    """Drop cached spend so a changed budget or admin key applies at once."""
    _cache.clear()
