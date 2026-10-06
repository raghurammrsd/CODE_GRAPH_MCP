"""Asynchronous message queue and cross-service distributed task intelligence.

Provides static detection, queue linking, and OpenTelemetry distributed tracing
reconciliation for Kafka, Celery, AWS SQS, RabbitMQ, Redis Pub/Sub, and Streams.
"""
from __future__ import annotations

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
    AsyncQueueEntity,
    AsyncQueueEvidenceClass,
    AsyncQueueLink,
)
from codegraph.async_queue.otel_models import (
    OTelEvidenceStatus,
    OTelSpanRecord,
    TraceReconciliationResult,
)
from codegraph.async_queue.otel_parser import parse_otel_spans
from codegraph.async_queue.reconciler import OTelTraceReconciler, ensure_otel_tables
from codegraph.async_queue.scanner import AsyncQueueScanner, ensure_async_tables
from codegraph.async_queue.traversal import (
    find_queue_consumers,
    find_queue_producers,
    list_async_queues,
    trace_async_flow,
)

__all__ = [
    "AsyncConsumerRecord",
    "AsyncMessagingSystem",
    "AsyncProducerRecord",
    "AsyncQueueEntity",
    "AsyncQueueEvidenceClass",
    "AsyncQueueLink",
    "AsyncQueueScanner",
    "OTelEvidenceStatus",
    "OTelSpanRecord",
    "OTelTraceReconciler",
    "TraceReconciliationResult",
    "ensure_async_tables",
    "ensure_otel_tables",
    "find_queue_consumers",
    "find_queue_producers",
    "list_async_queues",
    "parse_otel_spans",
    "trace_async_flow",
]
