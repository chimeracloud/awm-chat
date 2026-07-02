"""All non-chat REST endpoints in one module for compactness."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .auth import AuthedUser, require_user, require_admin
from .config import get_settings
from .storage import db, get_global_settings, month_key, now

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
    profile = db().collection("users").document(user.uid).get().to_dict() or {}
    snap = db().collection("usage").document(user.uid).collection("months").document(month_key()).get()
    used = (snap.to_dict() or {}).get("tokens_used", 0) if snap.exists else 0
    return {
        "month": month_key(),
        "tokens_used": used,
        "cap_tokens": profile.get("cap_tokens", get_settings().DEFAULT_CAP_TOKENS),
    }


# --- Admin -----------------------------------------------------------------


@router.get("/admin/users")
async def admin_list_users(admin: Annotated[AuthedUser, Depends(require_admin)]):
    items = []
    for u in db().collection("users").stream():
        d = u.to_dict()
        usage_snap = (
            db().collection("usage").document(u.id).collection("months").document(month_key()).get()
        )
        used = (usage_snap.to_dict() or {}).get("tokens_used", 0) if usage_snap.exists else 0
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
            "tokens_used": used,
            "conversation_count": conv_count,
        })
    items.sort(key=lambda x: x["tokens_used"], reverse=True)
    return {"items": items}


class UserUpdate(BaseModel):
    cap_tokens: int | None = None
    role: str | None = None
    model: str | None = None


@router.put("/admin/users/{uid}")
async def admin_update_user(
    uid: str,
    body: UserUpdate,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    patch = {}
    if body.cap_tokens is not None: patch["cap_tokens"] = body.cap_tokens
    if body.role is not None: patch["role"] = body.role
    if body.model is not None: patch["model"] = body.model
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
    """Clear this month's consumption counters for a single user."""
    mkey = month_key()
    ref = db().collection("usage").document(uid).collection("months").document(mkey)
    ref.set({"tokens_used": 0, "input_tokens": 0, "output_tokens": 0, "requests": 0})
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
    for u in db().collection("users").stream():
        snap = db().collection("usage").document(u.id).collection("months").document(mkey).get()
        if snap.exists:
            used = snap.to_dict().get("tokens_used", 0)
            total_tokens += used
            if used > 0:
                active_users += 1
    total_conversations = sum(1 for _ in db().collection("conversations").stream())
    # Sonnet rough pricing for estimation: $3/M input, $15/M output ... split assumption 1:3
    estimated_spend = (total_tokens / 4) / 1_000_000 * 3 + (3 * total_tokens / 4) / 1_000_000 * 15
    return {
        "month": mkey,
        "tokens_this_month": total_tokens,
        "active_users": active_users,
        "total_conversations": total_conversations,
        "estimated_spend_usd": estimated_spend,
    }


@router.post("/admin/usage/reset")
async def admin_reset_usage(admin: Annotated[AuthedUser, Depends(require_admin)]):
    """Clear this month's consumption counters for every user."""
    mkey = month_key()
    cleared = 0
    for u in db().collection("users").stream():
        ref = db().collection("usage").document(u.id).collection("months").document(mkey)
        if ref.get().exists:
            ref.set({"tokens_used": 0, "input_tokens": 0, "output_tokens": 0, "requests": 0})
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


@router.get("/admin/settings")
async def admin_get_settings(admin: Annotated[AuthedUser, Depends(require_admin)]):
    return get_global_settings()


@router.put("/admin/settings")
async def admin_update_settings(
    body: SettingsUpdate,
    admin: Annotated[AuthedUser, Depends(require_admin)],
):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if patch:
        db().collection("settings").document("global").set(patch, merge=True)
        db().collection("audit").document().set({
            "type": "settings_update",
            "admin_uid": admin.uid,
            "admin_email": admin.email,
            "patch": patch,
            "created_at": now(),
        })
    return get_global_settings()
