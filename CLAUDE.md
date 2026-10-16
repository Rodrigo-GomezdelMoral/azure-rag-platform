# CLAUDE.md — working agreement

`azure-rag-platform` is the Regulatory Intelligence Platform: grounded document intelligence over
a controlled corpus (EU AI Act, MDR, MDCG guidance) with article-level provenance, built on
Microsoft Agent Framework. A staff engineer reads it for ten minutes and must conclude the author
operates at principal level. That depends on **restraint**: how little code produces the result,
and whether every remaining line expresses a decision someone could defend.

Two rules govern every choice:

> If a capability exists in the Azure service or in Microsoft Agent Framework, do not reimplement it.
>
> If a task can be written as a function, write a function — not an agent, not a workflow.

Re-read this file at the start of every phase.

## Process

- Do not stage, commit or push. The author commits at the end of each phase with the message
  printed in the phase summary.
- At the end of each phase stop and print:

  ```
  ── PHASE n COMPLETE ──
  Files: <n>/60   Python: <n>/1400   Bicep: <n>/400   TS: <n>/700   Comments: <n>/20
  Verified: ruff ✓  mypy ✓  pytest ✓  budget ✓
  Commit with:
    git add <paths>
    git commit -m "<message>"
  Say "continue" for phase n+1.
  ```

- Every Agent Framework and Azure SDK name is verified against the installed package before it is
  written. The names below were verified on 2026-10-14 against the pinned versions in
  `requirements.txt`; the framework renamed many types before 1.0, so code copied from older
  samples looks right and does not run.

## Non-negotiable constraints

1. **No identity leakage** anywhere, fixtures and commit messages included. Placeholders only.
2. **Zero secrets.** `DefaultAzureCredential` for every Azure call. No Key Vault.
3. **Size budget, enforced by `tests/test_budget.py`:** tracked files excluding `docs/`,
   `eval/datasets/`, `web/node_modules/` and `web/fixtures/` at most 60 (the specification says
   42; its own mandated layout needs more, and the README records the count); ≤ 1,400 lines of
   Python (the specification's 1,000 covered application and operations code; tests and the
   evaluation harness are counted in the same figure here and the README reports the split);
   ≤ 400 Bicep; ≤ 700 TypeScript; directory depth 3; functions ≤ 35 lines.
4. **Comments.** No `#` comment may restate the code; fewer than 20 in the whole Python codebase.
   Type hints replace them.
5. **No defensive clutter.** No bare `except Exception`; ruff rule `BLE001` and the budget test
   both enforce it.
6. **Minimal dependencies.** `agent-framework-foundry` and `agent-framework-azure-cosmos`, never
   the `agent-framework` metapackage. `agent-framework-ollama` in dev only, pinned exactly.
7. **`targetScope = 'resourceGroup'`.** `rg-ragplatform-prod-swc` exists; never create it.
8. **English** everywhere. Nothing unfinished.

## SDK reference — verified against the installed packages

| Purpose | Verified names |
|---|---|
| Agents | `agent_framework.Agent(client=, name=, instructions=, default_options=, context_providers=)`; `await agent.run(messages, session=, options={"response_format": Model})` → `AgentResponse` with `.value` (parsed model), `.text`, `.usage_details` |
| Sessions | `agent_framework.AgentSession(session_id=<our authorised conversation id>)` |
| Foundry | `agent_framework.foundry.FoundryChatClient(project_endpoint=, model=<deployment name>, credential=)` |
| Local | `agent_framework.ollama.OllamaChatClient(host=, model=)` (dev only) |
| History | `agent_framework.azure.CosmosHistoryProvider(endpoint=, database_name=, container_name=, credential=)` or `container_client=`; the container partition key path is `/session_id`; attach with `context_providers=[provider]` and `default_options={"store": False}` |
| Errors | `agent_framework.exceptions.ChatClientContentFilterException` → typed refusal |
| Evaluation | `agent_framework.LocalEvaluator(*checks)`, `@agent_framework.evaluator` (parameters named `query`, `response`, `expected_output`, `conversation`, `context`), `evaluate_agent(agent=, queries=, expected_output=, evaluators=)` → `list[EvalResults]`, `EvalResults.raise_for_status()`; `agent_framework.foundry.FoundryEvals(client=, evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.RELEVANCE])` with `report_url` on the results |
| Telemetry | `azure.monitor.opentelemetry.configure_azure_monitor(connection_string=)`; `agent_framework.observability.create_resource(service_name=)`, `enable_instrumentation(enable_sensitive_data=False)`, `get_tracer()` |
| Search | `azure.search.documents.aio.SearchClient.search(search_text=, vector_queries=, filter=, query_type=)`; `azure.search.documents.indexes` with `SearchIndex`, `ScalarQuantizationCompression`, `SemanticSearch`, `SearchIndexerSkillset`, `DocumentIntelligenceLayoutSkill`, `ShaperSkill`, `SplitSkill`, `AzureOpenAIEmbeddingSkill`, `AIServicesAccountIdentity`, `SearchIndexerIndexProjection`, `SearchIndexerDataSourceConnection`, `SearchIndexer` |

