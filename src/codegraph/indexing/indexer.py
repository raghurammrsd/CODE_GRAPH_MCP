"""Incremental SQLite indexer with atomic per-file transactions and reference resolution.

Architectural Invariants:
1. Normalized SQLite storage with PRAGMA foreign_keys = ON and ON DELETE CASCADE.
2. Explicit FTS5 synchronization on every chunk insertion and deletion.
3. Parse-failure safety: if a file has syntax errors, its last-known-good index state is
   retained, marked 'parse_failed', and reported in freshness without corrupting the DB.
4. Reference resolution runs globally after file parsing, turning raw source facts into
   verified references, graph edges, and evidence.
5. Parser version and schema version participate in cache and index validity.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from codegraph.config import Settings
from codegraph.evidence_contract import RelationshipRecord
from codegraph.frameworks import RouteDetection
from codegraph.resolver import (
    DEFAULT_MAX_REEXPORT_DEPTH,
    DEFAULT_MAX_WILDCARD_EXPANSIONS,
    ReferenceResolver,
)
from codegraph.resources import (
    ResourceGovernor,
    TaskPriority,
    get_global_governor,
    get_parse_cache,
)

from .classifier import classify_file_detailed, make_compat_row
from .models import (
    BindingRef,
    CallRef,
    ImportRef,
    InheritanceRef,
    Symbol,
)
from .parser import PARSER_VERSION, parse
from .scanner import scan
from .telemetry import IndexingTelemetry, get_process_rss_mb

SCHEMA_VERSION = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS codegraph_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path            TEXT PRIMARY KEY,
    hash            TEXT NOT NULL,
    language        TEXT NOT NULL,
    indexed_at      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'ok',
    parse_error     TEXT,
    last_valid_hash TEXT,
    category        TEXT NOT NULL DEFAULT 'SOURCE'
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    language    TEXT NOT NULL,
    symbol      TEXT,
    symbol_type TEXT,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    hash        TEXT NOT NULL,
    FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content, path UNINDEXED, symbol UNINDEXED
);

CREATE TABLE IF NOT EXISTS symbols (
    name             TEXT NOT NULL,
    qualified_name   TEXT NOT NULL,
    kind             TEXT NOT NULL,
    path             TEXT NOT NULL,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    decorators       TEXT NOT NULL DEFAULT '',
    id               TEXT NOT NULL DEFAULT '',
    canonical_id     TEXT NOT NULL DEFAULT '',
    language         TEXT NOT NULL DEFAULT 'python',
    module           TEXT NOT NULL DEFAULT '',
    scope            TEXT NOT NULL DEFAULT '',
    signature        TEXT NOT NULL DEFAULT '',
    content_hash     TEXT NOT NULL DEFAULT '',
    parent_symbol_id TEXT,
    visibility       TEXT NOT NULL DEFAULT 'public',
    return_type      TEXT,
    parameter_count  INTEGER,
    documentation    TEXT,
    FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols (name);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols (qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_canonical ON symbols (canonical_id);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols (path);
CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols (parent_symbol_id);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks (path);
CREATE INDEX IF NOT EXISTS idx_chunks_symbol ON chunks (symbol);
CREATE INDEX IF NOT EXISTS idx_chunks_path_symbol ON chunks (path, symbol);

CREATE TABLE IF NOT EXISTS imports (
    source_path     TEXT NOT NULL,
    module          TEXT NOT NULL,
    name            TEXT,
    alias           TEXT,
    full_name       TEXT,
    line            INTEGER NOT NULL DEFAULT 1,
    source_module   TEXT NOT NULL DEFAULT '',
    imported_module TEXT NOT NULL DEFAULT '',
    imported_name   TEXT,
    local_name      TEXT NOT NULL DEFAULT '',
    import_type     TEXT NOT NULL DEFAULT 'module',
    resolved_path   TEXT,
    resolved_module TEXT,
    FOREIGN KEY(source_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_imports_source ON imports (source_path);
CREATE INDEX IF NOT EXISTS idx_imports_source_line ON imports (source_path, line);
CREATE INDEX IF NOT EXISTS idx_imports_module ON imports (module);
CREATE INDEX IF NOT EXISTS idx_imports_imported_module ON imports (imported_module);

CREATE TABLE IF NOT EXISTS calls (
    source_path        TEXT NOT NULL,
    callee             TEXT NOT NULL,
    qualified_callee   TEXT,
    line               INTEGER NOT NULL DEFAULT 1,
    confidence         TEXT NOT NULL DEFAULT 'LOW',
    source_symbol_id   TEXT,
    resolved_symbol_id TEXT,
    FOREIGN KEY(source_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_calls_source ON calls (source_path);
CREATE INDEX IF NOT EXISTS idx_calls_source_line ON calls (source_path, line, callee);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls (callee);
CREATE INDEX IF NOT EXISTS idx_calls_resolved ON calls (resolved_symbol_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee_source ON calls (callee, source_path);

CREATE TABLE IF NOT EXISTS inheritance (
    source_symbol       TEXT NOT NULL,
    base_name           TEXT NOT NULL,
    relationship        TEXT NOT NULL,
    source_file         TEXT NOT NULL,
    line                INTEGER NOT NULL DEFAULT 1,
    source_canonical_id TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(source_file) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inh_source ON inheritance (source_file);

CREATE TABLE IF NOT EXISTS raw_framework_routes (
    endpoint_id          TEXT PRIMARY KEY,
    framework            TEXT NOT NULL,
    http_method          TEXT NOT NULL,
    route_path           TEXT NOT NULL,
    normalized_route     TEXT NOT NULL,
    handler_name         TEXT NOT NULL,
    handler_canonical_id TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    router_name          TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_raw_routes_file ON raw_framework_routes (file_path);
CREATE INDEX IF NOT EXISTS idx_raw_routes_path ON raw_framework_routes (route_path);

CREATE TABLE IF NOT EXISTS router_mounts (
    mount_id             TEXT PRIMARY KEY,
    framework            TEXT NOT NULL,
    parent_router        TEXT NOT NULL,
    child_router         TEXT NOT NULL,
    prefix               TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mounts_file ON router_mounts (file_path);

CREATE TABLE IF NOT EXISTS router_definitions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    framework            TEXT NOT NULL,
    router_name          TEXT NOT NULL,
    prefix               TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    evidence             TEXT NOT NULL,
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_router_defs_file ON router_definitions (file_path);

CREATE TABLE IF NOT EXISTS local_bindings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name          TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    column               INTEGER,
    scope                TEXT NOT NULL DEFAULT '',
    expr_kind            TEXT NOT NULL DEFAULT 'IDENTIFIER',
    source_expr          TEXT NOT NULL DEFAULT '',
    is_conditional       INTEGER NOT NULL DEFAULT 0,
    base_expr            TEXT NOT NULL DEFAULT '',
    attr_name            TEXT NOT NULL DEFAULT '',
    dict_entries_json    TEXT NOT NULL DEFAULT '[]',
    list_entries_json    TEXT NOT NULL DEFAULT '[]',
    subscript_target     TEXT,
    subscript_key        TEXT,
    subscript_index      INTEGER,
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bindings_file ON local_bindings (file_path);
CREATE INDEX IF NOT EXISTS idx_bindings_target ON local_bindings (target_name);
CREATE INDEX IF NOT EXISTS idx_bindings_file_target ON local_bindings (file_path, target_name);

CREATE TABLE IF NOT EXISTS framework_routes (
    endpoint_id          TEXT PRIMARY KEY,
    framework            TEXT NOT NULL,
    http_method          TEXT NOT NULL,
    route_path           TEXT NOT NULL,
    normalized_route     TEXT NOT NULL,
    handler_name         TEXT NOT NULL,
    handler_canonical_id TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    line                 INTEGER NOT NULL,
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routes_file ON framework_routes (file_path);
CREATE INDEX IF NOT EXISTS idx_routes_handler ON framework_routes (handler_canonical_id);
CREATE INDEX IF NOT EXISTS idx_routes_path ON framework_routes (route_path);

CREATE TABLE IF NOT EXISTS "references" (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id TEXT NOT NULL,
    target_symbol_id TEXT,
    relationship     TEXT NOT NULL,
    confidence       TEXT NOT NULL,
    path             TEXT NOT NULL,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    evidence         TEXT NOT NULL DEFAULT '',
    source_hash      TEXT NOT NULL DEFAULT '',
    indexed_commit   TEXT,
    evidence_status  TEXT NOT NULL DEFAULT 'current',
    FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_refs_source ON "references" (source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON "references" (target_symbol_id);
CREATE INDEX IF NOT EXISTS idx_refs_path ON "references" (path);
CREATE INDEX IF NOT EXISTS idx_refs_rel ON "references" (relationship);

CREATE TABLE IF NOT EXISTS graph_edges (
    source           TEXT NOT NULL,
    target           TEXT NOT NULL,
    relationship     TEXT NOT NULL,
    confidence       TEXT NOT NULL,
    file             TEXT NOT NULL,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    evidence         TEXT NOT NULL DEFAULT '',
    evidence_id      TEXT NOT NULL DEFAULT '',
    source_hash      TEXT NOT NULL DEFAULT '',
    indexed_commit   TEXT,
    evidence_class   TEXT NOT NULL DEFAULT 'AST_VERIFIED',
    reason           TEXT,
    FOREIGN KEY(file) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges (source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges (target);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON graph_edges (relationship);
CREATE INDEX IF NOT EXISTS idx_edges_file ON graph_edges (file);
CREATE INDEX IF NOT EXISTS idx_edges_evidence ON graph_edges (evidence_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_rel ON graph_edges (target, relationship);
CREATE INDEX IF NOT EXISTS idx_edges_source_rel ON graph_edges (source, relationship);

CREATE TABLE IF NOT EXISTS context_cache (
    cache_key  TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS db_entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id    TEXT NOT NULL,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    dialect         TEXT NOT NULL DEFAULT 'UNKNOWN',
    schema_name     TEXT NOT NULL DEFAULT 'UNKNOWN',
    table_name      TEXT NOT NULL DEFAULT '',
    column_name     TEXT NOT NULL DEFAULT '',
    data_type       TEXT NOT NULL DEFAULT '',
    nullable        INTEGER NOT NULL DEFAULT 1,
    default_value   TEXT,
    is_primary_key  INTEGER NOT NULL DEFAULT 0,
    is_foreign_key  INTEGER NOT NULL DEFAULT 0,
    is_unique       INTEGER NOT NULL DEFAULT 0,
    is_indexed      INTEGER NOT NULL DEFAULT 0,
    target_table    TEXT,
    target_column   TEXT,
    orm_model_id    TEXT,
    framework       TEXT NOT NULL DEFAULT '',
    file_path       TEXT NOT NULL,
    start_line      INTEGER NOT NULL DEFAULT 1,
    end_line        INTEGER NOT NULL DEFAULT 1,
    evidence        TEXT NOT NULL DEFAULT '',
    confidence      TEXT NOT NULL DEFAULT 'HIGH',
    evidence_class  TEXT NOT NULL DEFAULT 'AST_VERIFIED',
    status          TEXT NOT NULL DEFAULT 'FACT',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_db_entities_canonical ON db_entities (canonical_id);
CREATE INDEX IF NOT EXISTS idx_db_entities_kind ON db_entities (kind);
CREATE INDEX IF NOT EXISTS idx_db_entities_table ON db_entities (table_name);
CREATE INDEX IF NOT EXISTS idx_db_entities_file ON db_entities (file_path);

CREATE TABLE IF NOT EXISTS db_queries (
    query_id           TEXT PRIMARY KEY,
    caller_symbol_id   TEXT NOT NULL,
    operation          TEXT NOT NULL,
    relationship       TEXT NOT NULL,
    table_name         TEXT NOT NULL,
    table_canonical_id TEXT NOT NULL,
    columns_json       TEXT NOT NULL DEFAULT '[]',
    framework          TEXT NOT NULL DEFAULT 'raw_sql',
    normalized_sql     TEXT NOT NULL DEFAULT '',
    file_path          TEXT NOT NULL,
    start_line         INTEGER NOT NULL DEFAULT 1,
    end_line           INTEGER NOT NULL DEFAULT 1,
    evidence           TEXT NOT NULL DEFAULT '',
    confidence         TEXT NOT NULL DEFAULT 'HIGH',
    evidence_class     TEXT NOT NULL DEFAULT 'AST_VERIFIED',
    status             TEXT NOT NULL DEFAULT 'FACT',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_db_queries_caller ON db_queries (caller_symbol_id);
CREATE INDEX IF NOT EXISTS idx_db_queries_table ON db_queries (table_name);
CREATE INDEX IF NOT EXISTS idx_db_queries_op ON db_queries (operation);
CREATE INDEX IF NOT EXISTS idx_db_queries_file ON db_queries (file_path);

CREATE TABLE IF NOT EXISTS db_migrations (
    migration_id         TEXT PRIMARY KEY,
    canonical_id         TEXT NOT NULL,
    system               TEXT NOT NULL,
    revision             TEXT NOT NULL,
    down_revision        TEXT,
    file_path            TEXT NOT NULL,
    start_line           INTEGER NOT NULL DEFAULT 1,
    end_line             INTEGER NOT NULL DEFAULT 1,
    created_tables_json  TEXT NOT NULL DEFAULT '[]',
    dropped_tables_json  TEXT NOT NULL DEFAULT '[]',
    added_columns_json   TEXT NOT NULL DEFAULT '[]',
    removed_columns_json TEXT NOT NULL DEFAULT '[]',
    renamed_columns_json TEXT NOT NULL DEFAULT '[]',
    indexes_json         TEXT NOT NULL DEFAULT '[]',
    foreign_keys_json    TEXT NOT NULL DEFAULT '[]',
    constraints_json     TEXT NOT NULL DEFAULT '[]',
    affected_tables_json TEXT NOT NULL DEFAULT '[]',
    evidence             TEXT NOT NULL DEFAULT '',
    confidence           TEXT NOT NULL DEFAULT 'HIGH',
    evidence_class       TEXT NOT NULL DEFAULT 'AST_VERIFIED',
    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_db_migrations_file ON db_migrations (file_path);
CREATE INDEX IF NOT EXISTS idx_db_migrations_rev ON db_migrations (revision);

CREATE TABLE IF NOT EXISTS runtime_observations (
    event_id           TEXT PRIMARY KEY,
    trace_id           TEXT NOT NULL,
    span_id            TEXT NOT NULL,
    parent_span_id     TEXT NOT NULL DEFAULT '',
    timestamp          TEXT NOT NULL DEFAULT '',
    source_format      TEXT NOT NULL DEFAULT 'json',
    http_method        TEXT NOT NULL DEFAULT '',
    route_path         TEXT NOT NULL DEFAULT '',
    handler_symbol     TEXT NOT NULL DEFAULT '',
    caller_symbol      TEXT NOT NULL DEFAULT '',
    callee_symbol      TEXT NOT NULL DEFAULT '',
    service_name       TEXT NOT NULL DEFAULT '',
    db_operation       TEXT NOT NULL DEFAULT '',
    db_table           TEXT NOT NULL DEFAULT '',
    db_columns_json    TEXT NOT NULL DEFAULT '[]',
    normalized_sql     TEXT NOT NULL DEFAULT '',
    status_code        INTEGER,
    exception_type     TEXT NOT NULL DEFAULT '',
    duration_ms        REAL NOT NULL DEFAULT 0.0,
    evidence_class     TEXT NOT NULL DEFAULT 'RUNTIME_OBSERVED',
    runtime_generation INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_rt_obs_trace ON runtime_observations (trace_id);
CREATE INDEX IF NOT EXISTS idx_rt_obs_route ON runtime_observations (route_path);
CREATE INDEX IF NOT EXISTS idx_rt_obs_caller ON runtime_observations (caller_symbol);
CREATE INDEX IF NOT EXISTS idx_rt_obs_table ON runtime_observations (db_table);

CREATE TABLE IF NOT EXISTS runtime_edges (
    edge_id            TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    target             TEXT NOT NULL,
    relationship       TEXT NOT NULL,
    operation          TEXT NOT NULL DEFAULT '',
    evidence_class     TEXT NOT NULL DEFAULT 'RUNTIME_OBSERVED',
    observation_count  INTEGER NOT NULL DEFAULT 1,
    first_seen         TEXT NOT NULL DEFAULT '',
    last_seen          TEXT NOT NULL DEFAULT '',
    avg_duration_ms    REAL NOT NULL DEFAULT 0.0,
    max_duration_ms    REAL NOT NULL DEFAULT 0.0,
    sample_trace_id    TEXT NOT NULL DEFAULT '',
    sample_span_id     TEXT NOT NULL DEFAULT '',
    normalized_sql     TEXT NOT NULL DEFAULT '',
    status_code        INTEGER,
    exception_type     TEXT NOT NULL DEFAULT '',
    runtime_generation INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_rt_edges_source ON runtime_edges (source);
CREATE INDEX IF NOT EXISTS idx_rt_edges_target ON runtime_edges (target);
CREATE INDEX IF NOT EXISTS idx_rt_edges_rel ON runtime_edges (relationship);
"""


