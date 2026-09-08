# How to test a model’s memory — and interpret the result

Start with the [interactive page](https://sanderputs.com/didyoueatthis/).
Click **Try a book example**, copy its first prompt into a new chat, and paste
the model’s reply back. You can score a single reply to learn the workflow;
a three-passage example is exploratory. Then try your own text, add a closely
matched control, and increase the number of passages.

Turn web search, memory and connected files off. Use a new chat for every
prompt. Never give the model the answer key or upload the complete document:
that would test copying from context instead of possible memorisation.

## What can this tell you?

Exact reproduction of distinctive, withheld text can be evidence consistent
with prior exposure. It cannot identify the training dataset, distinguish
between copies of a work, or exclude other information sources. A correct
name can also be inferred from context; a generic sentence can be predictable.
A refusal or miss does not establish that the model never saw the text.

These are exploratory tests, not a calibrated probability of training-set
membership. [Zhang, Das, Kamath and Tramèr](https://arxiv.org/abs/2409.19798)
explain the difficulty of establishing the relevant false-positive rate;
their [SPY Lab explanation](https://spylab.ai/blog/mia_position/) is a good
first read. Descriptive confidence intervals over sampled passages do not
solve that problem, and passages within a document may be correlated.

## Choose a method by access and question, not a universal ranking

There is no defensible weakest-to-strongest ordering across all models and
texts. A long exact continuation is easy to inspect, while a name or a
probability score answers a different question.

| Method | Available here | What you measure | Main limitation |
|---|---|---|---|
| Continuation | Browser, manual chat, CLI | Exact leading words in a hidden ending | Refusals, predictability, prompt sensitivity |
| Name cloze | Browser, manual chat, CLI | Recovery of a masked name | Names can be inferred or guessed |
| DE-COP-style multiple choice | CLI | Selecting original wording among three rewrites | Paraphrase style can reveal the answer |
| Min-K% | CLI with a compatible local scoring endpoint | Average log-probability of the least-likely tokens | Distribution differences can resemble membership |

### Continuation: inspect the wording

Show a prefix and ask for the next 40 words. By default a hit requires the
first 20 normalised words to match; case and much punctuation are ignored.
Multiple prefix lengths share a hidden ending and count as one passage.
[Carlini et al., *Quantifying Memorization*](https://arxiv.org/abs/2202.07646)
(ICLR 2023; initial preprint 2022) study how context length, duplication and
model scale affect extractability.

The page starts with three passages and a 64-word prefix to keep manual work
small. **Use a fuller test** selects up to 12 passages and a 16/32/64/128-word
sweep. That can generate many prompts: the page shows the actual count before
an API run. Longer, distinctive text usually provides more usable passages.

### Name cloze: one word, different evidence

Mask a name in a roughly 120-word passage and ask for the missing word.
[Chang et al., *Speak, Memory*](https://aclanthology.org/2023.emnlp-main.453/)
(EMNLP 2023) use name cloze to investigate book recall. Our implementation is
an English capitalisation heuristic, not a replication of their full study.
It filters names repeated in the visible passage and obvious multiword-name
clues. Some documents yield few or no eligible prompts.

This task may get answers when a model declines continuation. It does not
eliminate refusals, and a correct name does not prove memory. The browser
requires the reply to be the name, ignoring case and surrounding punctuation;
the CLI’s existing value scorer is more permissive about explanatory text.
The browser reports cloze separately and never labels it strong continuation
evidence. Its signal requires non-overlapping target/control intervals.

### Multiple choice: check the distractors before the score

[Duarte et al., DE-COP](https://arxiv.org/abs/2402.09910) compare original
passages with paraphrases. The CLI implements a simplified four-choice
variant with one seeded ordering per passage, not the complete paper’s
experimental protocol. Uniform random guessing is 25%, but that is not a
reliable baseline when writing style makes the original recognisable.

**Our September 8 calibration demonstrates this limitation.** Models chose
the original on 60–95% of Wikipedia controls. Moreover, 41 of 81 MCQ prompts
had duplicated options. Those historical results are unsuitable for a clean
four-choice interpretation; the current generator rejects duplicate options.
See the [corrected calibration notes](../README.md#cloze-and-multiple-choice-rerun).

```bash
uv run didyoueatthis text --doc book.txt --control matched-control.txt \
  --models openai:gpt-4.1 --methods continuation,cloze,mcq \
  --paraphrase-with openai:gpt-4.1
```

The paraphraser receives source passages. Inspect its rewrites for factual
changes, repeated options and style differences before interpreting scores.

### Min-K%: useful with access to input-token probabilities

[Shi et al., Min-K%](https://arxiv.org/abs/2310.16789) (ICLR 2024) average
the lowest-probability tokens in a supplied text. [Min-K%++](https://arxiv.org/abs/2404.02936)
(ICLR 2025) develops a normalised variant; this repository implements Min-K%,
not Min-K%++.

The CLI uses a compatible local server’s completions endpoint with input
text echo and token log-probabilities. The OpenAI endpoint attempted in this
project rejected that combination; do not assume that log-probabilities for
*generated* tokens score an arbitrary document. Endpoint support varies.

No visible generation is required, so refusal text is not the obstacle.
Alignment can still change token distributions. Min-K% is neither ground
truth nor immune to confounding. The control’s empirical 95th percentile is
a descriptive threshold, **not a guaranteed 5% false-positive rate**.

## Research developments in 2025–2026

- [Cooper et al., open-weight book extraction](https://arxiv.org/abs/2505.12546)
  (2025 preprint) find substantial variation across models and books. The
  [authors’ project website](https://books-memorization.github.io/) makes the
  comparisons accessible. These findings do not imply every model contains
  every famous book.
- [*Extracting books from production language models*](https://arxiv.org/abs/2601.02671)
  (2026) studies extraction with an initial feasibility probe and iterative
  continuation, sometimes using best-of-N prompting. This is a different,
  more extensive experiment than the short browser test.
- [Liu et al., *Alignment Whack-a-Mole*](https://arxiv.org/abs/2603.20957)
  (2026 preprint, under review) report that fine-tuning on plot-summary
  expansion can expose substantial held-out book recall in tested models.
  Their experiments support the possibility of latent recall despite output
  filtering; they do not diagnose the cause of every refusal in this tool.
  `scripts/unlock_finetune.py` is an experimental public-domain preparation
  and legacy OpenAI launch script. The attempted launch was rejected. It is
  **not a working local fine-tuning implementation**; a local adaptation
  requires a separate training pipeline and held-out evaluation.

### The August 2026 reasoning-trace leak

[*Stealing Reasoning Traces from Proprietary LLM APIs*](https://arxiv.org/abs/2608.09867)
(Panfilov et al., August 10, 2026) reports a vulnerability involving replay of
client-held reasoning blocks within a provider’s ecosystem, with disclosure
of reasoning and context data. The authors describe responsible disclosure
and mitigations.

That is a context-confidentiality issue, not a test of whether your document
was in pretraining. This page does not extract hidden reasoning. In API mode,
it scores visible final-answer text only.

## Make the comparison fair

1. **Calibrate the behaviour.** Use public-domain books as plausible positive
   references. If a model will not answer those probes, its silence on your
   writing tells you little. A famous book is not a verified member of every
   undisclosed training corpus.
2. **Match the control.** Match genre, era, length, names and predictability.
   Newly created Wikipedia articles can quote or reuse older sources; their
   creation dates do not establish the age of their wording. They are also a
   poor stylistic match for novels. Carefully chosen unpublished writing is
   often preferable.
3. **Separate missingness from misses.** API errors, empty/truncated output,
   unknown answers and refusals appear in the browser report. A partial run
   cannot become a confident negative. The browser is more conservative here
   than the historical CLI verdict heuristic.
4. **Inspect every claimed hit.** Look for predictable wording and content
   already present elsewhere in the prompt. Search for public copies before
   making source-attribution claims.
5. **Record the setup.** Keep the model ID, date, prompts, settings, answers
   and controls. The browser JSON export includes prompts and held-out
   answers, but no API keys. It does not save your work across reloads.

## Reading the browser result

| Category | Interpretation | Next step |
|---|---|---|
| Exploratory / inconclusive | Too few usable passages, incomplete/unknown replies, or insufficient comparison | Add passages, fix errors, or try a model that answers |
| A signal worth checking | Some continuation evidence, or a cloze gap clearing the browser threshold | Inspect hits and repeat with stronger controls |
| Strong continuation evidence | Several exact continuations clear the browser’s control heuristic | Check confounders; this remains no proof of corpus membership |
| No signal above the control | Completed responses do not clear the heuristic | Do not infer that the text was absent from training |

The full research surveys remain in [deepresearch/](deepresearch/). Treat
paper-specific numbers as results of those experiments, not expected accuracy
for this small tool.
