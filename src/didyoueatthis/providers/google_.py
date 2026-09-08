"""Google Gemini API adapter (google-genai SDK).

Thinking is switched off where the model allows it (Flash models accept a
zero thinking budget; Pro models do not, so they run at their minimum).
Safety blocks are recorded as refusals.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from ..core.probe import Probe, Response
from .base import Provider, Settings


class GoogleProvider(Provider):
    prefix = "google"
    receives_source_ok = False

    def __init__(self, settings: Settings | None = None):
        super().__init__(settings)
        self.client = genai.Client()

    def _call(self, model: str, probe: Probe) -> Response:
        cfg_kw: dict = dict(temperature=self.settings.temperature, max_output_tokens=max(probe.max_tokens, 64))
        if probe.system:
            cfg_kw["system_instruction"] = probe.system
        if "flash" in model:
            cfg_kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        resp = self.client.models.generate_content(
            model=model, contents=probe.prompt, config=types.GenerateContentConfig(**cfg_kw))
        meta: dict = {}
        refused = False
        text = ""
        try:
            text = resp.text or ""
        except Exception:  # noqa: BLE001 - blocked responses raise on .text
            text = ""
        if resp.candidates:
            fr = getattr(resp.candidates[0], "finish_reason", None)
            meta["finish_reason"] = str(fr)
            refused = fr is not None and "SAFETY" in str(fr)
        if getattr(resp, "prompt_feedback", None) and getattr(resp.prompt_feedback, "block_reason", None):
            refused = True
            meta["block_reason"] = str(resp.prompt_feedback.block_reason)
        um = getattr(resp, "usage_metadata", None)
        usage = {"prompt_tokens": getattr(um, "prompt_token_count", None),
                 "output_tokens": getattr(um, "candidates_token_count", None)} if um else {}
        return Response(probe_id=probe.id, model=model, text=text, refused=refused, usage=usage, raw_meta=meta)
