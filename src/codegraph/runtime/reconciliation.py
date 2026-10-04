"""Runtime Map & Static-vs-Runtime Reconciliation Engine (Phases 12 & 13).

Enables CodeGraph to:
1. Query the canonical runtime graph (`HTTP -> ROUTE -> HANDLER -> FUNCTION -> SERVICE -> DB OP -> TABLE -> COLUMN`)
   and reverse runtime mappings (`TABLE -> WRITERS`, `TABLE -> READERS`, `ROUTE -> DATABASE`,
   `DATABASE -> ROUTES`, `FUNCTION -> QUERIES`, `QUERY -> SOURCE LOCATION`).
2. Compare static code+database expectations against runtime observations:
   - `CONFIRMED_RUNTIME_PATH`
   - `STATIC_RUNTIME_CONFLICT`
   - `NOT_OBSERVED_AT_RUNTIME` (observational only; never implies impossibility)
   - `RUNTIME_ONLY_OBSERVED` (never promoted to static `AST_VERIFIED`)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from codegraph.security.redaction import redact_payload, redact_secrets

from .models import ReconciliationStatus


def get_runtime_trace(
    con: sqlite3.Connection,
    repo_or_trace_id: Any = None,
    route: str | None = None,
    symbol: str | None = None,
    table: str | None = None,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Query runtime observations and the aggregated runtime graph (Phase 13)."""
    if isinstance(repo_or_trace_id, str) and not trace_id:
        trace_id = repo_or_trace_id
    obs_rows = con.execute(
        "SELECT event_id, trace_id, span_id, parent_span_id, timestamp, source_format, "
        "http_method, route_path, handler_symbol, caller_symbol, callee_symbol, service_name, "
        "db_operation, db_table, db_columns_json, normalized_sql, status_code, exception_type, "
        "duration_ms, evidence_class, runtime_generation "
        "FROM runtime_observations ORDER BY runtime_generation DESC, event_id ASC"
    ).fetchall()

    edge_rows = con.execute(
        "SELECT edge_id, source, target, relationship, operation, evidence_class, "
        "observation_count, first_seen, last_seen, avg_duration_ms, max_duration_ms, "
        "sample_trace_id, sample_span_id, normalized_sql, status_code, exception_type, runtime_generation "
        "FROM runtime_edges ORDER BY observation_count DESC, edge_id ASC"
    ).fetchall()

    q_trace = (trace_id or "").strip()
    q_route = (route or "").strip().lower()
    q_sym = (symbol or "").strip().lower()
    q_tbl = (table or "").strip().lower().split(".")[-1]

    # Pre-collect trace_ids that match q_route so child spans in the same trace are retained
    route_matched_traces: set[str] = set()
    if q_route:
        for r in obs_rows:
            if q_route in str(r["route_path"]).lower():
                route_matched_traces.add(str(r["trace_id"]))

    filtered_obs: list[dict[str, Any]] = []
    for r in obs_rows:
        if q_trace and str(r["trace_id"]) != q_trace:
            continue
        if (
            q_route
            and q_route not in str(r["route_path"]).lower()
            and str(r["trace_id"]) not in route_matched_traces
        ):
            continue
        if q_sym and not any(
            q_sym in str(r[col]).lower()
            for col in ("handler_symbol", "caller_symbol", "callee_symbol", "service_name")
        ):
            continue
        if q_tbl and q_tbl != str(r["db_table"]).lower():
            continue

        # Attempt to map query back to static source location if symbol is known
        caller_sym = str(r["caller_symbol"] or r["handler_symbol"] or "")
        src_loc: dict[str, Any] | None = None
        if caller_sym:
            srow = con.execute(
                "SELECT path, start_line, end_line FROM symbols WHERE canonical_id = ? OR qualified_name = ? OR name = ? LIMIT 1",
                (caller_sym, caller_sym, caller_sym.split(".")[-1]),
            ).fetchone()
            if srow:
                src_loc = {
                    "file": str(srow["path"]),
                    "start_line": int(srow["start_line"]),
                    "end_line": int(srow["end_line"]),
                }

        filtered_obs.append({
            "event_id": str(r["event_id"]),
            "trace_id": str(r["trace_id"]),
            "span_id": str(r["span_id"]),
            "parent_span_id": str(r["parent_span_id"]),
            "timestamp": str(r["timestamp"]),
            "source_format": str(r["source_format"]),
            "http_method": str(r["http_method"]),
            "route_path": redact_secrets(str(r["route_path"])),
            "handler_symbol": str(r["handler_symbol"]),
            "caller_symbol": caller_sym,
            "callee_symbol": str(r["callee_symbol"]),
            "service_name": str(r["service_name"]),
            "db_operation": str(r["db_operation"]),
            "db_table": str(r["db_table"]),
            "db_columns": json.loads(r["db_columns_json"] or "[]"),
            "normalized_sql": redact_secrets(str(r["normalized_sql"])),
            "status_code": r["status_code"],
            "exception_type": redact_secrets(str(r["exception_type"])),
            "duration_ms": float(r["duration_ms"] or 0.0),
            "evidence_class": "RUNTIME_OBSERVED",
            "runtime_generation": int(r["runtime_generation"]),
            "source_location": src_loc,
        })

    filtered_edges: list[dict[str, Any]] = []
    table_writers: dict[str, list[str]] = {}
    table_readers: dict[str, list[str]] = {}
    route_to_tables: dict[str, list[str]] = {}
    table_to_routes: dict[str, list[str]] = {}
    function_to_queries: dict[str, list[str]] = {}

    for er in edge_rows:
        src = str(er["source"])
        tgt = str(er["target"])
        rel = str(er["relationship"])
        op = str(er["operation"])
        norm_sql = redact_secrets(str(er["normalized_sql"] or ""))

        if rel == "WRITES_TABLE":
            table_writers.setdefault(tgt, [])
            if src not in table_writers[tgt]:
                table_writers[tgt].append(src)
        elif rel == "READS_TABLE":
            table_readers.setdefault(tgt, [])
            if src not in table_readers[tgt]:
                table_readers[tgt].append(src)

        if norm_sql:
            function_to_queries.setdefault(src, [])
            if norm_sql not in function_to_queries[src]:
                function_to_queries[src].append(norm_sql)

        if q_trace and str(er["sample_trace_id"]) != q_trace:
            continue
        if (
            q_route
            and q_route not in src.lower()
            and q_route not in tgt.lower()
            and str(er["sample_trace_id"]) not in route_matched_traces
        ):
            continue
        if q_sym and q_sym not in src.lower() and q_sym not in tgt.lower():
            continue
        if q_tbl and q_tbl not in tgt.lower():
            continue

        filtered_edges.append({
            "edge_id": str(er["edge_id"]),
            "source": src,
            "target": tgt,
            "relationship": rel,
            "operation": op,
            "evidence_class": "RUNTIME_OBSERVED",
            "confidence": "HIGH",
            "status": "RUNTIME_OBSERVED",
            "observation_count": int(er["observation_count"]),
            "first_seen": str(er["first_seen"]),
            "last_seen": str(er["last_seen"]),
            "avg_duration_ms": round(float(er["avg_duration_ms"] or 0.0), 3),
            "max_duration_ms": round(float(er["max_duration_ms"] or 0.0), 3),
            "sample_trace_id": str(er["sample_trace_id"]),
            "sample_span_id": str(er["sample_span_id"]),
            "normalized_sql": norm_sql,
            "status_code": er["status_code"],
            "exception_type": redact_secrets(str(er["exception_type"] or "")),
            "runtime_generation": int(er["runtime_generation"]),
        })

    # Compute ROUTE <-> DATABASE from observations sharing a trace_id
    traces_routes: dict[str, set[str]] = {}
    traces_tables: dict[str, set[str]] = {}
    for obs in filtered_obs or [
        {
            "trace_id": str(r["trace_id"]),
            "route_path": str(r["route_path"]),
            "http_method": str(r["http_method"]),
            "db_table": str(r["db_table"]),
        }
        for r in obs_rows
    ]:
        tid = str(obs["trace_id"])
        rp = str(obs["route_path"])
        hm = str(obs["http_method"] or "ANY")
        dt = str(obs["db_table"])
        if rp:
            traces_routes.setdefault(tid, set()).add(f"{hm} {rp}")
        if dt:
            traces_tables.setdefault(tid, set()).add(dt)

    for tid, rset in traces_routes.items():
        tset = traces_tables.get(tid, set())
        for r_item in sorted(rset):
            for t_item in sorted(tset):
                route_to_tables.setdefault(r_item, [])
                if t_item not in route_to_tables[r_item]:
                    route_to_tables[r_item].append(t_item)
                table_to_routes.setdefault(t_item, [])
                if r_item not in table_to_routes[t_item]:
                    table_to_routes[t_item].append(r_item)

    return redact_payload({
        "status": "ok",
        "count": len(filtered_edges),
        "observation_count": len(filtered_obs),
        "edge_count": len(filtered_edges),
        "evidence_class": "RUNTIME_OBSERVED",
        "observations": filtered_obs,
        "edges": filtered_edges,
        "runtime_edges": filtered_edges,
        "reverse_maps": {
            "table_to_writers": table_writers,
            "table_to_readers": table_readers,
            "route_to_database": route_to_tables,
            "route_to_tables": route_to_tables,
            "database_to_routes": table_to_routes,
            "table_to_routes": table_to_routes,
            "function_to_queries": function_to_queries,
        },
        "results": filtered_edges,
    })


