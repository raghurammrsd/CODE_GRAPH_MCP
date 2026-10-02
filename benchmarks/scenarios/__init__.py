"""Benchmark Scenarios Package."""
from __future__ import annotations

from benchmarks.scenarios.ambiguity import run_ambiguity_benchmark
from benchmarks.scenarios.dynamic_dispatch import run_dynamic_dispatch_benchmark
from benchmarks.scenarios.stale_evidence import run_stale_evidence_benchmark

__all__ = [
    "run_ambiguity_benchmark",
    "run_dynamic_dispatch_benchmark",
    "run_stale_evidence_benchmark",
]
