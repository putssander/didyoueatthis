"""Calibration test sets: documents and tables whose exposure status is known.

Before trusting a verdict on your own document, run the same procedure on
material where the answer is known.  Three kinds are needed, and only the
first two can be fetched automatically:

known-positive   text that is certainly in every web-scale corpus *and* heavily
                 duplicated, so a chat model reproduces it despite tuning:
                 public-domain classics (Project Gutenberg) and the most-copied
                 teaching tables (Titanic).  Expected: ``strong_memorization``.
known-negative   text that did not exist when the model was trained: Wikipedia
                 articles created in the last days (fetched live from the API).
                 Expected: ``no_signal``.  These are also the best matched
                 *controls* for a Wikipedia-like target.
your own         unpublished writing of yours: the cleanest negative there is,
                 and the only one whose status you can be certain of.

Published membership-inference benchmarks (WikiMIA, BookMIA, MIMIR) are
deliberately not wired in: they were released in 2023-2024 and are themselves
inside the corpora of every model trained since, so their "non-member"
halves are not non-members for a 2026 model.  docs/04-test-sets.md
discusses this.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

GUTENBERG = {
    "pride-and-prejudice": 1342,
    "moby-dick": 2701,
    "alice-in-wonderland": 11,
    "frankenstein": 84,
}
TITANIC_URL = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"
WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "didyoueatthis/0.1 (memorisation audit; contact: see repository)"}


def _get(url: str, timeout: int = 60, retries: int = 5) -> bytes:
    """GET with exponential backoff on 429/5xx (Wikipedia rate-limits bursts: 5, 10, 20, 40 s)."""
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == retries - 1:
                raise
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError("unreachable")


def strip_gutenberg(text: str) -> str:
    """Drop the licence header/footer so probes come from the book, not the boilerplate."""
    m = re.search(r"\*\*\* START OF (THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n", text)
    if m:
        text = text[m.end():]
    m = re.search(r"\*\*\* END OF (THE|THIS) PROJECT GUTENBERG EBOOK", text)
    if m:
        text = text[: m.start()]
    return text.strip()


def fetch_gutenberg(dest: str) -> list[str]:
    os.makedirs(dest, exist_ok=True)
    out = []
    for name, gid in GUTENBERG.items():
        p = os.path.join(dest, f"{name}.txt")
        if not os.path.exists(p):
            raw = _get(f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt").decode("utf-8", "replace")
            with open(p, "w", encoding="utf-8") as f:
                f.write(strip_gutenberg(raw))
        out.append(p)
    return out


def fetch_fresh_wiki(dest: str, n_articles: int = 12, min_words: int = 400, max_scan: int = 400) -> list[str]:
    """Newest English Wikipedia articles (main namespace, not redirects) with enough prose.

    Each article becomes one file. Creation date is in the file name so the
    reader can check it postdates the model's cutoff.
    """
    os.makedirs(dest, exist_ok=True)
    # Articles fetched earlier today are reused; only the shortfall is fetched (delete the folder to refresh).
    out: list[str] = sorted(os.path.join(dest, f) for f in os.listdir(dest) if f.endswith(".txt"))
    have = {os.path.basename(f) for f in out}
    cont = ""
    scanned = 0
    while len(out) < n_articles and scanned < max_scan:
        q = {"action": "query", "list": "recentchanges", "rctype": "new", "rcnamespace": "0", "rcshow": "!redirect",
             "rclimit": "25", "maxlag": "5", "format": "json"}
        if cont:
            q["rccontinue"] = cont
        try:
            data = json.loads(_get(f"{WIKI_API}?{urllib.parse.urlencode(q)}"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and len(out) >= 4:
                print(f"fresh-wiki: rate-limited by Wikipedia; continuing with the {len(out)} articles on disk", file=sys.stderr)
                break
            raise
        pages = data["query"]["recentchanges"]
        scanned += len(pages)
        # TextExtracts returns at most 20 plain-text extracts per request.
        extracted: dict[str, dict] = {}
        for i in range(0, len(pages), 20):
            ids = "|".join(str(p["pageid"]) for p in pages[i:i + 20])
            q2 = {"action": "query", "prop": "extracts", "explaintext": "1", "exlimit": "20", "pageids": ids,
                  "maxlag": "5", "format": "json"}
            time.sleep(2.0)  # be polite to the API; TextExtracts is expensive server-side
            try:
                ex = json.loads(_get(f"{WIKI_API}?{urllib.parse.urlencode(q2)}"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    break
                raise
            if "query" not in ex:
                raise RuntimeError(f"Wikipedia API error: {ex}")
            extracted.update(ex["query"]["pages"])
        for pid, page in extracted.items():
            text = page.get("extract", "")
            if len(text.split()) < min_words:
                continue
            ts = next((p["timestamp"] for p in pages if str(p["pageid"]) == pid), "")[:10]
            slug = re.sub(r"[^a-z0-9]+", "-", page["title"].lower()).strip("-")[:60]
            if f"{ts}_{slug}.txt" in have:
                continue
            p = os.path.join(dest, f"{ts}_{slug}.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{page['title']}\n\n{text}")
            out.append(p)
            if len(out) >= n_articles:
                break
        cont = data.get("continue", {}).get("rccontinue", "")
        if not cont:
            break
    return out


def fetch_titanic(dest: str) -> list[str]:
    os.makedirs(dest, exist_ok=True)
    p = os.path.join(dest, "titanic.csv")
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(_get(TITANIC_URL))
    return [p]


@dataclass(frozen=True)
class TestSet:
    name: str
    kind: str                    # "text" | "csv"
    expected: str                # verdict expected from a model trained on the open web
    fetch: Callable[[str], list[str]]
    note: str


SETS: dict[str, TestSet] = {
    "gutenberg": TestSet("gutenberg", "text", "strong_memorization", fetch_gutenberg,
                         "Four public-domain novels. Present in every corpus, duplicated thousands of times."),
    "fresh-wiki": TestSet("fresh-wiki", "text", "no_signal", fetch_fresh_wiki,
                          "Wikipedia articles created in the last days: cannot be in any model trained before today."),
    "titanic": TestSet("titanic", "csv", "strong_memorization", fetch_titanic,
                       "The Kaggle Titanic table, copied into countless repositories and notebooks."),
}


def testset_dir(name: str, root: str = "data/testsets") -> str:
    return os.path.join(root, name)
