"""Thread-safe SQLite connection pool for concurrent MCP and CLI execution."""
from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from .classifier import make_compat_row


class SQLiteConnectionPool:
    """Thread-safe, re-entrant connection pool for SQLite databases.

    Features:
    - Thread-safe LIFO pool to maximize SQLite cache reuse.
    - WAL mode, synchronous=NORMAL, foreign_keys=ON, busy_timeout=30000ms.
    - check_same_thread=False for cross-thread pool handoff.
    - Re-entrant per-thread acquisition (nesting depth tracking via thread-local state).
    - Optional initializer hook for idempotent schema / setup execution.
    """

    def __init__(
        self,
        db_path: Path | str,
        max_size: int = 16,
        timeout: float = 30.0,
        initializer: Callable[[sqlite3.Connection], None] | None = None,
    ) -> None:
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self.max_size = max(1, max_size)
        self.timeout = timeout
        self.initializer = initializer
        self._pool: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()
        self._local = threading.local()

    def _create_connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=self.timeout,
        )
        con.row_factory = make_compat_row
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("PRAGMA cache_size = -64000")
        con.execute("PRAGMA temp_store = MEMORY")
        if self.initializer is not None:
            self.initializer(con)
        return con

    def acquire(self) -> tuple[sqlite3.Connection, bool]:
        """Acquire a connection. Returns (connection, is_owner).

        If the current thread already holds a connection from this pool,
        it increments the re-entrancy depth and returns (connection, False).
        """
        active_con = getattr(self._local, "con", None)
        if active_con is not None:
            self._local.nesting = getattr(self._local, "nesting", 0) + 1
            return active_con, False

        con: sqlite3.Connection | None = None
        try:
            con = self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.max_size:
                    con = self._create_connection()
                    self._created += 1

            if con is None:
                con = self._pool.get(timeout=self.timeout)

        self._local.con = con
        self._local.nesting = 1
        return con, True

    def release(
        self,
        con: sqlite3.Connection,
        is_owner: bool,
        rollback: bool = False,
    ) -> None:
        """Release a connection back to the pool."""
        if not is_owner:
            cur_nesting = getattr(self._local, "nesting", 1) - 1
            self._local.nesting = max(0, cur_nesting)
            if rollback:
                try:
                    con.rollback()
                except Exception:
                    pass
            return

        self._local.con = None
        self._local.nesting = 0
        if rollback:
            try:
                con.rollback()
            except Exception:
                pass
        else:
            try:
                con.commit()
            except Exception:
                pass

        try:
            self._pool.put_nowait(con)
        except Exception:
            try:
                con.close()
            except Exception:
                pass

    def close_all(self) -> None:
        """Close and dispose all connections in the pool."""
        with self._lock:
            while True:
                try:
                    con = self._pool.get_nowait()
                    try:
                        con.close()
                    except Exception:
                        pass
                except queue.Empty:
                    break
            self._created = 0
            self._local.con = None
            self._local.nesting = 0
