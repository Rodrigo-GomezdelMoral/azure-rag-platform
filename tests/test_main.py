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
QUESTION = {"question": "Which risk management obligations apply?"}


class FakeJwks:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=KEY.public_key())


def bearer(roles: list[str]) -> dict[str, str]:
    claims = {
        "aud": AUDIENCE,
        "iss": f"{main.LOGIN}/{TENANT}/v2.0",
        "oid": "caller",
        "roles": roles,
        "exp": int(time.time()) + 60,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, KEY, algorithm='RS256')}"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    agents = Agents(
        planner=as_agent(FakeAgent(QueryPlan(query="risk management"))),
        reranker=as_agent(FakeAgent()),
        answerer=as_agent(FakeAgent()),
    )
    main.app.state.settings, main.app.state.jwks = settings, FakeJwks()
    main.app.state.pipeline = Pipeline(settings, agents, LocalRetriever())
    main.app.state.clients = Clients(
        chat=cast(BaseChatClient[Any], object()), small_chat=cast(BaseChatClient[Any], object())
    )
    return TestClient(main.app)


def test_missing_token_and_missing_role_are_problem_responses(client: TestClient) -> None:
    missing = client.post("/v1/retrieve", json=QUESTION)
    assert missing.status_code == 401 and missing.headers["content-type"].startswith("application/problem+json")
    assert {"status", "detail", "trace_id", "instance"} <= set(missing.json())
    assert client.post("/v1/retrieve", json=QUESTION, headers=bearer([])).status_code == 403


def test_authorised_caller_receives_phase_events_and_validation_problems(client: TestClient) -> None:
    response = client.post("/v1/retrieve", json=QUESTION, headers=bearer(["Rag.Query"]))
    assert response.status_code == 200 and [event["phase"] for event in response.json()] == ["plan", "search", "rerank"]
    invalid = client.post("/v1/retrieve", json={"question": "x"}, headers=bearer(["Rag.Query"]))
    assert invalid.status_code == 422 and invalid.headers["content-type"].startswith("application/problem+json")


def test_health_and_feedback_without_azure(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    feedback = {"trace_id": "abc123", "helpful": True}
    assert client.post("/v1/feedback", json=feedback, headers=bearer(["Rag.Query"])).status_code == 503
