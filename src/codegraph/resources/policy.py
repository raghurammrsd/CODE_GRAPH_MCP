"""Resource Policies, Profiles, Task Priorities, and State Models.

Defines bounded execution budgets, memory limits, concurrency profiles,
and cooperative pressure levels without platform-specific hardware assumptions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ResourceProfile(StrEnum):
    LIGHT = "LIGHT"
    BALANCED = "BALANCED"
    PERFORMANCE = "PERFORMANCE"


class PressureLevel(StrEnum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskPriority(StrEnum):
    INTERACTIVE_HIGH = "INTERACTIVE_HIGH"
    INTERACTIVE_NORMAL = "INTERACTIVE_NORMAL"
    BACKGROUND = "BACKGROUND"
    MAINTENANCE = "MAINTENANCE"


class ActivityMode(StrEnum):
    ACTIVE_CODING = "ACTIVE_CODING"
    IDLE = "IDLE"
    BACKGROUND = "BACKGROUND"


@dataclass(frozen=True)
class ResourcePolicy:
    profile: ResourceProfile = ResourceProfile.BALANCED
    max_interactive_workers: int = 2
    max_background_workers: int = 1
    max_files_per_incremental_batch: int = 25
    max_graph_nodes_per_query: int = 300
    max_graph_edges_per_query: int = 1200
    max_git_commits: int = 15
    max_memory_mb: int = 1024
    max_cpu_time_ms_per_request: int = 5000
    background_enabled: bool = True
    aggressive_throttling: bool = True
    debounce_ms: int = 500

    @classmethod
    def for_profile(cls, profile: str | ResourceProfile) -> ResourcePolicy:
        p = ResourceProfile(str(profile).upper()) if isinstance(profile, str) else profile
        if p == ResourceProfile.LIGHT:
            return cls(
                profile=ResourceProfile.LIGHT,
                max_interactive_workers=1,
                max_background_workers=1,
                max_files_per_incremental_batch=10,
                max_graph_nodes_per_query=100,
                max_graph_edges_per_query=400,
                max_git_commits=5,
                max_memory_mb=512,
                max_cpu_time_ms_per_request=2000,
                background_enabled=True,
                aggressive_throttling=True,
                debounce_ms=800,
            )
        elif p == ResourceProfile.PERFORMANCE:
            return cls(
                profile=ResourceProfile.PERFORMANCE,
                max_interactive_workers=4,
                max_background_workers=2,
                max_files_per_incremental_batch=100,
                max_graph_nodes_per_query=1000,
                max_graph_edges_per_query=5000,
                max_git_commits=50,
                max_memory_mb=4096,
                max_cpu_time_ms_per_request=15000,
                background_enabled=True,
                aggressive_throttling=False,
                debounce_ms=250,
            )
        else:
            return cls(
                profile=ResourceProfile.BALANCED,
                max_interactive_workers=2,
                max_background_workers=1,
                max_files_per_incremental_batch=25,
                max_graph_nodes_per_query=300,
                max_graph_edges_per_query=1200,
                max_git_commits=15,
                max_memory_mb=1024,
                max_cpu_time_ms_per_request=5000,
                background_enabled=True,
                aggressive_throttling=True,
                debounce_ms=500,
            )

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["profile"] = self.profile.value
        return d


@dataclass(frozen=True)
class ResourceState:
    policy_profile: str = ResourceProfile.BALANCED.value
    active_interactive_requests: int = 0
    active_background_tasks: int = 0
    queued_tasks: int = 0
    recent_cpu_time_ms: float = 0.0
    recent_wall_time_ms: float = 0.0
    estimated_memory_mb: float | None = None
    pressure_level: str = PressureLevel.NORMAL.value
    activity_mode: str = ActivityMode.IDLE.value
    indexing_active: bool = False
    watcher_active: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
