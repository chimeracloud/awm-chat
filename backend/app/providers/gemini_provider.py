"""Google Gemini adapter (google-genai SDK).

Translates the canonical OpenAI-shaped history into Gemini `contents` at send
time. As with the Anthropic adapter, nothing is written back in this shape.

Gemini differences worth noting:
* the assistant role is called `model`
* the system prompt is config, not a message
* attachments are `inline_data` with raw base64, and PDFs are natively readable
"""
import base64
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
from .registry import GOOGLE

_INLINE_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/gif",
    "application/pdf",
}


def _to_parts(content, *, allow_media: bool) -> list[dict]:
    parts: list[dict] = []
    for part in iter_parts(content):
        ptype = part.get("type")

        if ptype == "input_text":
            text = part.get("text") or ""
            if text.strip():
                parts.append({"text": text})

        elif ptype in ("input_image", "input_file") and allow_media:
            url = part.get("image_url") if ptype == "input_image" else part.get("file_data")
            try:
                mime, data = parse_data_url(url or "")
            except ValueError:
                continue
            if mime in _INLINE_MIMES:
                # google-genai wants raw bytes for inline_data, not base64 text.
                parts.append({
                    "inline_data": {"mime_type": mime, "data": base64.b64decode(data)},
                })
            else:
                name = part.get("filename") or "attachment"
                parts.append({
                    "text": f"[Attached file {name} ({mime}) could not be read by this agent.]"
                })

    if not parts:
        parts = [{"text": "(no content)"}]
    return parts


def _to_contents(history: list[dict]) -> list[dict]:
    out: list[dict] = []
    for msg in history:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        if role == "assistant":
            text = text_of(msg.get("content"))
            if not text:
                continue
            out.append({"role": "model", "parts": [{"text": text}]})
        else:
            out.append({"role": "user", "parts": _to_parts(msg.get("content"), allow_media=True)})
    return out


class GeminiProvider(ChatProvider):
    name = GOOGLE

    def _client(self):
        from google import genai
        return genai.Client(api_key=get_settings().api_key_for(GOOGLE))

    def stream(self, spec: ChatRequestSpec) -> Iterator[StreamEvent]:
        from google.genai import types

        client = self._client()
        contents = _to_contents(spec.history)
        if not contents:
            yield StreamError("No usable conversation history for this agent.")
            return

        config_kwargs: dict = {
            "system_instruction": spec.system_prompt,
            "max_output_tokens": spec.max_output_tokens,
        }
        if spec.use_web_tools:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

        streamed_any = False
        input_tokens = output_tokens = 0

        try:
            stream = client.models.generate_content_stream(
                model=spec.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    streamed_any = True
                    yield StreamChunk(text)
                # Usage arrives on the final chunk; keep the last non-empty read.
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None:
                    input_tokens = getattr(usage, "prompt_token_count", 0) or input_tokens
                    output_tokens = (
                        getattr(usage, "candidates_token_count", 0) or output_tokens
                    )
        except Exception as e:
            yield StreamError(str(e), retryable_without_tools=not streamed_any)
            return

        yield StreamDone(input_tokens=input_tokens, output_tokens=output_tokens)
