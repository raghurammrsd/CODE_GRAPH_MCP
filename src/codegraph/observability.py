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


def compute_latency_percentiles(latencies: list[float]) -> dict[str, float]:
    """Compute deterministic p50, p95, p99 latency statistics."""
    if not latencies:
        return {
            "count": 0,
            "min_ms": 0.0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }
    s = sorted(latencies)
    n = len(s)

    def _pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round((n - 1) * p))))
        return round(s[idx], 2)

    return {
        "count": n,
        "min_ms": round(s[0], 2),
        "avg_ms": round(sum(s) / n, 2),
        "p50_ms": _pct(0.50),
        "p95_ms": _pct(0.95),
        "p99_ms": _pct(0.99),
        "max_ms": round(s[-1], 2),
    }


@dataclass
class ToolUsageRecord:
    """Local diagnostic record for agent tool-selection and fallback behavior (Section 14)."""

    request_classification: str
    selected_codegraph_tool: str | None
    codegraph_used: bool
    codegraph_call_count: int = 0
    direct_file_reads_after: int = 0
    fallback_occurred: bool = False
    fallback_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "request_classification": self.request_classification,
            "selected_codegraph_tool": self.selected_codegraph_tool,
            "codegraph_used": self.codegraph_used,
            "codegraph_call_count": self.codegraph_call_count,
            "direct_file_reads_after": self.direct_file_reads_after,
            "fallback_occurred": self.fallback_occurred,
            "fallback_reason": self.fallback_reason,
        }


class MetricsRegistry:
    """Thread-safe, bounded in-memory metrics tracker."""

    def __init__(self, max_records: int = 500) -> None:
        self.max_records = max_records
        self._records: list[OperationMetric] = []
        self._tool_usage_records: list[ToolUsageRecord] = []

    def record(self, metric: OperationMetric) -> None:
        self._records.append(metric)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]

    def record_tool_usage(self, usage: ToolUsageRecord) -> None:
        self._tool_usage_records.append(usage)
        if len(self._tool_usage_records) > self.max_records:
            self._tool_usage_records = self._tool_usage_records[-self.max_records :]

    def get_tool_usage_summary(self) -> dict[str, object]:
        total = len(self._tool_usage_records)
        if not total:
            return {
                "total_requests": 0,
                "codegraph_used_count": 0,
                "codegraph_invocation_rate": 0.0,
                "total_codegraph_calls": 0,
                "avg_codegraph_calls": 0.0,
                "total_direct_file_reads_after": 0,
                "fallback_count": 0,
                "by_classification": {},
                "records": [],
            }
        used_count = sum(1 for r in self._tool_usage_records if r.codegraph_used)
        total_cg_calls = sum(r.codegraph_call_count for r in self._tool_usage_records)
        total_reads = sum(r.direct_file_reads_after for r in self._tool_usage_records)
        fallbacks = sum(1 for r in self._tool_usage_records if r.fallback_occurred)
        by_cls: dict[str, int] = {}
        for r in self._tool_usage_records:
            by_cls[r.request_classification] = by_cls.get(r.request_classification, 0) + 1

        return {
            "total_requests": total,
            "codegraph_used_count": used_count,
            "codegraph_invocation_rate": round(used_count / total, 4),
            "total_codegraph_calls": total_cg_calls,
            "avg_codegraph_calls": round(total_cg_calls / total, 2),
            "total_direct_file_reads_after": total_reads,
            "fallback_count": fallbacks,
            "by_classification": {k: by_cls[k] for k in sorted(by_cls.keys())},
            "records": [r.as_dict() for r in self._tool_usage_records[-25:]],
        }

    def get_summary(self) -> dict[str, object]:
        total = len(self._records)
        if not total:
            return {
                "total_operations": 0,
                "avg_latency_ms": 0.0,
                "first_request_latency_ms": 0.0,
                "warm_request_latency_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "cache_hit_rate": 0.0,
                "errors": 0,
                "tool_usage": self.get_tool_usage_summary(),
            }
        all_lats = [r.latency_ms for r in self._records]
        pcts = compute_latency_percentiles(all_lats)
        first_lat = round(self._records[0].latency_ms, 2)
        warm_lats = [r.latency_ms for r in self._records[1:]] if total > 1 else all_lats
        warm_avg = round(sum(warm_lats) / len(warm_lats), 2) if warm_lats else first_lat
        cache_hits = sum(1 for r in self._records if r.cache_hit)
        errors = sum(1 for r in self._records if r.error_class is not None)
        return {
            "total_operations": total,
            "avg_latency_ms": pcts["avg_ms"],
            "first_request_latency_ms": first_lat,
            "warm_request_latency_ms": warm_avg,
            "p50_ms": pcts["p50_ms"],
            "p95_ms": pcts["p95_ms"],
            "p99_ms": pcts["p99_ms"],
            "cache_hit_rate": round(cache_hits / total, 3),
            "errors": errors,
            "recent_operations": [r.as_dict() for r in self._records[-10:]],
            "tool_usage": self.get_tool_usage_summary(),
        }

    def clear(self) -> None:
        self._records.clear()
        self._tool_usage_records.clear()


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
