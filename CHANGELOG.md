# Changelog

All notable changes to this repository, by phase. Dates are the days the work was done.

## 0.8.0 — 2026-10-15 · quality gate, deployment and portfolio documentation

- Four workflows: `ci` (ruff, mypy, pytest with the budgets, Bicep build and lint, gitleaks over
  the full history with email and GUID rules, trivy, pip-audit, frontend build), `eval` (smoke and
  adversarial suites on pull requests that touch the pipeline, the full suite weekly, scores posted
  as a pull-request comment), `deploy` (images built in the shared registry, a canary API revision
  at 10 % of traffic promoted or rolled back on its 5xx rate, then the web container) and `pages`
  (the recorded-run demo on GitHub Pages).
- The API app runs in multiple-revision mode so that the canary can exist.
- Experiments 001 (answerer model) and 002 (reranker) with measured results on the golden set;
  both cheap options are rejected, with the figures.
- `ndcg_at_10` credited every chunk that shared a golden label and could exceed 1.0 when an
  article's chunks filled the first ten; each label now counts once, at its first rank. The three
  golden reports of 2026-10-15 carry the earlier value, and the experiments say so.
- `docs/architecture.md`, `docs/security.md`, `docs/cost.md`, ADR-009, ADR-010, ADR-011, this
  file and the README.
- A v2 access token carries the bare client id as its audience; the API now accepts both forms.
  Found by the first request through the deployed frontend.

## 0.7.0 — 2026-10-15 · phase timeline and retrieval debug panel

- `web/`: React, TypeScript and Vite with no component, CSS or state library; phase timeline,
  verified-answer panel with inline citation markers, citation panel, refusal panel, and the
  retrieval debug panel behind *Inspect retrieval*.
- `web/server.ts` serves the app and proxies `/v1/*` with the frontend's managed identity.
- Four fixtures recorded from real runs with every identifier replaced; `VITE_DEMO_MODE` replays
  them with their real timings halved.

## 0.6.0 — 2026-10-15 · local and Foundry evaluators with calibrated judge

- Six datasets (golden 80, unanswerable 30, multihop 20, adversarial 25 with the canary,
  calibration 40, smoke 12), `thresholds.yaml`, `eval/run.py` and `eval/evaluators.py`.
- Groundedness and relevance from `FoundryEvals`; citation precision, recall at 10, nDCG at 10,
  correct and false refusal and canary appearances locally; κ against human labels when they exist.
- The golden set awaits human verification (`eval/datasets/REVIEW.md`); the smoke run of the day
  is published with its report and its red gate.
- The Python budget was raised from 1,000 to 1,400 lines to count tests and the harness.

## 0.5.0 — 2026-10-15 · verified pipeline with streamed progress

- `app/answer.py`: the five-phase generator, `verify()`, typed refusals, cost from usage.
- `app/main.py`: Entra token validation with the `Rag.Query` app role, server-sent phase events,
  retrieval-only route, feedback bound to the trace id, dependency health, RFC 9457 problems.
- `app/telemetry.py`: Azure Monitor with Entra ingestion, framework instrumentation without
  sensitive data, the `search` and `verify` spans and the `app.unverified_claims` counter.

## 0.4.0 — 2026-10-15 · planner, reranker and answerer on Agent Framework

- Versioned prompts, `app/clients.py`, `app/agents.py`, `app/retrieval.py` with the one owned
  abstraction, both rerankers, the local retriever over a committed sample, ADR-004 and ADR-008.
- Reasoning effort set to low and `store: false` on every Foundry call after the first live run.

## 0.3.0 — 2026-10-14 · search index, skillset and indexer as configuration

- `ops/corpus.py`, `ops/index.py`, `data/manifest.json`; the index built by the search service's
  own identity; ADR-001 and ADR-002 with the measured sizes of the quantised and twin indexes.

## 0.2.0 — 2026-10-14 · data plane, container apps and app-role authorisation

- Bicep at resource-group scope: identities, storage, Cosmos with both containers, Application
  Insights, Container Apps environment, apps and jobs, alerts, budget and every role assignment.

## 0.1.0 — 2026-10-14 · scaffold and agent specification

- Working agreement, layout, pinned dependencies, budget tests and `docs/agent-spec.md`.
