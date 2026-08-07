"""Chat: dispatches to the selected agent, persists to Firestore + GCS, updates usage.

Three vendors are reachable from here (Claude, OpenAI, Gemini) but only one
storage format exists. Everything written to Firestore and the GCS archive is
in the canonical shape this app has always used; the chosen provider adapter
translates it on the way out. See `providers/__init__.py` for the format.
"""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .attachments import (
    build_content_parts,
    flag_scan_corpus,
    lightweight_attachment,
    load_attachments_full,
)
from .auth import AuthedUser, require_user
from .awm_context import AWM_CONTEXT, AWM_GUIDANCE
from .config import available_providers, get_settings
from .providers.base import ChatRequestSpec, StreamChunk, StreamDone, StreamError
from .providers.registry import (
    PROVIDER_LABELS,
    default_model_for,
    get_provider,
    model_info,
    provider_for_model,
)
from .storage import (
    append_to_archive,
    cap_for,
    db,
    get_global_settings,
    month_key,
    now,
    read_usage,
    record_usage,
)

router = APIRouter()


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] | None = None
    # Per-turn agent override from the in-chat switcher. Falls back to the
    # user's saved preference when absent, so older clients keep working.
    model: str | None = None


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


def firestore_desc():
    # Helper for import-friendly direction enum
    from google.cloud.firestore_v1 import Query
    return Query.DESCENDING


def _load_history(uid: str, conv_id: str) -> list[dict]:
    """Load recent messages in chronological order, in the canonical format.

    This is provider-agnostic on purpose — the same list is handed to whichever
    adapter is serving the turn, which is what lets a conversation continue
    across agents.
    """
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
            "content": build_content_parts(text, atts_full),
        })
    return history


def _resolve_model(requested: str | None, profile: dict, global_cfg: dict, settings) -> str:
    """Pick a model we can actually serve.

    Order of preference: the model chosen in the chat window, then the user's
    saved default, then the org default, then the built-in default. A candidate
    is only honoured if it is in the catalog, on the admin's allowlist, and
    backed by a configured API key — otherwise a stale or unlicensed choice
    would 500 mid-stream instead of falling back.
    """
    allowed = [m for m in (global_cfg.get("available_models") or []) if model_info(m)]
    usable_providers = set(available_providers())

    def ok(candidate) -> bool:
        if not isinstance(candidate, str) or not candidate:
            return False
        info = model_info(candidate)
        if not info or info["provider"] not in usable_providers:
            return False
        return candidate in allowed if allowed else True

    for candidate in (requested, profile.get("model"), global_cfg.get("default_model"),
                      settings.DEFAULT_MODEL):
        if ok(candidate):
            return candidate

    # Nothing configured is usable — fall back to any catalog model whose
    # vendor has a key, so the app degrades to "works" rather than "broken".
    for candidate in allowed:
        if ok(candidate):
            return candidate
    for provider in usable_providers:
        fallback = default_model_for(provider)
        if fallback:
            return fallback
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "No AI agent is currently configured. Contact your administrator.",
    )


def _alternatives_with_headroom(profile: dict, usage: dict, global_cfg: dict,
                                exclude_provider: str) -> list[dict]:
    """Agents the user could switch to that still have tokens left.

    This is what powers the out-of-tokens prompt: the client gets a concrete
    list rather than a dead end.
    """
    allowed = [m for m in (global_cfg.get("available_models") or []) if model_info(m)]
    usable = set(available_providers())
    out: list[dict] = []
    seen: set[str] = set()

    for model in allowed:
        info = model_info(model)
        provider = info["provider"]
        if provider == exclude_provider or provider not in usable or provider in seen:
            continue
        cap = cap_for(profile, provider)
        used = usage["by_provider"][provider]["tokens_used"]
        if cap and used >= cap:
            continue
        seen.add(provider)
        out.append({
            "model": model,
            "provider": provider,
            "provider_label": PROVIDER_LABELS.get(provider, provider),
            "label": info["label"],
            "tokens_used": used,
            "cap_tokens": cap,
            "tokens_remaining": max(0, cap - used) if cap else None,
        })
    return out


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

    model = _resolve_model(body.model, profile, global_cfg, settings)
    provider = provider_for_model(model)
    info = model_info(model) or {}

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

    # Usage cap check — per agent, so exhausting one leaves the others usable.
    mkey = month_key()
    usage = read_usage(user.uid, mkey)
    cap = cap_for(profile, provider)
    used = usage["by_provider"][provider]["tokens_used"]
    if cap and used >= cap:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {
                "error": "provider_cap_reached",
                "message": (
                    f"Your monthly token allowance for "
                    f"{PROVIDER_LABELS.get(provider, provider)} is used up."
                ),
                "provider": provider,
                "provider_label": PROVIDER_LABELS.get(provider, provider),
                "model": model,
                "alternatives": _alternatives_with_headroom(
                    profile, usage, global_cfg, exclude_provider=provider
                ),
            },
        )

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
    adapter = get_provider(provider)

    spec = ChatRequestSpec(
        model=model,
        system_prompt=system_prompt,
        history=history,
        # Per-model ceiling, because Claude models count thinking against
        # max_tokens and would truncate at the old flat 4096.
        max_output_tokens=info.get("max_output_tokens") or settings.MAX_OUTPUT_TOKENS,
        use_web_tools=True,
    )

    async def stream():
        assistant_text = ""
        input_tokens = 0
        output_tokens = 0
        streamed_any = False
        error_message = None

        # Announce which agent answered so the UI can label the message even if
        # the user switches agents before the reply lands.
        yield f"data: {json.dumps({'type': 'meta', 'model': model, 'provider': provider, 'provider_label': PROVIDER_LABELS.get(provider, provider)})}\n\n"

        # Try with the vendor's web-search tool first. If that fails *before*
        # any output is produced, retry once without it so the user still gets
        # a reply rather than a dead, silently-looping turn.
        for use_tools in (True, False):
            spec.use_web_tools = use_tools
            assistant_text = ""
            error_message = None
            retry = False

            for event in adapter.stream(spec):
                if isinstance(event, StreamChunk):
                    assistant_text += event.text
                    streamed_any = True
                    yield f"data: {json.dumps({'type': 'chunk', 'text': event.text})}\n\n"
                elif isinstance(event, StreamDone):
                    input_tokens = event.input_tokens
                    output_tokens = event.output_tokens
                elif isinstance(event, StreamError):
                    if use_tools and event.retryable_without_tools and not streamed_any:
                        retry = True
                    else:
                        error_message = event.message
                    break

            if not retry:
                break

        if error_message is not None:
            yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
            return

        # Persist assistant message. `model` and `provider` are additive fields;
        # readers that predate them ignore them.
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
            "model": model,
            "provider": provider,
        })

        append_to_archive(user.uid, body.conversation_id, {
            "role": "assistant",
            "content": assistant_text,
            "uid": user.uid,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "provider": provider,
        })

        record_usage(user.uid, provider, input_tokens, output_tokens, mkey)

        total_used = used + input_tokens + output_tokens
        yield (
            "data: "
            + json.dumps({
                "type": "done",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": model,
                "provider": provider,
                "tokens_used": total_used,
                "cap_tokens": cap,
                # Lets the client warn before the next turn is refused.
                "cap_reached": bool(cap and total_used >= cap),
            })
            + "\n\n"
        )

    return StreamingResponse(stream(), media_type="text/event-stream")
