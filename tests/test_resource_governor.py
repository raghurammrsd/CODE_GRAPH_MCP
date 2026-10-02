from __future__ import annotations

import time

from codegraph.resources import (
    ActivityMode,
    PressureLevel,
    ResourceGovernor,
    ResourcePolicy,
    ResourceProfile,
    TaskPriority,
)


def test_resource_policy_profiles() -> None:
    p_light = ResourcePolicy.for_profile(ResourceProfile.LIGHT)
    assert p_light.max_interactive_workers == 1
    assert p_light.max_background_workers == 1
    assert p_light.profile == ResourceProfile.LIGHT

    p_perf = ResourcePolicy.for_profile(ResourceProfile.PERFORMANCE)
    assert p_perf.max_interactive_workers >= 4
    assert p_perf.profile == ResourceProfile.PERFORMANCE

    p_bal = ResourcePolicy.for_profile(ResourceProfile.BALANCED)
    assert p_bal.profile == ResourceProfile.BALANCED
    assert p_bal.max_interactive_workers == 2


def test_resource_governor_task_scope_and_state() -> None:
    policy = ResourcePolicy.for_profile(ResourceProfile.BALANCED)
    gov = ResourceGovernor(policy)

    state = gov.get_state()
    assert state.policy_profile == "BALANCED"
    assert state.active_interactive_requests == 0
    assert state.active_background_tasks == 0
    assert state.activity_mode == "IDLE"

    with gov.task_scope(TaskPriority.INTERACTIVE_HIGH):
        inner_state = gov.get_state()
        assert inner_state.active_interactive_requests == 1
        assert gov.is_active_coding() is True
        assert gov.get_activity_mode() == ActivityMode.ACTIVE_CODING

    after_state = gov.get_state()
    assert after_state.active_interactive_requests == 0
    assert after_state.recent_wall_time_ms >= 0


def test_resource_governor_pressure_levels() -> None:
    policy = ResourcePolicy(
        profile=ResourceProfile.BALANCED,
        max_memory_mb=10,  # artificially small
    )
    gov = ResourceGovernor(policy)
    # Process memory will easily exceed 10MB, triggering CRITICAL
    pressure = gov.get_pressure()
    assert pressure in (PressureLevel.HIGH, PressureLevel.CRITICAL)

    # With high memory limit, pressure is NORMAL
    gov.set_policy(ResourcePolicy(max_memory_mb=100_000))
    assert gov.get_pressure() == PressureLevel.NORMAL


def test_resource_governor_cooperative_yield() -> None:
    gov = ResourceGovernor()
    # High priority does not throttle or yield
    assert gov.should_throttle(TaskPriority.INTERACTIVE_HIGH) is False
    t0 = time.perf_counter()
    gov.yield_if_needed(TaskPriority.INTERACTIVE_HIGH)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05
