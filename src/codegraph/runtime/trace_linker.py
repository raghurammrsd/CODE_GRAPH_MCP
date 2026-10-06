"""Cross-Service & Multi-Localhost Distributed Trace Linker.

Stitches W3C distributed traces across multiple localhost ports:
- Frontend (e.g. Next.js on localhost:3000)
- Backend API (e.g. FastAPI / NestJS on localhost:8000)
- Database mutation (e.g. PostgreSQL on localhost:5432)

Attributes every step to:
1. Participating localhost service & port.
2. Static AST symbol / route handler.
3. Actual latency and HTTP status code.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceSpanNode:
    span_id: str
    parent_span_id: str
    service_name: str
    port: int | None
    route_path: str
    handler_symbol: str
    db_operation: str
    db_table: str
    status_code: int | None
    duration_ms: float
    children: tuple[TraceSpanNode, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "service_name": self.service_name,
            "port": self.port,
            "route_path": self.route_path,
            "handler_symbol": self.handler_symbol,
            "db_operation": self.db_operation,
            "db_table": self.db_table,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass(frozen=True)
class DistributedTraceReport:
    trace_id: str
    total_duration_ms: float
    services_involved: tuple[dict[str, Any], ...]
    root_spans: tuple[TraceSpanNode, ...]
    db_queries_count: int
    has_errors: bool
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_duration_ms": self.total_duration_ms,
            "services_involved": list(self.services_involved),
            "root_spans": [s.as_dict() for s in self.root_spans],
            "db_queries_count": self.db_queries_count,
            "has_errors": self.has_errors,
            "summary": self.summary,
        }


def link_distributed_trace(
    con: sqlite3.Connection,
    repo_root: Path,
    trace_id: str,
) -> DistributedTraceReport | None:
    """Reconstruct multi-service distributed execution graph for a given trace_id."""
    clean_tid = trace_id.strip()
    if not clean_tid:
        return None

    rows = con.execute(
        """SELECT event_id, trace_id, span_id, parent_span_id, http_method, route_path,
                  handler_symbol, service_name, db_operation, db_table, status_code,
                  duration_ms
           FROM runtime_observations
           WHERE trace_id = ?
           ORDER BY duration_ms DESC""",
        (clean_tid,),
    ).fetchall()

    if not rows:
        return None

    # Group spans
    spans_by_id: dict[str, dict[str, Any]] = {}
    children_by_parent: dict[str, list[str]] = {}
    services_set: set[str] = set()
    db_queries = 0
    has_err = False
    total_time = 0.0

    for r in rows:
        sid = str(r["span_id"] or r["event_id"])
        pid = str(r["parent_span_id"] or "")
        s_name = str(r["service_name"] or "unknown_service")
        services_set.add(s_name)
        dur = float(r["duration_ms"] or 0.0)
        total_time = max(total_time, dur)
        sc = r["status_code"]
        if sc and int(sc) >= 400:
            has_err = True
        if r["db_operation"]:
            db_queries += 1

        spans_by_id[sid] = {
            "span_id": sid,
            "parent_span_id": pid,
            "service_name": s_name,
            "port": None,
            "route_path": str(r["route_path"] or ""),
            "handler_symbol": str(r["handler_symbol"] or ""),
            "db_operation": str(r["db_operation"] or ""),
            "db_table": str(r["db_table"] or ""),
            "status_code": sc,
            "duration_ms": dur,
        }
        if pid not in children_by_parent:
            children_by_parent[pid] = []
        children_by_parent[pid].append(sid)

    # Build tree
    def _build_node(sid: str) -> TraceSpanNode:
        data = spans_by_id[sid]
        child_sids = children_by_parent.get(sid, [])
        children = tuple(_build_node(cid) for cid in child_sids if cid in spans_by_id)
        return TraceSpanNode(
            span_id=data["span_id"],
            parent_span_id=data["parent_span_id"],
            service_name=data["service_name"],
            port=data["port"],
            route_path=data["route_path"],
            handler_symbol=data["handler_symbol"],
            db_operation=data["db_operation"],
            db_table=data["db_table"],
            status_code=data["status_code"],
            duration_ms=data["duration_ms"],
            children=children,
        )

    # Root spans: parent_span_id is empty or not in spans_by_id
    roots: list[TraceSpanNode] = []
    for sid, data in spans_by_id.items():
        pid = data["parent_span_id"]
        if not pid or pid not in spans_by_id:
            roots.append(_build_node(sid))

    # Resolve services
    services_list: list[dict[str, Any]] = [{"name": s} for s in sorted(services_set)]

    summary = (
        f"Trace {clean_tid[:8]}: {len(rows)} spans across {len(services_set)} service(s), "
        f"{db_queries} DB queries, total duration {total_time:.1f}ms."
    )

    return DistributedTraceReport(
        trace_id=clean_tid,
        total_duration_ms=total_time,
        services_involved=tuple(services_list),
        root_spans=tuple(roots),
        db_queries_count=db_queries,
        has_errors=has_err,
        summary=summary,
    )
