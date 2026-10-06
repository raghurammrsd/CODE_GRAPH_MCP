"""Pydantic, Django Form, and DB Schema Drift Detection Engine (`src/codegraph/database/schema_drift.py`).

Provides deterministic, AST-verified cross-layer drift detection:
- Route input schemas (Pydantic BaseModel, Django Form/ModelForm, DRF Serializer, dataclasses)
  versus destination database table columns.
- Drift categories:
  1. MISSING_REQUIRED_COLUMN: DB column is NOT NULL with no default, but route schema lacks the field.
  2. NULLABILITY_MISMATCH: Route schema permits None/null, but DB column rejects NULLs.
  3. TYPE_INCOMPATIBILITY: Route schema type conflicts with DB column type (e.g., int vs DATE/TIMESTAMP).
  4. LENGTH_CONSTRAINT_DRIFT: Route schema allows max_length > DB column length limit.
  5. UNUSED_SCHEMA_FIELD: Route schema accepts a field that is never persisted to the table.
"""
from __future__ import annotations

import ast
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.database.interrogation import get_route_db_lineage


class DriftSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class DriftType(StrEnum):
    MISSING_REQUIRED_COLUMN = "MISSING_REQUIRED_COLUMN"
    NULLABILITY_MISMATCH = "NULLABILITY_MISMATCH"
    TYPE_INCOMPATIBILITY = "TYPE_INCOMPATIBILITY"
    LENGTH_CONSTRAINT_DRIFT = "LENGTH_CONSTRAINT_DRIFT"
    UNUSED_SCHEMA_FIELD = "UNUSED_SCHEMA_FIELD"
    RUNTIME_MISSING_REQUIRED_COLUMN = "RUNTIME_MISSING_REQUIRED_COLUMN"
    RUNTIME_UNKNOWN_COLUMN_WRITTEN = "RUNTIME_UNKNOWN_COLUMN_WRITTEN"
    STATIC_RUNTIME_DIVERGENCE = "STATIC_RUNTIME_DIVERGENCE"


@dataclass(frozen=True)
class SchemaFieldSpec:
    name: str
    type_name: str
    nullable: bool
    required: bool
    max_length: int | None = None
    default_repr: str | None = None
    file_path: str = ""
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchemaDriftIssue:
    drift_type: str
    field_name: str
    column_name: str | None
    severity: str
    message: str
    schema_field: dict[str, Any] | None
    db_column: dict[str, Any] | None
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AST Extraction for Pydantic / dataclass / Form Schemas
# ---------------------------------------------------------------------------

_IGNORED_AUTO_COLUMNS = frozenset({"id", "created_at", "updated_at", "created_on", "updated_on", "deleted_at"})
_IGNORED_SCHEMA_FIELDS = frozenset({"csrf_token", "csrfmiddlewaretoken", "captcha"})


def _unparse_ast(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node).strip()
    except Exception:
        return ""


def _extract_type_info(annotation_node: ast.AST | None) -> tuple[str, bool]:
    """Return (base_type_name, is_nullable)."""
    if annotation_node is None:
        return "Any", True

    raw_str = _unparse_ast(annotation_node)

    # Check for Optional[...] or None in Union
    is_nullable = False
    if "None" in raw_str or "Optional" in raw_str:
        is_nullable = True

    # Normalize base type
    base = raw_str.replace("Optional[", "").replace("]", "")
    parts = [p.strip() for p in base.split("|") if p.strip() and p.strip() != "None"]
    base_clean = parts[0] if parts else "Any"

    # Normalize common wrappers like Annotated[str, Field(...)]
    if base_clean.startswith("Annotated["):
        inner = base_clean[len("Annotated[") : -1]
        base_clean = inner.split(",")[0].strip()

    return base_clean, is_nullable


