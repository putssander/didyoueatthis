"""End-to-end checks with the mock provider: no network, no credentials.

Covers: passage selection, probe construction, scoring rules, permutation
null, tier summaries with confidence intervals, verdict rules, the policy
gate, the response cache, the CSV family and the test-set registry.
"""

import pytest

from didyoueatthis.core.probe import Probe
from didyoueatthis.core.report import build_report, to_markdown
from didyoueatthis.core.scoring import (clopper_pearson, score_continuation, score_value, summarise_tier, verdict,
                                     words)
from didyoueatthis.core.text import build_text_probes, select_passages
from didyoueatthis.runner import RunConfig, run_probes, score_responses

LOREM = " ".join(f"word{i} alpha{i % 7} beta{i % 11}." for i in range(1200))
DOC = "\n\n".join(" ".join(LOREM.split()[i:i + 220]) for i in range(0, 1200 * 3, 220))


def test_words_and_scoring():
    assert words('Hello, "World" 2196-04-09') == ["hello", "world", "2196-04-09"]
    hit, ep, run, sim = score_continuation("a b c d e f", "a b c d e f", hit_words=5)
    assert hit and ep == 6 and run == 6 and sim == 1.0
    hit, ep, run, _ = score_continuation("a b c d e f", "a b x d e f", hit_words=5)
    assert not hit and ep == 2 and run == 3
    assert score_value("142345", "The ticket number is 142345.")[0]
    assert not score_value("142345", "1423456")[0]
    assert score_value("2164-10-23 21:09:00", "2164-10-23 21:09:00")[0]
    assert score_value("SEPSIS", "sepsis")[0]


def test_ci():
    lo, hi = clopper_pearson(0, 30)
    assert lo == 0.0 and 0.09 < hi < 0.13   # rule of three: ~3/30
    lo, hi = clopper_pearson(30, 30)
    assert hi == 1.0 and lo > 0.85


def test_passage_selection_spreads_and_dedupes():
    ps = select_passages(DOC, n=6)
    assert 1 <= len(ps) <= 6
    starts = [p.start_word for p in ps]
    assert starts == sorted(starts)
    assert len({" ".join(p.text_words[:12]) for p in ps}) == len(ps)


def test_text_probes_share_suffix_across_prefix_lengths():
    probes = build_text_probes(DOC, "target", "doc", n_passages=3, prefix_words=(16, 64), suffix_words=20)
    by_group = {}
    for p in probes:
        by_group.setdefault(p.group, set()).add(p.truth)
    assert all(len(v) == 1 for v in by_group.values())
    assert all(p.sends_source_content for p in probes)


def test_mock_run_verdicts(tmp_path):
    target = build_text_probes(DOC, "target", "doc", n_passages=8, prefix_words=(16, 64), suffix_words=20)
    ctrl = build_text_probes(DOC[::-1], "control", "ctrl", n_passages=8, prefix_words=(16, 64), suffix_words=20)
    probes = target + ctrl
    cfg = RunConfig(models=["mock:memoriser"], cache_path=str(tmp_path / "r.jsonl"), workers=2)
    from didyoueatthis.providers import get_provider
    get_provider("mock", memorised_tiers=("target",))
    responses = run_probes(probes, cfg)
    scores = score_responses(probes, responses, hit_words=10)
    rep = build_report(scores)
    r = rep["models"]["mock:memoriser"]["text"]
    assert r["verdict"] == "strong_memorization", r
    assert r["tiers"]["control"]["hit_groups"] == 0
    md = to_markdown(rep)
    assert "strong_memorization" in md
    # Cache: second run makes no provider calls and returns identical answers.
    again = run_probes(probes, cfg)
    assert all(a.cached for a in again) and [a.text for a in again] == [b.text for b in responses]


def test_verdict_rules():
    def mk(tier, groups, hits):
        from didyoueatthis.core.scoring import Score
        return [Score(f"{tier}{i}", "m", tier, f"g{i}", "text", i < hits, 0, 0, 0.0, False, False) for i in range(groups)]
    t = summarise_tier("target", mk("target", 10, 4))
    c0 = summarise_tier("control", mk("control", 10, 0))
    c2 = summarise_tier("control", mk("control", 10, 2))
    assert verdict(t, c0) == "strong_memorization"
    assert verdict(t, c2) in ("memorization_signal", "no_signal")
    assert verdict(summarise_tier("target", mk("target", 3, 3)), c0) == "inconclusive"
    assert verdict(summarise_tier("target", mk("target", 10, 0)), c0) == "no_signal"
    assert verdict(summarise_tier("target", mk("target", 10, 4)), None) == "memorization_signal"


def test_policy_gate_blocks_restricted_context(tmp_path):
    p_ok = Probe("a", "csv", "restricted", "g", "prompt", "truth", meta={"contains_source": False})
    p_block = Probe("b", "csv", "restricted", "g", "prompt", "truth", meta={"contains_source": True})
    from didyoueatthis.providers import get_provider
    get_provider("mock")  # mock is receives_source_ok=True; simulate a cloud provider by flipping it
    get_provider("mock").receives_source_ok = False
    cfg = RunConfig(models=["mock:x"], cache_path=str(tmp_path / "r.jsonl"))
    rs = run_probes([p_ok, p_block], cfg)
    assert not rs[0].error and rs[1].error.startswith("policy")
    cfg.allow_restricted_context = True
    assert not run_probes([p_block], cfg)[0].error
    get_provider("mock").receives_source_ok = True




def test_csv_probes_and_synthetic_control(tmp_path):
    from didyoueatthis.core.table import build_table_study, load_csv, synthetic_rows
    p = tmp_path / "t.csv"
    p.write_text("PassengerId,Name,Fare\n" + "\n".join(f'{i},"Person {i}, Mr. X",{i * 3.5:.2f}' for i in range(1, 41)))
    df = load_csv(str(p))
    syn = synthetic_rows(df, 10, seed=0)
    assert list(syn.columns) == list(df.columns) and len(syn) == 10
    assert set(syn["PassengerId"]).isdisjoint(set(df["PassengerId"]))
    probes = build_table_study(df, "t", n_rows=5, context_rows=(0, 2), key_cols=1)
    assert {pr.tier for pr in probes} == {"target", "synthetic"}
    tgt = [pr for pr in probes if pr.tier == "target" and pr.meta["context_rows"] == 2][0]
    assert tgt.prompt.count("\n") == 3 and tgt.prompt.endswith(",") and tgt.truth.startswith('"Person ')
    from didyoueatthis.providers import get_provider
    get_provider("mock", memorised_tiers=("target",))
    cfg = RunConfig(models=["mock:m"], cache_path=str(tmp_path / "r.jsonl"))
    scores = score_responses(probes, run_probes(probes, cfg))
    r = build_report(scores)["models"]["mock:m"]["csv"]
    assert r["verdict"] == "strong_memorization" and r["tiers"]["synthetic"]["hit_groups"] == 0


def test_gutenberg_strip_and_testset_registry():
    from didyoueatthis.testsets import SETS, strip_gutenberg
    raw = "junk\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nIt is a truth.\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nmore"
    assert strip_gutenberg(raw) == "It is a truth."
    assert {s.kind for s in SETS.values()} == {"text", "csv"}
    assert SETS["fresh-wiki"].expected == "no_signal" and SETS["gutenberg"].expected == "strong_memorization"
