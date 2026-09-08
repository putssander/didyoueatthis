# didyoueatthis

*Did a language model eat your document?* Live page: https://putssander.github.io/didyoueatthis/

Evidence-graded tests for one question: **does a language model reproduce content it could only have seen by
training on (a copy of) this document or table?**

The two literature surveys in [docs/deepresearch/](docs/deepresearch/) establish that training-set *membership*
cannot be proven from outside a closed model, but *verbatim reproduction of rare content, absent on matched
controls* can be measured and graded. didyoueatthis does that for free text and for CSV tables, calibrates the
procedure on material with known status, and reports an evidence category with confidence intervals.

Three ways to use it:

| | what | needs |
|---|---|---|
| **Static page** ([docs/index.html](docs/index.html)) | paste a document and a control, add your own API keys, get a graded report in the browser. Host on GitHub Pages; no backend. **Manual mode** needs no key: it generates prompts to paste into any chat UI and scores the pasted replies. | a browser (and a vendor key, or a chat account) |
| **CLI** (`didyoueatthis text`, `didyoueatthis csv`, `didyoueatthis testsets`) | the same tests from files, with a response cache, local open-weight models, calibration sets and log-probabilities where available | Python 3.11/3.12, `uv` |
| **Local web UI** (`didyoueatthis serve`) | the static page's workflow backed by the CLI machinery | as CLI |

## What the report says, and does not say

Each model gets a verdict that is an *evidence category*, never a probability:

| verdict | meaning |
|---|---|
| `strong_memorization` | >= 3 independent passages (or rows) reproduced verbatim; the matched control reproduces none. The model has seen this text or a copy of it. |
| `memorization_signal` | at least one verbatim reproduction above control; needs more passages or a second model |
| `no_signal` | nothing above control. **Not evidence of absence.** |
| `inconclusive` | too few valid answers |

Every rate carries an exact 95% confidence interval; hits are counted once per passage or row, not per prompt;
and every run carries its own chance baseline (a control document, a paraphrase tier, or synthetic rows).
[docs/01-design.md](docs/01-design.md) gives the reasoning and the failure modes; read it before quoting a result.

## Quick start

```bash
uv sync --extra dev            # pinned environment
uv run pytest -q               # mock provider, no keys, no network
cp .env.example .env           # add OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY as available
uv run didyoueatthis models       # which providers are usable

# 1. Calibrate: known positive, known negative, known-positive table
uv run didyoueatthis testsets run gutenberg  --models openai:gpt-5 anthropic:claude-opus-5
uv run didyoueatthis testsets run fresh-wiki --models openai:gpt-5 anthropic:claude-opus-5
uv run didyoueatthis testsets run titanic    --models openai:gpt-5 anthropic:claude-opus-5

# 2. Your document, with a matched control believed unseen and a paraphrase tier
uv run didyoueatthis text --doc paper.txt --control control.txt \
    --models openai:gpt-5 anthropic:claude-opus-5 google:gemini-2.5-pro --paraphrase-with openai:gpt-5

# 3. A table (synthetic control rows are built automatically)
uv run didyoueatthis csv --file mytable.csv --models openai:gpt-5
```

Models are addressed as `<provider>:<model id>`: `openai:`, `anthropic:`, `google:`, `local:` (any
OpenAI-compatible server such as vLLM or Ollama, via `LOCAL_OPENAI_BASE_URL`), `mock:` (deterministic fake for
tests). A run writes `results/<run>/probes.jsonl`, `responses.jsonl` (every answer verbatim, with vendor
metadata; also the cache), `scores.jsonl`, `report.json` and `report.md`.

## How the test works

1. **Passages.** Distinctive passages are selected across the document (headings, boilerplate and duplicates
   skipped). Each is cut into a prefix and a hidden 40-word suffix.
2. **Prefix sweep.** The model is asked, at zero temperature where the vendor allows it, to continue verbatim
   after 16, 32, 64 and 128 words of prefix. Extractable memorisation rises with prefix length; a hit rate that
   climbs with it is the signature.
3. **Exact scoring.** A hit is 20 leading words of the suffix reproduced exactly. Fuzzy similarity is reported
   but never drives a verdict: understanding a topic yields paraphrase, only exposure yields wording.
4. **Controls in the same run.** A matched control document (best: written after the model's cutoff, or your own
   unpublished text), an optional paraphrase tier (same content, new wording), and for tables synthetic rows
   with the same schema. Every answer is also scored against the wrong passage's truth (permutation null).
