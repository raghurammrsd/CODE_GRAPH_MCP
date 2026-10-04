"""Canonical Runtime Observation & Static-Runtime Reconciliation Models (Phases 10-13, 16).

Architectural Rules:
1. Runtime mapping is an OPTIONAL observation layer.
2. Static and runtime evidence remain strictly distinguishable (`evidence_class="RUNTIME_OBSERVED"`).
3. Never convert runtime evidence into static proof (`AST_VERIFIED`).
4. Never convert static inference into runtime fact.
5. `NOT_OBSERVED_AT_RUNTIME` means no runtime observation was ingested for the static edge;
   it NEVER means the path cannot happen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from codegraph.security.redaction import normalize_and_redact_sql, redact_payload, redact_secrets


class ReconciliationStatus(StrEnum):
    CONFIRMED_RUNTIME_PATH = "CONFIRMED_RUNTIME_PATH"
    STATIC_RUNTIME_CONFLICT = "STATIC_RUNTIME_CONFLICT"
    NOT_OBSERVED_AT_RUNTIME = "NOT_OBSERVED_AT_RUNTIME"
    RUNTIME_ONLY_OBSERVED = "RUNTIME_ONLY_OBSERVED"


@dataclass(frozen=True)
class RuntimeEvent:
    """Normalized, privacy-safe runtime observation event."""

    event_id: str
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    timestamp: str = ""
    source_format: str = "json"  # otel | json | sql_log
    http_method: str = ""
    route_path: str = ""
    handler_symbol: str = ""
    caller_symbol: str = ""
    callee_symbol: str = ""
    service_name: str = ""
    db_operation: str = ""  # SELECT | INSERT | UPDATE | DELETE | ""
    db_table: str = ""
    db_columns: tuple[str, ...] = ()
    normalized_sql: str = ""
    status_code: int | None = None
    exception_type: str = ""
    duration_ms: float = 0.0
    evidence_class: str = "RUNTIME_OBSERVED"
    runtime_generation: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.normalized_sql:
            object.__setattr__(self, "normalized_sql", normalize_and_redact_sql(self.normalized_sql))
        if self.metadata:
            object.__setattr__(self, "metadata", redact_payload(dict(self.metadata)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "timestamp": self.timestamp,
            "source_format": self.source_format,
            "http_method": self.http_method,
            "route_path": redact_secrets(self.route_path),
            "handler_symbol": self.handler_symbol,
            "caller_symbol": self.caller_symbol,
            "callee_symbol": self.callee_symbol,
            "service_name": self.service_name,
            "db_operation": self.db_operation,
            "db_table": self.db_table,
            "db_columns": list(self.db_columns),
            "normalized_sql": self.normalized_sql,
            "status_code": self.status_code,
            "exception_type": redact_secrets(self.exception_type),
            "duration_ms": self.duration_ms,
            "evidence_class": "RUNTIME_OBSERVED",
            "runtime_generation": self.runtime_generation,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RuntimeAggregatedEdge:
    """Compact, deduplicated runtime edge stored in SQLite (Phase 16)."""

    edge_id: str
    source: str
    target: str
    relationship: str  # HANDLED_BY | CALLS | READS_TABLE | WRITES_TABLE | READS_COLUMN | WRITES_COLUMN
    operation: str = ""
    evidence_class: str = "RUNTIME_OBSERVED"
    observation_count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    sample_trace_id: str = ""
    sample_span_id: str = ""
    normalized_sql: str = ""
    status_code: int | None = None
    exception_type: str = ""
    runtime_generation: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship,
            "operation": self.operation,
            "evidence_class": "RUNTIME_OBSERVED",
            "confidence": "HIGH",
            "status": "RUNTIME_OBSERVED",
            "observation_count": self.observation_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "avg_duration_ms": round(self.avg_duration_ms, 3),
            "max_duration_ms": round(self.max_duration_ms, 3),
            "sample_trace_id": self.sample_trace_id,
            "sample_span_id": self.sample_span_id,
            "normalized_sql": self.normalized_sql,
            "status_code": self.status_code,
            "exception_type": self.exception_type,
            "runtime_generation": self.runtime_generation,
        }
