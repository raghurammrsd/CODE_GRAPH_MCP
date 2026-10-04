"""Canonical Database Schema & Evidence Models for CodeGraph (Phases 2, 3, 4, 5, 6, 7).

Provides deterministic canonical IDs and structured dataclasses for:
- Database
- Schema
- Table
- Column
- PrimaryKey
- ForeignKey
- Index
- UniqueConstraint
- CheckConstraint
- View
- Sequence
- Migration
- ORMModel

Architectural Rules:
1. Never assume database dialect or schema name when not statically provable; use `UNKNOWN` or `AMBIGUOUS`.
2. Every database entity and relationship carries source file, line range, parser version, index generation,
   relationship type, evidence class, confidence, and canonical IDs.
3. All connection strings and defaults pass through secret redaction before model construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from codegraph.security.redaction import redact_secrets


class DatabaseEntityKind(StrEnum):
    DATABASE = "Database"
    SCHEMA = "Schema"
    TABLE = "Table"
    COLUMN = "Column"
    PRIMARY_KEY = "PrimaryKey"
    FOREIGN_KEY = "ForeignKey"
    INDEX = "Index"
    UNIQUE_CONSTRAINT = "UniqueConstraint"
    CHECK_CONSTRAINT = "CheckConstraint"
    VIEW = "View"
    SEQUENCE = "Sequence"
    MIGRATION = "Migration"
    ORM_MODEL = "ORMModel"


def normalize_dialect(raw_dialect: str | None) -> str:
    """Normalize database dialect/provider string, defaulting to UNKNOWN when unproven."""
    if not raw_dialect:
        return "UNKNOWN"
    val = raw_dialect.strip().lower()
    if val in ("amg", "ambiguous"):
        return "AMBIGUOUS"
    if val in ("unknown", ""):
        return "UNKNOWN"
    if val.startswith(("postgres", "psycopg", "asyncpg", "pg")):
        return "postgres"
    if val.startswith(("mysql", "pymysql", "mariadb")):
        return "mysql"
    if val.startswith(("sqlite", "aiosqlite")):
        return "sqlite"
    if val.startswith(("mongo", "mongodb")):
        return "mongodb"
    if val.startswith("redis"):
        return "redis"
    if val.startswith(("mssql", "sqlserver")):
        return "mssql"
    return val


def normalize_schema_name(raw_schema: str | None, dialect: str = "UNKNOWN") -> str:
    """Normalize schema name without fabricating unproven schemas."""
    if raw_schema and raw_schema.strip():
        s = raw_schema.strip()
        if s.upper() in ("UNKNOWN", "AMBIGUOUS"):
            return s.upper()
        return s.lower()
    norm_dialect = normalize_dialect(dialect)
    if norm_dialect == "postgres":
        return "public"
    if norm_dialect == "sqlite":
        return "main"
    if norm_dialect == "AMBIGUOUS":
        return "AMBIGUOUS"
    return "UNKNOWN"


def build_db_canonical_id(
    kind: DatabaseEntityKind | str,
    table: str = "",
    column: str = "",
    name: str = "",
    dialect: str = "UNKNOWN",
    schema: str = "UNKNOWN",
    module: str = "",
) -> str:
    """Build a deterministic canonical ID for any database entity.

    Examples:
        Table:      db.postgres.public.users  or  db.UNKNOWN.UNKNOWN.users
        Column:     db.postgres.public.users.id
        PrimaryKey: db.postgres.public.users.pk.id
        ForeignKey: db.postgres.public.orders.fk.user_id
        Index:      db.postgres.public.users.idx.ix_users_email
        Migration:  db.migration.alembic.0001_initial
        ORMModel:   orm.app.models.User
    """
    k_str = kind.value if isinstance(kind, DatabaseEntityKind) else str(kind)
    d = normalize_dialect(dialect)
    s = normalize_schema_name(schema, d)
    tbl = table.strip().lower() if table else ""
    col = column.strip().lower() if column else ""
    nm = name.strip() if name else ""

    if k_str == DatabaseEntityKind.DATABASE.value:
        return f"db.{d}.{nm.lower() or s}"
    if k_str == DatabaseEntityKind.SCHEMA.value:
        return f"db.{d}.{nm.lower() or s}"
    if k_str == DatabaseEntityKind.TABLE.value:
        return f"db.{d}.{s}.{tbl or nm.lower() or 'unknown'}"
    if k_str == DatabaseEntityKind.VIEW.value:
        return f"db.{d}.{s}.view.{tbl or nm.lower() or 'unknown'}"
    if k_str == DatabaseEntityKind.SEQUENCE.value:
        return f"db.{d}.{s}.seq.{nm.lower() or tbl or 'unknown'}"
    if k_str == DatabaseEntityKind.COLUMN.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.{col or nm.lower() or 'unknown'}"
    if k_str == DatabaseEntityKind.PRIMARY_KEY.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.pk.{col or nm.lower() or 'pk'}"
    if k_str == DatabaseEntityKind.FOREIGN_KEY.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.fk.{col or nm.lower() or 'fk'}"
    if k_str == DatabaseEntityKind.INDEX.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.idx.{nm.lower() or col or 'idx'}"
    if k_str == DatabaseEntityKind.UNIQUE_CONSTRAINT.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.uq.{nm.lower() or col or 'uq'}"
    if k_str == DatabaseEntityKind.CHECK_CONSTRAINT.value:
        return f"db.{d}.{s}.{tbl or 'unknown'}.ck.{nm.lower() or 'ck'}"
    if k_str == DatabaseEntityKind.MIGRATION.value:
        sys_name = (module or "sql").strip().lower()
        return f"db.migration.{sys_name}.{nm or 'unknown'}"
    if k_str == DatabaseEntityKind.ORM_MODEL.value:
        if module:
            return f"{module}.{nm}"
        return f"orm.{nm}"
    return f"db.{d}.{s}.{nm.lower() or tbl or 'unknown'}"


@dataclass(frozen=True)
class DatabaseEntity:
    """Canonical representation of a discovered database schema or ORM entity."""

    canonical_id: str
    kind: str  # DatabaseEntityKind value
    name: str
    dialect: str = "UNKNOWN"
    schema_name: str = "UNKNOWN"
    table_name: str = ""
    column_name: str = ""
    data_type: str = ""
    nullable: bool = True
    default_value: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_unique: bool = False
    is_indexed: bool = False
    target_table: str | None = None
    target_column: str | None = None
    orm_model_id: str | None = None
    framework: str = ""
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    evidence: str = ""
    confidence: str = "HIGH"
    evidence_class: str = "AST_VERIFIED"
    status: str = "FACT"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_value is not None:
            object.__setattr__(self, "default_value", redact_secrets(str(self.default_value)))
        if self.evidence:
            object.__setattr__(self, "evidence", redact_secrets(self.evidence))

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "kind": self.kind,
            "name": self.name,
            "dialect": self.dialect,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "default_value": self.default_value,
            "is_primary_key": self.is_primary_key,
            "is_foreign_key": self.is_foreign_key,
            "is_unique": self.is_unique,
            "is_indexed": self.is_indexed,
            "target_table": self.target_table,
            "target_column": self.target_column,
            "orm_model_id": self.orm_model_id,
            "framework": self.framework,
            "file_path": self.file_path,
            "file": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DatabaseQueryFact:
    """Static database query or ORM operation extracted from source code."""

    query_id: str
    caller_symbol_id: str
    operation: str  # SELECT | INSERT | UPDATE | DELETE | DDL | UNKNOWN
    relationship: str  # READS_TABLE | WRITES_TABLE | POSSIBLE_TABLE | UNKNOWN_TABLE | QUERIES_DATABASE
    table_name: str  # table name or UNKNOWN / POSSIBLE candidate
    table_canonical_id: str
    columns: tuple[str, ...] = ()
    framework: str = "raw_sql"
    normalized_sql: str = ""
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    evidence: str = ""
    confidence: str = "HIGH"
    evidence_class: str = "AST_VERIFIED"
    status: str = "FACT"

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "caller_symbol_id": self.caller_symbol_id,
            "symbol": self.caller_symbol_id,
            "operation": self.operation,
            "relationship": self.relationship,
            "table_name": self.table_name,
            "table_canonical_id": self.table_canonical_id,
            "columns": list(self.columns),
            "framework": self.framework,
            "normalized_sql": self.normalized_sql,
            "file_path": self.file_path,
            "file": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
            "status": self.status,
        }


@dataclass(frozen=True)
class MigrationFact:
    """Extracted schema migration record (Alembic, Django migrations, Prisma, raw SQL)."""

    migration_id: str
    canonical_id: str
    system: str  # alembic | django | prisma | sql
    revision: str
    down_revision: str | None = None
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    created_tables: tuple[str, ...] = ()
    dropped_tables: tuple[str, ...] = ()
    added_columns: tuple[str, ...] = ()  # "table.column"
    removed_columns: tuple[str, ...] = ()  # "table.column"
    renamed_columns: tuple[str, ...] = ()  # "table.old_col->new_col"
    indexes: tuple[str, ...] = ()
    foreign_keys: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    affected_tables: tuple[str, ...] = ()
    evidence: str = ""
    confidence: str = "HIGH"
    evidence_class: str = "AST_VERIFIED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "canonical_id": self.canonical_id,
            "system": self.system,
            "revision": self.revision,
            "down_revision": self.down_revision,
            "file_path": self.file_path,
            "file": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "created_tables": list(self.created_tables),
            "dropped_tables": list(self.dropped_tables),
            "added_columns": list(self.added_columns),
            "removed_columns": list(self.removed_columns),
            "renamed_columns": list(self.renamed_columns),
            "indexes": list(self.indexes),
            "foreign_keys": list(self.foreign_keys),
            "constraints": list(self.constraints),
            "affected_tables": list(self.affected_tables),
            "evidence": self.evidence,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
        }
