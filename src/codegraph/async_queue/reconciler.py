"""Static-Runtime OpenTelemetry Reconciliation Engine.

Epistemic Invariants:
1. Do not replace static edges with runtime edges: Add runtime evidence to them.
2. If static topic match exists, upgrade evidence to OTEL_DISTRIBUTED_VERIFIED.
3. If consumer is external (e.g. Repo B), record as RUNTIME_ONLY_OBSERVED with service identity:
     service = <c.service_name>
     operation = <c.name>
     repository = UNKNOWN
   Do not invent a local AST symbol.
4. Bounded aggregation: Bounded sliding reservoir of at most 100 recent durations per link.
   Nearest-rank percentile estimation method with documented precision.
5. Idempotent: Re-ingesting previously observed spans is a no-op and never duplicates counts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from codegraph.async_queue.otel_models import (
    OTelEvidenceStatus,
    OTelSpanRecord,
    TraceReconciliationResult,
)

OTEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS otel_ingested_spans (
    composite_id       TEXT PRIMARY KEY,
    trace_id           TEXT NOT NULL,
    span_id            TEXT NOT NULL,
    parent_span_id     TEXT NOT NULL DEFAULT '',
    service_name       TEXT NOT NULL DEFAULT '',
    name               TEXT NOT NULL DEFAULT '',
    kind               TEXT NOT NULL DEFAULT '',
    duration_ms        REAL NOT NULL DEFAULT 0.0,
    status_code        TEXT NOT NULL DEFAULT 'OK',
    messaging_system   TEXT NOT NULL DEFAULT '',
    messaging_dest     TEXT NOT NULL DEFAULT '',
    messaging_op       TEXT NOT NULL DEFAULT '',
    corr_id_hash       TEXT NOT NULL DEFAULT '',
    ingested_at        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otel_spans_trace ON otel_ingested_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_dest ON otel_ingested_spans(messaging_dest);
CREATE INDEX IF NOT EXISTS idx_otel_spans_corr ON otel_ingested_spans(corr_id_hash);
"""


def ensure_otel_tables(con: sqlite3.Connection) -> None:
    """Ensure otel storage tables exist."""
    con.executescript(OTEL_SCHEMA)


def compute_percentiles(samples: list[float]) -> tuple[float, float, float]:
    """Compute (p50, p95, p99) using the nearest-rank method on a bounded reservoir (N <= 100)."""
    if not samples:
        return 0.0, 0.0, 0.0
    sorted_s = sorted(samples)
    n = len(sorted_s)

    def _rank(p: float) -> float:
        idx = max(0, min(int(round(p * n - 0.5)), n - 1))
        return round(sorted_s[idx], 2)

    return _rank(0.50), _rank(0.95), _rank(0.99)


