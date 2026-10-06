"""Database Intelligence Interrogation & Bidirectional Code-Database Impact Engine (Phases 8, 9, 17).

Provides deterministic, evidence-backed queries across:
- Tables, Columns, Primary Keys, Foreign Keys, Indexes, Constraints, Views, Sequences
- ORM Models & Field Mappings
- SQL & ORM Queries (Readers, Writers, Callers)
- Schema Migrations & Column/Table History
- Bidirectional Code <-> Database Impact Analysis (`DIRECT`, `FRAMEWORK`, `SEMANTIC`, `DI`, `TEST`, `DATABASE`, `RUNTIME`)
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from typing import Any

from codegraph.security.redaction import REDACTED_DB_CREDENTIALS, redact_payload, redact_secrets


def _table_matches(candidate_table: str, candidate_cid: str, query_str: str) -> bool:
    if not query_str:
        return True
    q = query_str.strip().lower()
    t = (candidate_table or "").strip().lower()
    cid = (candidate_cid or "").strip().lower()
    if q in (t, cid):
        return True
    if cid.endswith(f".{q}"):
        return True
    return False


def find_db_tables(
    con: sqlite3.Connection,
    repo_or_name: Any = None,
    name: str | None = None,
    dialect: str | None = None,
    schema: str | None = None,
    *,
    table: str | None = None,
) -> dict[str, Any]:
    """Discover database tables and views in the repository."""
    if isinstance(repo_or_name, str) and not name and not table:
        name = repo_or_name
    elif table and not name:
        name = table
    rows = con.execute(
        "SELECT canonical_id, kind, name, dialect, schema_name, table_name, orm_model_id, "
        "framework, file_path, start_line, end_line, evidence, confidence, evidence_class, status, metadata_json "
        "FROM db_entities WHERE kind IN ('Table', 'View') "
        "ORDER BY table_name, canonical_id, file_path, start_line"
    ).fetchall()

    tables_by_cid: dict[str, dict[str, Any]] = {}
    for r in rows:
        t_name = str(r["table_name"] or r["name"])
        cid = str(r["canonical_id"])
        if name and not _table_matches(t_name, cid, name):
            continue
        if dialect and str(r["dialect"]).lower() != dialect.strip().lower():
            continue
        if schema and str(r["schema_name"]).lower() != schema.strip().lower():
            continue

        if cid not in tables_by_cid:
            tables_by_cid[cid] = {
                "canonical_id": cid,
                "kind": str(r["kind"]),
                "name": t_name,
                "table_name": t_name,
                "dialect": str(r["dialect"]),
                "schema_name": str(r["schema_name"]),
                "orm_models": [str(r["orm_model_id"])] if r["orm_model_id"] else [],
                "framework": str(r["framework"]),
                "file": str(r["file_path"]),
                "start_line": int(r["start_line"]),
                "end_line": int(r["end_line"]),
                "evidence": redact_secrets(str(r["evidence"])),
                "confidence": str(r["confidence"]),
                "evidence_class": str(r["evidence_class"]),
                "status": str(r["status"]),
            }
        else:
            if r["orm_model_id"] and str(r["orm_model_id"]) not in tables_by_cid[cid]["orm_models"]:
                tables_by_cid[cid]["orm_models"].append(str(r["orm_model_id"]))

    results = sorted(tables_by_cid.values(), key=lambda x: (str(x["table_name"]), str(x["canonical_id"])))
    return {
        "status": "ok",
        "count": len(results),
        "tables": results,
        "results": results,
    }


def find_db_columns(
    con: sqlite3.Connection,
    repo_or_table: Any = None,
    column: str | None = None,
    *,
    table: str | None = None,
) -> dict[str, Any]:
    """Discover database columns, types, nullability, PK/FK flags, and ORM field mappings."""
    if isinstance(repo_or_table, str) and not table:
        table = repo_or_table
    rows = con.execute(
        "SELECT canonical_id, name, dialect, schema_name, table_name, column_name, data_type, "
        "nullable, default_value, is_primary_key, is_foreign_key, is_unique, is_indexed, "
        "target_table, target_column, orm_model_id, framework, file_path, start_line, end_line, "
        "evidence, confidence, evidence_class, status "
        "FROM db_entities WHERE kind = 'Column' "
        "ORDER BY table_name, column_name, file_path, start_line"
    ).fetchall()

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        t_name = str(r["table_name"])
        c_name = str(r["column_name"] or r["name"])
        cid = str(r["canonical_id"])
        if table and not _table_matches(t_name, cid, table):
            continue
        if column and column.strip().lower() not in (c_name.lower(), cid.lower(), f"{t_name.lower()}.{c_name.lower()}"):
            continue
        dedup_key = (cid, str(r["file_path"]))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        fk_target: str | None = None
        if r["target_table"] and r["target_column"]:
            fk_target = f"{r['target_table']}.{r['target_column']}"
        elif r["target_table"]:
            fk_target = str(r["target_table"])
        results.append({
            "canonical_id": cid,
            "table_name": t_name,
            "column_name": c_name,
            "name": c_name,
            "dialect": str(r["dialect"]),
            "schema_name": str(r["schema_name"]),
            "data_type": str(r["data_type"]),
            "nullable": bool(r["nullable"]),
            "default_value": redact_secrets(str(r["default_value"])) if r["default_value"] is not None else None,
            "is_primary_key": bool(r["is_primary_key"]),
            "is_foreign_key": bool(r["is_foreign_key"]),
            "is_unique": bool(r["is_unique"]),
            "is_indexed": bool(r["is_indexed"]),
            "target_table": r["target_table"],
            "target_column": r["target_column"],
            "foreign_key_target": fk_target,
            "orm_model_id": r["orm_model_id"],
            "framework": str(r["framework"]),
            "file": str(r["file_path"]),
            "start_line": int(r["start_line"]),
            "end_line": int(r["end_line"]),
            "evidence": redact_secrets(str(r["evidence"])),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
            "status": str(r["status"]),
        })

    return {
        "status": "ok",
        "count": len(results),
        "columns": results,
        "results": results,
    }


def find_db_models(
    con: sqlite3.Connection,
    repo_or_name: Any = None,
    name: str | None = None,
    table: str | None = None,
    framework: str | None = None,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Discover ORM models and their mapped database tables."""
    if isinstance(repo_or_name, str) and not name and not model:
        name = repo_or_name
    elif model and not name:
        name = model
    rows = con.execute(
        "SELECT canonical_id, name, dialect, schema_name, table_name, framework, "
        "file_path, start_line, end_line, evidence, confidence, evidence_class, status "
        "FROM db_entities WHERE kind = 'ORMModel' "
        "ORDER BY name, canonical_id, file_path, start_line"
    ).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        m_name = str(r["name"])
        cid = str(r["canonical_id"])
        t_name = str(r["table_name"])
        fw = str(r["framework"])
        if name and name.strip().lower() not in (m_name.lower(), cid.lower()):
            continue
        if table and table.strip().lower() != t_name.lower():
            continue
        if framework and framework.strip().lower() != fw.lower():
            continue

        # Attach mapped fields
        col_rows = con.execute(
            "SELECT column_name, data_type, is_primary_key, is_foreign_key, target_table, target_column "
            "FROM db_entities WHERE kind = 'Column' AND orm_model_id = ? ORDER BY start_line, column_name",
            (cid,),
        ).fetchall()
        fields = [
            {
                "column": str(cr["column_name"]),
                "data_type": str(cr["data_type"]),
                "is_primary_key": bool(cr["is_primary_key"]),
                "is_foreign_key": bool(cr["is_foreign_key"]),
                "target_table": cr["target_table"],
                "target_column": cr["target_column"],
            }
            for cr in col_rows
        ]
        results.append({
            "canonical_id": cid,
            "name": m_name,
            "model_name": m_name,
            "table_name": t_name,
            "dialect": str(r["dialect"]),
            "schema_name": str(r["schema_name"]),
            "framework": fw,
            "fields": fields,
            "file": str(r["file_path"]),
            "start_line": int(r["start_line"]),
            "end_line": int(r["end_line"]),
            "evidence": redact_secrets(str(r["evidence"])),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
            "status": str(r["status"]),
        })

    return {
        "status": "ok",
        "count": len(results),
        "models": results,
        "results": results,
    }


