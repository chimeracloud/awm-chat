"""OpenAI adapter (Responses API).

The canonical stored format *is* the OpenAI Responses `input` format, so this
adapter passes history through untouched. That is deliberate: it keeps the
provider that shaped the stored data on a zero-translation path, and makes the
other two adapters the only places where a translation bug can live.
"""
from typing import Iterator

from ..config import get_settings
from .base import ChatProvider, ChatRequestSpec, StreamChunk, StreamDone, StreamError, StreamEvent
from .registry import OPENAI


class OpenAIProvider(ChatProvider):
    name = OPENAI

    def _client(self):
        from openai import OpenAI
        return OpenAI(api_key=get_settings().api_key_for(OPENAI))

    def stream(self, spec: ChatRequestSpec) -> Iterator[StreamEvent]:
        client = self._client()

        kwargs = dict(
            model=spec.model,
            instructions=spec.system_prompt,
            input=spec.history,          # already in Responses format
            max_output_tokens=spec.max_output_tokens,
            stream=True,
        )
        if spec.use_web_tools:
            kwargs["tools"] = [{"type": "web_search"}]

        streamed_any = False
        input_tokens = output_tokens = 0

        try:
            for event in client.responses.create(**kwargs):
                etype = getattr(event, "type", "")
                if etype == "response.output_text.delta":
                    streamed_any = True
                    yield StreamChunk(event.delta)
                elif etype == "response.completed":
                    usage = getattr(event.response, "usage", None)
                    if usage is not None:
                        input_tokens = usage.input_tokens or 0
                        output_tokens = usage.output_tokens or 0
                elif etype in ("response.failed", "error"):
                    resp = getattr(event, "response", None)
                    err = getattr(resp, "error", None) or getattr(event, "message", None)
                    raise RuntimeError(
                        getattr(err, "message", None) or str(err) or "response failed"
                    )
        except Exception as e:
            yield StreamError(str(e), retryable_without_tools=not streamed_any)
            return

        yield StreamDone(input_tokens=input_tokens, output_tokens=output_tokens)
