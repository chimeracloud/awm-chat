"""Chat: streams from Anthropic, persists to Firestore + GCS, updates usage."""
import json
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .auth import AuthedUser, require_user
from .config import get_settings
from .storage import db, append_to_archive, month_key, now

router = APIRouter()


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


def _scan_for_flags(text: str) -> list[str]:
    s = text.lower()
    return [kw for kw in get_settings().FLAG_KEYWORDS if kw in s]


def _build_system_prompt(uid: str, profile: dict) -> str:
    pins_q = db().collection("pins").document(uid).collection("items").stream()
    pin_lines = []
    for p in pins_q:
        d = p.to_dict()
        label = d.get("label") or "Context"
        pin_lines.append(f"- [{label}] {d.get('content', '')}")

    base = (
        f"You are an internal assistant for Ascot Wealth Management, a UK financial advisory firm "
        f"established in 2010. You are speaking with {profile.get('display_name') or profile.get('email')}, "
        f"an AWM staff member. Be precise, professional, and useful. When uncertain, say so plainly. "
        f"Do not fabricate regulatory or compliance specifics. Today is {now().strftime('%Y-%m-%d')}.\n\n"
    )
    if pin_lines:
        base += "User pinned context (always consider):\n" + "\n".join(pin_lines) + "\n"
    return base


def _load_history(uid: str, conv_id: str) -> list[dict]:
    """Load recent messages in chronological order for the API call."""
    settings = get_settings()
    msgs_ref = (
        db()
        .collection("conversations")
        .document(conv_id)
        .collection("messages")
        .order_by("created_at", direction=firestore_desc())
        .limit(settings.CONTEXT_WINDOW_MESSAGES)
    )
    raw = list(msgs_ref.stream())
    # Verify conversation belongs to this user
    conv = db().collection("conversations").document(conv_id).get()
    if not conv.exists or conv.to_dict().get("owner_uid") != uid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    items = [m.to_dict() for m in raw]
    items.reverse()
    return [{"role": m["role"], "content": m["content"]} for m in items if m.get("content")]


def firestore_desc():
    # Helper for import-friendly direction enum
    from google.cloud.firestore_v1 import Query
    return Query.DESCENDING


@router.post("")
async def chat(
    body: ChatRequest,
    user: Annotated[AuthedUser, Depends(require_user)],
):
    settings = get_settings()
    profile_ref = db().collection("users").document(user.uid)
    profile = profile_ref.get().to_dict() or {}

    # Usage cap check
    mkey = month_key()
    usage_ref = db().collection("usage").document(user.uid).collection("months").document(mkey)
    usage_snap = usage_ref.get()
    used = (usage_snap.to_dict() or {}).get("tokens_used", 0) if usage_snap.exists else 0
    cap = profile.get("cap_tokens", settings.DEFAULT_CAP_TOKENS)
    if used >= cap:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Monthly token cap reached")

    # Persist user message
    user_msg_ref = (
        db()
        .collection("conversations")
        .document(body.conversation_id)
        .collection("messages")
        .document()
    )
    user_msg_ref.set({
        "role": "user",
        "content": body.message,
        "created_at": now(),
        "uid": user.uid,
    })

    # Touch conversation
    db().collection("conversations").document(body.conversation_id).update({
        "updated_at": now(),
    })

    # Flag check on the user message
    flags = _scan_for_flags(body.message)
    if flags:
        db().collection("audit").document().set({
            "type": "flag",
            "uid": user.uid,
            "email": user.email,
            "conversation_id": body.conversation_id,
            "message_id": user_msg_ref.id,
            "reason": ", ".join(flags),
            "snippet": body.message[:280],
            "created_at": now(),
        })

    archive_payload = {"role": "user", "content": body.message, "uid": user.uid}
    append_to_archive(user.uid, body.conversation_id, archive_payload)

    history = _load_history(user.uid, body.conversation_id)
    system_prompt = _build_system_prompt(user.uid, profile)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def stream():
        assistant_text = ""
        input_tokens = 0
        output_tokens = 0

        try:
            with client.messages.stream(
                model=settings.CLAUDE_MODEL,
                max_tokens=settings.MAX_OUTPUT_TOKENS,
                system=system_prompt,
                messages=history,
            ) as s:
                for event in s:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        delta = event.delta.text
                        assistant_text += delta
                        yield f"data: {json.dumps({'type': 'chunk', 'text': delta})}\n\n"
                final = s.get_final_message()
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Persist assistant message
        asst_ref = (
            db()
            .collection("conversations")
            .document(body.conversation_id)
            .collection("messages")
            .document()
        )
        asst_ref.set({
            "role": "assistant",
            "content": assistant_text,
            "created_at": now(),
            "uid": user.uid,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

        append_to_archive(user.uid, body.conversation_id, {
            "role": "assistant",
            "content": assistant_text,
            "uid": user.uid,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

        # Update usage counters
        total = input_tokens + output_tokens
        usage_ref.set({
            "tokens_used": (used + total),
            "input_tokens": (usage_snap.to_dict() or {}).get("input_tokens", 0) + input_tokens if usage_snap.exists else input_tokens,
            "output_tokens": (usage_snap.to_dict() or {}).get("output_tokens", 0) + output_tokens if usage_snap.exists else output_tokens,
            "requests": (usage_snap.to_dict() or {}).get("requests", 0) + 1 if usage_snap.exists else 1,
            "updated_at": now(),
        }, merge=True)

        yield f"data: {json.dumps({'type': 'done', 'input_tokens': input_tokens, 'output_tokens': output_tokens})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
