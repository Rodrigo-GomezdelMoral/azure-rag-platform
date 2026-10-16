# Experiment 002 · Semantic ranker versus the agent reranker

**Date:** 2026-10-15 · **Decision:** the semantic ranker stays the default · **Change under
test:** one setting, `RERANKER=agent` (`app/config.py`)

**Reports:** `docs/reports/2026-10-15-golden-gpt-5-mini-semantic.json` and
`docs/reports/2026-10-15-golden-gpt-5-mini-agent.json`

## Hypothesis

Retrieval returns thirty candidates from one hybrid query. With the **semantic ranker**, Azure AI
Search scores them in the same call and the pipeline keeps the first eight; the ranker is part of
the Basic tier's hourly price and adds no latency the caller can see. With the **agent reranker**,
a second `gpt-5-mini` call reads the thirty passages and scores each from 0 to 1 against the
question (`prompts/reranker_v1.md`), and `rerank()` keeps the eight best. The hypothesis is that
a model reading the question and the passage together lifts golden passages from positions nine
to thirty into the eight the Answerer sees, and that the lift in recall at 10 and nDCG at 10 is
worth a second model call per question.

## Method

Same golden set, index, planner, Answerer, prompts, reasoning effort and concurrency as
experiment 001; started twenty-seven minutes after the baseline run:

```
python -m eval.run --suite golden
RERANKER=agent python -m eval.run --suite golden
```

Recall at 10 is measured over the reranked eight followed by the remaining candidates in hybrid
order (`docs/evaluation.md`, known limits), so a golden passage anywhere in the thirty counts at
rank ten or better only if a ranker put it there. The caveats of experiment 001 apply: an
unverified golden set, one run per variant, and a planner whose rewrite moves recall by one or two
items between runs.

## Results

| Metric | Semantic ranker | Agent reranker | Difference |
|---|---|---|---|
| Recall at 10 | 0.700 | 0.713 | +0.013, one item |
| Items whose golden passage was not in the first ten | 24 | 23 | the same 23 items in both |
| nDCG at 10 | see below | see below | not comparable |
| Citation precision | 0.935 (n 69) | 0.926 (n 70) | −0.009 |
| Groundedness (judge, 0–1) | 0.979 (n 67) | 0.979 (n 68) | 0.000 |
| Relevance (judge, 0–1) | 0.896 | 0.906 | +0.010 |
| False refusals | 1 of 80 | 2 of 80 | +1 |
| Canary appearances | 0 | 0 | — |
| Cost per answer, mean | €0.0025 | €0.0104 | ×4.2 |
| Latency per answer, mean | 12.0 s | 44.2 s | +32 s |

**The misses are the same misses.** Twenty-three golden items were missed by both runs, and by
the `gpt-5-nano` run of experiment 001 as well. For those items the golden passage was not among
the thirty hybrid candidates at all, which is why a reranker that reorders those thirty cannot
recover it. By type they are twelve obligations, five procedures, four definitions and two
cross-references; by instrument seven from the AI Act, five from the MDR, seven from MDCG 2019-11
and four from MDCG 2020-1, three of those four from the same section on the general principles of
clinical evaluation. The lever for recall is upstream of either ranker: the planner's query and
the way the corpus is chunked and labelled. The smoke run's finding that definitions are retrieved
poorly (`docs/evaluation.md`) is one face of this; on the golden set definitions were in fact the
best-retrieved type (16 of 20) and obligations the worst (20 of 32), which the human review of the
golden set has to weigh before either figure is trusted.

**nDCG at 10 is not reported from these runs.** The three reports of 2026-10-15 were produced by a
version of `ndcg_at_10` that credited every chunk sharing a golden label, so when several chunks
of the same article ranked in the first ten the metric exceeded its own ideal: the agent run
recorded 1.025, the two semantic runs 0.958 and 0.952. The metric was corrected in this phase to
count each golden label once, at its first rank, and `tests/test_eval.py` covers a duplicated
label. The uncorrected values do say one thing: the agent packed more chunks of an already-found
article into the first ten, without finding any article the hybrid query had missed. The gain in
rank quality is therefore cosmetic for a pipeline that already keeps eight passages.

**The Answerer did not benefit.** Groundedness is identical, relevance moved by 0.010 and
citation precision by −0.009, each within one item of the other run. The agent reranker's
ordering changed which eight passages the Answerer read without changing what it could say.

**What it cost.** The reranker is a second `gpt-5-mini` call that reads thirty passages, so its
input tokens alone exceed the Answerer's: the mean cost per answer went from €0.0025 to €0.0104,
€10.4 per thousand questions against €2.5. Latency went from twelve seconds to forty-four. A
smaller sample taken an hour later on the first twelve golden questions, two in flight, shows
where the time goes:

| Sample of 12, by phase | Semantic ranker | Agent reranker |
|---|---|---|
| End to end, mean · median | 16.6 s · 17.5 s | 43.1 s · 42.6 s |
| Rerank phase, mean | 0 s (inside the search call) | 23.4 s |
| Answer phase, mean | 11.1 s | 13.0 s |
| Verified claims per answer, mean | 3.2 | 4.0 |
| Refusals among the twelve | 1 | 1 |
| Cost per answer, mean | €0.0032 | €0.0104 |

The reranking phase alone takes longer than the whole pipeline without it, and the interface,
which streams phase events rather than tokens (ADR-005), would show it as the longest bar on the
timeline. The Answerer wrote slightly more claims from the agent's selection, and the same number
survived verification in proportion, which is the −0.009 in citation precision above.

## Decision

The semantic ranker stays the default. The agent reranker moved recall at 10 by one item, inside
the planner's run-to-run noise, for four times the cost and three and a half times the latency.
The cheap option was good enough, and the measurement says why: the recall the pipeline is
missing is not in the thirty candidates either ranker sees.

`RERANKER=agent` remains a setting because it costs one function and no abstraction (ADR-004),
and because the experiment should be run again when two things change: the golden set is
verified, and the planner's rewrite is stable enough that a one-item difference means something.
It is not recommended for any share of traffic.

## What would reopen this

- A retrieval change that puts the missing twenty-three passages among the candidates, after
  which a reranker would have something to lift.
- A reranker that reads more than thirty candidates, which trades the latency measured here for
  the chance of recovering passages at ranks thirty to fifty; the cost would scale with it.
- Human verification of the golden set, without which none of these recalls is a statement about
  the system.
