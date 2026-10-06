"""Tests for OpenTelemetry Distributed Tracing & Cross-Service Async Graph Reconciliation.

Verifies:
1. Critical acceptance scenario: Cross-repo runtime worker (service=order-worker, repository=UNKNOWN)
2. Static + runtime promotion: STATIC_QUEUE_LINKED -> OTEL_DISTRIBUTED_VERIFIED
3. Idempotent ingestion: re-ingesting spans produces zero duplicates
4. Zero payload leakage: payload bodies and secrets stripped, correlation IDs hashed
5. Bounded reservoir percentiles: p50, p95, p99 computed from bounded window (N <= 100)
6. CLI codegraph async ingest-traces command
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.async_queue.otel_models import (
    OTelEvidenceStatus,
    OTelSpanRecord,
)
from codegraph.async_queue.otel_parser import (
    hash_correlation_id,
    parse_otel_spans,
)
from codegraph.async_queue.reconciler import OTelTraceReconciler, compute_percentiles
from codegraph.async_queue.traversal import trace_async_flow
from codegraph.cli import app
from codegraph.indexing.indexer import Indexer


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "otel_repo"
    repo.mkdir()
    return repo


def test_cross_repo_acceptance_scenario(temp_repo: Path) -> None:
    """Acceptance test: Repo A producer linked to external Repo B consumer via OTel."""
    producer_file = temp_repo / "order_service.py"
    producer_file.write_text(
        """def place_order(order):
    producer.send("orders", order)
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    # Telemetry where producer is in Repo A, but consumer is in external Repo B (order-worker)
    spans_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "order-api"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace_abc_123",
                                "spanId": "span_prod_1",
                                "name": "orders.publish",
                                "kind": 4,  # PRODUCER
                                "startTimeUnixNano": 1000000000,
                                "endTimeUnixNano": 1010000000,
                                "attributes": [
                                    {"key": "messaging.system", "value": {"stringValue": "kafka"}},
                                    {"key": "messaging.destination", "value": {"stringValue": "orders"}},
                                    {"key": "messaging.operation", "value": {"stringValue": "publish"}},
                                ],
                            }
                        ]
                    }
                ],
            },
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "order-worker"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace_abc_123",
                                "spanId": "span_cons_1",
                                "parentSpanId": "span_prod_1",
                                "name": "process_order",
                                "kind": 5,  # CONSUMER
                                "startTimeUnixNano": 1025000000,  # 15ms after publish
                                "endTimeUnixNano": 1045000000,
                                "attributes": [
                                    {"key": "messaging.system", "value": {"stringValue": "kafka"}},
                                    {"key": "messaging.destination", "value": {"stringValue": "orders"}},
                                    {"key": "messaging.operation", "value": {"stringValue": "process"}},
                                ],
                            }
                        ]
                    }
                ],
            },
        ]
    }

    spans = parse_otel_spans(spans_payload)
    assert len(spans) == 2

    with indexer.session() as con:
        reconciler = OTelTraceReconciler(con)
        res = reconciler.reconcile_spans(spans)
        assert res.spans_ingested == 2
        assert res.links_created_runtime_only == 1

        # Check async_links table has external consumer with service identity
        link_row = con.execute("SELECT * FROM async_links WHERE destination='orders'").fetchone()
        assert link_row is not None
        assert link_row["evidence_class"] == OTelEvidenceStatus.RUNTIME_ONLY_OBSERVED.value
        assert "external:order-worker" in link_row["consumer_id"]
        assert link_row["p50_ms"] == 25.0  # 1025000000 - 1000000000 = 25ms

        meta = json.loads(link_row["metadata_json"])
        assert meta["service"] == "order-worker"
        assert meta["operation"] == "process_order"
        assert meta["repository"] == "UNKNOWN"

        # Check trace_async_flow includes the external consumer
        flow = trace_async_flow(con, "place_order")
        assert flow["status"] == "ok"
        assert any(
            c["handler_canonical_id"].startswith("external:order-worker")
            for c in flow["consumers"]
        )


