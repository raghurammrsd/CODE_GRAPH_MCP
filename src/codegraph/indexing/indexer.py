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
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from codegraph.config import Settings
from codegraph.frameworks import RouteDetection
from codegraph.resolver import ReferenceResolver
from codegraph.resources import (
    ResourceGovernor,
    TaskPriority,
    get_global_governor,
    get_parse_cache,
)

from .models import (
    CallRef,
    ImportRef,
    InheritanceRef,
    Symbol,
)
from .parser import PARSER_VERSION, parse
from .scanner import scan

SCHEMA_VERSION = 6

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
"""


class Indexer:
    def __init__(
        self,
        repository: Path,
        settings: Settings | None = None,
        governor: ResourceGovernor | None = None,
    ) -> None:
        self.repository = repository.resolve(strict=True)
        self.settings = settings or Settings()
        self.db_path = self.settings.db_path or self.repository / ".codegraph.sqlite3"
        self.governor = governor or get_global_governor()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
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

    def index(self) -> dict[str, int]:
        """Perform an incremental indexing pass, followed by global reference resolution."""
        indexed = unchanged = parse_failed_count = 0
        from codegraph.freshness import current_commit, save_commit

        with self.governor.task_scope(TaskPriority.BACKGROUND):
            self.governor.set_indexing_active(True)
            try:
                files = scan(self.repository, self.settings.max_file_size, self.settings.exclude)
                seen = {item.relative_path.as_posix() for item in files}
                batch_limit = self.governor.policy.max_files_per_incremental_batch

                with self.session() as con:
                    # Check parser version invalidation
                    last_parser_ver = None
                    try:
                        row = con.execute("SELECT value FROM metadata WHERE key='parser_version'").fetchone()
                        if row:
                            last_parser_ver = str(row[0])
                    except sqlite3.OperationalError:
                        pass

                    force_reparse = (last_parser_ver != PARSER_VERSION)

                    for idx, item in enumerate(files):
                        if idx > 0 and idx % batch_limit == 0:
                            self.governor.yield_if_needed(TaskPriority.BACKGROUND)

                        relative = item.relative_path.as_posix()
                        content = item.path.read_text(encoding="utf-8", errors="replace")
                        digest = hashlib.sha256(content.encode()).hexdigest()
                        old = con.execute(
                            "SELECT hash, status FROM files WHERE path=?", (relative,)
                        ).fetchone()

                        if old and old["hash"] == digest and not force_reparse:
                            if old["status"] == "parse_failed":
                                parse_failed_count += 1
                            else:
                                unchanged += 1
                            continue

                        cat_obj = getattr(item, "category", None)
                        cat_str = str(cat_obj.value) if cat_obj is not None and hasattr(cat_obj, "value") else "SOURCE"
                        success = self._replace_file(con, relative, item.language, content, digest, category=cat_str)
                        if success:
                            indexed += 1
                        else:
                            parse_failed_count += 1

                    stale = [
                        r[0]
                        for r in con.execute("SELECT path FROM files")
                        if r[0] not in seen
                    ]
                    for path in stale:
                        self._delete_file(con, path)

                    # Record metadata
                    head_commit = current_commit(self.repository)
                    now_ts = int(time.time())
                    save_commit(con, head_commit, now_ts)

                    # Increment index generation
                    current_gen = 0
                    try:
                        grow = con.execute("SELECT value FROM metadata WHERE key='index_generation'").fetchone()
                        if grow and grow[0]:
                            current_gen = int(grow[0])
                    except (sqlite3.OperationalError, ValueError):
                        pass
                    next_gen = current_gen + 1

                    for key, val in [
                        ("repository", str(self.repository)),
                        ("parser_version", PARSER_VERSION),
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("index_generation", str(next_gen)),
                        ("index_timestamp", str(now_ts)),
                    ]:
                        con.execute(
                            "INSERT INTO metadata(key, value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, val),
                        )

                    # Run global reference resolution pass if any files were changed or removed
                    if indexed > 0 or len(stale) > 0 or force_reparse:
                        self._run_global_resolution(con, head_commit)
                        # Invalidate context cache on index update
                        try:
                            con.execute("DELETE FROM context_cache")
                        except sqlite3.OperationalError:
                            pass
            finally:
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

    def _delete_file(self, con: sqlite3.Connection, path: str) -> None:
        """Atomically delete all indexed facts for a file, maintaining FTS synchronization."""
        ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE path=?", (path,))]
        for chunk_id in ids:
            con.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
        con.execute("DELETE FROM chunks WHERE path=?", (path,))
        con.execute("DELETE FROM symbols WHERE path=?", (path,))
        con.execute("DELETE FROM imports WHERE source_path=?", (path,))
        con.execute("DELETE FROM calls WHERE source_path=?", (path,))
        con.execute("DELETE FROM inheritance WHERE source_file=?", (path,))
        con.execute("DELETE FROM framework_routes WHERE file_path=?", (path,))
        con.execute("DELETE FROM 'references' WHERE path=?", (path,))
        con.execute("DELETE FROM graph_edges WHERE file=?", (path,))
        con.execute("DELETE FROM files WHERE path=?", (path,))

    def _replace_file(
        self,
        con: sqlite3.Connection,
        path: str,
        language: str,
        content: str,
        digest: str,
        category: str = "SOURCE",
    ) -> bool:
        """Parse and insert a file. If parse fails, preserves last-known-good state."""
        parse_cache = get_parse_cache()
        cached = parse_cache.get((digest, PARSER_VERSION, language))
        if cached is not None:
            result = cached
        else:
            result = parse(content, language, path)
            parse_cache.put((digest, PARSER_VERSION, language), result)
        now = int(time.time())

        if result.parse_failed:
            # Parse failure safety: check if file previously existed
            old = con.execute("SELECT hash, status FROM files WHERE path=?", (path,)).fetchone()
            if old:
                # Retain last-known-good index records, mark file as parse_failed
                con.execute(
                    "UPDATE files SET hash=?, status='parse_failed', parse_error=?, indexed_at=?, category=? WHERE path=?",
                    (digest, result.parse_error, now, category, path),
                )
            else:
                con.execute(
                    "INSERT INTO files(path, hash, language, indexed_at, status, parse_error, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (path, digest, language, now, "parse_failed", result.parse_error, category),
                )
            return False

        # Successful parse: clean up old file state
        self._delete_file(con, path)
        con.execute(
            "INSERT INTO files(path, hash, language, indexed_at, status, parse_error, last_valid_hash, category) "
            "VALUES (?, ?, ?, ?, 'ok', NULL, ?, ?)",
            (path, digest, language, now, digest, category),
        )

        if category == "GENERATED":
            # Suppress generated bundle noise: do not extract AST symbols or populate chunks_fts
            return True

        lines = content.splitlines()

        if result.symbols:
            for s in result.symbols:
                dec_str = ",".join(s.decorators) if s.decorators else ""
                con.execute(
                    "INSERT INTO symbols("
                    "name, qualified_name, kind, path, start_line, end_line, decorators, "
                    "id, canonical_id, language, module, scope, signature, content_hash, "
                    "parent_symbol_id, visibility, return_type, parameter_count, documentation) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                        s.signature,
                        s.content_hash,
                        s.parent_symbol_id,
                        s.visibility,
                        s.return_type,
                        s.parameter_count,
                        s.documentation,
                    ),
                )
                body = "\n".join(lines[s.start_line - 1 : s.end_line])
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
                con.execute(
                    "INSERT INTO chunks_fts(rowid, content, path, symbol) VALUES (?,?,?,?)",
                    (cur.lastrowid, body, path, s.qualified_name),
                )
        else:
            cur = con.execute(
                "INSERT INTO chunks(path, language, symbol, symbol_type, start_line, end_line, content, hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (path, language, None, "module", 1, max(1, len(lines)), content, digest),
            )
            con.execute(
                "INSERT INTO chunks_fts(rowid, content, path, symbol) VALUES (?,?,?,?)",
                (cur.lastrowid, content, path, None),
            )

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

        if result.routes:
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
                        r.evidence,
                        r.confidence,
                    )
                    for r in result.routes
                ],
            )

        return True

    def _run_global_resolution(
        self, con: sqlite3.Connection, indexed_commit: str | None
    ) -> None:
        """Run repository-wide reference resolution, updating 'references' and 'graph_edges'."""
        # 1. Load all files
        file_rows = con.execute("SELECT path, hash FROM files WHERE status='ok'").fetchall()
        known_files = {str(r["path"]) for r in file_rows}
        file_hashes = {str(r["path"]): str(r["hash"]) for r in file_rows}

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

        # 6. Load framework routes
        rt_rows = con.execute(
            "SELECT endpoint_id, framework, http_method, route_path, normalized_route, "
            "handler_name, handler_canonical_id, file_path, line, evidence, confidence "
            "FROM framework_routes"
        ).fetchall()
        routes = [
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
            )
            for r in rt_rows
        ]

        # Run resolution engine
        resolver = ReferenceResolver(
            symbols=symbols,
            imports=imports,
            calls=calls,
            inheritance=inheritance,
            routes=routes,
            known_files=known_files,
            file_hashes=file_hashes,
            indexed_commit=indexed_commit,
        )
        output = resolver.resolve_all()

        # Update references table
        con.execute("DELETE FROM 'references'")
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
                    ref.evidence,
                    ref.source_hash,
                    ref.indexed_commit,
                    ref.evidence_status,
                )
                for ref in output.references
            ],
        )

        # Update graph_edges table
        con.execute("DELETE FROM graph_edges")
        con.executemany(
            "INSERT INTO graph_edges("
            "source, target, relationship, confidence, file, start_line, end_line, "
            "evidence, evidence_id, source_hash, indexed_commit) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    e.source,
                    e.target,
                    e.relationship,
                    e.confidence,
                    e.file,
                    e.start_line,
                    e.end_line,
                    e.evidence,
                    f"edge_{idx}",
                    file_hashes.get(e.file, ""),
                    indexed_commit,
                )
                for idx, e in enumerate(output.edges)
            ],
        )

        # Update resolved fields on imports and calls tables
        for (src_path, ln, loc_name), (tgt_path, tgt_mod) in output.resolved_imports.items():
            con.execute(
                "UPDATE imports SET resolved_path=?, resolved_module=? "
                "WHERE source_path=? AND line=? AND (local_name=? OR alias=? OR name=?)",
                (tgt_path, tgt_mod, src_path, ln, loc_name, loc_name, loc_name),
            )

        for (src_path, ln, callee_nm), (resolved_id, conf) in output.resolved_calls.items():
            con.execute(
                "UPDATE calls SET resolved_symbol_id=?, confidence=? "
                "WHERE source_path=? AND line=? AND callee=?",
                (resolved_id, conf, src_path, ln, callee_nm),
            )


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
