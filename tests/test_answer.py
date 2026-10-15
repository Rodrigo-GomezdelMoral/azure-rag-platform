from typing import Any

from agent_framework import AgentSession
from agent_framework.exceptions import ChatClientContentFilterException

from app.agents import Agents
from app.answer import Pipeline, answer, verify
from app.config import Settings
from app.models import Claim, Draft, PhaseEvent, QueryPlan, RefusalReason
from app.retrieval import LocalRetriever
from tests.conftest import USAGE, FakeAgent, FakeResponse, as_agent, make_chunk

LABEL = "Article 9 Risk management system"
PLAN = QueryPlan(query="risk management system high-risk AI")


class CitingAgent(FakeAgent):
    async def run(self, prompt: str, *, session: AgentSession | None = None, options: Any = None) -> FakeResponse:
        lines = prompt.splitlines()
        chunk_id = next(line for line in lines if line.startswith("chunk_id: ")).removeprefix("chunk_id: ")
        label = next(line for line in lines if line.startswith("citation_label: ")).removeprefix("citation_label: ")
        return FakeResponse(Draft(claims=[Claim(text="grounded", chunk_ids=[chunk_id], citation_label=label)]), USAGE)


def pipeline(settings: Settings, answerer: FakeAgent) -> Pipeline:
    agents = Agents(planner=as_agent(FakeAgent(PLAN)), reranker=as_agent(FakeAgent()), answerer=as_agent(answerer))
    return Pipeline(settings, agents, LocalRetriever())


async def collect(pipeline_: Pipeline, generate: bool = True) -> list[PhaseEvent]:
    return [event async for event in answer(pipeline_, "What applies to risk management?", "local:test", generate)]


def test_verify_drops_a_fabricated_chunk_id_and_a_mismatched_label() -> None:
    evidence = [make_chunk("c1"), make_chunk("c2", label="Article 10 Data and data governance")]
    claims = [Claim(text="kept", chunk_ids=["c1"], citation_label=LABEL)]
    claims += [
        Claim(text="fabricated", chunk_ids=["c9"], citation_label=LABEL),
        Claim(text="wrong label", chunk_ids=["c2"], citation_label=LABEL),
    ]
    verified, dropped = verify(Draft(claims=claims), evidence)
    assert [claim.text for claim in verified] == ["kept"] and dropped == 2


async def test_only_fabricated_claim_becomes_a_typed_refusal(settings: Settings) -> None:
    fabricated = Draft(claims=[Claim(text="made up", chunk_ids=["sample-999"], citation_label=LABEL)])
    events = await collect(pipeline(settings, FakeAgent(fabricated)))
    assert [event.phase for event in events] == ["plan", "search", "rerank", "answer", "verify"]
    assert events[3].data == {"claims": 1}
    result = events[4].data
    assert (result["refusal"], result["unverified_claims"], result["claims"]) == (RefusalReason.UNVERIFIED, 1, [])
    assert result["cost_eur"] > 0 and set(result["timings_ms"]) == {"plan", "search", "rerank", "answer", "verify"}


async def test_grounded_claim_survives_with_its_citation(settings: Settings) -> None:
    result = (await collect(pipeline(settings, CitingAgent())))[-1].data
    assert result["refusal"] is None and len(result["claims"]) == 1 and result["unverified_claims"] == 0
    assert result["citations"][0]["chunk_id"] == result["claims"][0]["chunk_ids"][0]
    assert result["citations"][0]["source_url"].startswith("https://")


async def test_content_filter_and_retrieve_only(settings: Settings) -> None:
    filtered = pipeline(settings, FakeAgent(error=ChatClientContentFilterException("blocked")))
    assert (await collect(filtered))[-1].data["refusal"] == RefusalReason.CONTENT_FILTER
    assert [event.phase for event in await collect(filtered, generate=False)] == ["plan", "search", "rerank"]
