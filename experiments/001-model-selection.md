# Experiment 001 · `gpt-5-mini` versus `gpt-5-nano` as the Answerer

**Date:** 2026-10-15 · **Decision:** keep `gpt-5-mini` · **Change under test:** one setting,
`CHAT_DEPLOYMENT=gpt-5-nano` (`app/config.py`)

**Reports:** `docs/reports/2026-10-15-golden-gpt-5-mini-semantic.json` and
`docs/reports/2026-10-15-golden-gpt-5-nano-semantic.json`

## Hypothesis

The Answerer's task is narrow. It receives eight passages, each with a `chunk_id` and a
`citation_label`, and writes one claim per label with the ids and the label copied character for
character. `verify()` then keeps only the claims whose ids are in the evidence and whose label is
the evidence's own. Because that check is deterministic, groundedness should not depend on the
model: a weaker model loses claims to verification, it does not get them published. If
`gpt-5-nano`, at a fifth of the price (€0.044 and €0.352 per million input and output tokens
against €0.22 and €1.76 for `gpt-5-mini`, Sweden Central, 2026-10-14), holds the copy-exactly
discipline, the cheap option is good enough and the saving is about €2 per thousand answers.

## Method

Both runs used the eighty-item golden set, the deployed index `regulations`, the planner on
`gpt-5-nano`, the semantic reranker, the same prompts, reasoning effort `low`, and three questions
in flight. They were started thirteen minutes apart on the same evening:

```
python -m eval.run --suite golden
CHAT_DEPLOYMENT=gpt-5-nano python -m eval.run --suite golden
```

The local metrics are those of `eval/evaluators.py`; groundedness and relevance come from
`FoundryEvals` over the answered items on a 1–5 scale, reported divided by five. Cost is computed
from the token counts the framework returns at the Retail Prices above; latency is the sum of the
five phase timings the pipeline records.

Three caveats bound what the numbers can say. The golden set is generated and **not yet verified
by a human** (`eval/datasets/REVIEW.md`), so the comparison is between the two variants, not a
statement of the system's quality. Each variant was run **once**, and the planner's query rewrite
is not deterministic: four smoke runs on the same day moved recall at 10 by 0.17
(`docs/evaluation.md`), so on eighty items a difference of one or two items (0.0125 to 0.025) is
noise. And the judge scores only the items that were answered, so a variant that refuses more
often is judged on fewer, easier items.

## Results

| Metric | `gpt-5-mini` | `gpt-5-nano` | Difference |
|---|---|---|---|
| Items answered, scored by the judge | 67 | 53 | −14 |
| Groundedness (judge, 0–1) | 0.979 | 0.940 | −0.039 |
| Relevance (judge, 0–1) | 0.896 | 0.853 | −0.043 |
| Citation precision (verified ÷ drafted claims) | 0.935 (n 69) | 0.690 (n 70) | −0.245 |
| Items below the 0.95 precision line | 9 | 27 | +18 |
| False refusals (answerable, golden passage retrieved, refused) | 1 of 80 | 13 of 80 | +12 |
| Recall at 10 | 0.700 | 0.713 | one item; planner noise |
| Canary appearances | 0 | 0 | — |
| Cost per answer, mean | €0.0025 | €0.0006 | −76 % |
| Latency per answer, mean | 12.0 s | 12.4 s | +0.4 s |

Recall at 10 is the same in both runs, as it must be: the Answerer runs after retrieval and the
same twenty-three items were missed by both (`experiments/002-reranking.md` examines them). The
one-item difference is the planner's rewrite varying between runs.

**What verification removed.** `gpt-5-mini` lost 6.5 % of its drafted claims to `verify()`;
`gpt-5-nano` lost 31 %. The failure is the one the hypothesis depended on: `gpt-5-nano` writes a
claim that rests on a passage and then cites it under a neighbouring label, or writes one claim
across passages that carry two labels, and the claim is discarded. In thirteen of eighty cases
every drafted claim was discarded, so the pipeline returned a typed refusal although the golden
passage was in the evidence. A refusal on an answerable question is the worst outcome the system
can produce short of an unverified statement: the reviewer opens the regulation and reads it
alone, which is what the platform exists to shorten.

**What survived was grounded.** Groundedness of the published claims stayed at 0.94 for
`gpt-5-nano` and 0.98 for `gpt-5-mini`; the floor is verification, not the model, as predicted.
The difference is in how much gets through the floor, not in the quality of what does.

**Cost and latency.** The Answerer is the expensive call of the pipeline; replacing it took the
per-answer cost from €0.0025 to €0.0006, a saving of about €1.9 per thousand answers. Latency did
not move: both models answer in about twelve seconds end to end at `low` reasoning effort, so the
model is not the lever for latency either. A second, smaller sample taken an hour later on the
first twelve golden questions, two in flight, breaks the latency down by phase and shows the same
shape at a slower hour of the service:

| Sample of 12, by phase | `gpt-5-mini` | `gpt-5-nano` |
|---|---|---|
| End to end, mean · median | 16.6 s · 17.5 s | 17.8 s · 16.3 s |
| Answer phase, mean | 11.1 s | 8.6 s |
| Verified claims per answer, mean | 3.2 | 1.2 |
| Refusals among the twelve | 1 | 6 |
| Cost per answer, mean | €0.0032 | €0.0007 |

The answer phase is two and a half seconds shorter with `gpt-5-nano` and the question takes as
long to answer, because the planner and the search, which did not change, are the rest of the
time. Half of the twelve ended in a refusal; the eighty-item run put the rate at one in six.

## Decision

`gpt-5-mini` stays as the Answerer. The saving is €1.9 per thousand questions; the price is about
150 more refusals per thousand on questions the corpus answers. A reviewer who has to look up one
of those refusals by hand spends at least a minute, which at the hourly rates the README quotes
costs more than the whole saving on the first few items.

`gpt-5-nano` remains the planner, where it was chosen in phase 4: a structured query plan is a
small task, and the identical recall of both runs shows the planner was not what changed here.

## What would reopen this

- A verified golden set: these are relative numbers on unreviewed pairs.
- A prompt revision aimed at `gpt-5-nano`'s label copying, which is a different experiment: this
  one tested the specification's one-line change and nothing else.
- A rerun with a run-to-run variance estimate, once the planner's rewrite is stabilised; until
  then, differences under 0.03 on this set are not differences.
