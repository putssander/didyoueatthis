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


OLD_WIKI_TITLES = ["Photosynthesis", "Napoleon", "Mitochondrion", "Ada Lovelace", "Great Barrier Reef", "Bicycle",
                   "Plate tectonics", "Ludwig van Beethoven", "Honey bee", "Printing press", "Mount Everest", "Chess"]
OLD_WIKI_AS_OF = "2021-01-01T00:00:00Z"


def strip_wikitext(w: str) -> str:
    """Wikitext -> plain prose, good enough for passage probes (templates, refs, tables, files, markup removed)."""
    w = re.sub(r"<!--.*?-->", "", w, flags=re.S)
    w = re.sub(r"<ref[^>/]*/>", "", w)
    w = re.sub(r"<ref[^>]*>.*?</ref>", "", w, flags=re.S)
    for _ in range(6):  # nested templates
        w2 = re.sub(r"\{\{[^{}]*\}\}", "", w)
        if w2 == w:
            break
        w = w2
    w = re.sub(r"\{\|.*?\|\}", "", w, flags=re.S)                 # tables
    w = re.sub(r"\[\[(?:File|Image|Category)[^\]]*\]\]", "", w, flags=re.I)
    w = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", w)         # [[a|b]] -> b
    w = re.sub(r"\[\[([^\]]*)\]\]", r"\1", w)                    # [[a]] -> a
    w = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", w)         # [url text] -> text
    w = re.sub(r"\[https?://\S+\]", "", w)
    w = re.sub(r"<[^>]+>", "", w)                                   # remaining html
    w = re.sub(r"'{2,}", "", w)                                     # bold/italic quotes
    w = re.sub(r"^\s*[*#:;].*$", "", w, flags=re.M)                # lists, definitions
    w = re.sub(r"^==+\s*(.*?)\s*==+\s*$", r"\1", w, flags=re.M)   # headings -> short lines (skipped as headings)
    w = re.sub(r"&nbsp;", " ", w)
    w = re.sub(r"\n{3,}", "\n\n", w)
    return w.strip()


def fetch_old_wiki(dest: str, titles: tuple[str, ...] = tuple(OLD_WIKI_TITLES), as_of: str = OLD_WIKI_AS_OF) -> list[str]:
    """Each article as it stood at `as_of`, from the revision history (plain text via strip_wikitext).

    Stable, famous articles from before every current model's cutoff, mirrored across the web thousands
    of times: the Wikipedia-genre known positive that matches the fresh-Wikipedia control.
    """
    from .core.sources import CC_BY_SA, write_sources
    os.makedirs(dest, exist_ok=True)
    out = []
    for title in titles:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        p = os.path.join(dest, f"{as_of[:10]}_{slug}.txt")
        if not os.path.exists(p):
            q = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": "1", "rvdir": "older",
                 "rvstart": as_of, "rvprop": "ids|timestamp|content", "rvslots": "main", "format": "json", "formatversion": "2"}
            data = json.loads(_get(f"{WIKI_API}?{urllib.parse.urlencode(q)}"))
            page = data["query"]["pages"][0]
            rev = page["revisions"][0]
            text = strip_wikitext(rev["slots"]["main"]["content"])
            if len(text.split()) < 600:
                continue
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{title}\n\n{text}")
            write_sources(p, [{"title": title, "author": "Wikipedia contributors", "url": f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&oldid={rev['revid']}",
                               "history_url": f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&action=history",
                               "revision_observed": rev["revid"], "revision_timestamp": rev["timestamp"], "retrieved": time.strftime("%Y-%m-%d"),
                               "license": "CC BY-SA 4.0", "license_url": CC_BY_SA,
                               "changes": "Historical revision; wikitext markup, templates, references and tables removed; excerpted.",
                               "notice": "Check third-party quotations separately. No Wikimedia endorsement."}])
            time.sleep(1.0)
        out.append(p)
    return out


STABLE_DATES = ("2020-01-01T00:00:00Z", "2023-01-01T00:00:00Z", "2025-01-01T00:00:00Z", None)  # None = current


