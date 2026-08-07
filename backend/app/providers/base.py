"""Provider interface + shared helpers for translating the canonical format."""
from dataclasses import dataclass, field
from typing import Iterator, Protocol


@dataclass
class StreamChunk:
    """A piece of assistant text as it arrives."""
    text: str


@dataclass
class StreamDone:
    """End of a successful turn, with the vendor's own token accounting."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamError:
    """The turn failed. `retryable_without_tools` drives the no-tools retry."""
    message: str
    retryable_without_tools: bool = False


StreamEvent = StreamChunk | StreamDone | StreamError


@dataclass
class ChatRequestSpec:
    """Everything a provider needs for one turn, in canonical form."""
    model: str
    system_prompt: str
    history: list[dict]
    max_output_tokens: int
    use_web_tools: bool = True
    extra: dict = field(default_factory=dict)


class ChatProvider(Protocol):
    """Implemented once per vendor.

    `stream` must be a generator yielding StreamChunk/StreamDone/StreamError.
    It must not raise for ordinary API failures — yield StreamError instead, so
    chat.py can decide whether to retry without tools or surface the message.
    """

    name: str

    def stream(self, spec: ChatRequestSpec) -> Iterator[StreamEvent]:
        ...


# ---------------------- Canonical-format helpers ----------------------

def parse_data_url(url: str) -> tuple[str, str]:
    """Split a `data:<mime>;base64,<payload>` URL into (mime_type, base64_payload).

    The canonical format stores images and PDFs as data URLs because that is
    what the OpenAI Responses API wanted. Anthropic and Gemini both want the
    mime type and the raw base64 as separate fields, so every adapter but
    OpenAI's runs its attachment parts through this.
    """
    if not url.startswith("data:"):
        raise ValueError("Not a data URL")
    header, _, payload = url.partition(",")
    if not payload:
        raise ValueError("Malformed data URL: no payload")
    mime = header[len("data:"):].split(";")[0] or "application/octet-stream"
    return mime, payload


def iter_parts(content) -> list[dict]:
    """Normalise a canonical `content` value to a list of parts.

    A plain string becomes a single `input_text` part, so adapters only ever
    have to handle the list form.
    """
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if isinstance(content, list):
        return [p for p in content if isinstance(p, dict)]
    return []


def text_of(content) -> str:
    """Flatten a canonical `content` value down to its text, ignoring media.

    Used for roles that cannot carry attachments on a given provider (assistant
    turns everywhere, and any provider that rejects media in a given position).
    """
    return "\n".join(
        p.get("text", "")
        for p in iter_parts(content)
        if p.get("type") == "input_text" and p.get("text")
    ).strip()
