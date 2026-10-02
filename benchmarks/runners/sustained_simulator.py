"""Sustained-Coding Workload Simulator (15-30 minute / multi-iteration simulator).

Simulates realistic interactive developer sessions:
1. File save burst
2. Debounced incremental indexing
3. AI coding agent context query
4. Follow-up query
5. Next file edit
Measures memory stability, CPU consumption, and latency bounds.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.resources import (
    ResourceGovernor,
    ResourcePolicy,
    ResourceProfile,
    get_process_memory_mb,
)


def run_sustained_workload_simulation(
    repository: Path,
    cycles: int = 15,
) -> dict[str, Any]:
    """Execute sustained multi-cycle developer editing and query workload."""
    governor = ResourceGovernor(ResourcePolicy.for_profile(ResourceProfile.BALANCED))
    indexer = Indexer(repository, governor=governor)
    indexer.index()

    mem_start = get_process_memory_mb() or 0.0
    peak_mem = mem_start

    cycle_latencies: list[float] = []
    total_cpu_start = time.process_time()

    editable_files = list(repository.glob("src/**/*.py"))
    if not editable_files:
        editable_files = [repository / "dummy.py"]

    for cycle in range(cycles):
        # 1. Simulate developer modifying code
        target_file = editable_files[cycle % len(editable_files)]
        original_content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        target_file.write_text(original_content + f"\n# iteration {cycle} mutation\n", encoding="utf-8")

        # 2. Incremental re-index
        indexer.index()

        # 3. Interactive agent query
        t0 = time.perf_counter()
        with indexer.session() as con:
            pkt = get_context(
                con=con,
                repository=repository,
                task="Explain recent changes in auth service and verify payment dependencies",
                mode="BALANCED",
                max_tokens=6000,
            )
            assert pkt.freshness == "FRESH"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        cycle_latencies.append(elapsed_ms)

        # 4. Follow-up query (warm cache hit)
        with indexer.session() as con:
            get_context(
                con=con,
                repository=repository,
                task="Explain recent changes in auth service and verify payment dependencies",
                mode="BALANCED",
                max_tokens=6000,
            )

        current_mem = get_process_memory_mb() or 0.0
        if current_mem > peak_mem:
            peak_mem = current_mem

        # Restore file to preserve repo state
        target_file.write_text(original_content, encoding="utf-8")

    total_cpu_time_ms = (time.process_time() - total_cpu_start) * 1000.0
    mem_end = get_process_memory_mb() or 0.0

    sorted_lat = sorted(cycle_latencies)
    p50_latency = sorted_lat[len(sorted_lat) // 2]
    p95_latency = sorted_lat[int(len(sorted_lat) * 0.95)]

    return {
        "cycles_completed": cycles,
        "initial_memory_mb": round(mem_start, 2),
        "peak_memory_mb": round(peak_mem, 2),
        "final_memory_mb": round(mem_end, 2),
        "memory_growth_mb": round(max(0.0, mem_end - mem_start), 2),
        "total_cpu_time_ms": round(total_cpu_time_ms, 2),
        "avg_latency_ms": round(sum(cycle_latencies) / len(cycle_latencies), 2),
        "p50_latency_ms": round(p50_latency, 2),
        "p95_latency_ms": round(p95_latency, 2),
        "memory_bounded": (mem_end - mem_start) < 50.0,
    }
