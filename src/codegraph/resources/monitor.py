"""Cross-platform process resource monitoring for CodeGraph.

Provides portable resident memory (RSS) measurements across Windows, macOS,
and Linux without requiring Unix-only APIs at import or runtime.
"""
from __future__ import annotations

import sys
from typing import Any


def _get_unix_memory_mb() -> float | None:
    """Read process RSS using standard library resource module on Unix."""
    try:
        import resource  # Unix-only standard library module

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            # macOS ru_maxrss is returned in bytes
            return round(usage / (1024 * 1024), 2)
        else:
            # Linux and BSD ru_maxrss is returned in kilobytes
            return round(usage / 1024, 2)
    except Exception:
        return None


def _get_psutil_memory_mb() -> float | None:
    """Read process RSS using psutil if installed."""
    try:
        import psutil  # type: ignore[import-untyped]

        rss_bytes = float(psutil.Process().memory_info().rss)
        return round(rss_bytes / (1024 * 1024), 2)
    except Exception:
        return None


def _get_windows_memory_mb_ctypes() -> float | None:
    """Read process RSS on Windows using standard library ctypes (zero dependencies)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        windll: Any = getattr(ctypes, "windll", None)
        if windll is None:
            return None

        handle = windll.kernel32.GetCurrentProcess()
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)

        # On Windows 7+, K32GetProcessMemoryInfo is in kernel32; otherwise in psapi
        get_info = getattr(windll.kernel32, "K32GetProcessMemoryInfo", None)
        if get_info is None:
            psapi = getattr(windll, "psapi", None)
            if psapi is not None:
                get_info = getattr(psapi, "GetProcessMemoryInfo", None)

        if get_info is not None and bool(get_info(handle, ctypes.byref(counters), counters.cb)):
            # WorkingSetSize is the resident set size in bytes
            return round(float(counters.WorkingSetSize) / (1024 * 1024), 2)
    except Exception:
        return None
    return None


def get_process_memory_mb() -> float | None:
    """Return estimated resident process memory in megabytes cross-platform.

    Returns:
        float: Estimated memory in MB if measurement is supported and succeeds.
        None: If measurement is unsupported or fails (degrades gracefully to UNKNOWN).
    """
    if sys.platform == "win32":
        # 1. On Windows: try psutil first, then ctypes Windows API
        mem = _get_psutil_memory_mb()
        if mem is not None:
            return mem
        return _get_windows_memory_mb_ctypes()

    # 2. On Unix-like platforms (macOS, Linux): try standard resource module
    mem = _get_unix_memory_mb()
    if mem is not None:
        return mem

    # 3. Fallback to psutil on any platform if resource module failed or is unavailable
    return _get_psutil_memory_mb()
