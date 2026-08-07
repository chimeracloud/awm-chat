"""Model catalog and provider resolution.

`MODEL_CATALOG` is the authoritative map of model ID -> capabilities. It is the
only place that knows which vendor serves a given model, so `_resolve_model`
and the admin UI both derive from it rather than string-sniffing model IDs the
way the OpenAI-only version had to.

Admins narrow the catalog down to what staff may actually pick via
`settings/global.available_models` (see `storage.get_global_settings`); this
file supplies the seed for that list and the capability flags each adapter
needs.
"""
from functools import lru_cache

# Vendor identifiers. These strings are persisted (usage counters are keyed by
# them), so treat them as a stable contract — do not rename without a migration.
ANTHROPIC = "anthropic"
OPENAI = "openai"
GOOGLE = "google"

PROVIDERS = (ANTHROPIC, OPENAI, GOOGLE)

PROVIDER_LABELS = {
    ANTHROPIC: "Claude",
    OPENAI: "OpenAI",
    GOOGLE: "Gemini",
}

# Secret Manager / env var holding each vendor's API key.
PROVIDER_SECRET_NAMES = {
    ANTHROPIC: "ANTHROPIC_API_KEY",
    OPENAI: "OPENAI_API_KEY",
    GOOGLE: "GEMINI_API_KEY",
}


MODEL_CATALOG: dict[str, dict] = {
    # ---- Anthropic -------------------------------------------------------
    "claude-opus-5": {
        "provider": ANTHROPIC,
        "label": "Claude Opus 5",
        "blurb": "Deepest reasoning. Best for complex analysis and long documents.",
        # Opus 5 thinks by default and max_tokens caps thinking + reply together,
        # so this ceiling must stay well clear of a normal answer length.
        "max_output_tokens": 16000,
        "supports_effort": True,
        "effort": "medium",
        "adaptive_thinking": True,
        "web_search_tool": "web_search_20260209",
    },
    "claude-sonnet-5": {
        "provider": ANTHROPIC,
        "label": "Claude Sonnet 5",
        "blurb": "Near-Opus quality, faster and cheaper. A good everyday default.",
        "max_output_tokens": 16000,
        "supports_effort": True,
        "effort": "medium",
        "adaptive_thinking": True,
        "web_search_tool": "web_search_20260209",
    },
    "claude-haiku-4-5": {
        "provider": ANTHROPIC,
        "label": "Claude Haiku 4.5",
        "blurb": "Fastest and cheapest. Good for quick lookups and short answers.",
        "max_output_tokens": 8000,
        # Haiku 4.5 predates the effort parameter and rejects it.
        "supports_effort": False,
        "adaptive_thinking": False,
        "web_search_tool": "web_search_20250305",
    },
    # ---- OpenAI ----------------------------------------------------------
    "gpt-4o": {
        "provider": OPENAI,
        "label": "GPT-4o",
        "blurb": "OpenAI's general-purpose multimodal model.",
        "max_output_tokens": 4096,
        "web_search_tool": "web_search",
    },
    "gpt-4o-mini": {
        "provider": OPENAI,
        "label": "GPT-4o mini",
        "blurb": "Smaller and faster GPT-4o. Good for routine questions.",
        "max_output_tokens": 4096,
        "web_search_tool": "web_search",
    },
    "gpt-4.1": {
        "provider": OPENAI,
        "label": "GPT-4.1",
        "blurb": "Strong instruction following and long-context work.",
        "max_output_tokens": 8000,
        "web_search_tool": "web_search",
    },
    # ---- Google ----------------------------------------------------------
    "gemini-2.5-pro": {
        "provider": GOOGLE,
        "label": "Gemini 2.5 Pro",
        "blurb": "Google's most capable model. Very large context window.",
        "max_output_tokens": 8192,
        "web_search_tool": "google_search",
    },
    "gemini-2.5-flash": {
        "provider": GOOGLE,
        "label": "Gemini 2.5 Flash",
        "blurb": "Fast and inexpensive, with the same large context window.",
        "max_output_tokens": 8192,
        "web_search_tool": "google_search",
    },
}


# What a fresh `settings/global` gets seeded with — one sensible model per
# vendor plus the cheaper alternates, so the switcher is useful on day one.
SEED_AVAILABLE_MODELS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "gpt-4o",
    "gpt-4o-mini",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]


def seeded_available_models() -> list[str]:
    return list(SEED_AVAILABLE_MODELS)


def model_info(model: str) -> dict | None:
    """Capabilities for a model ID, or None if we don't recognise it."""
    return MODEL_CATALOG.get(model)


def provider_for_model(model: str) -> str | None:
    info = MODEL_CATALOG.get(model)
    return info["provider"] if info else None


def default_model_for(provider: str) -> str | None:
    """The first catalog model served by `provider` — used when falling back."""
    for model_id, info in MODEL_CATALOG.items():
        if info["provider"] == provider:
            return model_id
    return None


@lru_cache
def get_provider(provider: str):
    """Instantiate an adapter. Imports lazily so a missing optional SDK only
    breaks the vendor that needs it, not the whole app."""
    if provider == ANTHROPIC:
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if provider == OPENAI:
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    if provider == GOOGLE:
        from .gemini_provider import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"Unknown provider: {provider}")
