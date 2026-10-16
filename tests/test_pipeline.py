import pytest
from agent_framework.exceptions import ChatClientContentFilterException
from pydantic import ValidationError

from app.agents import EVIDENCE_END, EVIDENCE_START, Agents, answerer_input, instructions, run, score_candidates
from app.answer import Pipeline, answer, verify
from app.config import Settings
from app.models import CandidateScore, Claim, Draft, PhaseEvent, QueryPlan, Ranking, RefusalReason
from app.retrieval import LocalRetriever
from tests.conftest import FakeAgent, as_agent, make_chunk

LABEL = "Article 9 Risk management system"
PLAN = QueryPlan(query="risk management system high-risk AI")
PHASES = ["plan", "search", "rerank", "answer", "verify"]


def citing(prompt: str) -> Draft:
    keys = ("chunk_id: ", "citation_label: ")
    f = dict(line.split(": ", 1) for line in prompt.splitlines() if line.startswith(keys))
    return Draft(claims=[Claim(text="grounded", chunk_ids=[f["chunk_id"]], citation_label=f["citation_label"])])


def pipeline(settings: Settings, answerer: FakeAgent, planner: FakeAgent | None = None) -> Pipeline:
    agents = Agents(as_agent(planner or FakeAgent(PLAN)), as_agent(FakeAgent()), as_agent(answerer))
    return Pipeline(settings, agents, LocalRetriever())


async def collect(pipeline_: Pipeline, generate: bool = True) -> list[PhaseEvent]:
    return [event async for event in answer(pipeline_, "What applies to risk management?", "local:test", generate)]


def test_prompts_are_files_and_the_answerer_input_delimits_untrusted_evidence() -> None:
    assert all(
        instructions(f"{name}_v1").startswith("# ") for name in ("planner", "reranker", "answerer", "judge_rubric")
    )
    text = answerer_input("Which obligations apply?", [make_chunk("c1")])
    assert text.index("Question:") < text.index(EVIDENCE_START) < text.index("chunk_id: c1") < text.index(EVIDENCE_END)
    assert "regulation: EU-2024-1689" in text


async def test_run_returns_the_structured_value_and_rejects_its_absence() -> None:
    ranking = Ranking(scores=[CandidateScore(chunk_id="c1", score=0.9)])
    parsed, usage = await run(as_agent(FakeAgent(ranking)), "p", Ranking)
    assert parsed == ranking and usage["input_token_count"] == 100
    with pytest.raises(ValidationError):
        await run(as_agent(FakeAgent(None)), "p", Ranking)
    scores, _ = await score_candidates(as_agent(FakeAgent(ranking)), PLAN, [make_chunk("c1")])
    assert scores == {"c1": 0.9}


def test_verify_drops_a_fabricated_chunk_id_and_a_mismatched_label() -> None:
    evidence = [make_chunk("c1"), make_chunk("c2", label="Article 10 Data and data governance")]
    cited = (("kept", "c1"), ("fabricated", "c9"), ("wrong", "c2"))
    verified, dropped = verify(
        Draft(claims=[Claim(text=t, chunk_ids=[c], citation_label=LABEL) for t, c in cited]), evidence
    )
    assert [claim.text for claim in verified] == ["kept"] and dropped == 2


async def test_only_fabricated_claim_becomes_a_typed_refusal(settings: Settings) -> None:
    fabricated = Draft(claims=[Claim(text="made up", chunk_ids=["sample-999"], citation_label=LABEL)])
    events = await collect(pipeline(settings, FakeAgent(fabricated)))
    assert [event.phase for event in events] == PHASES and events[3].data == {"claims": 1}
    result = events[4].data
    assert (result["refusal"], result["unverified_claims"], result["claims"]) == (RefusalReason.UNVERIFIED, 1, [])
    assert result["cost_eur"] > 0 and set(result["timings_ms"]) == set(PHASES)


async def test_grounded_claim_survives_with_its_citation(settings: Settings) -> None:
    result = (await collect(pipeline(settings, FakeAgent(make=citing))))[-1].data
    assert result["refusal"] is None and len(result["claims"]) == 1 and result["unverified_claims"] == 0
    assert result["citations"][0]["chunk_id"] == result["claims"][0]["chunk_ids"][0]


async def test_content_filter_and_retrieve_only(settings: Settings) -> None:
    failing = FakeAgent(error=ChatClientContentFilterException("blocked"))
    for blocked in (pipeline(settings, failing), pipeline(settings, FakeAgent(), failing)):
        assert (await collect(blocked))[-1].data["refusal"] == RefusalReason.CONTENT_FILTER
    assert [e.phase for e in await collect(pipeline(settings, failing), generate=False)] == PHASES[:3]
