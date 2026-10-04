"""Deterministic Database, ORM, Query, and Migration Extractor (Phases 1-7).

Inspects Python, JS/TS, SQL, and Prisma files without executing repository code.
All extracted evidence and SQL strings pass through secret redaction before emission.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from codegraph.evidence_contract import PARSER_VERSION, RelationshipRecord
from codegraph.indexing.models import normalize_module
from codegraph.security.redaction import (
    detect_env_variable_reads,
    normalize_and_redact_sql,
    parse_safe_connection_metadata,
    redact_secrets,
)

from .models import (
    DatabaseEntity,
    DatabaseEntityKind,
    DatabaseQueryFact,
    MigrationFact,
    build_db_canonical_id,
    normalize_dialect,
    normalize_schema_name,
)


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _pluralize_table(snake_name: str) -> str:
    if not snake_name:
        return "unknown"
    if snake_name.endswith("y") and len(snake_name) > 1 and snake_name[-2] not in "aeiou":
        return snake_name[:-1] + "ies"
    if snake_name.endswith("s"):
        return snake_name
    return snake_name + "s"


@dataclass
class DatabaseExtractionResult:
    """Container for all database facts extracted from a single file or repository pass."""

    entities: list[DatabaseEntity] = field(default_factory=list)
    queries: list[DatabaseQueryFact] = field(default_factory=list)
    migrations: list[MigrationFact] = field(default_factory=list)
    edges: list[RelationshipRecord] = field(default_factory=list)
    detected_dialects: set[str] = field(default_factory=set)
    env_reads: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SQL Parsing Helpers (Deterministic, Non-Executing)
# ---------------------------------------------------------------------------

_SQL_KEYWORD_BLACKLIST: frozenset[str] = frozenset({
    "select",
    "from",
    "where",
    "join",
    "inner",
    "left",
    "right",
    "full",
    "outer",
    "cross",
    "on",
    "group",
    "order",
    "by",
    "having",
    "limit",
    "offset",
    "values",
    "set",
    "into",
    "as",
    "and",
    "or",
    "not",
    "null",
    "true",
    "false",
    "distinct",
    "case",
    "when",
    "then",
    "else",
    "end",
    "exists",
    "in",
    "is",
    "table",
    "if",
    "only",
    "returning",
    "dual",
})


def parse_sql_statement(sql: str) -> list[dict[str, Any]]:
    """Deterministically parse a static SQL string into operations, tables, and columns."""
    results: list[dict[str, Any]] = []
    if not sql or not sql.strip():
        return results

    # Strip SQL comments
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*[\s\S]*?\*/", " ", cleaned)
    norm_sql = normalize_and_redact_sql(cleaned)

    # Split multiple statements on ';' safely
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    for stmt in statements:
        stmt_collapse = re.sub(r"\s+", " ", stmt).strip()
        upper = stmt_collapse.upper()

        # 1. CREATE TABLE [IF NOT EXISTS] [schema.]table ( ... )
        m_create = re.match(
            r"(?i)^CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"`]+)\s*\(([\s\S]+)\)",
            stmt_collapse,
        )
        if m_create:
            raw_tbl = m_create.group(1).strip('"`')
            tbl_name = raw_tbl.split(".")[-1].lower()
            body = m_create.group(2)
            cols: list[dict[str, Any]] = []
            fks: list[dict[str, str]] = []
            for part in _split_sql_Parens(body):
                p_strip = part.strip()
                if not p_strip:
                    continue
                p_up = p_strip.upper()
                if p_up.startswith("FOREIGN KEY"):
                    fk_m = re.search(
                        r"(?i)FOREIGN\s+KEY\s*\(\s*([A-Za-z0-9_\"`]+)\s*\)\s*REFERENCES\s+([A-Za-z0-9_.\"`]+)\s*\(\s*([A-Za-z0-9_\"`]+)\s*\)",
                        p_strip,
                    )
                    if fk_m:
                        fks.append({
                            "column": fk_m.group(1).strip('"`').lower(),
                            "target_table": fk_m.group(2).strip('"`').split(".")[-1].lower(),
                            "target_column": fk_m.group(3).strip('"`').lower(),
                        })
                    continue
                if p_up.startswith(("PRIMARY KEY", "CONSTRAINT", "UNIQUE", "CHECK", "INDEX", "KEY")):
                    continue
                col_tokens = p_strip.split()
                if len(col_tokens) >= 2:
                    c_name = col_tokens[0].strip('"`').lower()
                    c_type = col_tokens[1].upper()
                    is_pk = "PRIMARY KEY" in p_up
                    is_uq = "UNIQUE" in p_up
                    nullable = "NOT NULL" not in p_up and not is_pk
                    inline_fk = re.search(
                        r"(?i)REFERENCES\s+([A-Za-z0-9_.\"`]+)\s*(?:\(\s*([A-Za-z0-9_\"`]+)\s*\))?",
                        p_strip,
                    )
                    if inline_fk:
                        fks.append({
                            "column": c_name,
                            "target_table": inline_fk.group(1).strip('"`').split(".")[-1].lower(),
                            "target_column": (inline_fk.group(2) or "id").strip('"`').lower(),
                        })
                    cols.append({
                        "name": c_name,
                        "data_type": c_type,
                        "is_primary_key": is_pk,
                        "is_unique": is_uq,
                        "nullable": nullable,
                    })
            results.append({
                "operation": "CREATE_TABLE",
                "relationship": "MIGRATES_TABLE",
                "tables": [tbl_name],
                "columns": [c["name"] for c in cols],
                "column_defs": cols,
                "foreign_keys": fks,
                "normalized_sql": norm_sql,
            })
            continue

        # 2. CREATE VIEW
        m_view = re.match(
            r"(?i)^CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"`]+)\s+AS\s+([\s\S]+)",
            stmt_collapse,
        )
        if m_view:
            view_name = m_view.group(1).strip('"`').split(".")[-1].lower()
            results.append({
                "operation": "CREATE_VIEW",
                "relationship": "DEFINES",
                "view_name": view_name,
                "tables": [view_name],
                "columns": [],
                "normalized_sql": norm_sql,
            })
            continue

        # 3. CREATE SEQUENCE
        m_seq = re.match(
            r"(?i)^CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"`]+)",
            stmt_collapse,
        )
        if m_seq:
            seq_name = m_seq.group(1).strip('"`').split(".")[-1].lower()
            results.append({
                "operation": "CREATE_SEQUENCE",
                "relationship": "DEFINES",
                "sequence_name": seq_name,
                "tables": [],
                "columns": [],
                "normalized_sql": norm_sql,
            })
            continue

        # 4. ALTER TABLE
        m_alter = re.match(
            r"(?i)^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_.\"`]+)\s+([\s\S]+)",
            stmt_collapse,
        )
        if m_alter:
            tbl_name = m_alter.group(1).strip('"`').split(".")[-1].lower()
            action = m_alter.group(2)
            added_cols: list[str] = []
            for m_add in re.finditer(r"(?i)ADD\s+(?:COLUMN\s+)?([A-Za-z0-9_\"`]+)", action):
                col = m_add.group(1).strip('"`').lower()
                if col not in ("constraint", "foreign", "primary", "unique", "check", "index"):
                    added_cols.append(col)
            results.append({
                "operation": "ALTER_TABLE",
                "relationship": "MIGRATES_TABLE",
                "tables": [tbl_name],
                "columns": added_cols,
                "normalized_sql": norm_sql,
            })
            continue

        # 5. INSERT INTO [schema.]table [(col1, col2)] VALUES ...
        m_ins = re.search(
            r"(?i)\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+([A-Za-z0-9_.\"`]+)\s*(?:\(\s*([^)]+)\s*\))?",
            stmt_collapse,
        )
        if m_ins:
            tbl_name = m_ins.group(1).strip('"`').split(".")[-1].lower()
            if tbl_name not in _SQL_KEYWORD_BLACKLIST:
                cols_raw = m_ins.group(2) or ""
                col_names = [
                    c.strip().strip('"`').lower()
                    for c in cols_raw.split(",")
                    if c.strip() and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c.strip().strip('"`'))
                ]
                results.append({
                    "operation": "INSERT",
                    "relationship": "WRITES_TABLE",
                    "tables": [tbl_name],
                    "columns": col_names,
                    "normalized_sql": norm_sql,
                })
                continue

        # 6. UPDATE [schema.]table SET col1 = ..., col2 = ... [WHERE ...]
        m_upd = re.search(
            r"(?i)\bUPDATE\s+([A-Za-z0-9_.\"`]+)\s+SET\s+([\s\S]+?)(?:\bWHERE\b|\bRETURNING\b|$)",
            stmt_collapse,
        )
        if m_upd:
            tbl_name = m_upd.group(1).strip('"`').split(".")[-1].lower()
            if tbl_name not in _SQL_KEYWORD_BLACKLIST:
                set_clause = m_upd.group(2)
                write_cols = [
                    m.group(1).strip('"`').lower()
                    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", set_clause)
                ]
                where_match = re.search(r"(?i)\bWHERE\s+([\s\S]+)$", stmt_collapse)
                read_cols: list[str] = []
                if where_match:
                    for wm in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|<|>|LIKE|IN|IS)", where_match.group(1)):
                        cname = wm.group(1).lower()
                        if cname not in _SQL_KEYWORD_BLACKLIST:
                            read_cols.append(cname)
                results.append({
                    "operation": "UPDATE",
                    "relationship": "WRITES_TABLE",
                    "tables": [tbl_name],
                    "columns": write_cols,
                    "read_columns": read_cols,
                    "normalized_sql": norm_sql,
                })
                continue

        # 7. DELETE FROM [schema.]table [WHERE ...]
        m_del = re.search(
            r"(?i)\bDELETE\s+FROM\s+([A-Za-z0-9_.\"`]+)",
            stmt_collapse,
        )
        if m_del:
            tbl_name = m_del.group(1).strip('"`').split(".")[-1].lower()
            if tbl_name not in _SQL_KEYWORD_BLACKLIST:
                results.append({
                    "operation": "DELETE",
                    "relationship": "WRITES_TABLE",
                    "tables": [tbl_name],
                    "columns": [],
                    "normalized_sql": norm_sql,
                })
                continue

        # 8. SELECT ... FROM table [JOIN table2 ...]
        if "SELECT " in upper and " FROM " in upper:
            tables_found: list[str] = []
            for tm in re.finditer(
                r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.]*)",
                stmt_collapse,
            ):
                t_cand = tm.group(1).split(".")[-1].lower()
                if t_cand not in _SQL_KEYWORD_BLACKLIST and t_cand not in tables_found:
                    tables_found.append(t_cand)
            if tables_found:
                sel_match = re.search(r"(?i)\bSELECT\s+(?:DISTINCT\s+)?([\s\S]+?)\s+\bFROM\b", stmt_collapse)
                sel_cols: list[str] = []
                if sel_match:
                    sel_part = sel_match.group(1).strip()
                    if sel_part != "*":
                        for item in sel_part.split(","):
                            tok = item.strip().split(" ")[0].split(".")[-1].strip('"`').lower()
                            if re.match(r"^[a-z_][a-z0-9_]*$", tok) and tok not in _SQL_KEYWORD_BLACKLIST:
                                sel_cols.append(tok)
                where_match = re.search(r"(?i)\bWHERE\s+([\s\S]+?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", stmt_collapse)
                if where_match:
                    for wm in re.finditer(r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|<|>|LIKE|IN|IS)", where_match.group(1)):
                        cname = wm.group(1).lower()
                        if cname not in _SQL_KEYWORD_BLACKLIST and cname not in sel_cols:
                            sel_cols.append(cname)
                results.append({
                    "operation": "SELECT",
                    "relationship": "READS_TABLE",
                    "tables": tables_found,
                    "columns": sel_cols,
                    "normalized_sql": norm_sql,
                })

    return results


def _split_sql_Parens(body: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


# ---------------------------------------------------------------------------
# Python AST Extractor for ORMs, Queries, and Migrations
# ---------------------------------------------------------------------------

_DJANGO_FIELD_TYPES: frozenset[str] = frozenset({
    "CharField",
    "TextField",
    "IntegerField",
    "BigIntegerField",
    "SmallIntegerField",
    "PositiveIntegerField",
    "FloatField",
    "DecimalField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "TimeField",
    "EmailField",
    "URLField",
    "UUIDField",
    "SlugField",
    "JSONField",
    "BinaryField",
    "FileField",
    "ImageField",
    "AutoField",
    "BigAutoField",
    "SmallAutoField",
    "ForeignKey",
    "OneToOneField",
    "ManyToManyField",
})


def _ast_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        return node.func.attr
    return ""


def _ast_const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ast_const_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _get_kwarg(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def detect_file_dialects(content: str, file_path: str) -> set[str]:
    """Detect database dialects referenced in a file from imports and connection URLs."""
    dialects: set[str] = set()
    lower = content.lower()
    if any(k in lower for k in ("psycopg", "asyncpg", "postgresql://", "postgres://", "django.db.backends.postgresql")):
        dialects.add("postgres")
    if any(k in lower for k in ("sqlite3", "aiosqlite", "sqlite://", "django.db.backends.sqlite3")):
        dialects.add("sqlite")
    if any(k in lower for k in ("pymysql", "mysqlclient", "mysql://", "mysql+pymysql://", "django.db.backends.mysql")):
        dialects.add("mysql")
    if any(k in lower for k in ("pymongo", "motor", "mongodb://", "mongodb+srv://")):
        dialects.add("mongodb")
    if file_path.endswith(".prisma"):
        for m in re.finditer(r'provider\s*=\s*"([^"]+)"', content):
            prov = m.group(1).lower()
            if prov in ("postgresql", "postgres", "sqlite", "mysql", "mongodb", "sqlserver"):
                dialects.add(normalize_dialect(prov))
    return dialects


_PYTHON_DB_TOKENS: tuple[str, ...] = (
    "execute",
    "fetch",
    ".raw(",
    "query",
    "select(",
    "insert(",
    "update(",
    "delete(",
    ".add(",
    ".add_all(",
    ".merge(",
    ".objects",
    "__tablename__",
    "db_table",
    "DeclarativeBase",
    "SQLModel",
    "Model",
    "Base",
    "AsyncAttrs",
    "table=",
    "Table(",
    "Sequence(",
    "create_engine",
    "alembic",
    "Migration",
)

_PYTHON_ORM_MODEL_TOKENS: tuple[str, ...] = (
    "__tablename__",
    "db_table",
    "DeclarativeBase",
    "SQLModel",
    "Model",
    "Base",
    "AsyncAttrs",
    "table=",
)

_PYTHON_QUERY_TOKENS: tuple[str, ...] = (
    "execute",
    "fetch",
    ".raw(",
    "query",
    "select(",
    "insert(",
    "update(",
    "delete(",
    ".add(",
    ".add_all(",
    ".merge(",
    ".objects",
)


def has_potential_orm_models(content: str, file_path: str, language: str = "python") -> bool:
    """Return True if a file may define ORMModel entities needed for Pass 1 cross-file mapping."""
    if not content:
        return False
    if file_path.endswith(".prisma") or language == "prisma":
        return "model " in content
    if file_path.endswith(".sql") or language == "sql":
        return False
    if language == "python" or file_path.endswith(".py"):
        return any(tok in content for tok in _PYTHON_ORM_MODEL_TOKENS)
    if language in ("javascript", "typescript") or file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
        return any(tok in content for tok in ("Entity", "define(", ".init(", "model(", "Schema("))
    return False


def has_potential_database_activity(content: str, file_path: str, language: str = "python") -> bool:
    """Return True if a file may contain DB entities, queries, migrations, or env variable reads."""
    if not content:
        return False
    if file_path.endswith((".sql", ".prisma")) or language in ("sql", "prisma"):
        return True
    if language == "python" or file_path.endswith(".py"):
        return (
            "getenv" in content
            or "environ" in content
            or any(tok in content for tok in _PYTHON_DB_TOKENS)
        )
    if language in ("javascript", "typescript") or file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
        return True
    return False


def extract_database_from_file(
    content: str,
    file_path: str,
    language: str = "python",
    repo_dialect: str = "UNKNOWN",
    known_model_tables: dict[str, str] | None = None,
    index_generation: int = 1,
    tree: ast.AST | None = None,
) -> DatabaseExtractionResult:
    """Extract database entities, ORM mappings, queries, migrations, and edges from a file."""
    res = DatabaseExtractionResult()
    if not content:
        return res

    module_name = normalize_module(file_path, language)
    file_dialects = detect_file_dialects(content, file_path)
    res.detected_dialects.update(file_dialects)

    effective_dialect = repo_dialect
    if effective_dialect == "UNKNOWN":
        if len(file_dialects) == 1:
            effective_dialect = next(iter(file_dialects))
        elif len(file_dialects) > 1:
            effective_dialect = "AMBIGUOUS"

    effective_schema = normalize_schema_name(None, effective_dialect)
    model_to_table: dict[str, str] = dict(known_model_tables or {})

    is_py = language == "python" or file_path.endswith(".py")
    has_py_env = is_py and ("getenv" in content or "environ" in content)
    has_py_db = is_py and any(tok in content for tok in _PYTHON_DB_TOKENS)
    if is_py and tree is None and (has_py_env or has_py_db):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None

    # Track environment variable reads safely
    env_reads = detect_env_variable_reads(content, file_path, module_name, tree=tree)
    res.env_reads.extend(env_reads)
    for er in env_reads:
        res.edges.append(
            RelationshipRecord(
                source=str(er["source"]),
                target=str(er["target"]),
                relationship="READS_ENV",
                evidence_class="AST_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=int(er["line"]),
                end_line=int(er["line"]),
                evidence=redact_secrets(str(er["evidence"])),
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    if file_path.endswith(".sql") or language == "sql":
        _extract_sql_file(content, file_path, effective_dialect, effective_schema, index_generation, res)
        return res

    if file_path.endswith(".prisma") or language == "prisma":
        _extract_prisma_schema(content, file_path, effective_dialect, effective_schema, index_generation, res)
        return res

    if language in ("javascript", "typescript") or file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
        _extract_js_ts_database(
            content,
            file_path,
            module_name,
            effective_dialect,
            effective_schema,
            model_to_table,
            index_generation,
            res,
        )
        return res

    if is_py and has_py_db:
        _extract_python_database(
            content,
            file_path,
            module_name,
            effective_dialect,
            effective_schema,
            model_to_table,
            index_generation,
            res,
            tree=tree,
        )

    return res


def _extract_python_database(
    content: str,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    index_generation: int,
    res: DatabaseExtractionResult,
    tree: ast.AST | None = None,
) -> None:
    if tree is None:
        if not any(tok in content for tok in _PYTHON_DB_TOKENS):
            return
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

    lines = content.splitlines()

    def _line_snippet(lineno: int) -> str:
        if 1 <= lineno <= len(lines):
            return redact_secrets(lines[lineno - 1].strip())
        return ""

    # Check if this is an Alembic or Django migration file
    is_alembic = ("from alembic import op" in content or "import alembic" in content or "op.create_table" in content)
    is_django_migration = ("migrations.Migration" in content and "operations" in content)

    if is_alembic and isinstance(tree, ast.Module):
        _extract_alembic_migration(tree, content, file_path, module_name, dialect, schema, index_generation, res)

    if is_django_migration and isinstance(tree, ast.Module):
        _extract_django_migration(tree, content, file_path, module_name, dialect, schema, index_generation, res)

    # First pass over module-level SQLAlchemy Core `Table("name", metadata, Column(...))`
    # and `Sequence("name")` and `create_engine(...)`
    for node in getattr(tree, "body", ()):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            cname = _ast_call_name(node.value)
            if cname in ("Table", "sa.Table", "db.Table") and node.value.args:
                tbl_name = _ast_const_str(node.value.args[0])
                if tbl_name:
                    tbl_clean = tbl_name.strip().lower()
                    tbl_cid = build_db_canonical_id(
                        DatabaseEntityKind.TABLE,
                        table=tbl_clean,
                        dialect=dialect,
                        schema=schema,
                    )
                    res.entities.append(
                        DatabaseEntity(
                            canonical_id=tbl_cid,
                            kind=DatabaseEntityKind.TABLE.value,
                            name=tbl_clean,
                            dialect=dialect,
                            schema_name=schema,
                            table_name=tbl_clean,
                            framework="sqlalchemy",
                            file_path=file_path,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            evidence=_line_snippet(node.lineno),
                            metadata={"association_table": True},
                        )
                    )
                    for arg in node.value.args[1:]:
                        if isinstance(arg, ast.Call) and _ast_call_name(arg).endswith("Column") and arg.args:
                            col_nm = _ast_const_str(arg.args[0])
                            if col_nm:
                                _record_sqlalchemy_column(
                                    col_nm,
                                    arg,
                                    tbl_clean,
                                    tbl_cid,
                                    None,
                                    "sqlalchemy",
                                    dialect,
                                    schema,
                                    file_path,
                                    _line_snippet(arg.lineno),
                                    index_generation,
                                    res,
                                )
            elif cname in ("Sequence", "sa.Sequence") and node.value.args:
                seq_nm = _ast_const_str(node.value.args[0])
                if seq_nm:
                    seq_cid = build_db_canonical_id(
                        DatabaseEntityKind.SEQUENCE,
                        name=seq_nm,
                        dialect=dialect,
                        schema=schema,
                    )
                    res.entities.append(
                        DatabaseEntity(
                            canonical_id=seq_cid,
                            kind=DatabaseEntityKind.SEQUENCE.value,
                            name=seq_nm,
                            dialect=dialect,
                            schema_name=schema,
                            framework="sqlalchemy",
                            file_path=file_path,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            evidence=_line_snippet(node.lineno),
                        )
                    )
            elif cname.endswith("create_engine") and node.value.args:
                url_str = _ast_const_str(node.value.args[0])
                if url_str:
                    meta = parse_safe_connection_metadata(url_str)
                    prov = normalize_dialect(meta.get("provider"))
                    if prov != "UNKNOWN":
                        res.detected_dialects.add(prov)
                        db_cid = build_db_canonical_id(
                            DatabaseEntityKind.DATABASE,
                            name=meta.get("database") or prov,
                            dialect=prov,
                            schema=schema,
                        )
                        res.entities.append(
                            DatabaseEntity(
                                canonical_id=db_cid,
                                kind=DatabaseEntityKind.DATABASE.value,
                                name=meta.get("database") or prov,
                                dialect=prov,
                                schema_name=schema,
                                framework="sqlalchemy",
                                file_path=file_path,
                                start_line=node.lineno,
                                end_line=getattr(node, "end_lineno", node.lineno),
                                evidence=_line_snippet(node.lineno),
                                metadata=meta,
                            )
                        )

    # Second pass: inspect ClassDefs for ORM models (SQLAlchemy, Flask-SQLAlchemy, SQLModel, Django ORM)
    for node in getattr(tree, "body", ()):
        if isinstance(node, ast.ClassDef):
            _extract_orm_class(
                node,
                file_path,
                module_name,
                dialect,
                schema,
                model_to_table,
                _line_snippet,
                index_generation,
                res,
            )

    # Third pass: inspect functions and methods for ORM & raw SQL queries
    if any(tok in content for tok in _PYTHON_QUERY_TOKENS):
        _extract_python_queries_in_scope(
            tree,
            file_path,
            module_name,
            dialect,
            schema,
            model_to_table,
            _line_snippet,
            index_generation,
            res,
        )


def _extract_orm_class(
    cls_node: ast.ClassDef,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    line_snippet: Any,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    base_names: list[str] = []
    for b in cls_node.bases:
        if isinstance(b, ast.Name):
            base_names.append(b.id)
        elif isinstance(b, ast.Attribute):
            if isinstance(b.value, ast.Name):
                base_names.append(f"{b.value.id}.{b.attr}")
            else:
                base_names.append(b.attr)

    is_sqlmodel_table = any(
        kw.arg == "table" and _ast_const_bool(kw.value) is True for kw in cls_node.keywords
    )

    framework = ""
    if any(b in ("db.Model", "FlaskModel") for b in base_names):
        framework = "flask_sqlalchemy"
    elif any(b in ("models.Model", "Model") for b in base_names) and not is_sqlmodel_table:
        # Distinguish Django models.Model vs SQLAlchemy Base
        if "models.Model" in base_names or any(
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and _ast_call_name(stmt.value).split(".")[-1] in _DJANGO_FIELD_TYPES
            for stmt in cls_node.body
        ):
            framework = "django_orm"
        elif "db.Model" in base_names:
            framework = "flask_sqlalchemy"
    if not framework:
        if "SQLModel" in base_names or is_sqlmodel_table:
            framework = "sqlmodel"
        elif any(b in ("Base", "DeclarativeBase", "AsyncAttrs") or b.endswith("Base") for b in base_names):
            framework = "sqlalchemy"

    # Also detect if class explicitly defines `__tablename__`
    explicit_tablename: str | None = None
    explicit_schema: str | None = None
    django_meta_table: str | None = None
    django_unique_together: list[tuple[str, ...]] = []
    table_args_nodes: list[ast.AST] = []

    for stmt in cls_node.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                    explicit_tablename = _ast_const_str(stmt.value)
                elif isinstance(tgt, ast.Name) and tgt.id == "__table_args__":
                    if isinstance(stmt.value, (ast.Tuple, ast.List)):
                        table_args_nodes.extend(stmt.value.elts)
                    elif isinstance(stmt.value, ast.Dict):
                        table_args_nodes.append(stmt.value)
        elif isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
            for mstmt in stmt.body:
                if isinstance(mstmt, ast.Assign):
                    for mtgt in mstmt.targets:
                        if isinstance(mtgt, ast.Name) and mtgt.id == "db_table":
                            django_meta_table = _ast_const_str(mstmt.value)
                        elif isinstance(mtgt, ast.Name) and mtgt.id == "unique_together":
                            if isinstance(mstmt.value, (ast.Tuple, ast.List)):
                                for elt in mstmt.value.elts:
                                    if isinstance(elt, (ast.Tuple, ast.List)):
                                        cols = tuple(
                                            s for e in elt.elts if (s := _ast_const_str(e))
                                        )
                                        if cols:
                                            django_unique_together.append(cols)

    if explicit_tablename and not framework:
        framework = "sqlalchemy"

    if not framework:
        return

    # Determine table name
    for tan in table_args_nodes:
        if isinstance(tan, ast.Dict):
            for k, v in zip(tan.keys, tan.values, strict=False):
                if _ast_const_str(k) == "schema":
                    explicit_schema = _ast_const_str(v)

    tbl_schema = normalize_schema_name(explicit_schema, dialect) if explicit_schema else schema
    if explicit_tablename:
        table_name = explicit_tablename.strip().lower()
    elif django_meta_table:
        table_name = django_meta_table.strip().lower()
    elif framework == "django_orm":
        app_prefix = module_name.split(".")[0].lower() if "." in module_name else "app"
        if app_prefix in ("models", "root", "src"):
            table_name = _pluralize_table(_camel_to_snake(cls_node.name))
        else:
            table_name = f"{app_prefix}_{cls_node.name.lower()}"
    else:
        table_name = _camel_to_snake(cls_node.name)

    model_canonical_id = f"{module_name}.{cls_node.name}"
    model_to_table[cls_node.name] = table_name
    model_to_table[model_canonical_id] = table_name

    table_cid = build_db_canonical_id(
        DatabaseEntityKind.TABLE,
        table=table_name,
        dialect=dialect,
        schema=tbl_schema,
    )

    ev_cls = "FRAMEWORK_VERIFIED"
    ev_line = line_snippet(cls_node.lineno)

    # Emit ORMModel entity and Table entity
    res.entities.append(
        DatabaseEntity(
            canonical_id=model_canonical_id,
            kind=DatabaseEntityKind.ORM_MODEL.value,
            name=cls_node.name,
            dialect=dialect,
            schema_name=tbl_schema,
            table_name=table_name,
            orm_model_id=model_canonical_id,
            framework=framework,
            file_path=file_path,
            start_line=cls_node.lineno,
            end_line=getattr(cls_node, "end_lineno", cls_node.lineno),
            evidence=ev_line,
            confidence="HIGH",
            evidence_class=ev_cls,
        )
    )
    res.entities.append(
        DatabaseEntity(
            canonical_id=table_cid,
            kind=DatabaseEntityKind.TABLE.value,
            name=table_name,
            dialect=dialect,
            schema_name=tbl_schema,
            table_name=table_name,
            orm_model_id=model_canonical_id,
            framework=framework,
            file_path=file_path,
            start_line=cls_node.lineno,
            end_line=getattr(cls_node, "end_lineno", cls_node.lineno),
            evidence=ev_line,
            confidence="HIGH",
            evidence_class=ev_cls,
        )
    )
    res.edges.append(
        RelationshipRecord(
            source=model_canonical_id,
            target=table_cid,
            relationship="MAPS_TO_TABLE",
            evidence_class=ev_cls,
            confidence="HIGH",
            file=file_path,
            start_line=cls_node.lineno,
            end_line=getattr(cls_node, "end_lineno", cls_node.lineno),
            evidence=ev_line,
            status="FACT",
            parser_version=PARSER_VERSION,
            index_generation=index_generation,
        )
    )

    # Parse __table_args__ constraints & indexes
    for tan in table_args_nodes:
        if isinstance(tan, ast.Call):
            tname = _ast_call_name(tan).split(".")[-1]
            if tname == "UniqueConstraint":
                uq_cols = [s for a in tan.args if (s := _ast_const_str(a))]
                uq_name = _ast_const_str(_get_kwarg(tan, "name")) or f"uq_{table_name}_{'_'.join(uq_cols)}"
                uq_cid = build_db_canonical_id(
                    DatabaseEntityKind.UNIQUE_CONSTRAINT,
                    table=table_name,
                    name=uq_name,
                    dialect=dialect,
                    schema=tbl_schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=uq_cid,
                        kind=DatabaseEntityKind.UNIQUE_CONSTRAINT.value,
                        name=uq_name,
                        dialect=dialect,
                        schema_name=tbl_schema,
                        table_name=table_name,
                        framework=framework,
                        file_path=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        metadata={"columns": uq_cols},
                    )
                )
                res.edges.append(
                    RelationshipRecord(
                        source=table_cid,
                        target=uq_cid,
                        relationship="HAS_UNIQUE_CONSTRAINT",
                        evidence_class="AST_VERIFIED",
                        confidence="HIGH",
                        file=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        status="FACT",
                        parser_version=PARSER_VERSION,
                        index_generation=index_generation,
                    )
                )
            elif tname == "CheckConstraint":
                ck_expr = _ast_const_str(tan.args[0]) if tan.args else ""
                ck_name = _ast_const_str(_get_kwarg(tan, "name")) or f"ck_{table_name}_{tan.lineno}"
                ck_cid = build_db_canonical_id(
                    DatabaseEntityKind.CHECK_CONSTRAINT,
                    table=table_name,
                    name=ck_name,
                    dialect=dialect,
                    schema=tbl_schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=ck_cid,
                        kind=DatabaseEntityKind.CHECK_CONSTRAINT.value,
                        name=ck_name,
                        dialect=dialect,
                        schema_name=tbl_schema,
                        table_name=table_name,
                        framework=framework,
                        file_path=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        metadata={"expression": redact_secrets(ck_expr or "")},
                    )
                )
                res.edges.append(
                    RelationshipRecord(
                        source=table_cid,
                        target=ck_cid,
                        relationship="HAS_CHECK_CONSTRAINT",
                        evidence_class="AST_VERIFIED",
                        confidence="HIGH",
                        file=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        status="FACT",
                        parser_version=PARSER_VERSION,
                        index_generation=index_generation,
                    )
                )
            elif tname == "Index":
                idx_name = _ast_const_str(tan.args[0]) if tan.args else f"ix_{table_name}_{tan.lineno}"
                idx_cols = [s for a in tan.args[1:] if (s := _ast_const_str(a))]
                idx_cid = build_db_canonical_id(
                    DatabaseEntityKind.INDEX,
                    table=table_name,
                    name=idx_name or f"ix_{table_name}",
                    dialect=dialect,
                    schema=tbl_schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=idx_cid,
                        kind=DatabaseEntityKind.INDEX.value,
                        name=idx_name or f"ix_{table_name}",
                        dialect=dialect,
                        schema_name=tbl_schema,
                        table_name=table_name,
                        framework=framework,
                        file_path=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        metadata={"columns": idx_cols},
                    )
                )
                res.edges.append(
                    RelationshipRecord(
                        source=table_cid,
                        target=idx_cid,
                        relationship="HAS_INDEX",
                        evidence_class="AST_VERIFIED",
                        confidence="HIGH",
                        file=file_path,
                        start_line=tan.lineno,
                        end_line=getattr(tan, "end_lineno", tan.lineno),
                        evidence=line_snippet(tan.lineno),
                        status="FACT",
                        parser_version=PARSER_VERSION,
                        index_generation=index_generation,
                    )
                )

    for uq_tuple in django_unique_together:
        uq_name = f"uq_{table_name}_{'_'.join(uq_tuple)}"
        uq_cid = build_db_canonical_id(
            DatabaseEntityKind.UNIQUE_CONSTRAINT,
            table=table_name,
            name=uq_name,
            dialect=dialect,
            schema=tbl_schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=uq_cid,
                kind=DatabaseEntityKind.UNIQUE_CONSTRAINT.value,
                name=uq_name,
                dialect=dialect,
                schema_name=tbl_schema,
                table_name=table_name,
                framework=framework,
                file_path=file_path,
                start_line=cls_node.lineno,
                end_line=cls_node.lineno,
                evidence=f"unique_together = {uq_tuple!r}",
                metadata={"columns": list(uq_tuple)},
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=table_cid,
                target=uq_cid,
                relationship="HAS_UNIQUE_CONSTRAINT",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=cls_node.lineno,
                end_line=cls_node.lineno,
                evidence=f"unique_together = {uq_tuple!r}",
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    # Inspect class attributes for columns, foreign keys, and relationships
    for stmt in cls_node.body:
        field_name: str | None = None
        call_node: ast.Call | None = None
        ann_type: str = ""

        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            field_name = stmt.targets[0].id
            if isinstance(stmt.value, ast.Call):
                call_node = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            field_name = stmt.target.id
            ann_type = ast.unparse(stmt.annotation) if hasattr(ast, "unparse") else ""
            if isinstance(stmt.value, ast.Call):
                call_node = stmt.value

        if not field_name or field_name.startswith("__"):
            continue

        if call_node is not None:
            cname = _ast_call_name(call_node)
            short_cname = cname.split(".")[-1]

            # 1. SQLAlchemy / Flask-SQLAlchemy / SQLModel Column / mapped_column / Field
            if short_cname in ("Column", "mapped_column", "Field"):
                _record_sqlalchemy_column(
                    field_name,
                    call_node,
                    table_name,
                    table_cid,
                    model_canonical_id,
                    framework,
                    dialect,
                    tbl_schema,
                    file_path,
                    line_snippet(stmt.lineno),
                    index_generation,
                    res,
                    ann_type=ann_type,
                )
            # 2. SQLAlchemy / Flask-SQLAlchemy / SQLModel relationship / Relationship
            elif short_cname in ("relationship", "Relationship"):
                target_model = _ast_const_str(call_node.args[0]) if call_node.args else None
                if not target_model and ann_type:
                    m_ann = re.search(r"\b([A-Z][A-Za-z0-9_]*)\b", ann_type)
                    if m_ann and m_ann.group(1) not in ("Mapped", "List", "Optional", "Set"):
                        target_model = m_ann.group(1)
                secondary_node = _get_kwarg(call_node, "secondary")
                secondary_tbl = _ast_const_str(secondary_node)
                if secondary_tbl is None and isinstance(secondary_node, ast.Name):
                    secondary_tbl = secondary_node.id
                uselist_val = _ast_const_bool(_get_kwarg(call_node, "uselist"))
                rel_kind = "MANY_TO_MANY" if secondary_tbl else ("ONE_TO_ONE" if uselist_val is False else "ONE_TO_MANY")
                if target_model:
                    tgt_tbl = model_to_table.get(target_model) or _camel_to_snake(target_model)
                    tgt_tbl_cid = build_db_canonical_id(
                        DatabaseEntityKind.TABLE,
                        table=tgt_tbl,
                        dialect=dialect,
                        schema=tbl_schema,
                    )
                    res.edges.append(
                        RelationshipRecord(
                            source=f"{model_canonical_id}.{field_name}",
                            target=tgt_tbl_cid,
                            relationship="ORM_RELATION",
                            evidence_class=ev_cls,
                            confidence="HIGH",
                            file=file_path,
                            start_line=stmt.lineno,
                            end_line=getattr(stmt, "end_lineno", stmt.lineno),
                            evidence=line_snippet(stmt.lineno),
                            reason=rel_kind,
                            status="FACT",
                            parser_version=PARSER_VERSION,
                            index_generation=index_generation,
                            metadata={"relation_type": rel_kind, "secondary": secondary_tbl},
                        )
                    )
            # 3. Django ORM fields
            elif short_cname in _DJANGO_FIELD_TYPES:
                _record_django_field(
                    field_name,
                    short_cname,
                    call_node,
                    table_name,
                    table_cid,
                    model_canonical_id,
                    dialect,
                    tbl_schema,
                    model_to_table,
                    file_path,
                    line_snippet(stmt.lineno),
                    index_generation,
                    res,
                )


def _record_sqlalchemy_column(
    field_name: str,
    call_node: ast.Call,
    table_name: str,
    table_cid: str,
    model_canonical_id: str | None,
    framework: str,
    dialect: str,
    schema: str,
    file_path: str,
    evidence: str,
    index_generation: int,
    res: DatabaseExtractionResult,
    ann_type: str = "",
) -> None:
    col_name = field_name.lower()
    data_type = ann_type or "UNKNOWN"
    is_pk = _ast_const_bool(_get_kwarg(call_node, "primary_key")) is True
    is_unique = _ast_const_bool(_get_kwarg(call_node, "unique")) is True
    is_index = _ast_const_bool(_get_kwarg(call_node, "index")) is True
    nullable_kw = _ast_const_bool(_get_kwarg(call_node, "nullable"))
    nullable = False if is_pk else (True if nullable_kw is None else nullable_kw)

    default_node = _get_kwarg(call_node, "default") or _get_kwarg(call_node, "server_default")
    default_val: str | None = None
    if default_node is not None and isinstance(default_node, ast.Constant):
        default_val = redact_secrets( repr(default_node.value) )

    fk_target: str | None = _ast_const_str(_get_kwarg(call_node, "foreign_key"))

    for arg in call_node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            # Explicit column name or ForeignKey string
            if "." in arg.value:
                fk_target = arg.value
            else:
                col_name = arg.value.lower()
        elif isinstance(arg, ast.Name):
            data_type = arg.id
        elif isinstance(arg, ast.Attribute):
            data_type = arg.attr
        elif isinstance(arg, ast.Call):
            acname = _ast_call_name(arg).split(".")[-1]
            if acname == "ForeignKey" and arg.args:
                fk_target = _ast_const_str(arg.args[0])
            else:
                data_type = acname

    col_cid = build_db_canonical_id(
        DatabaseEntityKind.COLUMN,
        table=table_name,
        column=col_name,
        dialect=dialect,
        schema=schema,
    )
    tgt_tbl: str | None = None
    tgt_col: str | None = None
    if fk_target and "." in fk_target:
        parts = fk_target.split(".")
        tgt_tbl = parts[-2].lower()
        tgt_col = parts[-1].lower()

    ev_cls = "FRAMEWORK_VERIFIED" if framework == "flask_sqlalchemy" else "AST_VERIFIED"

    res.entities.append(
        DatabaseEntity(
            canonical_id=col_cid,
            kind=DatabaseEntityKind.COLUMN.value,
            name=col_name,
            dialect=dialect,
            schema_name=schema,
            table_name=table_name,
            column_name=col_name,
            data_type=data_type,
            nullable=nullable,
            default_value=default_val,
            is_primary_key=is_pk,
            is_foreign_key=bool(fk_target),
            is_unique=is_unique,
            is_indexed=is_index,
            target_table=tgt_tbl,
            target_column=tgt_col,
            orm_model_id=model_canonical_id,
            framework=framework,
            file_path=file_path,
            start_line=call_node.lineno,
            end_line=getattr(call_node, "end_lineno", call_node.lineno),
            evidence=evidence,
            confidence="HIGH",
            evidence_class=ev_cls,
        )
    )

    if model_canonical_id:
        res.edges.append(
            RelationshipRecord(
                source=f"{model_canonical_id}.{field_name}",
                target=col_cid,
                relationship="MAPS_TO_COLUMN",
                evidence_class=ev_cls,
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    if is_pk:
        pk_cid = build_db_canonical_id(
            DatabaseEntityKind.PRIMARY_KEY,
            table=table_name,
            column=col_name,
            dialect=dialect,
            schema=schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=pk_cid,
                kind=DatabaseEntityKind.PRIMARY_KEY.value,
                name=f"pk_{table_name}_{col_name}",
                dialect=dialect,
                schema_name=schema,
                table_name=table_name,
                column_name=col_name,
                is_primary_key=True,
                framework=framework,
                file_path=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=table_cid,
                target=col_cid,
                relationship="HAS_PRIMARY_KEY",
                evidence_class=ev_cls,
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    if is_index:
        idx_cid = build_db_canonical_id(
            DatabaseEntityKind.INDEX,
            table=table_name,
            column=col_name,
            name=f"ix_{table_name}_{col_name}",
            dialect=dialect,
            schema=schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=idx_cid,
                kind=DatabaseEntityKind.INDEX.value,
                name=f"ix_{table_name}_{col_name}",
                dialect=dialect,
                schema_name=schema,
                table_name=table_name,
                column_name=col_name,
                is_indexed=True,
                framework=framework,
                file_path=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=table_cid,
                target=idx_cid,
                relationship="HAS_INDEX",
                evidence_class=ev_cls,
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    if is_unique:
        uq_cid = build_db_canonical_id(
            DatabaseEntityKind.UNIQUE_CONSTRAINT,
            table=table_name,
            column=col_name,
            name=f"uq_{table_name}_{col_name}",
            dialect=dialect,
            schema=schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=uq_cid,
                kind=DatabaseEntityKind.UNIQUE_CONSTRAINT.value,
                name=f"uq_{table_name}_{col_name}",
                dialect=dialect,
                schema_name=schema,
                table_name=table_name,
                column_name=col_name,
                is_unique=True,
                framework=framework,
                file_path=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=table_cid,
                target=uq_cid,
                relationship="HAS_UNIQUE_CONSTRAINT",
                evidence_class=ev_cls,
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    if tgt_tbl and tgt_col:
        target_col_cid = build_db_canonical_id(
            DatabaseEntityKind.COLUMN,
            table=tgt_tbl,
            column=tgt_col,
            dialect=dialect,
            schema=schema,
        )
        fk_cid = build_db_canonical_id(
            DatabaseEntityKind.FOREIGN_KEY,
            table=table_name,
            column=col_name,
            dialect=dialect,
            schema=schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=fk_cid,
                kind=DatabaseEntityKind.FOREIGN_KEY.value,
                name=f"fk_{table_name}_{col_name}_{tgt_tbl}_{tgt_col}",
                dialect=dialect,
                schema_name=schema,
                table_name=table_name,
                column_name=col_name,
                is_foreign_key=True,
                target_table=tgt_tbl,
                target_column=tgt_col,
                framework=framework,
                file_path=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=col_cid,
                target=target_col_cid,
                relationship="FOREIGN_KEY_TO",
                evidence_class=ev_cls,
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )


def _record_django_field(
    field_name: str,
    field_type: str,
    call_node: ast.Call,
    table_name: str,
    table_cid: str,
    model_canonical_id: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    file_path: str,
    evidence: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    is_pk = _ast_const_bool(_get_kwarg(call_node, "primary_key")) is True or field_type in ("AutoField", "BigAutoField")
    is_unique = _ast_const_bool(_get_kwarg(call_node, "unique")) is True or field_type == "OneToOneField"
    is_index = _ast_const_bool(_get_kwarg(call_node, "db_index")) is True
    nullable = _ast_const_bool(_get_kwarg(call_node, "null")) is True

    if field_type in ("ForeignKey", "OneToOneField", "ManyToManyField"):
        target_model: str | None = None
        if call_node.args:
            arg0 = call_node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                target_model = arg0.value.split(".")[-1]
            elif isinstance(arg0, ast.Name):
                target_model = arg0.id
        if not target_model:
            to_kw = _get_kwarg(call_node, "to")
            if isinstance(to_kw, ast.Constant) and isinstance(to_kw.value, str):
                target_model = to_kw.value.split(".")[-1]
            elif isinstance(to_kw, ast.Name):
                target_model = to_kw.id

        tgt_tbl = (model_to_table.get(target_model or "") or _pluralize_table(_camel_to_snake(target_model or "unknown")))
        tgt_tbl_cid = build_db_canonical_id(
            DatabaseEntityKind.TABLE,
            table=tgt_tbl,
            dialect=dialect,
            schema=schema,
        )

        if field_type == "ManyToManyField":
            res.edges.append(
                RelationshipRecord(
                    source=f"{model_canonical_id}.{field_name}",
                    target=tgt_tbl_cid,
                    relationship="ORM_RELATION",
                    evidence_class="FRAMEWORK_VERIFIED",
                    confidence="HIGH",
                    file=file_path,
                    start_line=call_node.lineno,
                    end_line=getattr(call_node, "end_lineno", call_node.lineno),
                    evidence=evidence,
                    reason="MANY_TO_MANY",
                    status="FACT",
                    parser_version=PARSER_VERSION,
                    index_generation=index_generation,
                )
            )
            return

        col_name = f"{field_name.lower()}_id" if not field_name.lower().endswith("_id") else field_name.lower()
        col_cid = build_db_canonical_id(
            DatabaseEntityKind.COLUMN,
            table=table_name,
            column=col_name,
            dialect=dialect,
            schema=schema,
        )
        tgt_col_cid = build_db_canonical_id(
            DatabaseEntityKind.COLUMN,
            table=tgt_tbl,
            column="id",
            dialect=dialect,
            schema=schema,
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=col_cid,
                kind=DatabaseEntityKind.COLUMN.value,
                name=col_name,
                dialect=dialect,
                schema_name=schema,
                table_name=table_name,
                column_name=col_name,
                data_type=field_type,
                nullable=nullable,
                is_foreign_key=True,
                is_unique=is_unique,
                target_table=tgt_tbl,
                target_column="id",
                orm_model_id=model_canonical_id,
                framework="django_orm",
                file_path=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                evidence_class="FRAMEWORK_VERIFIED",
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=f"{model_canonical_id}.{field_name}",
                target=col_cid,
                relationship="MAPS_TO_COLUMN",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=col_cid,
                target=tgt_col_cid,
                relationship="FOREIGN_KEY_TO",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )
        return

    col_name = field_name.lower()
    col_cid = build_db_canonical_id(
        DatabaseEntityKind.COLUMN,
        table=table_name,
        column=col_name,
        dialect=dialect,
        schema=schema,
    )
    res.entities.append(
        DatabaseEntity(
            canonical_id=col_cid,
            kind=DatabaseEntityKind.COLUMN.value,
            name=col_name,
            dialect=dialect,
            schema_name=schema,
            table_name=table_name,
            column_name=col_name,
            data_type=field_type,
            nullable=nullable,
            is_primary_key=is_pk,
            is_unique=is_unique,
            is_indexed=is_index,
            orm_model_id=model_canonical_id,
            framework="django_orm",
            file_path=file_path,
            start_line=call_node.lineno,
            end_line=getattr(call_node, "end_lineno", call_node.lineno),
            evidence=evidence,
            evidence_class="FRAMEWORK_VERIFIED",
        )
    )
    res.edges.append(
        RelationshipRecord(
            source=f"{model_canonical_id}.{field_name}",
            target=col_cid,
            relationship="MAPS_TO_COLUMN",
            evidence_class="FRAMEWORK_VERIFIED",
            confidence="HIGH",
            file=file_path,
            start_line=call_node.lineno,
            end_line=getattr(call_node, "end_lineno", call_node.lineno),
            evidence=evidence,
            status="FACT",
            parser_version=PARSER_VERSION,
            index_generation=index_generation,
        )
    )
    if is_pk:
        res.edges.append(
            RelationshipRecord(
                source=table_cid,
                target=col_cid,
                relationship="HAS_PRIMARY_KEY",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=call_node.lineno,
                end_line=getattr(call_node, "end_lineno", call_node.lineno),
                evidence=evidence,
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )


def _extract_python_queries_in_scope(
    tree: ast.AST,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    line_snippet: Any,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    """Walk functions/methods and extract ORM queries, session mutations, and raw SQL operations."""

    def _visit_scope(
        node: ast.AST,
        scope_stack: list[str],
        local_model_vars: dict[str, str],
        local_sql_vars: dict[str, str],
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            next_scope = [*scope_stack, node.name]
            next_model_vars = dict(local_model_vars)
            next_sql_vars = dict(local_sql_vars)
            for child in ast.iter_child_nodes(node):
                _visit_scope(child, next_scope, next_model_vars, next_sql_vars)
            return

        # Track local variable bindings: e.g. `order = Order(user_id=1)` or `sql = "SELECT * FROM users"`
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            var_name = node.targets[0].id
            if isinstance(node.value, ast.Call):
                cname = _ast_call_name(node.value)
                if cname in model_to_table:
                    local_model_vars[var_name] = model_to_table[cname]
                elif cname and cname[0].isupper() and cname.split(".")[-1] in model_to_table:
                    local_model_vars[var_name] = model_to_table[cname.split(".")[-1]]
            elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                local_sql_vars[var_name] = node.value.value

        if isinstance(node, ast.Call):
            caller_id = (
                f"{module_name}.{'.'.join(scope_stack)}"
                if scope_stack
                else module_name
            )
            _inspect_call_for_db_query(
                node,
                caller_id,
                file_path,
                dialect,
                schema,
                model_to_table,
                local_model_vars,
                local_sql_vars,
                line_snippet,
                index_generation,
                res,
            )

        for child in ast.iter_child_nodes(node):
            _visit_scope(child, scope_stack, local_model_vars, local_sql_vars)

    _visit_scope(tree, [], {}, {})


def _inspect_call_for_db_query(
    call: ast.Call,
    caller_id: str,
    file_path: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    local_model_vars: dict[str, str],
    local_sql_vars: dict[str, str],
    line_snippet: Any,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    cname = _ast_call_name(call)
    short_name = cname.split(".")[-1]
    ev_line = line_snippet(call.lineno)

    # 1. Raw SQL execution: cursor.execute(...), con.execute(...), conn.fetch(...), session.execute(text(...))
    if short_name in ("execute", "executemany", "fetch", "fetchrow", "fetchval", "raw") and call.args:
        arg0 = call.args[0]
        raw_sql: str | None = _ast_const_str(arg0)
        if raw_sql is None and isinstance(arg0, ast.Name) and arg0.id in local_sql_vars:
            raw_sql = local_sql_vars[arg0.id]
        elif raw_sql is None and isinstance(arg0, ast.Call) and _ast_call_name(arg0).endswith("text") and arg0.args:
            raw_sql = _ast_const_str(arg0.args[0])

        if raw_sql:
            parsed_ops = parse_sql_statement(raw_sql)
            for op_info in parsed_ops:
                op = str(op_info["operation"])
                rel = str(op_info["relationship"])
                cols = tuple(str(c) for c in op_info.get("columns", []))
                for tbl in op_info.get("tables", []):
                    _emit_query_fact_and_edges(
                        caller_id=caller_id,
                        operation=op,
                        relationship=rel,
                        table_name=tbl,
                        columns=cols,
                        read_columns=tuple(str(c) for c in op_info.get("read_columns", [])),
                        framework="raw_sql",
                        normalized_sql=str(op_info.get("normalized_sql") or ""),
                        dialect=dialect,
                        schema=schema,
                        file_path=file_path,
                        start_line=call.lineno,
                        end_line=getattr(call, "end_lineno", call.lineno),
                        evidence=ev_line,
                        confidence="HIGH",
                        evidence_class="AST_VERIFIED",
                        status="FACT",
                        index_generation=index_generation,
                        res=res,
                    )
            return

        # Dynamic f-string or binary-op SQL where table name is not statically provable
        if isinstance(arg0, (ast.JoinedStr, ast.BinOp)):
            static_parts = ""
            if isinstance(arg0, ast.JoinedStr):
                static_parts = " ".join(
                    v.value for v in arg0.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
            if any(k in static_parts.upper() for k in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
                unk_cid = build_db_canonical_id(
                    DatabaseEntityKind.TABLE,
                    table="UNKNOWN",
                    dialect=dialect,
                    schema=schema,
                )
                q_id = f"q:{file_path}:{call.lineno}:{caller_id}:UNKNOWN"
                res.queries.append(
                    DatabaseQueryFact(
                        query_id=q_id,
                        caller_symbol_id=caller_id,
                        operation="UNKNOWN",
                        relationship="UNKNOWN_TABLE",
                        table_name="UNKNOWN",
                        table_canonical_id=unk_cid,
                        framework="raw_sql",
                        normalized_sql=normalize_and_redact_sql(static_parts),
                        file_path=file_path,
                        start_line=call.lineno,
                        end_line=getattr(call, "end_lineno", call.lineno),
                        evidence=ev_line,
                        confidence="UNKNOWN",
                        evidence_class="UNKNOWN",
                        status="UNKNOWN",
                    )
                )
                res.edges.append(
                    RelationshipRecord(
                        source=caller_id,
                        target=unk_cid,
                        relationship="UNKNOWN_TABLE",
                        evidence_class="UNKNOWN",
                        confidence="UNKNOWN",
                        file=file_path,
                        start_line=call.lineno,
                        end_line=getattr(call, "end_lineno", call.lineno),
                        evidence=ev_line,
                        reason="dynamic_sql_table_unresolvable",
                        status="UNKNOWN",
                        parser_version=PARSER_VERSION,
                        index_generation=index_generation,
                    )
                )
                return

    # 2. SQLAlchemy 1.x / 2.x select(Model), insert(Model), update(Model), delete(Model), session.query(Model)
    if short_name in ("query", "select", "insert", "update", "delete") and call.args:
        arg0 = call.args[0]
        model_name: str | None = None
        if isinstance(arg0, ast.Name):
            model_name = arg0.id
        elif isinstance(arg0, ast.Attribute):
            model_name = arg0.attr

        if model_name and model_name in model_to_table:
            tbl_name = model_to_table[model_name]
            if short_name in ("query", "select"):
                op, rel = "SELECT", "READS_TABLE"
            elif short_name == "insert":
                op, rel = "INSERT", "WRITES_TABLE"
            elif short_name == "update":
                op, rel = "UPDATE", "WRITES_TABLE"
            else:
                op, rel = "DELETE", "WRITES_TABLE"
            _emit_query_fact_and_edges(
                caller_id=caller_id,
                operation=op,
                relationship=rel,
                table_name=tbl_name,
                columns=(),
                read_columns=(),
                framework="sqlalchemy",
                normalized_sql=f"{op} {tbl_name}",
                dialect=dialect,
                schema=schema,
                file_path=file_path,
                start_line=call.lineno,
                end_line=getattr(call, "end_lineno", call.lineno),
                evidence=ev_line,
                confidence="HIGH",
                evidence_class="AST_VERIFIED",
                status="FACT",
                index_generation=index_generation,
                res=res,
            )
            return

    # 3. session.add(obj), db.session.add(obj), session.delete(obj)
    if short_name in ("add", "add_all", "merge") and call.args:
        is_session_call = False
        if isinstance(call.func, ast.Attribute):
            recv = ast.unparse(call.func.value) if hasattr(ast, "unparse") else ""
            if any(s in recv.lower() for s in ("session", "db")):
                is_session_call = True
        if is_session_call:
            arg0 = call.args[0]
            add_tbl_name: str | None = None
            add_cols: list[str] = []
            if isinstance(arg0, ast.Call):
                mname = _ast_call_name(arg0).split(".")[-1]
                add_tbl_name = model_to_table.get(mname)
                add_cols = [kw.arg.lower() for kw in arg0.keywords if kw.arg]
            elif isinstance(arg0, ast.Name) and arg0.id in local_model_vars:
                add_tbl_name = local_model_vars[arg0.id]
            if add_tbl_name:
                _emit_query_fact_and_edges(
                    caller_id=caller_id,
                    operation="INSERT",
                    relationship="WRITES_TABLE",
                    table_name=add_tbl_name,
                    columns=tuple(add_cols),
                    read_columns=(),
                    framework="sqlalchemy",
                    normalized_sql=f"INSERT INTO {add_tbl_name}",
                    dialect=dialect,
                    schema=schema,
                    file_path=file_path,
                    start_line=call.lineno,
                    end_line=getattr(call, "end_lineno", call.lineno),
                    evidence=ev_line,
                    confidence="HIGH",
                    evidence_class="DATAFLOW_VERIFIED",
                    status="FACT",
                    index_generation=index_generation,
                    res=res,
                )
                return

    # 4. Django ORM `Model.objects.<method>(...)` or Flask-SQLAlchemy `Model.query.<method>(...)`
    if isinstance(call.func, ast.Attribute):
        method_name = call.func.attr
        # Unwrap chained calls like Model.objects.filter(...).update(...)
        curr: ast.AST = call.func.value
        root_model: str | None = None
        manager_kind: str = ""
        while isinstance(curr, ast.Call) and isinstance(curr.func, ast.Attribute):
            curr = curr.func.value
        if isinstance(curr, ast.Attribute) and isinstance(curr.value, ast.Name):
            if curr.attr in ("objects", "query"):
                root_model = curr.value.id
                manager_kind = curr.attr

        if root_model and root_model in model_to_table:
            tbl_name = model_to_table[root_model]
            fw = "django_orm" if manager_kind == "objects" else "flask_sqlalchemy"
            kw_cols = tuple(
                kw.arg.split("__")[0].lower()
                for kw in call.keywords
                if kw.arg and kw.arg not in ("defaults",)
            )
            if method_name in ("filter", "filter_by", "get", "all", "first", "last", "count", "exists", "values", "values_list"):
                _emit_query_fact_and_edges(
                    caller_id=caller_id,
                    operation="SELECT",
                    relationship="READS_TABLE",
                    table_name=tbl_name,
                    columns=kw_cols,
                    read_columns=kw_cols,
                    framework=fw,
                    normalized_sql=f"SELECT FROM {tbl_name}",
                    dialect=dialect,
                    schema=schema,
                    file_path=file_path,
                    start_line=call.lineno,
                    end_line=getattr(call, "end_lineno", call.lineno),
                    evidence=ev_line,
                    confidence="HIGH",
                    evidence_class="FRAMEWORK_VERIFIED",
                    status="FACT",
                    index_generation=index_generation,
                    res=res,
                )
            elif method_name in ("create", "bulk_create", "get_or_create", "update_or_create"):
                _emit_query_fact_and_edges(
                    caller_id=caller_id,
                    operation="INSERT",
                    relationship="WRITES_TABLE",
                    table_name=tbl_name,
                    columns=kw_cols,
                    read_columns=(),
                    framework=fw,
                    normalized_sql=f"INSERT INTO {tbl_name}",
                    dialect=dialect,
                    schema=schema,
                    file_path=file_path,
                    start_line=call.lineno,
                    end_line=getattr(call, "end_lineno", call.lineno),
                    evidence=ev_line,
                    confidence="HIGH",
                    evidence_class="FRAMEWORK_VERIFIED",
                    status="FACT",
                    index_generation=index_generation,
                    res=res,
                )
            elif method_name in ("update", "bulk_update"):
                _emit_query_fact_and_edges(
                    caller_id=caller_id,
                    operation="UPDATE",
                    relationship="WRITES_TABLE",
                    table_name=tbl_name,
                    columns=kw_cols,
                    read_columns=(),
                    framework=fw,
                    normalized_sql=f"UPDATE {tbl_name}",
                    dialect=dialect,
                    schema=schema,
                    file_path=file_path,
                    start_line=call.lineno,
                    end_line=getattr(call, "end_lineno", call.lineno),
                    evidence=ev_line,
                    confidence="HIGH",
                    evidence_class="FRAMEWORK_VERIFIED",
                    status="FACT",
                    index_generation=index_generation,
                    res=res,
                )
            elif method_name == "delete":
                _emit_query_fact_and_edges(
                    caller_id=caller_id,
                    operation="DELETE",
                    relationship="WRITES_TABLE",
                    table_name=tbl_name,
                    columns=(),
                    read_columns=(),
                    framework=fw,
                    normalized_sql=f"DELETE FROM {tbl_name}",
                    dialect=dialect,
                    schema=schema,
                    file_path=file_path,
                    start_line=call.lineno,
                    end_line=getattr(call, "end_lineno", call.lineno),
                    evidence=ev_line,
                    confidence="HIGH",
                    evidence_class="FRAMEWORK_VERIFIED",
                    status="FACT",
                    index_generation=index_generation,
                    res=res,
                )


def _emit_query_fact_and_edges(
    caller_id: str,
    operation: str,
    relationship: str,
    table_name: str,
    columns: tuple[str, ...],
    read_columns: tuple[str, ...],
    framework: str,
    normalized_sql: str,
    dialect: str,
    schema: str,
    file_path: str,
    start_line: int,
    end_line: int,
    evidence: str,
    confidence: str,
    evidence_class: str,
    status: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    tbl_clean = table_name.strip().lower()
    tbl_cid = build_db_canonical_id(
        DatabaseEntityKind.TABLE,
        table=tbl_clean,
        dialect=dialect,
        schema=schema,
    )
    q_id = f"q:{file_path}:{start_line}:{caller_id}:{operation}:{tbl_clean}"
    res.queries.append(
        DatabaseQueryFact(
            query_id=q_id,
            caller_symbol_id=caller_id,
            operation=operation,
            relationship=relationship,
            table_name=tbl_clean,
            table_canonical_id=tbl_cid,
            columns=columns,
            framework=framework,
            normalized_sql=normalized_sql,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            evidence=evidence,
            confidence=confidence,
            evidence_class=evidence_class,
            status=status,
        )
    )
    res.edges.append(
        RelationshipRecord(
            source=caller_id,
            target=tbl_cid,
            relationship=relationship,
            evidence_class=evidence_class,
            confidence=confidence,
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            evidence=evidence,
            status=status,
            parser_version=PARSER_VERSION,
            index_generation=index_generation,
        )
    )

    col_rel = "WRITES_COLUMN" if relationship == "WRITES_TABLE" else "READS_COLUMN"
    for col in columns:
        col_cid = build_db_canonical_id(
            DatabaseEntityKind.COLUMN,
            table=tbl_clean,
            column=col,
            dialect=dialect,
            schema=schema,
        )
        res.edges.append(
            RelationshipRecord(
                source=caller_id,
                target=col_cid,
                relationship=col_rel,
                evidence_class=evidence_class,
                confidence=confidence,
                file=file_path,
                start_line=start_line,
                end_line=end_line,
                evidence=evidence,
                status=status,
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )

    for rcol in read_columns:
        if rcol not in columns or col_rel != "READS_COLUMN":
            rcol_cid = build_db_canonical_id(
                DatabaseEntityKind.COLUMN,
                table=tbl_clean,
                column=rcol,
                dialect=dialect,
                schema=schema,
            )
            res.edges.append(
                RelationshipRecord(
                    source=caller_id,
                    target=rcol_cid,
                    relationship="READS_COLUMN",
                    evidence_class=evidence_class,
                    confidence=confidence,
                    file=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    evidence=evidence,
                    status=status,
                    parser_version=PARSER_VERSION,
                    index_generation=index_generation,
                )
            )


# ---------------------------------------------------------------------------
# Migration Intelligence (Alembic, Django, SQL, Prisma)
# ---------------------------------------------------------------------------


def _extract_alembic_migration(
    tree: ast.Module,
    content: str,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    revision = module_name.split(".")[-1]
    down_revision: str | None = None
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    added_columns: list[str] = []
    removed_columns: list[str] = []
    renamed_columns: list[str] = []
    indexes: list[str] = []
    foreign_keys: list[str] = []
    constraints: list[str] = []
    affected_tables: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "revision":
                    revision = _ast_const_str(node.value) or revision
                elif isinstance(tgt, ast.Name) and tgt.id == "down_revision":
                    down_revision = _ast_const_str(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "revision" and node.value:
                revision = _ast_const_str(node.value) or revision
            elif node.target.id == "down_revision" and node.value:
                down_revision = _ast_const_str(node.value)

    # Walk upgrade() function (or module body if no upgrade function)
    upgrade_nodes: list[ast.AST] = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
    ] or [tree]

    for up_node in upgrade_nodes:
        for child in ast.walk(up_node):
            if not isinstance(child, ast.Call):
                continue
            cname = _ast_call_name(child)
            if not cname.startswith("op."):
                continue
            op_name = cname.split(".")[-1]
            if op_name == "create_table" and child.args:
                tbl = _ast_const_str(child.args[0])
                if tbl:
                    t_clean = tbl.lower()
                    created_tables.append(t_clean)
                    affected_tables.add(t_clean)
                    tbl_cid = build_db_canonical_id(
                        DatabaseEntityKind.TABLE,
                        table=t_clean,
                        dialect=dialect,
                        schema=schema,
                    )
                    res.entities.append(
                        DatabaseEntity(
                            canonical_id=tbl_cid,
                            kind=DatabaseEntityKind.TABLE.value,
                            name=t_clean,
                            dialect=dialect,
                            schema_name=schema,
                            table_name=t_clean,
                            framework="alembic",
                            file_path=file_path,
                            start_line=child.lineno,
                            end_line=getattr(child, "end_lineno", child.lineno),
                            evidence=f"op.create_table({t_clean!r})",
                        )
                    )
                    for sub in child.args[1:]:
                        if isinstance(sub, ast.Call):
                            sc = _ast_call_name(sub).split(".")[-1]
                            if sc == "Column" and sub.args:
                                col_nm = _ast_const_str(sub.args[0])
                                if col_nm:
                                    added_columns.append(f"{t_clean}.{col_nm.lower()}")
                                    _record_sqlalchemy_column(
                                        col_nm,
                                        sub,
                                        t_clean,
                                        tbl_cid,
                                        None,
                                        "alembic",
                                        dialect,
                                        schema,
                                        file_path,
                                        f"op.create_table({t_clean!r}) -> Column({col_nm!r})",
                                        index_generation,
                                        res,
                                    )
            elif op_name == "drop_table" and child.args:
                tbl = _ast_const_str(child.args[0])
                if tbl:
                    dropped_tables.append(tbl.lower())
                    affected_tables.add(tbl.lower())
            elif op_name == "add_column" and len(child.args) >= 2:
                tbl = _ast_const_str(child.args[0])
                col_arg = child.args[1]
                if tbl and isinstance(col_arg, ast.Call) and col_arg.args:
                    col_nm = _ast_const_str(col_arg.args[0])
                    if col_nm:
                        t_clean = tbl.lower()
                        c_clean = col_nm.lower()
                        added_columns.append(f"{t_clean}.{c_clean}")
                        affected_tables.add(t_clean)
                        tbl_cid = build_db_canonical_id(
                            DatabaseEntityKind.TABLE,
                            table=t_clean,
                            dialect=dialect,
                            schema=schema,
                        )
                        _record_sqlalchemy_column(
                            c_clean,
                            col_arg,
                            t_clean,
                            tbl_cid,
                            None,
                            "alembic",
                            dialect,
                            schema,
                            file_path,
                            f"op.add_column({t_clean!r}, Column({c_clean!r}))",
                            index_generation,
                            res,
                        )
            elif op_name == "drop_column" and len(child.args) >= 2:
                tbl = _ast_const_str(child.args[0])
                col_nm = _ast_const_str(child.args[1])
                if tbl and col_nm:
                    removed_columns.append(f"{tbl.lower()}.{col_nm.lower()}")
                    affected_tables.add(tbl.lower())
            elif op_name == "alter_column" and len(child.args) >= 2:
                tbl = _ast_const_str(child.args[0])
                col_nm = _ast_const_str(child.args[1])
                new_nm = _ast_const_str(_get_kwarg(child, "new_column_name"))
                if tbl and col_nm and new_nm:
                    renamed_columns.append(f"{tbl.lower()}.{col_nm.lower()}->{new_nm.lower()}")
                    affected_tables.add(tbl.lower())
            elif op_name == "create_index" and len(child.args) >= 2:
                idx_nm = _ast_const_str(child.args[0])
                tbl = _ast_const_str(child.args[1])
                if idx_nm and tbl:
                    indexes.append(f"{tbl.lower()}.{idx_nm}")
                    affected_tables.add(tbl.lower())
            elif op_name == "create_foreign_key" and len(child.args) >= 3:
                fk_nm = _ast_const_str(child.args[0]) or "fk"
                src_tbl = _ast_const_str(child.args[1])
                tgt_tbl = _ast_const_str(child.args[2])
                if src_tbl and tgt_tbl:
                    foreign_keys.append(f"{src_tbl.lower()}->{tgt_tbl.lower()}({fk_nm})")
                    affected_tables.add(src_tbl.lower())
                    affected_tables.add(tgt_tbl.lower())
            elif op_name in ("create_unique_constraint", "create_check_constraint") and len(child.args) >= 2:
                c_nm = _ast_const_str(child.args[0]) or op_name
                tbl = _ast_const_str(child.args[1])
                if tbl:
                    constraints.append(f"{tbl.lower()}.{c_nm}")
                    affected_tables.add(tbl.lower())

    mig_cid = build_db_canonical_id(
        DatabaseEntityKind.MIGRATION,
        name=revision,
        module="alembic",
    )
    mig_fact = MigrationFact(
        migration_id=revision,
        canonical_id=mig_cid,
        system="alembic",
        revision=revision,
        down_revision=down_revision,
        file_path=file_path,
        start_line=1,
        end_line=len(content.splitlines()) if content else 1,
        created_tables=tuple(sorted(set(created_tables))),
        dropped_tables=tuple(sorted(set(dropped_tables))),
        added_columns=tuple(sorted(set(added_columns))),
        removed_columns=tuple(sorted(set(removed_columns))),
        renamed_columns=tuple(sorted(set(renamed_columns))),
        indexes=tuple(sorted(set(indexes))),
        foreign_keys=tuple(sorted(set(foreign_keys))),
        constraints=tuple(sorted(set(constraints))),
        affected_tables=tuple(sorted(affected_tables)),
        evidence=f"Alembic revision={revision!r}",
    )
    res.migrations.append(mig_fact)
    res.entities.append(
        DatabaseEntity(
            canonical_id=mig_cid,
            kind=DatabaseEntityKind.MIGRATION.value,
            name=revision,
            dialect=dialect,
            schema_name=schema,
            framework="alembic",
            file_path=file_path,
            start_line=1,
            end_line=mig_fact.end_line,
            evidence=f"Alembic revision={revision!r}",
            metadata=mig_fact.as_dict(),
        )
    )
    for tbl in sorted(affected_tables):
        tbl_cid = build_db_canonical_id(
            DatabaseEntityKind.TABLE,
            table=tbl,
            dialect=dialect,
            schema=schema,
        )
        res.edges.append(
            RelationshipRecord(
                source=mig_cid,
                target=tbl_cid,
                relationship="MIGRATES_TABLE",
                evidence_class="AST_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=1,
                end_line=mig_fact.end_line,
                evidence=f"Alembic migration {revision} affects {tbl}",
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )


def _extract_django_migration(
    tree: ast.Module,
    content: str,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    revision = module_name.split(".")[-1]
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    added_columns: list[str] = []
    removed_columns: list[str] = []
    renamed_columns: list[str] = []
    affected_tables: set[str] = set()

    for child in ast.walk(tree):
        if not isinstance(child, ast.Call):
            continue
        cname = _ast_call_name(child).split(".")[-1]
        if cname == "CreateModel":
            m_name = _ast_const_str(_get_kwarg(child, "name"))
            if m_name:
                t_clean = _pluralize_table(_camel_to_snake(m_name))
                created_tables.append(t_clean)
                affected_tables.add(t_clean)
                fields_kw = _get_kwarg(child, "fields")
                if isinstance(fields_kw, ast.List):
                    for elt in fields_kw.elts:
                        if isinstance(elt, ast.Tuple) and elt.elts:
                            col_nm = _ast_const_str(elt.elts[0])
                            if col_nm:
                                added_columns.append(f"{t_clean}.{col_nm.lower()}")
        elif cname == "DeleteModel":
            m_name = _ast_const_str(_get_kwarg(child, "name"))
            if m_name:
                t_clean = _pluralize_table(_camel_to_snake(m_name))
                dropped_tables.append(t_clean)
                affected_tables.add(t_clean)
        elif cname == "AddField":
            m_name = _ast_const_str(_get_kwarg(child, "model_name"))
            f_name = _ast_const_str(_get_kwarg(child, "name"))
            if m_name and f_name:
                t_clean = _pluralize_table(_camel_to_snake(m_name))
                added_columns.append(f"{t_clean}.{f_name.lower()}")
                affected_tables.add(t_clean)
        elif cname == "RemoveField":
            m_name = _ast_const_str(_get_kwarg(child, "model_name"))
            f_name = _ast_const_str(_get_kwarg(child, "name"))
            if m_name and f_name:
                t_clean = _pluralize_table(_camel_to_snake(m_name))
                removed_columns.append(f"{t_clean}.{f_name.lower()}")
                affected_tables.add(t_clean)
        elif cname == "RenameField":
            m_name = _ast_const_str(_get_kwarg(child, "model_name"))
            old_nm = _ast_const_str(_get_kwarg(child, "old_name"))
            new_nm = _ast_const_str(_get_kwarg(child, "new_name"))
            if m_name and old_nm and new_nm:
                t_clean = _pluralize_table(_camel_to_snake(m_name))
                renamed_columns.append(f"{t_clean}.{old_nm.lower()}->{new_nm.lower()}")
                affected_tables.add(t_clean)

    mig_cid = build_db_canonical_id(
        DatabaseEntityKind.MIGRATION,
        name=revision,
        module="django",
    )
    mig_fact = MigrationFact(
        migration_id=revision,
        canonical_id=mig_cid,
        system="django",
        revision=revision,
        file_path=file_path,
        start_line=1,
        end_line=len(content.splitlines()) if content else 1,
        created_tables=tuple(sorted(set(created_tables))),
        dropped_tables=tuple(sorted(set(dropped_tables))),
        added_columns=tuple(sorted(set(added_columns))),
        removed_columns=tuple(sorted(set(removed_columns))),
        renamed_columns=tuple(sorted(set(renamed_columns))),
        affected_tables=tuple(sorted(affected_tables)),
        evidence=f"Django migration {revision}",
        evidence_class="FRAMEWORK_VERIFIED",
    )
    res.migrations.append(mig_fact)
    res.entities.append(
        DatabaseEntity(
            canonical_id=mig_cid,
            kind=DatabaseEntityKind.MIGRATION.value,
            name=revision,
            dialect=dialect,
            schema_name=schema,
            framework="django_orm",
            file_path=file_path,
            start_line=1,
            end_line=mig_fact.end_line,
            evidence=f"Django migration {revision}",
            evidence_class="FRAMEWORK_VERIFIED",
            metadata=mig_fact.as_dict(),
        )
    )
    for tbl in sorted(affected_tables):
        tbl_cid = build_db_canonical_id(
            DatabaseEntityKind.TABLE,
            table=tbl,
            dialect=dialect,
            schema=schema,
        )
        res.edges.append(
            RelationshipRecord(
                source=mig_cid,
                target=tbl_cid,
                relationship="MIGRATES_TABLE",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=1,
                end_line=mig_fact.end_line,
                evidence=f"Django migration {revision} affects {tbl}",
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )


def _extract_sql_file(
    content: str,
    file_path: str,
    dialect: str,
    schema: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    parsed = parse_sql_statement(content)
    rev = file_path.rsplit("/", 1)[-1].replace(".sql", "")
    created_tables: list[str] = []
    added_columns: list[str] = []
    affected_tables: set[str] = set()

    for op_info in parsed:
        op = str(op_info["operation"])
        if op == "CREATE_TABLE":
            for tbl in op_info.get("tables", []):
                created_tables.append(tbl)
                affected_tables.add(tbl)
                tbl_cid = build_db_canonical_id(
                    DatabaseEntityKind.TABLE,
                    table=tbl,
                    dialect=dialect,
                    schema=schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=tbl_cid,
                        kind=DatabaseEntityKind.TABLE.value,
                        name=tbl,
                        dialect=dialect,
                        schema_name=schema,
                        table_name=tbl,
                        framework="sql",
                        file_path=file_path,
                        start_line=1,
                        end_line=len(content.splitlines()),
                        evidence=str(op_info.get("normalized_sql") or "")[:160],
                    )
                )
                for cdef in op_info.get("column_defs", []):
                    col_cid = build_db_canonical_id(
                        DatabaseEntityKind.COLUMN,
                        table=tbl,
                        column=cdef["name"],
                        dialect=dialect,
                        schema=schema,
                    )
                    added_columns.append(f"{tbl}.{cdef['name']}")
                    res.entities.append(
                        DatabaseEntity(
                            canonical_id=col_cid,
                            kind=DatabaseEntityKind.COLUMN.value,
                            name=cdef["name"],
                            dialect=dialect,
                            schema_name=schema,
                            table_name=tbl,
                            column_name=cdef["name"],
                            data_type=cdef["data_type"],
                            nullable=cdef["nullable"],
                            is_primary_key=cdef["is_primary_key"],
                            is_unique=cdef["is_unique"],
                            framework="sql",
                            file_path=file_path,
                            start_line=1,
                            end_line=len(content.splitlines()),
                            evidence=f"{cdef['name']} {cdef['data_type']}",
                        )
                    )
                    if cdef["is_primary_key"]:
                        res.edges.append(
                            RelationshipRecord(
                                source=tbl_cid,
                                target=col_cid,
                                relationship="HAS_PRIMARY_KEY",
                                evidence_class="AST_VERIFIED",
                                confidence="HIGH",
                                file=file_path,
                                start_line=1,
                                end_line=1,
                                evidence=f"PRIMARY KEY ({cdef['name']})",
                                status="FACT",
                                parser_version=PARSER_VERSION,
                                index_generation=index_generation,
                            )
                        )
                for fk in op_info.get("foreign_keys", []):
                    src_col_cid = build_db_canonical_id(
                        DatabaseEntityKind.COLUMN,
                        table=tbl,
                        column=fk["column"],
                        dialect=dialect,
                        schema=schema,
                    )
                    tgt_col_cid = build_db_canonical_id(
                        DatabaseEntityKind.COLUMN,
                        table=fk["target_table"],
                        column=fk["target_column"],
                        dialect=dialect,
                        schema=schema,
                    )
                    res.edges.append(
                        RelationshipRecord(
                            source=src_col_cid,
                            target=tgt_col_cid,
                            relationship="FOREIGN_KEY_TO",
                            evidence_class="AST_VERIFIED",
                            confidence="HIGH",
                            file=file_path,
                            start_line=1,
                            end_line=1,
                            evidence=f"FOREIGN KEY ({fk['column']}) REFERENCES {fk['target_table']}({fk['target_column']})",
                            status="FACT",
                            parser_version=PARSER_VERSION,
                            index_generation=index_generation,
                        )
                    )
        elif op == "CREATE_VIEW":
            vname = str(op_info.get("view_name") or "")
            if vname:
                vcid = build_db_canonical_id(
                    DatabaseEntityKind.VIEW,
                    table=vname,
                    dialect=dialect,
                    schema=schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=vcid,
                        kind=DatabaseEntityKind.VIEW.value,
                        name=vname,
                        dialect=dialect,
                        schema_name=schema,
                        table_name=vname,
                        framework="sql",
                        file_path=file_path,
                        start_line=1,
                        end_line=1,
                        evidence=str(op_info.get("normalized_sql") or "")[:160],
                    )
                )
        elif op == "CREATE_SEQUENCE":
            sname = str(op_info.get("sequence_name") or "")
            if sname:
                scid = build_db_canonical_id(
                    DatabaseEntityKind.SEQUENCE,
                    name=sname,
                    dialect=dialect,
                    schema=schema,
                )
                res.entities.append(
                    DatabaseEntity(
                        canonical_id=scid,
                        kind=DatabaseEntityKind.SEQUENCE.value,
                        name=sname,
                        dialect=dialect,
                        schema_name=schema,
                        framework="sql",
                        file_path=file_path,
                        start_line=1,
                        end_line=1,
                        evidence=str(op_info.get("normalized_sql") or "")[:160],
                    )
                )
        elif op == "ALTER_TABLE":
            for tbl in op_info.get("tables", []):
                affected_tables.add(tbl)
                for col in op_info.get("columns", []):
                    added_columns.append(f"{tbl}.{col}")

    if affected_tables:
        mig_cid = build_db_canonical_id(DatabaseEntityKind.MIGRATION, name=rev, module="sql")
        mig_fact = MigrationFact(
            migration_id=rev,
            canonical_id=mig_cid,
            system="sql",
            revision=rev,
            file_path=file_path,
            start_line=1,
            end_line=len(content.splitlines()),
            created_tables=tuple(sorted(set(created_tables))),
            added_columns=tuple(sorted(set(added_columns))),
            affected_tables=tuple(sorted(affected_tables)),
            evidence=f"SQL migration {file_path}",
        )
        res.migrations.append(mig_fact)
        for tbl in sorted(affected_tables):
            tbl_cid = build_db_canonical_id(
                DatabaseEntityKind.TABLE,
                table=tbl,
                dialect=dialect,
                schema=schema,
            )
            res.edges.append(
                RelationshipRecord(
                    source=mig_cid,
                    target=tbl_cid,
                    relationship="MIGRATES_TABLE",
                    evidence_class="AST_VERIFIED",
                    confidence="HIGH",
                    file=file_path,
                    start_line=1,
                    end_line=len(content.splitlines()),
                    evidence=f"SQL migration {rev} affects {tbl}",
                    status="FACT",
                    parser_version=PARSER_VERSION,
                    index_generation=index_generation,
                )
            )


def _extract_prisma_schema(
    content: str,
    file_path: str,
    dialect: str,
    schema: str,
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    for m in re.finditer(r"model\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([\s\S]*?)\}", content):
        model_name = m.group(1)
        body = m.group(2)
        map_m = re.search(r'@@map\(\s*"([^"]+)"\s*\)', body)
        tbl_name = (map_m.group(1) if map_m else _pluralize_table(_camel_to_snake(model_name))).lower()
        tbl_cid = build_db_canonical_id(
            DatabaseEntityKind.TABLE,
            table=tbl_name,
            dialect=dialect,
            schema=schema,
        )
        model_cid = f"prisma.{model_name}"
        res.entities.append(
            DatabaseEntity(
                canonical_id=model_cid,
                kind=DatabaseEntityKind.ORM_MODEL.value,
                name=model_name,
                dialect=dialect,
                schema_name=schema,
                table_name=tbl_name,
                orm_model_id=model_cid,
                framework="prisma",
                file_path=file_path,
                start_line=1,
                end_line=1,
                evidence=f"model {model_name}",
                evidence_class="FRAMEWORK_VERIFIED",
            )
        )
        res.entities.append(
            DatabaseEntity(
                canonical_id=tbl_cid,
                kind=DatabaseEntityKind.TABLE.value,
                name=tbl_name,
                dialect=dialect,
                schema_name=schema,
                table_name=tbl_name,
                orm_model_id=model_cid,
                framework="prisma",
                file_path=file_path,
                start_line=1,
                end_line=1,
                evidence=f"model {model_name}",
                evidence_class="FRAMEWORK_VERIFIED",
            )
        )
        res.edges.append(
            RelationshipRecord(
                source=model_cid,
                target=tbl_cid,
                relationship="MAPS_TO_TABLE",
                evidence_class="FRAMEWORK_VERIFIED",
                confidence="HIGH",
                file=file_path,
                start_line=1,
                end_line=1,
                evidence=f"model {model_name} -> {tbl_name}",
                status="FACT",
                parser_version=PARSER_VERSION,
                index_generation=index_generation,
            )
        )


def _extract_js_ts_database(
    content: str,
    file_path: str,
    module_name: str,
    dialect: str,
    schema: str,
    model_to_table: dict[str, str],
    index_generation: int,
    res: DatabaseExtractionResult,
) -> None:
    del model_to_table
    lines = content.splitlines()
    for line_no, raw_line in enumerate(lines, start=1):
        ev = redact_secrets(raw_line.strip())
        # Prisma client: prisma.user.findMany / prisma.order.create / update / delete
        for pm in re.finditer(
            r"\bprisma\.([a-zA-Z_][a-zA-Z0-9_]*)\.(findMany|findUnique|findFirst|count|create|createMany|update|updateMany|upsert|delete|deleteMany)\b",
            raw_line,
        ):
            model_prop = pm.group(1)
            method = pm.group(2)
            tbl = _pluralize_table(_camel_to_snake(model_prop))
            is_read = method.startswith(("find", "count"))
            op = "SELECT" if is_read else ("INSERT" if "create" in method else ("DELETE" if "delete" in method else "UPDATE"))
            rel = "READS_TABLE" if is_read else "WRITES_TABLE"
            _emit_query_fact_and_edges(
                caller_id=module_name,
                operation=op,
                relationship=rel,
                table_name=tbl,
                columns=(),
                read_columns=(),
                framework="prisma",
                normalized_sql=f"{op} {tbl}",
                dialect=dialect,
                schema=schema,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                evidence=ev,
                confidence="HIGH",
                evidence_class="FRAMEWORK_VERIFIED",
                status="FACT",
                index_generation=index_generation,
                res=res,
            )
        # Knex: knex("users").select / insert / update / del
        for km in re.finditer(
            r'\bknex\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\)\.(select|where|first|insert|update|del|delete)\b',
            raw_line,
        ):
            tbl = km.group(1).lower()
            method = km.group(2)
            is_read = method in ("select", "where", "first")
            op = "SELECT" if is_read else ("INSERT" if method == "insert" else ("DELETE" if method in ("del", "delete") else "UPDATE"))
            rel = "READS_TABLE" if is_read else "WRITES_TABLE"
            _emit_query_fact_and_edges(
                caller_id=module_name,
                operation=op,
                relationship=rel,
                table_name=tbl,
                columns=(),
                read_columns=(),
                framework="knex",
                normalized_sql=f"{op} {tbl}",
                dialect=dialect,
                schema=schema,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                evidence=ev,
                confidence="HIGH",
                evidence_class="FRAMEWORK_VERIFIED",
                status="FACT",
                index_generation=index_generation,
                res=res,
            )
