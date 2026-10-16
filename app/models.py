from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Phase = Literal["plan", "search", "rerank", "answer", "verify"]


class Filters(BaseModel):
    regulation: str | None = None
    article: str | None = None
    language: str | None = None


class QueryPlan(BaseModel):
    query: str = Field(description="The question rewritten as a retrieval query.")
    filters: Filters = Field(default_factory=Filters)


class Chunk(BaseModel):
    chunk_id: str
    parent_id: str
    content: str
    regulation: str
    article: str
    citation_label: str
    source_url: str
    language: str = "en"
    hybrid_score: float = 0.0
    rerank_score: float | None = None
    rank_delta: int | None = None


class CandidateScore(BaseModel):
    chunk_id: str
    score: float = Field(ge=0.0, le=1.0)


class Ranking(BaseModel):
    scores: list[CandidateScore]


class Claim(BaseModel):
    text: str
    chunk_ids: list[str] = Field(min_length=1)
    citation_label: str


class Draft(BaseModel):
    claims: list[Claim]


class RefusalReason(StrEnum):
    NO_EVIDENCE = "no_evidence"
    UNVERIFIED = "unverified"
    CONTENT_FILTER = "content_filter"


class Answer(BaseModel):
    trace_id: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Chunk] = Field(default_factory=list)
    refusal: RefusalReason | None = None
    unverified_claims: int = 0
    cost_eur: float = 0.0
    timings_ms: dict[Phase, int] = Field(default_factory=dict)


class PhaseEvent(BaseModel):
    phase: Phase
    trace_id: str
    elapsed_ms: int
    data: dict[str, Any] = Field(default_factory=dict)
