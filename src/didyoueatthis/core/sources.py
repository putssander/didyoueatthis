"""Carry source/rights notices alongside text, prompts and exported evidence.

Metadata records provenance, not a legal determination. User-supplied files
can carry the same `<file>.sources.json` sidecar as fetched test documents.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .probe import Probe

SOURCE_MARKER = "\n\n--- Source attribution (not part of the passage) ---\n"
CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/"


def read_sources(path: str) -> list[dict]:
    sidecar = Path(str(path) + ".sources.json")
    return json.loads(sidecar.read_text(encoding="utf-8"))["sources"] if sidecar.exists() else []


def write_sources(path: str, sources: list[dict]) -> None:
    Path(str(path) + ".sources.json").write_text(
        json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_notice(sources: list[dict]) -> str:
    return "\n\n".join("\n".join(str(v) for v in [
        f"{s['title']} — {s.get('author', 'see source')}", s.get("url"),
        s.get("history_url"), s.get("license"), s.get("license_url"),
        s.get("changes"), s.get("notice")
    ] if v) for s in sources)


def with_sources(probes: list[Probe], sources: list[dict]) -> list[Probe]:
    """Attach source records to probes as metadata.

    The notice is deliberately NOT appended to the prompt sent to the model:
    naming the work ("Pride and Prejudice, Jane Austen") turns a recognition
    test into a recall-by-title test and can leak a cloze answer.  Sending
    text to an API is use, not redistribution; attribution belongs with the
    copies people keep and share, which is where the CLI and page put it
    (prompts.md, SOURCES.md, report.json, downloads).
    """
    if not sources:
        return probes
    return [replace(p, meta={**p.meta, "sources": sources}) for p in probes]
