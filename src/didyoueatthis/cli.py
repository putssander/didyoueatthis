"""Command line.

    didyoueatthis models                      list provider prefixes usable with the current keys
    didyoueatthis text  --doc FILE [--control FILE ...] --models ... [--methods continuation,cloze,mcq]
    didyoueatthis mink  --doc FILE --control FILE --model local:your-model   log-prob test
    didyoueatthis csv   --file table.csv --models ...            row-continuation test for a table
    didyoueatthis manual export|score ...      no API key: write prompts to paste into a chat UI, score pasted answers
    didyoueatthis testsets list|fetch|run ...  calibration sets with known status (docs/04-test-sets.md)
    didyoueatthis rescore --run-dir DIR       re-score a finished run without re-querying
    didyoueatthis serve                       the web front-end

Every run writes to results/<run>/: probes.jsonl, responses.jsonl (cache),
scores.jsonl, report.json and report.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

from .core.probe import Probe, dump_jsonl, load_jsonl
from .core.report import build_report, to_markdown
from .core.cloze import build_cloze_probes
from .core.sources import read_sources, source_notice, with_sources
from .core.mcq import build_mcq_probes
from .core.text import DEFAULT_PREFIX_WORDS, DEFAULT_SUFFIX_WORDS, build_text_probes, paraphrase_probes
from .runner import RunConfig, ensure_dir, run_probes, score_responses


def _write_run(run_dir: str, probes, responses, scores, meta) -> dict:
    ensure_dir(run_dir)
    for name, items in (("probes.jsonl", probes), ("scores.jsonl", scores)):
        p = os.path.join(run_dir, name)
        if os.path.exists(p):
            os.remove(p)
        dump_jsonl(p, [i if isinstance(i, dict) else i.__dict__ for i in items])
    # responses.jsonl is normally the cache written during the run; manual mode has no cache, so write it here.
    rp = os.path.join(run_dir, "responses.jsonl")
    if not os.path.exists(rp):
        dump_jsonl(rp, responses)
    sources = list({json.dumps(s, sort_keys=True): s for p in probes for s in p.meta.get("sources", [])}.values())
    if sources:
        meta = {**meta, "sources": sources}
        with open(os.path.join(run_dir, "SOURCES.md"), "w", encoding="utf-8") as f:
            f.write("# Source credits and reuse notices\n\n" + source_notice(sources) +
                    "\n\nPreserve these notices when sharing excerpts or adaptations. Review model replies for unrelated protected material.\n")
    rep = build_report(scores, meta)
    with open(os.path.join(run_dir, "report.json"), "w") as f:
        json.dump(rep, f, indent=2)
    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write(to_markdown(rep))
    return rep


def _progress(done, total):
    if done == total or done % 20 == 0:
        print(f"  {done}/{total}", file=sys.stderr)


def cmd_models(_a):
    from .providers import available_prefixes
    print("usable provider prefixes:", ", ".join(available_prefixes()))
    print("address a model as <prefix>:<model id>, e.g. openai:gpt-5, anthropic:claude-opus-5, google:gemini-2.5-pro, local:llama3")


def cmd_text(a):
    doc_id = os.path.splitext(os.path.basename(a.doc))[0]
    run_dir = a.run_dir or os.path.join("results", f"text_{doc_id}_{time.strftime('%Y%m%d-%H%M%S')}")
    rep = _run_text_docs([a.doc], a.control or [], a.models, a, run_dir, {})
    print(to_markdown(rep))


def _build_doc_probes(path, tier, a, methods, para):
    """All probe families requested for one document. `para` = (provider, model) for paraphrases or None."""
    did = os.path.splitext(os.path.basename(path))[0]
    text = open(path, encoding="utf-8").read()
    sources = read_sources(path)
    prefixes = tuple(int(x) for x in a.prefix_words.split(","))
    probes = []
    if "continuation" in methods:
        probes += build_text_probes(text, tier, did, a.passages, prefixes, a.suffix_words, a.seed)
    if "cloze" in methods:
        probes += build_cloze_probes(text, tier, did, a.passages, seed=a.seed)
    if "mcq" in methods:
        if para is None:
            print("mcq needs a paraphrasing model: pass --paraphrase-with (skipping mcq)", file=sys.stderr)
        else:
            probes += build_mcq_probes(text, tier, did, para[0], para[1], a.passages, seed=a.seed, sources=sources)
    return with_sources(probes, sources)


def _run_text_docs(targets, controls, models, a, run_dir, meta_extra):
    """Shared by `text` and `testsets run`: build target/control probes from files, run, score, report."""
    from .providers import get_provider, split_model
    prefixes = tuple(int(x) for x in a.prefix_words.split(","))
    methods = [m.strip() for m in a.methods.split(",")]
    para = None
    if getattr(a, "paraphrase_with", None):
        pfx, mid = split_model(a.paraphrase_with)
        para = (get_provider(pfx), mid)
    elif "mcq" in methods:
        pfx, mid = split_model(models[0])   # distractors only; the model under test is fine for that
        para = (get_provider(pfx), mid)
    probes = []
    for path in targets:
        probes += _build_doc_probes(path, "target", a, methods, para)
    for path in controls:
        probes += _build_doc_probes(path, "control", a, methods, para)
    if getattr(a, "paraphrase_with", None) and "continuation" in methods:
        probes += paraphrase_probes([p for p in probes if p.tier == "target" and p.family == "text"], para[0], para[1])
    cfg = RunConfig(models=models, cache_path=os.path.join(run_dir, "responses.jsonl"), workers=a.workers,
                    hit_words=a.hit_words, seed=a.seed, limit=a.limit, progress=_progress,
                    reasoning=getattr(a, "reasoning", False))
    print(f"{len(probes)} probes x {len(models)} models -> {run_dir}", file=sys.stderr)
    responses = run_probes(probes, cfg)
    scores = score_responses(probes, responses, a.hit_words, a.seed)
    return _write_run(run_dir, probes, responses, scores,
                      {"family": "text", "methods": methods, "targets": targets, "controls": controls, "models": models,
                       "prefix_words": prefixes, "suffix_words": a.suffix_words, "hit_words": a.hit_words,
                       "date": time.strftime("%Y-%m-%d"), **meta_extra})


def cmd_csv(a):
    from .core.table import build_table_study, load_csv
    df = load_csv(a.file)
    doc_id = os.path.splitext(os.path.basename(a.file))[0]
    ctx = tuple(int(x) for x in a.context_rows.split(","))
    probes = build_table_study(df, doc_id, a.n_rows, ctx, a.key_cols, a.seed, os.path.basename(a.file))
    run_dir = a.run_dir or os.path.join("results", f"csv_{doc_id}_{time.strftime('%Y%m%d-%H%M%S')}")
    cfg = RunConfig(models=a.models, cache_path=os.path.join(run_dir, "responses.jsonl"), workers=a.workers,
                    seed=a.seed, limit=a.limit, progress=_progress, reasoning=getattr(a, "reasoning", False))
    print(f"{len(probes)} probes x {len(a.models)} models -> {run_dir}", file=sys.stderr)
    responses = run_probes(probes, cfg)
    scores = score_responses(probes, responses, seed=a.seed)
    rep = _write_run(run_dir, probes, responses, scores,
                     {"family": "csv", "file": a.file, "models": a.models, "context_rows": ctx, "date": time.strftime("%Y-%m-%d")})
    print(to_markdown(rep))


def cmd_testsets(a):
    from .testsets import SETS, testset_dir
    if a.sub == "list":
        for s in SETS.values():
            print(f"{s.name:12s} {s.kind:5s} expected={s.expected:20s} {s.note}")
        return
    ts = SETS[a.name]
    files = ts.fetch(testset_dir(a.name, a.root))
    print(f"{a.name}: {len(files)} file(s) in {testset_dir(a.name, a.root)}", file=sys.stderr)
    if a.sub == "fetch":
        for f in files:
            print(f)
        return
    run_dir = a.run_dir or os.path.join("results", f"calib_{a.name}_{time.strftime('%Y%m%d-%H%M%S')}")
    if ts.kind == "csv":
        a.file, a.run_dir = files[0], run_dir
        return cmd_csv(a)
    # Text sets: the control tier is always fresh Wikipedia (for fresh-wiki itself, the second half).
    if a.name == "fresh-wiki":
        half = len(files) // 2
        targets, controls = files[:half], files[half:]
    else:
        targets = files
        controls = SETS["fresh-wiki"].fetch(testset_dir("fresh-wiki", a.root))
    rep = _run_text_docs(targets, controls, a.models, a, run_dir, {"testset": a.name, "expected": ts.expected})
    print(to_markdown(rep))
    for model, fams in rep["models"].items():
        for fam, r in fams.items():
            got = r["verdict"]
            print(f"CALIBRATION {a.name} {model} [{r['method']}]: expected {ts.expected}, got {got} -> "
                  f"{'OK' if got == ts.expected else 'MISMATCH'}")



MARK_P = "##### PROMPT {n} #####"
MARK_A = "##### ANSWER {n} #####"
MARK_T = "##### THINKING {n} #####"   # optional: the reasoning the chat app displayed


def cmd_manual(a):
    """Manual mode for people without API keys.

    export: build the probes and write DIR/probes.jsonl plus DIR/prompts.md,
            one self-contained prompt per block (audit instruction included),
            and an empty DIR/answers.md with matching markers.
    score:  read DIR/probes.jsonl and the answers file, score locally, write
            the report to DIR.
    """
    import re as _re
    if a.sub == "export":
        a.methods = getattr(a, "methods", "continuation")
        a.hit_words = 20
        methods = [m.strip() for m in a.methods.split(",")]
        probes = []
        for path, tier in [*[(d, "target") for d in a.doc], *[(c, "control") for c in (a.control or [])]]:
            probes += _build_doc_probes(path, tier, a, methods, None)
        if getattr(a, "canary_registry", None):
            from .core import canary as C
            probes += C.check_probes(C.load_registry(a.canary_registry))
        ensure_dir(a.dir)
        pp = os.path.join(a.dir, "probes.jsonl")
        if os.path.exists(pp):
            os.remove(pp)
        dump_jsonl(pp, probes)
        with open(os.path.join(a.dir, "prompts.md"), "w", encoding="utf-8") as f:
            f.write("Paste each prompt into a NEW chat (web search and memory off, default settings) and copy the reply "
                    "unedited under the matching marker in answers.md.\n\n")
            for i, p in enumerate(probes, 1):
                f.write(f"{MARK_P.format(n=i)}\n{p.system}\n\n{p.prompt}\n\n")
            credits = list({json.dumps(s, sort_keys=True): s for p in probes for s in p.meta.get("sources", [])}.values())
            if credits:
                f.write("## Source credits and reuse notices (keep with this file; do not paste into the chat)\n\n"
                        + source_notice(credits) + "\n")
        with open(os.path.join(a.dir, "answers.md"), "w", encoding="utf-8") as f:
            f.write("Paste each reply under its ANSWER marker. If the chat app showed the model's reasoning, paste "
                    "that under the matching THINKING marker (optional): it shows whether a refusal was a guardrail.\n\n")
            f.write("".join(f"{MARK_A.format(n=i)}\n\n\n{MARK_T.format(n=i)}\n\n\n" for i in range(1, len(probes) + 1)))
        print(f"{len(probes)} prompts -> {a.dir}/prompts.md; fill {a.dir}/answers.md, then: "
              f"didyoueatthis manual score --dir {a.dir}", file=sys.stderr)
        return
    from .core.probe import Response
    probes = [Probe(**d) for d in load_jsonl(os.path.join(a.dir, "probes.jsonl"))]
    text = open(a.answers or os.path.join(a.dir, "answers.md"), encoding="utf-8").read()
    # Blocks: "##### ANSWER n #####" and optional "##### THINKING n #####" (what the chat app showed as reasoning).
    thinking: dict[int, str] = {}
    parts = _re.split(r"#####\s*THINKING\s+(\d+)\s*#####", text)
    for i in range(1, len(parts) - 1, 2):
        thinking[int(parts[i])] = _re.split(r"#####\s*ANSWER\s+\d+\s*#####", parts[i + 1])[0].strip()
    parts = _re.split(r"#####\s*ANSWER\s+(\d+)\s*#####", text)
    answers = {int(parts[i]): _re.split(r"#####\s*THINKING\s+\d+\s*#####", parts[i + 1])[0].strip()
               for i in range(1, len(parts) - 1, 2)}
    label = f"manual:{a.label}"
    responses = [Response(probe_id=p.id, model=label, text=answers.get(i, ""),
                          error="" if answers.get(i) else "no answer pasted",
                          raw_meta={"reasoning": thinking[i]} if thinking.get(i) else {})
                 for i, p in enumerate(probes, 1)]
    scores = score_responses(probes, responses, a.hit_words, a.seed)
    rep = _write_run(a.dir, probes, responses, scores,
                     {"family": "text", "mode": "manual", "label": label,
                      "answered": sum(1 for r in responses if not r.error), "date": time.strftime("%Y-%m-%d")})
    print(to_markdown(rep))


def cmd_mink(a):
    """Min-K% on token log-probabilities: score the target and control documents directly (no generation)."""
    import json as _json
    from .core.mink import score_document, summarise_mink
    from .providers import get_provider, split_model
    pfx, mid = split_model(a.model)
    prov = get_provider(pfx)
    target, control = [], []
    for path in [a.doc]:
        target += score_document(prov, mid, open(path, encoding="utf-8").read(), os.path.basename(path), "target", a.chunk_words, a.max_chunks)
    for path in a.control:
        control += score_document(prov, mid, open(path, encoding="utf-8").read(), os.path.basename(path), "control", a.chunk_words, a.max_chunks)
    rep = summarise_mink(target, control)
    rep["model"], rep["doc"], rep["controls"] = a.model, a.doc, a.control
    rep["sources"] = [s for path in [a.doc, *a.control] for s in read_sources(path)]
    run_dir = a.run_dir or os.path.join("results", f"mink_{time.strftime('%Y%m%d-%H%M%S')}")
    ensure_dir(run_dir)
    with open(os.path.join(run_dir, "mink.json"), "w") as f:
        _json.dump({"summary": rep, "chunks": [c.__dict__ for c in target + control]}, f, indent=2, default=str)
    print(f"Min-K% ({a.model}): {len(target)} target chunks vs {len(control)} control chunks")
    for k, r in rep["k"].items():
        if "note" in r:
            print(f"  k={k:.0%}: {r['note']}")
        else:
            print(f"  k={k:.0%}: {r['target_above']}/{len(target)} target chunks above control p95 "
                  f"(target median {r['target_median']:.2f}, control median {r['control_median']:.2f})")
    print(f"-> {run_dir}/mink.json")


def cmd_canary(a):
    """Prospective canaries: plant now, check against models trained later."""
    from .core import canary as C
    if a.sub == "make":
        text = open(a.doc, encoding="utf-8").read()
        token = C.make_canary()
        planted = C.plant(text, token)
        out = a.out or a.doc
        with open(out, "w", encoding="utf-8") as f:
            f.write(planted)
        C.register(a.registry, C.Entry(token, os.path.basename(a.doc), time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                       C.sha256(planted), out, a.note))
        print(f"planted {token} in {out}; registry {a.registry}. Publish the document; commit it for a timestamp.")
        return
    entries = C.load_registry(a.registry)
    probes = C.check_probes(entries)
    run_dir = a.run_dir or os.path.join("results", f"canary_{time.strftime('%Y%m%d-%H%M%S')}")
    cfg = RunConfig(models=a.models, cache_path=os.path.join(run_dir, "responses.jsonl"), workers=a.workers, seed=a.seed)
    responses = run_probes(probes, cfg)
    by = {p.id: p for p in probes}
    ent = {f"{e.canary}|{e.shown_prefix}": e for e in entries}
    print(f"{len(entries)} canaries x {len(a.models)} models")
    rows = []
    for r in responses:
        p = by[r.probe_id]; e = ent[p.group]
        n = C.match_chars(p.truth, r.text)
        total = len("".join(ch for ch in p.truth if ch.isalnum()))
        verdict = "EXACT" if n >= total else (f"partial {n}/{total}" if n >= 4 else "no")
        rows.append((r.model, e.doc_id, e.planted_at[:10], verdict, r.text.strip()[:48].replace("\n", " ")))
        print(f"  {r.model:26s} {e.doc_id:34s} planted {e.planted_at[:10]}  {verdict:14s} answer: {rows[-1][4]!r}")
    with open(os.path.join(run_dir, "canary_check.json"), "w") as f:
        json.dump([{"model": m, "canary": d, "planted": pl, "result": v, "answer": ans} for m, d, pl, v, ans in rows], f, indent=2)
    if a.exposure_k:
        from .providers import get_provider, split_model
        for mq in a.models:
            pfx, mid = split_model(mq)
            prov = get_provider(pfx)
            for e in entries:
                try:
                    x = C.exposure(prov, mid, e, a.exposure_k, a.seed)
                    print(f"  exposure {mq} {e.canary}: rank {x['rank']}/{x['k'] + 1}, {x['exposure_bits']:.1f} of {x['max_bits']:.1f} bits")
                except NotImplementedError as err:
                    print(f"  exposure {mq}: {err}")
                    break


def cmd_rescore(a):
    """Re-score and re-report a run directory without re-querying (e.g. after changing scoring)."""
    from .core.probe import Response
    probes = [Probe(**d) for d in load_jsonl(os.path.join(a.run_dir, "probes.jsonl"))]
    responses = [Response.from_json(d) for d in load_jsonl(os.path.join(a.run_dir, "responses.jsonl"))]
    ids = {p.id for p in probes}
    responses = [r for r in responses if r.probe_id in ids]
    scores = score_responses(probes, responses, a.hit_words, a.seed)
    rep = _write_run(a.run_dir, probes, responses, scores, {"rescored": time.strftime("%Y-%m-%d")})
    print(to_markdown(rep))


def cmd_serve(a):
    import uvicorn
    uvicorn.run("didyoueatthis.web.app:app", host=a.host, port=a.port, reload=False)


def main(argv=None):
    load_dotenv()
    ap = argparse.ArgumentParser(prog="didyoueatthis", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("models", help="list usable providers").set_defaults(fn=cmd_models)

    def text_opts(p):
        p.add_argument("--methods", default="continuation,cloze",
                       help="comma list of continuation, cloze, mcq (mcq needs a paraphrasing model; defaults to the first model)")
        p.add_argument("--paraphrase-with", help="model used for paraphrases (mcq distractors, paraphrase tier), e.g. openai:gpt-4.1")
        p.add_argument("--passages", type=int, default=12)
        p.add_argument("--prefix-words", default=",".join(map(str, DEFAULT_PREFIX_WORDS)))
        p.add_argument("--suffix-words", type=int, default=DEFAULT_SUFFIX_WORDS)
        p.add_argument("--hit-words", type=int, default=20)

    def run_opts(p):
        p.add_argument("--reasoning", action="store_true",
                       help="also request the vendor's reasoning summary and score it (shows guardrails vs ignorance)")
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--limit", type=int)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--run-dir")

    t = sp.add_parser("text", help="general document test")
    t.add_argument("--doc", required=True)
    t.add_argument("--control", action="append", help="matched document believed unseen (repeatable)")
    t.add_argument("--models", nargs="+", required=True)
    text_opts(t); run_opts(t)
    t.set_defaults(fn=cmd_text)

    c = sp.add_parser("csv", help="row-continuation test for a CSV table (synthetic control built automatically)")
    c.add_argument("--file", required=True)
    c.add_argument("--models", nargs="+", required=True)
    c.add_argument("--n-rows", type=int, default=30)
    c.add_argument("--context-rows", default="0,2,5,10")
    c.add_argument("--key-cols", type=int, default=1, help="leading columns of the target row shown as the key")
    run_opts(c)
    c.set_defaults(fn=cmd_csv)

    tsp = sp.add_parser("testsets", help="calibration sets with known status").add_subparsers(dest="sub", required=True)
    tsp.add_parser("list").set_defaults(fn=cmd_testsets)
    for name, help_ in (("fetch", "download a set"), ("run", "fetch (if needed) and run a set")):
        q = tsp.add_parser(name, help=help_)
        q.add_argument("name", choices=["gutenberg", "fresh-wiki", "titanic"])
        q.add_argument("--root", default="data/testsets")
        if name == "run":
            q.add_argument("--models", nargs="+", required=True)
            q.add_argument("--n-rows", type=int, default=30)
            q.add_argument("--context-rows", default="0,2,5,10")
            q.add_argument("--key-cols", type=int, default=1)
            text_opts(q); run_opts(q)
        q.set_defaults(fn=cmd_testsets)

    man = sp.add_parser("manual", help="no API key: export prompts for a chat UI, score pasted answers").add_subparsers(dest="sub", required=True)
    me = man.add_parser("export")
    me.add_argument("--doc", action="append", required=True, help="document under test (repeatable)")
    me.add_argument("--control", action="append")
    me.add_argument("--dir", required=True, help="output directory (prompts.md, answers.md, probes.jsonl)")
    me.add_argument("--methods", default="continuation", help="comma list of continuation, cloze")
    me.add_argument("--canary-registry", help="also add the canaries from this registry as prompts")
    me.add_argument("--passages", type=int, default=6)
    me.add_argument("--prefix-words", default="64")
    me.add_argument("--suffix-words", type=int, default=DEFAULT_SUFFIX_WORDS)
    me.add_argument("--seed", type=int, default=0)
    me.set_defaults(fn=cmd_manual)
    ms = man.add_parser("score")
    ms.add_argument("--dir", required=True)
    ms.add_argument("--answers", help="defaults to DIR/answers.md")
    ms.add_argument("--label", default="chat", help="name of the model you pasted into, e.g. chatgpt-web")
    ms.add_argument("--hit-words", type=int, default=20)
    ms.add_argument("--seed", type=int, default=0)
    ms.set_defaults(fn=cmd_manual)

    mk = sp.add_parser("mink", help="Min-K%% log-probability test (needs an endpoint that scores given text)")
    mk.add_argument("--doc", required=True)
    mk.add_argument("--control", action="append", required=True)
    mk.add_argument("--model", required=True, help="local:<open-weight model> with input-token echo/logprobs support")
    mk.add_argument("--chunk-words", type=int, default=200)
    mk.add_argument("--max-chunks", type=int, default=20)
    mk.add_argument("--run-dir")
    mk.set_defaults(fn=cmd_mink)

    cn = sp.add_parser("canary", help="prospective canaries: plant now, check against models trained later").add_subparsers(dest="sub", required=True)
    cm = cn.add_parser("make", help="plant a random canary in a document and record it")
    cm.add_argument("--doc", required=True)
    cm.add_argument("--out", help="write the planted copy here (default: overwrite --doc)")
    cm.add_argument("--registry", default="data/canaries.json")
    cm.add_argument("--note", default="")
    cm.set_defaults(fn=cmd_canary)
    cc = cn.add_parser("check", help="ask models to complete the registered canaries")
    cc.add_argument("--registry", default="data/canaries.json")
    cc.add_argument("--models", nargs="+", required=True)
    cc.add_argument("--exposure-k", type=int, default=0, help="also rank the canary among k random ones by log-likelihood (local models)")
    cc.add_argument("--workers", type=int, default=4)
    cc.add_argument("--seed", type=int, default=0)
    cc.add_argument("--run-dir")
    cc.set_defaults(fn=cmd_canary)

    rs = sp.add_parser("rescore", help="re-score a run directory without re-querying")
    rs.add_argument("--run-dir", required=True)
    rs.add_argument("--hit-words", type=int, default=20)
    rs.add_argument("--seed", type=int, default=0)
    rs.set_defaults(fn=cmd_rescore)

    s = sp.add_parser("serve", help="web front-end")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
