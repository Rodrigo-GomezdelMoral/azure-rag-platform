# ADR-005 · Streaming progress, not tokens

**Status:** accepted · **Date:** 2026-10-15

## Context

Every chat product streams tokens, and the framework makes it one flag away. The first words of an
answer appear within a second and the interface feels alive. This system, however, promises that
every sentence it shows carries a citation that was checked. Verification (ADR-006) runs after the
answerer has finished, and it drops claims. A token stream would show a reader a claim, let them
start reading it, and then withdraw it — or, worse, not withdraw it, because the interface already
rendered it.

A reader also waits longer here than in a chat: a planner call, a hybrid query, a rerank, an
answer and a verification, some twenty seconds on the semantic path. Twenty silent seconds is a
broken product; twenty seconds with a visible pipeline is an engineering tool.

## Options

1. **Stream tokens.** Fastest first byte. The answer appears before it is verified and the
   interface has to retract text.
2. **Return one response at the end.** Correct and simple. Twenty seconds of nothing, and none of
   the retrieval detail that the debug panel needs.
3. **Stream phase events.** One server-sent event per phase — plan, search, rerank, answer,
   verify — each carrying what that phase produced: the rewritten query and filters, every
   candidate with its hybrid score, the reranked set with rerank scores and signed rank changes,
   the number of claims drafted, and finally the verified answer with citations, refusal reason,
   unverified-claim count, cost and per-phase timings.

## Decision

Option 3. `POST /v1/answer` responds with `text/event-stream`; each event is named by its phase
and carries a `PhaseEvent` as JSON. The `answer` event carries only a count of drafted claims.
The text of a claim appears exactly once, in the `verify` event, after verification has kept it.
There is no code path that emits partial answer text: the answerer runs with `stream=False`, and
the pipeline is an `async` generator whose yields are the five events and nothing else.

The same events feed the retrieval debug panel. The interface needs original versus rewritten
query, extracted filters, scores before and after reranking and the rank deltas; these are the
contents of the first three events, so the debug panel costs the API nothing extra.

## Consequences

- Time to first byte is the planner's latency, about six seconds with low reasoning effort,
  and the interface fills a timeline from there rather than printing words.
- `POST /v1/retrieve` is the same generator stopped after the rerank event, which gives
  experiments and evaluations the scores without paying for generation.
- Server-sent events need no library: three lines format `event:` and `data:` frames, and the
  browser's `EventSource` is not used because the request is a `POST` with a body — the frontend
  reads the stream with `fetch`.
- A reviewer can verify the claim by reading one function: there is one `yield` per phase, and
  the only one that carries claim text is the last.

## Revisit when

Verification moves inside generation — for example, a model that cites by constrained decoding
against the candidate ids — so that a token is never shown unverified. Until then, progress is the
only thing worth streaming.
