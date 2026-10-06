"""Repository scanner and reconciliation engine for asynchronous message queues and tasks.

Epistemic Invariant:
  Static topic matching within the same repository produces STATIC_QUEUE_LINKED edges.
  It NEVER claims to be runtime proof (OTEL_DISTRIBUTED_VERIFIED).
  The graph structure maintains distinct entities:
    Producer -> PRODUCES_TO_QUEUE -> Queue -> CONSUMES_FROM_QUEUE -> Consumer
"""
from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path

from codegraph.async_queue.detectors import run_all_detectors
from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncProducerRecord,
    AsyncQueueEntity,
    AsyncQueueEvidenceClass,
)
from codegraph.indexing.models import normalize_module

ASYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS async_queues (
    queue_id             TEXT PRIMARY KEY,
    system               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    service              TEXT NOT NULL DEFAULT '',
    environment          TEXT NOT NULL DEFAULT '',
    is_dlq               INTEGER NOT NULL DEFAULT 0,
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS async_producers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id             TEXT NOT NULL,
    system               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    caller_canonical_id  TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    call_snippet         TEXT NOT NULL DEFAULT '',
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(queue_id) REFERENCES async_queues(queue_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS async_consumers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id             TEXT NOT NULL,
    system               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    handler_canonical_id TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    handler_snippet      TEXT NOT NULL DEFAULT '',
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(queue_id) REFERENCES async_queues(queue_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS async_links (
    link_id              TEXT PRIMARY KEY,
    queue_id             TEXT NOT NULL,
    system               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    producer_id          TEXT NOT NULL,
    producer_file        TEXT NOT NULL,
    producer_line        INTEGER NOT NULL,
    consumer_id          TEXT NOT NULL,
    consumer_file        TEXT NOT NULL,
    consumer_line        INTEGER NOT NULL,
    evidence_class       TEXT NOT NULL DEFAULT 'STATIC_QUEUE_LINKED',
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    trace_count          INTEGER NOT NULL DEFAULT 1,
    avg_latency_ms       REAL NOT NULL DEFAULT 0.0,
    p50_ms               REAL NOT NULL DEFAULT 0.0,
    p95_ms               REAL NOT NULL DEFAULT 0.0,
    p99_ms               REAL NOT NULL DEFAULT 0.0,
    error_count          INTEGER NOT NULL DEFAULT 0,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(queue_id) REFERENCES async_queues(queue_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_async_producers_queue ON async_producers(queue_id);
CREATE INDEX IF NOT EXISTS idx_async_producers_caller ON async_producers(caller_canonical_id);
CREATE INDEX IF NOT EXISTS idx_async_consumers_queue ON async_consumers(queue_id);
CREATE INDEX IF NOT EXISTS idx_async_consumers_handler ON async_consumers(handler_canonical_id);
CREATE INDEX IF NOT EXISTS idx_async_links_queue ON async_links(queue_id);
CREATE INDEX IF NOT EXISTS idx_async_links_producer ON async_links(producer_id);
CREATE INDEX IF NOT EXISTS idx_async_links_consumer ON async_links(consumer_id);
"""


def ensure_async_tables(con: sqlite3.Connection) -> None:
    """Ensure async queue storage tables and indexes exist."""
    con.executescript(ASYNC_SCHEMA)


def scan_file_for_async(
    file_path: Path,
    repo_root: Path,
) -> tuple[list[AsyncProducerRecord], list[AsyncConsumerRecord]]:
    """Scan a single Python file for async messaging producers and consumers."""
    rel_path = file_path.relative_to(repo_root).as_posix()
    module_name = normalize_module(rel_path, "python")
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=rel_path)
    except Exception:
        return [], []

    return run_all_detectors(tree, content, rel_path, module_name)


class AsyncQueueScanner:
    """Repository-level scanner and graph reconciler for async queues."""

    def __init__(self, repository: Path) -> None:
        self.repository = repository.resolve()

    def scan_repository(
        self,
        con: sqlite3.Connection,
    ) -> dict[str, int]:
        """Scan all repository Python files, persist entities, and link matching queues."""
        ensure_async_tables(con)

        producers: list[AsyncProducerRecord] = []
        consumers: list[AsyncConsumerRecord] = []

        # Find all Python source files
        for py_file in self.repository.rglob("*.py"):
            if ".git" in py_file.parts or "__pycache__" in py_file.parts or ".codegraph" in py_file.parts:
                continue
            prods, cons = scan_file_for_async(py_file, self.repository)
            producers.extend(prods)
            consumers.extend(cons)

        # Clear existing static async tables
        con.execute("DELETE FROM async_links WHERE evidence_class='STATIC_QUEUE_LINKED'")
        con.execute("DELETE FROM async_consumers")
        con.execute("DELETE FROM async_producers")
        con.execute("DELETE FROM async_queues")
        con.execute("DELETE FROM graph_edges WHERE relationship IN ('PRODUCES_TO_QUEUE', 'CONSUMES_FROM_QUEUE', 'STATIC_QUEUE_LINKED')")

        # Collect distinct queues
        queues_by_id: dict[str, AsyncQueueEntity] = {}
        for p in producers:
            if p.queue_id not in queues_by_id:
                queues_by_id[p.queue_id] = AsyncQueueEntity(
                    queue_id=p.queue_id,
                    system=p.system,
                    destination=p.destination,
                )
        for c in consumers:
            if c.queue_id not in queues_by_id:
                queues_by_id[c.queue_id] = AsyncQueueEntity(
                    queue_id=c.queue_id,
                    system=c.system,
                    destination=c.destination,
                )

        # Insert async_queues
        for q in queues_by_id.values():
            con.execute(
                "INSERT INTO async_queues (queue_id, system, destination, service, environment, is_dlq) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (q.queue_id, str(q.system), q.destination, q.service, q.environment, 1 if q.is_dead_letter_queue else 0),
            )

        # Insert async_producers
        for p in producers:
            con.execute(
                "INSERT INTO async_producers (queue_id, system, destination, caller_canonical_id, file_path, line, call_snippet, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p.queue_id, str(p.system), p.destination, p.caller_canonical_id, p.file_path, p.line, p.call_snippet, p.confidence),
            )

        # Insert async_consumers
        for c in consumers:
            con.execute(
                "INSERT INTO async_consumers (queue_id, system, destination, handler_canonical_id, file_path, line, handler_snippet, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (c.queue_id, str(c.system), c.destination, c.handler_canonical_id, c.file_path, c.line, c.handler_snippet, c.confidence),
            )

        # Reconcile STATIC_QUEUE_LINKED edges (Same repository topic/queue matching)
        # Groups: fan-out (1 producer -> N consumers) and fan-in (M producers -> 1 consumer)
        prods_by_queue: dict[str, list[AsyncProducerRecord]] = {}
        for p in producers:
            prods_by_queue.setdefault(p.queue_id, []).append(p)

        cons_by_queue: dict[str, list[AsyncConsumerRecord]] = {}
        for c in consumers:
            cons_by_queue.setdefault(c.queue_id, []).append(c)

        links_count = 0
        graph_edges_to_insert: list[tuple[str, str, str, str, str, int, int, str, str]] = []

        for q_id, q_prods in prods_by_queue.items():
            q_cons = cons_by_queue.get(q_id, [])

            # 1. PRODUCES_TO_QUEUE edges: Producer -> Queue
            for p in q_prods:
                graph_edges_to_insert.append((
                    p.caller_canonical_id,
                    q_id,
                    "PRODUCES_TO_QUEUE",
                    "HIGH",
                    p.file_path,
                    p.line,
                    p.line,
                    p.call_snippet,
                    "STATIC_QUEUE_LINKED",
                ))

            # 2. CONSUMES_FROM_QUEUE edges: Queue -> Consumer
            for c in q_cons:
                graph_edges_to_insert.append((
                    q_id,
                    c.handler_canonical_id,
                    "CONSUMES_FROM_QUEUE",
                    "HIGH",
                    c.file_path,
                    c.line,
                    c.line,
                    c.handler_snippet,
                    "STATIC_QUEUE_LINKED",
                ))

            # 3. Direct bridge links: Producer -> Consumer across queue boundary
            for p in q_prods:
                for c in q_cons:
                    link_seed = f"{p.caller_canonical_id}:{q_id}:{c.handler_canonical_id}:{p.file_path}:{p.line}"
                    link_id = hashlib.sha256(link_seed.encode("utf-8")).hexdigest()[:16]

                    con.execute(
                        "INSERT OR REPLACE INTO async_links ("
                        "link_id, queue_id, system, destination, producer_id, producer_file, producer_line, "
                        "consumer_id, consumer_file, consumer_line, evidence_class, confidence"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            link_id,
                            q_id,
                            str(p.system),
                            p.destination,
                            p.caller_canonical_id,
                            p.file_path,
                            p.line,
                            c.handler_canonical_id,
                            c.file_path,
                            c.line,
                            AsyncQueueEvidenceClass.STATIC_QUEUE_LINKED.value,
                            "HIGH",
                        ),
                    )
                    links_count += 1

                    # Direct STATIC_QUEUE_LINKED edge in graph_edges
                    graph_edges_to_insert.append((
                        p.caller_canonical_id,
                        c.handler_canonical_id,
                        "STATIC_QUEUE_LINKED",
                        "HIGH",
                        p.file_path,
                        p.line,
                        c.line,
                        f"Matched queue '{q_id}' ({p.system})",
                        "STATIC_QUEUE_LINKED",
                    ))

        # Insert graph edges with ON CONFLICT IGNORE
        if graph_edges_to_insert:
            con.executemany(
                "INSERT OR IGNORE INTO graph_edges ("
                "source, target, relationship, confidence, file, start_line, end_line, evidence, evidence_class"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                graph_edges_to_insert,
            )

        con.commit()

        return {
            "queues": len(queues_by_id),
            "producers": len(producers),
            "consumers": len(consumers),
            "links": links_count,
        }