def _revision_text(title: str, as_of: str | None) -> tuple[str, int, str]:
    q = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": "1", "rvdir": "older",
         "rvprop": "ids|timestamp|content", "rvslots": "main", "format": "json", "formatversion": "2"}
    if as_of:
        q["rvstart"] = as_of
    data = json.loads(_get(f"{WIKI_API}?{urllib.parse.urlencode(q)}"))
    rev = data["query"]["pages"][0]["revisions"][0]
    return strip_wikitext(rev["slots"]["main"]["content"]), rev["revid"], rev["timestamp"]


def fetch_stable_wiki(dest: str, titles: tuple[str, ...] = tuple(OLD_WIKI_TITLES), dates=STABLE_DATES) -> list[str]:
    """Only the paragraphs of each article that are byte-identical across every snapshot date.

    Wikipedia is dynamic, and a model's crawl may predate its cutoff by a long way; a paragraph that has not
    changed since 2020 was seen in this exact wording by every crawl since. Paragraphs are compared after
    whitespace normalisation; each file records the stable share and the revision ids used.
    """
    from .core.sources import CC_BY_SA, write_sources
    os.makedirs(dest, exist_ok=True)
    out = []
    for title in titles:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        p = os.path.join(dest, f"stable_{slug}.txt")
        if not os.path.exists(p):
            snaps = []
            for d in dates:
                text, revid, ts = _revision_text(title, d)
                snaps.append((text, revid, ts))
                time.sleep(1.0)
            paras = [[re.sub(r"\s+", " ", x).strip() for x in t.split("\n\n")] for t, _, _ in snaps]
            common = set(paras[0])
            for ps in paras[1:]:
                common &= set(ps)
            stable = [x for x in paras[0] if x in common and len(x.split()) >= 40]   # keep the 2020 order
            words_all = sum(len(x.split()) for x in paras[0] if len(x.split()) >= 40)
            words_stable = sum(len(x.split()) for x in stable)
            if words_stable < 400:
                print(f"stable-wiki: {title}: only {words_stable} stable words, skipped", file=sys.stderr)
                continue
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{title}\n\n" + "\n\n".join(stable))
            write_sources(p, [{"title": title, "author": "Wikipedia contributors",
                               "url": f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&oldid={snaps[0][1]}",
                               "history_url": f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&action=history",
                               "revisions_compared": [{"revid": r, "timestamp": ts} for _, r, ts in snaps],
                               "stable_words": words_stable, "words_in_2020_revision": words_all,
                               "retrieved": time.strftime("%Y-%m-%d"), "license": "CC BY-SA 4.0", "license_url": CC_BY_SA,
                               "changes": "Only paragraphs identical across the compared revisions; markup, templates, references and tables removed.",
                               "notice": "Check third-party quotations separately. No Wikimedia endorsement."}])
            print(f"stable-wiki: {title}: {words_stable}/{words_all} words unchanged 2020-2026", file=sys.stderr)
        out.append(p)
    return out


HF_ROWS = "https://datasets-server.huggingface.co/rows"
CONTROLS_DIR = os.path.join(os.path.dirname(__file__), "controls")


def _hf_rows(dataset: str, config: str, split: str, n: int) -> list[dict]:
    rows = []
    for offset in range(0, n, 100):
        q = urllib.parse.urlencode({"dataset": dataset, "config": config, "split": split, "offset": offset, "length": min(100, n - offset)})
        rows += [r["row"] for r in json.loads(_get(f"{HF_ROWS}?{q}"))["rows"]]
        time.sleep(0.5)
    return rows


