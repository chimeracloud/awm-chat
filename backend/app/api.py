"""All non-chat REST endpoints in one module for compactness."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .auth import AuthedUser, require_user, require_admin
from .config import available_providers, get_settings
from .credits import all_provider_spend, invalidate_spend_cache
from .providers.registry import MODEL_CATALOG, PROVIDER_LABELS, PROVIDERS, model_info
from .storage import (
    cap_for,
    db,
    get_global_settings,
    month_key,
    now,
    read_usage,
    reset_usage,
)

router = APIRouter()


# --- Profile ---------------------------------------------------------------


@router.get("/me")
async def get_me(user: Annotated[AuthedUser, Depends(require_user)]):
    ref = db().collection("users").document(user.uid)
    snap = ref.get()
    settings = get_settings()
    if not snap.exists:
        # First sign-in ... create profile from global defaults
        cfg = get_global_settings()
        profile = {
            "uid": user.uid,
            "email": user.email,
            "display_name": user.name,
            "photo_url": user.picture,
            "role": "user",
            "cap_tokens": cfg.get("default_cap_tokens", settings.DEFAULT_CAP_TOKENS),
            "model": cfg.get("default_model"),
            "ack_accepted": False,
            "created_at": now(),
        }
        ref.set(profile)
        return profile
    return snap.to_dict()


class AckBody(BaseModel):
    accepted: bool


@router.post("/me/acknowledge")
async def acknowledge(body: AckBody, user: Annotated[AuthedUser, Depends(require_user)]):
    ref = db().collection("users").document(user.uid)
    ref.update({
        "ack_accepted": body.accepted,
        "ack_accepted_at": now(),
    })
    db().collection("audit").document().set({
        "type": "ack",
        "uid": user.uid,
        "email": user.email,
        "accepted": body.accepted,
        "created_at": now(),
    })
    return ref.get().to_dict()


# --- Self-service data export ----------------------------------------------


@router.get("/export/me")
async def export_me(user: Annotated[AuthedUser, Depends(require_user)]):
    """Let a signed-in user download all of their own data as a zip."""
    from fastapi.responses import Response
    from .export import build_user_export_zip

    zip_bytes, summary = build_user_export_zip(user.uid)
    label = (user.email or "me").split("@")[0].replace(".", "_")
    db().collection("audit").document().set({
        "type": "self_export",
        "uid": user.uid,
        "email": user.email,
        "summary": summary,
        "created_at": now(),
    })
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{label}_awm_chat_export.zip"'},
    )


# --- Conversations ---------------------------------------------------------


class NewConvBody(BaseModel):
    title: str | None = None


@router.get("/conversations")
async def list_conversations(user: Annotated[AuthedUser, Depends(require_user)]):
    from google.cloud.firestore_v1 import Query
    q = (
        db()
        .collection("conversations")
        .where("owner_uid", "==", user.uid)
        .where("archived", "==", False)
        .order_by("updated_at", direction=Query.DESCENDING)
        .limit(100)
    )
    items = []
    for s in q.stream():
        d = s.to_dict()
        items.append({
            "id": s.id,
            "title": d.get("title"),
            "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
            "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
        })
    return {"items": items}


@router.post("/conversations")
async def create_conversation(body: NewConvBody, user: Annotated[AuthedUser, Depends(require_user)]):
    ref = db().collection("conversations").document()
    payload = {
        "owner_uid": user.uid,
        "title": body.title or "New conversation",
        "created_at": now(),
        "updated_at": now(),
        "archived": False,
    }
    ref.set(payload)
    return {"id": ref.id, **{k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in payload.items()}}


@router.get("/conversations/{conv_id}/messages")
async def list_messages(conv_id: str, user: Annotated[AuthedUser, Depends(require_user)]):
    conv = db().collection("conversations").document(conv_id).get()
    if not conv.exists or conv.to_dict().get("owner_uid") != user.uid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    from google.cloud.firestore_v1 import Query
    q = (
        db()
        .collection("conversations")
        .document(conv_id)
        .collection("messages")
        .order_by("created_at", direction=Query.ASCENDING)
        .limit(500)
    )
    items = []
    for s in q.stream():
        d = s.to_dict()
        items.append({
            "id": s.id,
            "role": d.get("role"),
            "content": d.get("content"),
            "attachments": d.get("attachments"),
            "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
            "input_tokens": d.get("input_tokens"),
            "output_tokens": d.get("output_tokens"),
            # Absent on messages written before multi-agent support; the UI
            # simply omits the byline for those.
            "model": d.get("model"),
            "provider": d.get("provider"),
        })
    return {"items": items}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: Annotated[AuthedUser, Depends(require_user)]):
    conv_ref = db().collection("conversations").document(conv_id)
    conv = conv_ref.get()
    if not conv.exists or conv.to_dict().get("owner_uid") != user.uid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    # Soft delete: archive flag. Hard delete handled by retention job.
    conv_ref.update({"archived": True, "archived_at": now()})
    return {"ok": True}


# --- Pinned context --------------------------------------------------------


class PinBody(BaseModel):
    content: str
    label: str | None = None


@router.get("/pins")
async def list_pins(user: Annotated[AuthedUser, Depends(require_user)]):
    q = db().collection("pins").document(user.uid).collection("items").order_by("created_at").stream()
    items = []
    for s in q:
        d = s.to_dict()
        items.append({
            "id": s.id,
            "label": d.get("label"),
            "content": d.get("content"),
            "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        })
    return {"items": items}


@router.post("/pins")
async def add_pin(body: PinBody, user: Annotated[AuthedUser, Depends(require_user)]):
    ref = db().collection("pins").document(user.uid).collection("items").document()
    ref.set({
        "label": body.label,
        "content": body.content,
        "created_at": now(),
    })
    return {"ok": True, "id": ref.id}


@router.delete("/pins/{pin_id}")
async def delete_pin(pin_id: str, user: Annotated[AuthedUser, Depends(require_user)]):
    db().collection("pins").document(user.uid).collection("items").document(pin_id).delete()
    return {"ok": True}


# --- Usage -----------------------------------------------------------------


@router.get("/usage/me")
async def my_usage(user: Annotated[AuthedUser, Depends(require_user)]):
    """Aggregate usage. Kept for backwards compatibility with older clients —
    `/agents` is what the multi-agent UI reads."""
    profile = db().collection("users").document(user.uid).get().to_dict() or {}
    usage = read_usage(user.uid)
    return {
        "month": month_key(),
        "tokens_used": usage["tokens_used"],
        "cap_tokens": profile.get("cap_tokens", get_settings().DEFAULT_CAP_TOKENS),
    }


# --- Agents (model switcher + battery indicators) ---------------------------


@router.get("/agents")
async def list_agents(user: Annotated[AuthedUser, Depends(require_user)]):
    """Everything the chat window needs to render the switcher and batteries.

    Two layers per agent, because no vendor publishes a remaining-credit
    balance (verified for Anthropic, OpenAI and Google — see `credits.py`):

    * `allowance` — this user's own monthly token pool for that agent. Exact,
      live, and the thing that actually gates them. This drives the battery.
    * `org_spend` — month-to-date spend from the vendor's cost API against a
      budget set in config. Best-effort and org-wide; absent when no admin key
      or budget is configured, in which case the UI omits the marker.
    """
    profile = db().collection("users").document(user.uid).get().to_dict() or {}
    cfg = get_global_settings()
    usage = read_usage(user.uid)
    spend = all_provider_spend()
    usable = set(available_providers())

    allowed = [m for m in (cfg.get("available_models") or []) if model_info(m)]
    if not allowed:
        allowed = list(MODEL_CATALOG)

    agents = []
    for provider in PROVIDERS:
        models = [
            {
                "id": m,
                "label": MODEL_CATALOG[m]["label"],
                "blurb": MODEL_CATALOG[m].get("blurb", ""),
            }
            for m in allowed
            if MODEL_CATALOG[m]["provider"] == provider
        ]
        if not models:
            continue

        cap = cap_for(profile, provider)
        used = usage["by_provider"][provider]["tokens_used"]
        configured = provider in usable

        agents.append({
            "provider": provider,
            "label": PROVIDER_LABELS[provider],
            "available": configured,
            "unavailable_reason": None if configured else "No API key configured",
            "models": models,
            "allowance": {
                "tokens_used": used,
                "cap_tokens": cap,
                "tokens_remaining": max(0, cap - used) if cap else None,
                "fraction_used": min(1.0, used / cap) if cap else None,
                "exhausted": bool(cap and used >= cap),
            },
            "org_spend": spend.get(provider, {"available": False}),
        })

    return {
        "month": month_key(),
        "agents": agents,
        "selected_model": profile.get("model") or cfg.get("default_model"),
    }


class ModelPreference(BaseModel):
    model: str


@router.put("/me/model")
async def set_my_model(
    body: ModelPreference,
    user: Annotated[AuthedUser, Depends(require_user)],
):
    """Remember the agent picked in the chat window as this user's default."""
    if not model_info(body.model):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown model: {body.model}")
    cfg = get_global_settings()
    allowed = cfg.get("available_models") or []
    if allowed and body.model not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That agent is not enabled for your organisation")
    db().collection("users").document(user.uid).update({"model": body.model})
    return {"ok": True, "model": body.model}


