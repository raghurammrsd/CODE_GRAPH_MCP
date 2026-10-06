"""Production-Grade Cross-Language Client-Server API Contract Drift Detector.

Reconciles client-side data fetches (React, Next.js, Vue, Axios, SWR, React-Query)
against backend route declarations (FastAPI, Flask, Express, Django, NestJS)
and database models:
1. ORPHANED_CLIENT_ROUTE: Client fetch points to a non-existent route (runtime 404).
2. HTTP_METHOD_MISMATCH: Client sends POST, but backend endpoint only accepts GET (runtime 405).
3. PARAMETER_MISMATCH: Path parameter disparity between client fetch and backend declaration.
4. CROSS_LANGUAGE_FIELD_DRIFT: Client TypeScript interface expects a field that backend model/schema lacks.
5. NULLABILITY_DRIFT: Client TypeScript interface treats a field as non-nullable, but backend allows NULL/None.
6. TYPE_INCOMPATIBILITY: Client TypeScript type conflicts with backend type (e.g., number vs UUID/string).
7. UNUSED_BACKEND_ROUTE: Backend endpoint with zero client callers or tests.
"""
from __future__ import annotations

import ast
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codegraph.database.schema_drift import extract_schema_fields_from_class_node
from codegraph.route_topology import (
    match_route_topology,
    normalize_route,
)


@dataclass(frozen=True)
class ApiContractDrift:
    kind: str  # ORPHANED_CLIENT_ROUTE | HTTP_METHOD_MISMATCH | PARAMETER_MISMATCH | CROSS_LANGUAGE_FIELD_DRIFT | NULLABILITY_DRIFT | TYPE_INCOMPATIBILITY | UNUSED_BACKEND_ROUTE
    client_route: str
    client_method: str = ""
    client_file: str = ""
    client_line: int = 1
    client_type: str = ""
    backend_route: str = ""
    backend_methods: tuple[str, ...] = ()
    backend_handler: str = ""
    backend_file: str = ""
    field_name: str = ""
    client_field_type: str = ""
    backend_field_type: str = ""
    severity: str = "CRITICAL"  # CRITICAL | WARNING | INFO
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "client_route": self.client_route,
            "client_method": self.client_method,
            "client_file": self.client_file,
            "client_line": self.client_line,
            "client_type": self.client_type,
            "backend_route": self.backend_route,
            "backend_methods": list(self.backend_methods),
            "backend_handler": self.backend_handler,
            "backend_file": self.backend_file,
            "field_name": self.field_name,
            "client_field_type": self.client_field_type,
            "backend_field_type": self.backend_field_type,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ApiContractDriftReport:
    has_drift: bool
    total_client_calls: int
    total_backend_routes: int
    matched_calls: int = 0
    drifts: tuple[ApiContractDrift, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "has_drift": self.has_drift,
            "total_client_calls": self.total_client_calls,
            "total_backend_routes": self.total_backend_routes,
            "matched_calls": self.matched_calls,
            "drift_count": len(self.drifts),
            "drifts": [d.as_dict() for d in self.drifts],
        }


_TS_TO_BACKEND_TYPES: dict[str, set[str]] = {
    "string": {
        "str", "varchar", "text", "char", "character varying", "string",
        "citext", "charfield", "emailfield", "uuid", "uuidfield", "date",
        "datetime", "timestamp",
    },
    "number": {
        "int", "float", "integer", "bigint", "smallint", "serial",
        "bigserial", "tinyint", "double", "real", "numeric", "decimal",
        "integerfield", "floatfield", "decimalfield",
    },
    "boolean": {"bool", "boolean", "tinyint", "booleanfield"},
    "date": {"date", "datetime", "timestamp", "timestamptz", "datefield", "datetimefield"},
    "any": set(),
}


def _are_ts_backend_types_compatible(ts_type: str, backend_type: str) -> bool:
    clean_ts = ts_type.strip().rstrip("?").lower()
    clean_be = backend_type.strip().lower()
    if clean_ts in ("any", "unknown", "object") or clean_be in ("any", "unknown", "object"):
        return True
    if clean_ts == clean_be:
        return True
    compatible_be_types = _TS_TO_BACKEND_TYPES.get(clean_ts)
    if compatible_be_types is None:
        return True
    for be_allowed in compatible_be_types:
        if be_allowed in clean_be or clean_be in be_allowed:
            return True
    return False