`model=` always takes the deployment name. The framework emits agent and chat spans and token
usage by itself; this repository adds only two spans, `search` and `verify`.

## Architecture in one paragraph

`ca-ragweb` (external) proxies with its managed identity to `ca-ragapi` (external, Entra token
with the `Rag.Query` app role required). The API runs `answer()`, a plain async generator:
`QueryPlanner` (`gpt-5-nano`, the only agent with history) → `Retriever` (one hybrid search call)
→ reranker (semantic ranker or agent) → `Answerer` (`gpt-5-mini`, structured `Draft`) →
deterministic `verify()`. Progress is streamed as phase events, never tokens. The index is built
by the shared search service's own identity with an indexer, skillset and index projection over
the `corpus` blob container. No agent has tools; retrieval is not a decision the model makes.

## Phases

| # | Work | Commit message |
|---|---|---|
| 1 | `CLAUDE.md`, layout, requirements, `pyproject.toml`, `Makefile`, `Dockerfile`, devcontainer, `.env.example`, `.gitignore`, `config.py`, `models.py`, `test_budget.py`, `docs/agent-spec.md` | `chore: scaffold project and define agent specification` |
| 2 | `infra/`: storage, Cosmos with both containers, App Insights, identities, all role assignments, Container Apps and jobs, alerts, `azure.yaml` | `feat(infra): data plane, container apps and app-role authorisation` |
| 3 | `ops/corpus.py`, `ops/index.py`, ADR-001, ADR-002 with measured sizes | `feat(index): search index, skillset and indexer as configuration` |
| 4 | `prompts/`, `clients.py`, `agents.py`, `retrieval.py`, tests, ADR-004, ADR-008 | `feat(agents): planner, reranker and answerer on agent framework` |
| 5 | `answer.py`, `main.py`, `telemetry.py`, tests, ADR-003, ADR-005, ADR-006 | `feat(answer): verified pipeline with streamed progress` |
| 6 | `eval/`, six datasets, `REVIEW.md`, thresholds, calibration, ADR-007 | `feat(eval): local and foundry evaluators with calibrated judge` |
| 7 | `web/` and fixtures | `feat(web): phase timeline and retrieval debug panel` |
| 8 | Four workflows, `experiments/`, all docs, remaining ADRs, README, `CHANGELOG` | `ci: quality gate, deployment and portfolio documentation` |

## Definition of done

`make budget` green with actual counts · ruff, mypy, pytest clean · bicep build and lint clean ·
`azd provision --preview` succeeds · the API rejects an unauthenticated request and one without
the app role · no service key and no Key Vault anywhere · the app runs against `OllamaChatClient`
with no Azure account · demo mode runs with no backend · no email or GUID outside placeholders ·
no unfinished-work markers and no bare `except Exception` · no import from the `agent-framework` metapackage ·
comment count under 20, reported · nothing committed or pushed · `docs/evaluation.md` states the
golden set awaits human verification and publishes no metric until then. Then list anything that
could not be verified without a live deployment.
