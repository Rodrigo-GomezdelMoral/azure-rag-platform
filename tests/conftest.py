from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from agent_framework import Agent, AgentSession

from app.config import Settings
from app.models import Chunk

TENANT = "00000000-0000-0000-0000-000000000000"
AUDIENCE = f"api://{TENANT}"
USAGE = {"input_token_count": 100, "output_token_count": 50}
URL, LABEL = "https://x.invalid/x", "Article 9 Risk management system"
FAKE: dict[str, Any] = {name: URL for name in ("foundry_project_endpoint", "search_endpoint", "cosmos_endpoint")}
FAKE |= {"corpus_container_url": "https://x.invalid/corpus", "storage_account_resource_id": "/subscriptions/x/rg/st"}
FAKE |= {"entra_tenant_id": TENANT, "api_audience": AUDIENCE, "model_provider": "ollama", "require_auth": True}


class FakeAgent:
    def __init__(
        self, value: Any = None, error: Exception | None = None, make: Callable[[str], Any] | None = None
    ) -> None:
        self.value, self.error, self.make, self.prompts = value, error, make, list[str]()

    async def run(self, prompt: str, *, session: AgentSession | None = None, options: Any = None) -> SimpleNamespace:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(value=self.make(prompt) if self.make else self.value, text="", usage_details=USAGE)


def as_agent(fake: FakeAgent) -> Agent[Any]:
    return cast(Agent[Any], fake)


def make_chunk(chunk_id: str, label: str = LABEL, hybrid: float = 0.0, rerank: float | None = None) -> Chunk:
    names = {"parent_id": "parent", "regulation": "EU-2024-1689", "article": label, "citation_label": label}
    text, url = f"Providers shall comply with {label}.", "https://example.com/ai-act.pdf"
    return Chunk(chunk_id=chunk_id, content=text, source_url=url, hybrid_score=hybrid, rerank_score=rerank, **names)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, **FAKE)
