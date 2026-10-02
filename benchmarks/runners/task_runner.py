"""Benchmark Task Runner executing benchmark catalog tasks against indexed repositories."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from benchmarks.metrics import BenchmarkTaskResult, evaluate_task_output
from benchmarks.tasks import BenchmarkTask
from codegraph.context import get_context
from codegraph.indexing import Indexer


def run_benchmark_tasks(
    repository: Path,
    tasks: list[BenchmarkTask],
    max_tokens: int = 20_000,
    explain: bool = True,
) -> dict[str, Any]:
    """Execute benchmark tasks and compute comprehensive metrics."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    task_results: list[BenchmarkTaskResult] = []
    from codegraph.task import TaskSpec

    with indexer.session() as con:
        for t in tasks:
            t0 = time.perf_counter()
            task_input = TaskSpec(
                raw_prompt=t.prompt,
                goal=t.prompt,
                intent=t.intent,
                exclusions=tuple(list(t.excluded_symbols) + list(t.excluded_files)),
            )
            packet = get_context(
                con=con,
                repository=repository,
                task=task_input,
                intent=t.intent,
                max_tokens=t.max_context_tokens or max_tokens,
                explain=explain,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            packet_dict = packet.as_dict()

            res = evaluate_task_output(
                task_id=t.task_id,
                intent=t.intent,
                context_packet=packet_dict,
                expected_entrypoints=list(t.expected_entry_points),
                expected_symbols=list(t.expected_symbols),
                expected_relationships=[f"{src}->{tgt}" for src, tgt, _ in t.expected_relationships],
                expected_tests=list(t.expected_tests),
                excluded_symbols=list(t.excluded_symbols),
                latency_ms=elapsed_ms,
                expected_path_nodes=list(t.expected_path_nodes),
                expected_unknowns=list(t.expected_unknowns),
                expected_ambiguities=list(t.expected_ambiguities),
                category=t.category,
            )
            task_results.append(res)

    # Compute category breakdowns and overall aggregate
    by_category: dict[str, list[BenchmarkTaskResult]] = {}
    for r in task_results:
        by_category.setdefault(r.category, []).append(r)

    def _aggregate(group: list[BenchmarkTaskResult]) -> dict[str, float]:
        n = max(len(group), 1)
        return {
            "count": len(group),
            "avg_latency_ms": round(sum(x.latency_ms for x in group) / n, 2),
            "symbol_precision": round(sum(x.symbol_precision for x in group) / n, 4),
            "symbol_recall": round(sum(x.symbol_recall for x in group) / n, 4),
            "relationship_precision": round(sum(x.relationship_precision for x in group) / n, 4),
            "relationship_recall": round(sum(x.relationship_recall for x in group) / n, 4),
            "route_accuracy": round(sum(x.route_accuracy for x in group) / n, 4),
            "test_discovery_accuracy": round(sum(x.test_discovery_accuracy for x in group) / n, 4),
            "unsupported_claim_rate": round(sum(x.unsupported_claim_rate for x in group) / n, 4),
            "task_coverage": round(sum(x.task_coverage for x in group) / n, 4),
            "redundancy_ratio": round(sum(x.redundancy_ratio for x in group) / n, 4),
            "avg_selected_tokens": round(sum(x.selected_tokens for x in group) / n, 1),
            "avg_reduction_ratio": round(sum(x.reduction_ratio for x in group) / n, 4),
        }

    category_summaries = {cat: _aggregate(grp) for cat, grp in by_category.items()}
    overall_summary = _aggregate(task_results)

    return {
        "total_tasks": len(task_results),
        "overall": overall_summary,
        "categories": category_summaries,
        "tasks": [r.as_dict() for r in task_results],
    }
