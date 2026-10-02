"""Budget Curve Benchmark Runner evaluating context efficiency across token limits."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from benchmarks.metrics import calculate_structural_coverage
from benchmarks.tasks import BenchmarkTask
from codegraph.context import get_context
from codegraph.indexing import Indexer

DEFAULT_BUDGET_TIERS: tuple[int, ...] = (200, 500, 1000, 2000, 4000, 8000)


def run_budget_curve_benchmark(
    repository: Path,
    tasks: list[BenchmarkTask],
    budgets: tuple[int, ...] = DEFAULT_BUDGET_TIERS,
) -> dict[str, Any]:
    """Execute tasks across multiple token budgets to construct context efficiency curves."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    curve_results: dict[int, dict[str, Any]] = {}

    with indexer.session() as con:
        for budget in budgets:
            latencies: list[float] = []
            selected_tokens_list: list[int] = []
            coverages: list[float] = []
            reduction_ratios: list[float] = []

            for t in tasks:
                t0 = time.perf_counter()
                packet = get_context(
                    con=con,
                    repository=repository,
                    task=t.prompt,
                    intent=t.intent,
                    max_tokens=budget,
                )
                latencies.append((time.perf_counter() - t0) * 1000.0)
                selected_tokens_list.append(packet.selected_token_estimate)
                reduction_ratios.append(packet.context_reduction_pct / 100.0)
                coverages.append(calculate_structural_coverage(packet.as_dict()))

            n = max(len(tasks), 1)
            curve_results[budget] = {
                "budget_limit": budget,
                "avg_latency_ms": round(sum(latencies) / n, 2),
                "avg_selected_tokens": round(sum(selected_tokens_list) / n, 1),
                "avg_task_coverage": round(sum(coverages) / n, 4),
                "avg_reduction_ratio": round(sum(reduction_ratios) / n, 4),
                "coverage_per_1k_tokens": round((sum(coverages) / n) / max((sum(selected_tokens_list) / n) / 1000.0, 0.1), 4),
            }

    return {
        "budgets": list(budgets),
        "curve": {str(k): v for k, v in curve_results.items()},
    }
