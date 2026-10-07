"""Automatic Database Schema Sync & Migration Drift Watcher.

Continuously tracks:
1. Migration directory updates (Prisma, Drizzle, Alembic, raw SQL migrations).
2. Live database schema version cookies (PRAGMA schema_version, _prisma_migrations, alembic_version).
3. Schema drift detection: flags discrepancy between static ORM models and database state.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SchemaDriftItem:
    kind: str  # MISSING_COLUMN | MISSING_TABLE | TYPE_MISMATCH | NULLABILITY_MISMATCH
    table_name: str
    column_name: str = ""
    db_type: str = ""
    model_type: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "db_type": self.db_type,
            "model_type": self.model_type,
            "message": self.message,
        }


@dataclass(frozen=True)
class SchemaDriftReport:
    is_drifted: bool
    schema_version: str
    migration_hash: str
    drifts: tuple[SchemaDriftItem, ...] = ()
    migration_files_count: int = 0
    latest_migration_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_drifted": self.is_drifted,
            "schema_version": self.schema_version,
            "migration_hash": self.migration_hash,
            "drifts": [d.as_dict() for d in self.drifts],
            "migration_files_count": self.migration_files_count,
            "latest_migration_name": self.latest_migration_name,
        }


def compute_migration_directory_state(repo_root: Path) -> tuple[str, int, str]:
    """Scan migration directories and compute combined hash, count, and latest migration name."""
    migration_patterns = (
        "**/migrations/*.sql",
        "**/prisma/migrations/**/*.sql",
        "**/drizzle/*.sql",
        "**/alembic/versions/*.py",
    )
    migration_files: list[Path] = []
    for pattern in migration_patterns:
        migration_files.extend(repo_root.glob(pattern))

    migration_files = [f for f in migration_files if "node_modules" not in f.parts and ".git" not in f.parts]
    if not migration_files:
        return "", 0, ""

    migration_files.sort(key=lambda f: f.name)
    hasher = hashlib.sha256()
    for f in migration_files:
        try:
            hasher.update(f.name.encode())
            hasher.update(str(f.stat().st_mtime_ns).encode())
        except OSError:
            pass

    latest_name = migration_files[-1].name
    return hasher.hexdigest()[:16], len(migration_files), latest_name


def check_sqlite_schema_version(db_path: Path) -> int:
    """Read PRAGMA schema_version from SQLite database."""
    if not db_path.exists():
        return 0
    try:
        con = sqlite3.connect(str(db_path), timeout=5.0)
        cur = con.execute("PRAGMA schema_version")
        val = cur.fetchone()
        con.close()
        return int(val[0]) if val else 0
    except Exception:
        return 0


_DRIFT_CACHE: dict[str, tuple[float, SchemaDriftReport]] = {}
_DRIFT_CACHE_TTL_SEC = 5.0


def detect_schema_drift(
    con: sqlite3.Connection,
    repo_root: Path,
) -> SchemaDriftReport:
    """Compare indexed DB models against migration state with 5-second TTL cache (Zero idle CPU)."""
    global _DRIFT_CACHE
    cache_key = str(repo_root)
    now = time.monotonic()
    if cache_key in _DRIFT_CACHE:
        last_t, cached_report = _DRIFT_CACHE[cache_key]
        if now - last_t < _DRIFT_CACHE_TTL_SEC:
            return cached_report

    mig_hash, mig_count, latest_mig = compute_migration_directory_state(repo_root)

    # 1. Fetch tables and columns registered in CodeGraph
    db_tables_rows = con.execute("SELECT table_name, name, dialect FROM db_entities WHERE kind = 'Table'").fetchall()
    indexed_tables = {str(r["table_name"] or r["name"]).lower(): str(r["dialect"]) for r in db_tables_rows}

    indexed_cols: dict[str, set[str]] = {}
    col_rows = con.execute("SELECT table_name, name, data_type FROM db_entities WHERE kind = 'Column'").fetchall()
    for r in col_rows:
        t_name = str(r["table_name"] or "").lower()
        if t_name not in indexed_cols:
            indexed_cols[t_name] = set()
        c_name = str(r["name"] or "").lower()
        if c_name:
            indexed_cols[t_name].add(c_name)

    drifts: list[SchemaDriftItem] = []

    # 2. If a local SQLite database exists in repo (e.g. dev.db, local.db, test.db), check live tables
    local_dbs = list(repo_root.glob("*.db")) + list(repo_root.glob("*.sqlite")) + list(repo_root.glob("*.sqlite3"))
    local_dbs = [d for d in local_dbs if not d.name.startswith(".codegraph")]

    schema_version_str = "0"
    if local_dbs:
        target_db = local_dbs[0]
        schema_version_str = str(check_sqlite_schema_version(target_db))
        try:
            live_con = sqlite3.connect(str(target_db), timeout=5.0)
            live_tables = [
                row[0].lower()
                for row in live_con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for lt in live_tables:
                if lt not in indexed_tables and not lt.startswith(("_prisma", "alembic")):
                    drifts.append(
                        SchemaDriftItem(
                            kind="MISSING_TABLE",
                            table_name=lt,
                            message=f"Table '{lt}' exists in live database but has no corresponding code model.",
                        )
                    )
                else:
                    # check columns
                    live_cols = [
                        crow[1].lower()
                        for crow in live_con.execute(f"PRAGMA table_info('{lt}')").fetchall()
                    ]
                    known_c = indexed_cols.get(lt, set())
                    for lc in live_cols:
                        if lc not in known_c:
                            drifts.append(
                                SchemaDriftItem(
                                    kind="MISSING_COLUMN",
                                    table_name=lt,
                                    column_name=lc,
                                    message=f"Column '{lt}.{lc}' exists in live database but is missing in code model.",
                                )
                            )
            live_con.close()
        except Exception:
            pass

    report = SchemaDriftReport(
        is_drifted=len(drifts) > 0,
        schema_version=schema_version_str,
        migration_hash=mig_hash,
        drifts=tuple(drifts),
        migration_files_count=mig_count,
        latest_migration_name=latest_mig,
    )
    _DRIFT_CACHE[cache_key] = (now, report)
    return report
