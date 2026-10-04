"""Privacy-Safe, Bounded Runtime Ingestion Adapters (Phases 11, 15, 16).

Supported Formats:
1. OpenTelemetry (`otel`) — OTLP JSON (`resourceSpans` / `scopeSpans` / `spans` or flat span list)
2. Structured JSON Runtime Traces (`json` / `jsonl`) — explicit event objects
3. SQL / Query Logs (`sql_log`) — raw or structured SQL query log lines

Security & Storage Invariants:
- Never executes application code or connects to live databases.
- Strips and redacts Authorization headers, Cookies, request/response bodies, tokens, API keys,
  passwords, connection strings, and SQL bound parameters (`VALUES (?, ?)`).
- Enforces `max_events`, deterministic `sampling_rate`, `retention_limit`, and compact aggregation
  into `runtime_edges` with `observation_count`, `first_seen`, `last_seen`, and `runtime_generation`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from codegraph.database.extractor import parse_sql_statement
from codegraph.security.paths import safe_read_text
from codegraph.security.redaction import (
    SENSITIVE_RUNTIME_KEYS,
    is_secret_variable_name,
    normalize_and_redact_sql,
    redact_payload,
    redact_secrets,
)

from .models import RuntimeEvent

DEFAULT_MAX_INGEST_EVENTS = 5_000
DEFAULT_RETENTION_OBSERVATIONS = 1_000


def _deterministic_sample(trace_id: str, span_id: str, sampling_rate: float) -> bool:
    if sampling_rate >= 1.0:
        return True
    if sampling_rate <= 0.0:
        return False
    digest = hashlib.sha256(f"{trace_id}:{span_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return bucket <= sampling_rate


def _resolve_symbol_in_db(con: sqlite3.Connection, raw_sym: str) -> str:
    """Resolve a short or qualified function/method name to its indexed canonical_id if unique."""
    if not raw_sym:
        return ""
    cleaned = raw_sym.strip()
    row = con.execute(
        "SELECT canonical_id FROM symbols WHERE canonical_id = ? OR qualified_name = ? ORDER BY canonical_id LIMIT 1",
        (cleaned, cleaned),
    ).fetchone()
    if row:
        return str(row["canonical_id"])
    rows = con.execute(
        "SELECT canonical_id FROM symbols WHERE name = ? ORDER BY canonical_id",
        (cleaned.split(".")[-1],),
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0]["canonical_id"])
    return cleaned


def _resolve_table_in_db(con: sqlite3.Connection, raw_table: str) -> str:
    """Resolve a table name to its indexed canonical table ID if present, else `db.UNKNOWN.UNKNOWN.<table>`."""
    if not raw_table:
        return ""
    tbl = raw_table.strip().lower().split(".")[-1]
    row = con.execute(
        "SELECT canonical_id FROM db_entities WHERE kind = 'Table' AND table_name = ? ORDER BY canonical_id LIMIT 1",
        (tbl,),
    ).fetchone()
    if row:
        return str(row["canonical_id"])
    return f"db.UNKNOWN.UNKNOWN.{tbl}"


def parse_otel_traces(
    payload: dict[str, Any] | list[Any],
    runtime_generation: int = 1,
    max_events: int = DEFAULT_MAX_INGEST_EVENTS,
    sampling_rate: float = 1.0,
) -> list[RuntimeEvent]:
    """Parse OpenTelemetry JSON (`resourceSpans` or list of spans) into sanitized `RuntimeEvent`s."""
    spans_raw: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload, dict) and "resourceSpans" in payload:
        for rspan in payload.get("resourceSpans", []):
            if not isinstance(rspan, dict):
                continue
            svc_name = ""
            res_attrs = rspan.get("resource", {}).get("attributes", [])
            for attr in res_attrs if isinstance(res_attrs, list) else []:
                if isinstance(attr, dict) and attr.get("key") == "service.name":
                    val_obj = attr.get("value", {})
                    svc_name = str(val_obj.get("stringValue", "") if isinstance(val_obj, dict) else val_obj)
            scope_spans = rspan.get("scopeSpans") or rspan.get("instrumentationLibrarySpans") or []
            for sspan in scope_spans if isinstance(scope_spans, list) else []:
                if not isinstance(sspan, dict):
                    continue
                for sp in sspan.get("spans", []):
                    if isinstance(sp, dict):
                        spans_raw.append((svc_name, sp))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                spans_raw.append((str(item.get("service_name") or item.get("service") or ""), item))

    events: list[RuntimeEvent] = []
    for idx, (svc_name, sp) in enumerate(spans_raw):
        if len(events) >= max_events:
            break
        trace_id = str(sp.get("traceId") or sp.get("trace_id") or f"trace_{idx}")
        span_id = str(sp.get("spanId") or sp.get("span_id") or f"span_{idx}")
        parent_id = str(sp.get("parentSpanId") or sp.get("parent_span_id") or "")
        if not _deterministic_sample(trace_id, span_id, sampling_rate):
            continue

        # Parse attributes safely, dropping sensitive keys
        attrs: dict[str, Any] = {}
        raw_attrs = sp.get("attributes", {})
        if isinstance(raw_attrs, list):
            for entry in raw_attrs:
                if isinstance(entry, dict) and "key" in entry:
                    k = str(entry["key"])
                    v_obj = entry.get("value", {})
                    if isinstance(v_obj, dict):
                        v = (
                            v_obj.get("stringValue")
                            or v_obj.get("intValue")
                            or v_obj.get("doubleValue")
                            or v_obj.get("boolValue")
                            or ""
                        )
                    else:
                        v = v_obj
                    if k.lower() not in SENSITIVE_RUNTIME_KEYS and not is_secret_variable_name(k):
                        attrs[k] = v
        elif isinstance(raw_attrs, dict):
            for k, v in raw_attrs.items():
                if str(k).lower() not in SENSITIVE_RUNTIME_KEYS and not is_secret_variable_name(str(k)):
                    attrs[str(k)] = v

        http_method = str(attrs.get("http.method") or attrs.get("http.request.method") or sp.get("http_method") or "").upper()
        route_path = str(attrs.get("http.route") or attrs.get("url.path") or sp.get("route") or "")
        code_fn = str(attrs.get("code.function") or sp.get("function") or sp.get("handler") or "")
        code_ns = str(attrs.get("code.namespace") or "")
        full_fn = f"{code_ns}.{code_fn}" if code_ns and code_fn and not code_fn.startswith(code_ns) else code_fn
        db_stmt = str(attrs.get("db.statement") or sp.get("sql") or "")
        db_op = str(attrs.get("db.operation") or sp.get("operation") or "").upper()
        db_tbl = str(attrs.get("db.sql.table") or attrs.get("db.collection.name") or sp.get("table") or "").lower()
        db_cols: list[str] = []

        if db_stmt:
            parsed_sql = parse_sql_statement(db_stmt)
            if parsed_sql:
                first_op = parsed_sql[0]
                if not db_op:
                    db_op = str(first_op.get("operation") or "")
                if not db_tbl and first_op.get("tables"):
                    db_tbl = str(first_op["tables"][0]).lower()
                db_cols = [str(c) for c in first_op.get("columns", [])]

        start_ns = sp.get("startTimeUnixNano")
        end_ns = sp.get("endTimeUnixNano")
        duration_ms = float(sp.get("duration_ms") or 0.0)
        if not duration_ms and start_ns and end_ns:
            try:
                duration_ms = max(0.0, (int(end_ns) - int(start_ns)) / 1_000_000.0)
            except (ValueError, TypeError):
                duration_ms = 0.0

        status_code_raw = attrs.get("http.status_code") or attrs.get("http.response.status_code") or sp.get("status_code")
        status_code = int(status_code_raw) if status_code_raw is not None and str(status_code_raw).isdigit() else None

        events.append(
            RuntimeEvent(
                event_id=f"otel:{trace_id}:{span_id}",
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_id,
                timestamp=str(sp.get("timestamp") or start_ns or ""),
                source_format="otel",
                http_method=http_method,
                route_path=route_path,
                handler_symbol=full_fn if route_path else "",
                caller_symbol= str(sp.get("caller") or full_fn),
                callee_symbol= str(sp.get("callee") or ""),
                service_name=svc_name or str(attrs.get("service.name") or ""),
                db_operation=db_op,
                db_table=db_tbl,
                db_columns=tuple(db_cols),
                normalized_sql=normalize_and_redact_sql(db_stmt) if db_stmt else "",
                status_code=status_code,
                exception_type=str(attrs.get("exception.type") or sp.get("exception") or ""),
                duration_ms=duration_ms,
                runtime_generation=runtime_generation,
                metadata=redact_payload(attrs),
            )
        )

    return events


def parse_json_runtime_events(
    items: list[dict[str, Any]],
    runtime_generation: int = 1,
    max_events: int = DEFAULT_MAX_INGEST_EVENTS,
    sampling_rate: float = 1.0,
) -> list[RuntimeEvent]:
    """Parse structured JSON runtime events into normalized, redacted `RuntimeEvent` records."""
    events: list[RuntimeEvent] = []
    for idx, item in enumerate(items):
        if len(events) >= max_events:
            break
        if not isinstance(item, dict):
            continue
        trace_id = str(item.get("trace_id") or item.get("traceId") or f"trace_{idx}")
        span_id = str(item.get("span_id") or item.get("spanId") or f"span_{idx}")
        if not _deterministic_sample(trace_id, span_id, sampling_rate):
            continue

        raw_sql = str(item.get("sql") or item.get("query") or item.get("statement") or "")
        op = str(item.get("operation") or item.get("db_operation") or "").upper()
        tbl = str(item.get("table") or item.get("db_table") or "").lower()
        cols_raw = item.get("columns") or item.get("db_columns") or []
        cols: list[str] = [str(c).lower() for c in cols_raw] if isinstance(cols_raw, list) else []

        if raw_sql:
            parsed_sql = parse_sql_statement(raw_sql)
            if parsed_sql:
                first_op = parsed_sql[0]
                if not op:
                    op = str(first_op.get("operation") or "")
                if not tbl and first_op.get("tables"):
                    tbl = str(first_op["tables"][0]).lower()
                if not cols:
                    cols = [str(c) for c in first_op.get("columns", [])]

        route_str = str(item.get("route") or item.get("route_path") or item.get("path") or "")
        method_str = str(item.get("http_method") or item.get("method") or "").upper()
        if route_str and " " in route_str and not method_str:
            parts = route_str.split(" ", 1)
            if parts[0].upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                method_str = parts[0].upper()
                route_str = parts[1].strip()

        handler = str(item.get("handler") or item.get("handler_symbol") or "")
        caller = str(item.get("caller") or item.get("function") or item.get("source_symbol") or handler or "")
        callee = str(item.get("callee") or item.get("target_symbol") or "")
        service = str(item.get("service") or item.get("service_name") or "")

        safe_meta: dict[str, Any] = {}
        for k, v in item.items():
            kl = str(k).lower()
            if kl in (
                "trace_id",
                "span_id",
                "parent_span_id",
                "timestamp",
                "operation",
                "table",
                "columns",
                "sql",
                "query",
                "statement",
                "route",
                "route_path",
                "http_method",
                "method",
                "handler",
                "caller",
                "callee",
                "function",
                "service",
                "duration_ms",
                "status_code",
                "exception",
            ):
                continue
            if kl in SENSITIVE_RUNTIME_KEYS or is_secret_variable_name(str(k)):
                safe_meta[str(k)] = "[REDACTED]"
            else:
                safe_meta[str(k)] = redact_payload(v)

        status_raw = item.get("status_code") or item.get("status")
        status_code = int(status_raw) if status_raw is not None and str(status_raw).isdigit() else None

        events.append(
            RuntimeEvent(
                event_id=f"json:{trace_id}:{span_id}:{idx}",
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=str(item.get("parent_span_id") or ""),
                timestamp=str(item.get("timestamp") or ""),
                source_format="json",
                http_method=method_str,
                route_path=route_str,
                handler_symbol=handler,
                caller_symbol=caller,
                callee_symbol=callee,
                service_name=service,
                db_operation=op,
                db_table=tbl,
                db_columns=tuple(cols),
                normalized_sql=normalize_and_redact_sql(raw_sql) if raw_sql else (f"{op} {tbl}".strip() if op and tbl else ""),
                status_code=status_code,
                exception_type=str(item.get("exception") or item.get("exception_type") or ""),
                duration_ms=float(item.get("duration_ms") or 0.0),
                runtime_generation=runtime_generation,
                metadata=safe_meta,
            )
        )
    return events


def parse_sql_query_logs(
    log_text: str,
    runtime_generation: int = 1,
    max_events: int = DEFAULT_MAX_INGEST_EVENTS,
) -> list[RuntimeEvent]:
    """Parse SQL query log lines into normalized, parameter-redacted `RuntimeEvent` records."""
    events: list[RuntimeEvent] = []
    for idx, raw_line in enumerate(log_text.splitlines()):
        if len(events) >= max_events:
            break
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Extract optional structured tags like [trace_id=...] [caller=...] [duration_ms=...]
        trace_m = re.search(r"trace_id=([A-Za-z0-9_-]+)", line)
        caller_m = re.search(r"(?:caller|function|symbol)=([A-Za-z0-9_.:]+)", line)
        dur_m = re.search(r"duration(?:_ms)?=([0-9.]+)", line)

        trace_id = trace_m.group(1) if trace_m else f"sqllog_{idx}"
        caller = caller_m.group(1) if caller_m else ""
        dur = float(dur_m.group(1)) if dur_m else 0.0

        parsed_ops = parse_sql_statement(line)
        for op_idx, op_info in enumerate(parsed_ops):
            op = str(op_info.get("operation") or "")
            tables = op_info.get("tables", [])
            cols = tuple(str(c) for c in op_info.get("columns", []))
            norm_sql = str(op_info.get("normalized_sql") or "")
            for tbl in tables:
                events.append(
                    RuntimeEvent(
                        event_id=f"sqllog:{idx}:{op_idx}:{tbl}",
                        trace_id=trace_id,
                        span_id=f"sqlspan_{idx}_{op_idx}",
                        timestamp="",
                        source_format="sql_log",
                        caller_symbol=caller,
                        db_operation=op,
                        db_table=str(tbl).lower(),
                        db_columns=cols,
                        normalized_sql=norm_sql,
                        duration_ms=dur,
                        runtime_generation=runtime_generation,
                    )
                )
    return events


def ingest_runtime_traces(
    con: sqlite3.Connection,
    data_or_path: str | dict[str, Any] | list[Any] | Path | None = None,
    repository: Path | None = None,
    format: str = "auto",
    max_events: int = DEFAULT_MAX_INGEST_EVENTS,
    sampling_rate: float = 1.0,
    retention_limit: int = DEFAULT_RETENTION_OBSERVATIONS,
    *,
    source_path: str = "",
    payload: str = "",
    sample_rate: float | None = None,
) -> dict[str, Any]:
    """Ingest runtime observations from OpenTelemetry JSON, structured JSON/JSONL events, or SQL logs.

    Persists bounded, deduplicated, redacted records into `runtime_observations` and `runtime_edges`.
    """
    if sample_rate is not None:
        sampling_rate = float(sample_rate)
    if isinstance(data_or_path, Path):
        if repository is None:
            repository = data_or_path
        data_or_path = payload or source_path
    elif data_or_path is None:
        data_or_path = payload or source_path

    # Increment runtime_generation
    curr_gen = 0
    try:
        row = con.execute("SELECT value FROM metadata WHERE key='runtime_generation'").fetchone()
        if row and row[0]:
            curr_gen = int(row[0])
    except (sqlite3.OperationalError, ValueError):
        pass
    next_gen = curr_gen + 1

    raw_payload: Any = data_or_path
    if isinstance(data_or_path, str):
        stripped = data_or_path.strip()
        if stripped.startswith(("{", "[")):
            try:
                raw_payload = json.loads(stripped)
            except json.JSONDecodeError:
                # Could be JSONL
                jsonl_items: list[dict[str, Any]] = []
                for ln in stripped.splitlines():
                    ln_s = ln.strip()
                    if ln_s.startswith("{"):
                        try:
                            jsonl_items.append(json.loads(ln_s))
                        except json.JSONDecodeError:
                            pass
                if jsonl_items:
                    raw_payload = jsonl_items
        elif repository is not None and stripped and not stripped.upper().startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
            # Treat as repository-relative file path validated via safe_read_text
            _, _, file_text = safe_read_text(repository, stripped)
            try:
                raw_payload = json.loads(file_text)
            except json.JSONDecodeError:
                jsonl_list = [
                    json.loads(ln)
                    for ln in file_text.splitlines()
                    if ln.strip().startswith("{")
                ]
                raw_payload = jsonl_list if jsonl_list else file_text

    # Parse into RuntimeEvent list based on format
    events: list[RuntimeEvent] = []
    fmt = format.strip().lower()
    if isinstance(raw_payload, dict):
        if fmt in ("auto", "otel") and "resourceSpans" in raw_payload:
            events = parse_otel_traces(raw_payload, next_gen, max_events, sampling_rate)
        else:
            events = parse_json_runtime_events([raw_payload], next_gen, max_events, sampling_rate)
    elif isinstance(raw_payload, list):
        if fmt == "otel" or (
            fmt == "auto"
            and raw_payload
            and isinstance(raw_payload[0], dict)
            and ("traceId" in raw_payload[0] or "attributes" in raw_payload[0])
        ):
            events = parse_otel_traces(raw_payload, next_gen, max_events, sampling_rate)
        else:
            events = parse_json_runtime_events(raw_payload, next_gen, max_events, sampling_rate)
    elif isinstance(raw_payload, str):
        events = parse_sql_query_logs(raw_payload, next_gen, max_events)

    edges_upserted = 0
    spans_by_id: dict[tuple[str, str], RuntimeEvent] = {(e.trace_id, e.span_id): e for e in events}

    for ev in events:
        caller_resolved = _resolve_symbol_in_db(con, ev.caller_symbol or ev.handler_symbol or ev.service_name)
        handler_resolved = _resolve_symbol_in_db(con, ev.handler_symbol) if ev.handler_symbol else caller_resolved
        callee_resolved = _resolve_symbol_in_db(con, ev.callee_symbol) if ev.callee_symbol else ""
        tbl_resolved = _resolve_table_in_db(con, ev.db_table) if ev.db_table else ""

        con.execute(
            "INSERT OR REPLACE INTO runtime_observations("
            "event_id, trace_id, span_id, parent_span_id, timestamp, source_format, "
            "http_method, route_path, handler_symbol, caller_symbol, callee_symbol, service_name, "
            "db_operation, db_table, db_columns_json, normalized_sql, status_code, exception_type, "
            "duration_ms, evidence_class, runtime_generation) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.event_id,
                ev.trace_id,
                ev.span_id,
                ev.parent_span_id,
                ev.timestamp,
                ev.source_format,
                ev.http_method,
                redact_secrets(ev.route_path),
                handler_resolved,
                caller_resolved,
                callee_resolved,
                ev.service_name,
                ev.db_operation,
                ev.db_table,
                json.dumps(list(ev.db_columns)),
                ev.normalized_sql,
                ev.status_code,
                redact_secrets(ev.exception_type),
                ev.duration_ms,
                "RUNTIME_OBSERVED",
                next_gen,
            ),
        )

        # 1. Route -> Handler runtime edge
        if ev.route_path and handler_resolved:
            ep_label = f"ENDPOINT:{ev.http_method or 'ANY'}:{ev.route_path}"
            _upsert_runtime_edge(
                con,
                source=ep_label,
                target=handler_resolved,
                relationship="HANDLED_BY",
                operation=ev.http_method or "HTTP",
                ev=ev,
                next_gen=next_gen,
            )
            edges_upserted += 1

        # 2. Parent span caller -> child span caller edge
        if ev.parent_span_id and (ev.trace_id, ev.parent_span_id) in spans_by_id:
            parent_ev = spans_by_id[(ev.trace_id, ev.parent_span_id)]
            parent_sym = _resolve_symbol_in_db(con, parent_ev.caller_symbol or parent_ev.handler_symbol)
            if parent_sym and caller_resolved and parent_sym != caller_resolved:
                _upsert_runtime_edge(
                    con,
                    source=parent_sym,
                    target=caller_resolved,
                    relationship="CALLS",
                    operation="CALL",
                    ev=ev,
                    next_gen=next_gen,
                )
                edges_upserted += 1

        # 3. Explicit caller -> callee runtime edge
        if caller_resolved and callee_resolved:
            _upsert_runtime_edge(
                con,
                source=caller_resolved,
                target=callee_resolved,
                relationship="CALLS",
                operation="CALL",
                ev=ev,
                next_gen=next_gen,
            )
            edges_upserted += 1

        # 4. Caller / Service -> Database Table & Column runtime edges
        if ev.db_table and tbl_resolved:
            src_actor = caller_resolved or ev.service_name or (f"ENDPOINT:{ev.http_method or 'ANY'}:{ev.route_path}" if ev.route_path else "runtime.anonymous")
            op_upper = ev.db_operation.upper()
            rel = "READS_TABLE" if op_upper in ("SELECT", "READ", "FIND", "GET") else "WRITES_TABLE"
            _upsert_runtime_edge(
                con,
                source=src_actor,
                target=tbl_resolved,
                relationship=rel,
                operation=op_upper or "QUERY",
                ev=ev,
                next_gen=next_gen,
            )
            edges_upserted += 1

            col_rel = "READS_COLUMN" if rel == "READS_TABLE" else "WRITES_COLUMN"
            for col in ev.db_columns:
                col_cid = f"{tbl_resolved}.{col.lower()}"
                _upsert_runtime_edge(
                    con,
                    source=src_actor,
                    target=col_cid,
                    relationship=col_rel,
                    operation=op_upper or "QUERY",
                    ev=ev,
                    next_gen=next_gen,
                )
                edges_upserted += 1

    # Enforce retention limit on raw `runtime_observations`
    obs_count = int(con.execute("SELECT count(*) FROM runtime_observations").fetchone()[0])
    if obs_count > retention_limit:
        excess = obs_count - retention_limit
        con.execute(
            "DELETE FROM runtime_observations WHERE event_id IN ("
            "SELECT event_id FROM runtime_observations ORDER BY runtime_generation ASC, event_id ASC LIMIT ?"
            ")",
            (excess,),
        )

    con.execute(
        "INSERT INTO metadata(key, value) VALUES('runtime_generation', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(next_gen),),
    )
    con.commit()

    return {
        "status": "ok",
        "ingested_events": len(events),
        "events_ingested": len(events),
        "edges_updated": edges_upserted,
        "runtime_generation": next_gen,
        "evidence_class": "RUNTIME_OBSERVED",
        "retention_limit": retention_limit,
    }


def _upsert_runtime_edge(
    con: sqlite3.Connection,
    source: str,
    target: str,
    relationship: str,
    operation: str,
    ev: RuntimeEvent,
    next_gen: int,
) -> None:
    edge_id = f"rtedge:{source}->{target}:{relationship}:{operation}"
    existing = con.execute(
        "SELECT observation_count, first_seen, avg_duration_ms, max_duration_ms "
        "FROM runtime_edges WHERE edge_id = ?",
        (edge_id,),
    ).fetchone()

    if existing:
        old_cnt = int(existing["observation_count"])
        new_cnt = old_cnt + 1
        first_seen = str(existing["first_seen"] or ev.timestamp)
        last_seen = str(ev.timestamp or existing["first_seen"] or "")
        old_avg = float(existing["avg_duration_ms"] or 0.0)
        new_avg = ((old_avg * old_cnt) + ev.duration_ms) / new_cnt
        new_max = max(float(existing["max_duration_ms"] or 0.0), ev.duration_ms)
        con.execute(
            "UPDATE runtime_edges SET observation_count=?, first_seen=?, last_seen=?, "
            "avg_duration_ms=?, max_duration_ms=?, sample_trace_id=?, sample_span_id=?, "
            "normalized_sql=?, status_code=?, exception_type=?, runtime_generation=? "
            "WHERE edge_id=?",
            (
                new_cnt,
                first_seen,
                last_seen,
                new_avg,
                new_max,
                ev.trace_id,
                ev.span_id,
                ev.normalized_sql,
                ev.status_code,
                redact_secrets(ev.exception_type),
                next_gen,
                edge_id,
            ),
        )
    else:
        con.execute(
            "INSERT INTO runtime_edges("
            "edge_id, source, target, relationship, operation, evidence_class, "
            "observation_count, first_seen, last_seen, avg_duration_ms, max_duration_ms, "
            "sample_trace_id, sample_span_id, normalized_sql, status_code, exception_type, runtime_generation) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                edge_id,
                source,
                target,
                relationship,
                operation,
                "RUNTIME_OBSERVED",
                1,
                ev.timestamp,
                ev.timestamp,
                ev.duration_ms,
                ev.duration_ms,
                ev.trace_id,
                ev.span_id,
                ev.normalized_sql,
                ev.status_code,
                redact_secrets(ev.exception_type),
                next_gen,
            ),
        )
