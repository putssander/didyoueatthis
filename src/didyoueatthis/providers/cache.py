"""Append-only JSONL cache keyed by (model, probe id, prompt hash, settings).

Re-running a study costs nothing for probes already answered, and the file
doubles as the raw evidence record: every model answer is kept verbatim with
the vendor metadata that was available (fingerprint, stop reason, usage).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading

from ..core.probe import Probe, Response


class ResponseCache:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._mem: dict[str, Response] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        self._mem[d["_key"]] = Response.from_json(d)

    @staticmethod
    def key(model: str, probe: Probe, settings_repr: str) -> str:
        h = hashlib.sha256(f"{probe.system}\n---\n{probe.prompt}\n{probe.max_tokens}\n{settings_repr}".encode()).hexdigest()[:24]
        return f"{model}|{probe.id}|{h}"

    def get(self, k: str) -> Response | None:
        r = self._mem.get(k)
        if r is not None:
            r.cached = True
        return r

    def put(self, k: str, r: Response) -> None:
        with self._lock:
            self._mem[k] = r
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                d = r.to_json()
                d["_key"] = k
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