def reconcile_static_runtime(
    con: sqlite3.Connection,
    repo_or_symbol: Any = None,
    route: str | None = None,
    table: str | None = None,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Compare static code+database expectations against runtime observations (Phase 12).

    Classifies each relationship into:
    - `CONFIRMED_RUNTIME_PATH`
    - `STATIC_RUNTIME_CONFLICT`
    - `NOT_OBSERVED_AT_RUNTIME`
    - `RUNTIME_ONLY_OBSERVED`
    """
    if isinstance(repo_or_symbol, str) and not symbol:
        symbol = repo_or_symbol
    q_sym = (symbol or "").strip().lower()
    q_route = (route or "").strip().lower()
    q_tbl = (table or "").strip().lower().split(".")[-1]

    # 1. Load static database edges from `graph_edges`
    static_rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, end_line, evidence, evidence_class "
        "FROM graph_edges WHERE relationship IN ('READS_TABLE', 'WRITES_TABLE', 'POSSIBLE_TABLE', 'UNKNOWN_TABLE') "
        "ORDER BY source, relationship, target"
    ).fetchall()

    # 2. Load runtime database edges from `runtime_edges`
    runtime_rows = con.execute(
        "SELECT edge_id, source, target, relationship, operation, observation_count, "
        "first_seen, last_seen, avg_duration_ms, sample_trace_id, normalized_sql "
        "FROM runtime_edges WHERE relationship IN ('READS_TABLE', 'WRITES_TABLE') "
        "ORDER BY source, relationship, target"
    ).fetchall()

    def _norm_table(target_id: str) -> str:
        return target_id.strip().lower().split(".")[-1]

    # Group static edges by normalized source symbol
    static_by_source: dict[str, list[dict[str, Any]]] = {}
    for sr in static_rows:
        src = str(sr["source"])
        tgt = str(sr["target"])
        if q_sym and q_sym not in src.lower() and q_sym != src.split(".")[-1].lower():
            continue
        if q_route and q_route not in src.lower():
            continue
        if q_tbl and q_tbl != _norm_table(tgt):
            continue
        static_by_source.setdefault(src, []).append({
            "source": src,
            "target": tgt,
            "table_short": _norm_table(tgt),
            "relationship": str(sr["relationship"]),
            "confidence": str(sr["confidence"]),
            "evidence_class": str(sr["evidence_class"]),
            "file": str(sr["file"]),
            "start_line": int(sr["start_line"]),
            "evidence": redact_secrets(str(sr["evidence"])),
        })

    # Group runtime edges by source symbol (matching exact or short name against static symbols)
    runtime_by_source: dict[str, list[dict[str, Any]]] = {}
    for rr in runtime_rows:
        r_src = str(rr["source"])
        r_tgt = str(rr["target"])
        if q_sym and q_sym not in r_src.lower() and q_sym != r_src.split(".")[-1].lower():
            continue
        if q_route and q_route not in r_src.lower():
            continue
        if q_tbl and q_tbl != _norm_table(r_tgt):
            continue

        # Match against static_by_source keys if short name matches
        matched_key = r_src
        for s_key in static_by_source:
            if s_key.lower() == r_src.lower() or s_key.split(".")[-1].lower() == r_src.split(".")[-1].lower():
                matched_key = s_key
                break

        runtime_by_source.setdefault(matched_key, []).append({
            "edge_id": str(rr["edge_id"]),
            "source": r_src,
            "target": r_tgt,
            "table_short": _norm_table(r_tgt),
            "relationship": str(rr["relationship"]),
            "operation": str(rr["operation"]),
            "evidence_class": "RUNTIME_OBSERVED",
            "observation_count": int(rr["observation_count"]),
            "avg_duration_ms": round(float(rr["avg_duration_ms"] or 0.0), 3),
            "sample_trace_id": str(rr["sample_trace_id"]),
            "normalized_sql": redact_secrets(str(rr["normalized_sql"] or "")),
        })

    confirmed: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    not_observed: list[dict[str, Any]] = []
    runtime_only: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []

    all_sources = sorted(set(static_by_source.keys()) | set(runtime_by_source.keys()))

    for src in all_sources:
        s_edges = static_by_source.get(src, [])
        r_edges = runtime_by_source.get(src, [])

        matched_r_indices: set[int] = set()

        for s_edge in s_edges:
            s_tbl = s_edge["table_short"]
            s_rel = s_edge["relationship"]

            # 1. Exact (table, relationship) match -> CONFIRMED_RUNTIME_PATH
            exact_idx = next(
                (
                    i
                    for i, re_item in enumerate(r_edges)
                    if re_item["table_short"] == s_tbl and re_item["relationship"] == s_rel
                ),
                None,
            )
            if exact_idx is not None:
                matched_r_indices.add(exact_idx)
                re_item = r_edges[exact_idx]
                item = {
                    "reconciliation_status": ReconciliationStatus.CONFIRMED_RUNTIME_PATH.value,
                    "reconciliation_state": ReconciliationStatus.CONFIRMED_RUNTIME_PATH.value,
                    "runtime_evidence_class": "RUNTIME_OBSERVED",
                    "source": src,
                    "table": s_tbl,
                    "static": s_edge,
                    "runtime": re_item,
                    "explanation": (
                        f"Static expectation ({src} -> {s_rel} {s_tbl}) confirmed by runtime observation "
                        f"({re_item['operation']} {s_tbl}, count={re_item['observation_count']})."
                    ),
                }
                confirmed.append(item)
                all_items.append(item)
                continue

            # 2. If static had UNKNOWN_TABLE or POSSIBLE_TABLE and runtime observed a concrete table:
            # Keep static as UNKNOWN/POSSIBLE and report RUNTIME_ONLY_OBSERVED without promoting static proof
            if s_rel in ("UNKNOWN_TABLE", "POSSIBLE_TABLE") and r_edges:
                for i, re_item in enumerate(r_edges):
                    matched_r_indices.add(i)
                    item = {
                        "reconciliation_status": ReconciliationStatus.RUNTIME_ONLY_OBSERVED.value,
                        "reconciliation_state": ReconciliationStatus.RUNTIME_ONLY_OBSERVED.value,
                        "runtime_evidence_class": "RUNTIME_OBSERVED",
                        "source": src,
                        "table": re_item["table_short"],
                        "static": s_edge,
                        "runtime": re_item,
                        "explanation": (
                            f"Static analysis was {s_rel} ({s_edge['evidence_class']}); runtime observed "
                            f"{re_item['operation']} on '{re_item['table_short']}'. Runtime observation is NOT "
                            f"converted into static AST proof."
                        ),
                    }
                    runtime_only.append(item)
                    all_items.append(item)
                continue

            # 3. Static expected table A, but runtime observed this function accessing a DIFFERENT table B -> STATIC_RUNTIME_CONFLICT
            unmatched_r = [
                (i, re_item)
                for i, re_item in enumerate(r_edges)
                if re_item["table_short"] != s_tbl
            ]
            if unmatched_r and not any(re_item["table_short"] == s_tbl for re_item in r_edges):
                idx0, re_conflict = unmatched_r[0]
                matched_r_indices.add(idx0)
                item = {
                    "reconciliation_status": ReconciliationStatus.STATIC_RUNTIME_CONFLICT.value,
                    "reconciliation_state": ReconciliationStatus.STATIC_RUNTIME_CONFLICT.value,
                    "runtime_evidence_class": "RUNTIME_OBSERVED",
                    "source": src,
                    "expected_table": s_tbl,
                    "observed_table": re_conflict["table_short"],
                    "static": s_edge,
                    "runtime": re_conflict,
                    "explanation": (
                        f"Static analysis expected {src} -> {s_rel} '{s_tbl}', but runtime observed "
                        f"{re_conflict['relationship']} '{re_conflict['table_short']}'."
                    ),
                }
                conflicts.append(item)
                all_items.append(item)
                continue

            # 4. Otherwise, static edge was not observed in the supplied runtime telemetry
            item = {
                "reconciliation_status": ReconciliationStatus.NOT_OBSERVED_AT_RUNTIME.value,
                "reconciliation_state": ReconciliationStatus.NOT_OBSERVED_AT_RUNTIME.value,
                "runtime_evidence_class": "RUNTIME_UNOBSERVED",
                "source": src,
                "table": s_tbl,
                "static": s_edge,
                "runtime": None,
                "explanation": (
                    f"Static relationship ({src} -> {s_rel} {s_tbl}) has no matching event in supplied "
                    f"runtime telemetry. Note: runtime telemetry is observational, not exhaustive; "
                    f"'not observed' does NOT mean 'does not happen'."
                ),
            }
            not_observed.append(item)
            all_items.append(item)

        # Any remaining runtime edges for this source that had no static expectation at all
        for i, re_item in enumerate(r_edges):
            if i not in matched_r_indices:
                item = {
                    "reconciliation_status": ReconciliationStatus.RUNTIME_ONLY_OBSERVED.value,
                    "reconciliation_state": ReconciliationStatus.RUNTIME_ONLY_OBSERVED.value,
                    "runtime_evidence_class": "RUNTIME_OBSERVED",
                    "source": src,
                    "table": re_item["table_short"],
                    "static": None,
                    "runtime": re_item,
                    "explanation": (
                        f"Runtime observed {src} -> {re_item['relationship']} '{re_item['table_short']}' "
                        f"with no static database edge. Recorded as RUNTIME_OBSERVED without fabricating static proof."
                    ),
                }
                runtime_only.append(item)
                all_items.append(item)

    return redact_payload({
        "status": "ok",
        "summary": {
            "total_reconciled": len(all_items),
            "confirmed_count": len(confirmed),
            "conflict_count": len(conflicts),
            "not_observed_count": len(not_observed),
            "runtime_only_count": len(runtime_only),
        },
        "epistemic_note": (
            "Runtime observations reflect only the supplied telemetry traces. "
            "NOT_OBSERVED_AT_RUNTIME never implies a static path cannot execute, and "
            "RUNTIME_ONLY_OBSERVED is never promoted to static AST_VERIFIED proof."
        ),
        "confirmed": confirmed,
        "confirmed_runtime_paths": confirmed,
        "conflicts": conflicts,
        "static_runtime_conflicts": conflicts,
        "not_observed": not_observed,
        "not_observed_at_runtime": not_observed,
        "runtime_only": runtime_only,
        "runtime_only_observed": runtime_only,
        "results": all_items,
    })
