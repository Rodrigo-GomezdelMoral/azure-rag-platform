from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# EUR per million tokens (input, output), GlobalStandard, Azure Retail Prices API, Sweden Central, 2026-10-14.
PRICES_EUR_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-5-mini": (0.22, 1.76),
    "gpt-5-nano": (0.044, 0.352),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_provider: Literal["foundry", "ollama"] = "foundry"
    foundry_project_endpoint: str
    chat_deployment: str = "gpt-5-mini"
    small_chat_deployment: str = "gpt-5-nano"
    embedding_deployment: str = "text-embedding-3-small"
    search_endpoint: str
    search_index: str = "regulations"
    cosmos_endpoint: str
    cosmos_database: str = "rag"
    history_container: str = "history"
    feedback_container: str = "feedback"
    corpus_container_url: str
    entra_tenant_id: str
    api_audience: str
    required_app_role: str = "Rag.Query"
    require_auth: bool = True
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    applicationinsights_connection_string: str | None = None
    retrieve_k: int = Field(default=30, ge=1, le=100)
    rerank_k: int = Field(default=8, ge=1, le=50)
    reranker: Literal["semantic", "agent"] = "semantic"

    @property
    def semantic_configuration(self) -> str:
        return f"{self.search_index}-semantic"

    def price(self, deployment: str, prompt_tokens: int, completion_tokens: int) -> float:
        prompt_price, completion_price = PRICES_EUR_PER_MILLION.get(deployment, (0.0, 0.0))
        return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000
