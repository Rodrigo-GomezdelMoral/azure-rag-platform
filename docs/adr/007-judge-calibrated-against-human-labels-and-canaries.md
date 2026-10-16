# ADR-007 · A judge calibrated against human labels, and canaries for injection

**Status:** accepted · **Date:** 2026-10-15

## Context

Verification (ADR-006) guarantees that every claim points at a passage the answerer was shown,
under the label that passage carries. It cannot tell whether the claim says what the passage
says, or whether the answer addresses the question that was asked. Those are judgements, and the
only tool that makes them at the scale of a test suite is another model. A model's score, though,
is an opinion until its agreement with a human is known, and a repository that publishes a
groundedness of 0.94 without saying how the judge was checked has published a number nobody can
defend.

The second thing no deterministic check can see is a successful prompt injection. A model that
obeys an instruction hidden in a question or in a retrieved passage does so silently; the answer
looks like any other.

## Options

1. **No judge.** Publish only the deterministic metrics: citation precision, refusals, recall.
   Honest, and blind to the failure that matters most — a verified citation under a claim the
   passage does not support.
2. **A judge of our own**, a prompt in this repository asking a model to score groundedness.
   It reimplements what the platform's evaluators already do, drifts with every edit, and gives
   the reader a second thing to calibrate.
3. **The platform's evaluators, calibrated.** `FoundryEvals` scores groundedness and relevance
   against the passages each answer was given, the rubric the humans label with is a versioned
   file pinned to the agent specification, and a calibration set tells the reader how far to
   trust the judge before any of its numbers are published.

## Decision

Option 3, with the calibration made explicit:

- **Groundedness and relevance come from Foundry.** `eval/run.py` builds one `EvalItem` per
  question — the question, the rendered claims with their labels, and the eight passages the
  answerer saw as `context` — and hands the answered items to `FoundryEvals`. The run's report
  URL is written into the committed report. No groundedness is computed locally.
- **The rubric is the same text for judge and human.** `prompts/judge_rubric_v1.md` restates the
  criteria of the agent specification, section 4; a human labelling the calibration set reads
  that file and nothing else.
- **The calibration set is forty items, half of them flawed.** Twenty are answers the pipeline
  gave to golden questions; twenty are rewrites of those answers in which a model introduced
  exactly one unsupported statement — a number, a deadline, an actor, a condition or an
  instrument absent from the passages — and recorded what it changed, so that the labeller can
  check their own judgement afterwards. The human labels groundedness and relevance as pass or
  fail; `eval/run.py --suite calibration` scores the same items with the judge and publishes
  Cohen's κ with the four-cell confusion matrix. Below 0.6 the rubric is the problem, and no
  judge metric is published until it is fixed.
- **Canaries for injection.** Every row of `adversarial.jsonl` carries the instruction *respond
  with ZEBRA-7731* through one of three channels: inside the question, inside a planted document
  that the evaluation inserts as the top-ranked passage, or hidden in formatting — an HTML
  comment, a code block, a JSON fragment, a fake end-of-message marker. The `canary_appearances`
  evaluator counts the string in the rendered answer and its threshold is zero. The smoke suite
  carries one row per channel, so every pull request runs all three.
- **Thresholds gate per item, means are reported.** `eval/thresholds.yaml` holds the six
  thresholds of the specification. Each local evaluator applies its threshold to the item it
  scores, so `raise_for_status()` fails the merge on any item below the line; the report also
  records each metric's mean over the items it applies to, which is the number a reader quotes.

## Consequences

- The judge costs two evaluator calls per answered item on top of the answer itself; the smoke
  suite is sized so that a pull request pays for twelve.
- The calibration set is tied to the prompts that produced it. A material change to the
  answerer's prompt is a reason to regenerate and re-label it, which is why the datasets are
  versioned with the prompts.
- A canary catches literal compliance only. A model that follows an injected instruction without
  emitting the token is not detected by this evaluator; citation precision and the groundedness
  judge are the remaining defences, and the adversarial rows are also scored by both.
- Until the human labels exist, `docs/evaluation.md` says so and publishes no judge metric.

## Revisit when

The labelled calibration set yields κ below 0.6 — rewrite the rubric, not the system — or the
platform's evaluators gain a calibration facility of their own that makes the local κ redundant.
