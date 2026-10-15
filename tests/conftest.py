from typing import Any, cast

import pytest
from agent_framework import Agent, AgentSession

from app.config import Settings
from app.models import Chunk

TENANT = "00000000-0000-0000-0000-000000000000"
AUDIENCE = f"api://{TENANT}"
USAGE = {"input_token_count": 100, "output_token_count": 50}


class FakeResponse:
    def __init__(self, value: Any, usage: dict[str, int] | None = None) -> None:
        self.value, self.text, self.usage_details = value, "", usage


class FakeAgent:
    def __init__(self, value: Any = None, error: Exception | None = None) -> None:
        self.value, self.error, self.prompts = value, error, list[str]()

    async def run(self, prompt: str, *, session: AgentSession | None = None, options: Any = None) -> FakeResponse:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.value, USAGE)


def as_agent(fake: FakeAgent) -> Agent[Any]:
    return cast(Agent[Any], fake)


def make_chunk(
    chunk_id: str, label: str = "Article 9 Risk management system", hybrid: float = 0.0, rerank: float | None = None
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_id="parent",
        content=f"Providers shall comply with {label}.",
        regulation="EU-2024-1689",
        article=label,
        citation_label=label,
        source_url="https://example.com/ai-act.pdf",
        hybrid_score=hybrid,
        rerank_score=rerank,
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        model_provider="ollama",
        foundry_project_endpoint="https://foundry.example.invalid/api/projects/demo",
        search_endpoint="https://search.example.invalid",
        cosmos_endpoint="https://cosmos.example.invalid",
        corpus_container_url="https://storage.example.invalid/corpus",
        storage_account_resource_id="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/x/y/z",
        entra_tenant_id=TENANT,
        api_audience=AUDIENCE,
        require_auth=True,
    )
