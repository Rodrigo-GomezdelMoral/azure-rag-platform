import argparse
import asyncio
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_framework import EvalItem, EvalResults, LocalEvaluator, Message
from agent_framework.foundry import FoundryChatClient, FoundryEvals

from app.agents import build_agents
from app.answer import Pipeline, answer
from app.clients import Clients, build_clients
from app.config import Settings
from app.models import Chunk, QueryPlan
from app.retrieval import Retriever, SearchRetriever
from eval.evaluators import METRICS, THRESHOLDS, check

DATASETS = Path(__file__).with_name("datasets")
REPORTS = Path(__file__).resolve().parent.parent / "docs" / "reports"
JUDGED, JUDGE_SCALE = ("groundedness", "relevance"), 5
SUITES = {
    "smoke": ["smoke"],
    "full": ["golden", "unanswerable", "multihop", "adversarial"],
    "calibration": ["calibration"],
}
PLANTED = {"regulation": "MDCG-0000-0", "article": "Planted guidance", "citation_label": "Planted guidance"}


@dataclass(frozen=True)
class Planted:
    inner: Retriever
    passage: str

    async def search(self, plan: QueryPlan, k: int) -> list[Chunk]:
        planted = Chunk(
            chunk_id="planted",
            parent_id="planted",
            content=self.passage,
            source_url="https://example.invalid",
            **PLANTED,
        )
        return [planted.model_copy(update={"rerank_score": 9.0}), *await self.inner.search(plan, k)]


def rows(suite: str) -> list[dict[str, Any]]:
    text = "".join((DATASETS / f"{name}.jsonl").read_text(encoding="utf-8") for name in SUITES[suite])
    return [json.loads(line) for line in text.splitlines() if line]


def rendered(result: dict[str, Any]) -> str:
    claims = "\n".join(f"{claim['text']} [{claim['citation_label']}]" for claim in result["claims"])
    return f"Refused: {result['refusal']}." if result["refusal"] else claims


def item(row: dict[str, Any], response: str, context: str, data: dict[str, Any]) -> EvalItem:
    conversation = [Message("user", [row["question"]]), Message("assistant", [response], additional_properties=data)]
    return EvalItem(conversation=conversation, context=context)


async def evaluate_row(pipeline: Pipeline, row: dict[str, Any], limit: asyncio.Semaphore) -> EvalItem:
    if row.get("planted_passage"):
        pipeline = Pipeline(pipeline.settings, pipeline.agents, Planted(pipeline.retriever, row["planted_passage"]))
    async with limit:
        events = {event.phase: event.data async for event in answer(pipeline, row["question"], f"eval:{row['id']}")}
    reranked = events["rerank"]["candidates"]
    seen = {chunk["chunk_id"] for chunk in reranked}
    ranked = reranked + [chunk for chunk in events["search"]["candidates"] if chunk["chunk_id"] not in seen]
    data = {"row": row, "answer": events["verify"], "ranked": ranked, "text": rendered(events["verify"])}
    return item(row, data["text"], "\n\n".join(chunk["content"] for chunk in reranked), data)


def kappa(pairs: list[tuple[int, int]]) -> dict[str, float | int]:
    agreement = sum(a == b for a, b in pairs) / len(pairs)
    human, judge = sum(a for a, _ in pairs) / len(pairs), sum(b for _, b in pairs) / len(pairs)
    chance = human * judge + (1 - human) * (1 - judge)
    matrix = {f"human_{a}_judge_{b}": sum(x == a and y == b for x, y in pairs) for a in (0, 1) for b in (0, 1)}
    return {"kappa": round((agreement - chance) / (1 - chance), 3) if chance < 1 else 1.0, "n": len(pairs), **matrix}


def mean(values: list[float]) -> dict[str, float | int] | None:
    return {"mean": round(statistics.fmean(values), 4), "n": len(values)} if values else None


def summarise(items: list[EvalItem], local: EvalResults | None, judged: EvalResults | None) -> dict[str, Any]:
    data = [item.conversation[-1].additional_properties for item in items]
    report: dict[str, Any] = {"items": len(items), "thresholds": THRESHOLDS}
    if local is not None:
        report["local_pass_counts"] = local.per_evaluator
        failed = [(item.item_id, score) for item in local.items or [] for score in item.scores if score.passed is False]
        report["failures"] = [f"{i}: {s.name} {(s.sample or {}).get('reason')}" for i, s in failed]
        report |= {name: mean([v for v in map(metric, data) if v is not None]) for name, metric in METRICS.items()}
    if judged is not None:
        report["judge_report_url"] = judged.report_url
        for name in JUDGED:
            scores = [s.score / JUDGE_SCALE for r in judged.items or [] for s in r.scores if s.name == name]
            labelled = [(d["human"][name], int(v >= 0.6)) for d, v in zip(data, scores, strict=False) if d.get("human")]
            report |= {name: mean(scores), f"{name}_kappa": kappa(labelled) if labelled else "pending human labels"}
    return report


async def evaluate(suite: str, settings: Settings, clients: Clients) -> tuple[list[EvalItem], EvalResults | None]:
    if suite == "calibration":
        return [item(row, row["response"], row["context"], row) for row in rows(suite)], None
    assert clients.search is not None, "evaluation runs against the deployed index"
    pipeline = Pipeline(
        settings, build_agents(clients), SearchRetriever(clients.search, settings.semantic_configuration)
    )
    limit = asyncio.Semaphore(6)
    items = list(await asyncio.gather(*(evaluate_row(pipeline, row, limit) for row in rows(suite))))
    checks = LocalEvaluator(*(check(name, metric) for name, metric in METRICS.items()))
    return items, await checks.evaluate(items, eval_name=suite)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pipeline on a dataset suite and write a report")
    parser.add_argument("--suite", choices=SUITES, default="smoke")
    suite, settings, started = parser.parse_args().suite, Settings(), datetime.now(UTC)
    clients = build_clients(settings)
    assert isinstance(clients.chat, FoundryChatClient), "the judge runs in Foundry"
    items, local = await evaluate(suite, settings, clients)
    answered = [it for it in items if not it.response.startswith("Refused:")]
    judge = FoundryEvals(client=clients.chat, evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.RELEVANCE])
    judged = await judge.evaluate(answered, eval_name=f"{suite}-judge") if answered else None
    report = summarise(items, local, judged) | {"suite": suite, "started": started.isoformat(timespec="seconds")}
    report |= {"reranker": settings.reranker, "deployments": [settings.small_chat_deployment, settings.chat_deployment]}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{started:%Y-%m-%d}-{suite}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    await clients.close()
    if local is not None:
        local.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
