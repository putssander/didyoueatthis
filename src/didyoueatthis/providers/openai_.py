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
    """Reasoning models reject sampling parameters and take reasoning_effort. The *-chat-latest
    aliases are the ChatGPT-tuned non-reasoning variants and behave like gpt-4.1."""
    m = model.lower()
    if "chat-latest" in m:
        return False
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
        if self.settings.reasoning and _is_reasoning(model) and self.prefix == "openai":
            return self._call_responses(model, probe)
        messages = []
        if probe.system:
            messages.append({"role": "system", "content": probe.system})
        messages.append({"role": "user", "content": probe.prompt})
        kw: dict = dict(model=model, messages=messages, max_completion_tokens=probe.max_tokens)
        meta: dict = {}
        if _is_reasoning(model):
            # The cap counts hidden reasoning tokens too; a tight cap yields an empty answer.
            kw["max_completion_tokens"] = probe.max_tokens + 2048
        if _is_reasoning(model) and self.prefix == "openai":
            # Lowest reasoning setting the family accepts: recall, not deliberation.
            # "minimal" exists only on the first gpt-5 family (gpt-5, -mini, -nano); later generations start at "low".
            m = model.lower()
            kw["reasoning_effort"] = "minimal" if (m == "gpt-5" or m.startswith(("gpt-5-mini", "gpt-5-nano", "gpt-5-2025"))) else "low"
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
        # OpenAI-compatible reasoning models (DeepSeek, local gpt-oss/Qwen servers) return the trace here.
        rc = getattr(choice.message, "reasoning_content", None) or getattr(choice.message, "reasoning", None)
        if rc:
            meta["reasoning"] = str(rc)
        usage = resp.usage.model_dump() if resp.usage else {}
        refused = choice.finish_reason == "content_filter" or (
            getattr(choice.message, "refusal", None) is not None and bool(choice.message.refusal))
        return Response(probe_id=probe.id, model=model, text=text, refused=refused, usage=usage, raw_meta=meta)

    def _call_responses(self, model: str, probe: Probe) -> Response:
        """Responses API with reasoning summaries (documented option; summaries are written by the vendor)."""
        inp = []
        if probe.system:
            inp.append({"role": "developer", "content": probe.system})
        inp.append({"role": "user", "content": probe.prompt})
        effort = "low" if model.lower().startswith("gpt-6") else "low"
        r = self.client.responses.create(model=model, input=inp, reasoning={"effort": effort, "summary": "auto"},
                                         max_output_tokens=probe.max_tokens + 2048)
        text, reasoning = "", []
        for item in r.output:
            if item.type == "reasoning":
                reasoning += [s.text for s in (item.summary or [])]
            elif item.type == "message":
                text += "".join(p.text for p in item.content if getattr(p, "type", "") == "output_text")
        meta = {"api": "responses", "status": r.status, "reasoning": "\n\n".join(reasoning),
                "reasoning_tokens": getattr(getattr(r.usage, "output_tokens_details", None), "reasoning_tokens", None),
                "sampling": "omitted (reasoning model)"}
        refused = any(getattr(item, "type", "") == "message" and any(getattr(p, "type", "") == "refusal" for p in item.content)
                      for item in r.output)
        usage = r.usage.model_dump() if r.usage else {}
        return Response(probe_id=probe.id, model=model, text=text, refused=refused, usage=usage, raw_meta=meta)

    def logprobs_of(self, model: str, text: str) -> list[tuple[str, float | None]]:
        """Score `text` with the legacy completions endpoint (echo=True, max_tokens=0).

        Works for OpenAI-compatible servers (vLLM, llama.cpp) hosting open
        weights.  OpenAI's own API rejects echo+logprobs (checked 2026-09-08).
        """
        r = self.client.completions.create(model=model, prompt=text, max_tokens=0, echo=True, logprobs=0,
                                           temperature=0)
        lp = r.choices[0].logprobs
        return list(zip(lp.tokens, lp.token_logprobs))
