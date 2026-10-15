from typing import Any, cast

import pytest
from agent_framework import Agent, AgentSession

from app.agents import EVIDENCE_END, EVIDENCE_START, answerer_input, instructions, run, score_candidates
from app.models import CandidateScore, Chunk, QueryPlan, Ranking

CHUNK = Chunk(
    chunk_id="c1",
    parent_id="parent",
    content="Providers of high-risk AI systems shall establish a risk management system.",
    regulation="EU-2024-1689",
    article="Article 9 Risk management system",
    citation_label="Article 9 Risk management system",
    source_url="https://example.com/ai-act.pdf",
)


class FakeResponse:
    def __init__(self, value: Any, text: str = "", usage: dict[str, int] | None = None) -> None:
        self.value, self.text, self.usage_details = value, text, usage


class FakeAgent:
    def __init__(self, response: FakeResponse) -> None:
        self.response, self.prompts = response, list[str]()

    async def run(self, prompt: str, *, session: AgentSession | None = None, options: Any = None) -> FakeResponse:
        self.prompts.append(prompt)
        return self.response


def as_agent(fake: FakeAgent) -> Agent[Any]:
    return cast(Agent[Any], fake)


@pytest.mark.parametrize("name", ["planner_v1", "reranker_v1", "answerer_v1", "judge_rubric_v1"])
def test_prompts_are_versioned_markdown_files(name: str) -> None:
    assert instructions(name).startswith("# ")


def test_answerer_input_delimits_untrusted_evidence() -> None:
    text = answerer_input("Which obligations apply?", [CHUNK])
    assert text.index("Question:") < text.index(EVIDENCE_START) < text.index("chunk_id: c1") < text.index(EVIDENCE_END)


async def test_run_takes_the_parsed_value_or_parses_the_text() -> None:
    ranking = Ranking(scores=[CandidateScore(chunk_id="c1", score=0.5)])
    parsed, usage = await run(as_agent(FakeAgent(FakeResponse(ranking, usage={"input_token_count": 3}))), "p", Ranking)
    assert parsed == ranking and usage == {"input_token_count": 3}
    parsed, usage = await run(as_agent(FakeAgent(FakeResponse(None, text=ranking.model_dump_json()))), "p", Ranking)
    assert parsed == ranking and usage == {}


async def test_score_candidates_maps_ids_to_scores() -> None:
    fake = FakeAgent(FakeResponse(Ranking(scores=[CandidateScore(chunk_id="c1", score=0.9)])))
    scores, _ = await score_candidates(as_agent(fake), QueryPlan(query="risk management"), [CHUNK])
    assert scores == {"c1": 0.9} and fake.prompts[0].startswith("Query: risk management")
