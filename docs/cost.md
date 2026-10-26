# Cost

Every figure in this document is either **measured** — read from Azure Cost Management, from the
Retail Prices API or from a committed evaluation report — or **modelled** from a measured unit
price and a stated assumption. The two are never mixed in a column without saying which is which.

## What the workload costs today (measured)

Azure Cost Management, actual cost, month to date on 2026-10-15, grouped by the `repo` tag that
every resource carries:

| Tag `repo` | Resource group | Month to date | What drives it |
|---|---|---|---|
| `azure-rag-platform` | `rg-ragplatform-prod-swc` | €0.0008 | serverless Cosmos (a few hundred request units), Container Apps consumption while the apps scale to zero between demos, a Log Analytics ingestion of a few megabytes |
| `azure-ai-landing-zone` | `rg-aiplatform-shared-swc` | €10.36 | the shared platform, dominated by Azure AI Search Basic (about €2.13 a day at the measured €0.0889 an hour); the registry, the workspace and the model calls of every repository are billed here |

The platform's own resources cost cents because nothing in this resource group runs when nobody
asks a question. What this repository actually spends is model tokens and Document Intelligence
pages, which are billed to the shared Foundry account under the landing zone's tag; the figures
below isolate them.

## What a question costs (measured per call)

Every answer carries its own cost, computed from the token counts the framework returns and the
Retail Prices for Sweden Central on 2026-10-14 (`app/config.py`): gpt-5-mini €0.22 per million
input tokens and €1.76 per million output tokens; gpt-5-nano €0.044 and €0.352. The pipeline
uses the planner on gpt-5-nano, the answerer on gpt-5-mini, and the agent reranker on gpt-5-mini
only when it is selected.

| Source | Per answer | Items | Reranker |
|---|---|---|---|
| smoke report `docs/reports/2026-10-15-smoke-gpt-5-mini-semantic.json` | €0.0022 to €0.0055 across the answered items; refusals under €0.0015 because the answerer writes no claims | 12 | semantic |
| recorded fixtures `web/fixtures/*.json` | €0.0050, €0.0052, €0.0049 for three answers; €0.0015 for a refusal | 4 | semantic |
| golden run `docs/reports/2026-10-15-golden-gpt-5-mini-semantic.json` | €0.0025 mean; single-passage questions answered in about three claims | 80 | semantic |
| golden run `docs/reports/2026-10-15-golden-gpt-5-mini-agent.json` | €0.0104 mean; the same questions with the second model call | 80 | agent |

In local mode the same arithmetic runs over Ollama's token counts with the Foundry prices, so the figure an answer carries is what that answer would have cost on the deployments, not what the laptop paid. The semantic ranker is billed per query once its monthly free allowance is spent (below); the agent reranker is a second
gpt-5-mini call that reads thirty passages and multiplies the model cost of an answer by about four,
€0.0025 to €0.0104 on the eighty golden items (`experiments/002-reranking.md`).

## Cost per 1,000 queries

| Line | Per 1,000 queries | Basis |
|---|---|---|
| Model tokens, semantic reranker, short answers | **€2.5** | measured: mean of the eighty golden items, €0.0025 per answer |
| Model tokens, semantic reranker, multi-hop answers | **€5.0** | measured: mean of the answered smoke items and the fixtures, €0.005 per answer |
| Model tokens, agent reranker | **€10.4** | measured: mean of the eighty golden items with `RERANKER=agent`, €0.0104 per answer |
| Azure AI Search queries | €0 marginal | measured: queries are included in the Basic tier's hourly price |
| Semantic ranker | €0.88 | measured: the shared service's `standard` semantic plan bills each thousand queries beyond the monthly free allowance; Retail Prices API, North Europe, 2026-10-26 |
| Cosmos DB | about €0.002 | modelled: two writes and one read per question at serverless request-unit prices, well under a cent |
| Container Apps | about €0.09 | modelled: one request every few seconds keeps one 0.5 vCPU replica warm for the whole hour at consumption prices; at a thousand queries an hour the API runs continuously |
| **Total, semantic reranker** | **€3.5 to €6.0** | measured tokens, by answer length, and ranker price, plus modelled platform cost |

Tokens are the cost, and the shared search service's semantic ranker adds €0.88 a thousand. Everything
else in this resource group is noise until the question rate is high enough to keep replicas warm, and
even then its share stays under three per cent.

## Projection to production (modelled)

The assumptions: 50,000 questions a month, the semantic reranker, Azure AI Search Basic scaled to
**two replicas** for a query availability target, a **second region** with its own resource group,
search replica pair and container apps for failover, the same shared Foundry account, and the
Retail Prices of 2026-10-14 for Sweden Central.

| Item | Monthly | Measured or modelled |
|---|---|---|
| Model tokens, 50,000 answers at €0.005 | €250 | modelled from the higher of the two measured unit costs |
| Azure AI Search Basic, 2 replicas × 1 partition, one region | €130 | modelled from the measured €0.0889 per search unit hour |
| Azure AI Search Basic, 2 replicas, second region | €130 | modelled, same unit price |
| Semantic ranker, 50,000 queries | €44 | modelled from the measured €0.88 per thousand, ignoring the monthly free allowance |
| Container Apps, two regions, one warm API replica each | €60 | modelled from consumption prices for 0.5 vCPU and 1 GiB |
| Cosmos DB serverless, both regions | €5 | modelled from request units per question |
| Document Intelligence, re-ingestion of the corpus four times a year | €2 | measured: about 390 pages per run at €10 per thousand pages |
| Log Analytics and Application Insights, about 2 GB a month | €6 | modelled from the measured €2.63 per GB |
| Registry and budgets | €5 | measured: Basic registry at €0.15 a day |
| **Total** | **about €630 a month, €0.013 per question** | |

Two things the model does not include, on purpose: the shared Foundry account's base cost, which
belongs to the landing zone, and the people who verify the golden set and label the calibration
items, which is the real cost of operating a system whose claims must be true.

## How to refresh these numbers

- The per-answer cost is in every `verify` event and in every evaluation report.
- The month-to-date figures come from the Cost Management query grouped by the `repo` tag; the
  `make` target does not wrap it because it is one `az rest` call documented in the README.
- The unit prices come from the Azure Retail Prices API for the `swedencentral` region and are
  dated in `app/config.py`; change the date when you change the number.
