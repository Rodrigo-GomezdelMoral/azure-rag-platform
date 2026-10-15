import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agent_framework import AgentSession, UsageDetails
from agent_framework.exceptions import ChatClientContentFilterException

from app.agents import Agents, answerer_input, run, score_candidates
from app.config import Settings
from app.models import Answer, Chunk, Citation, Claim, Draft, Phase, PhaseEvent, QueryPlan, RefusalReason
from app.retrieval import Retriever, rerank
from app.telemetry import current_trace_id, tracer, unverified_claims


@dataclass(frozen=True)
class Pipeline:
    settings: Settings
    agents: Agents
    retriever: Retriever


@dataclass
class Run:
    trace_id: str = field(default_factory=current_trace_id)
    started: float = field(default_factory=time.perf_counter)
    timings_ms: dict[Phase, int] = field(default_factory=dict)
    usages: list[tuple[str, UsageDetails]] = field(default_factory=list)

    def lap(self, phase: Phase) -> int:
        now = time.perf_counter()
        self.timings_ms[phase], self.started = round((now - self.started) * 1000), now
        return sum(self.timings_ms.values())

    def event(self, phase: Phase, data: dict[str, Any]) -> PhaseEvent:
        return PhaseEvent(phase=phase, trace_id=self.trace_id, elapsed_ms=self.lap(phase), data=data)


def verify(draft: Draft, evidence: list[Chunk]) -> tuple[list[Claim], int]:
    labels = {chunk.chunk_id: chunk.citation_label for chunk in evidence}
    verified = [
        claim for claim in draft.claims if all(labels.get(cid) == claim.citation_label for cid in claim.chunk_ids)
    ]
    dropped = len(draft.claims) - len(verified)
    unverified_claims.add(dropped)
    return verified, dropped


def citations(claims: list[Claim], evidence: list[Chunk]) -> list[Citation]:
    chunks = {chunk.chunk_id: chunk for chunk in evidence}
    cited = dict.fromkeys(cid for claim in claims for cid in claim.chunk_ids)
    return [
        Citation(chunk_id=cid, citation_label=chunks[cid].citation_label, source_url=chunks[cid].source_url)
        for cid in cited
    ]


def cost_eur(settings: Settings, usages: list[tuple[str, UsageDetails]]) -> float:
    prices = (settings.price(d, u.get("input_token_count") or 0, u.get("output_token_count") or 0) for d, u in usages)
    return round(sum(prices), 6)


def scored(chunk: Chunk) -> dict[str, Any]:
    return chunk.model_dump(exclude={"content", "parent_id", "source_url", "language"})


async def draft_answer(
    pipeline: Pipeline, run_: Run, question: str, evidence: list[Chunk]
) -> tuple[Draft, RefusalReason | None]:
    if not evidence:
        return Draft(claims=[]), RefusalReason.NO_EVIDENCE
    try:
        draft, usage = await run(pipeline.agents.answerer, answerer_input(question, evidence), Draft)
    except ChatClientContentFilterException:
        return Draft(claims=[]), RefusalReason.CONTENT_FILTER
    run_.usages.append((pipeline.settings.chat_deployment, usage))
    return draft, None


async def answer(
    pipeline: Pipeline, question: str, session_id: str, generate: bool = True
) -> AsyncIterator[PhaseEvent]:
    settings, agents, run_ = pipeline.settings, pipeline.agents, Run()
    plan, usage = await run(agents.planner, question, QueryPlan, AgentSession(session_id=session_id))
    run_.usages.append((settings.small_chat_deployment, usage))
    yield run_.event(
        "plan", {"question": question, "query": plan.query, "filters": plan.filters.model_dump(exclude_none=True)}
    )
    with tracer.start_as_current_span("search"):
        candidates = await pipeline.retriever.search(plan, settings.retrieve_k)
    yield run_.event("search", {"candidates": [scored(chunk) for chunk in candidates]})
    scores = None
    if settings.reranker == "agent" and candidates:
        scores, usage = await score_candidates(agents.reranker, plan, candidates)
        run_.usages.append((settings.chat_deployment, usage))
    evidence = rerank(candidates, settings.rerank_k, scores)
    yield run_.event("rerank", {"reranker": settings.reranker, "candidates": [scored(chunk) for chunk in evidence]})
    if not generate:
        return
    draft, refusal = await draft_answer(pipeline, run_, question, evidence)
    yield run_.event("answer", {"claims": len(draft.claims)})
    with tracer.start_as_current_span("verify"):
        claims, dropped = verify(draft, evidence)
    if refusal is None and not claims:
        refusal = RefusalReason.UNVERIFIED if dropped else RefusalReason.NO_EVIDENCE
    elapsed = run_.lap("verify")
    result = Answer(trace_id=run_.trace_id, claims=claims, citations=citations(claims, evidence), refusal=refusal)
    result.unverified_claims, result.cost_eur, result.timings_ms = (
        dropped,
        cost_eur(settings, run_.usages),
        run_.timings_ms,
    )
    yield PhaseEvent(phase="verify", trace_id=run_.trace_id, elapsed_ms=elapsed, data=result.model_dump())
