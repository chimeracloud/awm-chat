#!/usr/bin/env python3
"""Regression checks for the behaviour that is easiest to break silently.

No pytest dependency and no network — everything here is pure translation and
arithmetic against stubbed clients, so it runs anywhere the app imports:

    GCP_PROJECT=chiops PYTHONPATH=backend python backend/tests/test_regression.py

Each check guards something that has actually gone wrong, or that would fail
invisibly if it regressed: a wrong translation reaches a vendor as a 400 mid
conversation, a broken token budget reappears as a rate-limit error for one
unlucky user, and a busted cache prefix just quietly costs more money.
"""
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GCP_PROJECT", "test")

PASS, FAIL = [], []


def check(name):
    def wrap(fn):
        try:
            fn()
            PASS.append(name)
            print(f"  PASS  {name}")
        except Exception as e:
            FAIL.append((name, e))
            print(f"  FAIL  {name} — {type(e).__name__}: {e}")
        return fn
    return wrap


PNG = base64.standard_b64encode(b"\x89PNG fake").decode()
PDF = base64.standard_b64encode(b"%PDF fake").decode()

import app.attachments as A  # noqa: E402
A.archive_bucket = lambda: type("B", (), {
    "blob": lambda s, p: type("Bl", (), {"download_as_bytes": lambda s: b"%PDF fake"})()
})()

from app.attachments import MAX_EXTRACTED_CHARS, build_content_parts, _truncate  # noqa: E402
from app.providers.anthropic_provider import _to_messages  # noqa: E402
from app.providers.gemini_provider import _to_contents  # noqa: E402
from app.providers.registry import ANTHROPIC, GOOGLE, OPENAI  # noqa: E402

CANONICAL = [
    {"role": "user", "content": "What are our fees?"},
    {"role": "assistant", "content": "0.5-1% p.a."},
    {"role": "user", "content": [
        {"type": "input_file", "filename": "r.pdf", "file_data": f"data:application/pdf;base64,{PDF}"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{PNG}", "detail": "auto"},
        {"type": "input_text", "text": "Summarise."},
    ]},
]


# ---------------------------------------------------------------- translation

@check("Anthropic: canonical parts map to document/image/text blocks")
def _():
    out = _to_messages(CANONICAL)
    assert [b["type"] for b in out[2]["content"]] == ["document", "image", "text"], out[2]
    assert out[0]["role"] == "user"


@check("Gemini: assistant becomes 'model' and media becomes raw inline bytes")
def _():
    out = _to_contents(CANONICAL)
    assert out[1]["role"] == "model", out[1]
    parts = out[2]["parts"]
    assert parts[0]["inline_data"]["data"] == base64.b64decode(PDF), "needs bytes, not base64 text"


@check("Anthropic: empty content is replaced (the API 400s on empty blocks)")
def _():
    out = _to_messages([{"role": "user", "content": [{"type": "input_text", "text": ""}]}])
    assert out[0]["content"] == [{"type": "text", "text": "(no content)"}], out


@check("Anthropic: a leading assistant turn is dropped (must open on a user turn)")
def _():
    out = _to_messages([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "yo"}])
    assert out[0]["role"] == "user", out


# ------------------------------------------------------------------ fidelity

ATT = [{"id": "a", "content_type": "application/pdf", "filename": "r.pdf",
        "gcs_path": "x", "extracted_text": "THE TEXT"}]


@check("PDF fidelity: newest turn native, older turns text")
def _():
    assert build_content_parts("q", ATT, native=True)[0]["type"] == "input_file"
    part = build_content_parts("q", ATT, native=False)[0]
    assert part["type"] == "input_text" and "THE TEXT" in part["text"], part


@check("Scanned PDF (no text layer) stays native even when downgraded")
def _():
    scanned = [{**ATT[0], "extracted_text": ""}]
    assert build_content_parts("q", scanned, native=False)[0]["type"] == "input_file"


@check("Over-long extraction is truncated with an explicit marker")
def _():
    t = _truncate("a" * (MAX_EXTRACTED_CHARS + 5000))
    assert "truncated" in t.lower() and len(t) > MAX_EXTRACTED_CHARS


# -------------------------------------------------------------------- budget

