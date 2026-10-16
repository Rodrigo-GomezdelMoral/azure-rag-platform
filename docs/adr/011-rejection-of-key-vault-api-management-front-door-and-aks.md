# ADR-011 · Rejection: no Key Vault, no API Management, no Front Door, no AKS

**Status:** accepted — the four alternatives are rejected · **Date:** 2026-10-15

## Context

A reference architecture for an enterprise RAG service usually shows these four services. Each
was considered for this repository and each lost to something simpler. Recording the reasons
matters more than the omission: a reader who does not find a vault assumes a secret is lying
around, and a reader who does not find a gateway assumes the API is unprotected.

## Key Vault

**What it would hold:** nothing. Every call to Azure — Foundry, Search, Cosmos, Storage, the
registry, Application Insights — is made with a managed identity or the developer's own login
through `DefaultAzureCredential`. The search service reads the corpus with its own identity and
calls the embedding model with it; storage has shared-key access disabled; Cosmos has local
authentication disabled; Application Insights ingests with Entra only. The only
configuration value that looks like a credential, the API's app registration client id, is an
identifier, not a secret, and lives in an environment variable.

**Why it lost:** a vault with no secrets is a resource to pay for, monitor and explain. The
guard that keeps it empty is the CI job: gitleaks over the full history with an email rule and a
GUID rule, and a test that fails if a connection string or key appears in a template.

**Would return when:** a dependency that cannot authenticate with Entra enters the system.

## API Management

**What it would add:** products, subscriptions, rate limits, request transformation, a developer
portal. **Why it lost:** the API has one caller holding one app role (ADR-009); there is nothing to
meter or to transform, and a gateway in front of a single internal consumer is a second place to
configure authentication. The SaaS platform in this portfolio is the repository where tenants,
quotas and keys exist, and it is where a gateway belongs.

**Would return when:** a second external consumer appears, or per-caller quotas are required.

## Front Door

**What it would add:** a global entry point, a web application firewall, caching, TLS at the
edge. **Why it lost:** the service runs in one region for one tenant, the edge already terminates
TLS, nothing cacheable is served by the API, and a WAF for an endpoint that returns `401` to
anyone without a token protects mostly against traffic that costs nothing to refuse. Its monthly
base price would exceed the measured cost of the entire workload.

**Would return when:** a second region is deployed for availability (the cost projection in
`docs/cost.md` models that case), or abuse at the edge is observed rather than imagined.

## AKS

**What it would add:** a cluster. **Why it lost:** the workload is two containers and two jobs,
scales to zero between demos, needs revisions with traffic splitting for the deployment
workflow, and needs managed identities per container. Container Apps gives each of those as a
property; a cluster gives them as a project — node pools, upgrades, ingress controllers,
workload identity configuration — for a service whose peak is a dozen concurrent requests.

**Would return when:** a component needs what Container Apps cannot express — GPUs for a local
model, a custom scheduler, a sidecar that must share a network namespace — and that component is
worth a cluster to operate.

## The pattern behind the four

Each rejected service answers a question this workload does not ask yet. The repository keeps
the question in this document, with the condition under which the answer changes, so that the
absence reads as a decision rather than an oversight.
