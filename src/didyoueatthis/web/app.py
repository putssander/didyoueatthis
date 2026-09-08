"""FastAPI app behind ``didyoueatthis serve``.

Endpoints
---------
GET  /                  the single-page UI
GET  /api/models        provider prefixes usable with the keys in the environment
POST /api/jobs          start a document test; body: {text, controls[], models[], passages, prefix_words,
                        suffix_words, hit_words, paraphrase_with}
GET  /api/jobs/{id}     progress and, when finished, the report (JSON + Markdown)

Jobs run in a background thread and persist to results/web_<id>/ like CLI
runs, so the raw answers are always on disk.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..core.report import build_report, to_markdown
from ..core.text import DEFAULT_PREFIX_WORDS, DEFAULT_SUFFIX_WORDS, build_text_probes, paraphrase_probes
from ..providers import available_prefixes, get_provider, split_model
from ..runner import RunConfig, ensure_dir, run_probes, score_responses
from ..core.probe import dump_jsonl

load_dotenv()
app = FastAPI(title="didyoueatthis")
STATIC = os.path.join(os.path.dirname(__file__), "static")
JOBS: dict[str, dict[str, Any]] = {}


class JobRequest(BaseModel):
    text: str = Field(min_length=200)
    controls: list[str] = []
    models: list[str] = Field(min_length=1)
    passages: int = 12
    prefix_words: list[int] = list(DEFAULT_PREFIX_WORDS)
    suffix_words: int = DEFAULT_SUFFIX_WORDS
    hit_words: int = 20
    paraphrase_with: str | None = None
    doc_id: str = "pasted"


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/models")
def models():
    return {"prefixes": available_prefixes(),
            "suggested": {"openai": ["gpt-5", "gpt-4.1"], "anthropic": ["claude-opus-5", "claude-sonnet-5"],
                          "google": ["gemini-2.5-pro", "gemini-2.5-flash"], "local": ["llama3"], "mock": ["memoriser"]}}


def _run_job(job_id: str, req: JobRequest) -> None:
    job = JOBS[job_id]
    try:
        run_dir = os.path.join("results", f"web_{job_id}")
        ensure_dir(run_dir)
        pw = tuple(req.prefix_words)
        probes = build_text_probes(req.text, "target", req.doc_id, req.passages, pw, req.suffix_words)
        for i, c in enumerate(req.controls):
            if c.strip():
                probes += build_text_probes(c, "control", f"control{i}", req.passages, pw, req.suffix_words)
        if req.paraphrase_with:
            job["stage"] = "paraphrasing"
            pfx, mid = split_model(req.paraphrase_with)
            probes += paraphrase_probes([p for p in probes if p.tier == "target"], get_provider(pfx), mid)
        dump_jsonl(os.path.join(run_dir, "probes.jsonl"), probes)
        job["stage"] = "querying"
        job["total"] = len(probes) * len(req.models)

        def prog(done, total):
            job["done"] = done

        cfg = RunConfig(models=req.models, cache_path=os.path.join(run_dir, "responses.jsonl"),
                        hit_words=req.hit_words, progress=prog)
        responses = run_probes(probes, cfg)
        scores = score_responses(probes, responses, req.hit_words)
        rep = build_report(scores, {"family": "text", "doc_id": req.doc_id, "models": req.models,
                                    "prefix_words": pw, "suffix_words": req.suffix_words,
                                    "hit_words": req.hit_words, "controls": len(req.controls),
                                    "date": time.strftime("%Y-%m-%d")})
        by_id = {p.id: p for p in probes}
        examples = []
        for r in responses:
            p = by_id[r.probe_id]
            examples.append({"model": r.model, "tier": p.tier, "group": p.group, "prefix_words": p.meta.get("prefix_words"),
                             "truth": p.truth, "answer": r.text[:600], "error": r.error, "refused": r.refused})
        with open(os.path.join(run_dir, "report.md"), "w") as f:
            f.write(to_markdown(rep))
        job.update(stage="done", report=rep, markdown=to_markdown(rep), examples=examples, run_dir=run_dir)
    except Exception as e:  # noqa: BLE001
        job.update(stage="error", error=f"{type(e).__name__}: {e}")


@app.post("/api/jobs")
def create_job(req: JobRequest):
    for m in req.models:
        pfx, _ = split_model(m)
        if pfx not in available_prefixes():
            raise HTTPException(400, f"provider '{pfx}' has no key configured")
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"id": job_id, "stage": "starting", "done": 0, "total": 0, "created": time.time()}
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "no such job")
    return JSONResponse(JOBS[job_id])
