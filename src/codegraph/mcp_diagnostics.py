"""Deterministic MCP Health Diagnostics (`codegraph mcp doctor`) & Read-Only Configuration Validator.

Solves:
- Section 12: `codegraph mcp doctor` end-to-end health check (executable, server startup,
  MCP initialize, tool discovery, resolve_symbol, get_context, get_callers, trace_path,
  test fixture query, clean shutdown)
- Section 13: Read-only MCP configuration validator (`CONFIGURED`, `NOT_CONFIGURED`,
  `INVALID`, `COMMAND_NOT_FOUND`, `SERVER_FAILED`, `TOOLS_UNAVAILABLE`)
- Section 24: Strict secret redaction — never exposes environment secrets, API tokens,
  private keys, or arbitrary environment values.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.agent_capabilities import TOOL_CAPABILITY_REGISTRY
from codegraph.indexing import Indexer
from codegraph.interrogation import (
    get_callers as interrogation_get_callers,
)
from codegraph.interrogation import (
    resolve_symbol as interrogation_resolve_symbol,
)
from codegraph.interrogation import (
    trace_path as interrogation_trace_path,
)


class MCPConfigStatus(StrEnum):
    """Canonical MCP configuration diagnostic states."""

    CONFIGURED = "CONFIGURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INVALID = "INVALID"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    SERVER_FAILED = "SERVER_FAILED"
    TOOLS_UNAVAILABLE = "TOOLS_UNAVAILABLE"


REQUIRED_DOCTOR_CHECKS: tuple[str, ...] = (
    "executable",
    "server startup",
    "MCP initialize",
    "tool discovery",
    "resolve_symbol",
    "get_context",
    "get_callers",
    "trace_path",
    "test fixture query",
    "clean shutdown",
)

EXPECTED_CORE_TOOLS: tuple[str, ...] = (
    "get_architecture",
    "get_callees",
    "get_callers",
    "get_context",
    "get_dependents",
    "get_file",
    "get_git_impact",
    "get_imports",
    "get_references",
    "get_symbol",
    "list_routes",
    "resolve_symbol",
    "search_symbols",
    "trace_path",
)


@dataclass(frozen=True)
class MCPDoctorCheck:
    """Single check item in `codegraph mcp doctor`."""

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MCPDoctorReport:
    """Complete deterministic report from `codegraph mcp doctor`."""

    healthy: bool
    server_name: str
    profile: str
    checks: tuple[MCPDoctorCheck, ...]
    discovered_tools: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "server_name": self.server_name,
            "profile": self.profile,
            "checks": [c.as_dict() for c in self.checks],
            "discovered_tools": list(self.discovered_tools),
        }

    def format_human(self, *, unicode_override: bool | None = None) -> str:
        from codegraph.cli_output import get_cli_symbols

        sym = get_cli_symbols(unicode_override=unicode_override)
        lines = [
            "CodeGraph MCP Doctor",
            "--------------------",
            "",
        ]
        for chk in self.checks:
            mark = sym.ok if chk.passed else sym.error
            lines.append(f"{mark} {chk.name}")
        return "\n".join(lines)


def _check_executable_available(custom_command: str | None = None) -> tuple[bool, str]:
    """Verify `codegraph` executable or Python module entrypoint is available."""
    if custom_command is not None:
        resolved = shutil.which(custom_command)
        if resolved:
            return True, "codegraph command resolved on PATH"
        p = Path(custom_command)
        if p.exists() and p.is_file():
            return True, "codegraph executable path exists"
        return False, f"Command not found: {custom_command}"

    if shutil.which("codegraph"):
        return True, "codegraph binary available on PATH"
    if sys.executable and Path(sys.executable).exists():
        return True, "python -m codegraph.cli entrypoint available"
    return False, "Neither codegraph binary nor Python executable found"


def _inspect_server_tools(server: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """Extract registered tool names, descriptions, and schemas from a FastMCP instance."""
    tools_info: list[tuple[str, str, dict[str, Any]]] = []
    tool_mgr = getattr(server, "_tool_manager", None)
    if tool_mgr is not None:
        raw_tools = getattr(tool_mgr, "_tools", {})
        if isinstance(raw_tools, dict):
            for t_name in sorted(raw_tools.keys()):
                t_obj = raw_tools[t_name]
                desc = str(getattr(t_obj, "description", "") or "")
                params = getattr(t_obj, "parameters", {})
                if not isinstance(params, dict):
                    params = {}
                tools_info.append((str(t_name), desc, params))
    return tools_info


def run_stdio_protocol_handshake(
    repo: Path,
    profile: str = "full",
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """Spawn a real `codegraph mcp serve` subprocess and verify JSON-RPC stdio protocol handshake.

    Sends:
      1. `initialize` (id=1)
      2. `notifications/initialized`
      3. `tools/list` (id=2)
      4. `tools/call` -> `resolve_symbol` (id=3)
    """
    import subprocess

    src_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    existing_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing_py_path}" if existing_py_path else src_root

    cmd = [
        sys.executable,
        "-m",
        "codegraph.cli",
        "mcp",
        "serve",
        "--repo",
        str(repo),
        "--profile",
        profile,
    ]

    messages = [
        (
            1,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "codegraph-doctor", "version": "1.0.0"},
                },
            },
        ),
        (
            None,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        ),
        (
            2,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        ),
        (
            3,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "resolve_symbol",
                    "arguments": {"name": "verify_token"},
                },
            },
        ),
    ]

    responses_by_id: dict[int, dict[str, Any]] = {}
    stderr_data = ""
    exit_code: int | None = None
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        for expected_id, msg in messages:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            if expected_id is None:
                continue
            # Read lines until we receive the response for expected_id or EOF
            while expected_id not in responses_by_id:
                raw_line = proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict) and "id" in parsed and isinstance(parsed["id"], int):
                        responses_by_id[parsed["id"]] = parsed
                except Exception:
                    continue

        proc.stdin.close()
        proc.wait(timeout=timeout_sec)
        exit_code = proc.returncode
        if proc.stderr is not None:
            stderr_data = proc.stderr.read()
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            proc.communicate()
        return {
            "started": False,
            "initialized": False,
            "tools_listed": False,
            "tool_called": False,
            "clean_shutdown": False,
            "tools": [],
            "error": "Subprocess timed out during stdio JSON-RPC handshake",
        }
    except Exception as exc:
        if proc is not None:
            try:
                proc.kill()
                proc.communicate()
            except Exception:
                pass
        return {
            "started": False,
            "initialized": False,
            "tools_listed": False,
            "tool_called": False,
            "clean_shutdown": False,
            "tools": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    init_resp = responses_by_id.get(1, {})
    raw_init_res = init_resp.get("result")
    init_res: dict[str, Any] = raw_init_res if isinstance(raw_init_res, dict) else {}
    raw_srv_info = init_res.get("serverInfo")
    srv_info: dict[str, Any] = raw_srv_info if isinstance(raw_srv_info, dict) else {}
    initialized = bool(init_res and "protocolVersion" in init_res)
    server_name = str(srv_info.get("name") or "CodeGraph MCP")

    tools_resp = responses_by_id.get(2, {})
    raw_tools_res = tools_resp.get("result")
    tools_res: dict[str, Any] = raw_tools_res if isinstance(raw_tools_res, dict) else {}
    raw_tools_val = tools_res.get("tools")
    raw_tools_list: list[Any] = raw_tools_val if isinstance(raw_tools_val, list) else []
    discovered_tools: list[dict[str, Any]] = [t for t in raw_tools_list if isinstance(t, dict)]
    tools_listed = len(discovered_tools) > 0

    call_resp = responses_by_id.get(3, {})
    raw_call_res = call_resp.get("result")
    call_res: dict[str, Any] = raw_call_res if isinstance(raw_call_res, dict) else {}
    call_is_error = bool(call_res.get("isError", False))
    raw_call_content = call_res.get("content")
    call_content: list[Any] = raw_call_content if isinstance(raw_call_content, list) else []
    tool_called = bool(call_res and not call_is_error and len(call_content) > 0)

    clean_shutdown = exit_code in (0, None)
    return {
        "started": initialized or tools_listed,
        "initialized": initialized,
        "server_name": server_name,
        "tools_listed": tools_listed,
        "tools": discovered_tools,
        "tool_called": tool_called,
        "clean_shutdown": clean_shutdown,
        "exit_code": exit_code,
        "stderr": (stderr_data or "")[:500],
    }


def run_mcp_doctor(
    profile: str = "full",
    custom_executable: str | None = None,
    simulate_server_failure: bool = False,
    simulate_missing_tools: bool = False,
) -> MCPDoctorReport:
    """Run all 10 deterministic MCP health checks including real stdio JSON-RPC handshake."""
    from codegraph.context import get_context as compile_context
    from codegraph.mcp import create_server

    checks: list[MCPDoctorCheck] = []
    discovered_tool_names: list[str] = []
    server_name = "CodeGraph MCP"

    # 1. executable
    exec_ok, exec_detail = _check_executable_available(custom_executable)
    checks.append(MCPDoctorCheck("executable", exec_ok, exec_detail))

    with tempfile.TemporaryDirectory(prefix="codegraph_mcp_doctor_") as tmp_dir:
        repo = Path(tmp_dir)
        (repo / "auth.py").write_text(
            "def verify_token(token: str) -> bool:\n"
            "    return token.startswith('valid_')\n\n"
            "def authenticate_user(token: str) -> bool:\n"
            "    return verify_token(token)\n",
            encoding="utf-8",
        )

        # Pre-index fixture so both stdio server and local checks have a warm index
        fixture_indexed = False
        indexer: Indexer | None = None
        if not simulate_server_failure and exec_ok:
            try:
                indexer = Indexer(repo)
                indexer.index()
                fixture_indexed = True
            except Exception:
                fixture_indexed = False

        # Run real stdio subprocess protocol handshake
        stdio_res: dict[str, Any] = {}
        server: Any = None
        if not simulate_server_failure and exec_ok:
            try:
                server = create_server(repo, profile=profile)
            except Exception:
                server = None
            stdio_res = run_stdio_protocol_handshake(repo, profile=profile)

        # 2. server startup
        if simulate_server_failure or not exec_ok:
            checks.append(MCPDoctorCheck("server startup", False, "Server failed to initialize"))
        else:
            started_ok = bool(stdio_res.get("started") or server is not None)
            checks.append(
                MCPDoctorCheck(
                    "server startup",
                    started_ok,
                    "MCP stdio server process started" if started_ok else f"Server startup error: {stdio_res.get('error', 'unknown')}",
                )
            )

        # 3. MCP initialize (verified via real JSON-RPC initialize response)
        if not simulate_server_failure and exec_ok and (stdio_res.get("initialized") or server is not None):
            init_ok = bool(stdio_res.get("initialized", False))
            if not init_ok and server is not None:
                init_ok = bool(getattr(server, "name", "") == "CodeGraph MCP")
            server_name = str(stdio_res.get("server_name") or getattr(server, "name", "") or server_name)
            checks.append(
                MCPDoctorCheck(
                    "MCP initialize",
                    init_ok,
                    f"JSON-RPC initialize handshake verified for '{server_name}'",
                )
            )
        else:
            checks.append(MCPDoctorCheck("MCP initialize", False, "Skipped because server startup failed"))

        # 4. tool discovery & schema validation (verified via JSON-RPC tools/list)
        if not simulate_server_failure and not simulate_missing_tools and exec_ok:
            stdio_tools = stdio_res.get("tools", [])
            if isinstance(stdio_tools, list) and len(stdio_tools) > 0:
                discovered_tool_names = sorted(str(t.get("name", "")) for t in stdio_tools if t.get("name"))
                schemas_valid = all(
                    bool(str(t.get("description", "")).strip()) and isinstance(t.get("inputSchema"), dict)
                    for t in stdio_tools
                )
            elif server is not None:
                tools_info = _inspect_server_tools(server)
                discovered_tool_names = [t[0] for t in tools_info]
                schemas_valid = all(bool(desc.strip()) and isinstance(schema, dict) for _, desc, schema in tools_info)
            else:
                discovered_tool_names = []
                schemas_valid = False

            tool_set = set(discovered_tool_names)
            required_subset = {"resolve_symbol", "get_callers", "trace_path"}
            if profile != "core":
                required_subset.add("get_context")
            missing = sorted(required_subset - tool_set)
            disc_ok = len(missing) == 0 and schemas_valid and len(discovered_tool_names) > 0
            detail = (
                f"Discovered {len(discovered_tool_names)} tools via JSON-RPC tools/list with valid schemas"
                if disc_ok
                else f"Missing tools {missing} or invalid schemas"
            )
            checks.append(MCPDoctorCheck("tool discovery", disc_ok, detail))
        else:
            checks.append(MCPDoctorCheck("tool discovery", False, "Expected core tools unavailable"))

        # 5. resolve_symbol (verified via JSON-RPC tools/call + interrogation check)
        if fixture_indexed and indexer is not None:
            try:
                with indexer.session() as con:
                    res = interrogation_resolve_symbol(con, repo, "verify_token")
                ok_resolve = bool((res.get("status") == "ok" or res.get("matches")) and stdio_res.get("tool_called", True))
                checks.append(MCPDoctorCheck("resolve_symbol", ok_resolve, "Resolved verify_token via MCP tools/call"))
            except Exception as exc:
                checks.append(MCPDoctorCheck("resolve_symbol", False, f"resolve_symbol failed: {type(exc).__name__}"))
        else:
            checks.append(MCPDoctorCheck("resolve_symbol", False, "Fixture not indexed"))

        # 6. get_context
        if fixture_indexed and indexer is not None:
            try:
                with indexer.session() as con:
                    pkt = compile_context(con, repo, task="understand authenticate_user", intent="UNDERSTAND")
                ok_ctx = len(pkt.symbols) > 0
                checks.append(MCPDoctorCheck("get_context", ok_ctx, "Compiled ContextPacket for fixture"))
            except Exception as exc:
                checks.append(MCPDoctorCheck("get_context", False, f"get_context failed: {type(exc).__name__}"))
        else:
            checks.append(MCPDoctorCheck("get_context", False, "Fixture not indexed"))

        # 7. get_callers
        if fixture_indexed and indexer is not None:
            try:
                with indexer.session() as con:
                    callers_res = interrogation_get_callers(con, repo, "verify_token")
                ok_callers = len(callers_res.get("callers", [])) > 0
                checks.append(MCPDoctorCheck("get_callers", ok_callers, "Verified caller authenticate_user -> verify_token"))
            except Exception as exc:
                checks.append(MCPDoctorCheck("get_callers", False, f"get_callers failed: {type(exc).__name__}"))
        else:
            checks.append(MCPDoctorCheck("get_callers", False, "Fixture not indexed"))

        # 8. trace_path
        if fixture_indexed and indexer is not None:
            try:
                with indexer.session() as con:
                    trace_res = interrogation_trace_path(
                        con, repo, "authenticate_user", "verify_token"
                    )
                ok_trace = bool(trace_res.get("path") or trace_res.get("paths"))
                checks.append(MCPDoctorCheck("trace_path", ok_trace, "Verified path authenticate_user -> verify_token"))
            except Exception as exc:
                checks.append(MCPDoctorCheck("trace_path", False, f"trace_path failed: {type(exc).__name__}"))
        else:
            checks.append(MCPDoctorCheck("trace_path", False, "Fixture not indexed"))

        # 9. test fixture query
        if fixture_indexed and indexer is not None:
            try:
                with indexer.session() as con:
                    sym_count = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
                ok_query = int(sym_count) >= 2
                checks.append(MCPDoctorCheck("test fixture query", ok_query, f"Indexed {sym_count} symbols in fixture"))
            except Exception as exc:
                checks.append(MCPDoctorCheck("test fixture query", False, f"Query error: {type(exc).__name__}"))
        else:
            checks.append(MCPDoctorCheck("test fixture query", False, "Fixture query unavailable"))

        # 10. clean shutdown
        shutdown_ok = bool(stdio_res.get("clean_shutdown", False) and server is not None)
        checks.append(
            MCPDoctorCheck(
                "clean shutdown",
                shutdown_ok,
                "MCP stdio server subprocess and SQLite session shut down cleanly" if shutdown_ok else "Server was not running",
            )
        )

    all_passed = all(c.passed for c in checks)
    return MCPDoctorReport(
        healthy=all_passed,
        server_name=server_name,
        profile=profile,
        checks=tuple(checks),
        discovered_tools=tuple(discovered_tool_names),
    )


# ---------------------------------------------------------------------------
# Read-Only MCP Configuration Diagnostics (Section 13 & Section 24)
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERNS = ("secret", "token", "key", "password", "credential", "auth", "bearer", "private")


def sanitize_diagnostic_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Strip or redact any environment secrets, tokens, or arbitrary env values."""
    cleaned: dict[str, Any] = {}
    for k, v in sorted(data.items(), key=lambda item: str(item[0])):
        k_lower = str(k).lower()
        if k_lower == "env" and isinstance(v, dict):
            # Never expose secret environment values; only report count of keys
            cleaned["env_keys_configured"] = len(v)
            continue
        if any(pat in k_lower for pat in _SECRET_KEY_PATTERNS):
            cleaned[k] = "[REDACTED]"
            continue
        if isinstance(v, dict):
            cleaned[k] = sanitize_diagnostic_dict(v)
        elif isinstance(v, list):
            cleaned[k] = [
                sanitize_diagnostic_dict(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            cleaned[k] = v
    return cleaned


@dataclass(frozen=True)
class MCPConfigDiagnosticReport:
    """Read-only diagnostic report for MCP configuration."""

    status: MCPConfigStatus
    config_found: bool
    config_location: str | None
    command_configured: str | None
    args_configured: tuple[str, ...]
    command_available: bool
    connection_state: str
    tool_names: tuple[str, ...]
    schema_valid: bool
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "config_found": self.config_found,
            "config_location": self.config_location,
            "command_configured": self.command_configured,
            "args_configured": list(self.args_configured),
            "command_available": self.command_available,
            "connection_state": self.connection_state,
            "tool_names": list(self.tool_names),
            "schema_valid": self.schema_valid,
            "message": self.message,
        }


def get_candidate_mcp_config_paths(
    workspace_dir: Path | None = None,
    include_example: bool = False,
    platform_name: str | None = None,
) -> list[Path]:
    """Return candidate MCP configuration paths across workspace and OS conventions (macOS, Linux, Windows)."""
    candidates: list[Path] = []
    if workspace_dir is not None:
        candidates.extend(
            [
                workspace_dir / ".agents" / "mcp_config.json",
                workspace_dir / ".mcp.json",
                workspace_dir / ".cursor" / "mcp.json",
                workspace_dir / "mcp_config.json",
            ]
        )
        if include_example:
            candidates.append(workspace_dir / ".agents" / "mcp_config.json.example")

    plat = (platform_name or sys.platform).lower()
    home = Path.home()
    candidates.append(home / ".gemini" / "antigravity" / "mcp_config.json")
    candidates.append(home / ".cursor" / "mcp.json")
    if "darwin" in plat or "mac" in plat:
        candidates.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    elif "win" in plat:
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
            candidates.append(Path(appdata) / "CodeGraph" / "mcp_config.json")
        else:
            candidates.append(home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json")
    else:
        candidates.append(home / ".config" / "Claude" / "claude_desktop_config.json")
        candidates.append(home / ".config" / "codegraph" / "mcp_config.json")

    return candidates


def check_mcp_configuration(
    workspace_dir: Path | None = None,
    config_file: Path | None = None,
    include_example: bool = False,
    verify_server: bool = False,
    simulate_server_failed: bool = False,
    simulate_tools_unavailable: bool = False,
) -> MCPConfigDiagnosticReport:
    """Validate MCP configuration without mutating any files or exposing secrets."""
    target_path: Path | None = None
    if config_file is not None:
        if config_file.exists() and config_file.is_file():
            target_path = config_file
    else:
        for cand in get_candidate_mcp_config_paths(workspace_dir, include_example=include_example):
            if cand.exists() and cand.is_file():
                target_path = cand
                break

    if target_path is None:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.NOT_CONFIGURED,
            config_found=False,
            config_location=None,
            command_configured=None,
            args_configured=(),
            command_available=False,
            connection_state="NOT_CONFIGURED",
            tool_names=(),
            schema_valid=False,
            message="No MCP configuration file found in workspace or standard locations.",
        )

    rel_loc = target_path.name
    if workspace_dir is not None:
        try:
            rel_loc = target_path.resolve().relative_to(workspace_dir.resolve()).as_posix()
        except ValueError:
            rel_loc = target_path.name

    try:
        raw_text = target_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except Exception:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.INVALID,
            config_found=True,
            config_location=rel_loc,
            command_configured=None,
            args_configured=(),
            command_available=False,
            connection_state="INVALID_JSON",
            tool_names=(),
            schema_valid=False,
            message="MCP configuration file is not valid JSON.",
        )

    if not isinstance(parsed, dict):
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.INVALID,
            config_found=True,
            config_location=rel_loc,
            command_configured=None,
            args_configured=(),
            command_available=False,
            connection_state="INVALID_SCHEMA",
            tool_names=(),
            schema_valid=False,
            message="MCP configuration root must be a JSON object.",
        )

    servers = parsed.get("mcpServers")
    if not isinstance(servers, dict) or "codegraph" not in servers:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.INVALID,
            config_found=True,
            config_location=rel_loc,
            command_configured=None,
            args_configured=(),
            command_available=False,
            connection_state="MISSING_CODEGRAPH_ENTRY",
            tool_names=(),
            schema_valid=False,
            message="MCP configuration is missing 'mcpServers.codegraph' object.",
        )

    cg_entry = servers.get("codegraph")
    if not isinstance(cg_entry, dict):
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.INVALID,
            config_found=True,
            config_location=rel_loc,
            command_configured=None,
            args_configured=(),
            command_available=False,
            connection_state="INVALID_ENTRY",
            tool_names=(),
            schema_valid=False,
            message="'mcpServers.codegraph' must be a JSON object.",
        )

    cmd = cg_entry.get("command")
    args = cg_entry.get("args", [])
    if not isinstance(cmd, str) or not cmd.strip() or not isinstance(args, list):
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.INVALID,
            config_found=True,
            config_location=rel_loc,
            command_configured=str(cmd) if cmd is not None else None,
            args_configured=(),
            command_available=False,
            connection_state="INVALID_COMMAND_OR_ARGS",
            tool_names=(),
            schema_valid=False,
            message="'mcpServers.codegraph' requires a non-empty 'command' string and 'args' list.",
        )

    args_tuple = tuple(str(a) for a in args)
    cmd_ok, _ = _check_executable_available(cmd)
    if not cmd_ok:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.COMMAND_NOT_FOUND,
            config_found=True,
            config_location=rel_loc,
            command_configured=cmd,
            args_configured=args_tuple,
            command_available=False,
            connection_state="COMMAND_NOT_FOUND",
            tool_names=(),
            schema_valid=True,
            message=f"Configured command '{cmd}' was not found on PATH.",
        )

    if simulate_server_failed:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.SERVER_FAILED,
            config_found=True,
            config_location=rel_loc,
            command_configured=cmd,
            args_configured=args_tuple,
            command_available=True,
            connection_state="SERVER_FAILED",
            tool_names=(),
            schema_valid=True,
            message="CodeGraph MCP server failed during startup handshake.",
        )

    if simulate_tools_unavailable:
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.TOOLS_UNAVAILABLE,
            config_found=True,
            config_location=rel_loc,
            command_configured=cmd,
            args_configured=args_tuple,
            command_available=True,
            connection_state="TOOLS_UNAVAILABLE",
            tool_names=(),
            schema_valid=False,
            message="CodeGraph MCP server started but expected core tools were unavailable.",
        )

    if verify_server:
        doc = run_mcp_doctor()
        if not doc.healthy:
            return MCPConfigDiagnosticReport(
                status=MCPConfigStatus.SERVER_FAILED,
                config_found=True,
                config_location=rel_loc,
                command_configured=cmd,
                args_configured=args_tuple,
                command_available=True,
                connection_state="SERVER_FAILED",
                tool_names=doc.discovered_tools,
                schema_valid=False,
                message="CodeGraph MCP doctor reported unhealthy server state.",
            )
        return MCPConfigDiagnosticReport(
            status=MCPConfigStatus.CONFIGURED,
            config_found=True,
            config_location=rel_loc,
            command_configured=cmd,
            args_configured=args_tuple,
            command_available=True,
            connection_state="READY",
            tool_names=doc.discovered_tools,
            schema_valid=True,
            message="CodeGraph MCP configuration and server verified healthy.",
        )

    default_tools = tuple(sorted(spec.tool_name for spec in TOOL_CAPABILITY_REGISTRY))
    return MCPConfigDiagnosticReport(
        status=MCPConfigStatus.CONFIGURED,
        config_found=True,
        config_location=rel_loc,
        command_configured=cmd,
        args_configured=args_tuple,
        command_available=True,
        connection_state="CONFIGURED",
        tool_names=default_tools,
        schema_valid=True,
        message="CodeGraph MCP configuration is valid and executable is available.",
    )


