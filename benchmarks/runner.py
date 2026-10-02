"""Benchmark Runner for CodeGraph MCP evaluation.

Loads benchmark suites, executes context retrieval and grounding across tasks,
and computes deterministic evaluation metrics.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from benchmarks.metrics import BenchmarkTaskResult, evaluate_task_output
from codegraph.context import get_context
from codegraph.indexing import Indexer


def run_benchmark_suite(
    repository: Path,
    suite_file: Path | None = None,
    max_tokens: int = 20_000,
) -> dict[str, Any]:
    """Execute all tasks in a benchmark suite and return aggregate metrics."""
    if suite_file is None:
        suite_file = Path(__file__).parent / "tasks" / "core_suite.json"

    if not suite_file.exists():
        return {
            "error": f"Suite file not found: {suite_file}",
            "tasks": [],
            "summary": {},
        }

    tasks_data = json.loads(suite_file.read_text(encoding="utf-8"))

    # Ensure repository is indexed
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    task_results: list[BenchmarkTaskResult] = []

    with indexer.session() as con:
        for t in tasks_data:
            tid = str(t.get("id", "task"))
            intent = str(t.get("intent", "UNDERSTAND"))
            task_str = str(t.get("task", ""))

            start_t = time.perf_counter()
            packet = get_context(
                con=con,
                repository=repository,
                task=task_str,
                intent=intent,
                max_tokens=max_tokens,
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0

            res = evaluate_task_output(
                task_id=tid,
                intent=intent,
                context_packet=packet.as_dict(),
                expected_entrypoints=t.get("expected_entrypoints", []),
                expected_symbols=t.get("expected_symbols", []),
                expected_relationships=t.get("expected_relationships", []),
                expected_tests=t.get("expected_tests", []),
                excluded_symbols=t.get("excluded_symbols", []),
                latency_ms=elapsed_ms,
            )
            task_results.append(res)

    total_tasks = len(task_results)
    avg_latency = sum(r.latency_ms for r in task_results) / max(total_tasks, 1)
    avg_prec = sum(r.symbol_precision for r in task_results) / max(total_tasks, 1)
    avg_rec = sum(r.symbol_recall for r in task_results) / max(total_tasks, 1)
    avg_reduction = sum(r.reduction_ratio for r in task_results) / max(total_tasks, 1)

    summary = {
        "suite": str(suite_file.name),
        "total_tasks": total_tasks,
        "avg_latency_ms": round(avg_latency, 2),
        "avg_symbol_precision": round(avg_prec, 4),
        "avg_symbol_recall": round(avg_rec, 4),
        "avg_token_reduction_ratio": round(avg_reduction, 4),
    }

    return {
        "summary": summary,
        "tasks": [r.as_dict() for r in task_results],
    }


if __name__ == "__main__":
    import sys

    repo_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    output = run_benchmark_suite(repo_arg)
    print(json.dumps(output, indent=2))
