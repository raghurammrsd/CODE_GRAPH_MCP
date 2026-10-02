"""Central Resource Governor for CodeGraph MCP.

Protects developer laptop responsiveness during active coding by bounding concurrency,
throttling background indexing, managing process memory, and cooperatively yielding.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from .monitor import get_process_memory_mb
from .policy import (
    ActivityMode,
    PressureLevel,
    ResourcePolicy,
    ResourceProfile,
    ResourceState,
    TaskPriority,
)


class ResourceGovernor:
    """Thread-safe central resource governor and priority scheduler."""

    def __init__(self, policy: ResourcePolicy | None = None) -> None:
        self.policy = policy or ResourcePolicy.for_profile(ResourceProfile.BALANCED)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)

        self._active_interactive: int = 0
        self._active_background: int = 0
        self._queued_tasks: int = 0
        self._indexing_active: bool = False
        self._watcher_active: bool = False

        self._last_interactive_time: float = 0.0
        self._last_file_change_time: float = 0.0

        self._recent_cpu_time_ms: float = 0.0
        self._recent_wall_time_ms: float = 0.0

        self._interactive_sem = threading.Semaphore(self.policy.max_interactive_workers)
        self._background_sem = threading.Semaphore(self.policy.max_background_workers)

    def set_policy(self, policy: ResourcePolicy) -> None:
        """Update runtime policy dynamically."""
        with self._lock:
            self.policy = policy
            self._interactive_sem = threading.Semaphore(policy.max_interactive_workers)
            self._background_sem = threading.Semaphore(policy.max_background_workers)
            self._condition.notify_all()

    def record_activity(self, kind: str = "interactive") -> None:
        """Record non-invasive activity to maintain active coding state."""
        now = time.time()
        with self._lock:
            if kind == "file_change":
                self._last_file_change_time = now
            else:
                self._last_interactive_time = now

    def get_activity_mode(self) -> ActivityMode:
        """Infer activity mode from recent MCP and file change events."""
        with self._lock:
            now = time.time()
            recent_interactive = (now - self._last_interactive_time) < 45.0
            recent_files = (now - self._last_file_change_time) < 45.0
            if recent_interactive or recent_files:
                return ActivityMode.ACTIVE_CODING
            if self._active_background > 0 or self._indexing_active:
                return ActivityMode.BACKGROUND
            return ActivityMode.IDLE

    def is_active_coding(self) -> bool:
        return self.get_activity_mode() == ActivityMode.ACTIVE_CODING

    def get_pressure(self) -> PressureLevel:
        """Compute system resource pressure with conservative hysteresis."""
        mem_mb = get_process_memory_mb()
        limit_mb = self.policy.max_memory_mb

        with self._lock:
            active_inter = self._active_interactive

        if mem_mb is not None and limit_mb and mem_mb >= limit_mb * 0.90:
            return PressureLevel.CRITICAL
        if active_inter >= self.policy.max_interactive_workers * 2:
            return PressureLevel.CRITICAL

        if mem_mb is not None and limit_mb and mem_mb >= limit_mb * 0.75:
            return PressureLevel.HIGH
        if active_inter > self.policy.max_interactive_workers:
            return PressureLevel.HIGH

        if mem_mb is not None and limit_mb and mem_mb >= limit_mb * 0.60:
            return PressureLevel.ELEVATED
        if active_inter > 0:
            return PressureLevel.ELEVATED

        return PressureLevel.NORMAL

    def should_throttle(self, priority: TaskPriority = TaskPriority.BACKGROUND) -> bool:
        """Check whether a background or maintenance task should throttle or yield."""
        if priority in (TaskPriority.INTERACTIVE_HIGH, TaskPriority.INTERACTIVE_NORMAL):
            return False
        pressure = self.get_pressure()
        if pressure in (PressureLevel.CRITICAL, PressureLevel.HIGH):
            return True
        return self.is_active_coding()

    def yield_if_needed(self, priority: TaskPriority = TaskPriority.BACKGROUND) -> None:
        """Cooperative yield point for long-running iterative tasks."""
        if priority in (TaskPriority.INTERACTIVE_HIGH, TaskPriority.INTERACTIVE_NORMAL):
            return

        pressure = self.get_pressure()
        if pressure == PressureLevel.CRITICAL:
            # Under critical pressure, background work yields for 100ms
            time.sleep(0.10)
        elif pressure == PressureLevel.HIGH or self.is_active_coding():
            # Under high pressure or active coding, yield 20ms to free up CPU
            time.sleep(0.02)
        else:
            # Minimal cooperative yield to let OS reschedule other threads
            time.sleep(0.001)

    def get_state(self) -> ResourceState:
        """Snapshot current resource state."""
        mem = get_process_memory_mb()
        pressure = self.get_pressure()
        mode = self.get_activity_mode()
        with self._lock:
            return ResourceState(
                policy_profile=self.policy.profile.value,
                active_interactive_requests=self._active_interactive,
                active_background_tasks=self._active_background,
                queued_tasks=self._queued_tasks,
                recent_cpu_time_ms=round(self._recent_cpu_time_ms, 2),
                recent_wall_time_ms=round(self._recent_wall_time_ms, 2),
                estimated_memory_mb=mem,
                pressure_level=pressure.value,
                activity_mode=mode.value,
                indexing_active=self._indexing_active,
                watcher_active=self._watcher_active,
            )

    @contextmanager
    def task_scope(
        self,
        priority: TaskPriority = TaskPriority.INTERACTIVE_HIGH,
        task_id: str | None = None,
    ) -> Iterator[None]:
        """Scoped execution guard that handles priority scheduling, tracking, and yielding."""
        del task_id
        is_interactive = priority in (TaskPriority.INTERACTIVE_HIGH, TaskPriority.INTERACTIVE_NORMAL)
        sem = self._interactive_sem if is_interactive else self._background_sem

        with self._lock:
            self._queued_tasks += 1
            if is_interactive:
                self.record_activity("interactive")

        sem.acquire()
        try:
            throttle = False
            with self._lock:
                self._queued_tasks = max(0, self._queued_tasks - 1)
                if is_interactive:
                    self._active_interactive += 1
                else:
                    self._active_background += 1
                    if self.is_active_coding() and self.policy.aggressive_throttling:
                        throttle = True
            if throttle:
                time.sleep(0.01)

            t0_cpu = time.process_time()
            t0_wall = time.perf_counter()
            try:
                yield
            finally:
                elapsed_cpu = (time.process_time() - t0_cpu) * 1000
                elapsed_wall = (time.perf_counter() - t0_wall) * 1000
                with self._lock:
                    if is_interactive:
                        self._active_interactive = max(0, self._active_interactive - 1)
                        self._last_interactive_time = time.time()
                    else:
                        self._active_background = max(0, self._active_background - 1)
                    self._recent_cpu_time_ms = elapsed_cpu
                    self._recent_wall_time_ms = elapsed_wall
                    self._condition.notify_all()
        finally:
            sem.release()

    def set_indexing_active(self, active: bool) -> None:
        with self._lock:
            self._indexing_active = active

    def set_watcher_active(self, active: bool) -> None:
        with self._lock:
            self._watcher_active = active


_GLOBAL_GOVERNOR: ResourceGovernor | None = None
_GOVERNOR_LOCK = threading.Lock()


def get_global_governor(policy: ResourcePolicy | None = None) -> ResourceGovernor:
    """Access the singleton resource governor for the current process."""
    global _GLOBAL_GOVERNOR
    with _GOVERNOR_LOCK:
        if _GLOBAL_GOVERNOR is None:
            _GLOBAL_GOVERNOR = ResourceGovernor(policy)
        elif policy is not None:
            _GLOBAL_GOVERNOR.set_policy(policy)
        return _GLOBAL_GOVERNOR
