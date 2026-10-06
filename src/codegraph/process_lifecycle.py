"""Cross-Platform MCP Process Lifecycle, Ownership Verification, and Safe Shutdown (`src/codegraph/process_lifecycle.py`).

Solves:
- Phase 2: Root-cause instrumentation for `codegraph mcp serve` (PID, parent PID, creation tokens, stdio state, platform).
- Phase 3: Deterministic MCP stdio shutdown (stdin EOF / transport disconnect, worker stop, SQLite close, child cleanup).
- Phase 4: Cross-platform parent/child ownership detection (POSIX reparent/zombie detection + Windows Win32 handle/creation-time verification).
- Phase 5: Safe `codegraph stop` command with strict ownership verification (never kills unrelated Python or reused-PID processes).
- Phase 6: Upgrade lock detection & safe cleanup during `codegraph install` and `codegraph uninstall`.
- Phase 7: Atomic process metadata (`~/.codegraph/processes/pid_<pid>.json`) and automatic stale/crash recovery.
- Phase 9: `codegraph doctor --processes` observability without exposing secrets or environment credentials.
"""
from __future__ import annotations

import atexit
import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.cli_output import get_cli_symbols

OWNERSHIP_MARKER = "CODEGRAPH_OWNED_PROCESS_V1"
PROCESS_SCHEMA_VERSION = "1.0"


class OwnershipState(StrEnum):
    """Canonical ownership verification states for tracked PIDs."""

    VERIFIED_CODEGRAPH_OWNED = "VERIFIED_CODEGRAPH_OWNED"
    DEAD_PROCESS = "DEAD_PROCESS"
    PID_REUSED_UNRELATED = "PID_REUSED_UNRELATED"
    INVALID_MARKER = "INVALID_MARKER"


@dataclass(frozen=True)
class LiveProcessInfo:
    """OS-level live process inspection snapshot."""

    pid: int
    ppid: int
    create_token: str
    executable: str
    command_summary: str
    is_zombie: bool = False


@dataclass(frozen=True)
class ProcessRecord:
    """Atomic metadata persisted for a running CodeGraph process."""

    schema_version: str
    ownership_marker: str
    session_id: str
    pid: int
    parent_pid: int
    process_create_token: str
    parent_create_token: str
    executable: str
    argv_signature: tuple[str, ...]
    repository: str
    mode: str
    profile: str
    platform: str
    started_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ownership_marker": self.ownership_marker,
            "session_id": self.session_id,
            "pid": self.pid,
            "parent_pid": self.parent_pid,
            "process_create_token": self.process_create_token,
            "parent_create_token": self.parent_create_token,
            "executable": self.executable,
            "argv_signature": list(self.argv_signature),
            "repository": self.repository,
            "mode": self.mode,
            "profile": self.profile,
            "platform": self.platform,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessRecord:
        raw_argv = data.get("argv_signature", ["codegraph", "mcp", "serve"])
        argv_tup = (
            tuple(str(x) for x in raw_argv)
            if isinstance(raw_argv, list)
            else ("codegraph", "mcp", "serve")
        )
        return cls(
            schema_version=str(data.get("schema_version", PROCESS_SCHEMA_VERSION)),
            ownership_marker=str(data.get("ownership_marker", "")),
            session_id=str(data.get("session_id", "")),
            pid=int(data.get("pid", -1)),
            parent_pid=int(data.get("parent_pid", -1)),
            process_create_token=str(data.get("process_create_token", "")),
            parent_create_token=str(data.get("parent_create_token", "")),
            executable=str(data.get("executable", "")),
            argv_signature=argv_tup,
            repository=str(data.get("repository", "")),
            mode=str(data.get("mode", "mcp_stdio")),
            profile=str(data.get("profile", "full")),
            platform=str(data.get("platform", sys.platform)),
            started_at=str(data.get("started_at", "")),
        )


