import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agent_framework import AgentSession, UsageDetails
from agent_framework.exceptions import ChatClientContentFilterException

from app.agents import Agents, answerer_input, run, score_candidates
from app.config import Settings
from app.models import Answer, Chunk, Claim, Draft, Phase, PhaseEvent, QueryPlan, RefusalReason
from app.retrieval import Retriever, rerank
from app.telemetry import current_trace_id, tracer, unverified_claims

HIDDEN = {"parent_id", "source_url", "language"}
Drafted = tuple[Draft, RefusalReason | None, UsageDetails]


@dataclass(frozen=True)
class Pipeline:
    settings: Settings
    agents: Agents
    retriever: Retriever


@dataclass
class Run:
    trace_id: str = field(default_factory=current_trace_id)
    started: float = field(default_factory=time.perf_counter)
    timings: dict[Phase, int] = field(default_factory=dict)
    usages: list[tuple[str, UsageDetails]] = field(default_factory=list)
    evidence: list[Chunk] = field(default_factory=list)
    refusal: RefusalReason | None = None

    def event(self, phase: Phase, data: dict[str, Any]) -> PhaseEvent:
        now = time.perf_counter()
        self.timings[phase], self.started = round((now - self.started) * 1000), now
        return PhaseEvent(phase=phase, trace_id=self.trace_id, elapsed_ms=sum(self.timings.values()), data=data)


def verify(draft: Draft, evidence: list[Chunk]) -> tuple[list[Claim], int]:
    labels = {chunk.chunk_id: chunk.citation_label for chunk in evidence}
    verified = [
        claim for claim in draft.claims if all(labels.get(cid) == claim.citation_label for cid in claim.chunk_ids)
    ]
    dropped = len(draft.claims) - len(verified)
    unverified_claims.add(dropped)
    return verified, dropped


def cited(claims: list[Claim], evidence: list[Chunk]) -> list[Chunk]:
    chunks = {chunk.chunk_id: chunk for chunk in evidence}
    return [chunks[cid] for cid in dict.fromkeys(cid for claim in claims for cid in claim.chunk_ids)]


def cost_eur(settings: Settings, usages: list[tuple[str, UsageDetails]]) -> float:
    prices = (settings.price(d, u.get("input_token_count") or 0, u.get("output_token_count") or 0) for d, u in usages)
    return round(sum(prices), 6)


async def draft_answer(pipeline: Pipeline, question: str, run_: Run) -> Drafted:
    if run_.refusal or not run_.evidence:
        return Draft(claims=[]), run_.refusal or RefusalReason.NO_EVIDENCE, UsageDetails()
    try:
        draft, usage = await run(pipeline.agents.answerer, answerer_input(question, run_.evidence), Draft)
    except ChatClientContentFilterException:
        return Draft(claims=[]), RefusalReason.CONTENT_FILTER, UsageDetails()
    return draft, None, usage


async def retrieve(pipeline: Pipeline, question: str, session_id: str, run_: Run) -> AsyncIterator[PhaseEvent]:
    settings, agents = pipeline.settings, pipeline.agents
    try:
        plan, usage = await run(agents.planner, question, QueryPlan, AgentSession(session_id=session_id))
    except ChatClientContentFilterException:
        run_.refusal = RefusalReason.CONTENT_FILTER
        yield run_.event("plan", {"question": question, "refusal": run_.refusal})
        return
    run_.usages.append((settings.small_chat_deployment, usage))
    filters = plan.filters.model_dump(exclude_none=True)
    yield run_.event("plan", {"question": question, "query": plan.query, "filters": filters})
    with tracer.start_as_current_span("search"):
        candidates = await pipeline.retriever.search(plan, settings.retrieve_k)
    yield run_.event("search", {"candidates": [chunk.model_dump(exclude=HIDDEN | {"content"}) for chunk in candidates]})
    scores = None
    if settings.reranker == "agent" and candidates:
        scores, usage = await score_candidates(agents.reranker, plan, candidates)
        run_.usages.append((settings.chat_deployment, usage))
    run_.evidence = rerank(candidates, settings.rerank_k, scores)
    ranked = [chunk.model_dump(exclude=HIDDEN) for chunk in run_.evidence]
    yield run_.event("rerank", {"reranker": settings.reranker, "candidates": ranked})


async def answer(
    pipeline: Pipeline, question: str, session_id: str, generate: bool = True
) -> AsyncIterator[PhaseEvent]:
    settings, run_ = pipeline.settings, Run()
    async for event in retrieve(pipeline, question, session_id, run_):
        yield event
    if not generate:
        return
    draft, refusal, usage = await draft_answer(pipeline, question, run_)
    run_.usages.append((settings.chat_deployment, usage))
    yield run_.event("answer", {"claims": len(draft.claims)})
    with tracer.start_as_current_span("verify"):
        claims, dropped = verify(draft, run_.evidence)
    refusal = refusal or (None if claims else RefusalReason.UNVERIFIED if dropped else RefusalReason.NO_EVIDENCE)
    final = run_.event("verify", {})
    result = Answer(trace_id=run_.trace_id, claims=claims, citations=cited(claims, run_.evidence), refusal=refusal)
    result.unverified_claims, result.cost_eur = dropped, cost_eur(settings, run_.usages)
    result.timings_ms = run_.timings
    yield final.model_copy(update={"data": result.model_dump()})