def _parse_field_call(call_node: ast.Call) -> tuple[bool, bool, int | None, str | None]:
    """Parse a Field(...) or Form field call for (required, nullable, max_length, default_repr)."""
    required = True
    nullable = False
    max_length: int | None = None
    default_repr: str | None = None

    # Positional args (e.g. Field(..., max_length=50) or Field(None))
    if call_node.args:
        first_arg = call_node.args[0]
        arg_str = _unparse_ast(first_arg)
        if arg_str == "...":
            required = True
        elif arg_str == "None":
            required = False
            nullable = True
            default_repr = "None"
        else:
            required = False
            default_repr = arg_str

    for kw in call_node.keywords:
        kw_name = kw.arg
        kw_val = _unparse_ast(kw.value)
        if kw_name == "default":
            if kw_val == "...":
                required = True
            elif kw_val == "None":
                required = False
                nullable = True
                default_repr = "None"
            else:
                required = False
                default_repr = kw_val
        elif kw_name == "default_factory":
            required = False
            default_repr = f"{kw_val}()"
        elif kw_name == "max_length":
            try:
                max_length = int(kw_val)
            except ValueError:
                pass
        elif kw_name == "required":
            if kw_val in ("False", "0"):
                required = False
                nullable = True
            elif kw_val in ("True", "1"):
                required = True

    return required, nullable, max_length, default_repr


def extract_schema_fields_from_class_node(
    class_node: ast.ClassDef,
    file_path: str,
) -> list[SchemaFieldSpec]:
    """Extract fields from a Pydantic BaseModel, dataclass, or Django Form AST node."""
    fields: list[SchemaFieldSpec] = []

    for stmt in class_node.body:
        # 1. Annotated assignments: field: type [= default]
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            f_name = stmt.target.id
            if f_name.startswith("_"):
                continue

            base_type, is_nullable = _extract_type_info(stmt.annotation)
            required = True
            max_length: int | None = None
            default_repr: str | None = None

            if stmt.value is not None:
                val_str = _unparse_ast(stmt.value)
                if isinstance(stmt.value, ast.Call):
                    # Check for Field(...) or forms.CharField(...)
                    call_func_name = _unparse_ast(stmt.value.func)
                    if "Field" in call_func_name or "forms." in call_func_name or "serializers." in call_func_name:
                        req, null, m_len, d_rep = _parse_field_call(stmt.value)
                        required = req
                        if null:
                            is_nullable = True
                        if m_len is not None:
                            max_length = m_len
                        default_repr = d_rep
                    else:
                        required = False
                        default_repr = val_str
                elif val_str == "...":
                    required = True
                elif val_str == "None":
                    required = False
                    is_nullable = True
                    default_repr = "None"
                else:
                    required = False
                    default_repr = val_str

            fields.append(
                SchemaFieldSpec(
                    name=f_name,
                    type_name=base_type,
                    nullable=is_nullable,
                    required=required,
                    max_length=max_length,
                    default_repr=default_repr,
                    file_path=file_path,
                    line=stmt.lineno,
                )
            )

        # 2. Assign statements (e.g. Django forms / DRF serializers: name = forms.CharField(...))
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            f_name = stmt.targets[0].id
            if f_name.startswith("_"):
                continue

            if isinstance(stmt.value, ast.Call):
                func_name = _unparse_ast(stmt.value.func)
                # Map Django / DRF fields to types
                inferred_type = "str"
                if "Integer" in func_name or "BigInteger" in func_name:
                    inferred_type = "int"
                elif "Float" in func_name or "Decimal" in func_name:
                    inferred_type = "float"
                elif "Boolean" in func_name:
                    inferred_type = "bool"
                elif "Date" in func_name:
                    inferred_type = "date"
                elif "Time" in func_name:
                    inferred_type = "datetime"
                elif "JSON" in func_name:
                    inferred_type = "dict"
                elif "UUID" in func_name:
                    inferred_type = "UUID"

                req, null, m_len, d_rep = _parse_field_call(stmt.value)
                fields.append(
                    SchemaFieldSpec(
                        name=f_name,
                        type_name=inferred_type,
                        nullable=null,
                        required=req,
                        max_length=m_len,
                        default_repr=d_rep,
                        file_path=file_path,
                        line=stmt.lineno,
                    )
                )

    return fields