_DB_EDGE_RELATIONSHIPS = (
    "MAPS_TO_TABLE",
    "FOREIGN_KEY_TO",
    "READS_TABLE",
    "WRITES_TABLE",
    "UPDATES_TABLE",
    "DELETES_FROM_TABLE",
    "REFERENCES_COLUMN",
    "MIGRATES_TABLE",
)


class Indexer:
    def __init__(
        self,
        repository: Path,
        settings: Settings | None = None,
        governor: ResourceGovernor | None = None,
        *,
        commit_batch_size: int = 500,
        max_reexport_depth: int = DEFAULT_MAX_REEXPORT_DEPTH,
        max_wildcard_expansions: int = DEFAULT_MAX_WILDCARD_EXPANSIONS,
    ) -> None:
        self.repository = repository.resolve(strict=True)
        self.settings = settings or Settings()
        self.db_path = self.settings.db_path or self.repository / ".codegraph.sqlite3"
        self.governor = governor or get_global_governor()
        self.commit_batch_size = max(1, commit_batch_size)
        self.max_reexport_depth = max_reexport_depth
        self.max_wildcard_expansions = max_wildcard_expansions
        self.last_epistemic_findings: list[dict[str, object]] = []
        self.last_telemetry: IndexingTelemetry | None = None

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = make_compat_row
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        self._ensure_schema(con)
        return con

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on failure, always close handle."""
        con = self.connect()
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _ensure_schema(self, con: sqlite3.Connection) -> None:
        """Migrate schema via PRAGMA user_version non-destructively."""
        current_version = con.execute("PRAGMA user_version").fetchone()[0]

        if current_version == 0:
            try:
                row = con.execute("SELECT version FROM schema_version").fetchone()
                if row:
                    current_version = int(row[0])
            except sqlite3.OperationalError:
                pass

        target_version = SCHEMA_VERSION

        if current_version < target_version:
            if current_version > 0:
                self._migrate_schema(con, current_version, target_version)
            else:
                con.executescript(SCHEMA)

            con.execute(f"PRAGMA user_version = {target_version}")
            try:
                con.execute("DROP TABLE IF EXISTS schema_version")
            except sqlite3.OperationalError:
                pass
            con.commit()
        else:
            existing_core = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('files', 'symbols', 'graph_edges', 'db_tables', 'runtime_traces')"
            ).fetchone()[0]
            if existing_core < 5:
                con.executescript(SCHEMA)
                con.commit()

    def _migrate_schema(
        self, con: sqlite3.Connection, from_version: int, to_version: int
    ) -> None:
        """Non-destructive schema migration using ALTER TABLE."""
        del from_version, to_version
        # Ensure new tables and indexes are created
        con.executescript(SCHEMA)

        # Add missing columns to existing tables
        def existing_columns(tbl: str) -> set[str]:
            try:
                return {
                    str(r["name"])
                    for r in con.execute(f"PRAGMA table_info({tbl})").fetchall()
                }
            except sqlite3.OperationalError:
                return set()

        files_cols = existing_columns("files")
        if "status" not in files_cols:
            con.execute("ALTER TABLE files ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'")
        if "parse_error" not in files_cols:
            con.execute("ALTER TABLE files ADD COLUMN parse_error TEXT")
        if "last_valid_hash" not in files_cols:
            con.execute("ALTER TABLE files ADD COLUMN last_valid_hash TEXT")
        if "category" not in files_cols:
            con.execute("ALTER TABLE files ADD COLUMN category TEXT NOT NULL DEFAULT 'SOURCE'")

        symbols_cols = existing_columns("symbols")
        for col_def in (
            ("id", "TEXT NOT NULL DEFAULT ''"),
            ("canonical_id", "TEXT NOT NULL DEFAULT ''"),
            ("language", "TEXT NOT NULL DEFAULT 'python'"),
            ("module", "TEXT NOT NULL DEFAULT ''"),
            ("scope", "TEXT NOT NULL DEFAULT ''"),
            ("signature", "TEXT NOT NULL DEFAULT ''"),
            ("content_hash", "TEXT NOT NULL DEFAULT ''"),
            ("parent_symbol_id", "TEXT"),
            ("visibility", "TEXT NOT NULL DEFAULT 'public'"),
            ("return_type", "TEXT"),
            ("parameter_count", "INTEGER"),
            ("documentation", "TEXT"),
        ):
            if col_def[0] not in symbols_cols:
                con.execute(f"ALTER TABLE symbols ADD COLUMN {col_def[0]} {col_def[1]}")

        imports_cols = existing_columns("imports")
        for col_def in (
            ("source_module", "TEXT NOT NULL DEFAULT ''"),
            ("imported_module", "TEXT NOT NULL DEFAULT ''"),
            ("imported_name", "TEXT"),
            ("local_name", "TEXT NOT NULL DEFAULT ''"),
            ("import_type", "TEXT NOT NULL DEFAULT 'module'"),
            ("resolved_path", "TEXT"),
            ("resolved_module", "TEXT"),
        ):
            if col_def[0] not in imports_cols:
                con.execute(f"ALTER TABLE imports ADD COLUMN {col_def[0]} {col_def[1]}")

        files_cols = existing_columns("files")
        if "category" not in files_cols:
            con.execute("ALTER TABLE files ADD COLUMN category TEXT NOT NULL DEFAULT 'SOURCE'")

        calls_cols = existing_columns("calls")
        for col_def in (
            ("source_symbol_id", "TEXT"),
            ("resolved_symbol_id", "TEXT"),
        ):
            if col_def[0] not in calls_cols:
                con.execute(f"ALTER TABLE calls ADD COLUMN {col_def[0]} {col_def[1]}")

        edges_cols = existing_columns("graph_edges")
        if "evidence_class" not in edges_cols:
            con.execute("ALTER TABLE graph_edges ADD COLUMN evidence_class TEXT NOT NULL DEFAULT 'AST_VERIFIED'")
        if "reason" not in edges_cols:
            con.execute("ALTER TABLE graph_edges ADD COLUMN reason TEXT")

        try:
            con.execute(
                "INSERT OR IGNORE INTO raw_framework_routes("
                "endpoint_id, framework, http_method, route_path, normalized_route, "
                "handler_name, handler_canonical_id, file_path, line, evidence, confidence) "
                "SELECT endpoint_id, framework, http_method, route_path, normalized_route, "
                "handler_name, handler_canonical_id, file_path, line, evidence, confidence "
                "FROM framework_routes"
            )
        except sqlite3.OperationalError:
            pass

        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS local_bindings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "target_name TEXT NOT NULL, "
                "file_path TEXT NOT NULL, "
                "line INTEGER NOT NULL, "
                "column INTEGER, "
                "scope TEXT NOT NULL DEFAULT '', "
                "expr_kind TEXT NOT NULL DEFAULT 'IDENTIFIER', "
                "source_expr TEXT NOT NULL DEFAULT '', "
                "is_conditional INTEGER NOT NULL DEFAULT 0, "
                "base_expr TEXT NOT NULL DEFAULT '', "
                "attr_name TEXT NOT NULL DEFAULT '', "
                "dict_entries_json TEXT NOT NULL DEFAULT '[]', "
                "list_entries_json TEXT NOT NULL DEFAULT '[]', "
                "subscript_target TEXT, "
                "subscript_key TEXT, "
                "subscript_index INTEGER, "
                "FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_bindings_file ON local_bindings (file_path)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_bindings_target ON local_bindings (target_name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_bindings_file_target ON local_bindings (file_path, target_name)")
        except sqlite3.OperationalError:
            pass

    def index(
        self,
        *,
        progress_callback: Callable[[str, int, int, IndexingTelemetry], None] | None = None,
        catch_interrupt: bool = False,
    ) -> dict[str, int]:
        """Perform an incremental indexing pass, followed by global reference resolution."""
        indexed = unchanged = parse_failed_count = 0
        stale: list[str] = []
        dirty_files: set[str] = set()
        files = []
        telemetry = IndexingTelemetry()
        self.last_telemetry = telemetry
        from codegraph.freshness import current_commit, save_commit

        with self.governor.task_scope(TaskPriority.BACKGROUND):
            self.governor.set_indexing_active(True)
            try:
                with telemetry.phase("repository_scan") as p_scan:
                    files = scan(self.repository, self.settings.max_file_size, self.settings.exclude)
                    p_scan.files_processed = len(files)
                    p_scan.items_processed = len(files)
                total_files = len(files)
                if progress_callback is not None:
                    progress_callback("repository_scan", total_files, total_files, telemetry)

                seen = {item.relative_path.as_posix() for item in files}
                batch_limit = self.governor.policy.max_files_per_incremental_batch
                uncommitted_in_batch = 0

                con = self.connect()
                try:
                    # Check parser version invalidation & previous interrupted state
                    last_parser_ver = None
                    resolution_dirty = False
                    try:
                        for mrow in con.execute(
                            "SELECT key, value FROM metadata WHERE key IN ('parser_version', 'resolution_dirty')"
                        ).fetchall():
                            mkey = str(mrow["key"])
                            if mkey == "parser_version":
                                last_parser_ver = str(mrow["value"])
                            elif mkey == "resolution_dirty" and str(mrow["value"]) == "1":
                                resolution_dirty = True
                    except sqlite3.OperationalError:
                        pass

                    force_reparse = (last_parser_ver != PARSER_VERSION)

                    # Pre-load existing file hashes and statuses in a single query
                    existing_files: dict[str, tuple[str, str]] = {
                        str(r["path"]): (str(r["hash"]), str(r["status"]))
                        for r in con.execute("SELECT path, hash, status FROM files").fetchall()
                    }

                    for idx, item in enumerate(files):
                        if idx > 0 and idx % batch_limit == 0:
                            self.governor.yield_if_needed(TaskPriority.BACKGROUND)

                        relative = item.relative_path.as_posix()
                        t_read = time.perf_counter()
                        try:
                            content = item.path.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            telemetry.record("file_reading", time.perf_counter() - t_read, errors_skips=1)
                            continue
                        digest = hashlib.sha256(content.encode()).hexdigest()
                        telemetry.record(
                            "file_reading",
                            time.perf_counter() - t_read,
                            files_processed=1,
                            items_processed=len(content),
                        )

                        old_state = existing_files.get(relative)
                        if old_state is not None and old_state[0] == digest and not force_reparse:
                            if old_state[1] == "parse_failed":
                                parse_failed_count += 1
                            else:
                                unchanged += 1
                            telemetry.phases["file_reading"].errors_skips += 1
                            continue

                        t_cls = time.perf_counter()
                        cat_info = classify_file_detailed(relative, content)
                        cat_str = cat_info.category.value
                        telemetry.record(
                            "file_classification",
                            time.perf_counter() - t_cls,
                            files_processed=1,
                            items_processed=1,
                        )

                        success = self._replace_file(
                            con,
                            relative,
                            item.language,
                            content,
                            digest,
                            category=cat_str,
                            is_existing=(old_state is not None),
                            telemetry=telemetry,
                        )
                        if success:
                            indexed += 1
                            dirty_files.add(relative)
                            existing_files[relative] = (digest, "ok")
                        else:
                            parse_failed_count += 1
                            existing_files[relative] = (digest, "parse_failed")

                        uncommitted_in_batch += 1
                        if uncommitted_in_batch >= self.commit_batch_size:
                            t_commit = time.perf_counter()
                            con.execute(
                                "INSERT INTO metadata(key, value) VALUES('resolution_dirty', '1') "
                                "ON CONFLICT(key) DO UPDATE SET value='1'"
                            )
                            con.execute(
                                "INSERT INTO metadata(key, value) VALUES('index_status', 'in_progress') "
                                "ON CONFLICT(key) DO UPDATE SET value='in_progress'"
                            )
                            con.commit()
                            telemetry.batch_commits += 1
                            telemetry.observe_wal(self.db_path)
                            try:
                                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                telemetry.wal_checkpoints += 1
                            except sqlite3.OperationalError:
                                pass
                            telemetry.observe_wal(self.db_path)
                            telemetry.record(
                                "sqlite_writes",
                                time.perf_counter() - t_commit,
                                db_writes=1,
                            )
                            uncommitted_in_batch = 0
                            if progress_callback is not None:
                                progress_callback("ast_parsing", idx + 1, total_files, telemetry)

                    telemetry.post_parse_rss_mb = get_process_rss_mb()
                    telemetry.peak_rss_mb = max(telemetry.peak_rss_mb, telemetry.post_parse_rss_mb)

                    stale = [
                        p for p in existing_files
                        if p not in seen
                    ]
                    if stale:
                        t_del = time.perf_counter()
                        for path in stale:
                            self._delete_file(con, path, telemetry=telemetry)
                        telemetry.record(
                            "sqlite_writes",
                            time.perf_counter() - t_del,
                            files_processed=len(stale),
                            db_writes=len(stale),
                        )

                    # Commit file indexing phase before global post-processing so completed file work is durable
                    head_commit = current_commit(self.repository)
                    now_ts = int(time.time())
                    need_resolution = (indexed > 0 or len(stale) > 0 or force_reparse or resolution_dirty)

                    if uncommitted_in_batch > 0 or stale:
                        t_commit = time.perf_counter()
                        if need_resolution:
                            con.execute(
                                "INSERT INTO metadata(key, value) VALUES('resolution_dirty', '1') "
                                "ON CONFLICT(key) DO UPDATE SET value='1'"
                            )
                        con.commit()
                        telemetry.batch_commits += 1
                        telemetry.observe_wal(self.db_path)
                        try:
                            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            telemetry.wal_checkpoints += 1
                        except sqlite3.OperationalError:
                            pass
                        telemetry.observe_wal(self.db_path)
                        telemetry.record("sqlite_writes", time.perf_counter() - t_commit, db_writes=1)
                        uncommitted_in_batch = 0

                    # Run global reference resolution pass if any files were changed, removed, or pending from interrupt
                    if need_resolution:
                        with telemetry.phase("post_processing") as p_post:
                            if progress_callback is not None:
                                progress_callback("post_processing", total_files, total_files, telemetry)
                            self._run_global_resolution(
                                con,
                                head_commit,
                                dirty_files=dirty_files if not (force_reparse or resolution_dirty) else None,
                                removed_files=set(stale) if not (force_reparse or resolution_dirty) else None,
                                telemetry=telemetry,
                                progress_callback=progress_callback,
                            )
                            p_post.files_processed = indexed + len(stale)
                            p_post.items_processed = indexed + len(stale)
                            # Invalidate context cache on index update
                            t_rank = time.perf_counter()
                            try:
                                con.execute("DELETE FROM context_cache")
                            except sqlite3.OperationalError:
                                pass
                            telemetry.record("ranking_index_building", time.perf_counter() - t_rank, db_writes=1)

                    # Final commit & WAL checkpoint
                    with telemetry.phase("final_commit_checkpoint") as p_final:
                        save_commit(con, head_commit, now_ts)
                        current_gen = 0
                        try:
                            grow = con.execute("SELECT value FROM metadata WHERE key='index_generation'").fetchone()
                            if grow and grow[0]:
                                current_gen = int(grow[0])
                        except (sqlite3.OperationalError, ValueError):
                            pass
                        next_gen = current_gen + 1

                        con.executemany(
                            "INSERT INTO metadata(key, value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            [
                                ("repository", str(self.repository)),
                                ("parser_version", PARSER_VERSION),
                                ("schema_version", str(SCHEMA_VERSION)),
                                ("index_generation", str(next_gen)),
                                ("index_timestamp", str(now_ts)),
                                ("resolution_dirty", "0"),
                                ("index_status", "ok"),
                            ],
                        )
                        con.commit()
                        telemetry.batch_commits += 1
                        telemetry.observe_wal(self.db_path)
                        try:
                            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            telemetry.wal_checkpoints += 1
                        except sqlite3.OperationalError:
                            pass
                        telemetry.observe_wal(self.db_path)
                        p_final.files_processed = total_files
                        p_final.items_processed = indexed
                        p_final.db_writes = 8
                        if progress_callback is not None:
                            progress_callback("final_commit_checkpoint", total_files, total_files, telemetry)

                except KeyboardInterrupt:
                    # Safe cancellation: roll back only the active uncommitted batch, preserve committed batches
                    telemetry.interrupted = True
                    telemetry.scanned_files = len(files)
                    telemetry.indexed_files = indexed
                    telemetry.unchanged_files = unchanged
                    telemetry.removed_files = len(stale)
                    telemetry.parse_failed_files = parse_failed_count
                    try:
                        con.rollback()
                        con.executemany(
                            "INSERT INTO metadata(key, value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            [
                                ("resolution_dirty", "1"),
                                ("index_status", "interrupted"),
                                ("parser_version", PARSER_VERSION),
                            ],
                        )
                        con.commit()
                        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                        telemetry.wal_checkpoints += 1
                        telemetry.observe_wal(self.db_path)
                    except sqlite3.OperationalError:
                        pass
                    telemetry.finish(self.db_path)
                    if catch_interrupt:
                        return {
                            "scanned": len(files),
                            "indexed": indexed,
                            "unchanged": unchanged,
                            "removed": len(stale),
                            "interrupted": 1,
                        }
                    raise
                except BaseException:
                    con.rollback()
                    raise
                finally:
                    con.close()
            finally:
                if not telemetry.interrupted:
                    telemetry.scanned_files = len(files)
                    telemetry.indexed_files = indexed
                    telemetry.unchanged_files = unchanged
                    telemetry.removed_files = len(stale)
                    telemetry.parse_failed_files = parse_failed_count
                    telemetry.finish(self.db_path)
                self.governor.set_indexing_active(False)

        result: dict[str, int] = {
            "scanned": len(files),
            "indexed": indexed,
            "unchanged": unchanged,
            "removed": len(stale),
        }
        if parse_failed_count > 0:
            result["parse_failed"] = parse_failed_count
        return result

    def _delete_file(
        self,
        con: sqlite3.Connection,
        path: str,
        *,
        telemetry: IndexingTelemetry | None = None,
    ) -> None:
        """Atomically delete all indexed facts for a file, maintaining FTS synchronization."""
        ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE path=?", (path,))]
        if ids:
            t_fts = time.perf_counter()
            con.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(chunk_id,) for chunk_id in ids])
            if telemetry is not None:
                telemetry.record(
                    "fts_updates",
                    time.perf_counter() - t_fts,
                    items_processed=len(ids),
                    db_writes=len(ids),
                )
        con.execute("DELETE FROM chunks WHERE path=?", (path,))
        con.execute("DELETE FROM symbols WHERE path=?", (path,))
        con.execute("DELETE FROM imports WHERE source_path=?", (path,))
        con.execute("DELETE FROM calls WHERE source_path=?", (path,))
        con.execute("DELETE FROM inheritance WHERE source_file=?", (path,))
        con.execute("DELETE FROM framework_routes WHERE file_path=?", (path,))
        con.execute("DELETE FROM raw_framework_routes WHERE file_path=?", (path,))
        con.execute("DELETE FROM router_mounts WHERE file_path=?", (path,))
        con.execute("DELETE FROM router_definitions WHERE file_path=?", (path,))
        con.execute("DELETE FROM local_bindings WHERE file_path=?", (path,))
        con.execute("DELETE FROM 'references' WHERE path=?", (path,))
        con.execute("DELETE FROM graph_edges WHERE file=?", (path,))
        con.execute("DELETE FROM db_entities WHERE file_path=?", (path,))
        con.execute("DELETE FROM db_queries WHERE file_path=?", (path,))
        con.execute("DELETE FROM db_migrations WHERE file_path=?", (path,))
        con.execute("DELETE FROM files WHERE path=?", (path,))

    def _replace_file(
        self,
        con: sqlite3.Connection,
        path: str,
        language: str,
        content: str,
        digest: str,
        category: str = "SOURCE",
        *,
        is_existing: bool = True,
        telemetry: IndexingTelemetry | None = None,
    ) -> bool:
        """Parse and insert a file. If parse fails, preserves last-known-good state."""
        from codegraph.security.redaction import redact_secrets

        t_parse = time.perf_counter()
        parse_cache = get_parse_cache()
        cached = parse_cache.get((digest, PARSER_VERSION, language))
        if cached is not None:
            result = cached
        else:
            result = parse(content, language, path)
            parse_cache.put((digest, PARSER_VERSION, language), result)
        parse_elapsed = time.perf_counter() - t_parse

        if telemetry is not None:
            telemetry.record(
                "ast_parsing",
                parse_elapsed,
                files_processed=1,
                items_processed=len(result.symbols) + len(result.imports) + len(result.calls),
                errors_skips=1 if result.parse_failed else 0,
            )
            telemetry.record(
                "symbol_extraction",
                0.0,
                files_processed=1,
                items_processed=len(result.symbols),
            )
            telemetry.record(
                "import_extraction",
                0.0,
                files_processed=1,
                items_processed=len(result.imports),
            )
            if result.routes or result.mounts or result.router_definitions:
                telemetry.record(
                    "framework_analysis",
                    0.0,
                    files_processed=1,
                    items_processed=len(result.routes) + len(result.mounts) + len(result.router_definitions),
                )

        now = int(time.time())

        if result.parse_failed:
            t_sql = time.perf_counter()
            # Parse failure safety: check if file previously existed
            old = con.execute("SELECT hash, status FROM files WHERE path=?", (path,)).fetchone() if is_existing else None
            if old:
                # Retain last-known-good index records, mark file as parse_failed
                con.execute(
                    "UPDATE files SET hash=?, status='parse_failed', parse_error=?, indexed_at=?, category=? WHERE path=?",
                    (digest, redact_secrets(result.parse_error or ""), now, category, path),
                )
            else:
                con.execute(
                    "INSERT INTO files(path, hash, language, indexed_at, status, parse_error, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (path, digest, language, now, "parse_failed", redact_secrets(result.parse_error or ""), category),
                )
            if telemetry is not None:
                telemetry.record("sqlite_writes", time.perf_counter() - t_sql, files_processed=1, db_writes=1)
            return False

        t_sql = time.perf_counter()
        db_write_count = 0
        fts_elapsed = 0.0
        fts_write_count = 0

        # Successful parse: clean up old file state only if file previously existed in DB
        if is_existing:
            self._delete_file(con, path, telemetry=telemetry)
            db_write_count += 16

        con.execute(
            "INSERT INTO files(path, hash, language, indexed_at, status, parse_error, last_valid_hash, category) "
            "VALUES (?, ?, ?, ?, 'ok', NULL, ?, ?)",
            (path, digest, language, now, digest, category),
        )
        db_write_count += 1

        if category in ("MINIFIED", "BUNDLE", "BINARY"):
            if telemetry is not None:
                telemetry.record("sqlite_writes", time.perf_counter() - t_sql, files_processed=1, db_writes=db_write_count)
            return True

        lines = content.splitlines()

        if result.symbols:
            symbol_rows = []
            for s in result.symbols:
                dec_str = ",".join(s.decorators) if s.decorators else ""
                safe_doc = redact_secrets(s.documentation) if s.documentation else None
                symbol_rows.append(
                    (
                        s.name,
                        s.qualified_name,
                        s.kind,
                        path,
                        s.start_line,
                        s.end_line,
                        dec_str,
                        s.id,
                        s.canonical_id,
                        s.language,
                        s.module,
                        s.scope,
                        redact_secrets(s.signature),
                        s.content_hash,
                        s.parent_symbol_id,
                        s.visibility,
                        s.return_type,
                        s.parameter_count,
                        safe_doc,
                    )
                )
                body = redact_secrets("\n".join(lines[s.start_line - 1 : s.end_line]))
                cur = con.execute(
                    "INSERT INTO chunks(path, language, symbol, symbol_type, start_line, end_line, content, hash) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        path,
                        language,
                        s.qualified_name,
                        s.kind,
                        s.start_line,
                        s.end_line,
                        body,
                        digest,
                    ),
                )
                db_write_count += 1
                t_fts = time.perf_counter()
                con.execute(
                    "INSERT INTO chunks_fts(rowid, content, path, symbol) VALUES (?,?,?,?)",
                    (cur.lastrowid, body, path, s.qualified_name),
                )
                fts_elapsed += time.perf_counter() - t_fts
                fts_write_count += 1

            con.executemany(
                "INSERT INTO symbols("
                "name, qualified_name, kind, path, start_line, end_line, decorators, "
                "id, canonical_id, language, module, scope, signature, content_hash, "
                "parent_symbol_id, visibility, return_type, parameter_count, documentation) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                symbol_rows,
            )
            db_write_count += len(symbol_rows)
        else:
            safe_content = redact_secrets(content)
            cur = con.execute(
                "INSERT INTO chunks(path, language, symbol, symbol_type, start_line, end_line, content, hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (path, language, None, "module", 1, max(1, len(lines)), safe_content, digest),
            )
            db_write_count += 1
            t_fts = time.perf_counter()
            con.execute(
                "INSERT INTO chunks_fts(rowid, content, path, symbol) VALUES (?,?,?,?)",
                (cur.lastrowid, safe_content, path, None),
            )
            fts_elapsed += time.perf_counter() - t_fts
            fts_write_count += 1

        if result.imports:
            con.executemany(
                "INSERT INTO imports(source_path, module, name, alias, full_name, line, "
                "source_module, imported_module, imported_name, local_name, import_type) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        path,
                        imp.module,
                        imp.name,
                        imp.alias,
                        imp.full,
                        imp.line,
                        imp.source_module,
                        imp.imported_module,
                        imp.imported_name,
                        imp.local_name,
                        imp.import_type,
                    )
                    for imp in result.imports
                ],
            )
            db_write_count += len(result.imports)

        if result.calls:
            con.executemany(
                "INSERT INTO calls(source_path, callee, qualified_callee, line, confidence, source_symbol_id) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        path,
                        c.callee,
                        c.qualified_callee,
                        c.line,
                        c.confidence,
                        c.caller_canonical_id,
                    )
                    for c in result.calls
                ],
            )
            db_write_count += len(result.calls)

        if result.inheritance:
            con.executemany(
                "INSERT INTO inheritance(source_symbol, base_name, relationship, source_file, line, source_canonical_id) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        inh.source_symbol,
                        inh.base_name,
                        inh.relationship,
                        path,
                        inh.line,
                        inh.source_canonical_id,
                    )
                    for inh in result.inheritance
                ],
            )
            db_write_count += len(result.inheritance)

        if result.routes:
            con.executemany(
                "INSERT INTO raw_framework_routes(endpoint_id, framework, http_method, route_path, "
                "normalized_route, handler_name, handler_canonical_id, file_path, line, evidence, confidence, router_name) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(endpoint_id) DO UPDATE SET "
                "framework=excluded.framework, "
                "http_method=excluded.http_method, "
                "route_path=excluded.route_path, "
                "normalized_route=excluded.normalized_route, "
                "handler_name=excluded.handler_name, "
                "handler_canonical_id=excluded.handler_canonical_id, "
                "file_path=excluded.file_path, "
                "line=excluded.line, "
                "evidence=excluded.evidence, "
                "confidence=excluded.confidence, "
                "router_name=excluded.router_name",
                [
                    (
                        r.endpoint_id,
                        r.framework,
                        r.http_method,
                        r.route_path,
                        r.normalized_route,
                        r.handler_name,
                        r.handler_canonical_id,
                        path,
                        r.line,
                        redact_secrets(r.evidence),
                        r.confidence,
                        r.router_name,
                    )
                    for r in result.routes
                ],
            )
            con.executemany(
                "INSERT INTO framework_routes(endpoint_id, framework, http_method, route_path, "
                "normalized_route, handler_name, handler_canonical_id, file_path, line, evidence, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(endpoint_id) DO UPDATE SET "
                "framework=excluded.framework, "
                "http_method=excluded.http_method, "
                "route_path=excluded.route_path, "
                "normalized_route=excluded.normalized_route, "
                "handler_name=excluded.handler_name, "
                "handler_canonical_id=excluded.handler_canonical_id, "
                "file_path=excluded.file_path, "
                "line=excluded.line, "
                "evidence=excluded.evidence, "
                "confidence=excluded.confidence",
                [
                    (
                        r.endpoint_id,
                        r.framework,
                        r.http_method,
                        r.route_path,
                        r.normalized_route,
                        r.handler_name,
                        r.handler_canonical_id,
                        path,
                        r.line,
                        redact_secrets(r.evidence),
                        r.confidence,
                    )
                    for r in result.routes
                ],
            )
            db_write_count += len(result.routes) * 2

        if result.mounts:
            con.executemany(
                "INSERT INTO router_mounts(mount_id, framework, parent_router, child_router, prefix, file_path, line, evidence, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(mount_id) DO UPDATE SET "
                "prefix=excluded.prefix, evidence=excluded.evidence, confidence=excluded.confidence",
                [
                    (
                        f"MOUNT:{m.framework}:{path}:{m.line}:{m.parent_router}->{m.child_router}",
                        m.framework,
                        m.parent_router,
                        m.child_router,
                        m.prefix,
                        path,
                        m.line,
                        redact_secrets(m.evidence),
                        m.confidence,
                    )
                    for m in result.mounts
                ],
            )
            db_write_count += len(result.mounts)

        if result.router_definitions:
            con.executemany(
                "INSERT INTO router_definitions(framework, router_name, prefix, file_path, line, evidence) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        d.framework,
                        d.router_name,
                        d.prefix,
                        path,
                        d.line,
                        redact_secrets(d.evidence),
                    )
                    for d in result.router_definitions
                ],
            )
            db_write_count += len(result.router_definitions)

        if result.bindings:
            con.executemany(
                "INSERT INTO local_bindings("
                "target_name, file_path, line, column, scope, expr_kind, source_expr, "
                "is_conditional, base_expr, attr_name, dict_entries_json, list_entries_json, "
                "subscript_target, subscript_key, subscript_index) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        b.target_name,
                        path,
                        b.line,
                        b.column,
                        b.scope,
                        b.expr_kind,
                        redact_secrets(b.source_expr),
                        1 if b.is_conditional else 0,
                        b.base_expr,
                        b.attr_name,
                        json.dumps(b.dict_entries),
                        json.dumps(b.list_entries),
                        b.subscript_target,
                        b.subscript_key,
                        b.subscript_index,
                    )
                    for b in result.bindings
                ],
            )
            db_write_count += len(result.bindings)

        total_sql_elapsed = max(0.0, (time.perf_counter() - t_sql) - fts_elapsed)
        if telemetry is not None:
            telemetry.record(
                "sqlite_writes",
                total_sql_elapsed,
                files_processed=1,
                items_processed=db_write_count,
                db_writes=db_write_count,
            )
            if fts_write_count > 0:
                telemetry.record(
                    "fts_updates",
                    fts_elapsed,
                    files_processed=1,
                    items_processed=fts_write_count,
                    db_writes=fts_write_count,
                )

        return True

    def _run_global_resolution(
        self,
        con: sqlite3.Connection,
        indexed_commit: str | None,
        *,
        dirty_files: set[str] | None = None,
        removed_files: set[str] | None = None,
        telemetry: IndexingTelemetry | None = None,
        progress_callback: Callable[[str, int, int, IndexingTelemetry], None] | None = None,
    ) -> None:
        """Run repository-wide reference resolution, updating 'references' and 'graph_edges'."""
        from codegraph.security.redaction import redact_secrets

        t_prep = time.perf_counter()
        # 1. Load all files
        file_rows = con.execute("SELECT path, hash, language FROM files WHERE status='ok'").fetchall()
        known_files = {str(r["path"]) for r in file_rows}
        file_hashes = {str(r["path"]): str(r["hash"]) for r in file_rows}
        file_langs = {str(r["path"]): str(r["language"]) for r in file_rows}

        # 2. Load symbols
        sym_rows = con.execute(
            "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
            "id, canonical_id, language, module, scope, signature, content_hash, "
            "parent_symbol_id, visibility, return_type, parameter_count, documentation "
            "FROM symbols"
        ).fetchall()
        symbols = [
            Symbol(
                id=str(r["id"]),
                canonical_id=str(r["canonical_id"]),
                name=str(r["name"]),
                qualified_name=str(r["qualified_name"]),
                kind=str(r["kind"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                file_path=str(r["path"]),
                decorators=[d for d in str(r["decorators"]).split(",") if d],
                language=str(r["language"]),
                module=str(r["module"]),
                path=str(r["path"]),
                scope=str(r["scope"]),
                signature=str(r["signature"]),
                content_hash=str(r["content_hash"]),
                parent_symbol_id=r["parent_symbol_id"],
                visibility=str(r["visibility"]),
                return_type=r["return_type"],
                parameter_count=r["parameter_count"],
                documentation=r["documentation"],
            )
            for r in sym_rows
        ]

        # 3. Load imports
        imp_rows = con.execute(
            "SELECT source_path, module, name, alias, full_name, line, "
            "source_module, imported_module, imported_name, local_name, import_type "
            "FROM imports"
        ).fetchall()
        imports = [
            ImportRef(
                module=str(r["module"]),
                source_file=str(r["source_path"]),
                name=r["name"],
                alias=r["alias"],
                full=r["full_name"],
                line=int(r["line"]),
                source_module=str(r["source_module"]),
                imported_module=str(r["imported_module"]),
                imported_name=r["imported_name"],
                local_name=str(r["local_name"]),
                import_type=str(r["import_type"]),
                is_reexport=(str(r["import_type"]) == "reexport"),
            )
            for r in imp_rows
        ]

        # 4. Load calls
        call_rows = con.execute(
            "SELECT source_path, callee, qualified_callee, line, confidence, source_symbol_id "
            "FROM calls"
        ).fetchall()
        calls = [
            CallRef(
                callee=str(r["callee"]),
                source_file=str(r["source_path"]),
                confidence=str(r["confidence"]),
                qualified_callee=r["qualified_callee"],
                line=int(r["line"]),
                caller_canonical_id=r["source_symbol_id"],
            )
            for r in call_rows
        ]

        # 5. Load inheritance
        inh_rows = con.execute(
            "SELECT source_symbol, base_name, relationship, source_file, line, source_canonical_id "
            "FROM inheritance"
        ).fetchall()
        inheritance = [
            InheritanceRef(
                source_symbol=str(r["source_symbol"]),
                base_name=str(r["base_name"]),
                relationship=str(r["relationship"]),
                source_file=str(r["source_file"]),
                line=int(r["line"]),
                source_canonical_id=str(r["source_canonical_id"]),
            )
            for r in inh_rows
        ]
        if telemetry is not None:
            telemetry.record(
                "ranking_index_building",
                time.perf_counter() - t_prep,
                files_processed=len(known_files),
                items_processed=len(symbols) + len(imports) + len(calls),
            )

        # 6. Load raw framework routes, router mounts, and router definitions for composition
        t_fw = time.perf_counter()
        from codegraph.frameworks import RouterDefinition, RouterMountDetection
        from codegraph.route_composer import compose_routes

        raw_rt_rows = con.execute(
            "SELECT endpoint_id, framework, http_method, route_path, normalized_route, "
            "handler_name, handler_canonical_id, file_path, line, evidence, confidence, router_name "
            "FROM raw_framework_routes"
        ).fetchall()
        raw_routes = [
            RouteDetection(
                framework=str(r["framework"]),
                http_method=str(r["http_method"]),
                route_path=str(r["route_path"]),
                normalized_route=str(r["normalized_route"]),
                handler_name=str(r["handler_name"]),
                handler_canonical_id=str(r["handler_canonical_id"]),
                file_path=str(r["file_path"]),
                line=int(r["line"]),
                evidence=str(r["evidence"]),
                confidence=str(r["confidence"]),
                endpoint_id_override=str(r["endpoint_id"]),
                router_name=str(r["router_name"]) if "router_name" in r.keys() else "",
            )
            for r in raw_rt_rows
        ]

        mount_rows = con.execute(
            "SELECT framework, parent_router, child_router, prefix, file_path, line, evidence, confidence "
            "FROM router_mounts"
        ).fetchall()
        mount_detections = [
            RouterMountDetection(
                framework=str(r["framework"]),
                parent_router=str(r["parent_router"]),
                child_router=str(r["child_router"]),
                prefix=str(r["prefix"]),
                file_path=str(r["file_path"]),
                line=int(r["line"]),
                evidence=str(r["evidence"]),
                confidence=str(r["confidence"]),
            )
            for r in mount_rows
        ]

        rdef_rows = con.execute(
            "SELECT framework, router_name, prefix, file_path, line, evidence "
            "FROM router_definitions"
        ).fetchall()
        router_defs = [
            RouterDefinition(
                framework=str(r["framework"]),
                router_name=str(r["router_name"]),
                prefix=str(r["prefix"]),
                file_path=str(r["file_path"]),
                line=int(r["line"]),
                evidence=str(r["evidence"]),
            )
            for r in rdef_rows
        ]

        # Compose routes across hierarchical router mounts
        composed_routes, verified_mount_edges = compose_routes(
            raw_routes=raw_routes,
            mounts=mount_detections,
            router_defs=router_defs,
            imports=imports,
            known_files=known_files,
        )
        if telemetry is not None:
            telemetry.record(
                "framework_analysis",
                time.perf_counter() - t_fw,
                files_processed=len(known_files),
                items_processed=len(composed_routes) + len(verified_mount_edges),
            )

        # Repopulate framework_routes with the composed routes
        t_sql = time.perf_counter()
        con.execute("DELETE FROM framework_routes")
        if composed_routes:
            con.executemany(
                "INSERT INTO framework_routes(endpoint_id, framework, http_method, route_path, "
                "normalized_route, handler_name, handler_canonical_id, file_path, line, evidence, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        r.endpoint_id,
                        r.framework,
                        r.http_method,
                        r.route_path,
                        r.normalized_route,
                        r.handler_name,
                        r.handler_canonical_id,
                        r.file_path,
                        r.line,
                        redact_secrets(r.evidence),
                        r.confidence,
                    )
                    for r in composed_routes
                ],
            )
        if telemetry is not None:
            telemetry.record(
                "sqlite_writes",
                time.perf_counter() - t_sql,
                items_processed=len(composed_routes),
                db_writes=len(composed_routes) + 1,
            )

        # 7. Load local bindings for data-flow and alias resolution
        t_sym_res = time.perf_counter()
        binding_rows = con.execute(
            "SELECT target_name, file_path, line, column, scope, expr_kind, source_expr, "
            "is_conditional, base_expr, attr_name, dict_entries_json, list_entries_json, "
            "subscript_target, subscript_key, subscript_index "
            "FROM local_bindings"
        ).fetchall()
        bindings = [
            BindingRef(
                target_name=str(r["target_name"]),
                file_path=str(r["file_path"]),
                line=int(r["line"]),
                column=r["column"],
                scope=str(r["scope"]),
                expr_kind=str(r["expr_kind"]),
                source_expr=str(r["source_expr"]),
                is_conditional=bool(r["is_conditional"]),
                base_expr=str(r["base_expr"]),
                attr_name=str(r["attr_name"]),
                dict_entries=tuple(tuple(x) for x in json.loads(r["dict_entries_json"])),
                list_entries=tuple(json.loads(r["list_entries_json"])),
                subscript_target=r["subscript_target"],
                subscript_key=r["subscript_key"],
                subscript_index=r["subscript_index"],
            )
            for r in binding_rows
        ]

        from codegraph.monorepo import detect_workspace
        workspace = detect_workspace(self.repository, con=con)

        # Run resolution engine with composed routes, mount edges, bindings, and workspace
        resolver = ReferenceResolver(
            symbols=symbols,
            imports=imports,
            calls=calls,
            inheritance=inheritance,
            routes=composed_routes,
            mount_edges=verified_mount_edges,
            known_files=known_files,
            file_hashes=file_hashes,
            indexed_commit=indexed_commit,
            bindings=bindings,
            workspace=workspace,
            max_reexport_depth=self.max_reexport_depth,
            max_wildcard_expansions=self.max_wildcard_expansions,
        )
        if telemetry is not None:
            telemetry.record(
                "symbol_resolution",
                time.perf_counter() - t_sym_res,
                files_processed=len(known_files),
                items_processed=len(symbols) + len(bindings),
            )
            if progress_callback is not None:
                progress_callback("symbol_resolution", len(known_files), len(known_files), telemetry)

        t_rel_res = time.perf_counter()
        output = resolver.resolve_all()
        self.last_epistemic_findings = list(output.findings)

        # Update framework_routes handler_canonical_id if resolved via local bindings / imports
        route_updates: list[tuple[str, str]] = []
        for rt in composed_routes:
            handler_sym, _conf, _reason = resolver.resolve_identifier_in_file(
                rt.handler_name, rt.file_path, use_line=rt.line
            )
            if handler_sym and handler_sym.canonical_id != rt.handler_canonical_id:
                route_updates.append((handler_sym.canonical_id, rt.endpoint_id))
        if route_updates:
            con.executemany(
                "UPDATE framework_routes SET handler_canonical_id=? WHERE endpoint_id=?",
                route_updates,
            )

        num_symbols = len(symbols)
        # Release in-memory IR lists and resolver caches before DB pass & SQL serialization
        symbols.clear()
        imports.clear()
        calls.clear()
        inheritance.clear()
        bindings.clear()
        del resolver

        if telemetry is not None:
            budget_skips = sum(
                1 for f in output.findings if f.get("reason") == "resolution_budget_exceeded"
            )
            telemetry.record(
                "relationship_resolution",
                time.perf_counter() - t_rel_res,
                files_processed=len(known_files),
                items_processed=len(output.references) + len(output.resolved_imports) + len(output.resolved_calls),
                errors_skips=budget_skips,
                db_writes=len(route_updates),
            )
            if progress_callback is not None:
                progress_callback("relationship_resolution", len(known_files), len(known_files), telemetry)

        # Run repository-wide Database Deep Intelligence extraction (Phases 1-8)
        with (telemetry.phase("database_analysis") if telemetry is not None else contextmanager(lambda: iter([None]))()) as p_db:
            db_edges = self._run_database_intelligence_pass(
                con,
                sorted(known_files),
                file_langs,
                dirty_files=dirty_files,
                removed_files=removed_files,
            )
            if p_db is not None:
                p_db.files_processed = len(dirty_files) if dirty_files is not None else len(known_files)
                p_db.items_processed = len(db_edges)
        if telemetry is not None and progress_callback is not None:
            progress_callback("database_analysis", len(known_files), len(known_files), telemetry)

        t_edges = time.perf_counter()
        all_edges: list[Any] = [*output.edges, *db_edges]
        output.edges.clear()
        db_edges.clear()
        total_edges = len(all_edges)
        total_refs = len(output.references)
        if telemetry is not None:
            telemetry.symbols_count = num_symbols
            telemetry.edges_count = total_edges
            telemetry.record(
                "graph_edge_creation",
                time.perf_counter() - t_edges,
                files_processed=len(known_files),
                items_processed=total_edges,
            )

        # Batch write references, graph_edges, and resolved imports/calls with bounded WAL checkpoints
        t_sql_post = time.perf_counter()
        post_chunk_size = 4000

        def _checkpoint_post() -> None:
            con.commit()
            if telemetry is not None:
                telemetry.batch_commits += 1
                telemetry.observe_wal(self.db_path)
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if telemetry is not None:
                    telemetry.wal_checkpoints += 1
            except sqlite3.OperationalError:
                pass
            if telemetry is not None:
                telemetry.observe_wal(self.db_path)

        con.execute("DELETE FROM 'references'")
        for i in range(0, total_refs, post_chunk_size):
            batch_refs = output.references[i : i + post_chunk_size]
            con.executemany(
                "INSERT INTO 'references'("
                "source_symbol_id, target_symbol_id, relationship, confidence, path, "
                "start_line, end_line, evidence, source_hash, indexed_commit, evidence_status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        ref.source_symbol_id,
                        ref.target_symbol_id,
                        ref.relationship,
                        ref.confidence,
                        ref.path,
                        ref.start_line,
                        ref.end_line,
                        redact_secrets(ref.evidence),
                        ref.source_hash,
                        ref.indexed_commit,
                        ref.evidence_status,
                    )
                    for ref in batch_refs
                ],
            )
            if total_refs > post_chunk_size:
                _checkpoint_post()
        output.references.clear()

        con.execute("DELETE FROM graph_edges")
        for i in range(0, total_edges, post_chunk_size):
            batch_edges = all_edges[i : i + post_chunk_size]
            con.executemany(
                "INSERT INTO graph_edges("
                "source, target, relationship, confidence, file, start_line, end_line, "
                "evidence, evidence_id, source_hash, indexed_commit, evidence_class, reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        e.source,
                        e.target,
                        e.relationship,
                        e.confidence,
                        e.file,
                        e.start_line,
                        e.end_line,
                        redact_secrets(e.evidence),
                        f"edge_{i + offset}",
                        file_hashes.get(e.file, ""),
                        indexed_commit,
                        getattr(e, "evidence_class", "AST_VERIFIED"),
                        getattr(e, "reason", None),
                    )
                    for offset, e in enumerate(batch_edges)
                ],
            )
            if total_edges > post_chunk_size:
                _checkpoint_post()
        all_edges.clear()

        # Batch update resolved fields on imports and calls tables using composite indexes
        num_res_imports = len(output.resolved_imports)
        if output.resolved_imports:
            imp_updates = [
                (tgt_path, tgt_mod, src_path, ln, loc_name, loc_name, loc_name)
                for (src_path, ln, loc_name), (tgt_path, tgt_mod) in output.resolved_imports.items()
            ]
            output.resolved_imports.clear()
            for i in range(0, len(imp_updates), post_chunk_size):
                con.executemany(
                    "UPDATE imports SET resolved_path=?, resolved_module=? "
                    "WHERE source_path=? AND line=? AND (local_name=? OR alias=? OR name=?)",
                    imp_updates[i : i + post_chunk_size],
                )
                if len(imp_updates) > post_chunk_size:
                    _checkpoint_post()

        num_res_calls = len(output.resolved_calls)
        if output.resolved_calls:
            call_updates = [
                (resolved_id, conf, src_path, ln, callee_nm)
                for (src_path, ln, callee_nm), (resolved_id, conf) in output.resolved_calls.items()
            ]
            output.resolved_calls.clear()
            for i in range(0, len(call_updates), post_chunk_size):
                con.executemany(
                    "UPDATE calls SET resolved_symbol_id=?, confidence=? "
                    "WHERE source_path=? AND line=? AND callee=?",
                    call_updates[i : i + post_chunk_size],
                )
                if len(call_updates) > post_chunk_size:
                    _checkpoint_post()

        if telemetry is not None:
            post_writes = (
                total_refs
                + total_edges
                + num_res_imports
                + num_res_calls
            )
            telemetry.record(
                "sqlite_writes",
                time.perf_counter() - t_sql_post,
                items_processed=post_writes,
                db_writes=post_writes,
            )

    def _run_database_intelligence_pass(
        self,
        con: sqlite3.Connection,
        sorted_files: list[str],
        file_langs: dict[str, str],
        *,
        dirty_files: set[str] | None = None,
        removed_files: set[str] | None = None,
    ) -> list[RelationshipRecord]:
        """Extract ORM models, tables, columns, queries, migrations, and database edges across the repo.

        Streams file contents instead of holding all repository files in memory at once,
        and supports incremental dirty-file extraction when the repository dialect and
        cross-file ORM model->table mappings are unchanged.
        """
        from codegraph.database import (
            DatabaseEntity,
            DatabaseQueryFact,
            MigrationFact,
            detect_file_dialects,
            extract_database_from_file,
            has_potential_database_activity,
            has_potential_orm_models,
        )
        from codegraph.security.redaction import redact_secrets

        def _compute_repo_dialect(dialects_map: dict[str, list[str]]) -> str:
            union_dialects: set[str] = set()
            for dlist in dialects_map.values():
                union_dialects.update(dlist)
            if len(union_dialects) == 1:
                return next(iter(union_dialects))
            if len(union_dialects) > 1:
                return "AMBIGUOUS"
            return "UNKNOWN"

        def _flatten_model_tables(models_map: dict[str, dict[str, str]]) -> dict[str, str]:
            flat: dict[str, str] = {}
            for fpath in sorted(models_map):
                flat.update(models_map[fpath])
            return flat

        def _insert_db_rows(
            entities: list[DatabaseEntity],
            queries: list[DatabaseQueryFact],
            migrations: list[MigrationFact],
        ) -> None:
            if entities:
                con.executemany(
                    "INSERT INTO db_entities("
                    "canonical_id, kind, name, dialect, schema_name, table_name, column_name, "
                    "data_type, nullable, default_value, is_primary_key, is_foreign_key, is_unique, "
                    "is_indexed, target_table, target_column, orm_model_id, framework, file_path, "
                    "start_line, end_line, evidence, confidence, evidence_class, status, metadata_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            e.canonical_id,
                            e.kind,
                            e.name,
                            e.dialect,
                            e.schema_name,
                            e.table_name,
                            e.column_name,
                            e.data_type,
                            1 if e.nullable else 0,
                            redact_secrets(e.default_value) if e.default_value is not None else None,
                            1 if e.is_primary_key else 0,
                            1 if e.is_foreign_key else 0,
                            1 if e.is_unique else 0,
                            1 if e.is_indexed else 0,
                            e.target_table,
                            e.target_column,
                            e.orm_model_id,
                            e.framework,
                            e.file_path,
                            e.start_line,
                            e.end_line,
                            redact_secrets(e.evidence),
                            e.confidence,
                            e.evidence_class,
                            e.status,
                            json.dumps(e.metadata),
                        )
                        for e in entities
                    ],
                )
            if queries:
                con.executemany(
                    "INSERT OR REPLACE INTO db_queries("
                    "query_id, caller_symbol_id, operation, relationship, table_name, table_canonical_id, "
                    "columns_json, framework, normalized_sql, file_path, start_line, end_line, "
                    "evidence, confidence, evidence_class, status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            q.query_id,
                            q.caller_symbol_id,
                            q.operation,
                            q.relationship,
                            q.table_name,
                            q.table_canonical_id,
                            json.dumps(list(q.columns)),
                            q.framework,
                            redact_secrets(q.normalized_sql),
                            q.file_path,
                            q.start_line,
                            q.end_line,
                            redact_secrets(q.evidence),
                            q.confidence,
                            q.evidence_class,
                            q.status,
                        )
                        for q in queries
                    ],
                )
            if migrations:
                con.executemany(
                    "INSERT OR REPLACE INTO db_migrations("
                    "migration_id, canonical_id, system, revision, down_revision, file_path, "
                    "start_line, end_line, created_tables_json, dropped_tables_json, added_columns_json, "
                    "removed_columns_json, renamed_columns_json, indexes_json, foreign_keys_json, "
                    "constraints_json, affected_tables_json, evidence, confidence, evidence_class) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            m.migration_id,
                            m.canonical_id,
                            m.system,
                            m.revision,
                            m.down_revision,
                            m.file_path,
                            m.start_line,
                            m.end_line,
                            json.dumps(list(m.created_tables)),
                            json.dumps(list(m.dropped_tables)),
                            json.dumps(list(m.added_columns)),
                            json.dumps(list(m.removed_columns)),
                            json.dumps(list(m.renamed_columns)),
                            json.dumps(list(m.indexes)),
                            json.dumps(list(m.foreign_keys)),
                            json.dumps(list(m.constraints)),
                            json.dumps(list(m.affected_tables)),
                            redact_secrets(m.evidence),
                            m.confidence,
                            m.evidence_class,
                        )
                        for m in migrations
                    ],
                )

        # Attempt fast incremental DB extraction when dirty_files is a small subset
        can_try_incremental = (
            dirty_files is not None
            and len(sorted_files) > 0
            and 0 < len(dirty_files) + len(removed_files or ()) <= max(64, len(sorted_files) // 5)
        )
        if can_try_incremental and dirty_files is not None:
            prev_dialect_row = con.execute(
                "SELECT value FROM metadata WHERE key='db_repo_dialect'"
            ).fetchone()
            prev_dialects_row = con.execute(
                "SELECT value FROM metadata WHERE key='db_dialects_by_file_json'"
            ).fetchone()
            prev_models_row = con.execute(
                "SELECT value FROM metadata WHERE key='db_models_by_file_json'"
            ).fetchone()
            if prev_dialect_row and prev_dialects_row and prev_models_row:
                try:
                    prev_repo_dialect = str(prev_dialect_row[0])
                    dialects_by_file: dict[str, list[str]] = json.loads(str(prev_dialects_row[0]))
                    models_by_file: dict[str, dict[str, str]] = json.loads(str(prev_models_row[0]))
                    prev_known_model_tables = _flatten_model_tables(models_by_file)

                    changed_or_removed = set(dirty_files) | set(removed_files or ())
                    for rem in changed_or_removed:
                        dialects_by_file.pop(rem, None)
                        models_by_file.pop(rem, None)

                    dirty_texts: dict[str, str] = {}
                    for fpath in sorted(dirty_files):
                        abs_p = self.repository / fpath
                        try:
                            text = abs_p.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            continue
                        dirty_texts[fpath] = text
                        f_dialects = sorted(detect_file_dialects(text, fpath))
                        if f_dialects:
                            dialects_by_file[fpath] = f_dialects

                    new_repo_dialect = _compute_repo_dialect(dialects_by_file)
                    for fpath, text in dirty_texts.items():
                        pass1 = extract_database_from_file(
                            text,
                            fpath,
                            language=file_langs.get(fpath, "python"),
                            repo_dialect=new_repo_dialect,
                        )
                        f_models: dict[str, str] = {}
                        for ent in pass1.entities:
                            if ent.kind == "ORMModel" and ent.table_name:
                                f_models[ent.name] = ent.table_name
                                f_models[ent.canonical_id] = ent.table_name
                        if f_models:
                            models_by_file[fpath] = f_models

                    new_known_model_tables = _flatten_model_tables(models_by_file)
                    if (
                        new_repo_dialect == prev_repo_dialect
                        and new_known_model_tables == prev_known_model_tables
                    ):
                        # Dialect and ORM model->table mappings are unchanged!
                        # Only update DB records for dirty_files and preserve unchanged files' DB edges.
                        for fpath in changed_or_removed:
                            con.execute("DELETE FROM db_entities WHERE file_path=?", (fpath,))
                            con.execute("DELETE FROM db_queries WHERE file_path=?", (fpath,))
                            con.execute("DELETE FROM db_migrations WHERE file_path=?", (fpath,))

                        inc_entities: list[DatabaseEntity] = []
                        inc_queries: list[DatabaseQueryFact] = []
                        inc_migrations: list[MigrationFact] = []
                        inc_edges: list[RelationshipRecord] = []

                        for fpath in sorted(dirty_texts):
                            pass2 = extract_database_from_file(
                                dirty_texts[fpath],
                                fpath,
                                language=file_langs.get(fpath, "python"),
                                repo_dialect=new_repo_dialect,
                                known_model_tables=new_known_model_tables,
                            )
                            inc_entities.extend(pass2.entities)
                            inc_queries.extend(pass2.queries)
                            inc_migrations.extend(pass2.migrations)
                            inc_edges.extend(pass2.edges)

                        _insert_db_rows(inc_entities, inc_queries, inc_migrations)

                        placeholders = ",".join("?" for _ in _DB_EDGE_RELATIONSHIPS)
                        existing_db_edge_rows = con.execute(
                            f"SELECT source, target, relationship, confidence, file, "
                            f"start_line, end_line, evidence, evidence_class, reason "
                            f"FROM graph_edges WHERE relationship IN ({placeholders})",
                            _DB_EDGE_RELATIONSHIPS,
                        ).fetchall()
                        preserved_edges = [
                            RelationshipRecord(
                                source=str(r["source"]),
                                target=str(r["target"]),
                                relationship=str(r["relationship"]),
                                file=str(r["file"]),
                                start_line=int(r["start_line"]),
                                end_line=int(r["end_line"]),
                                evidence=str(r["evidence"]),
                                evidence_class=str(r["evidence_class"]),
                                confidence=str(r["confidence"]),
                                reason=r["reason"],
                            )
                            for r in existing_db_edge_rows
                            if str(r["file"]) not in changed_or_removed
                        ]
                        con.executemany(
                            "INSERT INTO metadata(key, value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            [
                                ("db_dialects_by_file_json", json.dumps(dialects_by_file)),
                                ("db_models_by_file_json", json.dumps(models_by_file)),
                            ],
                        )
                        return [*preserved_edges, *inc_edges]
                except (sqlite3.OperationalError, ValueError, KeyError, TypeError):
                    pass

        # Full streaming pass: never hold all file_contents in RAM at once
        dialects_by_file_full: dict[str, list[str]] = {}
        models_by_file_full: dict[str, dict[str, str]] = {}
        db_candidate_files: list[str] = []

        # Pass 1: stream files to detect dialect and ORM model -> table mappings
        for fpath in sorted_files:
            abs_p = self.repository / fpath
            try:
                text = abs_p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text:
                continue
            lang = file_langs.get(fpath, "python")
            f_dialects = sorted(detect_file_dialects(text, fpath))
            if f_dialects:
                dialects_by_file_full[fpath] = f_dialects

            if has_potential_database_activity(text, fpath, lang):
                db_candidate_files.append(fpath)

            if has_potential_orm_models(text, fpath, lang):
                pass1 = extract_database_from_file(
                    text,
                    fpath,
                    language=lang,
                    repo_dialect="UNKNOWN",
                )
                f_models_full: dict[str, str] = {}
                for ent in pass1.entities:
                    if ent.kind == "ORMModel" and ent.table_name:
                        f_models_full[ent.name] = ent.table_name
                        f_models_full[ent.canonical_id] = ent.table_name
                if f_models_full:
                    models_by_file_full[fpath] = f_models_full

        repo_dialect = _compute_repo_dialect(dialects_by_file_full)
        known_model_tables = _flatten_model_tables(models_by_file_full)

        # Pass 2: stream only db_candidate_files (files that actually contain DB constructs)
        all_entities: list[DatabaseEntity] = []
        all_queries: list[DatabaseQueryFact] = []
        all_migrations: list[MigrationFact] = []
        all_edges: list[RelationshipRecord] = []

        for fpath in db_candidate_files:
            abs_p = self.repository / fpath
            try:
                content = abs_p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not content:
                continue
            pass2 = extract_database_from_file(
                content,
                fpath,
                language=file_langs.get(fpath, "python"),
                repo_dialect=repo_dialect,
                known_model_tables=known_model_tables,
            )
            all_entities.extend(pass2.entities)
            all_queries.extend(pass2.queries)
            all_migrations.extend(pass2.migrations)
            all_edges.extend(pass2.edges)

        con.execute("DELETE FROM db_entities")
        con.execute("DELETE FROM db_queries")
        con.execute("DELETE FROM db_migrations")
        _insert_db_rows(all_entities, all_queries, all_migrations)

        con.executemany(
            "INSERT INTO metadata(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [
                ("db_repo_dialect", repo_dialect),
                ("db_dialects_by_file_json", json.dumps(dialects_by_file_full)),
                ("db_models_by_file_json", json.dumps(models_by_file_full)),
            ],
        )

        return list(all_edges)


def check_database_health(con: sqlite3.Connection, repository: Path | None = None) -> dict[str, object]:
    """Inspect database integrity, FTS synchronization, orphan records, and consistency."""
    issues: list[str] = []

    # 1. Foreign keys
    fk_enabled = con.execute("PRAGMA foreign_keys").fetchone()[0]
    if not fk_enabled:
        issues.append("Foreign keys are disabled in SQLite connection.")

    # 2. Schema and user version
    user_ver = con.execute("PRAGMA user_version").fetchone()[0]
    if user_ver < SCHEMA_VERSION:
        issues.append(f"Schema version mismatch: database is v{user_ver}, expected v{SCHEMA_VERSION}.")

    # 3. FTS synchronization check
    chunks_count = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    fts_count = con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    if chunks_count != fts_count:
        issues.append(f"FTS desynchronization: chunks table has {chunks_count} rows, chunks_fts has {fts_count} rows.")

    # 4. Orphan symbols
    orphan_syms = con.execute(
        "SELECT count(*) FROM symbols s LEFT JOIN files f ON s.path = f.path WHERE f.path IS NULL"
    ).fetchone()[0]
    if orphan_syms > 0:
        issues.append(f"Found {orphan_syms} orphan symbol(s) referencing non-existent files.")

    # 5. Orphan references
    orphan_refs = con.execute(
        "SELECT count(*) FROM 'references' r LEFT JOIN files f ON r.path = f.path WHERE f.path IS NULL"
    ).fetchone()[0]
    if orphan_refs > 0:
        issues.append(f"Found {orphan_refs} orphan reference(s) referencing non-existent files.")

    # 6. Duplicate canonical IDs within same file
    dups = con.execute(
        "SELECT canonical_id, path, count(*) FROM symbols "
        "GROUP BY canonical_id, path HAVING count(*) > 1"
    ).fetchall()
    if dups:
        issues.append(f"Found {len(dups)} duplicate canonical symbol ID(s) in same file.")

    # 7. Check parser version
    parser_ver = None
    try:
        prow = con.execute("SELECT value FROM metadata WHERE key='parser_version'").fetchone()
        if prow:
            parser_ver = str(prow[0])
    except sqlite3.OperationalError:
        pass
    if parser_ver and parser_ver != PARSER_VERSION:
        issues.append(f"Parser version mismatch: indexed with {parser_ver}, active parser is {PARSER_VERSION}.")

    # 8. Orphan framework routes
    orphan_routes = con.execute(
        "SELECT count(*) FROM framework_routes r LEFT JOIN files f ON r.file_path = f.path WHERE f.path IS NULL"
    ).fetchone()[0]
    if orphan_routes > 0:
        issues.append(f"Found {orphan_routes} orphan route(s) referencing non-existent files.")

    # 9. Duplicate endpoint IDs
    dup_routes = con.execute(
        "SELECT endpoint_id, count(*) FROM framework_routes GROUP BY endpoint_id HAVING count(*) > 1"
    ).fetchall()
    if dup_routes:
        issues.append(f"Found {len(dup_routes)} duplicate route endpoint ID(s).")

    status = "OK" if not issues else "ISSUES_FOUND"
    return {
        "status": status,
        "database_version": user_ver,
        "expected_version": SCHEMA_VERSION,
        "parser_version": parser_ver or PARSER_VERSION,
        "chunks_count": chunks_count,
        "fts_count": fts_count,
        "foreign_keys": bool(fk_enabled),
        "issues": issues,
    }
