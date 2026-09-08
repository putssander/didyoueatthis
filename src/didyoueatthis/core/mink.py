"""Min-K% probability (Shi et al., ICLR 2024) on token log-probabilities.

For endpoints that can *score* a given text (return the log-probability of
each token of a supplied string), no generation is needed: the document is
scored directly, and the average log-probability of its least likely k% of
tokens is compared with the same statistic on matched control documents.
Unseen text tends to contain a few very surprising tokens; seen text less
so.  This avoids visible recitation refusals; alignment can still affect probabilities.

Availability: OpenAI-compatible local servers (vLLM, llama.cpp) for
open-weight models, via the completions endpoint with ``echo=True``.  As of
September 2026 OpenAI's own API rejects ``echo`` together with ``logprobs``
in this project’s attempted call. Use a compatible local scoring endpoint;
generated-token log-probabilities do not score arbitrary input text.

Reported per document: Min-K% for k in {10, 20, 30} on non-overlapping
chunks, then the fraction of target chunks above the control's 95th
percentile (a descriptive threshold, not a guaranteed 5% false-positive rate).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

KS = (0.1, 0.2, 0.3)


@dataclass
class ChunkScore:
    doc_id: str
    tier: str
    idx: int
    n_tokens: int
    mean_logprob: float
    mink: dict[float, float] = field(default_factory=dict)


def chunk_words(text: str, words_per_chunk: int = 200, max_chunks: int = 20) -> list[str]:
    w = text.split()
    chunks = [" ".join(w[i:i + words_per_chunk]) for i in range(0, len(w), words_per_chunk)]
    chunks = [c for c in chunks if len(c.split()) >= words_per_chunk // 2]
    if len(chunks) > max_chunks:  # even spread over the document
        step = len(chunks) / max_chunks
        chunks = [chunks[int(i * step)] for i in range(max_chunks)]
    return chunks


def mink_scores(logprobs: list[float]) -> dict[float, float]:
    lp = sorted(x for x in logprobs if x is not None)
    out = {}
    for k in KS:
        n = max(1, int(len(lp) * k))
        out[k] = sum(lp[:n]) / n
    return out


def score_document(provider, model: str, text: str, doc_id: str, tier: str, words_per_chunk: int = 200,
                   max_chunks: int = 20) -> list[ChunkScore]:
    """Requires ``provider.logprobs_of(model, text) -> list[(token, logprob)]``."""
    out = []
    for i, ch in enumerate(chunk_words(text, words_per_chunk, max_chunks)):
        toks = provider.logprobs_of(model, ch)
        lps = [lp for _, lp in toks[1:] if lp is not None]  # first token has no context
        if len(lps) < 20:
            continue
        out.append(ChunkScore(doc_id, tier, i, len(lps), sum(lps) / len(lps), mink_scores(lps)))
    return out


def summarise_mink(target: list[ChunkScore], control: list[ChunkScore]) -> dict:
    """Fraction of target chunks whose Min-K% exceeds the control 95th percentile, per k."""
    rep: dict = {"n_target_chunks": len(target), "n_control_chunks": len(control), "k": {}}
    for k in KS:
        t = [c.mink[k] for c in target]
        c = [x.mink[k] for x in control]
        if not t or len(c) < 5:
            rep["k"][k] = {"note": "need >= 5 control chunks"}
            continue
        c_sorted = sorted(c)
        thr = c_sorted[min(len(c_sorted) - 1, int(0.95 * len(c_sorted)))]
        above = sum(1 for x in t if x > thr)
        rep["k"][k] = {"threshold_control_p95": thr, "target_above": above, "target_rate": above / len(t),
                       "target_median": statistics.median(t), "control_median": statistics.median(c)}
    return rep