from app.chat import _estimate_message_tokens, SYSTEM_STABLE  # noqa: E402
from app.config import get_settings  # noqa: E402

BIG_PDF = {"content_type": "application/pdf", "size": 1_200_000, "extracted_chars": 38_000}


@check("A native PDF is estimated far dearer than the same PDF as text")
def _():
    native = _estimate_message_tokens({"content": "x", "attachments": [BIG_PDF]}, native=True)
    text = _estimate_message_tokens({"content": "x", "attachments": [BIG_PDF]}, native=False)
    assert text < native / 3, (native, text)


@check("A 20-turn thread with a report attached stays inside the budget")
def _():
    s = get_settings()
    msgs = [{"role": "user", "content": "summarise", "attachments": [BIG_PDF]}]
    for _ in range(19):
        msgs.append({"role": "assistant", "content": "x" * 1200, "attachments": []})
        msgs.append({"role": "user", "content": "y" * 80, "attachments": []})
    newest = len(msgs) - 1
    spent = _estimate_message_tokens(msgs[newest], native=True)
    for i in range(newest - 1, -1, -1):
        c = _estimate_message_tokens(msgs[i], native=False)
        if spent + c > s.HISTORY_TOKEN_BUDGET:
            break
        spent += c
    assert spent <= s.HISTORY_TOKEN_BUDGET, spent
    assert spent < 30_000, "must fit the tightest provider limit in use"


# --------------------------------------------------------------------- cache

@check("Cacheable prefix carries no per-user or per-day content")
def _():
    assert "Today is" not in SYSTEM_STABLE
    assert "pinned context" not in SYSTEM_STABLE.lower()
    assert len(SYSTEM_STABLE) > 4000, "too short to be worth caching"


@check("Combined system prompt puts the stable half first")
def _():
    from app.providers.base import ChatRequestSpec
    spec = ChatRequestSpec(model="m", system_stable=SYSTEM_STABLE,
                           system_volatile="V", history=[], max_output_tokens=1)
    assert spec.system_prompt.startswith(SYSTEM_STABLE)


@check("Anthropic history breakpoint leaves the newest turn outside it")
def _():
    msgs = _to_messages([{"role": "user", "content": "a"},
                         {"role": "assistant", "content": "b"},
                         {"role": "user", "content": "c"}])
    msgs[-2]["content"][-1] = {**msgs[-2]["content"][-1], "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in msgs[-1]["content"][-1]


# ------------------------------------------------------- keys and resolution

@check("An agent keyed at runtime appears without a restart")
def _():
    import app.config as cfg
    keys = {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "b"}
    original = cfg._fetch_secret
    try:
        cfg._fetch_secret = lambda n: keys.get(n)
        cfg.invalidate_secret_cache()
        assert GOOGLE not in cfg.available_providers()
        keys["GEMINI_API_KEY"] = "c"
        cfg.invalidate_secret_cache()
        assert GOOGLE in cfg.available_providers()
    finally:
        cfg._fetch_secret = original
        cfg.invalidate_secret_cache()


@check("Model resolution honours the allowlist and skips unkeyed vendors")
def _():
    import app.chat as C
    from app.chat import _resolve_model
    s = get_settings()
    cfg = {"available_models": ["claude-opus-5", "gpt-4o"], "default_model": "claude-sonnet-5"}
    original = C.available_providers
    try:
        C.available_providers = lambda: (ANTHROPIC, OPENAI, GOOGLE)
        assert _resolve_model("gpt-4o", {}, cfg, s) == "gpt-4o"
        assert _resolve_model("gemini-2.5-pro", {}, cfg, s) == "claude-opus-5", "off-allowlist rejected"
        assert _resolve_model("nonsense", {}, cfg, s) == "claude-opus-5"
        C.available_providers = lambda: (OPENAI,)
        assert _resolve_model("claude-opus-5", {}, cfg, s) == "gpt-4o", "unkeyed vendor skipped"
    finally:
        C.available_providers = original


@check("Per-agent caps override the shared fallback")
def _():
    from app.storage import cap_for
    prof = {"cap_tokens": 500_000, "caps_by_provider": {OPENAI: 100_000}}
    assert cap_for(prof, OPENAI) == 100_000
    assert cap_for(prof, ANTHROPIC) == 500_000


if __name__ == "__main__":
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)
