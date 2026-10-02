"""Optional local audit log for MCP tool operations.

Records: timestamp, tool, operation, repository, files accessed, duration.
File contents are NEVER recorded.
Log can be cleared via CLI.  Disabled by default.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AuditLog:
    """SQLite-backed local audit log.  Contents never include source code."""

    def __init__(self, db_path: Path, enabled: bool = False) -> None:
        self.db_path = db_path
        self.enabled = enabled
        if enabled:
            self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_table(self) -> None:
        with self._session() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY,
                    ts INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    files_accessed TEXT NOT NULL DEFAULT '[]',
                    duration_ms REAL NOT NULL DEFAULT 0
                )
            """)

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def record(
        self,
        tool: str,
        operation: str,
        repository: str,
        files_accessed: list[str] | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        if not self.enabled:
            return
        with self._session() as con:
            con.execute(
                "INSERT INTO audit_log(ts, tool, operation, repository, files_accessed, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    int(time.time()),
                    tool,
                    operation,
                    repository,
                    json.dumps(files_accessed or []),
                    duration_ms,
                ),
            )

    def recent(self, limit: int = 100) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        with self._session() as con:
            rows = con.execute(
                "SELECT ts, tool, operation, repository, files_accessed, duration_ms "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "ts": r["ts"],
                    "tool": r["tool"],
                    "operation": r["operation"],
                    "repository": r["repository"],
                    "files_accessed": json.loads(r["files_accessed"]),
                    "duration_ms": r["duration_ms"],
                }
                for r in rows
            ]

    def clear(self) -> None:
        if not self.enabled:
            return
        with self._session() as con:
            con.execute("DELETE FROM audit_log")
