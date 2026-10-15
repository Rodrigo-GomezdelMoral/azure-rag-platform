import asyncio
from dataclasses import dataclass
from typing import Any

from agent_framework import BaseChatClient
from agent_framework.azure import CosmosHistoryProvider
from agent_framework.foundry import FoundryChatClient, FoundryChatOptions
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient

from app.config import Settings


@dataclass(frozen=True)
class Clients:
    chat: BaseChatClient[Any]
    small_chat: BaseChatClient[Any]
    search: SearchClient | None = None
    cosmos: CosmosClient | None = None
    history: CosmosHistoryProvider | None = None
    credential: DefaultAzureCredential | None = None
    options: FoundryChatOptions | None = None

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in (self.search, self.cosmos, self.credential) if client))


def build_clients(settings: Settings) -> Clients:
    if settings.model_provider == "ollama":
        from agent_framework.ollama import OllamaChatClient

        local = OllamaChatClient(host=settings.ollama_host, model=settings.ollama_model)
        return Clients(chat=local, small_chat=local)
    credential = DefaultAzureCredential()
    cosmos = CosmosClient(settings.cosmos_endpoint, credential)
    history = cosmos.get_database_client(settings.cosmos_database).get_container_client(settings.history_container)
    endpoint, small = settings.foundry_project_endpoint, settings.small_chat_deployment
    return Clients(
        chat=FoundryChatClient(project_endpoint=endpoint, model=settings.chat_deployment, credential=credential),
        small_chat=FoundryChatClient(project_endpoint=endpoint, model=small, credential=credential),
        search=SearchClient(settings.search_endpoint, settings.search_index, credential),
        cosmos=cosmos,
        history=CosmosHistoryProvider(container_client=history),
        credential=credential,
        options=FoundryChatOptions(reasoning={"effort": "low"}, store=False),
    )
