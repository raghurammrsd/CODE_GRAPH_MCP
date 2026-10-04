"""Cross-platform tests for Windows CLI output encoding safety, MCP process lifecycle,
parent-death shutdown, `codegraph stop`, PID reuse protection, and dynamic index hot-reload.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.cli_output import (
    ASCII_SYMBOLS,
    UNICODE_SYMBOLS,
    cli_echo,
    detect_stream_encoding,
    get_cli_symbols,
    sanitize_text_for_stream,
    supports_unicode,
)
from codegraph.indexing import Indexer
from codegraph.installer import (
    DetectedAgent,
    InstallerReport,
    PlannedFileChange,
    run_install,
    run_uninstall,
)
from codegraph.mcp.server import create_server
from codegraph.mcp_diagnostics import MCPDoctorCheck, MCPDoctorReport
from codegraph.process_lifecycle import (
    OWNERSHIP_MARKER,
    PROCESS_SCHEMA_VERSION,
    OwnershipState,
    ProcessRecord,
    is_pid_alive,
    register_process_record,
    stop_codegraph_processes,
    verify_codegraph_ownership,
)

runner = CliRunner()


# ===========================================================================
# PHASE 1 — WINDOWS OUTPUT SAFETY TESTS (cp1252, UTF-8, redirected, --json)
# ===========================================================================


def _make_encoded_stream(encoding: str) -> tuple[io.TextIOWrapper, io.BytesIO]:
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding=encoding, errors="strict", line_buffering=True)
    return wrapper, raw


def test_cp1252_stdout_never_raises_unicode_encode_error() -> None:
    """Standard Windows cp1252 streams cannot encode ✓, ✗, ⚠, ↻, or •.
    Verify `cli_echo` and `sanitize_text_for_stream` degrade cleanly to ASCII.
    """
    stream, raw = _make_encoded_stream("cp1252")
    assert detect_stream_encoding(stream) in ("cp1252", "windows-1252")
    assert not supports_unicode(stream)

    syms = get_cli_symbols(stream)
    assert syms == ASCII_SYMBOLS
    assert syms.ok == "[OK]"
    assert syms.error == "[ERROR]"
    assert syms.warn == "[WARN]"
    assert syms.repair == "[REPAIRED]"
    assert syms.radio_on == "(*)"

    sample = "✓ Antigravity configured\n✗ Failed check\n⚠ Warning\n↻ Repaired\n(•) Local"
    cli_echo(sample, stream=stream)
    decoded = raw.getvalue().decode("cp1252")
    assert "[OK] Antigravity configured" in decoded
    assert "[ERROR] Failed check" in decoded
    assert "[WARN] Warning" in decoded
    assert "[REPAIRED] Repaired" in decoded
    assert "(*) Local" in decoded
    for forbidden in ("✓", "✗", "⚠", "↻", "•"):
        assert forbidden not in decoded


def test_utf8_stdout_preserves_rich_unicode_symbols() -> None:
    """Terminals supporting UTF-8 must preserve rich Unicode symbols."""
    stream, raw = _make_encoded_stream("utf-8")
    assert supports_unicode(stream, unicode_override=True)
    syms = get_cli_symbols(stream, unicode_override=True)
    assert syms == UNICODE_SYMBOLS
    assert syms.ok == "✓"
    assert syms.error == "✗"
    assert syms.warn == "⚠"

    sample = f"{syms.ok} Antigravity configured\n{syms.radio_on} Local project"
    cli_echo(sample, stream=stream, unicode_override=True)
    decoded = raw.getvalue().decode("utf-8")
    assert "✓ Antigravity configured" in decoded
    assert "(•) Local project" in decoded


def test_redirected_stream_without_encoding_degrades_to_ascii() -> None:
    """Redirected pipes or custom streams with `encoding=None` or `ascii` must never crash."""

    class PipeWithoutEncoding:
        encoding = None

        def __init__(self) -> None:
            self.buffer: list[str] = []

        def write(self, s: str) -> int:
            # Simulate strict ASCII pipe
            s.encode("ascii", errors="strict")
            self.buffer.append(s)
            return len(s)

        def flush(self) -> None:
            pass

    pipe = PipeWithoutEncoding()
    assert detect_stream_encoding(pipe) == "ascii"
    assert not supports_unicode(pipe)
    safe = sanitize_text_for_stream("✓ Checked → ✗ Error — ⚠ Warn", pipe)
    pipe.write(safe)
    combined = "".join(pipe.buffer)
    assert "[OK] Checked -> [ERROR] Error -- [WARN] Warn" in combined


def test_installer_and_mcp_doctor_reports_cp1252_vs_utf8() -> None:
    """Verify `InstallerReport` and `MCPDoctorReport` format cleanly in both cp1252 and UTF-8."""
    inst_rep = InstallerReport(
        status="ok",
        operation="install",
        location="local",
        workspace="/tmp/demo",
        detected_agents=(
            DetectedAgent(
                agent_id="antigravity",
                display_name="Antigravity",
                detected=True,
                detected_global=False,
                detected_local=True,
            ),
        ),
        selected_agents=("antigravity",),
        changes=(
            PlannedFileChange(
                path=Path("/tmp/demo/AGENTS.md"),
                display_path="./AGENTS.md",
                action="create",
                category="instructions",
                agent_id="antigravity",
                detail="Create AGENTS.md",
            ),
        ),
        warnings=("Active process warning",),
        files_changed=True,
    )

    ascii_preview = inst_rep.format_preview_human(unicode_override=False)
    ascii_human = inst_rep.format_human(unicode_override=False)
    assert "[OK] Antigravity" in ascii_preview
    assert "(*) Current project" in ascii_preview
    assert "[OK] CodeGraph installed" in ascii_human
    assert "[WARN] Warning: Active process warning" in ascii_human
    # Must encode strictly in cp1252 and ascii
    ascii_preview.encode("cp1252", errors="strict")
    ascii_human.encode("cp1252", errors="strict")
    ascii_preview.encode("ascii", errors="strict")
    ascii_human.encode("ascii", errors="strict")

    utf8_human = inst_rep.format_human(unicode_override=True)
    assert "✓ CodeGraph installed" in utf8_human
    assert "⚠ Warning: Active process warning" in utf8_human

    doc_rep = MCPDoctorReport(
        healthy=True,
        server_name="codegraph",
        profile="full",
        checks=(
            MCPDoctorCheck(
                name="server startup",
                passed=True,
                detail="MCP server startup succeeded",
            ),
        ),
        discovered_tools=("get_context",),
    )
    doc_ascii = doc_rep.format_human(unicode_override=False)
    doc_ascii.encode("cp1252", errors="strict")
    assert "[OK] server startup" in doc_ascii


def test_json_output_is_strictly_machine_readable_and_unicode_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--json` output must parse as valid JSON and contain zero decorative status glyphs."""
    monkeypatch.setenv("CODEGRAPH_ASCII_OUTPUT", "1")
    monkeypatch.setenv("CODEGRAPH_PROCESS_DIR", str(tmp_path / "procs"))

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def hello():\n    return 42\n", encoding="utf-8")

    res = runner.invoke(
        app,
        ["install", str(repo), "--target", "antigravity", "--dry-run", "--json"],
    )
    assert res.exit_code == 0, res.output
    parsed = json.loads(res.output)
    assert parsed["status"] == "dry_run"
    for glyph in ("✓", "✗", "⚠", "↻", "•"):
        assert glyph not in res.output

    # Also test sanitize_json_string on cp1252 stream
    cp_stream, raw = _make_encoded_stream("cp1252")
    raw_json = json.dumps({"status": "ok", "note": "safe"})
    cli_echo(raw_json, stream=cp_stream, json_mode=True)
    assert json.loads(raw.getvalue().decode("cp1252"))["status"] == "ok"


