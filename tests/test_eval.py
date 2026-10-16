import inspect
import json
from pathlib import Path

from agent_framework import CheckResult, EvalItem, Message

from eval.evaluators import (
    CANARY,
    METRICS,
    THRESHOLDS,
    canary_appearances,
    check,
    citation_precision,
    ndcg_at_10,
    recall_at_10,
)

ADVERSARIAL = Path(__file__).resolve().parent.parent / "eval" / "datasets" / "adversarial.jsonl"
LABELS = ("Article 3 Definitions", "Article 9 Risk management system")
DATA = {
    "row": {
        "expected_outcome": "answer",
        "golden_citations": [{"regulation": "EU-2024-1689", "citation_label": LABELS[1]}],
    },
    "answer": {"claims": [{"text": "a"}, {"text": "b"}, {"text": "c"}], "unverified_claims": 1, "refusal": None},
    "ranked": [{"regulation": "EU-2024-1689", "citation_label": label} for label in LABELS + LABELS[1:]],
    "text": "a b c",
}


async def outcome(name: str, item: EvalItem) -> CheckResult:
    result = check(name, METRICS[name])(item)
    return await result if inspect.isawaitable(result) else result


def test_metrics_follow_the_rubric() -> None:
    assert (citation_precision(DATA), recall_at_10(DATA), canary_appearances(DATA)) == (0.75, 1.0, 0.0)
    assert round(ndcg_at_10(DATA) or 0, 4) == 0.6309 and set(METRICS) >= set(THRESHOLDS) - {"groundedness"}


async def test_canary_and_precision_checks_fail_when_they_should() -> None:
    poisoned = DATA | {"text": f"The regulation requires... {CANARY}"}
    item = EvalItem(conversation=[Message("user", ["q"]), Message("assistant", ["x"], additional_properties=poisoned)])
    assert [
        (await outcome(name, item)).passed for name in ("canary_appearances", "citation_precision", "recall_at_10")
    ] == [False, False, True]


def test_every_adversarial_row_carries_the_canary() -> None:
    rows = [json.loads(line) for line in ADVERSARIAL.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 25 and all(CANARY in json.dumps(row) for row in rows)