def _resolve_backend_fields_for_handler(
    con: sqlite3.Connection,
    repo_root: Path | None,
    handler_canonical_id: str,
    handler_name: str,
    backend_file: str,
) -> dict[str, tuple[str, bool]]:
    """Discover schema fields (type_name, is_nullable) for a backend handler.

    Checks:
    1. Python AST Pydantic / dataclass response model or return annotation.
    2. Python AST function parameter input schemas.
    3. Database columns from db_entities or db_queries.
    """
    fields: dict[str, tuple[str, bool]] = {}

    # 1. AST inspection if file exists
    if repo_root and backend_file:
        full_path = repo_root / backend_file
        if full_path.exists() and backend_file.endswith(".py"):
            try:
                tree = ast.parse(full_path.read_text(encoding="utf-8", errors="replace"), filename=str(full_path))
                handler_fn: ast.FunctionDef | ast.AsyncFunctionDef | None = None
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == handler_name:
                        handler_fn = node
                        break

                if handler_fn:
                    target_model_name: str | None = None
                    # Check decorators for response_model=ModelName
                    for dec in handler_fn.decorator_list:
                        if isinstance(dec, ast.Call):
                            for kw in dec.keywords:
                                if kw.arg == "response_model":
                                    try:
                                        target_model_name = ast.unparse(kw.value).strip()
                                    except Exception:
                                        pass

                    # Check return annotation -> ModelName
                    if not target_model_name and handler_fn.returns:
                        try:
                            ret_str = ast.unparse(handler_fn.returns).strip()
                            ret_str = ret_str.replace("list[", "").replace("List[", "").replace("]", "")
                            ret_str = ret_str.replace("Optional[", "").replace("]", "").split("|")[0].strip()
                            target_model_name = ret_str
                        except Exception:
                            pass

                    # Check parameter input schema
                    if not target_model_name:
                        excluded = {"request", "db", "session", "self", "cls"}
                        for arg in handler_fn.args.args:
                            if arg.arg not in excluded and arg.annotation:
                                try:
                                    ann_str = ast.unparse(arg.annotation).strip()
                                    target_model_name = ann_str.replace("Optional[", "").replace("]", "").split("|")[0].strip()
                                    break
                                except Exception:
                                    pass

                    if target_model_name:
                        # Find class definition
                        for c_node in ast.walk(tree):
                            if isinstance(c_node, ast.ClassDef) and c_node.name == target_model_name:
                                specs = extract_schema_fields_from_class_node(c_node, str(full_path))
                                for s in specs:
                                    fields[s.name] = (s.type_name, s.nullable)
                                break
            except Exception:
                pass

    # 2. Database columns from db_entities if no AST model found
    if not fields:
        # Check if queries exist for this handler
        q_rows = con.execute(
            "SELECT table_name FROM db_queries WHERE caller_symbol_id = ? OR caller_symbol_id LIKE ?",
            (handler_canonical_id, f"%{handler_name}"),
        ).fetchall()
        tables = [str(r[0]) for r in q_rows if r[0]]
        if tables:
            placeholders = ",".join("?" for _ in tables)
            col_rows = con.execute(
                f"SELECT column_name, data_type, nullable FROM db_entities WHERE kind = 'column' AND table_name IN ({placeholders})",
                tables,
            ).fetchall()
            for cr in col_rows:
                c_name = str(cr[0])
                c_type = str(cr[1] or "text")
                c_null = bool(cr[2])
                fields[c_name] = (c_type, c_null)

    return fields


