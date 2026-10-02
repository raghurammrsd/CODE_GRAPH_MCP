"""File Change Debouncer and Burst Coalescer.

Coalesces rapid file system save events from code editors into bounded batches
to prevent repeated, wasteful index cycles.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path


class FileChangeDebouncer:
    """Thread-safe debounce accumulator for editor save bursts."""

    def __init__(
        self,
        debounce_ms: int = 500,
        max_batch_size: int = 100,
        on_batch: Callable[[set[str]], None] | None = None,
    ) -> None:
        self.debounce_ms = debounce_ms
        self.max_batch_size = max_batch_size
        self.on_batch = on_batch

        self._lock = threading.Lock()
        self._pending_paths: set[str] = set()
        self._timer: threading.Timer | None = None
        self._last_event_time: float = 0.0

    def add_change(self, path: str | Path) -> None:
        """Record a file modification or save event."""
        p_str = path.as_posix() if isinstance(path, Path) else str(path)
        with self._lock:
            self._pending_paths.add(p_str)
            self._last_event_time = time.time()

            if len(self._pending_paths) >= self.max_batch_size:
                self._dispatch_locked()
                return

            if self._timer is not None:
                self._timer.cancel()

            delay_sec = self.debounce_ms / 1000.0
            self._timer = threading.Timer(delay_sec, self._on_timer_fired)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer_fired(self) -> None:
        with self._lock:
            self._dispatch_locked()

    def _dispatch_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        if not self._pending_paths:
            return

        batch = set(self._pending_paths)
        self._pending_paths.clear()

        if self.on_batch:
            # Dispatch outside lock or in thread to avoid deadlocks
            threading.Thread(target=self.on_batch, args=(batch,), daemon=True).start()

    def flush(self) -> set[str]:
        """Synchronously drain all pending coalesced paths."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            batch = set(self._pending_paths)
            self._pending_paths.clear()
            return batch

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending_paths)

    def record_change(self, path: str | Path) -> None:
        """Alias for add_change."""
        self.add_change(path)

    def start(self, on_batch: Callable[[set[str]], None]) -> None:
        """Configure or update batch callback."""
        with self._lock:
            self.on_batch = on_batch

    def stop(self) -> None:
        """Cancel any pending timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
