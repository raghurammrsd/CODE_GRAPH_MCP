"""Resource Management, Concurrency Throttling, and Laptop Protection.

Provides:
- ResourceGovernor: Priority scheduling, cooperative yielding, process memory monitoring
- ResourcePolicy: Profiles (LIGHT, BALANCED, PERFORMANCE), bounds, and thresholds
- RequestCoalescer: De-duplicating identical concurrent flights
- FileChangeDebouncer: Coalescing editor save bursts
- BoundedMemoryCache: Memory-bounded LRU caches for parse results and graphs
"""
from __future__ import annotations

from .cache import (
    BoundedMemoryCache,
    get_graph_cache,
    get_parse_cache,
)
from .coalescer import RequestCoalescer, get_global_coalescer
from .debouncer import FileChangeDebouncer
from .governor import ResourceGovernor, get_global_governor
from .monitor import get_process_memory_mb
from .policy import (
    ActivityMode,
    PressureLevel,
    ResourcePolicy,
    ResourceProfile,
    ResourceState,
    TaskPriority,
)

__all__ = [
    "ActivityMode",
    "BoundedMemoryCache",
    "FileChangeDebouncer",
    "PressureLevel",
    "RequestCoalescer",
    "ResourceGovernor",
    "ResourcePolicy",
    "ResourceProfile",
    "ResourceState",
    "TaskPriority",
    "get_global_coalescer",
    "get_global_governor",
    "get_graph_cache",
    "get_parse_cache",
    "get_process_memory_mb",
]