@dataclass(frozen=True)
class ActiveProcessStatus:
    """Verified status of an active CodeGraph process."""

    record: ProcessRecord
    ownership_state: OwnershipState
    parent_alive: bool
    orphaned: bool
    safe_to_stop: bool
    metadata_file: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.record.pid,
            "parent_pid": self.record.parent_pid,
            "repository": self.record.repository,
            "mode": self.record.mode,
            "profile": self.record.profile,
            "platform": self.record.platform,
            "started_at": self.record.started_at,
            "argv_signature": list(self.record.argv_signature),
            "ownership_state": self.ownership_state.value,
            "parent_alive": self.parent_alive,
            "orphaned": self.orphaned,
            "safe_to_stop": self.safe_to_stop,
        }


@dataclass(frozen=True)
class ProcessDiscoveryResult:
    """Result of scanning the CodeGraph process registry."""

    active_processes: tuple[ActiveProcessStatus, ...]
    stale_cleaned_pids: tuple[int, ...] = ()
    reused_skipped_pids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_count": len(self.active_processes),
            "orphaned_count": sum(1 for p in self.active_processes if p.orphaned),
            "stale_cleaned_count": len(self.stale_cleaned_pids),
            "reused_skipped_count": len(self.reused_skipped_pids),
            "processes": [p.as_dict() for p in self.active_processes],
        }

    def format_human(self, *, unicode_override: bool | None = None) -> str:
        sym = get_cli_symbols(unicode_override=unicode_override)
        lines: list[str] = ["CodeGraph Process Diagnostics", ""]
        if not self.active_processes:
            lines.append(f"{sym.ok} No active CodeGraph background processes found.")
            if self.stale_cleaned_pids:
                lines.append(
                    f"  Cleaned {len(self.stale_cleaned_pids)} stale process metadata file(s)."
                )
            return "\n".join(lines)

        lines.append(
            f"{'PID':<8} {'Parent':<8} {'Mode':<11} {'Orphaned':<10} {'Safe Stop':<10} Repo"
        )
        for p in self.active_processes:
            orph = "yes" if p.orphaned else "no"
            safe = "yes" if p.safe_to_stop else "no"
            lines.append(
                f"{p.record.pid:<8} {p.record.parent_pid:<8} {p.record.mode:<11} "
                f"{orph:<10} {safe:<10} {p.record.repository}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class StoppedProcessItem:
    """Single process stop outcome."""

    pid: int
    parent_pid: int
    repository: str
    stopped: bool
    forced: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "parent_pid": self.parent_pid,
            "repository": self.repository,
            "stopped": self.stopped,
            "forced": self.forced,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StopProcessesReport:
    """Structured report for `codegraph stop`."""

    status: str  # "ok" | "partial"
    stopped_processes: tuple[StoppedProcessItem, ...]
    stale_cleaned_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stopped_count": sum(1 for p in self.stopped_processes if p.stopped),
            "stale_cleaned_count": self.stale_cleaned_count,
            "processes": [p.as_dict() for p in self.stopped_processes],
        }

    def format_human(self, *, unicode_override: bool | None = None) -> str:
        sym = get_cli_symbols(unicode_override=unicode_override)
        if not self.stopped_processes:
            msg = f"{sym.ok} No running CodeGraph processes found."
            if self.stale_cleaned_count > 0:
                msg += f" (Cleaned {self.stale_cleaned_count} stale metadata file(s).)"
            return msg

        lines: list[str] = [
            "CodeGraph processes",
            f"{'PID':<8}{'Parent':<10}Repo",
        ]
        for item in self.stopped_processes:
            lines.append(f"{item.pid:<8}{item.parent_pid:<10}{item.repository}")
        lines.append("")
        for item in self.stopped_processes:
            lines.append(f"Stopping PID {item.pid}...")
            if item.stopped:
                lines.append(f"{sym.ok} {item.detail}")
            else:
                lines.append(f"{sym.error} {item.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process Directory Resolution
# ---------------------------------------------------------------------------


def get_process_registry_dir(custom_dir: Path | None = None) -> Path:
    """Return the directory where active CodeGraph process metadata files are stored."""
    if custom_dir is not None:
        return custom_dir.resolve()
    env_dir = os.environ.get("CODEGRAPH_PROCESS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    home_dir = (Path.home() / ".codegraph" / "processes").resolve()
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        if os.access(home_dir, os.W_OK):
            return home_dir
    except OSError:
        pass
    return (Path(tempfile.gettempdir()) / "codegraph-processes").resolve()


def _metadata_file_for_pid(pid: int, process_dir: Path | None = None) -> Path:
    reg_dir = get_process_registry_dir(process_dir)
    return reg_dir / f"pid_{pid}.json"


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.replace(str(tmp_path), str(target))
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()


# ---------------------------------------------------------------------------
# Cross-Platform OS Process Inspection (Windows + POSIX)
# ---------------------------------------------------------------------------


def _win32_inspect_process(pid: int) -> LiveProcessInfo | None:
    """Inspect a Windows process using Win32 kernel32 APIs without external dependencies."""
    if sys.platform != "win32" or pid <= 0:
        return None
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        kernel32 = windll.kernel32
        # SYNCHRONIZE (0x00100000) | PROCESS_QUERY_LIMITED_INFORMATION (0x00001000)
        access = 0x00100000 | 0x00001000
        handle = kernel32.OpenProcess(access, False, int(pid))
        if not handle:
            return None
        try:
            exit_code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            # STILL_ACTIVE == 259; also check WaitForSingleObject(handle, 0) == WAIT_TIMEOUT (0x102)
            wait_res = kernel32.WaitForSingleObject(handle, 0)
            if exit_code.value != 259 or wait_res == 0:
                return None

            # Creation time via GetProcessTimes
            creation_time = ctypes.c_ulonglong(0)
            exit_time = ctypes.c_ulonglong(0)
            kernel_time = ctypes.c_ulonglong(0)
            user_time = ctypes.c_ulonglong(0)
            create_token = ""
            if kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                create_token = str(creation_time.value)

            # Executable path via QueryFullProcessImageNameW
            buf_len = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(1024)
            exe_name = ""
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
                exe_name = Path(buf.value).name.lower()

            return LiveProcessInfo(
                pid=pid,
                ppid=0,
                create_token=create_token,
                executable=exe_name,
                command_summary=exe_name,
                is_zombie=False,
            )
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


class _DarwinProcBsdInfo(ctypes.Structure):
    """macOS `<sys/proc_info.h>` `struct proc_bsdinfo` (136 bytes)."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _darwin_inspect_process(pid: int) -> LiveProcessInfo | None:
    """Inspect a macOS process directly via `libSystem.B.dylib` `proc_pidinfo` without spawning `ps`."""
    if sys.platform != "darwin" or pid <= 0:
        return None
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        info = _DarwinProcBsdInfo()
        # PROC_PIDTBSDINFO == 3, SZOMB == 5
        expected_size = ctypes.sizeof(info)
        res = int(libc.proc_pidinfo(int(pid), 3, 0, ctypes.byref(info), expected_size))
        if res != expected_size:
            return None
        zombie = int(info.pbi_status) == 5
        raw_name = bytes(info.pbi_name).split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        raw_comm = bytes(info.pbi_comm).split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        exe_name = (raw_name or raw_comm or "python").lower()
        create_tok = f"{int(info.pbi_start_tvsec)}:{int(info.pbi_start_tvusec)}"
        return LiveProcessInfo(
            pid=pid,
            ppid=int(info.pbi_ppid),
            create_token=create_tok,
            executable=exe_name,
            command_summary=exe_name,
            is_zombie=zombie,
        )
    except Exception:
        return None


def _posix_inspect_process(pid: int) -> LiveProcessInfo | None:
    """Inspect a POSIX (Linux / macOS) process via `/proc`, `proc_pidinfo`, or `ps`."""
    if sys.platform == "win32" or pid <= 0:
        return None

    # Check if PID exists at all
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    except OSError:
        return None

    # 1. Fast path on macOS: native kernel `proc_pidinfo` (zero subprocesses, sandbox-safe)
    if sys.platform == "darwin":
        darwin_info = _darwin_inspect_process(pid)
        if darwin_info is None or darwin_info.is_zombie:
            return None
        return darwin_info

    # 2. Fast path on Linux: /proc/<pid>/stat
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            raw = proc_stat.read_text(encoding="utf-8", errors="replace")
            rparen = raw.rfind(")")
            lparen = raw.find("(")
            if lparen != -1 and rparen != -1:
                comm = raw[lparen + 1 : rparen]
                fields_after = raw[rparen + 2 :].split()
                state = fields_after[0] if len(fields_after) > 0 else ""
                ppid = int(fields_after[1]) if len(fields_after) > 1 else 0
                starttime = fields_after[19] if len(fields_after) > 19 else ""
                is_zombie = state.upper().startswith("Z")
                if is_zombie:
                    return None
                cmdline_path = Path(f"/proc/{pid}/cmdline")
                cmd_summary = comm
                if cmdline_path.exists():
                    raw_cmd = cmdline_path.read_bytes().replace(b"\x00", b" ").decode(
                        "utf-8", errors="replace"
                    ).strip()
                    if raw_cmd:
                        cmd_summary = raw_cmd[:200]
                return LiveProcessInfo(
                    pid=pid,
                    ppid=ppid,
                    create_token=starttime,
                    executable=comm.lower(),
                    command_summary=cmd_summary.lower(),
                    is_zombie=False,
                )
        except Exception:
            pass

    # 3. Fallback on BSD / other POSIX: `ps -p <pid> -o ppid=,stat=,lstart=,comm=`
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid=,stat=,lstart=,comm="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            line = res.stdout.strip().splitlines()[0].strip()
            parts = line.split()
            if len(parts) >= 8:
                ppid = int(parts[0])
                stat_str = parts[1]
                if stat_str.upper().startswith("Z"):
                    return None
                lstart = " ".join(parts[2:7])
                comm_str = " ".join(parts[7:])
                exe_name = Path(comm_str).name.lower()
                return LiveProcessInfo(
                    pid=pid,
                    ppid=ppid,
                    create_token=lstart,
                    executable=exe_name,
                    command_summary=comm_str.lower(),
                    is_zombie=False,
                )
    except Exception:
        pass

    # `os.kill(pid, 0)` succeeded above, so the process is alive even if `ps` was restricted
    return LiveProcessInfo(
        pid=pid,
        ppid=0,
        create_token="",
        executable="",
        command_summary="",
        is_zombie=False,
    )


def get_live_process_info(pid: int) -> LiveProcessInfo | None:
    """Return live OS process information for `pid`, or `None` if dead/zombie."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _win32_inspect_process(pid)
    return _posix_inspect_process(pid)


def is_pid_alive(pid: int) -> bool:
    """Return True if `pid` is currently alive and not a zombie process."""
    return get_live_process_info(pid) is not None


def is_parent_alive(
    parent_pid: int,
    parent_create_token: str = "",
    *,
    current_ppid: int | None = None,
) -> bool:
    """Return True if the parent process `parent_pid` is still alive and owns this child."""
    if parent_pid <= 1:
        # PID 0 and 1 represent init / systemd / launchd / container root; always considered alive
        return True

    # 1. Direct probe whether parent PID exists via os.kill(pid, 0)
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        # ESRCH: Process does not exist; parent is definitely dead
        return False
    except PermissionError:
        # EPERM: Process exists, but caller lacks permissions to signal it (e.g. sandbox/different user)
        return True
    except OSError:
        # Other OS error: safe fallback is alive
        return True

    live = get_live_process_info(parent_pid)
    if live is None:
        # If OS inspection was restricted (e.g. sandbox blocking proc_pidinfo),
        # but os.kill succeeded above, the process is alive.
        return True
    if live.is_zombie:
        return False

    if parent_create_token and live.create_token and live.create_token != parent_create_token:
        # Parent PID was recycled by the OS for a newer process
        return False

    return True


def verify_codegraph_ownership(
    record: ProcessRecord,
    *,
    live_info: LiveProcessInfo | None = None,
) -> OwnershipState:
    """Verify that `record` corresponds to a live CodeGraph-owned process and not a reused PID."""
    if record.ownership_marker != OWNERSHIP_MARKER or record.pid <= 0:
        return OwnershipState.INVALID_MARKER

    info = live_info if live_info is not None else get_live_process_info(record.pid)
    if info is None or info.is_zombie:
        return OwnershipState.DEAD_PROCESS

    # 1. Creation timestamp/token check protects against PID reuse after a crash
    if (
        record.process_create_token
        and info.create_token
        and record.process_create_token != info.create_token
    ):
        return OwnershipState.PID_REUSED_UNRELATED

    # 2. Executable / command signature check
    if info.executable:
        rec_exe = Path(record.executable).name.lower() if record.executable else ""
        live_exe = Path(info.executable).name.lower()
        allowed_tokens = ("python", "py", "codegraph", "pytest", "uv")
        matches_known = any(
            tok in live_exe or tok in info.command_summary for tok in allowed_tokens
        )
        matches_recorded = bool(rec_exe and (rec_exe in live_exe or live_exe in rec_exe))
        if not matches_known and not matches_recorded:
            return OwnershipState.PID_REUSED_UNRELATED

    return OwnershipState.VERIFIED_CODEGRAPH_OWNED


# ---------------------------------------------------------------------------
# Process Registration, Discovery & Safe Termination
# ---------------------------------------------------------------------------


def build_current_process_record(
    repository: Path,
    mode: str = "mcp_stdio",
    profile: str = "full",
    argv_signature: tuple[str, ...] = ("codegraph", "mcp", "serve"),
) -> ProcessRecord:
    """Capture current process and parent process ownership metadata."""
    pid = os.getpid()
    ppid = os.getppid()
    self_info = get_live_process_info(pid)
    parent_info = get_live_process_info(ppid) if ppid > 1 else None

    return ProcessRecord(
        schema_version=PROCESS_SCHEMA_VERSION,
        ownership_marker=OWNERSHIP_MARKER,
        session_id=uuid.uuid4().hex,
        pid=pid,
        parent_pid=ppid,
        process_create_token=self_info.create_token if self_info else "",
        parent_create_token=parent_info.create_token if parent_info else "",
        executable=Path(sys.executable).name if sys.executable else "python",
        argv_signature=argv_signature,
        repository=str(repository.resolve()),
        mode=mode,
        profile=profile,
        platform=sys.platform,
        started_at=datetime.now(UTC).isoformat(),
    )


def register_process_record(
    record: ProcessRecord,
    process_dir: Path | None = None,
) -> Path:
    """Persist `record` atomically to `~/.codegraph/processes/pid_<pid>.json`."""
    meta_file = _metadata_file_for_pid(record.pid, process_dir)
    _atomic_write_json(meta_file, record.as_dict())
    return meta_file


def unregister_process_record(
    pid: int,
    session_id: str | None = None,
    process_dir: Path | None = None,
) -> None:
    """Remove `pid_<pid>.json` if it belongs to `pid` (and `session_id` if specified)."""
    meta_file = _metadata_file_for_pid(pid, process_dir)
    if not meta_file.exists():
        return
    try:
        if session_id is not None:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
            if raw.get("session_id") != session_id:
                return
        meta_file.unlink(missing_ok=True)
    except OSError:
        pass


def discover_codegraph_processes(
    process_dir: Path | None = None,
    *,
    clean_stale: bool = True,
) -> ProcessDiscoveryResult:
    """Scan `process_dir` for tracked CodeGraph processes, cleaning up stale/reused PID files."""
    reg_dir = get_process_registry_dir(process_dir)
    if not reg_dir.exists():
        return ProcessDiscoveryResult(active_processes=())

    active: list[ActiveProcessStatus] = []
    stale_pids: list[int] = []
    reused_pids: list[int] = []

    for meta_file in sorted(reg_dir.glob("pid_*.json")):
        try:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                if clean_stale:
                    meta_file.unlink(missing_ok=True)
                continue
            record = ProcessRecord.from_dict(raw)
        except Exception:
            if clean_stale:
                with contextlib.suppress(OSError):
                    meta_file.unlink(missing_ok=True)
            continue

        verdict = verify_codegraph_ownership(record)
        if verdict == OwnershipState.DEAD_PROCESS:
            stale_pids.append(record.pid)
            if clean_stale:
                with contextlib.suppress(OSError):
                    meta_file.unlink(missing_ok=True)
            continue

        if verdict in (OwnershipState.PID_REUSED_UNRELATED, OwnershipState.INVALID_MARKER):
            reused_pids.append(record.pid)
            if clean_stale:
                with contextlib.suppress(OSError):
                    meta_file.unlink(missing_ok=True)
            continue

        live_self = get_live_process_info(record.pid)
        observed_ppid = (
            live_self.ppid
            if (live_self is not None and live_self.ppid > 0)
            else record.parent_pid
        )
        parent_ok = is_parent_alive(
            record.parent_pid,
            record.parent_create_token,
            current_ppid=observed_ppid,
        )
        active.append(
            ActiveProcessStatus(
                record=record,
                ownership_state=verdict,
                parent_alive=parent_ok,
                orphaned=not parent_ok,
                safe_to_stop=(verdict == OwnershipState.VERIFIED_CODEGRAPH_OWNED),
                metadata_file=meta_file,
            )
        )

    return ProcessDiscoveryResult(
        active_processes=tuple(active),
        stale_cleaned_pids=tuple(stale_pids),
        reused_skipped_pids=tuple(reused_pids),
    )


def _terminate_verified_pid(pid: int, force: bool = False) -> bool:
    """Send graceful or forced termination to a verified CodeGraph-owned PID."""
    if pid <= 0 or pid == os.getpid():
        return False

    if sys.platform == "win32":
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                kernel32 = windll.kernel32
                # PROCESS_TERMINATE == 0x0001
                handle = kernel32.OpenProcess(0x0001, False, int(pid))
                if not handle:
                    return not is_pid_alive(pid)
                try:
                    ok = bool(kernel32.TerminateProcess(handle, 0))
                    return ok or not is_pid_alive(pid)
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        return not is_pid_alive(pid)

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return not is_pid_alive(pid)


def stop_codegraph_processes(
    *,
    repository: Path | None = None,
    stop_all: bool = False,
    only_orphaned: bool = False,
    timeout_sec: float = 3.0,
    process_dir: Path | None = None,
) -> StopProcessesReport:
    """Safely stop verified CodeGraph-owned background processes.

    Guarantees:
    - Never touches processes that fail `verify_codegraph_ownership`.
    - When `repository` is specified and `stop_all=False`, only stops processes for `repository`.
    - Requests graceful shutdown first (`SIGTERM`), escalating to `SIGKILL` only after `timeout_sec`.
    """
    discovery = discover_codegraph_processes(process_dir=process_dir, clean_stale=True)
    target_repo = str(repository.resolve()) if repository is not None else None
    current_pid = os.getpid()

    candidates: list[ActiveProcessStatus] = []
    for proc_status in discovery.active_processes:
        if proc_status.record.pid == current_pid:
            continue
        if not proc_status.safe_to_stop:
            continue
        if only_orphaned and not proc_status.orphaned:
            continue
        if (
            not stop_all
            and target_repo is not None
            and proc_status.record.repository != target_repo
        ):
            continue
        candidates.append(proc_status)

    outcomes: list[StoppedProcessItem] = []
    for cand in candidates:
        pid = cand.record.pid
        # Re-verify ownership right before sending any signal
        recheck = verify_codegraph_ownership(cand.record)
        if recheck == OwnershipState.DEAD_PROCESS:
            unregister_process_record(pid, cand.record.session_id, process_dir=process_dir)
            outcomes.append(
                StoppedProcessItem(
                    pid=pid,
                    parent_pid=cand.record.parent_pid,
                    repository=cand.record.repository,
                    stopped=True,
                    forced=False,
                    detail="Process already exited.",
                )
            )
            continue

        if recheck != OwnershipState.VERIFIED_CODEGRAPH_OWNED:
            unregister_process_record(pid, cand.record.session_id, process_dir=process_dir)
            outcomes.append(
                StoppedProcessItem(
                    pid=pid,
                    parent_pid=cand.record.parent_pid,
                    repository=cand.record.repository,
                    stopped=False,
                    forced=False,
                    detail="Skipped: PID ownership changed.",
                )
            )
            continue

        _terminate_verified_pid(pid, force=False)
        deadline = time.monotonic() + max(timeout_sec, 0.1)
        while time.monotonic() < deadline:
            if not is_pid_alive(pid):
                break
            time.sleep(0.05)

        forced = False
        if is_pid_alive(pid):
            # Escalate after bounded timeout, re-verifying ownership first
            if verify_codegraph_ownership(cand.record) == OwnershipState.VERIFIED_CODEGRAPH_OWNED:
                forced = True
                _terminate_verified_pid(pid, force=True)
                force_deadline = time.monotonic() + 1.0
                while time.monotonic() < force_deadline:
                    if not is_pid_alive(pid):
                        break
                    time.sleep(0.05)

        exited = not is_pid_alive(pid)
        if exited:
            unregister_process_record(pid, cand.record.session_id, process_dir=process_dir)
            detail = (
                "Process exited cleanly."
                if not forced
                else "Process force-terminated after timeout."
            )
        else:
            detail = "Process did not exit within timeout."

        outcomes.append(
            StoppedProcessItem(
                pid=pid,
                parent_pid=cand.record.parent_pid,
                repository=cand.record.repository,
                stopped=exited,
                forced=forced,
                detail=detail,
            )
        )

    all_ok = all(o.stopped for o in outcomes)
    return StopProcessesReport(
        status="ok" if all_ok else "partial",
        stopped_processes=tuple(outcomes),
        stale_cleaned_count=len(discovery.stale_cleaned_pids),
    )


# ---------------------------------------------------------------------------
# MCP Stdio Lifecycle & Shutdown Controller
# ---------------------------------------------------------------------------


def _is_stream_closed_or_eof(stream: Any) -> bool:
    """Return True if `stream` is closed or its underlying file descriptor is invalid."""
    if stream is None:
        return True
    if getattr(stream, "closed", False):
        return True
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    if fd < 0:
        return True
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


@dataclass
class MCPLifecycleController:
    """Manages deterministic startup, parent/transport monitoring, and teardown for `codegraph mcp serve`."""

    repository: Path
    profile: str = "full"
    mode: str = "mcp_stdio"
    process_dir: Path | None = None
    poll_interval_sec: float = 0.25
    force_exit_on_async_stop: bool = False
    record: ProcessRecord = field(init=False)
    metadata_path: Path | None = field(default=None, init=False)
    shutdown_reason: str | None = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _shutdown_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _shutdown_completed: bool = field(default=False, init=False)
    _close_callbacks: list[Callable[[], None]] = field(default_factory=list, init=False)
    _child_processes: list[subprocess.Popen[Any]] = field(default_factory=list, init=False)
    _watchdog_thread: threading.Thread | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        env_poll = os.environ.get("CODEGRAPH_PARENT_POLL_SEC", "").strip()
        if env_poll:
            with contextlib.suppress(ValueError):
                self.poll_interval_sec = max(float(env_poll), 0.05)
        self.record = build_current_process_record(
            repository=self.repository,
            mode=self.mode,
            profile=self.profile,
        )

    def add_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Register a resource cleanup callback invoked during shutdown."""
        self._close_callbacks.append(callback)

    def register_child_process(self, proc: subprocess.Popen[Any]) -> None:
        """Track a child subprocess so it is terminated when the MCP server shuts down."""
        self._child_processes.append(proc)

    def start(self) -> None:
        """Clean stale registry files, write current process record, and start parent/transport watchdog."""
        discover_codegraph_processes(process_dir=self.process_dir, clean_stale=True)
        self.metadata_path = register_process_record(self.record, process_dir=self.process_dir)
        atexit.register(self._atexit_cleanup)

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="codegraph-mcp-lifecycle-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """Low-overhead event-backed watchdog detecting parent termination or closed stdin."""
        disable_parent_watchdog = (
            os.environ.get("CODEGRAPH_DISABLE_PARENT_WATCHDOG", "").strip().lower()
            in ("1", "true", "yes")
            or self.record.parent_pid <= 1
        )
        while not self._stop_event.wait(timeout=self.poll_interval_sec):
            if _is_stream_closed_or_eof(sys.stdin):
                self.shutdown("stdin_closed")
                return
            if not disable_parent_watchdog:
                if not is_parent_alive(
                    self.record.parent_pid,
                    self.record.parent_create_token,
                ):
                    self.shutdown("parent_process_terminated")
                    return

    def _atexit_cleanup(self) -> None:
        self.shutdown("atexit")

    def shutdown(self, reason: str = "normal_exit") -> None:
        """Idempotently stop workers, close resources, terminate child processes, and remove PID metadata."""
        with self._shutdown_lock:
            if self._shutdown_completed:
                return
            self._shutdown_completed = True
            self.shutdown_reason = reason
            self._stop_event.set()

            # 1. Execute all registered resource/SQLite/governor cleanup callbacks
            for cb in reversed(self._close_callbacks):
                with contextlib.suppress(Exception):
                    cb()

            # 2. Terminate any child subprocesses spawned by CodeGraph
            for child in self._child_processes:
                with contextlib.suppress(Exception):
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            child.kill()

            # 3. Remove process metadata file
            unregister_process_record(
                self.record.pid,
                session_id=self.record.session_id,
                process_dir=self.process_dir,
            )

            # 4. Flush standard output/error streams safely
            with contextlib.suppress(Exception):
                sys.stdout.flush()
            with contextlib.suppress(Exception):
                sys.stderr.flush()

            # 5. If running stdio MCP and parent died or a termination signal arrived while
            # `anyio.wrap_file(sys.stdin)` has a worker thread blocked in C-level `readline()`,
            # ensure the process exits cleanly after all cleanup above has completed.
            if self.force_exit_on_async_stop and (
                reason.startswith("parent_")
                or reason.startswith("stdin_")
                or reason.startswith("signal_")
            ):
                def _post_cleanup_exit() -> None:
                    time.sleep(0.10)
                    os._exit(0)

                exiter = threading.Thread(
                    target=_post_cleanup_exit,
                    name="codegraph-mcp-post-cleanup-exit",
                    daemon=True,
                )
                exiter.start()


def run_mcp_stdio_server(
    server: Any,
    repository: Path,
    *,
    profile: str = "full",
    process_dir: Path | None = None,
    poll_interval_sec: float = 0.25,
) -> int:
    """Run `server` in stdio MCP mode with deterministic lifecycle, signal, and parent-exit handling."""
    import anyio

    controller = MCPLifecycleController(
        repository=repository,
        profile=profile,
        mode="mcp_stdio",
        process_dir=process_dir,
        poll_interval_sec=poll_interval_sec,
        force_exit_on_async_stop=True,
    )

    # Register cleanup for any attached indexer on the server
    indexer = getattr(server, "_codegraph_indexer", None)
    if indexer is not None:
        def _cleanup_indexer() -> None:
            gov = getattr(indexer, "governor", None)
            if gov is not None and hasattr(gov, "shutdown"):
                gov.shutdown()

        controller.add_cleanup_callback(_cleanup_indexer)

    prev_handlers: dict[int, Any] = {}
    handled_signals: list[int] = [signal.SIGINT, signal.SIGTERM]
    for opt_sig_name in ("SIGHUP", "SIGBREAK"):
        opt_sig = getattr(signal, opt_sig_name, None)
        if opt_sig is not None:
            handled_signals.append(opt_sig)

    def _on_signal(signum: int, _frame: Any) -> None:
        controller.shutdown(f"signal_{signum}")

    for sig in handled_signals:
        with contextlib.suppress(OSError, ValueError):
            prev_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _on_signal)

    controller.start()

    async def _run_with_lifecycle() -> None:
        async with anyio.create_task_group() as tg:
            async def _monitor_stop() -> None:
                while not controller._stop_event.is_set():
                    await anyio.sleep(min(controller.poll_interval_sec, 0.1))
                tg.cancel_scope.cancel()

            async def _serve_stdio() -> None:
                try:
                    await server.run_stdio_async()
                finally:
                    controller.shutdown("stdio_eof")
                    tg.cancel_scope.cancel()

            tg.start_soon(_monitor_stop)
            tg.start_soon(_serve_stdio)

    try:
        anyio.run(_run_with_lifecycle)
    except (KeyboardInterrupt, SystemExit):
        controller.shutdown("interrupted")
    except BaseException:
        controller.shutdown("exception")
        raise
    finally:
        controller.shutdown("normal_exit")
        for sig, prev in prev_handlers.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, prev)

    return 0