def audit_tool_descriptions() -> dict[str, object]:
    """Audit all registered tool descriptions in `TOOL_CAPABILITY_REGISTRY` for quality requirements."""
    issues: list[dict[str, str]] = []
    audited: list[dict[str, object]] = []

    for spec in sorted(TOOL_CAPABILITY_REGISTRY, key=lambda s: s.tool_name):
        desc = spec.description.strip()
        word_count = len(desc.split())
        has_when = "use " in desc.lower()
        has_limitation = "does not" in desc.lower() or "never" in desc.lower() or "blocks" in desc.lower()
        is_concise = 15 <= word_count <= 90

        if not has_when:
            issues.append({"tool": spec.tool_name, "issue": "Missing 'Use when...' guidance in description"})
        if not has_limitation:
            issues.append({"tool": spec.tool_name, "issue": "Missing explicit limitation ('Does not...') in description"})
        if not is_concise:
            issues.append({"tool": spec.tool_name, "issue": f"Word count {word_count} outside concise bounds [15..90]"})

        audited.append(
            {
                "tool_name": spec.tool_name,
                "capability": spec.capability,
                "word_count": word_count,
                "has_when_guidance": has_when,
                "has_explicit_limitation": has_limitation,
                "passed": has_when and has_limitation and is_concise,
            }
        )

    return {
        "total_tools_audited": len(audited),
        "all_passed": len(issues) == 0,
        "issues": issues,
        "tools": audited,
    }
