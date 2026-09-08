"""Model providers.

Every provider exposes one method, ``complete(probe) -> Response``, and a
``receives_source_ok`` flag saying whether it may be sent restricted source
material in full (see ``runner.py``; local servers yes, cloud vendors no).  Models are addressed as
``"<provider>:<model id>"``; ``get_provider`` resolves the prefix.

Provider prefixes
-----------------
openai      OpenAI API (chat completions, logprobs where the model allows)
anthropic   Anthropic API (Messages)
google      Google Gemini API
local       any OpenAI-compatible server (vLLM, Ollama, llama.cpp) via LOCAL_OPENAI_BASE_URL
mock        deterministic fake for tests and dry runs
"""

from __future__ import annotations

import os

from .base import Provider
from .mock import MockProvider

_REGISTRY: dict[str, Provider] = {}


def available_prefixes() -> list[str]:
    """Prefixes usable with the keys currently in the environment."""
    out = ["mock"]
    if os.getenv("OPENAI_API_KEY"):
        out.append("openai")
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        out.append("anthropic")
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        out.append("google")
    if os.getenv("LOCAL_OPENAI_BASE_URL"):
        out.append("local")
    return out


def split_model(qualified: str) -> tuple[str, str]:
    if ":" not in qualified:
        raise ValueError(f"model must be '<provider>:<id>', got {qualified!r}")
    p, m = qualified.split(":", 1)
    return p, m


_RUN_SETTINGS: dict[str, object] = {}


def configure(reasoning: bool | None = None) -> None:
    """Apply run-level settings to every provider created so far or later.

    Dataclass defaults are frozen into ``Settings.__init__`` at class creation,
    so a class attribute cannot be used for "later"; the values are kept here
    and applied by ``get_provider`` when a provider is constructed.
    """
    if reasoning is not None:
        _RUN_SETTINGS["reasoning"] = reasoning
        for prov in _REGISTRY.values():
            prov.settings.reasoning = reasoning


def get_provider(prefix: str, **kw) -> Provider:
    """Return (and cache) the provider object for a prefix. Imports lazily so a
    missing SDK for one vendor never blocks the others. Keyword arguments only
    apply to the mock provider and re-create it (tests configure it per case)."""
    if prefix in _REGISTRY and not (prefix == "mock" and kw):
        return _REGISTRY[prefix]
    if prefix == "mock":
        prov: Provider = MockProvider(**kw)
    elif prefix == "openai":
        from .openai_ import OpenAIProvider
        prov = OpenAIProvider()
    elif prefix == "local":
        from .openai_ import OpenAIProvider
        prov = OpenAIProvider(
            base_url=os.environ["LOCAL_OPENAI_BASE_URL"],
            api_key=os.getenv("LOCAL_OPENAI_API_KEY", "none"),
            prefix="local",
            receives_source_ok=True,
        )
    elif prefix == "anthropic":
        from .anthropic_ import AnthropicProvider
        prov = AnthropicProvider()
    elif prefix == "google":
        from .google_ import GoogleProvider
        prov = GoogleProvider()
    else:
        raise ValueError(f"unknown provider prefix {prefix!r}")
    for k, v in _RUN_SETTINGS.items():
        setattr(prov.settings, k, v)
    _REGISTRY[prefix] = prov
    return prov


__all__ = ["Provider", "MockProvider", "get_provider", "split_model", "available_prefixes"]
