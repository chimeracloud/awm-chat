"""Chat: streams from Anthropic, persists to Firestore + GCS, updates usage."""
import json
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .attachments import (
    build_content_blocks,
    flag_scan_corpus,
    lightweight_attachment,
    load_attachments_full,
)
from .auth import AuthedUser, require_user
from .awm_context import AWM_CONTEXT, AWM_GUIDANCE, web_tools
from .config import get_settings
from .storage import db, append_to_archive, get_global_settings, month_key, now

router = APIRouter()


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] | None = None


def _scan_for_flags(text: str, keywords: list[str]) -> list[str]:
    s = text.lower()
    return [kw for kw in keywords if kw and kw in s]


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
    base += AWM_CONTEXT.strip() + "\n\n"
    base += AWM_GUIDANCE.strip() + "\n\n"
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

    history: list[dict] = []
    for m in items:
        att_refs = m.get("attachments") or []
        text = m.get("content") or ""
        if not text and not att_refs:
            continue
        if not att_refs:
            history.append({"role": m["role"], "content": text})
            continue
        ids = [a.get("id") for a in att_refs if a.get("id")]
        atts_full = load_attachments_full(uid, ids)
        history.append({
            "role": m["role"],
            "content": build_content_blocks(text, atts_full),
        })
    return history


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
    global_cfg = get_global_settings()
    profile_ref = db().collection("users").document(user.uid)
    profile = profile_ref.get().to_dict() or {}

    # Validate input — message must have text or at least one attachment
    if not body.message.strip() and not body.attachment_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty message")

    # Load any referenced attachments up front so we can validate and reuse
    attachments_full = load_attachments_full(user.uid, body.attachment_ids or [])
    if body.attachment_ids and len(attachments_full) != len(body.attachment_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "One or more attachments not found")
    for att in attachments_full:
        if att.get("status") != "ready":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Attachment {att.get('id')} is not ready (status: {att.get('status')})",
            )

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
        "attachments": [lightweight_attachment(a) for a in attachments_full],
        "created_at": now(),
        "uid": user.uid,
    })

    # Touch conversation
    db().collection("conversations").document(body.conversation_id).update({
        "updated_at": now(),
    })

    # Flag check across the user's text + any extracted document text / video transcripts
    flags = _scan_for_flags(
        flag_scan_corpus(body.message, attachments_full),
        global_cfg.get("flag_keywords") or settings.FLAG_KEYWORDS,
    )
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

    archive_payload = {
        "role": "user",
        "content": body.message,
        "uid": user.uid,
        "attachments": [lightweight_attachment(a) for a in attachments_full],
    }
    append_to_archive(user.uid, body.conversation_id, archive_payload)

    history = _load_history(user.uid, body.conversation_id)
    system_prompt = _build_system_prompt(user.uid, profile)
    model = profile.get("model") or global_cfg.get("default_model") or settings.CLAUDE_MODEL

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def stream():
        assistant_text = ""
        input_tokens = 0
        output_tokens = 0
        streamed_any = False
        error_message = None

        def open_stream(use_tools: bool):
            kwargs = dict(
                model=model,
                max_tokens=settings.MAX_OUTPUT_TOKENS,
                system=system_prompt,
                messages=history,
            )
            if use_tools:
                kwargs["tools"] = web_tools()
            return client.messages.stream(**kwargs)

        # Try with the server-side web tools first. If that fails *before* any
        # output is produced (e.g. the user's assigned model can't use the web
        # tools), retry once without them so the user still gets a reply rather
        # than a dead, silently-looping turn.
        for use_tools in (True, False):
            try:
                with open_stream(use_tools) as s:
                    for event in s:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            delta = event.delta.text
                            assistant_text += delta
                            streamed_any = True
                            yield f"data: {json.dumps({'type': 'chunk', 'text': delta})}\n\n"
                    final = s.get_final_message()
                    input_tokens = final.usage.input_tokens
                    output_tokens = final.usage.output_tokens
                error_message = None
                break
            except Exception as e:
                if use_tools and not streamed_any:
                    # Nothing was sent to the client yet — safe to retry cleanly.
                    assistant_text = ""
                    continue
                error_message = str(e)
                break

        if error_message is not None:
            yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
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
