"""Latency and Analysis Depth Benchmark Runner comparing FAST, BALANCED, and DEEP modes."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer


def run_latency_modes_benchmark(
    repository: Path,
    deep_task: str = "Trace POST /api/v1/auth/login to database and explain architecture",
    iterations: int = 3,
) -> dict[str, Any]:
    """Evaluate latency, candidates explored, and graph depth across FAST, BALANCED, and DEEP modes."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    mode_metrics: dict[str, Any] = {}

    with indexer.session() as con:
        for mode in ("FAST", "BALANCED", "DEEP"):
            latencies: list[float] = []
            selected_tokens_list: list[int] = []
            symbols_count_list: list[int] = []
            relationships_count_list: list[int] = []

            for _ in range(iterations):
                t0 = time.perf_counter()
                packet = get_context(
                    con=con,
                    repository=repository,
                    task=deep_task,
                    mode=mode,
                    max_tokens=10_000,
                )
                latencies.append((time.perf_counter() - t0) * 1000.0)
                selected_tokens_list.append(packet.selected_token_estimate)
                symbols_count_list.append(len(packet.symbols))
                relationships_count_list.append(len(packet.relationships))

            mode_metrics[mode] = {
                "mode": mode,
                "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
                "p50_latency_ms": round(sorted(latencies)[len(latencies) // 2], 2),
                "avg_selected_tokens": round(sum(selected_tokens_list) / len(selected_tokens_list), 1),
                "avg_symbols_explored": round(sum(symbols_count_list) / len(symbols_count_list), 1),
                "avg_relationships_explored": round(sum(relationships_count_list) / len(relationships_count_list), 1),
            }

    return mode_metrics
