# ADR-009 · App-role authorisation instead of a network boundary

**Status:** accepted · **Date:** 2026-10-15

## Context

The landing zone this platform runs on has no virtual network, by decision: no private endpoints,
no private DNS zones, no internal ingress. That decision was taken for the whole portfolio, and
this repository has to protect an API that answers regulatory questions, writes conversation
history and spends model tokens on every call, without a network to hide it in.

The API has exactly one legitimate caller today — the frontend container — and one planned
caller, the gateway of the SaaS platform in another repository. Nothing in a browser should ever
be able to call it.

## Options

1. **A virtual network after all.** Internal ingress for the API, a private endpoint for Cosmos,
   the frontend as the only public surface. It is the textbook answer, it contradicts the
   platform's posture, and for one caller it buys a network that nobody else would be on.
2. **IP restrictions on the ingress.** The frontend's egress addresses are not stable in Container
   Apps without a NAT gateway, which is a network again.
3. **The token as the boundary.** Entra ID authentication required at the ingress, an app role
   `Rag.Query` defined on the API's app registration, the role granted to the frontend's managed
   identity and to nothing else, and the API checking the role itself.

## Decision

Option 3, enforced twice, on purpose:

- **At the edge**, Container Apps' built-in authentication (`authConfigs` in
  `infra/modules/apps.bicep`) rejects any request without a valid Entra token for the API's
  audience with `401`, before a container is even scaled up. `/healthz` is the only excluded
  path, and it probes dependencies without touching the model.
- **In the code**, `principal()` in `app/main.py` validates the same token against the tenant's
  signing keys and audience, then requires `Rag.Query` in its `roles` claim, returning `403`
  otherwise. The edge does not check roles; an app that validates the token but not the role
  would accept any identity in the tenant that can obtain a token for the audience — and any
  application in the tenant can. The role is the authorisation; the token is only authentication.
- **The browser never holds a token.** `web/server.ts` runs with the frontend's user-assigned
  identity, requests a token for `api://<client id>/.default` with `DefaultAzureCredential`, and
  proxies `/v1/*` server-side. The static demo on GitHub Pages replays recorded runs and calls
  nothing.
- **The session is authorised before it exists.** The route derives the conversation id from the
  caller's object id and the client's conversation id, so a caller can only ever reach its own
  history, and only then constructs the `AgentSession`.

Locally the same code runs with `REQUIRE_AUTH=false`, which is how the tests exercise the
pipeline without a tenant and how the Codespaces demo runs against Ollama.

## Trade-offs

- The API's address is public. Anyone can reach the edge and receive a `401`; nobody can reach
  the model. Volumetric abuse is bounded by the app's maximum replica count, the budget and the
  5xx alert rather than by a firewall; a web application firewall is the thing ADR-011 declines
  and the first thing to add if abuse appears.
- Two validations of one token are a few milliseconds and twenty lines; they are the price of
  running the same code with and without the edge.
- Granting a new caller is an app-role assignment on the API's service principal, an operation
  that needs a directory role and is recorded in the README as the bootstrap step. That is
  slower than opening a network path and is meant to be.

## Revisit when

A caller outside the tenant needs access, a compliance requirement names network isolation
explicitly, or the SaaS platform brings tenants whose isolation cannot be expressed as roles. Each
of those is a network decision for the landing zone, not for this repository.