def extract_schema_fields_from_file(
    file_path: Path,
    class_name: str,
) -> list[SchemaFieldSpec]:
    """Parse file_path and extract SchemaFieldSpecs for class_name."""
    if not file_path.exists():
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(file_path))
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return extract_schema_fields_from_class_node(node, str(file_path))

    return []


def extract_dynamic_request_fields(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
) -> list[SchemaFieldSpec]:
    """Extract dynamic form/json/query parameters accessed on Flask/FastAPI/Django request objects."""
    fields: dict[str, SchemaFieldSpec] = {}

    for node in ast.walk(func_node):
        # 1. request.form.get("key") or request.json.get("key") or request.args.get("key")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            base = node.func.value
            if isinstance(base, ast.Attribute) and base.attr in ("form", "args", "json", "values", "GET", "POST"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    f_name = node.args[0].value
                    has_default = len(node.args) > 1 or any(kw.arg == "default" for kw in node.keywords)
                    if f_name not in fields:
                        fields[f_name] = SchemaFieldSpec(
                            name=f_name,
                            type_name="Any",
                            nullable=True,
                            required=not has_default,
                            default_repr="None" if not has_default else "...",
                            file_path=file_path,
                            line=node.lineno,
                        )
            # Also handle request.get_json().get("name")
            elif isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute) and base.func.attr == "get_json":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    f_name = node.args[0].value
                    if f_name not in fields:
                        fields[f_name] = SchemaFieldSpec(
                            name=f_name,
                            type_name="Any",
                            nullable=True,
                            required=False,
                            file_path=file_path,
                            line=node.lineno,
                        )
        # 2. request.form["key"] or request.json["key"]
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr in ("form", "args", "json", "values", "GET", "POST"):
            slice_node = node.slice
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                f_name = slice_node.value
                fields[f_name] = SchemaFieldSpec(
                    name=f_name,
                    type_name="Any",
                    nullable=False,
                    required=True,
                    file_path=file_path,
                    line=node.lineno,
                )

    return list(fields.values())


