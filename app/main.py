import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

import jwt
from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import telemetry
from app.agents import build_agents
from app.answer import Pipeline, answer
from app.clients import Clients, build_clients
from app.config import Settings
from app.models import PhaseEvent
from app.retrieval import LocalRetriever, SearchRetriever

LOGIN = "https://login.microsoftonline.com"


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9-]{1,64}$")


class Feedback(BaseModel):
    trace_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    helpful: bool
    comment: str = Field(default="", max_length=2000)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings, clients = Settings(), build_clients(Settings())
    telemetry.configure(settings)
    retriever = SearchRetriever(clients.search, settings.semantic_configuration) if clients.search else LocalRetriever()
    app.state.settings, app.state.clients = settings, clients
    app.state.pipeline = Pipeline(settings, build_agents(clients), retriever)
    app.state.jwks = jwt.PyJWKClient(f"{LOGIN}/{settings.entra_tenant_id}/discovery/v2.0/keys", cache_keys=True)
    yield
    await clients.close()


app = FastAPI(title="Regulatory Intelligence Platform", lifespan=lifespan)


def principal(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if not settings.require_auth:
        return {"oid": "local"}
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "a bearer token is required")
    try:
        key = request.app.state.jwks.get_signing_key_from_jwt(token).key
        issuer = f"{LOGIN}/{settings.entra_tenant_id}/v2.0"
        claims: dict[str, Any] = jwt.decode(
            token, key, algorithms=["RS256"], audience=settings.api_audience, issuer=issuer
        )
    except jwt.PyJWTError as error:
        raise HTTPException(401, f"invalid token: {error}") from error
    if settings.required_app_role not in claims.get("roles", []):
        raise HTTPException(403, f"the {settings.required_app_role} app role is required")
    return claims


async def problem(request: Request, error: Exception) -> JSONResponse:
    status = error.status_code if isinstance(error, HTTPException) else 422
    detail = error.detail if isinstance(error, HTTPException) else str(error)
    body = {"type": "about:blank", "title": "request rejected", "status": status, "detail": detail}
    body |= {"instance": request.url.path, "trace_id": telemetry.current_trace_id()}
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


app.add_exception_handler(HTTPException, problem)
app.add_exception_handler(RequestValidationError, problem)


Claims = Annotated[dict[str, Any], Depends(principal)]


@app.post("/v1/answer")
async def answer_route(body: Question, request: Request, claims: Claims) -> StreamingResponse:
    session = f"{claims.get('oid', 'local')}:{body.conversation_id}"

    async def events() -> AsyncIterator[str]:
        async for event in answer(request.app.state.pipeline, body.question, session):
            yield f"event: {event.phase}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/retrieve")
async def retrieve_route(body: Question, request: Request, claims: Claims) -> list[PhaseEvent]:
    session = f"{claims.get('oid', 'local')}:{body.conversation_id}"
    return [event async for event in answer(request.app.state.pipeline, body.question, session, generate=False)]


@app.post("/v1/feedback", status_code=204)
async def feedback_route(body: Feedback, request: Request, claims: Claims) -> None:
    clients: Clients = request.app.state.clients
    if clients.cosmos is None:
        raise HTTPException(503, "feedback storage is not configured")
    settings: Settings = request.app.state.settings
    container = clients.cosmos.get_database_client(settings.cosmos_database).get_container_client(
        settings.feedback_container
    )
    await container.upsert_item({"id": body.trace_id, "principal": claims.get("oid"), **body.model_dump()})


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    clients: Clients = request.app.state.clients
    settings: Settings = request.app.state.settings
    probes: dict[str, Any] = {}
    if clients.search is not None and clients.cosmos is not None:
        probes["search"] = clients.search.get_document_count()
        probes["cosmos"] = clients.cosmos.get_database_client(settings.cosmos_database).read()
    outcomes = await asyncio.gather(*probes.values(), return_exceptions=True)
    status = {n: type(o).__name__ if isinstance(o, AzureError) else "ok" for n, o in zip(probes, outcomes, strict=True)}
    healthy = all(value == "ok" for value in status.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", **status}, 200 if healthy else 503)
