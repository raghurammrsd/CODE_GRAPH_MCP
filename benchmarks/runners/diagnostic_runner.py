"""Diagnostic benchmark runner — emits TaskDiagnosticReport for every task."""
from __future__ import annotations

import time
from pathlib import Path

from benchmarks.diagnostics import TaskDiagnosticReport, build_task_diagnostic
from benchmarks.tasks import BenchmarkTask
from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.task import TaskSpec


def run_diagnostic_benchmark(
    repository: Path,
    tasks: list[BenchmarkTask],
    max_tokens: int = 20_000,
) -> list[TaskDiagnosticReport]:
    """Run every task and produce a TaskDiagnosticReport for each."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    reports: list[TaskDiagnosticReport] = []

    with indexer.session() as con:
        for t in tasks:
            task_input = TaskSpec(
                raw_prompt=t.prompt,
                goal=t.prompt,
                intent=t.intent,
                exclusions=tuple(list(t.excluded_symbols) + list(t.excluded_files)),
            )
            t0 = time.perf_counter()
            packet = get_context(
                con=con,
                repository=repository,
                task=task_input,
                intent=t.intent,
                max_tokens=t.max_context_tokens or max_tokens,
                explain=True,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            packet_dict = packet.as_dict()

            report = build_task_diagnostic(
                task_id=t.task_id,
                category=t.category,
                intent=t.intent,
                prompt=t.prompt,
                packet_dict=packet_dict,
                expected_symbols=list(t.expected_symbols),
                expected_relationships=[
                    f"{src}->{tgt}" for src, tgt, _ in t.expected_relationships
                ],
                expected_routes=list(t.expected_entry_points),
                expected_tests=list(t.expected_tests),
                excluded_symbols=list(t.excluded_symbols),
                excluded_files=list(t.excluded_files),
                latency_ms=elapsed_ms,
            )
            reports.append(report)

    return reports