def resolve_handler_input_schema(
    con: sqlite3.Connection,
    repo_path: Path,
    handler_symbol_or_path: str,
) -> tuple[str, list[SchemaFieldSpec]] | None:
    """Find the route handler AST, discover parameter type annotations, and extract the input schema."""
    # Look up handler in symbols table
    sym_row = con.execute(
        "SELECT name, path, start_line, end_line, signature FROM symbols "
        "WHERE (canonical_id = ? OR qualified_name = ? OR name = ?) AND kind in ('function', 'method') LIMIT 1",
        (handler_symbol_or_path, handler_symbol_or_path, handler_symbol_or_path),
    ).fetchone()

    if not sym_row:
        # Try finding handler via framework_routes
        rt_row = con.execute(
            "SELECT handler_name, file_path, line FROM framework_routes "
            "WHERE (handler_name = ? OR handler_canonical_id = ? OR route_path = ?) LIMIT 1",
            (handler_symbol_or_path, handler_symbol_or_path, handler_symbol_or_path),
        ).fetchone()
        if rt_row:
            h_path = repo_path / str(rt_row[1])
            h_name = str(rt_row[0])
        else:
            return None
    else:
        h_path = repo_path / str(sym_row["path"])
        h_name = str(sym_row["name"])

    if not h_path.exists():
        return None

    try:
        source = h_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(h_path))
    except Exception:
        return None

    handler_fn: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == h_name:
            handler_fn = node
            break

    if not handler_fn:
        return None

    # Inspect function parameters for schema types
    # Exclude request, db, session, self, cls
    excluded_params = {"request", "db", "session", "self", "cls", "background_tasks", "response"}
    for arg in handler_fn.args.args:
        if arg.arg in excluded_params:
            continue
        if arg.annotation:
            ann_str = _unparse_ast(arg.annotation)
            # Remove Optional / Union wrappers
            schema_type = ann_str.replace("Optional[", "").replace("]", "").split("|")[0].strip()
            # If schema_type is a defined class in this file or imported
            # 1. Check current file for class definition
            for c_node in ast.walk(tree):
                if isinstance(c_node, ast.ClassDef) and c_node.name == schema_type:
                    specs = extract_schema_fields_from_class_node(c_node, str(h_path))
                    if specs:
                        return schema_type, specs

            # 2. Direct lookup in symbols table for ClassDef
            cls_row = con.execute(
                "SELECT path FROM symbols WHERE name = ? AND kind = 'class' LIMIT 1",
                (schema_type,),
            ).fetchone()
            if cls_row:
                c_path = repo_path / str(cls_row[0])
                specs = extract_schema_fields_from_file(c_path, schema_type)
                if specs:
                    return schema_type, specs

            # 3. Check imports table in SQLite
            try:
                imp_rows = con.execute(
                    "SELECT module FROM imports WHERE source_path = ? AND (module LIKE ? OR module = ?)",
                    (str(h_path.relative_to(repo_path)), f"%{schema_type}%", schema_type),
                ).fetchall()
                for imp in imp_rows:
                    mod_str = str(imp[0])
                    pot_rel = mod_str.replace(".", "/") + ".py"
                    pot_path = repo_path / pot_rel
                    if pot_path.exists():
                        specs = extract_schema_fields_from_file(pot_path, schema_type)
                        if specs:
                            return schema_type, specs
            except sqlite3.OperationalError:
                pass

    # 4. Fallback: Dynamic payload extraction in handler body (Flask request.form / request.json / request.args)
    dynamic_specs = extract_dynamic_request_fields(handler_fn, str(h_path))
    if dynamic_specs:
        return f"{h_name}:DynamicPayload", dynamic_specs

    return None


# ---------------------------------------------------------------------------
# Type Compatibility Matrix
# ---------------------------------------------------------------------------

_COMPATIBLE_TYPES: dict[str, set[str]] = {
    "int": {"integer", "int", "bigint", "smallint", "serial", "bigserial", "tinyint", "integerfield"},
    "str": {"varchar", "text", "char", "character varying", "string", "citext", "charfield", "emailfield"},
    "float": {"float", "double", "real", "numeric", "decimal", "double precision", "floatfield", "decimalfield"},
    "bool": {"boolean", "bool", "tinyint", "booleanfield"},
    "date": {"date", "datefield"},
    "datetime": {"timestamp", "timestamptz", "datetime", "timestamp with time zone", "timestamp without time zone", "datetimefield"},
    "dict": {"json", "jsonb", "jsonfield"},
    "list": {"json", "jsonb", "array"},
    "UUID": {"uuid", "varchar", "char", "text", "uuidfield"},
    "Any": set(),  # Compatible with all
}


def _are_types_compatible(schema_type: str, db_col_type: str) -> bool:
    s_norm = schema_type.lower()
    d_norm = db_col_type.lower().split("(")[0].strip()

    if s_norm in ("any", "object") or d_norm in ("any", "unknown", ""):
        return True

    # Normalize schema type name
    target_key = "str"
    if s_norm in ("int", "integer"):
        target_key = "int"
    elif s_norm in ("float", "decimal"):
        target_key = "float"
    elif s_norm in ("bool", "boolean"):
        target_key = "bool"
    elif s_norm in ("datetime",):
        target_key = "datetime"
    elif s_norm in ("date",):
        target_key = "date"
    elif s_norm in ("dict", "mapping"):
        target_key = "dict"
    elif s_norm in ("list", "sequence"):
        target_key = "list"
    elif s_norm in ("uuid",):
        target_key = "UUID"

    allowed = _COMPATIBLE_TYPES.get(target_key, set())
    if not allowed:
        return True

    return any(a in d_norm for a in allowed)


