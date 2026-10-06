"""Canonical OpenTelemetry models and reconciliation classifications.

Epistemic Invariant:
1. Static and runtime evidence are distinct:
   - STATIC_QUEUE_LINKED: Same-repo static topic match.
   - OTEL_DISTRIBUTED_VERIFIED: Real empirical telemetry links producer and consumer.
   - RUNTIME_ONLY_OBSERVED: Observed in telemetry, but consumer or producer lives in another repository/service.
   - STATIC_RUNTIME_CONFLICT: Static code points to queue X, but runtime points to queue Y or reports persistent failure.
   - UNKNOWN: Inconclusive / unobserved.
2. Zero payload retention: Never persist message bodies, tokens, or raw sensitive headers.
3. Correlation IDs are stored strictly as salted SHA-256 digests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class OTelEvidenceStatus(StrEnum):
    """Epistemic evidence classification for static and distributed links."""

    STATIC_QUEUE_LINKED = "STATIC_QUEUE_LINKED"
    OTEL_DISTRIBUTED_VERIFIED = "OTEL_DISTRIBUTED_VERIFIED"
    RUNTIME_ONLY_OBSERVED = "RUNTIME_ONLY_OBSERVED"
    STATIC_RUNTIME_CONFLICT = "STATIC_RUNTIME_CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OTelSpanRecord:
    """Sanitized, canonical representation of an ingested OpenTelemetry span."""

    trace_id: str
    span_id: str
    parent_span_id: str = ""
    service_name: str = ""
    name: str = ""
    kind: str = "INTERNAL"  # PRODUCER, CONSUMER, SERVER, CLIENT, INTERNAL
    start_time_unix_nano: int = 0
    end_time_unix_nano: int = 0
    duration_ms: float = 0.0
    status_code: str = "OK"  # OK, ERROR, UNSET
    messaging_system: str = ""
    messaging_destination: str = ""
    messaging_operation: str = ""  # publish, process, receive
    correlation_id_hash: str = ""  # Salted SHA-256 digest
    attributes: dict[str, Any] = field(default_factory=dict)
    links: tuple[tuple[str, str], ...] = ()  # ((trace_id, span_id), ...)

    @property
    def composite_id(self) -> str:
        """Stable idempotent key for deduplication."""
        return f"{self.trace_id}:{self.span_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["links"] = [{"trace_id": t, "span_id": s} for t, s in self.links]
        return d


@dataclass(frozen=True)
class TraceReconciliationResult:
    """Summary of an idempotent OTel trace ingestion and reconciliation pass."""

    spans_ingested: int
    spans_deduplicated: int
    links_upgraded: int
    links_created_runtime_only: int
    conflicts_detected: int
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