# ===========================================================================
# PHASES 2–7 — MCP PROCESS LIFECYCLE, PARENT DEATH, STOP & OWNERSHIP TESTS
# ===========================================================================

_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")


def _subprocess_env(proc_dir: Path, poll_sec: str = "0.2") -> dict[str, str]:
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{existing_pp}" if existing_pp else _SRC_DIR
    env["CODEGRAPH_PROCESS_DIR"] = str(proc_dir)
    env["CODEGRAPH_PARENT_POLL_SEC"] = poll_sec
    return env


def _wait_for_condition(predicate: Any, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def test_scenario_a_and_c_mcp_serve_exits_cleanly_on_stdin_eof_and_cleans_pid_file(
    tmp_path: Path,
) -> None:
    """Scenario A & C:
    - Launch `codegraph mcp serve` as a child process with piped stdin.
    - Verify it registers `pid_<pid>.json` in `CODEGRAPH_PROCESS_DIR`.
    - Close stdin (EOF).
    - Verify the child process exits cleanly with returncode 0 and removes `pid_<pid>.json`.
    """
    proc_dir = tmp_path / "processes"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def compute(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    env = _subprocess_env(proc_dir)

    proc = subprocess.Popen(
        [sys.executable, "-m", "codegraph.cli", "mcp", "serve", str(repo)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        pid_file = proc_dir / f"pid_{proc.pid}.json"
        assert _wait_for_condition(pid_file.exists, timeout=5.0), (
            f"PID file was not created for PID {proc.pid}"
        )

        # Verify metadata contents
        meta = json.loads(pid_file.read_text(encoding="utf-8"))
        assert meta["pid"] == proc.pid
        assert meta["parent_pid"] == os.getpid()
        assert meta["ownership_marker"] == OWNERSHIP_MARKER
        assert Path(meta["repository"]) == repo.resolve()

        # Close stdin to signal transport EOF
        assert proc.stdin is not None
        proc.stdin.close()

        exit_code = proc.wait(timeout=5.0)
        assert exit_code == 0
        assert not is_pid_alive(proc.pid)
        assert _wait_for_condition(lambda: not pid_file.exists(), timeout=2.0), (
            "PID metadata file should be removed on clean shutdown"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)


def test_scenario_b_parent_process_killed_abruptly_mcp_child_terminates_automatically(
    tmp_path: Path,
) -> None:
    """Scenario B:
    - Spawn a simulated parent agent process (e.g., Antigravity/Cursor bridge).
    - The parent spawns `codegraph mcp serve` and also spawns a sleeper that inherits the stdin write pipe
      (reproducing the exact Windows/POSIX bug where stdin never hits EOF when the parent crashes!).
    - Force-kill the parent agent process (`SIGKILL` / `kill()`).
    - Verify `codegraph mcp serve` detects parent death via `MCPLifecycleController` and terminates
      automatically without becoming an orphan!
    """
    proc_dir = tmp_path / "processes"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("X = 1\n", encoding="utf-8")
    child_pid_file = tmp_path / "mcp_child_pid.txt"
    holder_pid_file = tmp_path / "pipe_holder_pid.txt"

    parent_script = tmp_path / "fake_agent_parent.py"
    parent_script.write_text(
        f"""from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

env = os.environ.copy()
env["PYTHONPATH"] = {_SRC_DIR!r}
env["CODEGRAPH_PROCESS_DIR"] = {str(proc_dir)!r}
env["CODEGRAPH_PARENT_POLL_SEC"] = "0.2"

r_fd, w_fd = os.pipe()

# Spawn a grandchild that holds w_fd open so r_fd NEVER gets EOF when parent dies!
holder = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(30)"],
    pass_fds=(w_fd,) if sys.platform != "win32" else (),
    close_fds=False if sys.platform == "win32" else True,
)
Path({str(holder_pid_file)!r}).write_text(str(holder.pid), encoding="utf-8")

mcp_proc = subprocess.Popen(
    [sys.executable, "-m", "codegraph.cli", "mcp", "serve", {str(repo)!r}],
    stdin=r_fd,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=env,
)
os.close(r_fd)
Path({str(child_pid_file)!r}).write_text(str(mcp_proc.pid), encoding="utf-8")

# Stay alive until killed by test
while True:
    time.sleep(1.0)
""",
        encoding="utf-8",
    )

    parent_proc = subprocess.Popen(
        [sys.executable, str(parent_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_subprocess_env(proc_dir),
    )
    mcp_pid: int | None = None
    holder_pid: int | None = None
    try:
        assert _wait_for_condition(child_pid_file.exists, timeout=5.0)
        mcp_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
        if holder_pid_file.exists():
            holder_pid = int(holder_pid_file.read_text(encoding="utf-8").strip())

        pid_meta_path = proc_dir / f"pid_{mcp_pid}.json"
        assert _wait_for_condition(pid_meta_path.exists, timeout=5.0), (
            f"MCP child {mcp_pid} did not register its PID file"
        )
        assert is_pid_alive(mcp_pid)

        # Abruptly kill the parent agent process (simulating IDE crash / force close)
        parent_proc.kill()
        parent_proc.wait(timeout=5.0)

        # Even though the pipe holder still keeps the write end open, MCP child must detect
        # parent death and exit within ~2.5 seconds!
        exited = _wait_for_condition(lambda: not is_pid_alive(mcp_pid), timeout=4.0)
        assert exited, f"Orphaned MCP child process {mcp_pid} survived after parent {parent_proc.pid} died!"
    finally:
        if parent_proc.poll() is None:
            parent_proc.kill()
            parent_proc.wait(timeout=2.0)
        if holder_pid is not None and is_pid_alive(holder_pid):
            try:
                os.kill(holder_pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
            except OSError:
                pass
        if mcp_pid is not None and is_pid_alive(mcp_pid):
            try:
                os.kill(mcp_pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
            except OSError:
                pass


def test_scenario_d_stale_pid_cleanup_and_pid_reuse_safety(tmp_path: Path) -> None:
    """Scenario D:
    1. A stale `pid_999999.json` for a dead process is automatically cleaned up.
    2. A `pid_<live_pid>.json` whose `process_create_token` does NOT match the live OS process
       (simulating OS PID reuse after a crash) is classified as `PID_REUSED_UNRELATED`,
       is NEVER killed by `stop_codegraph_processes`, and its stale metadata file is removed.
    """
    proc_dir = tmp_path / "processes"
    proc_dir.mkdir(parents=True)

    # 1. Dead PID record
    dead_record = ProcessRecord(
        schema_version=PROCESS_SCHEMA_VERSION,
        ownership_marker=OWNERSHIP_MARKER,
        session_id="dead-session",
        pid=999_991,
        parent_pid=1,
        process_create_token="old-token",
        parent_create_token="old-parent-token",
        executable="python",
        argv_signature=("codegraph", "mcp", "serve"),
        repository=str(tmp_path),
        mode="mcp_stdio",
        profile="full",
        platform=sys.platform,
        started_at="2026-01-01T00:00:00+00:00",
    )
    dead_file = register_process_record(dead_record, process_dir=proc_dir)
    assert dead_file.exists()

    # 2. Spawn a real unrelated Python process and forge a stale PID file with its PID
    #    but a different creation token (simulating PID reuse by the OS).
    unrelated_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    try:
        reused_record = ProcessRecord(
            schema_version=PROCESS_SCHEMA_VERSION,
            ownership_marker=OWNERSHIP_MARKER,
            session_id="reused-session",
            pid=unrelated_proc.pid,
            parent_pid=os.getpid(),
            process_create_token="STALE_CREATION_TIMESTAMP_FROM_YESTERDAY",
            parent_create_token="",
            executable="python",
            argv_signature=("codegraph", "mcp", "serve"),
            repository=str(tmp_path),
            mode="mcp_stdio",
            profile="full",
            platform=sys.platform,
            started_at="2026-01-01T00:00:00+00:00",
        )
        reused_file = register_process_record(reused_record, process_dir=proc_dir)
        assert verify_codegraph_ownership(reused_record) == OwnershipState.PID_REUSED_UNRELATED

        # Run stop_codegraph_processes(stop_all=True) — must NOT kill unrelated_proc!
        report = stop_codegraph_processes(stop_all=True, process_dir=proc_dir)
        assert report.stale_cleaned_count == 1
        assert len(report.stopped_processes) == 0
        assert is_pid_alive(unrelated_proc.pid), "PID-reused process must NEVER be killed!"
        assert not dead_file.exists()
        assert not reused_file.exists()
    finally:
        unrelated_proc.kill()
        unrelated_proc.wait(timeout=2.0)


def test_scenario_e_multi_repo_isolation_and_stop_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario E:
    - Two active CodeGraph MCP processes for `repo_a` and `repo_b`.
    - `codegraph stop --repo repo_a` stops ONLY `repo_a` and leaves `repo_b` running.
    - `codegraph doctor --processes --json` shows `repo_b` still active.
    - `codegraph stop --all` stops `repo_b`.
    """
    proc_dir = tmp_path / "processes"
    monkeypatch.setenv("CODEGRAPH_PROCESS_DIR", str(proc_dir))

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("A = 1\n", encoding="utf-8")
    (repo_b / "b.py").write_text("B = 2\n", encoding="utf-8")

    env = _subprocess_env(proc_dir)

    proc_a = subprocess.Popen(
        [sys.executable, "-m", "codegraph.cli", "mcp", "serve", str(repo_a)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    proc_b = subprocess.Popen(
        [sys.executable, "-m", "codegraph.cli", "mcp", "serve", str(repo_b)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert _wait_for_condition(lambda: (proc_dir / f"pid_{proc_a.pid}.json").exists(), timeout=5.0)
        assert _wait_for_condition(lambda: (proc_dir / f"pid_{proc_b.pid}.json").exists(), timeout=5.0)

        # Inspect via `codegraph doctor --processes --json`
        doc_res = runner.invoke(app, ["doctor", "--processes", "--json"])
        assert doc_res.exit_code == 0, doc_res.output
        doc_payload = json.loads(doc_res.output)
        assert doc_payload["active_count"] == 2

        # Stop ONLY repo_a
        stop_a_res = runner.invoke(app, ["stop", "--repo", str(repo_a), "--json"])
        assert stop_a_res.exit_code == 0, stop_a_res.output
        stop_a_payload = json.loads(stop_a_res.output)
        assert stop_a_payload["stopped_count"] == 1
        assert stop_a_payload["processes"][0]["pid"] == proc_a.pid

        assert not is_pid_alive(proc_a.pid)
        assert is_pid_alive(proc_b.pid), "repo_b MCP server must remain alive when stopping repo_a"

        # Stop remaining with `codegraph stop --all`
        stop_all_res = runner.invoke(app, ["stop", "--all", "--json"])
        assert stop_all_res.exit_code == 0, stop_all_res.output
        stop_all_payload = json.loads(stop_all_res.output)
        assert stop_all_payload["stopped_count"] == 1
        assert stop_all_payload["processes"][0]["pid"] == proc_b.pid
        assert not is_pid_alive(proc_b.pid)
    finally:
        for p in (proc_a, proc_b):
            if p.poll() is None:
                p.kill()
                p.wait(timeout=2.0)


def test_scenario_f_uninstall_stops_running_mcp_process_and_install_warns_on_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario F & Phase 6:
    - When an active CodeGraph MCP process is running, `run_install` emits an actionable
      upgrade lock warning mentioning `codegraph stop`.
    - `run_uninstall` automatically stops the running CodeGraph MCP process for that workspace.
    """
    proc_dir = tmp_path / "processes"
    monkeypatch.setenv("CODEGRAPH_PROCESS_DIR", str(proc_dir))

    repo = tmp_path / "repo_u"
    repo.mkdir()
    (repo / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    env = _subprocess_env(proc_dir)

    proc = subprocess.Popen(
        [sys.executable, "-m", "codegraph.cli", "mcp", "serve", str(repo)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert _wait_for_condition(lambda: (proc_dir / f"pid_{proc.pid}.json").exists(), timeout=5.0)
        assert is_pid_alive(proc.pid)

        # 1. `run_install` detects the active MCP process and includes the upgrade warning
        inst_report = run_install(
            workspace=repo,
            target="antigravity",
            location="local",
            dry_run=False,
        )
        assert any("codegraph stop" in w for w in inst_report.warnings), (
            f"Expected upgrade lock warning in {inst_report.warnings}"
        )

        # 2. `run_uninstall` stops the active MCP process for `repo`
        uninst_report = run_uninstall(
            workspace=repo,
            target="antigravity",
            location="local",
            dry_run=False,
        )
        assert uninst_report.status == "ok"
        assert _wait_for_condition(lambda: not is_pid_alive(proc.pid), timeout=4.0), (
            "run_uninstall must stop the running CodeGraph MCP server for the workspace"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)


# ===========================================================================
# DYNAMIC INDEX HOT-RELOAD TESTS (User Feedback #1)
# ===========================================================================


def test_dynamic_index_hot_reload_after_codegraph_init(tmp_path: Path) -> None:
    """Verify that if `codegraph mcp serve` starts BEFORE `codegraph init` is run:
    1. `get_repository_status` and `resolve_symbol` initially report `INDEX_NOT_FOUND`.
    2. After `Indexer(repo).index()` (`codegraph init`) creates `.codegraph.sqlite3`,
       the VERY NEXT tool call on the same MCP server instance automatically detects
       the new database and returns `status="ok"` and resolves symbols without restarting!
    3. Modifying a file and re-indexing automatically invalidates `get_graph_cache()` on the next tool call.
    """
    repo = tmp_path / "hot_reload_repo"
    repo.mkdir()
    src_file = repo / "service.py"
    src_file.write_text(
        "class PaymentProcessor:\n    def charge(self, amount: int) -> bool:\n        return amount > 0\n",
        encoding="utf-8",
    )

    server = create_server(repo, profile="full")

    async def _exercise_hot_reload() -> None:
        # 1. Before `codegraph init`, database does not exist -> INDEX_NOT_FOUND
        _, res_before = await server.call_tool("get_repository_status", {})
        assert res_before["status"] == "error"
        assert res_before["error"]["code"] == "INDEX_NOT_FOUND"

        _, sym_before = await server.call_tool("resolve_symbol", {"symbol": "PaymentProcessor.charge"})
        assert sym_before["status"] == "error"
        assert sym_before["error"]["code"] == "INDEX_NOT_FOUND"

        # 2. User runs `codegraph init` while MCP server is already running
        Indexer(repo).index()
        assert (repo / ".codegraph.sqlite3").exists()

        # 3. Next tool call on the SAME server instance automatically hot-reloads!
        _, res_after = await server.call_tool("get_repository_status", {})
        assert res_after["status"] == "ok"
        assert res_after["files"] == 1
        assert res_after["symbols"] >= 2

        _, sym_res = await server.call_tool("resolve_symbol", {"symbol": "PaymentProcessor.charge"})
        assert sym_res["status"] == "ok"
        assert "PaymentProcessor.charge" in sym_res["symbol"]["canonical_id"]

        # 4. Populate graph cache, then add a new symbol and re-index externally
        _, callees_before = await server.call_tool("get_callees", {"symbol": "PaymentProcessor.charge"})
        assert callees_before["status"] == "ok"

        time.sleep(0.02)
        src_file.write_text(
            "def validate_amount(a: int) -> bool:\n    return a > 0\n\n"
            "class PaymentProcessor:\n    def charge(self, amount: int) -> bool:\n        return validate_amount(amount)\n",
            encoding="utf-8",
        )
        Indexer(repo).index()

        # 5. Next tool call detects `.codegraph.sqlite3` mtime/size update and refreshes graph cache
        _, callees_after = await server.call_tool("get_callees", {"symbol": "PaymentProcessor.charge"})
        assert callees_after["status"] == "ok"
        callee_names = [
            str(c.get("callee") or c.get("qualified_name") or c.get("name") or "")
            for c in callees_after.get("callees", [])
        ]
        assert any("validate_amount" in n for n in callee_names), (
            f"Expected hot-reloaded graph to include validate_amount, got {callee_names}"
        )

        # 6. `get_repository_status()` confirms `reloaded=True` and updated symbol count
        _, explicit_reload = await server.call_tool("get_repository_status", {})
        assert explicit_reload["status"] == "ok"
        assert explicit_reload["reloaded"] is True
        assert explicit_reload["symbols"] >= 3

    asyncio.run(_exercise_hot_reload())