def _extract_db_varchar_length(data_type: str) -> int | None:
    m = re.search(r"(?:varchar|char|character varying|string|charfield)\s*\(\s*(\d+)\s*\)", data_type, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Schema Drift Interrogation Core
# ---------------------------------------------------------------------------


def detect_schema_drift(
    con: sqlite3.Connection,
    repo_path: Path,
    *,
    route_or_handler: str,
    target_table: str | None = None,
    schema_name: str | None = None,
) -> dict[str, Any]:
    """Detect schema validation drift between a route's input schema and the destination database table.

    Deterministic verification of:
    - MISSING_REQUIRED_COLUMN
    - NULLABILITY_MISMATCH
    - TYPE_INCOMPATIBILITY
    - LENGTH_CONSTRAINT_DRIFT
    - UNUSED_SCHEMA_FIELD
    """
    # 1. Determine destination table via get_route_db_lineage if not explicitly provided
    resolved_table = target_table
    lineage = None
    if not resolved_table:
        lineage = get_route_db_lineage(con, route_or_handler)
        writes = lineage.get("db_writes", [])
        if writes:
            resolved_table = writes[0].get("table")
        elif lineage.get("tables"):
            resolved_table = lineage["tables"][0]

    # 1b. Fallback: check runtime observations & edges if static lineage did not resolve table
    if not resolved_table:
        rt_row = con.execute(
            "SELECT db_table FROM runtime_observations "
            "WHERE (route_path = ? OR handler_symbol = ? OR caller_symbol = ? OR route_path LIKE ? OR handler_symbol LIKE ?) "
            "AND db_table != '' "
            "ORDER BY runtime_generation DESC, rowid DESC LIMIT 1",
            (route_or_handler, route_or_handler, route_or_handler, f"%{route_or_handler}%", f"%{route_or_handler}%"),
        ).fetchone()
        if rt_row and rt_row[0]:
            resolved_table = str(rt_row[0])
        else:
            edge_row = con.execute(
                "SELECT target FROM runtime_edges "
                "WHERE (source = ? OR source LIKE ?) AND relationship IN ('WRITES_TABLE', 'READS_TABLE') "
                "ORDER BY observation_count DESC LIMIT 1",
                (route_or_handler, f"%{route_or_handler}%"),
            ).fetchone()
            if edge_row and edge_row[0]:
                resolved_table = str(edge_row[0]).split(".")[-1]

    if not resolved_table:
        return {
            "status": "error",
            "route_or_handler": route_or_handler,
            "drift_count": 0,
            "issues": [],
            "error": "No destination database table found for route or handler.",
        }

    # 2. Extract input schema fields
    fields: list[SchemaFieldSpec] = []
    resolved_schema_name = schema_name
    schema_mode = "STATIC_TYPED"

    if resolved_schema_name:
        cls_row = con.execute(
            "SELECT path FROM symbols WHERE name = ? AND kind = 'class' LIMIT 1",
            (resolved_schema_name,),
        ).fetchone()
        if cls_row:
            fields = extract_schema_fields_from_file(repo_path / str(cls_row[0]), resolved_schema_name)
    else:
        resolved = resolve_handler_input_schema(con, repo_path, route_or_handler)
        if resolved:
            resolved_schema_name, fields = resolved
            if ":DynamicPayload" in resolved_schema_name:
                schema_mode = "DYNAMIC_AST"

    # Query runtime SQL observations for this route/handler and target table
    rt_sql_rows = con.execute(
        "SELECT db_operation, db_table, db_columns_json, normalized_sql, duration_ms, event_id "
        "FROM runtime_observations "
        "WHERE (route_path = ? OR handler_symbol = ? OR caller_symbol = ? OR route_path LIKE ? OR handler_symbol LIKE ?) "
        "AND (db_table = ? OR db_table LIKE ?) AND normalized_sql != '' "
        "ORDER BY runtime_generation DESC, rowid DESC",
        (route_or_handler, route_or_handler, route_or_handler, f"%{route_or_handler}%", f"%{route_or_handler}%", resolved_table, f"%{resolved_table}%"),
    ).fetchall()

    # If static/dynamic fields could not be found, attempt to build runtime schema fields from observed SQL
    if not fields or not resolved_schema_name:
        if rt_sql_rows:
            seen_rt_cols: set[str] = set()
            for r in rt_sql_rows:
                try:
                    cols_list = json.loads(r[2] or "[]")
                except Exception:
                    cols_list = []
                for c in cols_list:
                    if c and c.lower() not in seen_rt_cols:
                        seen_rt_cols.add(c.lower())
                        fields.append(
                            SchemaFieldSpec(
                                name=c,
                                type_name="Any",
                                nullable=False,
                                required=True,
                                default_repr="<runtime_sql>",
                                file_path="[RUNTIME_OBSERVED]",
                                line=0,
                            )
                        )
            if fields:
                resolved_schema_name = f"RuntimeSQL:{resolved_table}"
                schema_mode = "RUNTIME_OBSERVED"

    if not fields or not resolved_schema_name:
        return {
            "status": "error",
            "route_or_handler": route_or_handler,
            "target_table": resolved_table,
            "drift_count": 0,
            "issues": [],
            "error": "Could not locate static schema class, dynamic request fields, or runtime SQL traces for handler.",
        }

    # 3. Retrieve database table columns from db_entities table
    col_rows = con.execute(
        "SELECT column_name, data_type, nullable, default_value, is_primary_key, is_foreign_key, file_path, start_line, evidence "
        "FROM db_entities WHERE table_name = ? AND (LOWER(kind) = 'column' OR kind LIKE '%COLUMN%') ORDER BY column_name ASC",
        (resolved_table,),
    ).fetchall()

    if not col_rows:
        return {
            "status": "error",
            "route_or_handler": route_or_handler,
            "target_table": resolved_table,
            "schema_name": resolved_schema_name,
            "drift_count": 0,
            "issues": [],
            "error": f"No indexed columns found for destination table '{resolved_table}'.",
        }

    cols_by_name: dict[str, dict[str, Any]] = {}
    for r in col_rows:
        c_name = str(r[0]).lower()
        cols_by_name[c_name] = {
            "column_name": str(r[0]),
            "data_type": str(r[1] or ""),
            "nullable": bool(r[2]),
            "default_value": r[3],
            "is_primary_key": bool(r[4]),
            "is_foreign_key": bool(r[5]),
            "file_path": str(r[6]),
            "line": int(r[7]),
            "evidence": str(r[8]),
        }

    issues: list[SchemaDriftIssue] = []
    fields_by_name = {f.name.lower(): f for f in fields}

    # 4. Check for MISSING_REQUIRED_COLUMN in schema
    for c_lower, c_spec in cols_by_name.items():
        if c_lower in _IGNORED_AUTO_COLUMNS or c_spec["is_primary_key"]:
            continue
        # Column is required if nullable is False and no default is configured
        col_required = (not c_spec["nullable"]) and (c_spec["default_value"] is None)
        if col_required and c_lower not in fields_by_name:
            issues.append(
                SchemaDriftIssue(
                    drift_type=DriftType.MISSING_REQUIRED_COLUMN.value,
                    field_name=c_spec["column_name"],
                    column_name=c_spec["column_name"],
                    severity=DriftSeverity.CRITICAL.value,
                    message=(
                        f"Database column '{resolved_table}.{c_spec['column_name']}' is NOT NULL with no default, "
                        f"but input schema '{resolved_schema_name}' does not define this field."
                    ),
                    schema_field=None,
                    db_column=c_spec,
                    evidence=c_spec["evidence"],
                )
            )

    # 5. Check schema fields against matched columns
    for f_lower, f_spec in fields_by_name.items():
        if f_lower in _IGNORED_SCHEMA_FIELDS:
            continue

        matched_col = cols_by_name.get(f_lower)
        if not matched_col:
            issues.append(
                SchemaDriftIssue(
                    drift_type=DriftType.UNUSED_SCHEMA_FIELD.value,
                    field_name=f_spec.name,
                    column_name=None,
                    severity=DriftSeverity.INFO.value,
                    message=(
                        f"Schema field '{resolved_schema_name}.{f_spec.name}' is accepted by route, "
                        f"but no matching column exists in destination table '{resolved_table}'."
                    ),
                    schema_field=f_spec.as_dict(),
                    db_column=None,
                    evidence=f"{f_spec.file_path}:{f_spec.line}",
                )
            )
            continue

        # NULLABILITY_MISMATCH: schema is nullable/optional, but DB rejects NULLs without default
        db_rejects_null = (not matched_col["nullable"]) and (matched_col["default_value"] is None)
        if f_spec.nullable and db_rejects_null:
            issues.append(
                SchemaDriftIssue(
                    drift_type=DriftType.NULLABILITY_MISMATCH.value,
                    field_name=f_spec.name,
                    column_name=matched_col["column_name"],
                    severity=DriftSeverity.CRITICAL.value,
                    message=(
                        f"Schema field '{f_spec.name}' allows None/null, but DB column '{matched_col['column_name']}' "
                        f"is NOT NULL with no default value."
                    ),
                    schema_field=f_spec.as_dict(),
                    db_column=matched_col,
                    evidence=f"Schema: {f_spec.file_path}:{f_spec.line} | DB: {matched_col['evidence']}",
                )
            )

        # TYPE_INCOMPATIBILITY
        if not _are_types_compatible(f_spec.type_name, matched_col["data_type"]):
            issues.append(
                SchemaDriftIssue(
                    drift_type=DriftType.TYPE_INCOMPATIBILITY.value,
                    field_name=f_spec.name,
                    column_name=matched_col["column_name"],
                    severity=DriftSeverity.CRITICAL.value,
                    message=(
                        f"Type mismatch: Schema field '{f_spec.name}' type '{f_spec.type_name}' "
                        f"is incompatible with database column type '{matched_col['data_type']}'."
                    ),
                    schema_field=f_spec.as_dict(),
                    db_column=matched_col,
                    evidence=f"Schema: {f_spec.type_name} | DB: {matched_col['data_type']}",
                )
            )

        # LENGTH_CONSTRAINT_DRIFT
        col_max_len = _extract_db_varchar_length(matched_col["data_type"])
        if col_max_len is not None and f_spec.max_length is not None and f_spec.max_length > col_max_len:
            issues.append(
                SchemaDriftIssue(
                    drift_type=DriftType.LENGTH_CONSTRAINT_DRIFT.value,
                    field_name=f_spec.name,
                    column_name=matched_col["column_name"],
                    severity=DriftSeverity.WARNING.value,
                    message=(
                        f"Length constraint drift: Schema allows max_length={f_spec.max_length}, "
                        f"but DB column '{matched_col['column_name']}' is restricted to {col_max_len} characters."
                    ),
                    schema_field=f_spec.as_dict(),
                    db_column=matched_col,
                    evidence=f"Schema max_length={f_spec.max_length} vs DB {matched_col['data_type']}",
                )
            )

    # 6. Reconcile runtime SQL execution against destination database table columns
    runtime_cols_written: set[str] = set()
    last_sql_sample = ""
    for r in rt_sql_rows:
        op = str(r[0] or "").upper()
        sql_txt = str(r[3] or "")
        if not last_sql_sample and sql_txt:
            last_sql_sample = sql_txt
        try:
            c_list = [str(x) for x in json.loads(r[2] or "[]")]
        except Exception:
            c_list = []
        for c in c_list:
            if c:
                runtime_cols_written.add(c.lower())

        # If operation is INSERT: check if any required NOT NULL column in DB was omitted
        if op == "INSERT" and c_list:
            inserted_lower = {c.lower() for c in c_list}
            for c_lower, c_spec in cols_by_name.items():
                if c_lower in _IGNORED_AUTO_COLUMNS or c_spec["is_primary_key"]:
                    continue
                col_required = (not c_spec["nullable"]) and (c_spec["default_value"] is None)
                if col_required and c_lower not in inserted_lower:
                    if not any(i.drift_type == DriftType.RUNTIME_MISSING_REQUIRED_COLUMN.value and i.column_name == c_spec["column_name"] for i in issues):
                        issues.append(
                            SchemaDriftIssue(
                                drift_type=DriftType.RUNTIME_MISSING_REQUIRED_COLUMN.value,
                                field_name=c_spec["column_name"],
                                column_name=c_spec["column_name"],
                                severity=DriftSeverity.CRITICAL.value,
                                message=(
                                    f"[RUNTIME_OBSERVED] Executed query '{sql_txt}' omitted required NOT NULL column "
                                    f"'{resolved_table}.{c_spec['column_name']}'."
                                ),
                                schema_field=None,
                                db_column=c_spec,
                                evidence=f"Runtime SQL: {sql_txt} | DB: {c_spec['evidence']}",
                            )
                        )

            # Check if query wrote to unknown column not in DB
            for written_c in c_list:
                if written_c.lower() not in cols_by_name:
                    if not any(i.drift_type == DriftType.RUNTIME_UNKNOWN_COLUMN_WRITTEN.value and i.field_name == written_c for i in issues):
                        issues.append(
                            SchemaDriftIssue(
                                drift_type=DriftType.RUNTIME_UNKNOWN_COLUMN_WRITTEN.value,
                                field_name=written_c,
                                column_name=None,
                                severity=DriftSeverity.CRITICAL.value,
                                message=(
                                    f"[RUNTIME_OBSERVED] Executed query '{sql_txt}' wrote to unknown column '{written_c}' "
                                    f"not present in destination table '{resolved_table}'."
                                ),
                                schema_field=None,
                                db_column=None,
                                evidence=f"Runtime SQL: {sql_txt}",
                            )
                        )

    # Deterministic sorting
    severity_order = {DriftSeverity.CRITICAL.value: 0, DriftSeverity.WARNING.value: 1, DriftSeverity.INFO.value: 2}
    sorted_issues = sorted(
        issues,
        key=lambda x: (severity_order.get(x.severity, 99), x.drift_type, x.field_name),
    )

    runtime_recon = {
        "is_observed": bool(rt_sql_rows),
        "observation_count": len(rt_sql_rows),
        "last_sql_sample": last_sql_sample if last_sql_sample else None,
        "runtime_columns_written": sorted(list(runtime_cols_written)),
        "status": "CONFIRMED_RUNTIME_PATH" if rt_sql_rows else "NOT_OBSERVED_AT_RUNTIME",
    }

    return {
        "status": "ok",
        "route_or_handler": route_or_handler,
        "target_table": resolved_table,
        "schema_name": resolved_schema_name,
        "schema_mode": schema_mode,
        "drift_count": len(sorted_issues),
        "critical_count": sum(1 for i in sorted_issues if i.severity == DriftSeverity.CRITICAL.value),
        "warning_count": sum(1 for i in sorted_issues if i.severity == DriftSeverity.WARNING.value),
        "info_count": sum(1 for i in sorted_issues if i.severity == DriftSeverity.INFO.value),
        "issues": [i.as_dict() for i in sorted_issues],
        "runtime_reconciliation": runtime_recon,
    }