# --- Admin -----------------------------------------------------------------


@router.get("/admin/users")
async def admin_list_users(admin: Annotated[AuthedUser, Depends(require_admin)]):
    items = []
    for u in db().collection("users").stream():
        d = u.to_dict()
        usage = read_usage(u.id)
        # Count conversations
        conv_count = 0
        for _ in db().collection("conversations").where("owner_uid", "==", u.id).where("archived", "==", False).stream():
            conv_count += 1
        items.append({
            "uid": u.id,
            "email": d.get("email"),
            "display_name": d.get("display_name"),
            "role": d.get("role", "user"),
            "model": d.get("model"),
            "cap_tokens": d.get("cap_tokens", get_settings().DEFAULT_CAP_TOKENS),
            "caps_by_provider": {p: cap_for(d, p) for p in PROVIDERS},
            "tokens_used": usage["tokens_used"],
            "tokens_by_provider": {
                p: usage["by_provider"][p]["tokens_used"] for p in PROVIDERS
            },
            "conversation_count": conv_count,
        })
    items.sort(key=lambda x: x["tokens_used"], reverse=True)
    return {"items": items}


class UserUpdate(BaseModel):
    cap_tokens: int | None = None
    role: str | None = None
    model: str | None = None
    # Per-agent allowances, e.g. {"anthropic": 500000, "openai": 250000}.
    # Any agent left out falls back to `cap_tokens`.
    caps_by_provider: dict[str, int] | None = None


