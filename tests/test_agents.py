import pytest
from pydantic import ValidationError

from app.agents import EVIDENCE_END, EVIDENCE_START, answerer_input, instructions, run, score_candidates
from app.models import CandidateScore, QueryPlan, Ranking
from tests.conftest import FakeAgent, as_agent, make_chunk


@pytest.mark.parametrize("name", ["planner_v1", "reranker_v1", "answerer_v1", "judge_rubric_v1"])
def test_prompts_are_versioned_markdown_files(name: str) -> None:
    assert instructions(name).startswith("# ")


def test_answerer_input_delimits_untrusted_evidence() -> None:
    text = answerer_input("Which obligations apply?", [make_chunk("c1")])
    assert text.index("Question:") < text.index(EVIDENCE_START) < text.index("chunk_id: c1") < text.index(EVIDENCE_END)
    assert "regulation: EU-2024-1689" in text


async def test_run_returns_the_structured_value_and_rejects_its_absence() -> None:
    ranking = Ranking(scores=[CandidateScore(chunk_id="c1", score=0.5)])
    parsed, usage = await run(as_agent(FakeAgent(ranking)), "p", Ranking)
    assert parsed == ranking and usage["input_token_count"] == 100
    with pytest.raises(ValidationError):
        await run(as_agent(FakeAgent(None)), "p", Ranking)


async def test_score_candidates_maps_ids_to_scores() -> None:
    fake = FakeAgent(Ranking(scores=[CandidateScore(chunk_id="c1", score=0.9)]))
    scores, _ = await score_candidates(as_agent(fake), QueryPlan(query="risk management"), [make_chunk("c1")])
    assert scores == {"c1": 0.9} and fake.prompts[0].startswith("Query: risk management")
