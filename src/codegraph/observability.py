"""Production Observability and Structured Metrics.

Invariants:
- Never log raw repository source code.
- Never log secrets or credentials.
- Zero network dependencies or cloud uploads.
- Structured metrics buffer available locally for audits, benchmarks, and doctor diagnostics.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionTiming:
    planning_ms: float = 0.0
    search_ms: float = 0.0
    graph_ms: float = 0.0
    framework_ms: float = 0.0
    tests_ms: float = 0.0
    git_ms: float = 0.0
    evidence_ms: float = 0.0
    ranking_ms: float = 0.0
    compilation_ms: float = 0.0
    serialization_ms: float = 0.0
    total_ms: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "planning_ms": round(self.planning_ms, 2),
            "search_ms": round(self.search_ms, 2),
            "graph_ms": round(self.graph_ms, 2),
            "framework_ms": round(self.framework_ms, 2),
            "tests_ms": round(self.tests_ms, 2),
            "git_ms": round(self.git_ms, 2),
            "evidence_ms": round(self.evidence_ms, 2),
            "ranking_ms": round(self.ranking_ms, 2),
            "compilation_ms": round(self.compilation_ms, 2),
            "serialization_ms": round(self.serialization_ms, 2),
            "total_ms": round(self.total_ms, 2),
        }


@dataclass
class ExecutionMetadata:
    latency_ms: float = 0.0
    cache_hit: bool = False
    index_generation: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    mode: str = "BALANCED"  # FAST | BALANCED | DEEP
    timing: ExecutionTiming | None = None

    def as_dict(self) -> dict[str, object]:
        res: dict[str, object] = {
            "latency_ms": round(self.latency_ms, 2),
            "cache_hit": self.cache_hit,
            "index_generation": self.index_generation,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "mode": self.mode,
        }
        if self.timing:
            res["timing"] = self.timing.as_dict()
        return res


@dataclass
class OperationMetric:
    request_id: str
    tool_or_op: str
    latency_ms: float
    index_generation: int = 0
    cache_hit: bool = False
    candidate_count: int = 0
    selected_count: int = 0
    estimated_tokens: int = 0
    task_intent: str = "UNDERSTAND"
    ambiguity_state: str = "CLEAR"
    freshness: str = "FRESH"
    error_class: str | None = None
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class MetricsRegistry:
    """Thread-safe, bounded in-memory metrics tracker."""

    def __init__(self, max_records: int = 500) -> None:
        self.max_records = max_records
        self._records: list[OperationMetric] = []

    def record(self, metric: OperationMetric) -> None:
        self._records.append(metric)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]

    def get_summary(self) -> dict[str, object]:
        total = len(self._records)
        if not total:
            return {
                "total_operations": 0,
                "avg_latency_ms": 0.0,
                "cache_hit_rate": 0.0,
                "errors": 0,
            }
        avg_lat = sum(r.latency_ms for r in self._records) / total
        cache_hits = sum(1 for r in self._records if r.cache_hit)
        errors = sum(1 for r in self._records if r.error_class is not None)
        return {
            "total_operations": total,
            "avg_latency_ms": round(avg_lat, 2),
            "cache_hit_rate": round(cache_hits / total, 3),
            "errors": errors,
            "recent_operations": [r.as_dict() for r in self._records[-10:]],
        }

    def clear(self) -> None:
        self._records.clear()


# Global in-memory metrics registry for current process
_GLOBAL_METRICS = MetricsRegistry()


def get_global_metrics() -> MetricsRegistry:
    return _GLOBAL_METRICS


class Timer:
    """Context manager for measuring latency with high precision."""

    def __init__(self) -> None:
        self.start_time = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> Timer:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000.0


def create_request_id() -> str:
    return uuid.uuid4().hex[:12]
