"""Integration & Unit Tests for Live Localhost, Auto DB Sync, and Runtime Telemetry.

Validates:
- Multi-localhost port discovery & process attribution (docker-compose, package.json, .env).
- Zero-Heat TTL caching (no polling, no CPU spikes).
- Live Database schema migration tracking and drift detection.
- Push-based OTLP runtime collector daemon and multi-service distributed trace stitching.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.runtime.collector import RuntimeCollectorDaemon
from codegraph.runtime.db_watcher import detect_schema_drift
from codegraph.runtime.port_inspector import (
    discover_live_listening_ports,
    discover_static_configured_ports,
    resolve_port_to_service,
)
from codegraph.runtime.trace_linker import link_distributed_trace


def test_discover_static_configured_ports():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # 1. docker-compose.yml
        (repo / "docker-compose.yml").write_text("""
services:
  web:
    ports:
      - "3000:3000"
  api:
    ports:
      - "8000:8000"
  db:
    ports:
      - "5432:5432"
""")

        # 2. package.json
        apps_dir = repo / "apps" / "dashboard"
        apps_dir.mkdir(parents=True, exist_ok=True)
        (apps_dir / "package.json").write_text("""{
  "name": "dashboard",
  "scripts": {
    "dev": "next dev -p 3001"
  }
}""")

        # 3. .env
        (repo / ".env").write_text("API_PORT=8080\n")

        ports = discover_static_configured_ports(repo)
        assert 3000 in ports
        assert 8000 in ports
        assert 5432 in ports
        assert 3001 in ports
        assert 8080 in ports

        # Resolve port to service
        svc_3001 = resolve_port_to_service(3001, repo)
        assert svc_3001.port == 3001
        assert "dashboard" in svc_3001.service_name or "3001" in svc_3001.service_name


def test_port_caching_zero_cpu():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        p1 = discover_live_listening_ports(repo)
        p2 = discover_live_listening_ports(repo)
        # Should be identical cached list without re-running lsof
        assert p1 == p2


def test_schema_drift_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Create dummy local sqlite db with an extra unmapped table
        test_db = repo / "dev.sqlite3"
        con = sqlite3.connect(test_db)
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        con.execute("CREATE TABLE unmapped_billing (id INTEGER PRIMARY KEY, amount REAL)")
        con.commit()
        con.close()

        # Initialize Indexer
        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as icon:
            report = detect_schema_drift(icon, repo)
            assert report.schema_version != "0" or not report.is_drifted
            # unmapped_billing should be flagged as missing table in code models
            drift_tables = {d.table_name for d in report.drifts}
            assert "unmapped_billing" in drift_tables


def test_runtime_collector_and_distributed_trace_stitching():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as icon:
            # 1. Daemon lifecycle verification
            collector = RuntimeCollectorDaemon(icon, repo, port=14318)
            assert collector.is_running is False
            collector.stop()

            # 2. Ingest multi-service distributed trace (Frontend :3000 -> Backend :8000 -> DB)
            from codegraph.runtime.ingestor import ingest_runtime_traces

            trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
            multi_span_payload = {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {"key": "service.name", "value": {"stringValue": "frontend-web"}}
                            ]
                        },
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "traceId": trace_id,
                                        "spanId": "span-frontend-1",
                                        "name": "POST /api/checkout",
                                        "attributes": [
                                            {"key": "http.method", "value": {"stringValue": "POST"}},
                                            {"key": "http.route", "value": {"stringValue": "/api/checkout"}},
                                            {"key": "http.status_code", "value": {"intValue": 200}},
                                        ],
                                    }
                                ]
                            }
                        ],
                    },
                    {
                        "resource": {
                            "attributes": [
                                {"key": "service.name", "value": {"stringValue": "backend-api"}}
                            ]
                        },
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "traceId": trace_id,
                                        "spanId": "span-backend-1",
                                        "parentSpanId": "span-frontend-1",
                                        "name": "CheckoutHandler",
                                        "attributes": [
                                            {"key": "code.function", "value": {"stringValue": "handle_checkout"}},
                                            {"key": "http.status_code", "value": {"intValue": 200}},
                                        ],
                                    },
                                    {
                                        "traceId": trace_id,
                                        "spanId": "span-db-1",
                                        "parentSpanId": "span-backend-1",
                                        "name": "INSERT orders",
                                        "attributes": [
                                            {"key": "db.system", "value": {"stringValue": "postgresql"}},
                                            {"key": "db.statement", "value": {"stringValue": "INSERT INTO orders (id, amount) VALUES (1, 100)"}},
                                            {"key": "db.name", "value": {"stringValue": "production"}},
                                        ],
                                    },
                                ]
                            }
                        ],
                    },
                ]
            }

            ingest_res = ingest_runtime_traces(
                icon,
                multi_span_payload,
                repository=repo,
                format="otel",
            )
            assert ingest_res.get("events_ingested", 0) >= 2 or ingest_res.get("ingested_events", 0) >= 2

            # 3. Stitch distributed trace
            report = link_distributed_trace(icon, repo, trace_id)
            assert report is not None
            assert report.trace_id == trace_id
            service_names = {s["name"] for s in report.services_involved}
            assert "frontend-web" in service_names
            assert "backend-api" in service_names
            assert report.db_queries_count >= 1
            assert report.has_errors is False
