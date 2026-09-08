# Test sets: calibrating the procedure on material with known status

A verdict on your own document is only as good as the procedure's behaviour on
documents whose status you already know. Run the calibration sets below
against the same models with the same settings *first*. If the known-positive
does not come back `strong_memorization`, the model is refusing or the prompt
is not eliciting recall, and a `no_signal` on your document means nothing. If
the known-negative comes back with hits, the criterion is too loose for that
model or genre and the threshold (`--hit-words`) must go up.

## Sets that can be fetched automatically

| set | kind | expected verdict | why the status is known |
|---|---|---|---|
| `gutenberg` | text | `strong_memorization` | Four public-domain novels (Pride and Prejudice, Moby-Dick, Alice, Frankenstein). Widely circulated original novels; possible positive references, not verified members of every model. Check the edition and public-domain status for your jurisdiction. |
| `fresh-wiki` | text | `no_signal` | English Wikipedia articles created in the last few days, fetched live. Creation dates do not establish unseen wording. Most useful as comparisons for similar encyclopaedia prose; contributor and CC BY-SA notices accompany fetched text. |
| `old-wiki` | text | `strong_memorization` | Twelve famous Wikipedia articles as they stood on 2021-01-01, before every current model's cutoff. Same genre as the fresh-Wikipedia control, so the comparison is fair. Caveat: articles change, and a crawl may predate a cutoff by years, so some 2021 wording may never have been seen. |
| `stable-wiki` | text | `strong_memorization` | The same articles reduced to paragraphs byte-identical across their 2020, 2023, 2025 and current revisions (6 of 12 articles keep 400+ such words). Text unchanged for six years was seen in this exact wording by every crawl, whatever the cutoff; the cleanest Wikipedia-genre positive. |
| `enron` | text | `memorization_signal` | Forty real Enron employee emails (AESLC subset). Private correspondence when written, public record since the 2003 regulatory release, and in every large corpus since. Control: ten business emails written for this project, unpublished. Completing a specific email from its opening means the model trained on people's mail. |
| `gsm8k` | text | `memorization_signal` | Forty questions from the GSM8K *test* split (MIT). A benchmark's held-out set is what a model must not have studied; completing a question's exact wording from its first half is contamination, not arithmetic. Control: fourteen word problems written for this project, unpublished. |
| `titanic` | csv | `strong_memorization` | The Kaggle Titanic table. Passenger names, ticket numbers and fares are high-entropy, and the file sits in an enormous number of public notebooks and repositories. Tests the row-continuation probe with a built-in synthetic control. |

```bash
uv run didyoueatthis testsets list
uv run didyoueatthis testsets run gutenberg  --models openai:gpt-5 anthropic:claude-opus-5   # control: fresh-wiki
uv run didyoueatthis testsets run fresh-wiki --models openai:gpt-5 anthropic:claude-opus-5   # target/control: two halves
uv run didyoueatthis testsets run titanic    --models openai:gpt-5 anthropic:claude-opus-5   # control: synthetic rows
```

Each run prints `CALIBRATION <set> <model>: expected X, got Y -> OK|MISMATCH`.

The Enron and GSM8K sets are the "sensitive then, harmless now" category: material a model arguably should
not have been trained on (private mail; exam questions), whose exposure today harms nobody and whose licence
allows the test. Declassified government documents belong in the same category and are public domain, but
there is no clean programmatic source yet.

## The set only you can supply: your own unpublished text

The cleanest negative is writing that has never left your machine: drafts,
notes, an unpublished manuscript. Use it as `--control` for a target of the
same genre. Its status is certain; every fetched negative is only *almost*
certain (a new Wikipedia article can paste text from an older public source).

## Why the published MIA benchmarks are not wired in

WikiMIA and BookMIA (Shi et al. 2024), MIMIR (Duan et al. 2024) and similar
sets were built with member/non-member labels relative to 2023-era models.
They have since been downloaded, mirrored and quoted; for any model trained
after their release *both* halves are members. Using them as negatives
against a 2026 model would manufacture false "no signal" baselines. They
remain useful for open-weight models with a known, older cutoff, which is a
different study.

## Matching controls to targets

The control's job is to estimate how often the criterion fires on unseen
text *of the same kind*. Mismatched controls mislead in both directions:

| target | good control | poor control |
|---|---|---|
| a 2019 journal article | a 2026 preprint in the same field, same length | fresh Wikipedia (different register) |
| a novel | recent self-published fiction you are sure is unindexed, or your own prose | Gutenberg (that is a positive) |
| a CSV table | the built-in synthetic rows | another public table |
| an internal report | a second internal report | anything public |

## What a calibration cannot tell you

Calibration verifies that the *procedure* separates seen from unseen text for
a given model. It does not calibrate a probability for your document; the
verdict remains an evidence category (docs/01-design.md, section 4), and a
positive still needs a search for other public copies before it is attributed
to your specific file.

## Copyright and source records

See [the source and reuse guide](07-copyright.md). Wikipedia fetches now retain
licence and attribution sidecars; keep them with the text and retain notices
in exports. Older unattributed caches are not selected automatically. The
Titanic CSV remains an optional legacy dataset: verify its particular source
and reuse terms before distributing it. Open availability alone is not a licence.
