import re
from pathlib import Path
from typing import Any, Protocol

from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizableTextQuery

from app.models import Chunk, Filters, QueryPlan

SELECT = ["chunk_id", "parent_id", "content", "regulation", "article", "citation_label", "source_url", "language"]
SAMPLE_CHUNKS = Path(__file__).resolve().parent.parent / "data" / "sample-chunks.jsonl"


def odata_filter(filters: Filters) -> str | None:
    exact = (("regulation", filters.regulation), ("language", filters.language))
    clauses = [f"{field} eq '{value}'" for field, value in exact if value]
    if filters.article:
        clauses.append(f"search.ismatch('\"{filters.article}\"', 'citation_label')")
    return " and ".join(clauses) or None


def to_chunk(result: dict[str, Any]) -> Chunk:
    fields = {name: result[name] for name in SELECT}
    return Chunk(**fields, hybrid_score=result["@search.score"], rerank_score=result.get("@search.reranker_score"))


class Retriever(Protocol):
    async def search(self, plan: QueryPlan, k: int) -> list[Chunk]: ...


class SearchRetriever:
    def __init__(self, client: SearchClient, semantic_configuration: str) -> None:
        self._client, self._semantic_configuration = client, semantic_configuration

    async def search(self, plan: QueryPlan, k: int) -> list[Chunk]:
        vector = VectorizableTextQuery(text=plan.query, k_nearest_neighbors=k, fields="content_vector")
        results = await self._client.search(
            search_text=plan.query,
            vector_queries=[vector],
            filter=odata_filter(plan.filters),
            query_type="semantic",
            semantic_configuration_name=self._semantic_configuration,
            top=k,
            select=SELECT,
        )
        return [to_chunk(result) async for result in results]


def terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class LocalRetriever:
    def __init__(self, path: Path = SAMPLE_CHUNKS) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        self._chunks = [Chunk.model_validate_json(line) for line in lines if line]

    async def search(self, plan: QueryPlan, k: int) -> list[Chunk]:
        wanted, filters = terms(plan.query), plan.filters
        scored = [
            chunk.model_copy(update={"hybrid_score": len(wanted & terms(chunk.content)) / max(len(wanted), 1)})
            for chunk in self._chunks
            if filters.regulation in (None, chunk.regulation)
            and filters.language in (None, chunk.language)
            and (filters.article or "").lower() in chunk.citation_label.lower()
        ]
        return sorted(scored, key=lambda chunk: chunk.hybrid_score, reverse=True)[:k]


def rerank(candidates: list[Chunk], k: int, scores: dict[str, float] | None = None) -> list[Chunk]:
    if scores is not None:
        candidates = [
            chunk.model_copy(update={"rerank_score": scores.get(chunk.chunk_id, 0.0)}) for chunk in candidates
        ]
    position = {chunk.chunk_id: index for index, chunk in enumerate(candidates)}
    ranked = sorted(
        candidates,
        key=lambda chunk: chunk.hybrid_score if chunk.rerank_score is None else chunk.rerank_score,
        reverse=True,
    )[:k]
    return [
        chunk.model_copy(update={"rank_delta": position[chunk.chunk_id] - index}) for index, chunk in enumerate(ranked)
    ]
