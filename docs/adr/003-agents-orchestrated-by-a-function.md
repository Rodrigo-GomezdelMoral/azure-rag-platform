# ADR-003 · Agents orchestrated by a function, not a workflow

**Status:** accepted · **Date:** 2026-10-15

## Context

Microsoft Agent Framework offers two ways to combine agents: a workflow — a graph of executors
with typed edges, checkpoints, human-input requests and the orchestration patterns built on it —
and plain code that calls agents. The pipeline here is five steps in a fixed order: plan, search,
rerank, answer, verify. It never branches on the model's output, never waits for a person, never
runs long enough to need a checkpoint, and two of its five steps are not agents at all: search is
a service call and verify is arithmetic over ids.

The question is which of the two the pipeline should be written in, and the answer decides how
much of the framework a reader has to know to follow the system.

## Options

1. **A framework workflow.** Each phase an executor; the sequence an edge list; phase events the
   workflow's own events. Everything the framework offers for free — visualisation, checkpoints,
   parallel branches — is available and unused.
2. **A plain `async` generator.** Five awaited calls in a function body; a `PhaseEvent` yielded
   after each; timings, cost and the typed refusal computed in the same scope.
3. **A hand-written step abstraction.** A `Step` protocol and a loop over steps, the shape a
   team writes when it expects to need a workflow later.

## Decision

Option 2. `app/answer.py` holds one generator, `answer()`, of about twenty-five lines, and the
helpers it calls. What it does with each step is visible in the order the lines appear:

| Line of the generator | What a reader learns without opening another file |
|---|---|
| `run(agents.planner, question, QueryPlan, AgentSession(...))` | the planner is the only agent given a session |
| `with tracer.start_as_current_span("search")` | search is the service's call, timed as one span |
| `rerank(candidates, settings.rerank_k, scores)` | one function serves both rerankers |
| `draft_answer(...)` returning a `Draft` and an optional refusal | the content filter is a typed outcome, not an exception that escapes |
| `with tracer.start_as_current_span("verify")` | verification is separate from generation and timed |

A workflow would have expressed the same sequence in more lines and in two languages — Python and
the graph — and every reader would have had to learn the second to confirm that the graph is a
straight line. Option 3 is a workflow without the framework's tooling, the worst of both.

The field-operations copilot in the same portfolio does use workflows: its steps branch on
inspection results, pause for a technician's confirmation and resume later. The contrast is the
argument. A workflow earns its place when there is a graph; here there is a list.

## Consequences

- No module imports `agent_framework.orchestrations`, `WorkflowBuilder`, `@workflow` or `@step`.
  The budget test does not check this; the validation prompt does, and a grep confirms it.
- Progress is visible because the generator yields it, which is what ADR-005 builds on; cost and
  timings are plain local variables in one function.
- Adding a step means adding a line in order, not an executor and an edge.
- Retrieval-only requests (`/v1/retrieve`) run the same generator with generation switched off,
  so there is one path through the system and one place to time it.

## Revisit when

A phase has to branch on a model's decision, wait for a human, or survive a process restart.
Any one of those is a graph, and the framework already has the graph.