class OTelTraceReconciler:
    """Idempotent reconciliation engine for OpenTelemetry traces and CodeGraph async queues."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.row_factory = sqlite3.Row
        ensure_otel_tables(self.con)

    def reconcile_spans(
        self,
        spans: list[OTelSpanRecord],
    ) -> TraceReconciliationResult:
        """Idempotently ingest spans, pair publishers and consumers, and reconcile with graph."""
        if not spans:
            return TraceReconciliationResult(
                spans_ingested=0,
                spans_deduplicated=0,
                links_upgraded=0,
                links_created_runtime_only=0,
                conflicts_detected=0,
                details=[],
            )

        now_ts = int(time.time())

        # 1. Filter out previously ingested spans (idempotence guard)
        existing_keys = {
            str(r[0])
            for r in self.con.execute(
                f"SELECT composite_id FROM otel_ingested_spans WHERE composite_id IN ({','.join(['?']*len(spans))})",
                [s.composite_id for s in spans],
            ).fetchall()
        }

        fresh_spans = [s for s in spans if s.composite_id not in existing_keys]
        spans_deduplicated = len(spans) - len(fresh_spans)

        if not fresh_spans:
            return TraceReconciliationResult(
                spans_ingested=0,
                spans_deduplicated=spans_deduplicated,
                links_upgraded=0,
                links_created_runtime_only=0,
                conflicts_detected=0,
                details=[{"message": "All spans were previously ingested; zero new updates."}],
            )

        # 2. Insert fresh spans into otel_ingested_spans
        insert_rows = [
            (
                s.composite_id,
                s.trace_id,
                s.span_id,
                s.parent_span_id,
                s.service_name,
                s.name,
                s.kind,
                s.duration_ms,
                s.status_code,
                s.messaging_system,
                s.messaging_destination,
                s.messaging_operation,
                s.correlation_id_hash,
                now_ts,
            )
            for s in fresh_spans
        ]
        self.con.executemany(
            """
            INSERT OR IGNORE INTO otel_ingested_spans (
                composite_id, trace_id, span_id, parent_span_id, service_name, name, kind,
                duration_ms, status_code, messaging_system, messaging_dest, messaging_op,
                corr_id_hash, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )

        # 3. Categorize into producers and consumers
        producers: list[OTelSpanRecord] = []
        consumers: list[OTelSpanRecord] = []

        for s in fresh_spans:
            if s.messaging_operation == "publish" or s.kind == "PRODUCER":
                producers.append(s)
            elif s.messaging_operation in ("process", "receive") or s.kind == "CONSUMER":
                consumers.append(s)

        # 4. Correlate producers to consumers
        # Matching index:
        # Key: (trace_id, destination) OR parent_span_id OR correlation_id_hash
        paired_links: list[tuple[OTelSpanRecord, OTelSpanRecord, float]] = []

        for p in producers:
            for c in consumers:
                matched = False
                # Match A: Parent-child span link
                if c.parent_span_id and c.parent_span_id == p.span_id:
                    matched = True
                # Match B: Span links
                elif any(l_trace == p.trace_id and l_span == p.span_id for l_trace, l_span in c.links):
                    matched = True
                # Match C: Same trace ID + same destination
                elif (
                    p.trace_id == c.trace_id
                    and p.messaging_destination
                    and p.messaging_destination == c.messaging_destination
                ):
                    matched = True
                # Match D: Same correlation ID hash
                elif p.correlation_id_hash and p.correlation_id_hash == c.correlation_id_hash:
                    matched = True

                if matched:
                    # Transit/execution latency:
                    if c.start_time_unix_nano > 0 and p.start_time_unix_nano > 0:
                        lat = max(0.0, (c.start_time_unix_nano - p.start_time_unix_nano) / 1_000_000.0)
                    else:
                        lat = max(0.0, p.duration_ms + c.duration_ms)
                    paired_links.append((p, c, lat))

        upgraded_count = 0
        runtime_only_count = 0
        conflicts_count = 0
        details: list[dict[str, Any]] = []

        # 5. Reconcile pairs against static async_links
        for p, c, lat_ms in paired_links:
            dest = p.messaging_destination or c.messaging_destination
            sys_name = p.messaging_system or c.messaging_system or "generic"

            # Check if static link exists for destination
            static_rows = self.con.execute(
                "SELECT * FROM async_links WHERE destination = ?",
                (dest,),
            ).fetchall()

            if static_rows:
                # Upgrade existing static links with runtime empirical evidence
                for row in static_rows:
                    l_id = str(row["link_id"])
                    meta_raw = str(row["metadata_json"] or "{}")
                    try:
                        meta = json.loads(meta_raw)
                    except Exception:
                        meta = {}

                    reservoir: list[float] = meta.get("durations_reservoir", [])
                    reservoir.append(lat_ms)
                    if len(reservoir) > 100:
                        reservoir = reservoir[-100:]  # Bounded reservoir

                    p50, p95, p99 = compute_percentiles(reservoir)
                    new_trace_count = int(row["trace_count"] or 0) + 1
                    err_inc = 1 if (p.status_code == "ERROR" or c.status_code == "ERROR") else 0
                    new_error_count = int(row["error_count"] or 0) + err_inc
                    avg_lat = round(sum(reservoir) / len(reservoir), 2)

                    meta["durations_reservoir"] = reservoir
                    meta["last_observed_trace_id"] = p.trace_id
                    meta["producer_service"] = p.service_name
                    meta["consumer_service"] = c.service_name

                    self.con.execute(
                        """
                        UPDATE async_links SET
                            evidence_class = ?,
                            trace_count = ?,
                            avg_latency_ms = ?,
                            p50_ms = ?,
                            p95_ms = ?,
                            p99_ms = ?,
                            error_count = ?,
                            metadata_json = ?
                        WHERE link_id = ?
                        """,
                        (
                            OTelEvidenceStatus.OTEL_DISTRIBUTED_VERIFIED.value,
                            new_trace_count,
                            avg_lat,
                            p50,
                            p95,
                            p99,
                            new_error_count,
                            json.dumps(meta),
                            l_id,
                        ),
                    )

                    # Update graph_edges to reflect OTEL_DISTRIBUTED_VERIFIED
                    self.con.execute(
                        """
                        UPDATE graph_edges SET
                            evidence_class = 'OTEL_DISTRIBUTED_VERIFIED',
                            evidence = ?
                        WHERE source = ? AND target = ? AND relationship = 'STATIC_QUEUE_LINKED'
                        """,
                        (
                            f"Verified via OpenTelemetry trace {p.trace_id} (p50={p50}ms, p95={p95}ms)",
                            str(row["producer_id"]),
                            str(row["consumer_id"]),
                        ),
                    )
                    upgraded_count += 1
                    details.append({
                        "link_id": l_id,
                        "destination": dest,
                        "action": "UPGRADED_TO_OTEL_DISTRIBUTED_VERIFIED",
                        "p50_ms": p50,
                        "p95_ms": p95,
                        "p99_ms": p99,
                        "trace_count": new_trace_count,
                    })
            else:
                # No static link in repository index (e.g. cross-repository worker in Repo B)
                # Invariant: Record as RUNTIME_ONLY_OBSERVED with service identity. Do NOT invent a local symbol.
                seed = f"rt:{p.service_name}:{dest}:{c.service_name}:{c.name}"
                link_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
                q_id = f"{sys_name}:{dest}"

                meta = {
                    "service": c.service_name or "external_worker",
                    "operation": c.name or "process",
                    "repository": "UNKNOWN",
                    "durations_reservoir": [lat_ms],
                    "producer_service": p.service_name,
                    "last_observed_trace_id": p.trace_id,
                }
                p50, p95, p99 = lat_ms, lat_ms, lat_ms

                # Ensure queue exists in async_queues
                self.con.execute(
                    """
                    INSERT OR IGNORE INTO async_queues (queue_id, system, destination, service)
                    VALUES (?, ?, ?, ?)
                    """,
                    (q_id, sys_name, dest, p.service_name),
                )

                # Check if this repository has a local producer for destination
                prod_record = self.con.execute(
                    "SELECT caller_canonical_id, file_path, line FROM async_producers WHERE destination = ? LIMIT 1",
                    (dest,),
                ).fetchone()

                if prod_record:
                    producer_id = str(prod_record["caller_canonical_id"])
                    prod_file = str(prod_record["file_path"])
                    prod_line = int(prod_record["line"])
                else:
                    producer_id = p.name or f"{p.service_name}:publisher"
                    prod_file = ""
                    prod_line = 0

                consumer_id = f"external:{c.service_name or 'unknown'}:{c.name or 'handler'}"

                self.con.execute(
                    """
                    INSERT INTO async_links (
                        link_id, queue_id, system, destination,
                        producer_id, producer_file, producer_line,
                        consumer_id, consumer_file, consumer_line,
                        evidence_class, confidence, trace_count,
                        avg_latency_ms, p50_ms, p95_ms, p99_ms,
                        error_count, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(link_id) DO UPDATE SET
                        trace_count = trace_count + 1,
                        avg_latency_ms = excluded.avg_latency_ms,
                        p50_ms = excluded.p50_ms,
                        p95_ms = excluded.p95_ms,
                        p99_ms = excluded.p99_ms
                    """,
                    (
                        link_id,
                        q_id,
                        sys_name,
                        dest,
                        producer_id,
                        prod_file,
                        prod_line,
                        consumer_id,
                        "",
                        0,
                        OTelEvidenceStatus.RUNTIME_ONLY_OBSERVED.value,
                        "HIGH",
                        1,
                        lat_ms,
                        p50,
                        p95,
                        p99,
                        1 if (p.status_code == "ERROR" or c.status_code == "ERROR") else 0,
                        json.dumps(meta),
                    ),
                )

                # If local producer file exists, insert into graph_edges; otherwise insert into runtime_edges
                if prod_file:
                    self.con.execute(
                        """
                        INSERT OR IGNORE INTO graph_edges (
                            source, target, relationship, confidence, file,
                            start_line, end_line, evidence, evidence_class
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            producer_id,
                            consumer_id,
                            "OTEL_DISTRIBUTED_VERIFIED",
                            "HIGH",
                            prod_file,
                            prod_line,
                            prod_line,
                            f"Cross-service runtime link via {q_id} (service: {c.service_name})",
                            OTelEvidenceStatus.RUNTIME_ONLY_OBSERVED.value,
                        ),
                    )
                else:
                    edge_id = hashlib.sha256(f"{producer_id}:{consumer_id}:{q_id}".encode()).hexdigest()[:16]
                    self.con.execute(
                        """
                        INSERT OR IGNORE INTO runtime_edges (
                            edge_id, source, target, relationship, operation, evidence_class, observation_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            edge_id,
                            producer_id,
                            consumer_id,
                            "OTEL_DISTRIBUTED_VERIFIED",
                            dest,
                            OTelEvidenceStatus.RUNTIME_ONLY_OBSERVED.value,
                            1,
                        ),
                    )
                runtime_only_count += 1
                details.append({
                    "link_id": link_id,
                    "destination": dest,
                    "action": "CREATED_RUNTIME_ONLY_OBSERVED",
                    "consumer_service": c.service_name,
                    "consumer_operation": c.name,
                    "repository": "UNKNOWN",
                    "latency_ms": lat_ms,
                })

        self.con.commit()

        return TraceReconciliationResult(
            spans_ingested=len(fresh_spans),
            spans_deduplicated=spans_deduplicated,
            links_upgraded=upgraded_count,
            links_created_runtime_only=runtime_only_count,
            conflicts_detected=conflicts_count,
            details=details,
        )
