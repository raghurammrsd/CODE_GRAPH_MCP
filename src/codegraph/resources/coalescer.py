"""Thread-safe Request Coalescing and In-Flight Flight Sharing.

Prevents duplicate concurrent executions of identical read or compilation requests
by allowing concurrent callers to share a single in-flight computation.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class _InFlight[T]:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: T | None = None
        self.error: BaseException | None = None


class RequestCoalescer:
    """Coalesces identical concurrent tasks into a single execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[str, _InFlight[Any]] = {}
        self._coalesced_count: int = 0
        self._total_requests: int = 0

    def coalesce[T](self, key: str, fn: Callable[[], T]) -> T:
        """Execute fn() or wait for an identical in-flight execution under the given key."""
        with self._lock:
            self._total_requests += 1
            flight: _InFlight[T] | None = self._flights.get(key)
            if flight is not None:
                is_leader = False
                self._coalesced_count += 1
            else:
                is_leader = True
                flight = _InFlight[T]()
                self._flights[key] = flight

        if not is_leader:
            # Wait for leader to complete computation
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.result  # type: ignore[return-value]

        # Leader executes fn()
        try:
            res = fn()
            flight.result = res
            return res
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.event.set()

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._flights)

    def clear(self) -> None:
        with self._lock:
            self._flights.clear()

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "in_flight": len(self._flights),
                "total_requests": self._total_requests,
                "coalesced_requests": self._coalesced_count,
            }


_GLOBAL_COALESCER = RequestCoalescer()


def get_global_coalescer() -> RequestCoalescer:
    return _GLOBAL_COALESCER
