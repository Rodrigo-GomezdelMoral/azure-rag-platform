# ADR-004 · One abstraction seam

**Status:** accepted · **Date:** 2026-10-15

## Context

A retrieval-augmented service grows abstractions by reflex. An `LLMClient` protocol "so we can
swap models". A `VectorStore` interface "so we are not locked in". A `PromptTemplate` class, a
`Pipeline` with `Step`s, a `Reranker` hierarchy. Each one is a seam nobody pulls, a file a reader
has to open to find out that it forwards to the SDK, and the first thing to rot when the SDK
changes underneath it. This repository has a thousand lines of Python in total and a reader who
counts them, so every abstraction has to pay for its lines with a decision it makes possible.

This document is about the abstractions that are **absent**, and about the one that is not.

## The test

An interface is owned by this repository only when all three hold today, not in a hypothetical
future:

1. Two implementations exist and are both used.
2. They differ in kind, not in configuration — different data, different service, different
   failure modes — so that a parameter would not express the difference.
3. The caller has to see something through the interface that the underlying SDK would hide.

## Candidates that fail the test

**The chat client.** Microsoft Agent Framework already is the seam. `FoundryChatClient` and
`OllamaChatClient` both satisfy the framework's client protocol, and `Agent` does not know which
one it holds. Swapping a model provider is one constructor call in `app/clients.py`, chosen by a
setting. A protocol of our own would duplicate the framework's, and lag it: the framework renamed
its types several times before 1.0, and a wrapper written against any of those names would have
broken on every rename while the agents behind it kept working. The framework's types therefore
appear in our signatures — `Agent`, `AgentSession`, `UsageDetails` — and when they change, our
code changes with them, openly.

**The reranker.** Two rerankers exist, the search service's semantic ranker and the `Reranker`
agent, and both populate `rerank_score`. They fail the second test: they differ in where a score
comes from, not in what the caller does with it. The semantic score arrives inside the search
response; the agent score is one structured call. One function, `rerank(candidates, k, scores)`,
expresses both, and comparing them is calling it twice. A `Reranker` protocol would add a class
per reranker to carry one dictionary.

**Conversation history.** `CosmosHistoryProvider` is the framework's context provider; the
planner is built with it or without it. There is nothing to abstract.

**Prompts.** Files, read by one function (ADR-008). No template engine, no class.

**The pipeline.** A function (ADR-003). Five steps in a fixed order with no branching do not need
a step interface, and `PhaseEvent` is the whole contract between the pipeline and its callers.

**Storage for feedback.** One container, one write, in the route that receives the feedback.

## The one that passes

`Retriever`, a protocol with one method: `search(plan, k) -> list[Chunk]`.

1. Two implementations are used: `SearchRetriever`, which runs one hybrid query with semantic
   ranking and OData filters against Azure AI Search, and `LocalRetriever`, which scores a
   committed sample of chunks by term overlap so that the service runs with no Azure account —
   the Codespaces demo and the unit tests.
2. They differ in kind. One is a network call to a service with its own scoring, filtering and
   failure modes; the other is forty-three lines of text in a file.
3. The caller needs what the SDK's higher-level option hides. Verification (ADR-006) and the
   retrieval debug panel need every candidate's `chunk_id`, `citation_label`, hybrid score and
   rerank score. The framework's `AzureAISearchContextProvider` would fold retrieval into the
   agent call and return prose, which is why ADR-010 rejects it. The protocol exists to keep
   candidates and scores visible to the code that checks them.

## Consequences

- There is no mock of our own interfaces in the tests, because there are none to mock. Tests use
  the real `Chunk` model, the real `LocalRetriever` over the committed sample, and a fake agent
  with the same `run` shape as the framework's.
- `app/clients.py` builds the framework's and the SDKs' clients once, in the lifespan, and hands
  them to the agents. It contains no class of its own beyond a frozen record of what it built.
- When the framework removes or renames a type, the compiler — mypy in strict mode — finds every
  use, because nothing stands between our code and the framework.

## Revisit when

A second production retriever is needed — a different search service, or a tenant-scoped index
in the SaaS platform — or the framework stops exposing a client protocol that both providers
satisfy. Either would be a reason to own another seam, and it would have to pass the same test.