def find_db_queries(
    con: sqlite3.Connection,
    repo_or_table: Any = None,
    table: str | None = None,
    operation: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Discover static database queries (ORM and raw SQL) across the repository."""
    if isinstance(repo_or_table, str) and not table:
        table = repo_or_table
    rows = con.execute(
        "SELECT query_id, caller_symbol_id, operation, relationship, table_name, table_canonical_id, "
        "columns_json, framework, normalized_sql, file_path, start_line, end_line, "
        "evidence, confidence, evidence_class, status "
        "FROM db_queries ORDER BY file_path, start_line, query_id"
    ).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        t_name = str(r["table_name"])
        t_cid = str(r["table_canonical_id"])
        op = str(r["operation"])
        caller = str(r["caller_symbol_id"])
        if table and not _table_matches(t_name, t_cid, table):
            continue
        if operation and operation.strip().upper() != op.upper():
            continue
        if symbol and symbol.strip() not in (caller, caller.split(".")[-1]):
            continue

        cols = json.loads(r["columns_json"]) if r["columns_json"] else []
        results.append({
            "query_id": str(r["query_id"]),
            "symbol": caller,
            "caller_symbol_id": caller,
            "operation": op,
            "relationship": str(r["relationship"]),
            "table_name": t_name,
            "table_canonical_id": t_cid,
            "columns": cols,
            "framework": str(r["framework"]),
            "normalized_sql": redact_secrets(str(r["normalized_sql"])),
            "file": str(r["file_path"]),
            "start_line": int(r["start_line"]),
            "end_line": int(r["end_line"]),
            "evidence": redact_secrets(str(r["evidence"])),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
            "status": str(r["status"]),
        })

    return {
        "status": "ok",
        "count": len(results),
        "queries": results,
        "results": results,
    }


def _find_table_accessors(
    con: sqlite3.Connection,
    target: str,
    rel_filter: tuple[str, ...],
    include_upstream_routes: bool = True,
) -> dict[str, Any]:
    """Shared implementation for find_db_readers, find_db_writers, and find_db_callers."""
    q = target.strip().lower()
    # Match graph_edges where relationship is in rel_filter and target matches table or column
    placeholders = ",".join("?" for _ in rel_filter)
    edge_rows = con.execute(
        f"SELECT source, target, relationship, confidence, file, start_line, end_line, "
        f"evidence, evidence_class, reason "
        f"FROM graph_edges WHERE relationship IN ({placeholders}) "
        f"ORDER BY file, start_line, source, target",
        rel_filter,
    ).fetchall()

    direct_accessors: list[dict[str, Any]] = []
    seed_symbols: set[str] = set()

    for r in edge_rows:
        tgt = str(r["target"])
        tgt_lower = tgt.lower()
        if not (
            tgt_lower == q
            or tgt_lower.endswith(f".{q}")
            or f".{q}." in tgt_lower
        ):
            continue
        src = str(r["source"])
        seed_symbols.add(src)
        ev_cls = str(r["evidence_class"] or "AST_VERIFIED")
        st = "UNKNOWN" if ev_cls == "UNKNOWN" else ("INFERENCE" if ev_cls in ("POSSIBLE", "AMBIGUOUS") else "FACT")
        direct_accessors.append({
            "source": src,
            "symbol": src,
            "target": tgt,
            "relationship": str(r["relationship"]),
            "confidence": str(r["confidence"]),
            "evidence_class": ev_cls,
            "status": st,
            "file": str(r["file"]),
            "start_line": int(r["start_line"]),
            "end_line": int(r["end_line"]),
            "evidence": redact_secrets(str(r["evidence"])),
            "reason": r["reason"],
            "distance": 1,
        })

    # Traverse upstream callers (service -> controller -> route) deterministically
    upstream_callers: list[dict[str, Any]] = []
    reaching_routes: list[dict[str, Any]] = []

    if include_upstream_routes and seed_symbols:
        visited: set[str] = set(seed_symbols)
        queue: deque[tuple[str, int, list[str]]] = deque((s, 1, [s]) for s in sorted(seed_symbols))

        while queue:
            curr_sym, dist, path_chain = queue.popleft()
            if dist >= 5:
                continue

            # Find callers of curr_sym in graph_edges
            caller_rows = con.execute(
                "SELECT source, target, relationship, confidence, file, start_line, end_line, evidence, evidence_class "
                "FROM graph_edges WHERE target = ? AND relationship IN ('CALLS', 'HANDLED_BY', 'ROUTE_HANDLER', 'ROUTES_TO', 'INJECTS', 'PROVIDES') "
                "ORDER BY file, start_line, source",
                (curr_sym,),
            ).fetchall()

            for cr in caller_rows:
                caller_src = str(cr["source"])
                rel_type = str(cr["relationship"])
                new_chain = [caller_src, *path_chain]
                if caller_src.startswith("ENDPOINT:") or rel_type in ("HANDLED_BY", "ROUTE_HANDLER", "ROUTES_TO"):
                    ep_parts = caller_src.split(":", 2)
                    inferred_method = ep_parts[1] if len(ep_parts) >= 3 else "ANY"
                    inferred_route = ep_parts[2] if len(ep_parts) >= 3 else caller_src
                    if " /" in caller_src:
                        before_path, after_slash = caller_src.split(" /", 1)
                        inferred_method = before_path.split(":")[-1].strip() or inferred_method
                        inferred_route = "/" + after_slash.split("#", 1)[0].strip()
                    reaching_routes.append({
                        "endpoint": caller_src,
                        "http_method": inferred_method,
                        "route_path": inferred_route,
                        "handler": curr_sym,
                        "relationship": rel_type,
                        "confidence": str(cr["confidence"]),
                        "evidence_class": str(cr["evidence_class"]),
                        "file": str(cr["file"]),
                        "start_line": int(cr["start_line"]),
                        "evidence": redact_secrets(str(cr["evidence"])),
                        "chain": new_chain,
                    })
                if caller_src not in visited:
                    visited.add(caller_src)
                    upstream_callers.append({
                        "source": caller_src,
                        "symbol": caller_src,
                        "calls": curr_sym,
                        "relationship": rel_type,
                        "confidence": str(cr["confidence"]),
                        "evidence_class": str(cr["evidence_class"]),
                        "file": str(cr["file"]),
                        "start_line": int(cr["start_line"]),
                        "end_line": int(cr["end_line"]),
                        "evidence": redact_secrets(str(cr["evidence"])),
                        "distance": dist + 1,
                        "chain": new_chain,
                    })
                    queue.append((caller_src, dist + 1, new_chain))

            # Also check framework_routes table directly for handlers matching curr_sym
            rt_rows = con.execute(
                "SELECT endpoint_id, framework, http_method, route_path, handler_canonical_id, file_path, line, evidence, confidence "
                "FROM framework_routes WHERE handler_canonical_id = ? OR handler_name = ? ORDER BY endpoint_id",
                (curr_sym, curr_sym.split(".")[-1]),
            ).fetchall()
            for rr in rt_rows:
                ep_id = str(rr["endpoint_id"])
                if not any(rt["endpoint"] == ep_id for rt in reaching_routes):
                    reaching_routes.append({
                        "endpoint": ep_id,
                        "http_method": str(rr["http_method"]),
                        "route_path": str(rr["route_path"]),
                        "framework": str(rr["framework"]),
                        "handler": curr_sym,
                        "relationship": "HANDLED_BY",
                        "confidence": str(rr["confidence"]),
                        "evidence_class": "FRAMEWORK_VERIFIED",
                        "file": str(rr["file_path"]),
                        "start_line": int(rr["line"]),
                        "evidence": redact_secrets(str(rr["evidence"])),
                        "chain": [ep_id, *path_chain],
                    })

    return {
        "status": "ok",
        "target": target,
        "count": len(direct_accessors),
        "direct_accessors": direct_accessors,
        "upstream_callers": upstream_callers,
        "routes": reaching_routes,
        "upstream_routes": reaching_routes,
        "results": direct_accessors,
    }


def _resolve_target_arg(
    repo_or_target: Any = None,
    table: str | None = None,
    column: str | None = None,
    table_or_column: str | None = None,
) -> str:
    if isinstance(repo_or_target, str) and repo_or_target.strip():
        return repo_or_target.strip()
    if table_or_column and table_or_column.strip():
        return table_or_column.strip()
    if table and column:
        return f"{table.strip()}.{column.strip()}"
    if table:
        return table.strip()
    if column:
        return column.strip()
    return ""


def find_db_writers(
    con: sqlite3.Connection,
    repo_or_target: Any = None,
    *,
    table: str | None = None,
    column: str | None = None,
    table_or_column: str | None = None,
) -> dict[str, Any]:
    """Find all functions, services, and routes that write (INSERT/UPDATE/DELETE) to a table or column."""
    target = _resolve_target_arg(repo_or_target, table=table, column=column, table_or_column=table_or_column)
    res = _find_table_accessors(
        con,
        target,
        ("WRITES_TABLE", "WRITES_COLUMN", "WRITES_COLLECTION"),
        include_upstream_routes=True,
    )
    res["writers"] = res["direct_accessors"]
    return res


def find_db_readers(
    con: sqlite3.Connection,
    repo_or_target: Any = None,
    *,
    table: str | None = None,
    column: str | None = None,
    table_or_column: str | None = None,
) -> dict[str, Any]:
    """Find all functions, services, and routes that read (SELECT/JOIN) from a table or column."""
    target = _resolve_target_arg(repo_or_target, table=table, column=column, table_or_column=table_or_column)
    res = _find_table_accessors(
        con,
        target,
        ("READS_TABLE", "READS_COLUMN", "READS_COLLECTION"),
        include_upstream_routes=True,
    )
    res["readers"] = res["direct_accessors"]
    return res


def find_db_callers(
    con: sqlite3.Connection,
    repo_or_target: Any = None,
    *,
    table: str | None = None,
    column: str | None = None,
    table_or_column: str | None = None,
) -> dict[str, Any]:
    """Find all code symbols and routes that read, write, map to, or query a database table or column."""
    target = _resolve_target_arg(repo_or_target, table=table, column=column, table_or_column=table_or_column)
    res = _find_table_accessors(
        con,
        target,
        (
            "READS_TABLE",
            "WRITES_TABLE",
            "READS_COLUMN",
            "WRITES_COLUMN",
            "MAPS_TO_TABLE",
            "MAPS_TO_COLUMN",
            "POSSIBLE_TABLE",
            "UNKNOWN_TABLE",
        ),
        include_upstream_routes=True,
    )
    res["callers"] = res["direct_accessors"]
    return res


def find_db_relationships(
    con: sqlite3.Connection,
    repo_or_target: Any = None,
    relationship_type: str | None = None,
    *,
    target: str | None = None,
    table: str | None = None,
) -> dict[str, Any]:
    """Discover explicit database relationships (FOREIGN_KEY_TO, MAPS_TO_TABLE, MAPS_TO_COLUMN,
    ORM_RELATION, HAS_PRIMARY_KEY, HAS_INDEX, HAS_UNIQUE_CONSTRAINT, HAS_CHECK_CONSTRAINT,
    MIGRATES_TABLE, READS_TABLE, WRITES_TABLE).
    """
    if isinstance(repo_or_target, str) and not target and not table:
        target = repo_or_target
    elif table and not target:
        target = table
    db_rels = (
        "MAPS_TO_TABLE",
        "MAPS_TO_COLUMN",
        "READS_TABLE",
        "WRITES_TABLE",
        "READS_COLUMN",
        "WRITES_COLUMN",
        "REFERENCES_TABLE",
        "REFERENCES_COLUMN",
        "FOREIGN_KEY_TO",
        "HAS_PRIMARY_KEY",
        "HAS_INDEX",
        "HAS_UNIQUE_CONSTRAINT",
        "HAS_CHECK_CONSTRAINT",
        "MIGRATES_TABLE",
        "QUERIES_DATABASE",
        "ORM_RELATION",
        "POSSIBLE_TABLE",
        "UNKNOWN_TABLE",
    )
    placeholders = ",".join("?" for _ in db_rels)
    rows = con.execute(
        f"SELECT source, target, relationship, confidence, file, start_line, end_line, "
        f"evidence, evidence_class, reason "
        f"FROM graph_edges WHERE relationship IN ({placeholders}) "
        f"ORDER BY relationship, source, target, file, start_line",
        db_rels,
    ).fetchall()

    results: list[dict[str, Any]] = []
    q = (target or "").strip().lower()
    rel_f = (relationship_type or "").strip().upper()

    for r in rows:
        src = str(r["source"])
        tgt = str(r["target"])
        rel = str(r["relationship"])
        if rel_f and rel != rel_f:
            continue
        if q and not (
            q in src.lower()
            or q in tgt.lower()
        ):
            continue
        ev_cls = str(r["evidence_class"] or "AST_VERIFIED")
        st = "UNKNOWN" if ev_cls == "UNKNOWN" else ("INFERENCE" if ev_cls in ("POSSIBLE", "AMBIGUOUS") else "FACT")
        results.append({
            "source": src,
            "target": tgt,
            "relationship": rel,
            "confidence": str(r["confidence"]),
            "evidence_class": ev_cls,
            "status": st,
            "file": str(r["file"]),
            "start_line": int(r["start_line"]),
            "end_line": int(r["end_line"]),
            "evidence": redact_secrets(str(r["evidence"])),
            "reason": r["reason"],
        })

    return {
        "status": "ok",
        "count": len(results),
        "relationships": results,
        "results": results,
    }


def get_db_table(
    con: sqlite3.Connection,
    repo_or_table: Any = None,
    *,
    table: str | None = None,
) -> dict[str, Any]:
    """Get comprehensive details for a single database table: columns, PKs, FKs, indexes,
    constraints, ORM models, readers, writers, migrations, and runtime observations.
    """
    if isinstance(repo_or_table, str) and not table:
        table = repo_or_table
    tbl_name = (table or "").strip()
    tbl_res = find_db_tables(con, name=tbl_name)
    cols_res = find_db_columns(con, table=tbl_name)
    models_res = find_db_models(con, table=tbl_name)
    readers_res = find_db_readers(con, tbl_name)
    writers_res = find_db_writers(con, tbl_name)
    rels_res = find_db_relationships(con, target=tbl_name)

    # Migrations affecting this table
    mig_rows = con.execute(
        "SELECT migration_id, canonical_id, system, revision, down_revision, file_path, "
        "start_line, end_line, created_tables_json, dropped_tables_json, added_columns_json, "
        "removed_columns_json, renamed_columns_json, affected_tables_json, evidence, confidence "
        "FROM db_migrations ORDER BY file_path, revision"
    ).fetchall()
    q_lower = tbl_name.lower().split(".")[-1]
    migrations: list[dict[str, Any]] = []
    for mr in mig_rows:
        aff = [str(x).lower() for x in json.loads(mr["affected_tables_json"] or "[]")]
        if q_lower in aff:
            migrations.append({
                "migration_id": str(mr["migration_id"]),
                "canonical_id": str(mr["canonical_id"]),
                "system": str(mr["system"]),
                "revision": str(mr["revision"]),
                "down_revision": mr["down_revision"],
                "file": str(mr["file_path"]),
                "created_tables": json.loads(mr["created_tables_json"] or "[]"),
                "dropped_tables": json.loads(mr["dropped_tables_json"] or "[]"),
                "added_columns": json.loads(mr["added_columns_json"] or "[]"),
                "removed_columns": json.loads(mr["removed_columns_json"] or "[]"),
                "renamed_columns": json.loads(mr["renamed_columns_json"] or "[]"),
                "evidence": redact_secrets(str(mr["evidence"])),
                "confidence": str(mr["confidence"]),
            })

    # Runtime observations for this table
    runtime_obs: list[dict[str, Any]] = []
    try:
        rt_rows = con.execute(
            "SELECT source, target, relationship, operation, observation_count, first_seen, last_seen, "
            "avg_duration_ms, normalized_sql "
            "FROM runtime_edges WHERE LOWER(target) LIKE ? ORDER BY source, operation",
            (f"%{q_lower}%",),
        ).fetchall()
        for rr in rt_rows:
            runtime_obs.append({
                "source": str(rr["source"]),
                "target": str(rr["target"]),
                "relationship": str(rr["relationship"]),
                "operation": str(rr["operation"]),
                "evidence_class": "RUNTIME_OBSERVED",
                "observation_count": int(rr["observation_count"]),
                "first_seen": rr["first_seen"],
                "last_seen": rr["last_seen"],
                "avg_duration_ms": float(rr["avg_duration_ms"] or 0.0),
                "normalized_sql": redact_secrets(str(rr["normalized_sql"] or "")),
            })
    except sqlite3.OperationalError:
        pass

    primary_table = tbl_res["tables"][0] if tbl_res["tables"] else {
        "canonical_id": f"db.UNKNOWN.UNKNOWN.{q_lower}",
        "name": q_lower,
        "table_name": q_lower,
        "dialect": "UNKNOWN",
        "schema_name": "UNKNOWN",
        "status": "UNKNOWN",
    }

    pks = [c["column_name"] for c in cols_res["columns"] if c.get("is_primary_key")]
    fks = [
        {
            "column": c["column_name"],
            "target_table": c["target_table"],
            "target_column": c["target_column"],
        }
        for c in cols_res["columns"]
        if c.get("is_foreign_key")
    ]
    dedup_routes = sorted(
        {r["endpoint"]: r for r in [*readers_res["routes"], *writers_res["routes"]]}.values(),
        key=lambda x: str(x["endpoint"]),
    )

    return redact_payload({
        "status": "ok",
        "canonical_id": primary_table["canonical_id"],
        "table_name": primary_table["table_name"],
        "table": primary_table,
        "columns": cols_res["columns"],
        "primary_keys": pks,
        "foreign_keys": fks,
        "orm_models": models_res["models"],
        "models": models_res["models"],
        "readers": readers_res["direct_accessors"],
        "writers": writers_res["direct_accessors"],
        "routes": dedup_routes,
        "upstream_routes": dedup_routes,
        "relationships": rels_res["relationships"],
        "migrations": migrations,
        "runtime_observations": runtime_obs,
        "credentials_policy": REDACTED_DB_CREDENTIALS,
    })


def get_db_schema(
    con: sqlite3.Connection,
    repo_or_dialect: Any = None,
    schema: str | None = None,
    *,
    dialect: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the complete repository database schema overview with safe credential redaction."""
    if isinstance(repo_or_dialect, str) and not dialect:
        dialect = repo_or_dialect
    tables = find_db_tables(con, dialect=dialect, schema=schema)["tables"]
    columns = find_db_columns(con)["columns"]
    models = find_db_models(con)["models"]
    rels = find_db_relationships(con)["relationships"]

    mig_rows = con.execute(
        "SELECT migration_id, canonical_id, system, revision, down_revision, file_path, "
        "created_tables_json, dropped_tables_json, added_columns_json, removed_columns_json, "
        "renamed_columns_json, affected_tables_json, evidence, confidence "
        "FROM db_migrations ORDER BY file_path, revision"
    ).fetchall()
    migrations = [
        {
            "migration_id": str(r["migration_id"]),
            "canonical_id": str(r["canonical_id"]),
            "system": str(r["system"]),
            "revision": str(r["revision"]),
            "down_revision": r["down_revision"],
            "file": str(r["file_path"]),
            "created_tables": json.loads(r["created_tables_json"] or "[]"),
            "dropped_tables": json.loads(r["dropped_tables_json"] or "[]"),
            "added_columns": json.loads(r["added_columns_json"] or "[]"),
            "removed_columns": json.loads(r["removed_columns_json"] or "[]"),
            "renamed_columns": json.loads(r["renamed_columns_json"] or "[]"),
            "affected_tables": json.loads(r["affected_tables_json"] or "[]"),
            "evidence": redact_secrets(str(r["evidence"])),
            "confidence": str(r["confidence"]),
        }
        for r in mig_rows
    ]

    env_rows = con.execute(
        "SELECT source, target, file, start_line, evidence FROM graph_edges "
        "WHERE relationship = 'READS_ENV' ORDER BY file, start_line"
    ).fetchall()
    env_vars = [
        {
            "source": str(er["source"]),
            "env_var": str(er["target"]),
            "file": str(er["file"]),
            "start_line": int(er["start_line"]),
            "evidence": redact_secrets(str(er["evidence"])),
        }
        for er in env_rows
    ]

    dialects = sorted({t["dialect"] for t in tables if t.get("dialect")}) or ["UNKNOWN"]

    safe_tables = tables
    safe_models = models
    safe_migrations = migrations
    safe_cols = columns
    safe_rels = rels

    if limit is not None:
        safe_offset = max(0, offset)
        safe_limit = max(0, limit)
        safe_tables = tables[safe_offset : safe_offset + safe_limit]
        safe_models = models[safe_offset : safe_offset + safe_limit]
        safe_migrations = migrations[safe_offset : safe_offset + safe_limit]
        safe_cols = columns[: max(safe_limit * 5, 20)]
        safe_rels = rels[: max(safe_limit * 5, 20)]

    result_dict: dict[str, Any] = {
        "status": "ok",
        "dialects": dialects,
        "table_count": len(tables),
        "column_count": len(columns),
        "model_count": len(models),
        "migration_count": len(migrations),
        "tables": safe_tables,
        "columns": safe_cols,
        "models": safe_models,
        "relationships": safe_rels,
        "migrations": safe_migrations,
        "env_variables": env_vars,
        "database_credentials": "REDACTED",
    }
    if limit is not None:
        result_dict["limit"] = safe_limit
        result_dict["offset"] = safe_offset
        result_dict["has_more"] = (safe_offset + len(safe_tables)) < len(tables)

    return redact_payload(result_dict)


def get_db_impact(
    con: sqlite3.Connection,
    repo_or_target: Any = None,
    max_depth: int = 5,
    *,
    target: str | None = None,
    table: str | None = None,
    column: str | None = None,
) -> dict[str, Any]:
    """Bidirectional Database <-> Code impact analysis (Phases 8 & 17).

    Supports:
    1. DATABASE -> CODE:
       "If I change `products.price` or `users`, what ORM fields, models, queries, services, routes, and tests are affected?"
    2. CODE / ROUTE -> DATABASE:
       "If I change this route or service, which database tables and columns can it touch?"
    3. MIGRATION -> CODE:
       "If I change this schema migration, what tables and code are affected?"

    Preserves impact categories:
        DIRECT, FRAMEWORK, SEMANTIC, DI, TEST, DATABASE, RUNTIME
    """
    q = _resolve_target_arg(repo_or_target, table=table, column=column, table_or_column=target)
    q_lower = q.lower()

    affected_columns: list[dict[str, Any]] = []
    affected_tables: list[dict[str, Any]] = []
    affected_models: list[dict[str, Any]] = []
    affected_queries: list[dict[str, Any]] = []
    affected_services: list[dict[str, Any]] = []
    affected_writers: list[dict[str, Any]] = []
    affected_readers: list[dict[str, Any]] = []
    affected_routes: list[dict[str, Any]] = []
    affected_tests: list[dict[str, Any]] = []
    affected_migrations: list[dict[str, Any]] = []
    impact_items: list[dict[str, Any]] = []

    # Check if target is a table, table.column, ORM model, route, or code symbol
    col_matches = find_db_columns(con, column=q)["columns"]
    tbl_matches = find_db_tables(con, name=q.split(".")[0] if "." in q else q)["tables"]

    # Case A: Target matches a database column or table (DATABASE -> CODE impact)
    if col_matches or tbl_matches or q_lower.startswith("db."):
        target_table_names = {c["table_name"] for c in col_matches} | {t["table_name"] for t in tbl_matches}
        if not target_table_names and "." in q_lower:
            parts = q_lower.split(".")
            target_table_names.add(parts[-2] if len(parts) >= 2 else parts[0])

        for c in col_matches:
            affected_columns.append(c)
            impact_items.append({
                "symbol": c["canonical_id"],
                "category": "DATABASE",
                "relationship": "MAPS_TO_COLUMN",
                "confidence": c["confidence"],
                "file": c["file"],
                "start_line": c["start_line"],
                "evidence": c["evidence"],
            })

        for t_name in sorted(target_table_names):
            t_info = get_db_table(con, table=t_name)
            if t_info.get("table"):
                affected_tables.append(t_info["table"])
            for w_item in t_info.get("writers", []):
                affected_writers.append(w_item)
            for r_item in t_info.get("readers", []):
                affected_readers.append(r_item)
            for m in find_db_models(con, table=t_name)["models"]:
                affected_models.append(m)
                impact_items.append({
                    "symbol": m["canonical_id"],
                    "category": "DATABASE",
                    "relationship": "MAPS_TO_TABLE",
                    "confidence": m["confidence"],
                    "file": m["file"],
                    "start_line": m["start_line"],
                    "evidence": m["evidence"],
                })
            for q_item in find_db_queries(con, table=t_name)["queries"]:
                affected_queries.append(q_item)
                impact_items.append({
                    "symbol": q_item["symbol"],
                    "category": "DIRECT",
                    "relationship": q_item["relationship"],
                    "confidence": q_item["confidence"],
                    "file": q_item["file"],
                    "start_line": q_item["start_line"],
                    "evidence": q_item["evidence"],
                })
            callers_info = find_db_callers(con, table=t_name)
            for acc in [*callers_info["direct_accessors"], *callers_info["upstream_callers"]]:
                sym_id = str(acc["symbol"])
                cat = "DIRECT" if acc.get("distance", 1) == 1 else "SEMANTIC"
                if "test" in str(acc.get("file", "")).lower() or sym_id.split(".")[-1].startswith("test_"):
                    cat = "TEST"
                    affected_tests.append(acc)
                else:
                    affected_services.append(acc)
                impact_items.append({
                    "symbol": sym_id,
                    "category": cat,
                    "relationship": acc["relationship"],
                    "confidence": acc["confidence"],
                    "file": acc["file"],
                    "start_line": acc["start_line"],
                    "evidence": acc["evidence"],
                })
            for rt in callers_info["routes"]:
                affected_routes.append(rt)
                impact_items.append({
                    "symbol": rt["endpoint"],
                    "category": "FRAMEWORK",
                    "relationship": rt["relationship"],
                    "confidence": rt["confidence"],
                    "file": rt["file"],
                    "start_line": rt["start_line"],
                    "evidence": rt["evidence"],
                })
            for mig in t_info.get("migrations", []):
                affected_migrations.append(mig)

            # Also check tests linked to any affected service or model
            candidate_syms = {m["canonical_id"] for m in affected_models} | {s["symbol"] for s in affected_services}
            for csym in sorted(candidate_syms):
                test_rows = con.execute(
                    "SELECT source, target, relationship, confidence, file, start_line, evidence "
                    "FROM graph_edges WHERE (target = ? OR target = ?) AND relationship LIKE 'TESTS%' ORDER BY file, start_line",
                    (csym, csym.split(".")[-1]),
                ).fetchall()
                for tr in test_rows:
                    t_entry = {
                        "symbol": str(tr["source"]),
                        "target": str(tr["target"]),
                        "relationship": str(tr["relationship"]),
                        "confidence": str(tr["confidence"]),
                        "file": str(tr["file"]),
                        "start_line": int(tr["start_line"]),
                        "evidence": redact_secrets(str(tr["evidence"])),
                    }
                    affected_tests.append(t_entry)
                    impact_items.append({
                        "symbol": str(tr["source"]),
                        "category": "TEST",
                        "relationship": str(tr["relationship"]),
                        "confidence": str(tr["confidence"]),
                        "file": str(tr["file"]),
                        "start_line": int(tr["start_line"]),
                        "evidence": redact_secrets(str(tr["evidence"])),
                    })
                # Also check CALLS from test_* symbols to affected services
                caller_test_rows = con.execute(
                    "SELECT source, target, relationship, confidence, file, start_line, evidence "
                    "FROM graph_edges WHERE (target = ? OR target = ?) AND relationship = 'CALLS' ORDER BY file, start_line",
                    (csym, csym.split(".")[-1]),
                ).fetchall()
                for ctr in caller_test_rows:
                    c_src = str(ctr["source"])
                    c_file = str(ctr["file"])
                    if "test" in c_file.lower() or c_src.split(".")[-1].startswith("test_"):
                        t_entry = {
                            "symbol": c_src,
                            "target": str(ctr["target"]),
                            "relationship": "TESTS",
                            "confidence": str(ctr["confidence"]),
                            "file": c_file,
                            "start_line": int(ctr["start_line"]),
                            "evidence": redact_secrets(str(ctr["evidence"])),
                        }
                        if not any(x["symbol"] == c_src for x in affected_tests):
                            affected_tests.append(t_entry)
                            impact_items.append({
                                "symbol": c_src,
                                "category": "TEST",
                                "relationship": "TESTS",
                                "confidence": str(ctr["confidence"]),
                                "file": c_file,
                                "start_line": int(ctr["start_line"]),
                                "evidence": redact_secrets(str(ctr["evidence"])),
                            })

    # Case B: Target is a route, function, or service (CODE -> DATABASE forward traversal)
    visited_fwd: set[str] = {q}
    fwd_queue: deque[tuple[str, int]] = deque([(q, 0)])
    # Also resolve short symbol names or route paths
    sym_rows = con.execute(
        "SELECT canonical_id FROM symbols WHERE canonical_id = ? OR qualified_name = ? OR name = ?",
        (q, q, q),
    ).fetchall()
    for sr in sym_rows:
        cid = str(sr["canonical_id"])
        if cid not in visited_fwd:
            visited_fwd.add(cid)
            fwd_queue.append((cid, 0))

    rt_seed_rows = con.execute(
        "SELECT endpoint_id, handler_canonical_id FROM framework_routes WHERE route_path = ? OR endpoint_id = ?",
        (q, q),
    ).fetchall()
    for rsr in rt_seed_rows:
        h_cid = str(rsr["handler_canonical_id"])
        if h_cid not in visited_fwd:
            visited_fwd.add(h_cid)
            fwd_queue.append((h_cid, 1))

    while fwd_queue:
        curr, depth = fwd_queue.popleft()
        if depth >= max_depth:
            continue
        out_rows = con.execute(
            "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class "
            "FROM graph_edges WHERE source = ? ORDER BY file, start_line, target",
            (curr,),
        ).fetchall()
        for orow in out_rows:
            tgt = str(orow["target"])
            rel = str(orow["relationship"])
            if rel in ("READS_TABLE", "WRITES_TABLE", "READS_COLUMN", "WRITES_COLUMN", "MAPS_TO_TABLE", "POSSIBLE_TABLE", "UNKNOWN_TABLE"):
                affected_tables.append({
                    "canonical_id": tgt,
                    "relationship": rel,
                    "source": curr,
                    "confidence": str(orow["confidence"]),
                    "evidence_class": str(orow["evidence_class"]),
                    "file": str(orow["file"]),
                    "start_line": int(orow["start_line"]),
                    "evidence": redact_secrets(str(orow["evidence"])),
                })
                impact_items.append({
                    "symbol": tgt,
                    "category": "DATABASE",
                    "relationship": rel,
                    "confidence": str(orow["confidence"]),
                    "file": str(orow["file"]),
                    "start_line": int(orow["start_line"]),
                    "evidence": redact_secrets(str(orow["evidence"])),
                })
            elif rel in ("CALLS", "HANDLED_BY", "ROUTE_HANDLER", "ROUTES_TO", "INJECTS", "PROVIDES", "RESOLVES_TO") and tgt not in visited_fwd:
                visited_fwd.add(tgt)
                fwd_queue.append((tgt, depth + 1))

    return redact_payload({
        "status": "ok",
        "target": q,
        "impact_count": len(impact_items),
        "columns": affected_columns,
        "tables": affected_tables,
        "models": affected_models,
        "affected_models": affected_models,
        "queries": affected_queries,
        "affected_queries": affected_queries,
        "services": affected_services,
        "affected_services": affected_services,
        "writers": affected_writers,
        "affected_writers": affected_writers,
        "readers": affected_readers,
        "affected_readers": affected_readers,
        "routes": affected_routes,
        "affected_routes": affected_routes,
        "tests": affected_tests,
        "affected_tests": affected_tests,
        "migrations": affected_migrations,
        "affected_migrations": affected_migrations,
        "impacts": impact_items,
        "results": impact_items,
    })


def _normalize_table_name(raw: str) -> str:
    if not raw:
        return ""
    clean = raw.strip().strip('"`')
    if clean.startswith("db."):
        parts = clean.split(".")
        cand = parts[-1].strip('"`')
        return "UNKNOWN" if cand.upper() == "UNKNOWN" else cand.lower()
    cand = clean.split(".")[-1].strip('"`')
    return "UNKNOWN" if cand.upper() == "UNKNOWN" else cand.lower()


def _normalize_col_name(raw: str) -> str:
    clean = raw.strip().strip('"`')
    return clean.split(".")[-1].strip('"`').lower()


def _infer_table_from_column_target(tgt: str) -> str:
    clean = tgt.strip().strip('"`')
    parts = clean.split(".")
    if len(parts) >= 2:
        cand = parts[-2].strip('"`')
        return "UNKNOWN" if cand.upper() == "UNKNOWN" else cand.lower()
    return ""


def _aggregate_table_access(raw_items: list[dict[str, Any]], max_cols: int) -> list[dict[str, Any]]:
    by_table: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        t = item["table"]
        if not t:
            continue
        if t not in by_table:
            by_table[t] = {
                "table": t,
                "columns": set(),
                "operations": set(),
                "evidence_classes": set(),
                "confidences": set(),
                "call_chains": [],
                "evidence": [],
            }
        entry = by_table[t]
        for c in item.get("columns", []):
            if c:
                entry["columns"].add(c)
        if item.get("operation"):
            entry["operations"].add(item["operation"])
        entry["evidence_classes"].add(item.get("evidence_class", "AST_VERIFIED"))
        entry["confidences"].add(item.get("confidence", "HIGH"))
        if item.get("call_chain"):
            entry["call_chains"].append(item["call_chain"])
        if item.get("evidence"):
            entry["evidence"].append({
                "file": item.get("file", ""),
                "line": item.get("line", 0),
                "snippet": item.get("evidence", ""),
            })

    results: list[dict[str, Any]] = []
    for t_name in sorted(by_table.keys()):
        data = by_table[t_name]
        sorted_cols = sorted(list(data["columns"]))[:max_cols]
        ops = set(data["operations"])
        # If specific mutation operations exist, drop generic "WRITE"
        if len(ops) > 1 and "WRITE" in ops and any(x in ops for x in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")):
            ops.remove("WRITE")
        # If specific read operations exist, drop generic "READ"
        if len(ops) > 1 and "READ" in ops and "SELECT" in ops:
            ops.remove("READ")

        sorted_ops = sorted(list(ops))
        ev_classes = data["evidence_classes"]

        if "UNKNOWN" in ev_classes:
            synth_ev = "UNKNOWN"
            synth_conf = "UNKNOWN"
        elif "POSSIBLE" in ev_classes or "AMBIGUOUS" in ev_classes:
            synth_ev = "POSSIBLE"
            synth_conf = "LOW"
        elif "DATAFLOW_VERIFIED" in ev_classes:
            synth_ev = "DATAFLOW_VERIFIED"
            synth_conf = "HIGH"
        elif "FRAMEWORK_VERIFIED" in ev_classes:
            synth_ev = "FRAMEWORK_VERIFIED"
            synth_conf = "HIGH"
        else:
            synth_ev = "AST_VERIFIED"
            synth_conf = "HIGH"

        shortest_chain = min(data["call_chains"], key=len) if data["call_chains"] else []

        results.append({
            "table": t_name,
            "columns": sorted_cols,
            "operations": sorted_ops,
            "evidence_class": synth_ev,
            "confidence": synth_conf,
            "call_chain": shortest_chain,
            "evidence": data["evidence"][:10],
        })

    return results


def get_route_db_lineage(
    con: sqlite3.Connection,
    route_or_handler: str,
    method: str | None = None,
    *,
    max_depth: int = 4,
    max_tables: int = 25,
    max_columns_per_table: int = 50,
) -> dict[str, Any]:
    """Deterministically trace route or handler through services, repositories, and ORM/SQL down to database mutations and reads.

    Enforces bounded BFS (max_depth=4), cycle protection via visited set, deterministic ordering (table ASC, column ASC),
    strict output budgets, and preserves epistemic states (AST_VERIFIED, STATIC_VERIFIED, DATAFLOW_VERIFIED, FRAMEWORK_VERIFIED, POSSIBLE, UNKNOWN).
    """
    raw = (route_or_handler or "").strip()
    if not raw:
        return {
            "status": "ok",
            "route": "",
            "method": (method or "").upper() or "ANY",
            "handler": "",
            "db_reads": [],
            "db_writes": [],
            "tables": [],
            "evidence_class": "STATIC_VERIFIED",
        }

    clean_target = raw
    req_method = (method or "").strip().upper() or None

    if " " in clean_target:
        parts = clean_target.split(" ", 1)
        if parts[0].upper() in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            req_method = req_method or parts[0].upper()
            clean_target = parts[1].strip()

    route_query = (
        "SELECT route_path, http_method, handler_name, handler_canonical_id, file_path, line "
        "FROM framework_routes WHERE route_path = ? OR endpoint_id = ?"
    )
    params: list[Any] = [clean_target, clean_target]
    if req_method:
        route_query += " AND UPPER(http_method) = ?"
        params.append(req_method)

    try:
        route_rows = con.execute(route_query, params).fetchall()
    except sqlite3.OperationalError:
        route_rows = []

    if not route_rows and req_method:
        try:
            route_rows = con.execute(
                "SELECT route_path, http_method, handler_name, handler_canonical_id, file_path, line "
                "FROM framework_routes WHERE route_path = ? OR endpoint_id = ?",
                (clean_target, clean_target),
            ).fetchall()
        except sqlite3.OperationalError:
            route_rows = []

    seeds: list[tuple[str, str]] = []
    route_info: dict[str, Any] = {}

    if route_rows:
        primary_r = route_rows[0]
        route_info = {
            "route": str(primary_r["route_path"]),
            "method": str(primary_r["http_method"] or req_method or "").upper(),
            "file": str(primary_r["file_path"]),
            "line": int(primary_r["line"]),
        }
        for rr in route_rows:
            h_cid = str(rr["handler_canonical_id"] or "")
            h_name = str(rr["handler_name"] or "")
            if h_cid:
                seeds.append((h_cid, h_name or h_cid.split(".")[-1]))
            elif h_name:
                seeds.append((h_name, h_name))
    else:
        try:
            sym_rows = con.execute(
                "SELECT canonical_id, qualified_name, name, file_path, start_line FROM symbols "
                "WHERE canonical_id = ? OR qualified_name = ? OR name = ?",
                (clean_target, clean_target, clean_target),
            ).fetchall()
        except sqlite3.OperationalError:
            sym_rows = []
        if sym_rows:
            for sr in sym_rows:
                cid = str(sr["canonical_id"] or sr["qualified_name"] or sr["name"])
                seeds.append((cid, str(sr["name"])))
        else:
            seeds.append((clean_target, clean_target))

    visited: set[str] = set()
    queue: deque[tuple[str, int, list[str]]] = deque()
    for s_id, s_disp in seeds:
        if s_id not in visited:
            visited.add(s_id)
            queue.append((s_id, 0, [s_disp]))

    raw_reads: list[dict[str, Any]] = []
    raw_writes: list[dict[str, Any]] = []

    while queue:
        curr_sym, depth, chain = queue.popleft()
        if depth > max_depth:
            continue

        curr_bare = curr_sym.split(".")[-1]

        # 1. Query db_queries table
        try:
            q_rows = con.execute(
                "SELECT query_id, caller_symbol_id, operation, relationship, table_name, table_canonical_id, "
                "columns_json, file_path, start_line, end_line, evidence, confidence, evidence_class, status "
                "FROM db_queries "
                "WHERE caller_symbol_id = ? OR caller_symbol_id LIKE ? OR caller_symbol_id LIKE ? OR caller_symbol_id = ?",
                (curr_sym, f"%.{curr_sym}", f"{curr_sym}.%", curr_bare),
            ).fetchall()
        except sqlite3.OperationalError:
            q_rows = []

        for qr in q_rows:
            op = str(qr["operation"] or "").upper()
            rel = str(qr["relationship"] or "")
            tbl_raw = str(qr["table_name"] or qr["table_canonical_id"] or "")
            tbl_name = _normalize_table_name(tbl_raw)
            if not tbl_name:
                continue

            cols_raw: list[Any] = []
            try:
                cols_raw = json.loads(qr["columns_json"] or "[]")
            except Exception:
                cols_raw = []
            cols = [_normalize_col_name(str(c)) for c in cols_raw if str(c).strip()]

            ev_cls = str(qr["evidence_class"] or "AST_VERIFIED")
            conf = str(qr["confidence"] or "HIGH")
            item = {
                "table": tbl_name,
                "columns": cols,
                "operation": op,
                "evidence_class": ev_cls,
                "confidence": conf,
                "call_chain": list(chain),
                "file": str(qr["file_path"]),
                "line": int(qr["start_line"]),
                "evidence": redact_secrets(str(qr["evidence"])),
            }

            if op in ("SELECT", "FETCH", "READ", "FIND") or rel in ("READS_TABLE", "READS_COLUMN"):
                raw_reads.append(item)
            elif op in ("INSERT", "UPDATE", "DELETE", "WRITE", "SAVE", "CREATE", "DROP", "ALTER") or rel in ("WRITES_TABLE", "WRITES_COLUMN"):
                raw_writes.append(item)
            elif op == "UNKNOWN" or rel == "UNKNOWN_TABLE" or ev_cls == "UNKNOWN":
                raw_writes.append(item)
                raw_reads.append(item)

        # 2. Query graph_edges table for outgoing edges from curr_sym
        try:
            edge_rows = con.execute(
                "SELECT source, target, relationship, confidence, file, start_line, end_line, evidence, evidence_class, reason "
                "FROM graph_edges WHERE source = ? OR source = ?",
                (curr_sym, curr_bare),
            ).fetchall()
        except sqlite3.OperationalError:
            edge_rows = []

        for er in edge_rows:
            rel = str(er["relationship"])
            tgt = str(er["target"])
            ev_cls = str(er["evidence_class"] or "AST_VERIFIED")
            conf = str(er["confidence"] or "HIGH")
            ev_str = redact_secrets(str(er["evidence"] or ""))

            if rel in ("READS_TABLE", "READS_COLUMN"):
                tbl_name = _normalize_table_name(tgt) if rel == "READS_TABLE" else _infer_table_from_column_target(tgt)
                col_name = _normalize_col_name(tgt) if rel == "READS_COLUMN" else None
                if tbl_name:
                    raw_reads.append({
                        "table": tbl_name,
                        "columns": [col_name] if col_name else [],
                        "operation": "SELECT",
                        "evidence_class": ev_cls,
                        "confidence": conf,
                        "call_chain": list(chain),
                        "file": str(er["file"]),
                        "line": int(er["start_line"]),
                        "evidence": ev_str,
                    })
            elif rel in ("WRITES_TABLE", "WRITES_COLUMN"):
                tbl_name = _normalize_table_name(tgt) if rel == "WRITES_TABLE" else _infer_table_from_column_target(tgt)
                col_name = _normalize_col_name(tgt) if rel == "WRITES_COLUMN" else None
                if tbl_name:
                    raw_writes.append({
                        "table": tbl_name,
                        "columns": [col_name] if col_name else [],
                        "operation": "WRITE",
                        "evidence_class": ev_cls,
                        "confidence": conf,
                        "call_chain": list(chain),
                        "file": str(er["file"]),
                        "line": int(er["start_line"]),
                        "evidence": ev_str,
                    })
            elif rel in ("UNKNOWN_TABLE", "POSSIBLE_TABLE"):
                tbl_name = _normalize_table_name(tgt)
                if tbl_name:
                    u_item = {
                        "table": tbl_name,
                        "columns": [],
                        "operation": "UNKNOWN",
                        "evidence_class": "UNKNOWN" if rel == "UNKNOWN_TABLE" else "POSSIBLE",
                        "confidence": "UNKNOWN" if rel == "UNKNOWN_TABLE" else "LOW",
                        "call_chain": list(chain),
                        "file": str(er["file"]),
                        "line": int(er["start_line"]),
                        "evidence": ev_str,
                    }
                    raw_writes.append(u_item)
                    raw_reads.append(u_item)
            elif rel in (
                "CALLS",
                "INJECTS",
                "PROVIDES",
                "RESOLVES_DEPENDENCY",
                "DISPATCHES_TO",
                "ROUTES_TO",
                "HANDLED_BY",
                "CALLS_CELERY_TASK",
                "DISPATCHES_SIGNAL",
            ):
                if depth + 1 <= max_depth and tgt not in visited:
                    visited.add(tgt)
                    next_disp = tgt.split(".")[-1]
                    queue.append((tgt, depth + 1, chain + [next_disp]))

        # 3. Class method expansion
        try:
            def_rows = con.execute(
                "SELECT target FROM graph_edges WHERE (source = ? OR source = ?) AND relationship = 'DEFINES'",
                (curr_sym, curr_bare),
            ).fetchall()
            for dr in def_rows:
                dtgt = str(dr["target"])
                if depth + 1 <= max_depth and dtgt not in visited:
                    visited.add(dtgt)
                    queue.append((dtgt, depth + 1, chain + [dtgt.split(".")[-1]]))
        except sqlite3.OperationalError:
            pass

    aggregated_reads = _aggregate_table_access(raw_reads, max_columns_per_table)[:max_tables]
    aggregated_writes = _aggregate_table_access(raw_writes, max_columns_per_table)[:max_tables]

    all_tables = sorted(list(set(r["table"] for r in aggregated_reads) | set(w["table"] for w in aggregated_writes)))

    all_ev_classes = set(r["evidence_class"] for r in aggregated_reads) | set(w["evidence_class"] for w in aggregated_writes)
    if "UNKNOWN" in all_ev_classes:
        overall_ev = "UNKNOWN"
    elif "POSSIBLE" in all_ev_classes:
        overall_ev = "POSSIBLE"
    elif all_ev_classes:
        overall_ev = "AST_VERIFIED"
    else:
        overall_ev = "STATIC_VERIFIED"

    return {
        "status": "ok",
        "route": route_info.get("route", clean_target),
        "method": route_info.get("method", req_method or "ANY"),
        "handler": seeds[0][0] if seeds else clean_target,
        "db_reads": aggregated_reads,
        "db_writes": aggregated_writes,
        "tables": all_tables,
        "evidence_class": overall_ev,
    }

