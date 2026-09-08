"""Anthropic Messages API adapter.

Notes
-----
* Current models (Opus 5, Sonnet 5, Fable 5.x, 4.7/4.8) reject ``temperature``;
  it is only sent to the models that still accept it.  Thinking is left at
  its model default but ``output_config.effort`` is set to ``"low"`` so the
  answer is a recall rather than a reasoning exercise.
* No server-side refusal fallback is configured on purpose: a fallback would
  substitute another model's answer for the one under test.  A refusal is
  recorded as ``refused=True`` with its category in ``raw_meta``.
* Token log-probabilities are not exposed by this API; likelihood-based
  scores cannot be computed for Anthropic models.
"""

from __future__ import annotations

import anthropic

from ..core.probe import Probe, Response
from .base import Provider, Settings

_SAMPLING_OK_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6", "claude-sonnet-4-5",
                         "claude-opus-4-5", "claude-3")


class AnthropicProvider(Provider):
    prefix = "anthropic"
    receives_source_ok = False

    def __init__(self, settings: Settings | None = None):
        super().__init__(settings)
        self.client = anthropic.Anthropic(timeout=self.settings.timeout_s)

    def _call(self, model: str, probe: Probe) -> Response:
        kw: dict = dict(
            model=model,
            max_tokens=max(probe.max_tokens, 64),
            messages=[{"role": "user", "content": probe.prompt}],
            output_config={"effort": "low"},
        )
        meta: dict = {}
        if probe.system:
            kw["system"] = probe.system
        if model.startswith(_SAMPLING_OK_PREFIXES):
            kw["temperature"] = self.settings.temperature
        else:
            meta["sampling"] = "omitted (model rejects sampling parameters)"
        resp = self.client.messages.create(**kw)
        meta["stop_reason"] = resp.stop_reason
        refused = resp.stop_reason == "refusal"
        if refused and getattr(resp, "stop_details", None) is not None:
            meta["refusal_category"] = getattr(resp.stop_details, "category", None)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = resp.usage.model_dump() if resp.usage else {}
        return Response(probe_id=probe.id, model=model, text=text, refused=refused, usage=usage, raw_meta=meta)
