from typing import Any

import pytest

from app.models import Filters, QueryPlan
from app.retrieval import LocalRetriever, odata_filter, rerank, to_chunk
from tests.conftest import make_chunk


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (Filters(), None),
        (Filters(regulation="EU-2024-1689", language="en"), "regulation eq 'EU-2024-1689' and language eq 'en'"),
        (Filters(article="Article 9"), "search.ismatch('\"Article 9\"', 'citation_label')"),
    ],
)
def test_odata_filter(filters: Filters, expected: str | None) -> None:
    assert odata_filter(filters) == expected


def test_to_chunk_reads_both_scores() -> None:
    result: dict[str, Any] = dict.fromkeys(
        ("chunk_id", "parent_id", "content", "regulation", "article", "source_url"), "x"
    )
    result |= {"citation_label": "CHAPTER I > Article 2", "language": "en", "@search.score": 0.03}
    assert (
        to_chunk(result).rerank_score is None and to_chunk(result | {"@search.reranker_score": 2.5}).rerank_score == 2.5
    )


async def test_local_retriever_filters_and_ranks() -> None:
    plan = QueryPlan(query="risk management system high-risk AI", filters=Filters(regulation="EU-2024-1689"))
    chunks = await LocalRetriever().search(plan, k=5)
    assert len(chunks) == 5 and all(c.regulation == "EU-2024-1689" for c in chunks)
    assert chunks[0].hybrid_score >= chunks[-1].hybrid_score > 0
    assert await LocalRetriever().search(QueryPlan(query="risk", filters=Filters(article="Annex XIV")), k=5) == []


def test_rerank_applies_scores_or_follows_the_semantic_ranker_with_signed_rank_change() -> None:
    candidates = [make_chunk("a", hybrid=0.9), make_chunk("b", hybrid=0.8), make_chunk("c", hybrid=0.7)]
    ranked = rerank(candidates, k=2, scores={"c": 1.0, "a": 0.5})
    assert [(c.chunk_id, c.rerank_score, c.rank_delta) for c in ranked] == [("c", 1.0, 2), ("a", 0.5, -1)]
    semantic = [make_chunk("a", hybrid=0.9, rerank=1.0), make_chunk("b", hybrid=0.8, rerank=3.0), make_chunk("c")]
    assert [(c.chunk_id, c.rank_delta) for c in rerank(semantic, k=3)] == [("b", 1), ("a", -1), ("c", 0)]