@router.put("/admin/users/{uid}")
async def admin_update_user(
    uid: str,
    body: UserUpdate,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    patch = {}
    if body.cap_tokens is not None: patch["cap_tokens"] = body.cap_tokens
    if body.role is not None: patch["role"] = body.role
    if body.model is not None:
        if not model_info(body.model):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown model: {body.model}")
        patch["model"] = body.model
    if body.caps_by_provider is not None:
        unknown = set(body.caps_by_provider) - set(PROVIDERS)
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Unknown provider(s): {', '.join(sorted(unknown))}"
            )
        patch["caps_by_provider"] = body.caps_by_provider
    if not patch:
        return {"ok": True}
    db().collection("users").document(uid).update(patch)
    db().collection("audit").document().set({
        "type": "admin_update",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "target_uid": uid,
        "patch": patch,
        "created_at": now(),
    })
    return {"ok": True}


@router.get("/admin/users/{uid}/export")
async def admin_export_user(
    uid: str,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Download one user's full data (conversations, pins, attachments) as a zip."""
    from fastapi.responses import Response
    from .export import build_user_export_zip

    snap = db().collection("users").document(uid).get()
    if not snap.exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    zip_bytes, summary = build_user_export_zip(uid)
    email = (snap.to_dict() or {}).get("email") or uid
    label = email.split("@")[0].replace(".", "_")

    db().collection("audit").document().set({
        "type": "user_export",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "target_uid": uid,
        "summary": summary,
        "created_at": now(),
    })

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{label}_awm_chat_export.zip"'},
    )


