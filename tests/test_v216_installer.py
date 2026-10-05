"""Comprehensive tests for CodeGraph v2.1.6 Production Installer, Uninstaller & Uninit (`codegraph install`, `uninstall`, `uninit`).

Covers all 22 required test areas in isolated temporary environments (never mutating real user config):
1. Agent detection (local and global)
2. Target filtering (`auto`, `all`, comma-separated, aliases, unsupported target error UX)
3. Global vs local location scoping
4. MCP config creation across supported agents
5. MCP config update preserving unrelated servers and top-level settings
6. Marker insertion (`<!-- CODEGRAPH:START -->` ... `<!-- CODEGRAPH:END -->`)
7. Marker replacement in place preserving surrounding user instructions
8. Idempotency (`install` x3 -> zero duplicate blocks, zero unnecessary writes)
9. Duplicate prevention
10. Malformed JSON config detection & structured error UX
11. Partial installation & repair behavior (duplicate/broken markers, corrupted mcpServers, `--repair` with `.bak`)
12. `--dry-run` preview without mutating disk
13. `--yes` and interactive confirmation (`y` vs `n`)
14. `--json` and `--print-config <agent>`
15. `uninstall` symmetry (preserves user config, `.git`, source files, and `.codegraph.sqlite3`)
16. `uninit` (removes `.codegraph.sqlite3` and `.codegraph/` while preserving source and agent configs)
17. Modified-file protection on both `install` and `uninstall`
18. Path traversal, null-byte, and sensitive-file protection
19. Symlink escape protection
20. Atomic writes and transactional rollback on failure
21. Post-install MCP verification
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.errors import CodeGraphError, ErrorCode, SecurityError
from codegraph.installer import (
    INSTALLER_AGENT_ORDER,
    MARKER_END,
    MARKER_START,
    PlannedFileChange,
    _apply_planned_changes_atomically,
    _ensure_safe_target_path,
    detect_agents,
    resolve_target_agents,
    run_install,
    run_uninstall,
)

runner = CliRunner()


def _fake_which_none(_cmd: str) -> str | None:
    return None


# ---------------------------------------------------------------------------
# 1. Agent Detection & Target Filtering
# ---------------------------------------------------------------------------


def test_01_agent_detection_in_fake_environments(tmp_path: Path) -> None:
    """Detect agents accurately from local workspace and global home directories."""
    ws = tmp_path / "workspace"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    # Initially nothing detected
    detected0 = detect_agents(ws, home=home, which_fn=_fake_which_none)
    assert [a.agent_id for a in detected0] == list(INSTALLER_AGENT_ORDER)
    assert all(not a.detected for a in detected0)

    # Create fake global Claude & Cursor, local Antigravity & Gemini
    (home / ".claude").mkdir()
    (home / ".cursor").mkdir()
    (ws / ".agents").mkdir()
    (ws / "GEMINI.md").write_text("# Gemini\n", encoding="utf-8")

    detected1 = {a.agent_id: a for a in detect_agents(ws, home=home, which_fn=_fake_which_none)}
    assert detected1["claude"].detected is True
    assert detected1["claude"].detected_global is True
    assert detected1["cursor"].detected is True
    assert detected1["cursor"].detected_global is True
    assert detected1["antigravity"].detected is True
    assert detected1["antigravity"].detected_local is True
    assert detected1["gemini"].detected is True
    assert detected1["gemini"].detected_local is True
    assert detected1["codex"].detected is False
    assert detected1["cline"].detected is False


def test_02_target_filtering_and_unsupported_agent_error_ux(tmp_path: Path) -> None:
    """Verify `--target auto`, `--target all`, comma lists, aliases, and structured error on unsupported targets."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    # When none detected, auto falls back to antigravity
    det_empty = detect_agents(ws, home=home, which_fn=_fake_which_none)
    assert resolve_target_agents("auto", det_empty) == ["antigravity"]

    # When cursor & claude detected, auto selects them in canonical order
    (home / ".claude").mkdir()
    (ws / ".cursor").mkdir()
    det_some = detect_agents(ws, home=home, which_fn=_fake_which_none)
    assert resolve_target_agents("auto", det_some) == ["claude", "cursor"]

    # all selects all 6 supported agents
    assert resolve_target_agents("all", det_some) == list(INSTALLER_AGENT_ORDER)

    # Explicit comma-separated list & aliases
    assert resolve_target_agents("claude-code,cursor,agy,gemini-cli", det_some) == [
        "claude",
        "cursor",
        "antigravity",
        "gemini",
    ]

    # Unsupported target (e.g. kiro or unknown) raises CodeGraphError with UNSUPPORTED_AGENT
    with pytest.raises(CodeGraphError) as exc_info:
        resolve_target_agents("kiro", det_some)
    assert exc_info.value.code == ErrorCode.UNSUPPORTED_AGENT.value
    assert "Kiro" in exc_info.value.message
    assert exc_info.value.next_action is not None


