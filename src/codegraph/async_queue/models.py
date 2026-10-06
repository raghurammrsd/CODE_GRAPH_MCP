"""Data models for asynchronous message queues, task dispatches, and cross-service traces.

Epistemic Invariants:
1. Never collapse distributed message passing into a generic synchronous CALLS edge.
2. Distinct semantic relationships:
   - PRODUCES_TO_QUEUE: Producer AST call site -> Queue/Topic entity
   - CONSUMES_FROM_QUEUE: Queue/Topic entity -> Consumer Worker AST handler
   - STATIC_QUEUE_LINKED: Same-repository static topic match (static inference, not runtime proof)
   - OTEL_DISTRIBUTED_VERIFIED: OpenTelemetry runtime-confirmed trace/span/link proof
3. Queue identity: `f"{system}:{destination}"` (system + topic/queue name).
4. Never persist raw message bodies or unredacted keys.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AsyncMessagingSystem(StrEnum):
    """Supported message brokers and asynchronous execution systems."""

    KAFKA = "kafka"
    CELERY = "celery"
    AWS_SQS = "aws_sqs"
    RABBITMQ = "rabbitmq"
    REDIS = "redis"
    GENERIC = "generic"


class AsyncQueueEvidenceClass(StrEnum):
    """Epistemic evidence classification for asynchronous queue links."""

    STATIC_QUEUE_LINKED = "STATIC_QUEUE_LINKED"
    OTEL_DISTRIBUTED_VERIFIED = "OTEL_DISTRIBUTED_VERIFIED"


class AsyncOperationType(StrEnum):
    """Operation performed on the message broker."""

    PUBLISH = "publish"
    CONSUME = "consume"


@dataclass(frozen=True)
class AsyncQueueEntity:
    """Logical queue, topic, or task channel."""

    queue_id: str  # f"{system}:{destination}"
    system: AsyncMessagingSystem
    destination: str  # topic name, queue URL, or celery task name
    service: str = ""
    environment: str = ""
    is_dead_letter_queue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsyncProducerRecord:
    """Static or runtime-observed message publisher/producer call site."""

    system: AsyncMessagingSystem
    destination: str
    queue_id: str
    caller_canonical_id: str
    file_path: str
    line: int
    call_snippet: str
    confidence: str = "HIGH"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": str(self.system),
            "destination": self.destination,
            "queue_id": self.queue_id,
            "caller_canonical_id": self.caller_canonical_id,
            "file_path": self.file_path,
            "line": self.line,
            "call_snippet": self.call_snippet,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AsyncConsumerRecord:
    """Static or runtime-observed message subscriber/consumer worker handler."""

    system: AsyncMessagingSystem
    destination: str
    queue_id: str
    handler_canonical_id: str
    file_path: str
    line: int
    handler_snippet: str
    confidence: str = "HIGH"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": str(self.system),
            "destination": self.destination,
            "queue_id": self.queue_id,
            "handler_canonical_id": self.handler_canonical_id,
            "file_path": self.file_path,
            "line": self.line,
            "handler_snippet": self.handler_snippet,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AsyncQueueLink:
    """Bridged relationship between a producer and a consumer across an async boundary."""

    link_id: str
    queue_id: str
    system: AsyncMessagingSystem
    destination: str
    producer_id: str
    producer_file: str
    producer_line: int
    consumer_id: str
    consumer_file: str
    consumer_line: int
    evidence_class: AsyncQueueEvidenceClass
    confidence: str = "HIGH"
    trace_count: int = 1
    avg_latency_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "queue_id": self.queue_id,
            "system": str(self.system),
            "destination": self.destination,
            "producer_id": self.producer_id,
            "producer_file": self.producer_file,
            "producer_line": self.producer_line,
            "consumer_id": self.consumer_id,
            "consumer_file": self.consumer_file,
            "consumer_line": self.consumer_line,
            "evidence_class": str(self.evidence_class),
            "confidence": self.confidence,
            "trace_count": self.trace_count,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "error_count": self.error_count,
            "metadata": dict(self.metadata),
        }
