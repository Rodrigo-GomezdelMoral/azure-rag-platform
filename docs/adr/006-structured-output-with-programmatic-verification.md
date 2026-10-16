# ADR-006 · Structured output with programmatic verification

**Status:** accepted · **Date:** 2026-10-15

## Context

The product rule is that an answer without a citation to the exact article is worthless and a
hallucination is an audit finding. Prompting alone cannot deliver that rule: a model asked to
"always cite" will cite, and some of the citations will point at passages that do not say what
the claim says, or at passages it was never shown. The system therefore needs a representation of
the answer that can be checked, and a check that is not performed by a model.

## Options

1. **Free text with inline citation markers**, parsed with regular expressions. Fragile at the
   parsing step, and the marker can be present while the content is invented.
2. **A judge model** that reads the answer and the passages and scores groundedness. Useful for
   evaluation, where it is used (ADR-007); unacceptable as the gate in front of every answer,
   because it is another model's opinion, costs a second generation and cannot be unit-tested.
3. **Structured output, then a deterministic check.** The answerer returns a `Draft`: a list of
   claims, each with the ids of the passages that support it and the citation label copied from
   them. A function then keeps a claim only if every cited id is among the passages the answerer
   was shown **and** the label matches the one those passages carry.

## Decision

Option 3. Three mechanisms, each in its own place:

- **The schema is the contract.** `Draft`, `Claim`, `Ranking` and `QueryPlan` are Pydantic
  models passed as the framework's `response_format` on every call, and `run()` reads
  `response.value` and validates it — it never parses text. The framework and the model API
  enforce the shape; the application enforces the meaning.
- **The check is a function.** `verify(draft, evidence)` is nine lines: a dictionary of label by
  chunk id over the evidence, a comprehension that keeps the claims whose ids all resolve to the
  claim's label, and a count of what was dropped. It runs inside the `verify` span and increments
  the `app.unverified_claims` counter so that the rate of dropped claims is a metric, not an
  anecdote.
- **The outcome is typed.** An answer with no surviving claims is a refusal with a reason:
  `no_evidence` when retrieval returned nothing or the answerer wrote nothing, `unverified` when
  it wrote claims and verification removed them all, `content_filter` when the model API
  refused. A refusal is a correct outcome and renders as one; it is not an error.

Why labels as well as ids: an id proves the passage was shown; the label proves the claim points
where the answerer says it points, and it is the string a reader checks. A model that cites a real
passage under the wrong article has still misled the reader, and the label test catches it. The
first live run of the pipeline dropped exactly one claim for that reason — it cited two passages
under one label — which is the mechanism working, not a fault to fix.

## Consequences

- Verification costs no tokens and no time worth measuring; it is set arithmetic.
- The answerer's prompt tells the model the rule, so that it writes one claim per label and does
  not waste claims. A prompt change can raise or lower the drop rate, which is why the counter
  exists and why prompts are versioned files (ADR-008).
- A claim can still be grounded in the wrong way — supported by the passage but not answering
  the question — and that is what the evaluation harness measures with the judge. Verification
  guarantees provenance, not relevance, and the documentation says so.
- The test for this decision injects a fabricated chunk id and asserts that the claim is dropped,
  the counter incremented and a refusal returned when it was the only claim.

## Revisit when

The model API offers citations constrained to the passages it was given, so that provenance is
enforced before the text exists. The label check would then be redundant; until then it is the
line between an answer and an audit finding.