@router.post("/admin/users/{uid}/usage/reset")
async def admin_reset_user_usage(
    uid: str,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    """Clear this month's consumption counters for a single user, all agents."""
    mkey = month_key()
    reset_usage(uid, mkey)
    db().collection("audit").document().set({
        "type": "usage_reset",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "target_uid": uid,
        "month": mkey,
        "created_at": now(),
    })
    return {"ok": True, "uid": uid, "month": mkey}


@router.get("/admin/metrics")
async def admin_metrics(admin: Annotated[AuthedUser, Depends(require_admin)]):
    mkey = month_key()
    total_tokens = 0
    active_users = 0
    tokens_by_provider = {p: 0 for p in PROVIDERS}
    for u in db().collection("users").stream():
        usage = read_usage(u.id, mkey)
        used = usage["tokens_used"]
        total_tokens += used
        for p in PROVIDERS:
            tokens_by_provider[p] += usage["by_provider"][p]["tokens_used"]
        if used > 0:
            active_users += 1
    total_conversations = sum(1 for _ in db().collection("conversations").stream())

    # Actual billed spend from each vendor's cost API, where configured. This
    # replaces the old single-model token estimate, which was meaningless once
    # three vendors with different rates were in play.
    spend = all_provider_spend()
    billed = [s["spend_usd"] for s in spend.values() if s.get("available")]

    return {
        "month": mkey,
        "tokens_this_month": total_tokens,
        "tokens_by_provider": tokens_by_provider,
        "active_users": active_users,
        "total_conversations": total_conversations,
        "provider_spend": spend,
        "billed_spend_usd": round(sum(billed), 2) if billed else None,
    }


@router.get("/admin/providers")
async def admin_providers(admin: Annotated[AuthedUser, Depends(require_admin)]):
    """Which agents are configured, and what each vendor's cost API reports.

    `org_spend.available: false` is expected and harmless — it means no admin
    key or budget is set for that vendor, and the UI just hides the marker.
    """
    usable = set(available_providers())
    spend = all_provider_spend()
    return {
        "providers": [
            {
                "provider": p,
                "label": PROVIDER_LABELS[p],
                "key_configured": p in usable,
                "models": [m for m, i in MODEL_CATALOG.items() if i["provider"] == p],
                "org_spend": spend.get(p, {"available": False}),
            }
            for p in PROVIDERS
        ]
    }


@router.post("/admin/usage/reset")
async def admin_reset_usage(admin: Annotated[AuthedUser, Depends(require_admin)]):
    """Clear this month's consumption counters for every user."""
    mkey = month_key()
    cleared = 0
    for u in db().collection("users").stream():
        ref = db().collection("usage").document(u.id).collection("months").document(mkey)
        if ref.get().exists:
            reset_usage(u.id, mkey)
            cleared += 1
    db().collection("audit").document().set({
        "type": "usage_reset",
        "admin_uid": admin.uid,
        "admin_email": admin.email,
        "month": mkey,
        "users_cleared": cleared,
        "created_at": now(),
    })
    return {"ok": True, "users_cleared": cleared, "month": mkey}


@router.get("/admin/flags")
async def admin_flags(admin: Annotated[AuthedUser, Depends(require_admin)]):
    from google.cloud.firestore_v1 import Query
    q = (
        db()
        .collection("audit")
        .where("type", "==", "flag")
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(100)
    )
    items = []
    for s in q.stream():
        d = s.to_dict()
        items.append({
            "id": s.id,
            "user_email": d.get("email"),
            "reason": d.get("reason"),
            "snippet": d.get("snippet"),
            "conversation_id": d.get("conversation_id"),
            "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        })
    return {"items": items}


# --- Admin settings --------------------------------------------------------


class SettingsUpdate(BaseModel):
    default_model: str | None = None
    available_models: list[str] | None = None
    default_cap_tokens: int | None = None
    flag_keywords: list[str] | None = None
    # Non-secret agent config, editable in the admin Settings page. API keys are
    # deliberately not here — those go to Secret Manager via /admin/secrets.
    provider_budgets_usd: dict[str, float] | None = None
    gcp_billing_export_table: str | None = None


@router.get("/admin/settings")
async def admin_get_settings(admin: Annotated[AuthedUser, Depends(require_admin)]):
    return get_global_settings()


@router.put("/admin/settings")
async def admin_update_settings(
    body: SettingsUpdate,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}

    if "provider_budgets_usd" in patch:
        unknown = set(patch["provider_budgets_usd"]) - set(PROVIDERS)
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown provider(s): {', '.join(sorted(unknown))}",
            )
    if "available_models" in patch:
        bad = [m for m in patch["available_models"] if not model_info(m)]
        if bad:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Unknown model(s): {', '.join(bad)}"
            )

    if patch:
        db().collection("settings").document("global").set(patch, merge=True)
        # Budgets feed the cached spend markers — drop the cache so a changed
        # budget is reflected immediately rather than up to 5 minutes later.
        if "provider_budgets_usd" in patch or "gcp_billing_export_table" in patch:
            invalidate_spend_cache()
        db().collection("audit").document().set({
            "type": "settings_update",
            "admin_uid": admin.uid,
            "admin_email": admin.email,
            "patch": patch,
            "created_at": now(),
        })
    return get_global_settings()
