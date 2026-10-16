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
Scored = dict[int, dict[str, float]]
FULL = ["golden", "unanswerable", "multihop", "adversarial"]
SUITES = {"smoke": ["smoke"], "full": FULL, "calibration": ["calibration"]}
PLANTED: dict[str, Any] = {"chunk_id": "planted", "parent_id": "planted", "source_url": "https://example.invalid"}
PLANTED |= {"regulation": "MDCG-0000-0", "article": "Planted guidance", "citation_label": "Planted guidance"}


@dataclass(frozen=True)
class Planted:
    inner: Retriever
    passage: str

    async def search(self, plan: QueryPlan, k: int) -> list[Chunk]:
        return [Chunk(content=self.passage, rerank_score=9.0, **PLANTED), *await self.inner.search(plan, k)]


def rows(suite: str) -> list[dict[str, Any]]:
    text = "".join((DATASETS / f"{name}.jsonl").read_text(encoding="utf-8") for name in SUITES.get(suite, [suite]))
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
    reranked = events.get("rerank", {}).get("candidates", [])
    searched = events.get("search", {}).get("candidates", [])
    seen = {chunk["chunk_id"] for chunk in reranked}
    ranked = reranked + [chunk for chunk in searched if chunk["chunk_id"] not in seen]
    data = {"row": row, "answer": events["verify"], "ranked": ranked, "text": rendered(events["verify"])}
    return item(row, data["text"], "\n\n".join(chunk["content"] for chunk in reranked), data)


def kappa(pairs: list[tuple[int, int]]) -> dict[str, float | int | None]:
    agreement = sum(a == b for a, b in pairs) / len(pairs)
    human, judge = sum(a for a, _ in pairs) / len(pairs), sum(b for _, b in pairs) / len(pairs)
    chance = human * judge + (1 - human) * (1 - judge)
    matrix = {f"human_{a}_judge_{b}": sum(x == a and y == b for x, y in pairs) for a in (0, 1) for b in (0, 1)}
    return {"kappa": round((agreement - chance) / (1 - chance), 3) if chance < 1 else None, "n": len(pairs), **matrix}


def mean(values: list[float]) -> dict[str, float | int] | None:
    return {"mean": round(statistics.fmean(values), 4), "n": len(values)} if values else None


def summarise(items: list[EvalItem], local: EvalResults | None, scored: Scored | None, url: str) -> dict[str, Any]:
    data = [item.conversation[-1].additional_properties for item in items]
    report: dict[str, Any] = {"items": len(items), "thresholds": THRESHOLDS}
    if local is not None:
        report["local_pass_counts"] = local.per_evaluator
        failed = [(item.item_id, score) for item in local.items or [] for score in item.scores if score.passed is False]
        report["failures"] = [f"{i}: {s.name} {(s.sample or {}).get('reason')}" for i, s in failed]
        report |= {name: mean([v for v in map(metric, data) if v is not None]) for name, metric in METRICS.items()}
        report["cost_eur"] = mean([d["answer"]["cost_eur"] for d in data])
        report["latency_ms"] = mean([float(sum(d["answer"]["timings_ms"].values())) for d in data])
    if scored is not None:
        head, _, tail = url.partition("/r/")
        report["judge_report_url"] = f"{head}/r/<subscription>,{tail.partition(',')[2]}" if tail else head
        rows_ = [d for it, d in zip(items, data, strict=True) if not it.response.startswith("Refused:")]
        for name in JUDGED:
            scores = {i: s[name] / JUDGE_SCALE for i, s in scored.items() if name in s}
            labelled = [(rows_[i]["human"][name], int(v >= 0.6)) for i, v in scores.items() if rows_[i].get("human")]
            report |= {name: mean(list(scores.values())), f"{name}_kappa": kappa(labelled) if labelled else "no labels"}
        report["judge_unscored"] = len(rows_) - len([s for s in scored.values() if s])
    return report


async def evaluate(suite: str, settings: Settings, clients: Clients) -> tuple[list[EvalItem], EvalResults | None]:
    if suite == "calibration":
        return [item(row, row["response"], row["context"], row) for row in rows(suite)], None
    assert clients.search is not None, "evaluation runs against the deployed index"
    retriever = SearchRetriever(clients.search, settings.semantic_configuration)
    pipeline = Pipeline(settings, build_agents(clients), retriever)
    limit = asyncio.Semaphore(3)
    items = list(await asyncio.gather(*(evaluate_row(pipeline, row, limit) for row in rows(suite))))
    checks = LocalEvaluator(*(check(name, metric) for name, metric in METRICS.items()))
    return items, await checks.evaluate(items, eval_name=suite)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pipeline on a dataset suite and write a report")
    parser.add_argument("--suite", default="smoke", help="smoke, full, calibration, or one dataset name")
    suite, settings, started = parser.parse_args().suite, Settings(), datetime.now(UTC)
    clients = build_clients(settings)
    assert isinstance(clients.chat, FoundryChatClient), "the judge runs in Foundry"
    items, local = await evaluate(suite, settings, clients)
    answered = [it for it in items if not it.response.startswith("Refused:")]
    evaluators = [FoundryEvals.GROUNDEDNESS, FoundryEvals.RELEVANCE]
    judge = FoundryEvals(client=clients.chat, evaluators=evaluators, timeout=1800)
    judged = await judge.evaluate(answered, eval_name=f"{suite}-judge") if answered else None
    scored: Scored | None = None
    if judged is not None:
        page = await clients.chat.client.evals.runs.output_items.list(run_id=judged.run_id, eval_id=judged.eval_id)
        scored = {o.datasource_item_id: {r.name: r.score for r in o.results or [] if r.score} async for o in page}
    assert scored is None or any(scored.values()), "the judge scored no item: check the CI principal's Foundry role"
    url = (judged.report_url if judged is not None else None) or ""
    report = summarise(items, local, scored, url) | {"suite": suite, "started": started.isoformat(timespec="seconds")}
    report |= {"reranker": settings.reranker, "deployments": [settings.small_chat_deployment, settings.chat_deployment]}
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = f"{started:%Y-%m-%d}-{suite}-{settings.chat_deployment}-{settings.reranker}.json"
    (REPORTS / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    await clients.close()
    if local is not None:
        local.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
