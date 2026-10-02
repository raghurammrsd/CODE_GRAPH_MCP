"""Tests for cross-platform resource monitoring, Windows portability, and governor degradation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.resources import (
    ActivityMode,
    PressureLevel,
    ResourceGovernor,
    ResourcePolicy,
    ResourceProfile,
    TaskPriority,
    get_process_memory_mb,
)
from codegraph.resources.monitor import (
    _get_psutil_memory_mb,
    _get_unix_memory_mb,
    _get_windows_memory_mb_ctypes,
)


def test_windows_import_and_startup_path() -> None:
    """Verify that importing resources and CLI on Windows (where resource is absent) succeeds."""
    # Mask the 'resource' module to simulate a Windows environment where it does not exist
    with patch.dict(sys.modules, {"resource": None}):
        with patch("sys.platform", "win32"):
            # Ensure calling monitor functions does not attempt to import resource or raise ModuleNotFoundError
            mem = get_process_memory_mb()
            # Under mocked win32 without real Windows kernel, it gracefully returns None (or float if psutil available)
            assert mem is None or isinstance(mem, float)

            # Creating a governor and getting its state must succeed without resource
            gov = ResourceGovernor()
            state = gov.get_state()
            assert state.policy_profile == "BALANCED"


def test_unix_import_and_startup_path() -> None:
    """Verify that on Unix/macOS, native resource interrogation succeeds."""
    if sys.platform in ("darwin", "linux"):
        mem = _get_unix_memory_mb()
        assert mem is not None
        assert isinstance(mem, float)
        assert mem > 0.0

        # get_process_memory_mb() returns positive float
        total_mem = get_process_memory_mb()
        assert total_mem is not None
        assert total_mem > 0.0


def test_resource_measurement_psutil_success() -> None:
    """Verify that psutil returns memory when available."""
    mock_process = MagicMock()
    mock_process.memory_info.return_value.rss = 104857600  # 100 MB in bytes

    mock_psutil = MagicMock()
    mock_psutil.Process.return_value = mock_process

    with patch.dict(sys.modules, {"psutil": mock_psutil}):
        mem = _get_psutil_memory_mb()
        assert mem == 100.0


def test_resource_measurement_windows_ctypes_success() -> None:
    """Verify Windows ctypes memory interrogation when windll is available."""
    mock_windll = MagicMock()
    mock_handle = MagicMock()
    mock_windll.kernel32.GetCurrentProcess.return_value = mock_handle

    def fake_get_info(handle: object, byref_counters: object, cb: int) -> int:
        # Access the real struct passed in byref
        # In ctypes, byref wraps an _obj attribute
        counters = getattr(byref_counters, "_obj", None)
        if counters is not None:
            counters.WorkingSetSize = 52428800  # 50 MB
        return 1

    mock_windll.kernel32.K32GetProcessMemoryInfo = fake_get_info

    import ctypes

    with patch.object(ctypes, "windll", mock_windll, create=True):
        mem = _get_windows_memory_mb_ctypes()
        assert mem == 50.0


def test_resource_measurement_unavailable_failure() -> None:
    """Verify graceful degradation to None (UNKNOWN) when all measurement backends fail."""
    with patch("codegraph.resources.monitor._get_unix_memory_mb", return_value=None):
        with patch("codegraph.resources.monitor._get_psutil_memory_mb", return_value=None):
            with patch("codegraph.resources.monitor._get_windows_memory_mb_ctypes", return_value=None):
                with patch("sys.platform", "win32"):
                    assert get_process_memory_mb() is None
                with patch("sys.platform", "linux"):
                    assert get_process_memory_mb() is None
                with patch("sys.platform", "darwin"):
                    assert get_process_memory_mb() is None


def test_governor_behavior_when_memory_measurement_is_unknown() -> None:
    """Verify governor behaves safely without crashing when memory measurement is UNKNOWN (None)."""
    with patch("codegraph.resources.governor.get_process_memory_mb", return_value=None):
        gov = ResourceGovernor()

        # State records None for estimated_memory_mb
        state = gov.get_state()
        assert state.estimated_memory_mb is None

        # Dict representation contains None (serializes to JSON null)
        d = state.as_dict()
        assert d["estimated_memory_mb"] is None

        # Pressure is NORMAL when there is no concurrency pressure
        assert gov.get_pressure() == PressureLevel.NORMAL

        # Concurrency pressure continues to be accurately computed
        # For BALANCED profile: max_interactive_workers = 2
        # active > 2 -> HIGH, active >= 4 -> CRITICAL, active > 0 -> ELEVATED
        with gov._lock:
            gov._active_interactive = 1
        assert gov.get_pressure() == PressureLevel.ELEVATED

        with gov._lock:
            gov._active_interactive = 3
        assert gov.get_pressure() == PressureLevel.HIGH

        with gov._lock:
            gov._active_interactive = 4
        assert gov.get_pressure() == PressureLevel.CRITICAL

        # Reset active interactive
        with gov._lock:
            gov._active_interactive = 0

        # Throttling decision functions normally without memory data
        assert gov.should_throttle(TaskPriority.INTERACTIVE_HIGH) is False
        assert gov.should_throttle(TaskPriority.BACKGROUND) is False


def test_cli_startup_on_windows(tmp_path: Path) -> None:
    """Verify that CLI commands start and execute successfully in a simulated Windows environment."""
    runner = CliRunner()

    with patch.dict(sys.modules, {"resource": None}):
        with patch("sys.platform", "win32"):
            # 1. Version command
            res_ver = runner.invoke(app, ["--version"])
            assert res_ver.exit_code == 0
            assert "2.1.3" in res_ver.stdout

            # 2. Help command
            res_help = runner.invoke(app, ["--help"], prog_name="codegraph")
            assert res_help.exit_code == 0
            assert "Usage: codegraph" in res_help.stdout

            # 3. Init command
            res_init = runner.invoke(app, ["init", str(tmp_path)])
            assert res_init.exit_code == 0

            # 4. Index command
            res_index = runner.invoke(app, ["index", str(tmp_path)])
            assert res_index.exit_code == 0

            # 5. Doctor command
            res_doc = runner.invoke(app, ["doctor", str(tmp_path)])
            assert res_doc.exit_code == 0
            assert "resources" in res_doc.stdout

            # 6. Status command
            res_status = runner.invoke(app, ["status", str(tmp_path)])
            assert res_status.exit_code == 0
            assert "resource_profile" in res_status.stdout


def test_existing_resource_governor_behavior_on_current_platform() -> None:
    """Verify existing governor behavior on macOS/Linux remains preserved."""
    gov = ResourceGovernor(ResourcePolicy.for_profile(ResourceProfile.BALANCED))
    assert gov.get_activity_mode() == ActivityMode.IDLE
    assert gov.is_active_coding() is False

    with gov.task_scope(TaskPriority.INTERACTIVE_HIGH):
        assert gov.is_active_coding() is True
        state = gov.get_state()
        assert state.active_interactive_requests == 1
        if sys.platform in ("darwin", "linux"):
            assert state.estimated_memory_mb is not None
            assert state.estimated_memory_mb > 0.0

    after_state = gov.get_state()
    assert after_state.active_interactive_requests == 0
    assert after_state.activity_mode == ActivityMode.ACTIVE_CODING.value