def test_static_to_runtime_promotion(temp_repo: Path) -> None:
    """Test that existing same-repo static link is promoted to OTEL_DISTRIBUTED_VERIFIED."""
    service_file = temp_repo / "srv.py"
    service_file.write_text(
        """def trigger_payment(data):
    producer.send("payments", data)
""",
        encoding="utf-8",
    )

    worker_file = temp_repo / "worker.py"
    worker_file.write_text(
        """@consumer("payments")
def process_payment(data):
    pass
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    # Pre-condition: link exists as STATIC_QUEUE_LINKED
    with indexer.session() as con:
        row = con.execute("SELECT evidence_class FROM async_links WHERE destination='payments'").fetchone()
        assert row["evidence_class"] == "STATIC_QUEUE_LINKED"

    # Ingest flat JSON span pair
    spans_data = [
        {
            "trace_id": "tr_100",
            "span_id": "sp_pub",
            "service_name": "billing-api",
            "name": "payments.publish",
            "kind": "PRODUCER",
            "start_time_unix_nano": 1000000000,
            "attributes": {
                "messaging.system": "kafka",
                "messaging.destination": "payments",
                "messaging.operation": "publish",
            },
        },
        {
            "trace_id": "tr_100",
            "span_id": "sp_sub",
            "parent_span_id": "sp_pub",
            "service_name": "billing-worker",
            "name": "process_payment",
            "kind": "CONSUMER",
            "start_time_unix_nano": 1015000000,
            "attributes": {
                "messaging.system": "kafka",
                "messaging.destination": "payments",
                "messaging.operation": "process",
            },
        },
    ]

    spans = parse_otel_spans(spans_data)
    with indexer.session() as con:
        reconciler = OTelTraceReconciler(con)
        res = reconciler.reconcile_spans(spans)
        assert res.links_upgraded == 1

        row = con.execute("SELECT evidence_class, p50_ms, trace_count FROM async_links WHERE destination='payments'").fetchone()
        assert row["evidence_class"] == OTelEvidenceStatus.OTEL_DISTRIBUTED_VERIFIED.value
        assert row["p50_ms"] == 15.0
        assert row["trace_count"] == 2  # 1 initial static + 1 runtime trace


def test_idempotent_ingestion(temp_repo: Path) -> None:
    """Test re-ingesting identical spans is a no-op that never duplicates counts."""
    service_file = temp_repo / "pub.py"
    service_file.write_text(
        """def send_msg(m):
    producer.send("audit_events", m)
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    span = OTelSpanRecord(
        trace_id="tr_dup_1",
        span_id="sp_dup_1",
        messaging_system="kafka",
        messaging_destination="audit_events",
        messaging_operation="publish",
        duration_ms=10.0,
    )

    with indexer.session() as con:
        reconciler = OTelTraceReconciler(con)
        # First ingestion
        res1 = reconciler.reconcile_spans([span])
        assert res1.spans_ingested == 1
        assert res1.spans_deduplicated == 0

        # Second ingestion of the exact same span
        res2 = reconciler.reconcile_spans([span])
        assert res2.spans_ingested == 0
        assert res2.spans_deduplicated == 1


def test_zero_payload_leakage_and_correlation_hash() -> None:
    """Test sensitive payloads, tokens, and cookies are stripped, and correlation IDs are hashed."""
    raw_span = {
        "trace_id": "tr_sec_1",
        "span_id": "sp_sec_1",
        "attributes": {
            "messaging.system": "kafka",
            "messaging.destination": "orders",
            "messaging.message_id": "order-secret-999",
            "authorization": "Bearer secret_jwt_token_12345",
            "cookie": "session_id=xyz789",
            "message_body": '{"credit_card": "4111222233334444"}',
            "password": "supersecretpassword",
            "http.status_code": 200,
        },
    }

    spans = parse_otel_spans([raw_span])
    assert len(spans) == 1
    s = spans[0]

    # Verify sensitive attributes were stripped
    attrs = s.attributes
    assert "authorization" not in attrs
    assert "cookie" not in attrs
    assert "message_body" not in attrs
    assert "password" not in attrs
    assert attrs["http.status_code"] == 200

    # Verify correlation ID is hashed with salt, not stored in plaintext
    assert s.correlation_id_hash == hash_correlation_id("order-secret-999")
    assert "order-secret-999" not in s.correlation_id_hash


def test_bounded_reservoir_percentiles() -> None:
    """Test percentiles computation on sample durations."""
    samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50, p95, p99 = compute_percentiles(samples)
    assert p50 == 50.0
    assert p95 == 100.0
    assert p99 == 100.0


def test_cli_ingest_traces_command(temp_repo: Path, tmp_path: Path) -> None:
    """Test codegraph async ingest-traces CLI command."""
    runner = CliRunner()

    p_file = temp_repo / "cli_prod.py"
    p_file.write_text(
        """def trigger_event():
    producer.send("cli_topic", 123)
""",
        encoding="utf-8",
    )

    # Index repository first
    idx_res = runner.invoke(app, ["index", "-r", str(temp_repo)])
    assert idx_res.exit_code == 0

    # Write trace file
    trace_file = tmp_path / "traces.json"
    trace_file.write_text(
        json.dumps([
            {
                "trace_id": "tr_cli_1",
                "span_id": "sp_cli_p",
                "name": "cli_topic.publish",
                "service_name": "cli-service",
                "attributes": {
                    "messaging.system": "kafka",
                    "messaging.destination": "cli_topic",
                    "messaging.operation": "publish",
                },
            },
            {
                "trace_id": "tr_cli_1",
                "span_id": "sp_cli_c",
                "parent_span_id": "sp_cli_p",
                "name": "handle_cli_event",
                "service_name": "cli-worker",
                "attributes": {
                    "messaging.system": "kafka",
                    "messaging.destination": "cli_topic",
                    "messaging.operation": "process",
                },
            },
        ]),
        encoding="utf-8",
    )

    # Ingest via CLI
    cli_res = runner.invoke(app, ["async", "ingest-traces", str(trace_file), "-r", str(temp_repo)])
    assert cli_res.exit_code == 0
    assert "Spans Ingested:       2" in cli_res.output

    # Ingest via CLI --json
    json_res = runner.invoke(app, ["async", "ingest-traces", str(trace_file), "-r", str(temp_repo), "--json"])
    assert json_res.exit_code == 0
    assert '"spans_deduplicated": 2' in json_res.output  # Second run deduplicates!
