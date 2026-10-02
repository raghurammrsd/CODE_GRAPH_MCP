from __future__ import annotations

import builtins
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self.session() as con:
            con.execute("CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def list(self) -> builtins.list[tuple[str, str]]: 
        with self.session() as con:
            return list(con.execute("SELECT key, value FROM memory ORDER BY key"))

    def search(self, query: str, limit: int = 20) -> builtins.list[tuple[str, str]]: 
        if not query.strip():
            raise ValueError("memory query must be non-empty")
        with self.session() as con:
            return list(con.execute(
                "SELECT key, value FROM memory WHERE key LIKE ? OR value LIKE ? ORDER BY key LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ))

    def clear(self) -> None:
        with self.session() as con:
            con.execute("DELETE FROM memory")
