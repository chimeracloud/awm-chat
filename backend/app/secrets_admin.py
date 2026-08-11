"""Admin-managed API keys, written through to Google Secret Manager.

Admins set vendor keys from the Settings page instead of the GCP console. The
keys themselves are **never stored in Firestore** — this module writes them
straight to Secret Manager and reads them back from there.

That matters here specifically: the Cloud Run service account carries an
inherited `roles/editor`, so anything in Firestore is readable by a wide set of
principals, and Firestore gives no versioning, rotation history, or per-access
audit trail. Secret Manager gives all three. The admin experience is the same
either way; only the storage differs.

What is stored in Firestore is the non-secret metadata an admin needs to see
whether a key is configured and when it last changed (`settings/secrets`), plus
an entry in the existing `audit` collection on every change.

Requires `roles/secretmanager.admin` on the service account (or, minimally,
`secretmanager.secrets.create`, `secretmanager.versions.add`,
`secretmanager.versions.access` and `secretmanager.versions.disable`).
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from google.api_core import exceptions as gexc
from pydantic import BaseModel, Field

from .auth import AuthedUser, require_admin
from .config import get_settings, invalidate_secret_cache, read_secret_raw
from .providers.registry import ANTHROPIC, GOOGLE, OPENAI, PROVIDER_LABELS
from .storage import db, now

log = logging.getLogger(__name__)

router = APIRouter()


# Only these may be written from the app. An allowlist rather than a free-form
# name, so a compromised admin session can't overwrite unrelated secrets in the
# project (database passwords, service-account keys, anything else in `chiops`).
MANAGED_SECRETS: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {
        "label": "Claude API key",
        "provider": ANTHROPIC,
        "kind": "inference",
        "hint": "Starts with sk-ant-api…  — from console.anthropic.com → API keys",
        "required": True,
    },
    "OPENAI_API_KEY": {
        "label": "OpenAI API key",
        "provider": OPENAI,
        "kind": "inference",
        "hint": "Starts with sk-…  — from platform.openai.com → API keys",
        "required": True,
    },
    "GEMINI_API_KEY": {
        "label": "Gemini API key",
        "provider": GOOGLE,
        "kind": "inference",
        "hint": "Starts with AIza…  — from aistudio.google.com → Get API key",
        "required": True,
    },
    "ANTHROPIC_ADMIN_KEY": {
        "label": "Claude admin key",
        "provider": ANTHROPIC,
        "kind": "spend",
        "hint": "Starts with sk-ant-admin01…  — only needed for the spend marker",
        "required": False,
    },
    "OPENAI_ADMIN_KEY": {
        "label": "OpenAI admin key",
        "provider": OPENAI,
        "kind": "spend",
        "hint": "An organisation admin key — only needed for the spend marker",
        "required": False,
    },
}


def _sm_client():
    from google.cloud import secretmanager
    return secretmanager.SecretManagerServiceClient()


def _require_managed(name: str) -> dict:
    meta = MANAGED_SECRETS.get(name)
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Not a managed secret: {name}")
    return meta


def _meta_doc():
    return db().collection("settings").document("secrets")


def _read_meta() -> dict:
    snap = _meta_doc().get()
    return (snap.to_dict() or {}) if snap.exists else {}


# ---------------------- Validation ----------------------
#
# A key is checked against the vendor before it is saved, so a typo is caught
# at paste time rather than surfacing as a broken agent for whoever chats next.

def _validate(name: str, value: str) -> tuple[bool, str]:
    meta = MANAGED_SECRETS[name]
    provider, kind = meta["provider"], meta["kind"]
    try:
        if kind == "inference":
            # Each client is bound to a local. Constructing one inline and
            # chaining off it leaves no reference, so the client can be
            # garbage-collected — and closed — before a lazily-paginated call
            # actually issues its request. google-genai's models.list() is
            # lazy, and that pattern fails with "Cannot send a request, as the
            # client has been closed" rather than reporting the real result.
            if provider == ANTHROPIC:
                import anthropic
                client = anthropic.Anthropic(api_key=value)
                client.models.list(limit=1)
            elif provider == OPENAI:
                from openai import OpenAI
                client = OpenAI(api_key=value)
                client.models.list()
            elif provider == GOOGLE:
                from google import genai
                client = genai.Client(api_key=value)
                # One page is enough to prove the key; don't walk the catalog.
                next(iter(client.models.list()), None)
        else:
            import requests
            from datetime import timedelta
            end = now()
            start = end - timedelta(days=1)
            if provider == ANTHROPIC:
                r = requests.get(
                    "https://api.anthropic.com/v1/organizations/cost_report",
                    headers={"x-api-key": value, "anthropic-version": "2023-06-01"},
                    params={
                        "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "ending_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    timeout=10,
                )
                r.raise_for_status()
            elif provider == OPENAI:
                r = requests.get(
                    "https://api.openai.com/v1/organization/costs",
                    headers={"Authorization": f"Bearer {value}"},
                    params={"start_time": int(start.timestamp()), "limit": 1},
                    timeout=10,
                )
                r.raise_for_status()
        return True, "Key accepted by the vendor."
    except Exception as e:
        # Surface the vendor's own message — "invalid x-api-key" is far more
        # useful to whoever is pasting than a generic failure.
        detail = str(e)
        return False, detail[:300]


# ---------------------- Endpoints ----------------------


@router.get("/admin/secrets")
async def list_secrets(admin: Annotated[AuthedUser, Depends(require_admin)]):
    """Status of each managed key. Never returns a key value.

    `env_override` matters: a key set as a Cloud Run env var takes precedence
    over Secret Manager, so saving here would appear to do nothing. Surfacing
    it stops that being a mystery.
    """
    meta = _read_meta()
    items = []
    for name, spec in MANAGED_SECRETS.items():
        import os
        env_override = bool(os.getenv(name))
        try:
            value = read_secret_raw(name)
        except Exception:
            value = None
        stored = meta.get(name) or {}
        items.append({
            "name": name,
            "label": spec["label"],
            "provider": spec["provider"],
            "provider_label": PROVIDER_LABELS.get(spec["provider"], spec["provider"]),
            "kind": spec["kind"],
            "hint": spec["hint"],
            "required": spec["required"],
            "configured": bool(value),
            # Enough to recognise which key is loaded, not enough to use it.
            "masked": f"…{value[-4:]}" if value and len(value) >= 8 else None,
            "env_override": env_override,
            "updated_at": stored.get("updated_at").isoformat() if stored.get("updated_at") else None,
            "updated_by": stored.get("updated_by"),
        })
    return {"secrets": items}


class SecretBody(BaseModel):
    value: str = Field(min_length=8, max_length=512)
    # Set false only to force-save a key the vendor rejected (e.g. a brand new
    # key that has not propagated yet).
    validate_first: bool = True


@router.put("/admin/secrets/{name}")
async def set_secret(
    name: str,
    body: SecretBody,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Save a key as a new Secret Manager version, after checking it works."""
    _require_managed(name)
    value = body.value.strip()
    if not value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Key is empty")

    if body.validate_first:
        ok, message = _validate(name, value)
        if not ok:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                {"error": "validation_failed", "message": message},
            )

    project = get_settings().GCP_PROJECT
    client = _sm_client()
    parent = f"projects/{project}"

    try:
        try:
            client.create_secret(request={
                "parent": parent,
                "secret_id": name,
                "secret": {"replication": {"automatic": {}}},
            })
        except gexc.AlreadyExists:
            pass  # first write creates it; later writes just add a version

        client.add_secret_version(request={
            "parent": f"{parent}/secrets/{name}",
            "payload": {"data": value.encode("utf-8")},
        })
    except gexc.PermissionDenied as e:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": "permission_denied",
                "message": (
                    "The backend service account cannot write to Secret Manager. "
                    "Grant it roles/secretmanager.admin on the project. "
                    f"({e})"
                ),
            },
        )
    except Exception as e:
        log.exception("Secret write failed for %s", name)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not save key: {e}")

    invalidate_secret_cache(name)

    _meta_doc().set(
        {name: {"updated_at": now(), "updated_by": admin.email}},
        merge=True,
    )
    # Record that a key changed — never what it changed to.
    db().collection("audit").document().set({
        "type": "secret_update",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "secret": name,
        "created_at": now(),
    })

    return {"ok": True, "name": name, "masked": f"…{value[-4:]}"}


