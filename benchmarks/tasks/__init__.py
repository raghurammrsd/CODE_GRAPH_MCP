"""Benchmark Tasks Package."""
from __future__ import annotations

from benchmarks.tasks.catalog import get_standard_benchmark_catalog
from benchmarks.tasks.models import BenchmarkCategory, BenchmarkTask

__all__ = [
    "BenchmarkTask",
    "BenchmarkCategory",
    "get_standard_benchmark_catalog",
]
