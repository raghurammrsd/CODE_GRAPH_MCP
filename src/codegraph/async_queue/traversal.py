"""Query and graph traversal engine for asynchronous message queues and tasks.

Epistemic Invariants:
1. Preserves distinct semantic relationships:
   - PRODUCES_TO_QUEUE
   - CONSUMES_FROM_QUEUE
   - STATIC_QUEUE_LINKED
   - OTEL_DISTRIBUTED_VERIFIED
2. Bridges entrypoint handlers -> producers -> queues -> consumer workers -> downstream DB/operations.
3. Fully deterministic ordering.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def list_async_queues(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all statically detected async queues, topics, and channels."""
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT q.queue_id, q.system, q.destination, q.service, q.environment, q.is_dlq,
                   COUNT(DISTINCT p.id) as producer_count,
                   COUNT(DISTINCT c.id) as consumer_count,
                   COUNT(DISTINCT l.link_id) as link_count
            FROM async_queues q
            LEFT JOIN async_producers p ON q.queue_id = p.queue_id
            LEFT JOIN async_consumers c ON q.queue_id = c.queue_id
            LEFT JOIN async_links l ON q.queue_id = l.queue_id
            GROUP BY q.queue_id
            ORDER BY q.queue_id ASC
            """
        ).fetchall()
        return [
            {
                "queue_id": str(r["queue_id"]),
                "system": str(r["system"]),
                "destination": str(r["destination"]),
                "service": str(r["service"]),
                "environment": str(r["environment"]),
                "is_dlq": bool(r["is_dlq"]),
                "producer_count": int(r["producer_count"]),
                "consumer_count": int(r["consumer_count"]),
                "link_count": int(r["link_count"]),
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def find_queue_producers(
    con: sqlite3.Connection,
    queue_or_topic: str,
) -> list[dict[str, Any]]:
    """Find all producer call sites for a given queue, topic, or destination."""
    con.row_factory = sqlite3.Row
    clean = queue_or_topic.strip()
    if not clean:
        return []

    try:
        rows = con.execute(
            """
            SELECT p.id, p.queue_id, p.system, p.destination, p.caller_canonical_id,
                   p.file_path, p.line, p.call_snippet, p.confidence, s.name as caller_name
            FROM async_producers p
            LEFT JOIN symbols s ON p.caller_canonical_id = s.canonical_id
            WHERE p.queue_id = ? OR p.destination = ? OR p.destination LIKE ?
            ORDER BY p.file_path ASC, p.line ASC
            """,
            (clean, clean, f"%{clean}%"),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "queue_id": str(r["queue_id"]),
                "system": str(r["system"]),
                "destination": str(r["destination"]),
                "caller_canonical_id": str(r["caller_canonical_id"]),
                "caller_name": str(r["caller_name"] or r["caller_canonical_id"]),
                "file_path": str(r["file_path"]),
                "line": int(r["line"]),
                "call_snippet": str(r["call_snippet"]),
                "confidence": str(r["confidence"]),
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def find_queue_consumers(
    con: sqlite3.Connection,
    queue_or_topic: str,
) -> list[dict[str, Any]]:
    """Find all consumer workers and handlers subscribed to a given queue or topic."""
    con.row_factory = sqlite3.Row
    clean = queue_or_topic.strip()
    if not clean:
        return []

    try:
        rows = con.execute(
            """
            SELECT c.id, c.queue_id, c.system, c.destination, c.handler_canonical_id,
                   c.file_path, c.line, c.handler_snippet, c.confidence, s.name as handler_name
            FROM async_consumers c
            LEFT JOIN symbols s ON c.handler_canonical_id = s.canonical_id
            WHERE c.queue_id = ? OR c.destination = ? OR c.destination LIKE ?
            ORDER BY c.file_path ASC, c.line ASC
            """,
            (clean, clean, f"%{clean}%"),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "queue_id": str(r["queue_id"]),
                "system": str(r["system"]),
                "destination": str(r["destination"]),
                "handler_canonical_id": str(r["handler_canonical_id"]),
                "handler_name": str(r["handler_name"] or r["handler_canonical_id"]),
                "file_path": str(r["file_path"]),
                "line": int(r["line"]),
                "handler_snippet": str(r["handler_snippet"]),
                "confidence": str(r["confidence"]),
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def trace_async_flow(
    con: sqlite3.Connection,
    entrypoint: str,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Trace cross-process asynchronous execution flow starting from an entrypoint.

    Entrypoint can be:
    - An HTTP endpoint or service function that publishes to a queue
    - A queue or topic name directly
    - A background consumer worker function

    Returns deterministic flow steps across the async boundary, including
    downstream database queries and callees invoked by consumer workers.
    """
    con.row_factory = sqlite3.Row
    clean = entrypoint.strip()
    if not clean:
        return {
            "status": "error",
            "message": "Entrypoint cannot be empty.",
            "entrypoint": entrypoint,
            "steps": [],
        }

    # 1. Check if entrypoint is a queue or topic directly
    queue_matches = con.execute(
        "SELECT queue_id, system, destination FROM async_queues WHERE queue_id=? OR destination=?",
        (clean, clean),
    ).fetchall()

    producers: list[dict[str, Any]] = []
    consumers: list[dict[str, Any]] = []
    flow_steps: list[dict[str, Any]] = []
    downstream_ops: list[dict[str, Any]] = []

    if queue_matches:
        for q in queue_matches:
            q_id = str(q["queue_id"])
            q_prods = find_queue_producers(con, q_id)
            q_cons = find_queue_consumers(con, q_id)
            producers.extend(q_prods)
            consumers.extend(q_cons)

            for p in q_prods:
                flow_steps.append({
                    "step": len(flow_steps) + 1,
                    "source": p["caller_canonical_id"],
                    "target": q_id,
                    "relationship": "PRODUCES_TO_QUEUE",
                    "system": p["system"],
                    "evidence_class": "STATIC_QUEUE_LINKED",
                    "confidence": p["confidence"],
                    "file": p["file_path"],
                    "line": p["line"],
                    "snippet": p["call_snippet"],
                })

            for c in q_cons:
                flow_steps.append({
                    "step": len(flow_steps) + 1,
                    "source": q_id,
                    "target": c["handler_canonical_id"],
                    "relationship": "CONSUMES_FROM_QUEUE",
                    "system": c["system"],
                    "evidence_class": "STATIC_QUEUE_LINKED",
                    "confidence": c["confidence"],
                    "file": c["file_path"],
                    "line": c["line"],
                    "snippet": c["handler_snippet"],
                })
    else:
        # 2. Check if entrypoint is a producer symbol or calls a producer
        # Look up directly matching producers
        direct_prods = con.execute(
            """
            SELECT p.id, p.queue_id, p.system, p.destination, p.caller_canonical_id,
                   p.file_path, p.line, p.call_snippet, p.confidence
            FROM async_producers p
            WHERE p.caller_canonical_id = ? OR p.caller_canonical_id LIKE ?
            ORDER BY p.file_path ASC, p.line ASC
            """,
            (clean, f"%{clean}%"),
        ).fetchall()

        # If none direct, check if entrypoint calls a producer function (e.g. controller calling service)
        if not direct_prods:
            callee_prods = con.execute(
                """
                SELECT p.id, p.queue_id, p.system, p.destination, p.caller_canonical_id,
                       p.file_path, p.line, p.call_snippet, p.confidence, ge.source as entry_source
                FROM graph_edges ge
                JOIN async_producers p ON ge.target = p.caller_canonical_id
                WHERE (ge.source = ? OR ge.source LIKE ?) AND ge.relationship = 'CALLS'
                ORDER BY p.file_path ASC, p.line ASC
                """,
                (clean, f"%{clean}%"),
            ).fetchall()
            for cp in callee_prods:
                flow_steps.append({
                    "step": len(flow_steps) + 1,
                    "source": str(cp["entry_source"]),
                    "target": str(cp["caller_canonical_id"]),
                    "relationship": "CALLS",
                    "evidence_class": "AST_VERIFIED",
                    "confidence": "HIGH",
                    "file": str(cp["file_path"]),
                    "line": int(cp["line"]),
                    "snippet": "",
                })
                direct_prods.append(cp)

        for p in direct_prods:
            q_id = str(p["queue_id"])
            producers.append({
                "queue_id": q_id,
                "system": str(p["system"]),
                "destination": str(p["destination"]),
                "caller_canonical_id": str(p["caller_canonical_id"]),
                "file_path": str(p["file_path"]),
                "line": int(p["line"]),
                "call_snippet": str(p["call_snippet"]),
                "confidence": str(p["confidence"]),
            })
            flow_steps.append({
                "step": len(flow_steps) + 1,
                "source": str(p["caller_canonical_id"]),
                "target": q_id,
                "relationship": "PRODUCES_TO_QUEUE",
                "system": str(p["system"]),
                "evidence_class": "STATIC_QUEUE_LINKED",
                "confidence": str(p["confidence"]),
                "file": str(p["file_path"]),
                "line": int(p["line"]),
                "snippet": str(p["call_snippet"]),
            })

            # Find matching static consumers for this queue
            q_cons = find_queue_consumers(con, q_id)
            consumers.extend(q_cons)

            # Look up runtime links to augment evidence and latency metrics
            try:
                rt_links = con.execute(
                    "SELECT * FROM async_links WHERE queue_id = ? OR destination = ?",
                    (q_id, str(p["destination"])),
                ).fetchall()
            except sqlite3.OperationalError:
                rt_links = []

            links_by_consumer = {str(rk["consumer_id"]): rk for rk in rt_links}

            for c in q_cons:
                matched_link = links_by_consumer.get(c["handler_canonical_id"])
                ev_class = str(matched_link["evidence_class"]) if matched_link else "STATIC_QUEUE_LINKED"
                step_dict: dict[str, Any] = {
                    "step": len(flow_steps) + 1,
                    "source": q_id,
                    "target": c["handler_canonical_id"],
                    "relationship": "CONSUMES_FROM_QUEUE",
                    "system": c["system"],
                    "evidence_class": ev_class,
                    "confidence": c["confidence"],
                    "file": c["file_path"],
                    "line": c["line"],
                    "snippet": c["handler_snippet"],
                }
                if matched_link and ev_class == "OTEL_DISTRIBUTED_VERIFIED":
                    step_dict["latency_p50_ms"] = float(matched_link["p50_ms"])
                    step_dict["latency_p95_ms"] = float(matched_link["p95_ms"])
                    step_dict["trace_count"] = int(matched_link["trace_count"])
                flow_steps.append(step_dict)

            # Include cross-repository / external runtime consumers
            for rk in rt_links:
                c_id = str(rk["consumer_id"])
                if c_id.startswith("external:"):
                    consumers.append({
                        "queue_id": q_id,
                        "system": str(rk["system"]),
                        "destination": str(rk["destination"]),
                        "handler_canonical_id": c_id,
                        "file_path": "",
                        "line": 0,
                        "handler_snippet": f"External consumer ({rk['system']})",
                        "confidence": "HIGH",
                    })
                    flow_steps.append({
                        "step": len(flow_steps) + 1,
                        "source": q_id,
                        "target": c_id,
                        "relationship": "CONSUMES_FROM_QUEUE",
                        "system": str(rk["system"]),
                        "evidence_class": str(rk["evidence_class"]),
                        "confidence": "HIGH",
                        "file": "",
                        "line": 0,
                        "snippet": f"Observed via OTel (p50={rk['p50_ms']}ms, p95={rk['p95_ms']}ms)",
                        "latency_p50_ms": float(rk["p50_ms"]),
                        "latency_p95_ms": float(rk["p95_ms"]),
                        "trace_count": int(rk["trace_count"]),
                    })

        # 3. If still no producers found, check if entrypoint is a consumer worker handler
        if not producers:
            direct_cons = con.execute(
                """
                SELECT c.id, c.queue_id, c.system, c.destination, c.handler_canonical_id,
                       c.file_path, c.line, c.handler_snippet, c.confidence
                FROM async_consumers c
                WHERE c.handler_canonical_id = ? OR c.handler_canonical_id LIKE ?
                ORDER BY c.file_path ASC, c.line ASC
                """,
                (clean, f"%{clean}%"),
            ).fetchall()

            for c in direct_cons:
                q_id = str(c["queue_id"])
                consumers.append({
                    "queue_id": q_id,
                    "system": str(c["system"]),
                    "destination": str(c["destination"]),
                    "handler_canonical_id": str(c["handler_canonical_id"]),
                    "file_path": str(c["file_path"]),
                    "line": int(c["line"]),
                    "handler_snippet": str(c["handler_snippet"]),
                    "confidence": str(c["confidence"]),
                })
                # Find upstream producers
                q_prods = find_queue_producers(con, q_id)
                producers.extend(q_prods)
                for p in q_prods:
                    flow_steps.append({
                        "step": len(flow_steps) + 1,
                        "source": p["caller_canonical_id"],
                        "target": q_id,
                        "relationship": "PRODUCES_TO_QUEUE",
                        "system": p["system"],
                        "evidence_class": "STATIC_QUEUE_LINKED",
                        "confidence": p["confidence"],
                        "file": p["file_path"],
                        "line": p["line"],
                        "snippet": p["call_snippet"],
                    })
                flow_steps.append({
                    "step": len(flow_steps) + 1,
                    "source": q_id,
                    "target": str(c["handler_canonical_id"]),
                    "relationship": "CONSUMES_FROM_QUEUE",
                    "system": str(c["system"]),
                    "evidence_class": "STATIC_QUEUE_LINKED",
                    "confidence": str(c["confidence"]),
                    "file": str(c["file_path"]),
                    "line": int(c["line"]),
                    "snippet": str(c["handler_snippet"]),
                })

    # For each consumer handler discovered, find downstream database queries and operations
    visited_handlers: set[str] = set()
    for c in consumers:
        h_id = c["handler_canonical_id"]
        if h_id in visited_handlers:
            continue
        visited_handlers.add(h_id)

        try:
            db_rows = con.execute(
                """
                SELECT query_id, operation, relationship, table_name, file_path, start_line, evidence
                FROM db_queries
                WHERE caller_symbol_id = ?
                ORDER BY file_path ASC, start_line ASC
                """,
                (h_id,),
            ).fetchall()
            for db in db_rows:
                op_dict = {
                    "consumer": h_id,
                    "operation": str(db["operation"]),
                    "relationship": str(db["relationship"]),
                    "table_name": str(db["table_name"]),
                    "file": str(db["file_path"]),
                    "line": int(db["start_line"]),
                    "evidence": str(db["evidence"]),
                }
                downstream_ops.append(op_dict)
                flow_steps.append({
                    "step": len(flow_steps) + 1,
                    "source": h_id,
                    "target": f"table:{db['table_name']}",
                    "relationship": str(db["relationship"]),
                    "evidence_class": "AST_VERIFIED",
                    "confidence": "HIGH",
                    "file": str(db["file_path"]),
                    "line": int(db["start_line"]),
                    "snippet": f"{db['operation']} on {db['table_name']}",
                })
        except sqlite3.OperationalError:
            pass

    return {
        "status": "ok" if flow_steps else "not_found",
        "entrypoint": clean,
        "step_count": len(flow_steps),
        "producers_count": len(producers),
        "consumers_count": len(consumers),
        "downstream_ops_count": len(downstream_ops),
        "producers": producers,
        "consumers": consumers,
        "downstream_ops": downstream_ops,
        "flow_steps": flow_steps,
    }
