# Security

The platform's boundary is identity, not network. There is no virtual network, no private
endpoint and no firewall in front of the API; what protects it is that every call to it must
carry an Entra token with the `Rag.Query` app role, every call it makes to Azure is made with a
managed identity holding the narrowest role the service offers, and the repository contains no
secret of any kind — not in code, templates, fixtures, workflows or history.

## Identities and roles

| Identity | Role | Scope | Declared in |
|---|---|---|---|
| `id-ragapi` | Foundry User | the shared Foundry project | `infra/modules/shared-access.bicep` |
| `id-ragapi` | Search Index Data Reader | the shared search service | `infra/modules/shared-access.bicep` |
| `id-ragapi` | Cosmos DB Built-in Data Contributor (SQL role assignment) | database `rag` | `infra/modules/data.bicep` |
| `id-ragapi`, `id-ragweb`, `id-ragjobs` | Monitoring Metrics Publisher | Application Insights | `infra/modules/apps.bicep` |
| `id-ragapi`, `id-ragweb`, `id-ragjobs` | AcrPull | the shared registry | `infra/modules/shared-access.bicep` |
| `id-ragweb` | app role `Rag.Query` | the API's app registration | bootstrap step in the README (Graph app-role assignment) |
| `id-ragjobs` | Foundry User | the shared Foundry project | `infra/modules/shared-access.bicep` |
| `id-ragjobs` | Search Service Contributor, Search Index Data Contributor | the shared search service | `infra/modules/shared-access.bicep` |
| `id-ragjobs` | Storage Blob Data Contributor | the `corpus` container | `infra/modules/data.bicep` |
| the shared search service's identity | Storage Blob Data Reader | the `corpus` container | `infra/modules/data.bicep` |
| `gh-azure-rag-platform` (GitHub OIDC) | Contributor; Contributor on the shared registry (`az acr build` schedules an ACR task and uploads its context, beyond what AcrPush allows); Foundry User; Cognitive Services OpenAI User (the evaluation graders call the model deployment as the caller); Search Index Data Reader; Cosmos SQL Data Contributor | this resource group; the shared registry, project, Foundry account and search service; the Cosmos account | bootstrap step in the README |

No identity holds a control-plane role it does not need: the API cannot write the index, the jobs
cannot read conversations, the frontend can only ask the API. The deployment principal's
Contributor role is scoped to this resource group; on the shared group it can only assign roles
to the identities this repository creates, and it reads the shared project and index only to run
the evaluation suite from a pull request.

## What a caller has to present

Container Apps rejects any request to `ca-ragapi` without a valid Entra token for
`api://<client id>` with `401` at the ingress (`infra/modules/apps.bicep`, `authConfigs`). The
code then validates the same token against the tenant's keys and requires the app role
(`app/main.py`, `principal()`), returning `403` without it. `/healthz` is the only path without
authentication and it touches no model. The conversation id a caller may use is prefixed with the
caller's object id before the agent session is created, so history is partitioned by caller.

## Threats and where each one is mitigated

| Threat | Mitigation | File |
|---|---|---|
| Prompt injection through the question | the planner and answerer are told that the question is data; the answerer's rules put every claim under a citation that verification checks; a question that trips Azure OpenAI's jailbreak filter at the planner ends as a `content_filter` refusal, which the first full-suite run showed was an unhandled exception until then | `prompts/planner_v1.md`, `prompts/answerer_v1.md`, `app/answer.py` (`retrieve`) |
| Prompt injection through a retrieved or planted document | evidence reaches the answerer as a user-role block delimited and labelled untrusted; no agent has tools, so an injected instruction has nothing to call | `app/agents.py` (`answerer_input`), `app/answer.py` |
| Injection that succeeds silently | every adversarial evaluation row carries a canary, through the question, a planted top-ranked passage and formatting; its appearance fails the gate | `eval/datasets/adversarial.jsonl`, `eval/evaluators.py` (`canary_appearances`), `eval/run.py` (`Planted`) |
| Fabricated or misattributed citation | `verify()` keeps a claim only when every cited chunk id was shown to the answerer and its label matches; an answer with no surviving claim is a typed refusal | `app/answer.py` (`verify`), `tests/test_pipeline.py` |
| Answer from model knowledge when retrieval finds nothing | empty evidence is a `no_evidence` refusal before the answerer is called | `app/answer.py` (`draft_answer`) |
| Regulatory text or answers persisted in history | only the planner has a history provider; the answerer has none; every call uses `store: false` | `app/agents.py` (`build_agents`), `app/clients.py` |
| Anonymous or unauthorised access to the API | Entra authentication at the ingress plus app-role check in the code | `infra/modules/apps.bicep`, `app/main.py` |
| A token in the browser | the frontend proxies server-side with its managed identity | `web/server.ts` |
| Cross-caller access to a conversation | session id derived from the caller's object id | `app/main.py` (`answer_route`, `retrieve_route`) |
| Secrets in the repository | no key or connection string exists; gitleaks with email and GUID rules over the full history; identifiers in fixtures replaced | `.gitleaks.toml`, `.github/workflows/ci.yml`, `web/fixtures/` |
| Over-privileged identities | one assignment per need, scoped to the resource; data-plane SQL role for Cosmos | `infra/modules/shared-access.bicep`, `infra/modules/data.bicep` |
| Keys on storage, Cosmos or Application Insights | shared-key access disabled, local authentication disabled, Entra-only ingestion | `infra/modules/data.bicep`, `infra/modules/apps.bicep` |
| Vulnerable or tampered dependencies | exact pins for Python and npm, trivy and pip-audit in CI | `requirements.txt`, `web/package-lock.json`, `.github/workflows/ci.yml` |
| Runaway spend | a monthly budget with alerts on this group, scale limits on the apps, a 5xx alert | `infra/modules/apps.bicep` |
| Harmful content | the provider's content filter is honoured as a typed refusal at the planner and at the answerer, never retried around | `app/answer.py` (`retrieve`, `draft_answer`) |
| A bad deployment | a canary revision takes 10 % of traffic and is rolled back on an error-rate regression | `.github/workflows/deploy.yml` |

## What is not defended

A caller that holds the app role can ask any number of questions; cost, not access, is the
limit, and the budget alert is the control. The public ingress accepts connections from anywhere
and refuses them cheaply; a web application firewall is declined in ADR-011 with the condition
under which it returns. A model that follows an injected instruction without emitting the canary
is caught only if the resulting claim fails verification or the judge.