@router.post("/admin/secrets/{name}/test")
async def test_secret(
    name: str,
    body: SecretBody,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Check a key against the vendor without saving it."""
    _require_managed(name)
    ok, message = _validate(name, body.value.strip())
    return {"ok": ok, "message": message}


@router.post("/admin/secrets/{name}/verify")
async def verify_stored_secret(
    name: str,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Check the key that is *currently loaded* still works.

    Useful for confirming a rotation landed, or diagnosing an agent that has
    started failing without anyone changing anything.
    """
    _require_managed(name)
    try:
        value = read_secret_raw(name)
    except Exception:
        value = None
    if not value:
        return {"ok": False, "message": "No key is configured."}
    ok, message = _validate(name, value)
    return {"ok": ok, "message": message}


@router.delete("/admin/secrets/{name}")
async def clear_secret(
    name: str,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Disable the current version, switching that agent off.

    Disable rather than destroy, so a mistake is recoverable from the GCP
    console. Inference keys are required — removing one takes its agent out of
    the switcher for everyone.
    """
    _require_managed(name)
    project = get_settings().GCP_PROJECT
    client = _sm_client()
    try:
        client.disable_secret_version(
            request={"name": f"projects/{project}/secrets/{name}/versions/latest"}
        )
    except gexc.NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No key is configured")
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not clear key: {e}")

    invalidate_secret_cache(name)
    _meta_doc().set({name: {"updated_at": now(), "updated_by": admin.email}}, merge=True)
    db().collection("audit").document().set({
        "type": "secret_cleared",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "secret": name,
        "created_at": now(),
    })
    return {"ok": True}
