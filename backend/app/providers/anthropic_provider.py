"""Anthropic (Claude) adapter.

Translates the canonical OpenAI-shaped history into Anthropic content blocks at
send time. Nothing is written back in this shape — the stored format is
unchanged, so a conversation can move between agents mid-thread.

Two behaviours worth knowing about:

* **Thinking stays on.** On Opus 5 / Sonnet 5 thinking is adaptive and enabled
  by default. Disabling it is tempting for latency, but with a web-search tool
  attached a thinking-disabled turn can emit the tool call as plain visible
  text — the call silently never runs and the user gets a reply that looks fine
  and did nothing. We keep thinking on and control spend with `effort` instead,
  which is why `max_output_tokens` for Claude models is set well above a normal
  answer length (`max_tokens` caps thinking + reply together).
* **Empty text blocks are rejected.** `build_content_parts` emits a single empty
  `input_text` when a message is attachment-only; Anthropic 400s on that, so
  empty blocks are dropped and a placeholder used if nothing survives.
"""
from typing import Iterator

from ..config import get_settings
from .base import (
    ChatProvider,
    ChatRequestSpec,
    StreamChunk,
    StreamDone,
    StreamError,
    StreamEvent,
    iter_parts,
    parse_data_url,
    text_of,
)
from .registry import ANTHROPIC, model_info

# Anthropic accepts these as image blocks; anything else is described in text
# rather than dropped silently, so the model knows something was attached.
_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _to_blocks(content, *, allow_media: bool) -> list[dict]:
    """Canonical content -> Anthropic content blocks."""
    blocks: list[dict] = []
    for part in iter_parts(content):
        ptype = part.get("type")

        if ptype == "input_text":
            text = part.get("text") or ""
            if text.strip():
                blocks.append({"type": "text", "text": text})

        elif ptype == "input_image" and allow_media:
            try:
                mime, data = parse_data_url(part.get("image_url", ""))
            except ValueError:
                continue
            if mime in _IMAGE_MIMES:
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": data},
                })
            else:
                blocks.append({
                    "type": "text",
                    "text": f"[Attached image in unsupported format {mime}.]",
                })

        elif ptype == "input_file" and allow_media:
            filename = part.get("filename") or "attachment"
            try:
                mime, data = parse_data_url(part.get("file_data", ""))
            except ValueError:
                continue
            if mime == "application/pdf":
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": mime, "data": data},
                    "title": filename,
                })
            else:
                blocks.append({
                    "type": "text",
                    "text": f"[Attached file {filename} ({mime}) could not be read by this agent.]",
                })

    if not blocks:
        blocks = [{"type": "text", "text": "(no content)"}]
    return blocks


def _to_messages(history: list[dict]) -> list[dict]:
    """Canonical history -> Anthropic `messages`.

    Anthropic requires the first message to be `user` and rejects empty
    content, so leading assistant turns are dropped and empties skipped.
    Consecutive same-role turns are legal and left alone.
    """
    out: list[dict] = []
    for msg in history:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        # Media is only valid on user turns.
        blocks = _to_blocks(msg.get("content"), allow_media=(role == "user"))
        if role == "assistant":
            text = text_of(msg.get("content"))
            if not text:
                continue
            blocks = [{"type": "text", "text": text}]
        if not out and role == "assistant":
            continue  # conversation must open on a user turn
        out.append({"role": role, "content": blocks})
    return out


class AnthropicProvider(ChatProvider):
    name = ANTHROPIC

    def _client(self):
        import anthropic
        return anthropic.Anthropic(api_key=get_settings().api_key_for(ANTHROPIC))

    def stream(self, spec: ChatRequestSpec) -> Iterator[StreamEvent]:
        client = self._client()
        info = model_info(spec.model) or {}

        messages = _to_messages(spec.history)
        if not messages:
            yield StreamError("No usable conversation history for this agent.")
            return

        # Anthropic caches explicitly. The breakpoint goes on the stable half
        # of the system prompt, which is byte-identical for every user in the
        # firm — so the first request of the day warms it and everyone else
        # reads it back at a fraction of the price. The volatile half follows
        # it uncached; it is small, and keeping it outside the breakpoint is
        # what stops the daily date change invalidating the whole prefix.
        system: list[dict] = [{
            "type": "text",
            "text": spec.system_stable,
            "cache_control": {"type": "ephemeral"},
        }]
        volatile = spec.system_volatile.strip()
        if volatile:
            system.append({"type": "text", "text": volatile})

        # Second breakpoint at the end of the settled history. The newest
        # message is left outside it deliberately: attachments on the newest
        # turn are sent natively and switch to their text layer once they are
        # no longer newest, so including it would invalidate the prefix on the
        # very next turn.
        if len(messages) >= 2:
            tail = messages[-2]["content"]
            if isinstance(tail, list) and tail:
                tail[-1] = {**tail[-1], "cache_control": {"type": "ephemeral"}}

        kwargs: dict = {
            "model": spec.model,
            "max_tokens": spec.max_output_tokens,
            "system": system,
            "messages": messages,
        }
        if info.get("adaptive_thinking"):
            kwargs["thinking"] = {"type": "adaptive"}
        if info.get("supports_effort"):
            kwargs["output_config"] = {"effort": info.get("effort", "medium")}
        if spec.use_web_tools and info.get("web_search_tool"):
            kwargs["tools"] = [{"type": info["web_search_tool"], "name": "web_search"}]

        streamed_any = False
        input_tokens = output_tokens = 0
        cache_read = cache_write = 0

        try:
            with client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    if text:
                        streamed_any = True
                        yield StreamChunk(text)
                final = stream.get_final_message()

            usage = getattr(final, "usage", None)
            if usage is not None:
                # Cache reads/writes are billed differently but still consume
                # the user's allowance, so fold them into the input count.
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
                input_tokens = (usage.input_tokens or 0) + cache_read + cache_write
                output_tokens = usage.output_tokens or 0

            if getattr(final, "stop_reason", None) == "refusal":
                details = getattr(final, "stop_details", None)
                category = getattr(details, "category", None)
                yield StreamError(
                    "Claude declined this request"
                    + (f" ({category})" if category else "")
                    + ". Try rephrasing, or switch to a different agent."
                )
                return
        except Exception as e:
            yield StreamError(str(e), retryable_without_tools=not streamed_any)
            return

        yield StreamDone(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
