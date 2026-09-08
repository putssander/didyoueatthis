"""OpenAI Chat Completions adapter; also serves any OpenAI-compatible server.

Notes on determinism and metadata
---------------------------------
* ``temperature`` and ``seed`` are sent unless the model is a reasoning model
  (``gpt-5*``, ``gpt-6*``, ``o*``), which rejects sampling parameters; for
  those the lowest ``reasoning_effort`` the family accepts (``minimal``, or
  ``low`` for gpt-6) is used so that the answer is a recall, not a deliberation.
* ``logprobs`` are requested when ``Settings.logprobs`` is set and the model
  is not a reasoning model.  They are stored raw in ``raw_meta['logprobs']``
  as ``[(token, logprob), ...]`` for Min-K style analyses later.
* ``system_fingerprint`` and ``finish_reason`` are recorded so a run can be
  tied to a backend version.
"""

from __future__ import annotations

from openai import OpenAI

from ..core.probe import Probe, Response
from .base import Provider, Settings


def _is_reasoning(model: str) -> bool:
    m = model.lower()
    return m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


class OpenAIProvider(Provider):
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 prefix: str = "openai", receives_source_ok: bool = False,
                 settings: Settings | None = None):
        super().__init__(settings)
        self.prefix = prefix
        self.receives_source_ok = receives_source_ok
        kw = {}
        if base_url:
            kw["base_url"] = base_url
        if api_key:
            kw["api_key"] = api_key
        self.client = OpenAI(timeout=self.settings.timeout_s, **kw)

    def _call(self, model: str, probe: Probe) -> Response:
        messages = []
        if probe.system:
            messages.append({"role": "system", "content": probe.system})
        messages.append({"role": "user", "content": probe.prompt})
        kw: dict = dict(model=model, messages=messages, max_completion_tokens=probe.max_tokens)
        meta: dict = {}
        if _is_reasoning(model) and self.prefix == "openai":
            # Lowest reasoning setting the family accepts: recall, not deliberation.
            kw["reasoning_effort"] = "low" if model.lower().startswith("gpt-6") else "minimal"
            meta["sampling"] = "omitted (reasoning model)"
        else:
            kw["temperature"] = self.settings.temperature
            if self.settings.seed is not None and self.prefix == "openai":
                kw["seed"] = self.settings.seed
            if self.settings.logprobs:
                kw["logprobs"] = True
                kw["top_logprobs"] = 5
        resp = self.client.chat.completions.create(**kw)
        choice = resp.choices[0]
        text = choice.message.content or ""
        meta["finish_reason"] = choice.finish_reason
        meta["system_fingerprint"] = getattr(resp, "system_fingerprint", None)
        if getattr(choice, "logprobs", None) and choice.logprobs and choice.logprobs.content:
            meta["logprobs"] = [(lp.token, lp.logprob) for lp in choice.logprobs.content]
        usage = resp.usage.model_dump() if resp.usage else {}
        refused = choice.finish_reason == "content_filter" or (
            getattr(choice.message, "refusal", None) is not None and bool(choice.message.refusal))
        return Response(probe_id=probe.id, model=model, text=text, refused=refused, usage=usage, raw_meta=meta)
