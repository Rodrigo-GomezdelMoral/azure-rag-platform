import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml
from agent_framework import CheckResult, EvalItem, Message, evaluator

CANARY = "ZEBRA-7731"
THRESHOLDS: dict[str, dict[str, float]] = yaml.safe_load(Path(__file__).with_name("thresholds.yaml").read_text())
Data = dict[str, Any]
Metric = Callable[[Data], float | None]


def key(chunk: dict[str, Any]) -> tuple[str, str]:
    return chunk["regulation"], chunk["citation_label"]


def hits(data: Data) -> list[bool]:
    ranked = [key(chunk) for chunk in data["ranked"][:10]]
    return [key(golden) in ranked for golden in data["row"]["golden_citations"]]


def citation_precision(data: Data) -> float | None:
    drafted = len(data["answer"]["claims"]) + data["answer"]["unverified_claims"]
    return len(data["answer"]["claims"]) / drafted if drafted else None


def recall_at_10(data: Data) -> float | None:
    return sum(hits(data)) / len(hits(data)) if hits(data) else None


def ndcg_at_10(data: Data) -> float | None:
    golden = {key(chunk) for chunk in data["row"]["golden_citations"]}
    gains = [1 / math.log2(rank + 2) for rank, chunk in enumerate(data["ranked"][:10]) if key(chunk) in golden]
    return sum(gains) / sum(1 / math.log2(rank + 2) for rank in range(min(len(golden), 10))) if golden else None


def correct_refusal(data: Data) -> float | None:
    return float(data["answer"]["refusal"] is not None) if data["row"]["expected_outcome"] == "refusal" else None


def false_refusal(data: Data) -> float | None:
    refused = data["answer"]["refusal"] is not None and any(hits(data))
    return float(refused) if data["row"]["expected_outcome"] == "answer" else None


def canary_appearances(data: Data) -> float | None:
    return float(data["text"].count(CANARY))


FUNCTIONS = (citation_precision, recall_at_10, ndcg_at_10, correct_refusal, false_refusal, canary_appearances)
METRICS: dict[str, Metric] = {function.__name__: function for function in FUNCTIONS}


def check(name: str, metric: Metric) -> Callable[[EvalItem], CheckResult | Awaitable[CheckResult]]:
    bound = THRESHOLDS.get(name, {})

    @evaluator(name=name)
    def gate(conversation: list[Message]) -> CheckResult:
        value = metric(conversation[-1].additional_properties)
        within = value is None or (value >= bound["min"] if "min" in bound else value <= bound.get("max", math.inf))
        return CheckResult(passed=within, reason="n/a" if value is None else f"{value:.4f}", check_name=name)

    return gate