def _write_docs(dest: str, name: str, texts: list[str], source: dict) -> list[str]:
    from .core.sources import write_sources
    os.makedirs(dest, exist_ok=True)
    out = []
    for i, t in enumerate(texts):
        p = os.path.join(dest, f"{name}_{i:03d}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.strip() + "\n")
        write_sources(p, [source])
        out.append(p)
    return out


def fetch_enron(dest: str, n_emails: int = 40, min_words: int = 120) -> list[str]:
    """Real Enron employee emails (AESLC subset, Zhang & Tetreault 2019), public since the 2003 FERC release.

    Private correspondence when written, public record for two decades, and inside every large corpus. A model
    that completes a specific email from its opening trained on people's mail; time has removed the sensitivity,
    not the lesson.
    """
    rows = _hf_rows("Yale-LILY/aeslc", "default", "train", 400)
    texts = [re.sub(r"[ \t]+", " ", r["email_body"]).strip() for r in rows]
    texts = [t for t in texts if len(t.split()) >= min_words][:n_emails]
    return _write_docs(dest, "enron", texts, {"title": "Enron email (AESLC subset)", "author": "Enron employees; corpus released by FERC (2003), AESLC by Zhang & Tetreault (2019)",
                                             "url": "https://huggingface.co/datasets/Yale-LILY/aeslc", "license": "Public record; AESLC distributed for research",
                                             "changes": "Whitespace normalised; excerpted.", "notice": "Contains real names of former employees; do not redistribute replies beyond what the check needs."})


def fetch_gsm8k(dest: str, n: int = 40, min_words: int = 45) -> list[str]:
    """GSM8K *test* questions (MIT licence). A benchmark's held-out set is exactly what a model should not have
    studied; completing a question's exact wording from its first half is contamination, not arithmetic."""
    rows = _hf_rows("openai/gsm8k", "main", "test", 300)
    texts = [re.sub(r"\s+", " ", r["question"]).strip() for r in rows]
    texts = [t for t in texts if len(t.split()) >= min_words][:n]
    return _write_docs(dest, "gsm8k", texts, {"title": "GSM8K test question", "author": "Cobbe et al. (OpenAI), 2021",
                                             "url": "https://huggingface.co/datasets/openai/gsm8k", "license": "MIT", "license_url": "https://opensource.org/license/mit",
                                             "changes": "Whitespace normalised; the question text only.", "notice": ""})


def control_docs(name: str, root: str = "data/testsets") -> list[str]:
    """Genre-matched, unpublished controls shipped with the package (written for this project, CC0).

    The file holds one control text per paragraph (after the first, explanatory paragraph); each becomes its
    own document so that every control text is an independent group, like the target documents."""
    text = open(os.path.join(CONTROLS_DIR, name), encoding="utf-8").read()
    paras = [x.strip() for x in text.split("\n\n") if x.strip()][1:]
    dest = os.path.join(root, "controls", name.replace(".txt", ""))
    os.makedirs(dest, exist_ok=True)
    out = []
    for i, para in enumerate(paras):
        pth = os.path.join(dest, f"control_{i:02d}.txt")
        if not os.path.exists(pth):
            with open(pth, "w", encoding="utf-8") as f:
                f.write(para + "\n")
        out.append(pth)
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
    control: str = "fresh-wiki"  # "fresh-wiki", or a file name under controls/ (genre-matched, unpublished)
    prefix_words: str = "16,32,64,128"
    suffix_words: int = 40
    hit_words: int = 20
    passages: int | None = None  # per document; None = the CLI default


SETS: dict[str, TestSet] = {
    "gutenberg": TestSet("gutenberg", "text", "strong_memorization", fetch_gutenberg,
                         "Four nineteenth-century novels; plausible positive references. Check local public-domain and edition rights."),
    "fresh-wiki": TestSet("fresh-wiki", "text", "no_signal", fetch_fresh_wiki,
                          "Recent Wikipedia articles with attribution; wording may reuse older sources. Not guaranteed unseen."),
    "old-wiki": TestSet("old-wiki", "text", "strong_memorization", fetch_old_wiki,
                        "Famous Wikipedia articles as of 2021-01-01, before every current cutoff and mirrored everywhere: the Wikipedia-genre positive."),
    "stable-wiki": TestSet("stable-wiki", "text", "strong_memorization", fetch_stable_wiki,
                           "Paragraphs of famous Wikipedia articles unchanged from 2020 to today: seen in this wording by every crawl."),
    "enron": TestSet("enron", "text", "memorization_signal", fetch_enron,
                     "Real Enron emails (public record since 2003): were models trained on people's private mail?",
                     control="emails.txt", prefix_words="32,64", suffix_words=30, hit_words=15, passages=1),
    "gsm8k": TestSet("gsm8k", "text", "memorization_signal", fetch_gsm8k,
                     "GSM8K held-out test questions (MIT): does the model know the exam by heart?",
                     control="word-problems.txt", prefix_words="16,32", suffix_words=20, hit_words=12, passages=1),
    "titanic": TestSet("titanic", "csv", "strong_memorization", fetch_titanic,
                       "The Kaggle Titanic table, copied into countless repositories and notebooks."),
}


def testset_dir(name: str, root: str = "data/testsets") -> str:
    return os.path.join(root, name)