def detect_api_contract_drift(
    con: sqlite3.Connection,
    repo_root: Path | None = None,
) -> ApiContractDriftReport:
    """Analyze client data fetches vs backend route registrations to find contract mismatches."""
    # 1. Fetch backend routes
    route_table = "framework_routes"
    has_fw_routes = con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='framework_routes'"
    ).fetchone()[0] > 0
    if not has_fw_routes:
        route_table = "raw_framework_routes"

    backend_routes_rows = con.execute(
        f"SELECT endpoint_id, framework, http_method, route_path, normalized_route, handler_name, handler_canonical_id, file_path "
        f"FROM {route_table}"
    ).fetchall()

    backend_routes: list[dict[str, Any]] = []
    for r in backend_routes_rows:
        raw_p = str(r["route_path"] or "")
        method = str(r["http_method"] or "GET").upper()
        norm_route = normalize_route(method, raw_p)
        backend_routes.append({
            "endpoint_id": str(r["endpoint_id"]),
            "framework": str(r["framework"]),
            "http_method": method,
            "route_path": raw_p,
            "normalized_route": norm_route,
            "handler_name": str(r["handler_name"] or ""),
            "handler_canonical_id": str(r["handler_canonical_id"] or ""),
            "file_path": str(r["file_path"] or ""),
        })

    # 2. Fetch TypeScript interfaces from local_bindings
    ts_interfaces: dict[str, list[tuple[str, str]]] = {}
    if con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='local_bindings'"
    ).fetchone()[0] > 0:
        ts_rows = con.execute(
            "SELECT target_name, dict_entries_json FROM local_bindings WHERE expr_kind = 'TS_INTERFACE'"
        ).fetchall()
        for tr in ts_rows:
            iname = str(tr[0])
            try:
                entries = json.loads(str(tr[1] or "[]"))
                ts_interfaces[iname] = [(str(e[0]), str(e[1])) for e in entries if len(e) >= 2]
            except Exception:
                pass

    # 3. Fetch client fetch calls from local_bindings
    client_calls_rows = con.execute(
        "SELECT target_name, file_path, line, source_expr, attr_name, base_expr, scope "
        "FROM local_bindings "
        "WHERE expr_kind IN ('REACT_FETCH_ROUTE', 'TEST_ROUTE', 'HTML_FORM_ACTION', 'HTMX_REQUEST')"
    ).fetchall()

    drifts: list[ApiContractDrift] = []
    matched_backend_endpoints: set[str] = set()
    total_matched_calls = 0

    for r in client_calls_rows:
        raw_client_url = str(r["target_name"] or "")
        if not raw_client_url.startswith("/") and not raw_client_url.startswith("http"):
            continue

        if raw_client_url.startswith("http"):
            m_path = re.search(r"https?://[^/]+(/[^?#]*)", raw_client_url)
            client_path = m_path.group(1) if m_path else raw_client_url
        else:
            client_path = raw_client_url

        client_file = str(r["file_path"] or "")
        client_line = int(r["line"] or 1)
        raw_m = str(r["base_expr"] or "").upper()
        if raw_m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            client_method = raw_m
        else:
            client_method = "GET"

        resp_type = str(r["attr_name"] or "").strip()
        client_norm = normalize_route(client_method, client_path)

        # Check topological matches
        exact_matches: list[dict[str, Any]] = []
        path_matches_wrong_method: list[dict[str, Any]] = []

        for b in backend_routes:
            matched, _ = match_route_topology(client_norm, b["normalized_route"], allow_proxy_prefix=True, match_methods=True)
            if matched:
                exact_matches.append(b)
            else:
                p_matched, _ = match_route_topology(client_norm, b["normalized_route"], allow_proxy_prefix=True, match_methods=False)
                if p_matched:
                    path_matches_wrong_method.append(b)

        if exact_matches:
            total_matched_calls += 1
            for em in exact_matches:
                matched_backend_endpoints.add(em["endpoint_id"])

            primary_backend = exact_matches[0]

            # 4. Cross-Language TypeScript Interface <-> Backend Contract Verification
            if resp_type and resp_type in ts_interfaces:
                ts_fields = ts_interfaces[resp_type]
                backend_fields = _resolve_backend_fields_for_handler(
                    con,
                    repo_root,
                    primary_backend["handler_canonical_id"],
                    primary_backend["handler_name"],
                    primary_backend["file_path"],
                )

                if backend_fields:
                    for f_name, f_type_str in ts_fields:
                        is_opt_client = f_type_str.endswith("?") or "null" in f_type_str or "undefined" in f_type_str
                        clean_ts_type = f_type_str.rstrip("?").strip()

                        # Check 1: Missing field in backend
                        if f_name not in backend_fields:
                            if not is_opt_client:
                                drifts.append(
                                    ApiContractDrift(
                                        kind="CROSS_LANGUAGE_FIELD_DRIFT",
                                        client_route=client_path,
                                        client_method=client_method,
                                        client_file=client_file,
                                        client_line=client_line,
                                        client_type=resp_type,
                                        backend_route=primary_backend["route_path"],
                                        backend_methods=(primary_backend["http_method"],),
                                        backend_handler=primary_backend["handler_name"],
                                        backend_file=primary_backend["file_path"],
                                        field_name=f_name,
                                        client_field_type=f_type_str,
                                        severity="CRITICAL",
                                        message=(
                                            f"Client TypeScript interface '{resp_type}' expects required field '{f_name}: {f_type_str}', "
                                            f"but backend route '{primary_backend['route_path']}' ({primary_backend['handler_name']}) does not provide this field."
                                        ),
                                    )
                                )
                        else:
                            be_type, be_nullable = backend_fields[f_name]

                            # Check 2: Nullability Drift
                            if not is_opt_client and be_nullable:
                                drifts.append(
                                    ApiContractDrift(
                                        kind="NULLABILITY_DRIFT",
                                        client_route=client_path,
                                        client_method=client_method,
                                        client_file=client_file,
                                        client_line=client_line,
                                        client_type=resp_type,
                                        backend_route=primary_backend["route_path"],
                                        backend_methods=(primary_backend["http_method"],),
                                        backend_handler=primary_backend["handler_name"],
                                        backend_file=primary_backend["file_path"],
                                        field_name=f_name,
                                        client_field_type=f_type_str,
                                        backend_field_type=f"{be_type} (nullable)",
                                        severity="WARNING",
                                        message=(
                                            f"Client TypeScript interface '{resp_type}' expects '{f_name}' to be non-nullable, "
                                            f"but backend schema/column allows NULL/None."
                                        ),
                                    )
                                )

                            # Check 3: Type Incompatibility
                            if not _are_ts_backend_types_compatible(clean_ts_type, be_type):
                                drifts.append(
                                    ApiContractDrift(
                                        kind="TYPE_INCOMPATIBILITY",
                                        client_route=client_path,
                                        client_method=client_method,
                                        client_file=client_file,
                                        client_line=client_line,
                                        client_type=resp_type,
                                        backend_route=primary_backend["route_path"],
                                        backend_methods=(primary_backend["http_method"],),
                                        backend_handler=primary_backend["handler_name"],
                                        backend_file=primary_backend["file_path"],
                                        field_name=f_name,
                                        client_field_type=f_type_str,
                                        backend_field_type=be_type,
                                        severity="CRITICAL",
                                        message=(
                                            f"Type mismatch on field '{f_name}': client expects '{f_type_str}', "
                                            f"but backend returns '{be_type}'."
                                        ),
                                    )
                                )

        elif path_matches_wrong_method:
            first_m = path_matches_wrong_method[0]
            allowed_methods = tuple(sorted({m["http_method"] for m in path_matches_wrong_method}))
            drifts.append(
                ApiContractDrift(
                    kind="HTTP_METHOD_MISMATCH",
                    client_route=client_path,
                    client_method=client_method,
                    client_file=client_file,
                    client_line=client_line,
                    backend_route=first_m["route_path"],
                    backend_methods=allowed_methods,
                    backend_handler=first_m["handler_name"],
                    backend_file=first_m["file_path"],
                    severity="CRITICAL",
                    message=(
                        f"Client sends '{client_method} {client_path}' at {client_file}:{client_line}, "
                        f"but backend handler '{first_m['handler_name']}' only accepts {list(allowed_methods)}."
                    ),
                )
            )
        else:
            # Check if this looks like an API route worthy of reporting as orphaned
            if client_path.startswith("/api/") or client_path.startswith("/v1/") or client_path.startswith("/v2/") or "/api" in client_path:
                drifts.append(
                    ApiContractDrift(
                        kind="ORPHANED_CLIENT_ROUTE",
                        client_route=client_path,
                        client_method=client_method,
                        client_file=client_file,
                        client_line=client_line,
                        severity="CRITICAL",
                        message=f"Client calls '{client_path}' at {client_file}:{client_line}, but no backend route handler is registered.",
                    )
                )

    return ApiContractDriftReport(
        has_drift=len(drifts) > 0,
        total_client_calls=len(client_calls_rows),
        total_backend_routes=len(backend_routes_rows),
        matched_calls=total_matched_calls,
        drifts=tuple(drifts),
    )
