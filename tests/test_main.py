import time
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from agent_framework import BaseChatClient
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import main
from app.agents import Agents
from app.answer import Pipeline
from app.clients import Clients
from app.config import Settings
from app.models import QueryPlan
from app.retrieval import LocalRetriever
from tests.conftest import AUDIENCE, TENANT, FakeAgent, as_agent

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=KEY.public_key()))
QUESTION = {"question": "Which risk management obligations apply?"}


def bearer(roles: list[str]) -> dict[str, str]:
    claims = {"aud": AUDIENCE, "iss": f"{main.LOGIN}/{TENANT}/v2.0", "oid": "caller", "roles": roles}
    return {"Authorization": f"Bearer {jwt.encode(claims | {'exp': int(time.time()) + 60}, KEY, algorithm='RS256')}"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    fakes = as_agent(FakeAgent(QueryPlan(query="risk management"))), as_agent(FakeAgent()), as_agent(FakeAgent())
    stub = cast(BaseChatClient[Any], object())
    main.app.state.settings, main.app.state.jwks = settings, JWKS
    main.app.state.clients = Clients(chat=stub, small_chat=stub)
    main.app.state.pipeline = Pipeline(settings, Agents(*fakes), LocalRetriever())
    return TestClient(main.app)


def test_token_and_role_are_enforced_with_problem_responses(client: TestClient) -> None:
    missing = client.post("/v1/retrieve", json=QUESTION)
    assert missing.status_code == 401 and missing.headers["content-type"].startswith("application/problem+json")
    assert {"status", "detail", "trace_id", "instance"} <= set(missing.json())
    assert client.post("/v1/retrieve", json=QUESTION, headers=bearer([])).status_code == 403
    invalid = client.post("/v1/retrieve", json={"question": "x"}, headers=bearer(["Rag.Query"]))
    assert invalid.status_code == 422 and invalid.headers["content-type"].startswith("application/problem+json")


def test_authorised_caller_health_and_feedback_without_azure(client: TestClient) -> None:
    response = client.post("/v1/retrieve", json=QUESTION, headers=bearer(["Rag.Query"]))
    assert response.status_code == 200 and [event["phase"] for event in response.json()] == ["plan", "search", "rerank"]
    assert client.get("/healthz").json() == {"status": "ok"}
    feedback = {"trace_id": "abc123", "helpful": True}
    assert client.post("/v1/feedback", json=feedback, headers=bearer(["Rag.Query"])).status_code == 503
