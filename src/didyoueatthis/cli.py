"""Command line.

    didyoueatthis models                      list provider prefixes usable with the current keys
    didyoueatthis text  --doc FILE [--control FILE ...] --models openai:gpt-5 anthropic:claude-opus-5
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


def _run_text_docs(targets, controls, models, a, run_dir, meta_extra):
    """Shared by `text` and `testsets run`: build target/control probes from files, run, score, report."""
    from .providers import get_provider, split_model
    prefixes = tuple(int(x) for x in a.prefix_words.split(","))
    probes = []
    for path in targets:
        did = os.path.splitext(os.path.basename(path))[0]
        probes += build_text_probes(open(path, encoding="utf-8").read(), "target", did, a.passages, prefixes, a.suffix_words, a.seed)
    for path in controls:
        did = os.path.splitext(os.path.basename(path))[0]
        probes += build_text_probes(open(path, encoding="utf-8").read(), "control", did, a.passages, prefixes, a.suffix_words, a.seed)
    if getattr(a, "paraphrase_with", None):
        pfx, mid = split_model(a.paraphrase_with)
        probes += paraphrase_probes([p for p in probes if p.tier == "target"], get_provider(pfx), mid)
    cfg = RunConfig(models=models, cache_path=os.path.join(run_dir, "responses.jsonl"), workers=a.workers,
                    hit_words=a.hit_words, seed=a.seed, limit=a.limit, progress=_progress)
    print(f"{len(probes)} probes x {len(models)} models -> {run_dir}", file=sys.stderr)
    responses = run_probes(probes, cfg)
    scores = score_responses(probes, responses, a.hit_words, a.seed)
    return _write_run(run_dir, probes, responses, scores,
                      {"family": "text", "targets": targets, "controls": controls, "models": models,
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
                    seed=a.seed, limit=a.limit, progress=_progress)
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
        got = fams["text"]["verdict"]
        print(f"CALIBRATION {a.name} {model}: expected {ts.expected}, got {got} -> {'OK' if got == ts.expected else 'MISMATCH'}")



MARK_P = "##### PROMPT {n} #####"
MARK_A = "##### ANSWER {n} #####"


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
        prefixes = tuple(int(x) for x in a.prefix_words.split(","))
        probes = []
        for path, tier in [(a.doc, "target"), *[(c, "control") for c in (a.control or [])]]:
            did = os.path.splitext(os.path.basename(path))[0]
            probes += build_text_probes(open(path, encoding="utf-8").read(), tier, did, a.passages, prefixes, a.suffix_words, a.seed)
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
        with open(os.path.join(a.dir, "answers.md"), "w", encoding="utf-8") as f:
            f.write("".join(f"{MARK_A.format(n=i)}\n\n\n" for i in range(1, len(probes) + 1)))
        print(f"{len(probes)} prompts -> {a.dir}/prompts.md; fill {a.dir}/answers.md, then: "
              f"didyoueatthis manual score --dir {a.dir}", file=sys.stderr)
        return
    from .core.probe import Response
    probes = [Probe(**d) for d in load_jsonl(os.path.join(a.dir, "probes.jsonl"))]
    text = open(a.answers or os.path.join(a.dir, "answers.md"), encoding="utf-8").read()
    parts = _re.split(r"#####\s*ANSWER\s+(\d+)\s*#####", text)
    answers = {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    label = f"manual:{a.label}"
    responses = [Response(probe_id=p.id, model=label, text=answers.get(i, ""),
                          error="" if answers.get(i) else "no answer pasted") for i, p in enumerate(probes, 1)]
    scores = score_responses(probes, responses, a.hit_words, a.seed)
    rep = _write_run(a.dir, probes, responses, scores,
                     {"family": "text", "mode": "manual", "label": label,
                      "answered": sum(1 for r in responses if not r.error), "date": time.strftime("%Y-%m-%d")})
    print(to_markdown(rep))


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
        p.add_argument("--paraphrase-with", help="model used to build the paraphrase tier, e.g. openai:gpt-5")
        p.add_argument("--passages", type=int, default=12)
        p.add_argument("--prefix-words", default=",".join(map(str, DEFAULT_PREFIX_WORDS)))
        p.add_argument("--suffix-words", type=int, default=DEFAULT_SUFFIX_WORDS)
        p.add_argument("--hit-words", type=int, default=20)

    def run_opts(p):
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
    me.add_argument("--doc", required=True)
    me.add_argument("--control", action="append")
    me.add_argument("--dir", required=True, help="output directory (prompts.md, answers.md, probes.jsonl)")
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
