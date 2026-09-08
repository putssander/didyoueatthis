"""Turn scores into a report: per model, per tier (and per field / prefix length), plus a verdict.

The report is produced both as a JSON structure (for the web UI and for
archiving) and as Markdown (for reading and pasting into a paper).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any

from .scoring import VERDICTS, Score, TierSummary, summarise_tier, verdict

# Which tier is the question and which is the chance baseline, per family.
TARGET_TIER = {"text": "target", "csv": "target", "cloze": "target", "mcq": "target", "canary": "target"}
CONTROL_TIER = {"text": "control", "csv": "synthetic", "cloze": "control", "mcq": "control", "canary": "control"}
CHANCE = {"mcq": 0.25}
FAMILY_LABEL = {"text": "verbatim continuation", "csv": "row continuation", "cloze": "name cloze",
                "mcq": "multiple choice (DE-COP)", "canary": "canary completion"}
TIER_ORDER = ["target", "paraphrase", "control", "synthetic"]


def _fmt_ci(s: TierSummary) -> str:
    lo, hi = s.ci
    return f"{s.rate:.2f} [{lo:.2f}, {hi:.2f}]"


def _tier_dict(s: TierSummary) -> dict[str, Any]:
    d = asdict(s)
    d["rate"], (d["ci_lo"], d["ci_hi"]), d["null_rate"] = s.rate, s.ci, s.null_rate
    return d


def build_report(scores: list[Score], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    by_model_family: dict[tuple[str, str], list[Score]] = defaultdict(list)
    for s in scores:
        by_model_family[(s.model, s.family)].append(s)
    out: dict[str, Any] = {"meta": meta or {}, "models": {}}
    for (model, family), ss in sorted(by_model_family.items()):
        tiers = {t: summarise_tier(t, [s for s in ss if s.tier == t]) for t in sorted({s.tier for s in ss})}
        target = tiers.get(TARGET_TIER[family])
        control = tiers.get(CONTROL_TIER[family])
        v = verdict(target, control, chance=CHANCE.get(family, 0.0)) if target else "inconclusive"
        # Secondary breakdowns: by context rows (csv) or prefix length (text).
        breakdown: dict[str, dict[str, Any]] = {}
        key = {"csv": "context_rows", "text": "prefix_words"}.get(family)
        for t, tss in (tiers.items() if key else []):
            for val in sorted({str(s.meta.get(key)) for s in ss if s.tier == t}, key=lambda x: (len(x), x)):
                sub = [s for s in ss if s.tier == t and str(s.meta.get(key)) == val]
                breakdown.setdefault(t, {})[val] = _tier_dict(summarise_tier(t, sub))
        # Exhibits: the actual hits, so a reader can check them by eye.
        hidden = [{"tier": s.tier, "group": s.group, "probe_id": s.probe_id} for s in ss if s.reasoning_hit and not s.hit]
        hits = [{"tier": s.tier, "group": s.group, "probe_id": s.probe_id, "exact_prefix": s.exact_prefix,
                 "longest_run": s.longest_run, **{k: s.meta.get(k) for k in ("field", "prefix_words", "context_rows")}}
                for s in ss if s.hit]
        hit_groups = sorted({(h["tier"], h["group"]) for h in hits})
        out["models"].setdefault(model, {})[family] = {
            "verdict": v, "verdict_text": VERDICTS[v], "method": FAMILY_LABEL.get(family, family),
            "chance": CHANCE.get(family, 0.0),
            "target_tier": TARGET_TIER[family], "control_tier": CONTROL_TIER[family],
            "tiers": {t: _tier_dict(s) for t, s in tiers.items()},
            "breakdown_key": key, "breakdown": breakdown, "hits": hits,
            "hit_groups": [f"{t}/{g}" for t, g in hit_groups],
            "hidden_recall": hidden,
        }
    return out


def to_markdown(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    m = rep.get("meta", {})
    if m:
        lines.append("# didyoueatthis report\n")
        for k, v in m.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
    for model, fams in rep["models"].items():
        for family, r in fams.items():
            lines.append(f"## {model} — {r['method']}" + (f" (chance {r['chance']:.2f})" if r["chance"] else "") + "\n")
            lines.append(f"**Verdict: `{r['verdict']}`** — {r['verdict_text']}\n")
            has_reasoning = any(s["with_reasoning"] for s in r["tiers"].values())
            lines.append("| tier | groups | hit groups | rate [95% CI] | probe hits / n | null rate | unknown | refused/err | blocked | mean exact-prefix words | longest run | mean sim |"
                         + (" with reasoning | recalled in reasoning | guardrail mentioned | hidden recall |" if has_reasoning else ""))
            lines.append("|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|" + ("---:|---:|---:|---:|" if has_reasoning else ""))
            for t in sorted(r["tiers"], key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99):
                s = r["tiers"][t]
                lines.append(f"| {t} | {s['n_groups']} | {s['hit_groups']} | {s['rate']:.2f} [{s['ci_lo']:.2f}, {s['ci_hi']:.2f}] | "
                             f"{s['hit_probes']}/{s['n_probes']} | {s['null_rate']:.2f} | {s['unknown']} | {s['refused']} | {s['blocked']} | "
                             f"{s['mean_exact_prefix']:.1f} | {s['max_longest_run']} | {s['mean_sim']:.2f} |"
                             + (f" {s['with_reasoning']} | {s['recalled_in_reasoning']} | {s['guardrail_mentions']} | {s['hidden_recall']} |" if has_reasoning else ""))
            lines.append("")
            if not r["breakdown_key"]:
                lines.append("")
            else:
                lines.append(f"Breakdown by `{r['breakdown_key']}` (hit groups / groups):\n")
                keys = sorted({k for t in r["breakdown"].values() for k in t}, key=lambda x: (len(x), x))
                lines.append("| tier | " + " | ".join(keys) + " |")
                lines.append("|---|" + "---:|" * len(keys))
                for t in sorted(r["breakdown"], key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99):
                    cells = []
                    for k in keys:
                        s = r["breakdown"][t].get(k)
                        cells.append(f"{s['hit_groups']}/{s['n_groups']}" if s else "–")
                    lines.append(f"| {t} | " + " | ".join(cells) + " |")
                lines.append("")
            if r.get("hidden_recall"):
                lines.append(f"{len(r['hidden_recall'])} answers where the reasoning summary contains the source text but the "
                             "answer does not (a guardrail, not ignorance): " +
                             ", ".join(f"{h['tier']}/{h['group']}" for h in r["hidden_recall"][:20]) + "\n")
            if r["hits"]:
                hg = r["hit_groups"]
                lines.append(f"{len(r['hits'])} exact hits in {len(hg)} groups (probe ids in `scores.jsonl`): " +
                             ", ".join(hg[:30]) + (" …" if len(hg) > 30 else ""))
                lines.append("")
    return "\n".join(lines)
