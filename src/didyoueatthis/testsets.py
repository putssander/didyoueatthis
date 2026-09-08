"""Candidate calibration texts and tables; exposure is not independently known.

Classic novels are plausible positive references. Recently created Wikipedia
articles are comparison candidates, not guaranteed unseen wording. Match
controls to the target and inspect replies. Fetches retain source notices;
see docs/07-copyright.md for reuse conditions and docs/04-test-sets.md for
experimental limitations.
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

from .core.sources import CC_BY_SA, write_sources

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
        write_sources(p, [{"title": name.replace("-", " ").title(),
            "author": {1342: "Jane Austen", 2701: "Herman Melville", 11: "Lewis Carroll", 84: "Mary Shelley"}[gid],
            "url": f"https://www.gutenberg.org/ebooks/{gid}",
            "license": "Original nineteenth-century novel; verify public-domain status and edition rights in your jurisdiction.",
            "changes": "Book text extracted; source header/footer excluded from probes; excerpts and masks may follow.",
            "notice": "Source terms and edition information: https://www.gutenberg.org/policy/permission.html"}])
        out.append(p)
    return out


def fetch_fresh_wiki(dest: str, n_articles: int = 12, min_words: int = 400, max_scan: int = 400) -> list[str]:
    """Newest English Wikipedia articles (main namespace, not redirects) with enough prose.

    Each article becomes one file. Creation date is in the file name so the
    reader can check it postdates the model's cutoff.
    """
    os.makedirs(dest, exist_ok=True)
    # Reuse attributed cache files only. Legacy files without provenance are left on disk, but not selected.
    out: list[str] = sorted(os.path.join(dest, f) for f in os.listdir(dest)
                            if f.endswith(".txt") and os.path.exists(os.path.join(dest, f) + ".sources.json"))
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
            q2 = {"action": "query", "prop": "extracts|info", "explaintext": "1", "exlimit": "20", "pageids": ids,
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
                f.write(f"{page['title']}\n\n{clean_wiki(text)}")
            write_sources(p, [{
                "title": page["title"], "author": "Wikipedia contributors",
                "url": f"https://en.wikipedia.org/?curid={page['pageid']}",
                "history_url": f"https://en.wikipedia.org/w/index.php?curid={page['pageid']}&action=history",
                "revision_observed": page.get("lastrevid"), "retrieved": time.strftime("%Y-%m-%d"),
                "license": "CC BY-SA 4.0", "license_url": CC_BY_SA,
                "changes": "Plain-text extraction; section headings removed; excerpts, masked names and paraphrases are adaptations offered under CC BY-SA 4.0.",
                "notice": "Check third-party quotations and special notices separately. No Wikimedia endorsement.",
            }])
            out.append(p)
            if len(out) >= n_articles:
                break
        cont = data.get("continue", {}).get("rccontinue", "")
        if not cont:
            break
    return out


def clean_wiki(text: str) -> str:
    """Drop '== Section ==' markers (they are trivially guessable cloze answers) and empty sections."""
    text = re.sub(r"^\s*=+\s*[^=\n]+?\s*=+\s*$", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
                         "Four nineteenth-century novels; plausible positive references. Check local public-domain and edition rights."),
    "fresh-wiki": TestSet("fresh-wiki", "text", "no_signal", fetch_fresh_wiki,
                          "Recent Wikipedia articles with attribution; wording may reuse older sources. Not guaranteed unseen."),
    "titanic": TestSet("titanic", "csv", "strong_memorization", fetch_titanic,
                       "The Kaggle Titanic table, copied into countless repositories and notebooks."),
}


def testset_dir(name: str, root: str = "data/testsets") -> str:
    return os.path.join(root, name)
