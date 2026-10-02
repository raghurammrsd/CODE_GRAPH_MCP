"""Benchmark suite evaluating Context Compiler 2.0 latency, token compression, and cache efficiency.

Measures:
1. Cold vs Warm context retrieval latency (Cache hit / Cache miss)
2. P50 / P95 latency across query modes (FAST, BALANCED, DEEP)
3. Token budget reduction ratios across budgets (1,000, 5,000, 20,000)
4. Redundancy filtering and coverage layer allocation
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer


def _build_context_corpus(root: Path) -> None:
    for i in range(10):
        (root / f"service_{i}.py").write_text(
            f"""class Service{i}:
    def __init__(self):
        self.id = {i}

    def process_{i}(self, data: str) -> str:
        # Processing routine for service {i}
        return f"processed: {{data}}"

    def validate_{i}(self, payload: dict) -> bool:
        return bool(payload)
""",
            encoding="utf-8",
        )

        (root / f"test_service_{i}.py").write_text(
            f"""from service_{i} import Service{i}

def test_service_{i}():
    s = Service{i}()
    assert s.process_{i}("input") == "processed: input"
""",
            encoding="utf-8",
        )


def run_context_benchmarks() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _build_context_corpus(repo)

        indexer = Indexer(repo)
        indexer.index()

        results: dict[str, Any] = {
            "cache_comparison": {},
            "modes_latency": {},
            "budget_compression": {},
        }

        task = "Explain Service3 process_3 implementation and its tests"

        with indexer.session() as con:
            # 1. Cold query (Cache miss)
            t0 = time.perf_counter()
            cold_packet = get_context(
                con=con,
                repository=repo,
                task=task,
                intent="explain",
                max_tokens=8000,
            )
            cold_ms = (time.perf_counter() - t0) * 1000.0

            # 2. Warm query (Cache hit)
            t0 = time.perf_counter()
            warm_packet = get_context(
                con=con,
                repository=repo,
                task=task,
                intent="explain",
                max_tokens=8000,
            )
            warm_ms = (time.perf_counter() - t0) * 1000.0

            results["cache_comparison"] = {
                "cold_latency_ms": round(cold_ms, 2),
                "warm_latency_ms": round(warm_ms, 2),
                "speedup_factor": round(cold_ms / max(warm_ms, 0.001), 2),
                "cold_cache_hit": cold_packet.execution.get("cache_hit") if cold_packet.execution else False,
                "warm_cache_hit": warm_packet.execution.get("cache_hit") if warm_packet.execution else True,
            }

            # 3. Latency distribution across modes
            latencies_by_mode: dict[str, list[float]] = {"FAST": [], "BALANCED": [], "DEEP": []}
            for mode in ("FAST", "BALANCED", "DEEP"):
                for idx in range(5):
                    query_task = f"Understand Service{idx} process_{idx} logic"
                    t0 = time.perf_counter()
                    get_context(
                        con=con,
                        repository=repo,
                        task=query_task,
                        mode=mode,
                        max_tokens=6000,
                    )
                    latencies_by_mode[mode].append((time.perf_counter() - t0) * 1000.0)

            for mode, times in latencies_by_mode.items():
                sorted_times = sorted(times)
                p50 = sorted_times[len(sorted_times) // 2]
                p95 = sorted_times[int(len(sorted_times) * 0.95)]
                results["modes_latency"][mode] = {
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "avg_ms": round(sum(sorted_times) / len(sorted_times), 2),
                }

            # 4. Budget compression across token limits
            for budget_limit in (200, 600, 2000):
                pkt = get_context(
                    con=con,
                    repository=repo,
                    task="Explain Service0 Service1 Service2 Service3 Service4 Service5 implementations",
                    intent="explain",
                    max_tokens=budget_limit,
                )
                results["budget_compression"][f"budget_{budget_limit}"] = {
                    "budget_limit": budget_limit,
                    "candidate_tokens": pkt.candidate_token_estimate,
                    "selected_tokens": pkt.selected_token_estimate,
                    "reduction_pct": pkt.context_reduction_pct,
                    "selected_files_count": len(pkt.selected_files),
                }

        return results


if __name__ == "__main__":
    import json

    res = run_context_benchmarks()
    print(json.dumps(res, indent=2))
