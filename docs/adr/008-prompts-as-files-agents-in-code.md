# ADR-008 · Prompts as versioned files, agents in code rather than in Foundry Agent Service

**Status:** accepted · **Date:** 2026-10-15

## Context

Two things have to live somewhere: the instructions of the three agents, and the agents
themselves. Microsoft Foundry offers a hosted agent service where an agent — model,
instructions, tools — is defined once, stored in the project, edited in the portal and versioned
there, and the framework can target such hosted agents. The alternative is to construct the
agents in code at start-up and keep their instructions in the repository.

The instructions are the most consequential text in this system. The answerer's rules decide
whether a claim is written without evidence; the planner's rules decide whether a filter hides
the right passage. The agent specification says that a change to a prompt is a change to the
system under test.

## Options

1. **Hosted agents in Foundry Agent Service.** Definitions live in the project; the service
   manages threads and state; the portal edits and versions instructions.
2. **Agents in code, instructions inline in Python.** One file, everything visible, prose
   formatted as string literals.
3. **Agents in code, instructions in `prompts/<name>_v<n>.md`.** Read once at start-up by one
   function; the active version named in `app/agents.py` and nowhere else.

## Decision

Option 3.

- **A prompt change must pass the same gate as a code change.** The evaluation workflow runs on
  every pull request that touches `prompts/`, and `raise_for_status()` fails its check. A hosted
  agent's instructions would be editable outside that gate, and the evaluation report could not
  name the commit it measured.
- **Versions are files, not history.** `answerer_v2.md` is a new file beside `answerer_v1.md`, so
  an experiment evaluates both against the same dataset in the same run and the result names
  both. The datasets are versioned with the prompts for the same reason.
- **Prose is reviewed as prose.** A reviewer reads a Markdown file differently from a string
  literal with escaped quotes and f-string braces, and the Python budget is not spent on text.
- **There is nothing for the hosted service to manage.** No agent has tools and none keeps
  server-side state: every call is made with `store: False`, so the model API retains neither
  the questions nor the regulatory text the answerer reads, and the only conversation history
  is the planner's, held in this resource group's Cosmos account by `CosmosHistoryProvider`.
  The hosted service would add a second place where questions are stored, outside the privacy
  topology the architecture is built on.
- **The judge rubric is a file too**, pinned to the agent specification's rubric, so that the
  text the judge scores with and the text humans label with are the same text.

## Consequences

- Changing a prompt means a pull request, an evaluation run and a container image. That is the
  intended cost: it is the cost of a change to the system under test.
- No portal editing. Someone who wants to tune a prompt opens the repository.
- `app/agents.py` is the only place that knows which version is active, and `instructions()` is
  the only code that reads a prompt file.

## Revisit when

An agent needs tools or hosted threads — the field-operations copilot in this portfolio does —
or when prompt experiments become frequent enough that the evaluation gate, not the file layout,
is the bottleneck.
