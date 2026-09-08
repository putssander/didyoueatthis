"""Deterministic fake provider for tests, smoke runs and UI development.

It "remembers" a set of probe ids (or every probe of a tier; by default the
``target`` tier, so a dry run shows what a positive looks like)
and answers those with the exact truth; for everything else it emits plausible-looking
but wrong text so that scoring and statistics can be exercised end to end
without a network or an API key.
"""

from __future__ import annotations

import random

from ..core.probe import Probe, Response
from .base import Provider


class MockProvider(Provider):
    prefix = "mock"
    receives_source_ok = True

    def __init__(self, memorised_tiers: tuple[str, ...] = ("target",), memorised_ids: set[str] | None = None,
                 recall_prob: float = 1.0, seed: int = 0, **_):
        super().__init__()
        self.memorised_tiers = set(memorised_tiers)
        self.memorised_ids = memorised_ids or set()
        self.recall_prob = recall_prob
        self.rng = random.Random(seed)

    def _call(self, model: str, probe: Probe) -> Response:
        rng = random.Random(f"{probe.id}:{self.rng.random()}")
        remembered = probe.id in self.memorised_ids or probe.tier in self.memorised_tiers
        if remembered and rng.random() < self.recall_prob:
            return Response(probe_id=probe.id, model=model, text=probe.truth)
        if model.endswith("-refuser"):
            return Response(probe_id=probe.id, model=model, text="", refused=True)
        return Response(probe_id=probe.id, model=model, text=wrong_answer(probe.truth, rng))


def wrong_answer(truth: str, rng: random.Random) -> str:
    """A format-preserving answer that is guaranteed not to equal the truth.

    Short values with digits (identifiers, timestamps, codes) get other digits
    so the answer looks like a real value; free text gets different words.
    """
    toks = truth.split()
    if len(toks) <= 3 and any(ch.isdigit() for ch in truth):
        out = list(truth)
        for i, ch in enumerate(out):
            if ch.isdigit():
                out[i] = str((int(ch) + rng.randint(1, 9)) % 10)
        return "".join(out)
    return " ".join(f"{t}x{i}" for i, t in enumerate(toks))