5. **Grading.** Clopper-Pearson intervals on per-passage hit rates; the verdict rules are in
   [docs/01-design.md](docs/01-design.md) section 4.

Tables use the same idea with rows: header, *k* preceding rows in file order, the first column of the target
row, and the model completes the line. Names, ticket numbers and timestamps are high-entropy; one exact row is
already informative.

## Calibration sets

Run these before trusting a verdict on your own material ([docs/04-test-sets.md](docs/04-test-sets.md)):

| set | kind | expected | why |
|---|---|---|---|
| `gutenberg` | text | `strong_memorization` | four public-domain novels; in every corpus, duplicated thousands of times |
| `fresh-wiki` | text | `no_signal` | Wikipedia articles created in the last days, fetched live; also the generic prose control |
| `titanic` | csv | `strong_memorization` | the Kaggle Titanic table; high-entropy fields, copied everywhere |

Published membership-inference benchmarks (WikiMIA, BookMIA, MIMIR) are deliberately not included: released in
2023-2024, they are now inside every corpus, so their "non-member" halves are members for current models.

## The static page on GitHub Pages

The page runs the whole test in the
browser: passage selection, prompting, scoring and statistics are a JavaScript port of `core/text.py` and
`core/scoring.py` (checked against scipy to four decimals), and the API key goes from the browser directly to
the vendor (Anthropic requires the `anthropic-dangerous-direct-browser-access` header, which the page sets).
It has a one-click known positive (Pride and Prejudice, embedded) and fetches fresh Wikipedia articles as a
control from the Wikipedia API. Results download as JSON. Use a low-limit key made for this purpose.

**Without a key**, tick *Manual mode*: the page generates numbered, self-contained prompts (6 passages, 64-word
prefix by default, so about a dozen prompts with a control), each copyable; paste them one per fresh chat into
ChatGPT, Claude, Gemini or anything else, paste the replies back (per row, or all at once with the
`##### ANSWER n #####` markers) and score locally. The CLI equivalent is `didyoueatthis manual export` /
`didyoueatthis manual score`. Chat products may have web search or memory switched on; turn those off, because
a retrieved quotation is not a memorised one.

## Data policy

The document you paste or pass is sent to the models you select; use documents you own or are authorised to
test, and read the vendor's terms on automated querying. For material under a data-use agreement, build probes
with `tier="restricted"`: the runner then refuses to send prompts that embed the material to cloud endpoints
unless explicitly allowed, and lets them go to local models. `data/` and `results/` are git-ignored because they
hold fetched texts and verbatim model answers.

## Repository layout

```
docs/
  index.html              static client (GitHub Pages)
  01-design.md            what is measured, controls, confidence, verdict rules, failure modes
  04-test-sets.md         calibration sets, matching controls to targets, why MIA benchmarks are excluded
  deepresearch/           the two literature surveys this is built on
src/didyoueatthis/
  core/probe.py           Probe / Response data model (tier, group, contains_source)
  core/text.py            document -> distinctive passages -> prefix/suffix probes; paraphrase tier
  core/table.py           CSV row-continuation probes and synthetic control rows
  core/scoring.py         exact-match scoring, permutation null, Clopper-Pearson, verdict rules
  core/report.py          JSON + Markdown report
  providers/              openai_, anthropic_, google_, mock; response cache; policy flag per provider
  runner.py               execution with cache, concurrency and the data-policy gate
  testsets.py             gutenberg / fresh-wiki / titanic fetchers and expectations
  cli.py                  didyoueatthis models | text | csv | testsets | manual | rescore | serve
  web/                    FastAPI app + single-page UI (backend variant)
tests/test_pipeline.py    end-to-end with the mock provider, no network
```

## Status (2026-09-08)

- Package, tests, static client, local web UI, CSV family and calibration sets are complete; `uv run pytest`
  passes; fetchers verified against the live sources.
- **No frontier model has been queried yet**: no vendor keys are configured on this machine. Step 1 of the quick
  start is the first real run.
- Not implemented: likelihood scores (Min-K%) on the stored log-probabilities; a base-model (non-chat) endpoint
  for local models; canary generation for future documents.

## People

Sander Puts, 2026-09-08, with AI assistance (Claude) for code and documentation. Literature basis: the two deep
research reports in `docs/deepresearch/` (Carlini et al. 2021/2022, Kandpal et al. 2022, Mattern et al. 2023,
Shi et al. 2024, Zhang et al. 2024, Nasr et al. 2023). Licence: not yet chosen.
