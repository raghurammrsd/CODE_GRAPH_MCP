from __future__ import annotations

import time

from codegraph.resources import (
    ActivityMode,
    ResourceGovernor,
    ResourcePolicy,
    ResourceProfile,
    TaskPriority,
)


def test_active_coding_detection_and_decay() -> None:
    gov = ResourceGovernor()
    assert gov.is_active_coding() is False
    assert gov.get_activity_mode() == ActivityMode.IDLE

    # User interacts with MCP or saves file
    gov.record_activity("interactive")
    assert gov.is_active_coding() is True
    assert gov.get_activity_mode() == ActivityMode.ACTIVE_CODING

    # Background tasks should be throttled during active coding if aggressive_throttling is enabled
    assert gov.should_throttle(TaskPriority.BACKGROUND) is True
    assert gov.should_throttle(TaskPriority.INTERACTIVE_HIGH) is False


def test_background_cooperative_yield_under_pressure() -> None:
    gov = ResourceGovernor(ResourcePolicy.for_profile(ResourceProfile.LIGHT))
    # Artificially trigger elevated pressure
    gov.record_activity("file_change")

    t0 = time.perf_counter()
    gov.yield_if_needed(TaskPriority.BACKGROUND)
    elapsed = time.perf_counter() - t0
    # Throttling yields for at least a brief sleep
    assert elapsed >= 0.005


def test_resource_governor_as_dict() -> None:
    gov = ResourceGovernor()
    d = gov.get_state().as_dict()
    assert "policy_profile" in d
    assert "pressure_level" in d
    assert "activity_mode" in d
    assert "estimated_memory_mb" in d
    assert "active_interactive_requests" in d
    assert "active_background_tasks" in d
