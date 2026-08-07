"""Multi-provider chat backends.

AWM Chat talks to three model vendors — Anthropic, OpenAI and Google — through
one interface. The rule that shapes this package: **the stored conversation
format never changes**. Firestore and the GCS archive keep exactly the shape
they had when the app was OpenAI-only (see `attachments.build_content_parts`),
and each provider adapter translates that canonical shape into its own wire
format at send time. Nothing is rewritten on disk, so all three agents read the
same history and conversations started on one agent continue on another.

Canonical message shape (what `chat._load_history` produces):

    {"role": "user" | "assistant", "content": "plain text"}
    {"role": "user", "content": [<part>, ...]}

    part = {"type": "input_text",  "text": str}
         | {"type": "input_image", "image_url": "data:<mime>;base64,<b64>"}
         | {"type": "input_file",  "filename": str, "file_data": "data:...;base64,<b64>"}

Adapters live in `openai_provider`, `anthropic_provider` and `gemini_provider`;
`registry` maps a model ID to the adapter that serves it.
"""
from .base import ChatProvider, StreamChunk, StreamDone, StreamError, parse_data_url
from .registry import (
    MODEL_CATALOG,
    PROVIDERS,
    default_model_for,
    get_provider,
    model_info,
    provider_for_model,
    seeded_available_models,
)

__all__ = [
    "ChatProvider",
    "StreamChunk",
    "StreamDone",
    "StreamError",
    "parse_data_url",
    "MODEL_CATALOG",
    "PROVIDERS",
    "default_model_for",
    "get_provider",
    "model_info",
    "provider_for_model",
    "seeded_available_models",
]
