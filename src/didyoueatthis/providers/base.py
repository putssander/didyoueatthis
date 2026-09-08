"""Provider interface and shared request settings."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..core.probe import Probe, Response


@dataclass
class Settings:
    """Decoding settings applied where the vendor allows them.

    temperature   0.0 where supported; several current models reject sampling
                  parameters entirely, in which case the provider omits them and
                  records that in ``Response.raw_meta``.
    seed          passed to vendors that accept one (OpenAI).
    logprobs      request token log-probabilities where the model supports it;
                  stored in ``raw_meta['logprobs']`` for likelihood analyses.
    """
    temperature: float = 0.0
    seed: int | None = 0
    logprobs: bool = False
    timeout_s: float = 120.0


class Provider(ABC):
    prefix: str = ""
    receives_source_ok: bool = False   # may this endpoint be sent restricted source material in full?

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    @abstractmethod
    def _call(self, model: str, probe: Probe) -> Response: ...

    def complete(self, model: str, probe: Probe) -> Response:
        t0 = time.time()
        try:
            r = self._call(model, probe)
        except Exception as e:  # noqa: BLE001 - recorded, never raised, so a batch survives
            r = Response(probe_id=probe.id, model=f"{self.prefix}:{model}", text="", error=f"{type(e).__name__}: {e}")
        r.latency_s = round(time.time() - t0, 3)
        r.model = f"{self.prefix}:{model}"
        r.probe_id = probe.id
        return r