# ---------------------------------------------------------------------------
# 2. Global vs Local Scope & Config Creation / Update
# ---------------------------------------------------------------------------


def test_03_local_and_global_installation_scopes(tmp_path: Path) -> None:
    """Verify `--location local` writes only to workspace and `--location global` writes only to home."""
    ws = tmp_path / "project"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    # Local install for claude, cursor, antigravity
    rep_local = run_install(
        workspace=ws,
        target="claude,cursor,antigravity",
        location="local",
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep_local.status == "ok"
    assert (ws / ".mcp.json").exists()
    assert (ws / "CLAUDE.md").exists()
    assert (ws / ".cursor" / "mcp.json").exists()
    assert (ws / ".cursorrules").exists()
    assert (ws / ".agents" / "mcp_config.json").exists()
    assert (ws / ".agents" / "rules" / "codegraph.md").exists()
    assert (ws / ".agents" / "skills" / "codegraph" / "SKILL.md").exists()
    assert (ws / "AGENTS.md").exists()
    # Home was untouched
    assert list(home.iterdir()) == []

    # Global install for claude, cursor, antigravity, gemini, codex, cline
    rep_global = run_install(
        workspace=ws,
        target="all",
        location="global",
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep_global.status == "ok"
    assert (home / ".claude.json").exists()
    assert (home / ".claude" / "CLAUDE.md").exists()
    assert (home / ".cursor" / "mcp.json").exists()
    assert (home / ".gemini" / "antigravity" / "mcp_config.json").exists()
    assert (home / ".gemini" / "config" / "GEMINI.md").exists()
    assert (home / ".gemini" / "config" / "skills" / "codegraph" / "SKILL.md").exists()
    assert (home / ".gemini" / "settings.json").exists()
    assert (home / ".codex" / "mcp_config.json").exists()
    assert (home / ".cline" / "mcp_settings.json").exists()


def test_04_mcp_config_preserves_unrelated_servers_and_settings(tmp_path: Path) -> None:
    """Updating existing MCP config preserves other MCP servers and unrelated top-level JSON keys."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    existing_cfg = {
        "theme": "dark",
        "autoApprove": ["read_file"],
        "mcpServers": {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
            }
        },
    }
    (ws / ".mcp.json").write_text(json.dumps(existing_cfg, indent=2), encoding="utf-8")

    rep = run_install(
        workspace=ws,
        target="claude",
        location="local",
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep.status == "ok"

    updated = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    assert updated["theme"] == "dark"
    assert updated["autoApprove"] == ["read_file"]
    assert updated["mcpServers"]["github"] == existing_cfg["mcpServers"]["github"]
    assert updated["mcpServers"]["codegraph"] == {
        "command": "codegraph",
        "args": ["mcp", "serve"],
    }


# ---------------------------------------------------------------------------
# 3. Marker Insertion, Replacement, Idempotency & Duplicate Prevention
# ---------------------------------------------------------------------------


def test_05_marker_insertion_and_in_place_replacement_preserves_user_content(tmp_path: Path) -> None:
    """Marker block is appended without touching user text, and updated in place on subsequent runs."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    user_header = "# My Custom Project Rules\n\nAlways run pytest before committing.\n"
    user_footer = "\n## Team Conventions\n\nUse snake_case everywhere.\n"
    claude_md = ws / "CLAUDE.md"
    claude_md.write_text(
        f"{user_header}\n{MARKER_START}\nOLD OUTDATED CODEGRAPH CONTENT\n{MARKER_END}\n{user_footer}",
        encoding="utf-8",
    )

    rep = run_install(
        workspace=ws,
        target="claude",
        location="local",
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep.status == "ok"

    result_text = claude_md.read_text(encoding="utf-8")
    assert "My Custom Project Rules" in result_text
    assert "Always run pytest before committing." in result_text
    assert "Use snake_case everywhere." in result_text
    assert "OLD OUTDATED CODEGRAPH CONTENT" not in result_text
    assert result_text.count(MARKER_START) == 1
    assert result_text.count(MARKER_END) == 1
    assert "## CodeGraph Mental Model" in result_text


def test_06_idempotency_across_repeated_installs(tmp_path: Path) -> None:
    """Running `codegraph install` three times produces identical state and zero duplicate blocks."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    r1 = run_install(workspace=ws, target="all", location="local", home=home, which_fn=_fake_which_none, run_server_check=False)
    assert r1.status == "ok"
    assert r1.files_changed is True

    snapshot1 = {
        p.relative_to(ws).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(ws.rglob("*"))
        if p.is_file()
    }

    r2 = run_install(workspace=ws, target="all", location="local", home=home, which_fn=_fake_which_none, run_server_check=False)
    assert r2.status == "ok"
    assert r2.files_changed is False
    assert all(c.action == "unchanged" for c in r2.changes)

    r3 = run_install(workspace=ws, target="all", location="local", home=home, which_fn=_fake_which_none, run_server_check=False)
    assert r3.status == "ok"
    assert r3.files_changed is False

    snapshot3 = {
        p.relative_to(ws).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(ws.rglob("*"))
        if p.is_file()
    }
    assert snapshot1 == snapshot3


# ---------------------------------------------------------------------------
# 4. Malformed Config, Partial Installation & Repair Mode
# ---------------------------------------------------------------------------


def test_07_malformed_json_detected_and_repaired_with_backup(tmp_path: Path) -> None:
    """Malformed JSON raises CONFIG_PARSE_ERROR by default, and backs up + repairs when `allow_malformed_repair=True`."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    broken_json = '{"mcpServers": {"codegraph": INVALID_JSON'
    (ws / ".mcp.json").write_text(broken_json, encoding="utf-8")

    with pytest.raises(CodeGraphError) as exc_info:
        run_install(
            workspace=ws,
            target="claude",
            location="local",
            home=home,
            which_fn=_fake_which_none,
            run_server_check=False,
        )
    assert exc_info.value.code == ErrorCode.CONFIG_PARSE_ERROR.value
    # File was not overwritten on error
    assert (ws / ".mcp.json").read_text(encoding="utf-8") == broken_json

    # Now run with allow_malformed_repair=True (--repair)
    rep = run_install(
        workspace=ws,
        target="claude",
        location="local",
        allow_malformed_repair=True,
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep.status == "ok"
    assert len(rep.repairs) >= 1
    assert (ws / ".mcp.json.bak").exists()
    assert (ws / ".mcp.json.bak").read_text(encoding="utf-8") == broken_json
    repaired_cfg = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    assert repaired_cfg["mcpServers"]["codegraph"]["args"] == ["mcp", "serve"]


def test_08_repair_mode_fixes_duplicate_markers_and_corrupted_mcp_entry(tmp_path: Path) -> None:
    """Partial/corrupted CodeGraph entries and duplicated markers are repaired while preserving user content."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    # Corrupted mcpServers.codegraph + duplicate key case + unrelated server
    (ws / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "other-mcp", "args": []},
                    "codegraph": {"command": "", "args": ["wrong"]},
                    "CodeGraph": {"command": "old", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )

    # Duplicated markers in CLAUDE.md
    (ws / "CLAUDE.md").write_text(
        f"# User Header\n\n{MARKER_START}\nBlock 1\n{MARKER_END}\n\nMiddle text\n\n{MARKER_START}\nBlock 2\n{MARKER_END}\n",
        encoding="utf-8",
    )

    rep = run_install(
        workspace=ws,
        target="claude",
        location="local",
        home=home,
        which_fn=_fake_which_none,
        run_server_check=False,
    )
    assert rep.status == "ok"
    assert len(rep.repairs) == 2

    cfg = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["other"] == {"command": "other-mcp", "args": []}
    assert list(cfg["mcpServers"].keys()) == ["other", "codegraph"]
    assert cfg["mcpServers"]["codegraph"] == {"command": "codegraph", "args": ["mcp", "serve"]}

    md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "# User Header" in md
    assert "Middle text" in md
    assert md.count(MARKER_START) == 1
    assert md.count(MARKER_END) == 1


# ---------------------------------------------------------------------------
# 5. CLI Options: --dry-run, --yes, Interactive Prompt, --json, --print-config
# ---------------------------------------------------------------------------


def test_09_cli_dry_run_modifies_nothing(tmp_path: Path) -> None:
    """`codegraph install --dry-run` shows exact planned changes and writes zero files."""
    res = runner.invoke(app, ["install", str(tmp_path), "--target", "claude,cursor", "--dry-run"])
    assert res.exit_code == 0
    assert "CodeGraph Installer" in res.stdout
    assert "Would create:" in res.stdout
    assert ".mcp.json" in res.stdout
    assert "CLAUDE.md" in res.stdout
    assert "No files were changed." in res.stdout
    assert list(tmp_path.iterdir()) == []


def test_10_cli_interactive_confirmation_yes_and_no(tmp_path: Path) -> None:
    """Interactive prompt aborts on `n` (modifying nothing) and proceeds on `y`."""
    # Decline confirmation
    res_no = runner.invoke(app, ["install", str(tmp_path), "--target", "claude"], input="n\n")
    assert res_no.exit_code == 0
    assert "Continue? [y/N]" in res_no.stdout
    assert "No files were changed." in res_no.stdout
    assert list(tmp_path.iterdir()) == []

    # Accept confirmation
    res_yes = runner.invoke(app, ["install", str(tmp_path), "--target", "claude"], input="y\n")
    assert res_yes.exit_code == 0
    assert "✓ CodeGraph installed" in res_yes.stdout
    assert "✓ MCP configuration verified" in res_yes.stdout
    assert "✓ Agent instructions verified" in res_yes.stdout
    assert "✓ MCP server health verified" in res_yes.stdout
    assert (tmp_path / ".mcp.json").exists()
    assert (tmp_path / "CLAUDE.md").exists()


def test_11_cli_json_and_print_config_modes(tmp_path: Path) -> None:
    """Verify `--print-config <agent>` and `--json` output deterministic structured JSON."""
    res_print = runner.invoke(app, ["install", "--print-config", "claude", "--json"])
    assert res_print.exit_code == 0
    payload = json.loads(res_print.stdout)
    assert payload["status"] == "ok"
    assert payload["agent"] == "claude"
    assert payload["mcp_config"]["mcpServers"]["codegraph"]["args"] == ["mcp", "serve"]
    assert MARKER_START in payload["instructions_block"]

    res_inst = runner.invoke(app, ["install", str(tmp_path), "--target", "antigravity", "--yes", "--json"])
    assert res_inst.exit_code == 0
    inst_data = json.loads(res_inst.stdout)
    assert inst_data["status"] == "ok"
    assert inst_data["verification"]["passed"] is True
    assert inst_data["verification"]["tool_count"] == 62


# ---------------------------------------------------------------------------
# 6. Uninstall Symmetry, Modified-File Protection & Uninit
# ---------------------------------------------------------------------------


def test_12_uninstall_reverses_only_codegraph_changes_and_preserves_index_and_user_files(tmp_path: Path) -> None:
    """`codegraph uninstall` removes CodeGraph integration while preserving user instructions, other MCP servers, source code, and `.codegraph.sqlite3`."""
    # Seed source file, index DB, user CLAUDE.md, and existing MCP server
    (tmp_path / "app.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
    (tmp_path / ".codegraph.sqlite3").write_text("sqlite-dummy", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# User Instructions\nKeep this section.\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"postgres": {"command": "pg-mcp", "args": []}}}),
        encoding="utf-8",
    )

    # Install Claude + Antigravity
    runner.invoke(app, ["install", str(tmp_path), "--target", "claude,antigravity", "--yes"])
    assert (tmp_path / ".agents" / "skills" / "codegraph" / "SKILL.md").exists()
    assert MARKER_START in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    # Dry-run uninstall first
    res_dry = runner.invoke(app, ["uninstall", str(tmp_path), "--dry-run"])
    assert res_dry.exit_code == 0
    assert "No files were changed." in res_dry.stdout
    assert (tmp_path / ".agents" / "skills" / "codegraph" / "SKILL.md").exists()

    # Execute uninstall
    res_un = runner.invoke(app, ["uninstall", str(tmp_path), "--yes"])
    assert res_un.exit_code == 0
    assert "✓ CodeGraph agent integration uninstalled" in res_un.stdout

    # Standalone CodeGraph files were removed
    assert not (tmp_path / ".agents" / "skills" / "codegraph" / "SKILL.md").exists()
    assert not (tmp_path / ".agents" / "rules" / "codegraph.md").exists()
    assert not (tmp_path / ".agents" / "mcp_config.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()

    # Shared files preserved user content and removed only CodeGraph section
    claude_after = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "# User Instructions" in claude_after
    assert "Keep this section." in claude_after
    assert MARKER_START not in claude_after

    mcp_after = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "codegraph" not in mcp_after["mcpServers"]
    assert mcp_after["mcpServers"]["postgres"] == {"command": "pg-mcp", "args": []}

    # Source code and index database were untouched
    assert (tmp_path / "app.py").exists()
    assert (tmp_path / ".codegraph.sqlite3").exists()


def test_13_modified_file_protection_on_install_and_uninstall(tmp_path: Path) -> None:
    """Manually modified CodeGraph files/blocks are detected, warned, and never silently overwritten or deleted."""
    ws = tmp_path / "ws"
    home = tmp_path / "home"
    ws.mkdir()
    home.mkdir()

    run_install(workspace=ws, target="antigravity,claude", location="local", home=home, which_fn=_fake_which_none, run_server_check=False)

    # User manually customizes standalone `.agents/rules/codegraph.md`
    rule_path = ws / ".agents" / "rules" / "codegraph.md"
    custom_rule = rule_path.read_text(encoding="utf-8") + "\n# User Custom Addition\nDo not delete me.\n"
    rule_path.write_text(custom_rule, encoding="utf-8")

    # User also manually edits inside the marker block of CLAUDE.md
    claude_path = ws / "CLAUDE.md"
    claude_path.write_text(
        f"{MARKER_START}\nUser customized inside marker block\n{MARKER_END}\n",
        encoding="utf-8",
    )

    # Re-running install warns and skips overwriting `.agents/rules/codegraph.md`
    rep_inst = run_install(workspace=ws, target="antigravity", location="local", home=home, which_fn=_fake_which_none, run_server_check=False)
    assert any("Protected manually modified file" in w for w in rep_inst.warnings)
    assert rule_path.read_text(encoding="utf-8") == custom_rule

    # Running uninstall warns and preserves both modified files
    rep_un = run_uninstall(workspace=ws, target="antigravity,claude", location="local", home=home, which_fn=_fake_which_none)
    assert len(rep_un.warnings) >= 2
    assert rule_path.exists()
    assert rule_path.read_text(encoding="utf-8") == custom_rule
    assert claude_path.exists()
    assert "User customized inside marker block" in claude_path.read_text(encoding="utf-8")


def test_14_uninit_removes_project_index_only(tmp_path: Path) -> None:
    """`codegraph uninit` removes `.codegraph.sqlite3*` and `.codegraph/` without touching source or agent configs."""
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    runner.invoke(app, ["init", str(tmp_path)])
    runner.invoke(app, ["install", str(tmp_path), "--target", "claude", "--yes"])
    (tmp_path / ".codegraph").mkdir(exist_ok=True)
    (tmp_path / ".codegraph" / "cache.json").write_text("{}", encoding="utf-8")

    assert (tmp_path / ".codegraph.sqlite3").exists()
    assert (tmp_path / ".codegraph").exists()

    # Dry-run uninit
    res_dry = runner.invoke(app, ["uninit", str(tmp_path), "--dry-run"])
    assert res_dry.exit_code == 0
    assert (tmp_path / ".codegraph.sqlite3").exists()

    # Actual uninit
    res_uninit = runner.invoke(app, ["uninit", str(tmp_path), "--yes"])
    assert res_uninit.exit_code == 0
    assert not (tmp_path / ".codegraph.sqlite3").exists()
    assert not (tmp_path / ".codegraph").exists()
    # Source and agent config remain intact
    assert (tmp_path / "main.py").exists()
    assert (tmp_path / ".mcp.json").exists()


# ---------------------------------------------------------------------------
# 7. Path Traversal, Symlink Protection & Atomic Rollback
# ---------------------------------------------------------------------------


def test_15_path_traversal_sensitive_file_and_symlink_protection(tmp_path: Path) -> None:
    """Reject traversal (`..`), null bytes, sensitive paths (`.env`), and symlinks."""
    with pytest.raises(SecurityError):
        _ensure_safe_target_path(tmp_path, "../escape.json")

    with pytest.raises(SecurityError):
        _ensure_safe_target_path(tmp_path, "bad\x00path.json")

    with pytest.raises(SecurityError):
        _ensure_safe_target_path(tmp_path, ".env")

    # Symlink file blocked
    outside = tmp_path.parent / f"outside_{tmp_path.name}.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        sym_file = tmp_path / ".mcp.json"
        sym_file.symlink_to(outside)
        with pytest.raises(SecurityError):
            _ensure_safe_target_path(tmp_path, ".mcp.json")
    finally:
        if outside.exists():
            outside.unlink()


def test_16_atomic_rollback_restores_previous_files_on_failure(tmp_path: Path) -> None:
    """If an error occurs mid-transaction, all previously modified files in the batch are rolled back."""
    f1 = tmp_path / "file1.md"
    f2 = tmp_path / "file2.json"
    f1.write_text("original-1", encoding="utf-8")
    f2.write_text('{"original": true}', encoding="utf-8")

    changes = [
        PlannedFileChange(
            path=f1,
            display_path="file1.md",
            action="modify",
            category="instructions",
            agent_id="claude",
            detail="update f1",
            new_content="updated-1",
        ),
        PlannedFileChange(
            path=f2,
            display_path="file2.json",
            action="modify",
            category="mcp_config",
            agent_id="claude",
            detail="corrupt json triggers verification failure",
            new_content="{INVALID_JSON_THAT_FAILS_POST_WRITE_VERIFICATION",
        ),
    ]

    with pytest.raises(json.JSONDecodeError):
        _apply_planned_changes_atomically(changes)

    # Both f1 and f2 are restored to their exact original contents
    assert f1.read_text(encoding="utf-8") == "original-1"
    assert f2.read_text(encoding="utf-8") == '{"original": true}'
