# ADR-010 · Rejection: `AzureAISearchContextProvider` hides candidate scores and chunk identity

**Status:** accepted — the alternative is rejected · **Date:** 2026-10-15

## Context

Microsoft Agent Framework ships a context provider for Azure AI Search. Attached to an agent, it
runs a search for every turn, folds the passages it finds into the model's context and lets the
agent answer with them. It is the shortest path to a grounded answer in this framework — a
constructor call and a `context_providers=[...]` argument — and it is exactly the kind of
capability this repository's working agreement says not to reimplement.

This repository reimplements it anyway, as `Retriever` (ADR-004) and the `search` and `rerank`
phases of `app/answer.py`. This document records why that is not a contradiction.

## What the provider does not give back

A context provider contributes messages to a model call and returns nothing to the code that
made the call. From the pipeline's point of view, retrieval happens inside the agent's turn and
leaves no trace that can be inspected, scored or checked:

- **No candidate list.** The thirty hybrid candidates, their `@search.score` values, the
  semantic ranker's scores and the order after reranking never exist as data. The retrieval debug
  panel, the Recall at 10 and nDCG metrics and the reranker experiment all need exactly that list.
- **No chunk identity.** The answerer cites by `chunk_id` and `citation_label`, and `verify()`
  keeps a claim only when the ids it cites were among the passages shown and the labels match.
  With the provider, the passages shown are prose inside the context; there is no id to cite and
  nothing to verify against. The product's central promise — a claim is shown only when its
  citation was checked — cannot be kept.
- **No control over the query.** The planner's rewrite, the OData filters and the choice between
  the semantic ranker and the agent reranker are decisions the pipeline makes before the model is
  called. The provider makes its own.
- **No separation of history and evidence.** The provider contributes to the same context as the
  conversation history. Here the planner is the only agent with history and the answerer is the
  only agent that sees regulatory text; the privacy requirement is met by that topology, and a
  provider on either agent would merge the two.

## Decision

Rejected. Retrieval is one explicit call in `app/retrieval.py` whose result — ids, labels,
scores — flows through the `search` and `rerank` events to verification, to the interface and to
the evaluation harness. The cost is about eighty lines, which is the budget ADR-004 spends on the
one abstraction the repository owns.

## What would change the decision

A provider that returned its candidates as data — ids, scores, the rendered context — alongside
the model's response, so that verification and the metrics could run on them. The framework's
evaluation types already carry a `context`; a provider that exposed what it put there would
remove most of this repository's reason to own a retriever.
