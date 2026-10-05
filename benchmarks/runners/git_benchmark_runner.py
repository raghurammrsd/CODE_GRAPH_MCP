"""Git Intelligence Benchmark Runner.

Measures the latency and efficiency of:
- HEAD freshness check (<50ms target)
- Structural revision comparison (AST-level diff)
- Deep change impact analysis
- Context freshness validation
- Incremental Git synchronization
"""
from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from codegraph.change_impact import get_deep_change_impact
from codegraph.context_freshness import check_context_freshness
from codegraph.git_state import get_git_state, incremental_git_sync
from codegraph.indexing import Indexer
from codegraph.structural_diff import compare_revisions


def run_git_intelligence_benchmark(
    repository: Path,
    iterations: int = 10,
) -> dict[str, Any]:
    """Execute performance benchmarks across all Git intelligence operations."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    head_check_latencies: list[float] = []
    diff_latencies: list[float] = []
    impact_latencies: list[float] = []
    freshness_latencies: list[float] = []
    sync_latencies: list[float] = []

    with indexer.session() as con:
        # 1. Benchmark HEAD freshness check
        for _ in range(iterations):
            t0 = time.perf_counter()
            state = get_git_state(repository, con=con)
            head_check_latencies.append((time.perf_counter() - t0) * 1000.0)

        # 2. Benchmark structural revision comparison (HEAD~1 vs HEAD if git, else HEAD vs HEAD)
        base_ref = "HEAD~1" if state.is_git else "HEAD"
        head_ref = "HEAD" if state.is_git else "HEAD"
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = compare_revisions(repository, base=base_ref, head=head_ref, con=con)
            diff_latencies.append((time.perf_counter() - t0) * 1000.0)

        # 3. Benchmark deep change impact analysis
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = get_deep_change_impact(repository, con, base=base_ref, head=head_ref, max_depth=2)
            impact_latencies.append((time.perf_counter() - t0) * 1000.0)

        # 4. Benchmark context freshness check
        sample_context = {
            "metadata": {
                "indexed_commit": state.current_head or "HEAD",
                "files": [str(list(repository.glob("**/*.py"))[0].relative_to(repository))] if list(repository.glob("**/*.py")) else [],
            },
            "files": [str(list(repository.glob("**/*.py"))[0].relative_to(repository))] if list(repository.glob("**/*.py")) else [],
        }
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = check_context_freshness(sample_context, repository, con=con)
            freshness_latencies.append((time.perf_counter() - t0) * 1000.0)

        # 5. Benchmark incremental sync
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = incremental_git_sync(repository, con)
            sync_latencies.append((time.perf_counter() - t0) * 1000.0)

    def _stats(arr: list[float]) -> dict[str, float]:
        if not arr:
            return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
        s = sorted(arr)
        p50 = s[len(s) // 2]
        p95 = s[min(int(len(s) * 0.95), len(s) - 1)]
        return {
            "avg_ms": round(statistics.mean(arr), 2),
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "min_ms": round(min(arr), 2),
            "max_ms": round(max(arr), 2),
        }

    return {
        "iterations": iterations,
        "head_freshness_check": _stats(head_check_latencies),
        "structural_diff": _stats(diff_latencies),
        "deep_change_impact": _stats(impact_latencies),
        "context_freshness_validation": _stats(freshness_latencies),
        "incremental_git_sync": _stats(sync_latencies),
        "head_sub_50ms_gate": _stats(head_check_latencies)["avg_ms"] < 50.0,
    }


if __name__ == "__main__":
    import json
    import sys

    repo_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    report = run_git_intelligence_benchmark(repo_dir, iterations=10)
    print(json.dumps(report, indent=2))
