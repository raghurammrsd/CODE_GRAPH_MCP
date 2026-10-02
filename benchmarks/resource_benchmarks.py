"""Resource benchmarks measuring CPU, memory stability, and coalescing efficiency.

Evaluates:
1. Active coding burst performance (burst save -> debounced incremental index -> context query).
2. Memory stability under repetitive query & index cycles.
3. Request coalescing efficiency under concurrent bursts.
"""
from __future__ import annotations

import concurrent.futures
import tempfile
import time
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.resources import (
    ResourceGovernor,
    ResourcePolicy,
    ResourceProfile,
    get_graph_cache,
    get_parse_cache,
    get_process_memory_mb,
)


def benchmark_active_coding_bursts(iterations: int = 10) -> dict[str, Any]:
    """Measure latency and CPU time across repeated edit -> index -> query cycles."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        for i in range(15):
            (repo / f"module_{i}.py").write_text(
                f"def compute_{i}(x: int) -> int:\n    return x * {i + 1}\n",
                encoding="utf-8",
            )

        gov = ResourceGovernor(ResourcePolicy.for_profile(ResourceProfile.BALANCED))
        indexer = Indexer(repo, governor=gov)
        indexer.index()

        cycle_times_ms: list[float] = []
        cpu_times_ms: list[float] = []

        mem_start = get_process_memory_mb() or 0.0

        for step in range(iterations):
            t0_wall = time.perf_counter()
            t0_cpu = time.process_time()

            # 1. Edit a file
            target_file = repo / f"module_{step % 15}.py"
            target_file.write_text(
                f"def compute_{step % 15}(x: int) -> int:\n    # revised {step}\n    return x + {step}\n",
                encoding="utf-8",
            )

            # 2. Incremental re-index (uses parse cache for unchanged files)
            indexer.index()

            # 3. Interactive context query
            with indexer.session() as con:
                packet = get_context(
                    con=con,
                    repository=repo,
                    task=f"Understand compute_{step % 15}",
                    intent="UNDERSTAND",
                )
                assert packet.freshness == "FRESH"

            elapsed_wall = (time.perf_counter() - t0_wall) * 1000.0
            elapsed_cpu = (time.process_time() - t0_cpu) * 1000.0
            cycle_times_ms.append(elapsed_wall)
            cpu_times_ms.append(elapsed_cpu)

        mem_end = get_process_memory_mb() or 0.0

        return {
            "iterations": iterations,
            "avg_cycle_wall_ms": round(sum(cycle_times_ms) / len(cycle_times_ms), 2),
            "max_cycle_wall_ms": round(max(cycle_times_ms), 2),
            "avg_cycle_cpu_ms": round(sum(cpu_times_ms) / len(cpu_times_ms), 2),
            "memory_start_mb": mem_start,
            "memory_end_mb": mem_end,
            "memory_delta_mb": round(mem_end - mem_start, 2),
            "parse_cache_stats": get_parse_cache().stats(),
            "graph_cache_stats": get_graph_cache().stats(),
        }


def benchmark_request_coalescing(concurrency: int = 8) -> dict[str, Any]:
    """Measure speedup and compute savings when concurrent queries request identical context."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "service.py").write_text(
            "def handler(req):\n    return process(req)\ndef process(data):\n    return 'ok'\n",
            encoding="utf-8",
        )
        indexer = Indexer(repo)
        indexer.index()

        def _worker_query() -> Any:
            with indexer.session() as con:
                return get_context(
                    con=con,
                    repository=repo,
                    task="Explain process handler",
                    intent="EXPLAIN",
                )

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(_worker_query) for _ in range(concurrency)]
            results = [f.result() for f in futures]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert len(results) == concurrency
        assert all(r.task == results[0].task for r in results)

        return {
            "concurrency": concurrency,
            "total_elapsed_ms": round(elapsed_ms, 2),
            "per_request_amortized_ms": round(elapsed_ms / concurrency, 2),
        }


if __name__ == "__main__":
    print("Running active coding burst benchmark...")
    res_burst = benchmark_active_coding_bursts(iterations=10)
    print("Burst Results:", res_burst)

    print("\nRunning request coalescing benchmark...")
    res_coalesce = benchmark_request_coalescing(concurrency=8)
    print("Coalesce Results:", res_coalesce)
