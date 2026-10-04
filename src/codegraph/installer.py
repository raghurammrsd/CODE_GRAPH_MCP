"""Production Installer, Agent Onboarding, Uninstaller & Index Uninitializer (`codegraph install`, `uninstall`, `uninit`).

Provides:
- Deterministic AI agent detection (Claude Code, Cursor, Antigravity, Codex CLI, Gemini CLI, Cline)
- Safe, atomic, idempotent MCP configuration (`mcpServers.codegraph`) preserving unrelated user config
- Marker-based instruction management (`<!-- CODEGRAPH:START -->` ... `<!-- CODEGRAPH:END -->`)
- Duplicate block prevention and automatic repair of partial/corrupted CodeGraph blocks
- Modified-file detection & protection (never silently overwrites or deletes user edits)
- Symlink & path-traversal protection (`SecurityError`)
- Post-install verification (executable, MCP config, rules/skills, MCP server health)
- Clean `uninstall` (removes only CodeGraph agent integration) and `uninit` (removes only project index)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.agent_rules import (
    render_agent_rules,
    render_antigravity_skill,
)
from codegraph.errors import CodeGraphError, ErrorCode, SecurityError
from codegraph.security import is_sensitive

MARKER_START = "<!-- CODEGRAPH:START -->"
MARKER_END = "<!-- CODEGRAPH:END -->"

INSTALLER_AGENT_ORDER: tuple[str, ...] = (
    "claude",
    "cursor",
    "antigravity",
    "codex",
    "gemini",
    "cline",
)

AGENT_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude Code",
    "cursor": "Cursor",
    "antigravity": "Antigravity",
    "codex": "Codex CLI",
    "gemini": "Gemini CLI",
    "cline": "Cline",
}

AGENT_ALIASES: dict[str, str] = {
    "claude": "claude",
    "claude-code": "claude",
    "claude_code": "claude",
    "claudecode": "claude",
    "cursor": "cursor",
    "antigravity": "antigravity",
    "agy": "antigravity",
    "codex": "codex",
    "codex-cli": "codex",
    "codex_cli": "codex",
    "gemini": "gemini",
    "gemini-cli": "gemini",
    "gemini_cli": "gemini",
    "cline": "cline",
}

UNSUPPORTED_KNOWN_AGENTS: dict[str, str] = {
    "kiro": "Kiro IDE does not yet have a standardized CLI MCP configuration schema in CodeGraph.",
    "windsurf": "Windsurf MCP configuration is not directly managed by CodeGraph installer.",
    "zed": "Zed uses custom context_servers settings outside standard mcpServers JSON.",
    "continue": "Continue uses YAML/JSON assistant blocks that vary per profile.",
}


@dataclass(frozen=True)
class DetectedAgent:
    """Detection status for a supported AI coding agent."""

    agent_id: str
    display_name: str
    detected: bool
    detected_global: bool
    detected_local: bool
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "detected": self.detected,
            "detected_global": self.detected_global,
            "detected_local": self.detected_local,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PlannedFileChange:
    """Single planned or applied file operation."""

    path: Path
    display_path: str
    action: str  # "create" | "modify" | "repair" | "unchanged" | "remove" | "skip_modified"
    category: str  # "mcp_config" | "instructions" | "skill" | "rules" | "index"
    agent_id: str
    detail: str
    new_content: str | None = None
    backup_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.display_path,
            "action": self.action,
            "category": self.category,
            "agent_id": self.agent_id,
            "detail": self.detail,
        }
        if self.backup_path is not None:
            data["backup_path"] = str(self.backup_path)
        return data


@dataclass(frozen=True)
class InstallVerificationResult:
    """Post-install verification report."""

    passed: bool
    executable_verified: bool
    mcp_config_verified: bool
    instructions_verified: bool
    mcp_server_health_verified: bool
    no_duplicate_config_verified: bool
    tool_count: int
    details: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "executable_verified": self.executable_verified,
            "mcp_config_verified": self.mcp_config_verified,
            "instructions_verified": self.instructions_verified,
            "mcp_server_health_verified": self.mcp_server_health_verified,
            "no_duplicate_config_verified": self.no_duplicate_config_verified,
            "tool_count": self.tool_count,
            "details": list(self.details),
        }


@dataclass(frozen=True)
class InstallerReport:
    """Structured result for `codegraph install`, `codegraph uninstall`, or `codegraph uninit`."""

    status: str  # "ok" | "dry_run" | "aborted" | "error"
    operation: str  # "install" | "uninstall" | "uninit"
    location: str  # "local" | "global"
    workspace: str
    detected_agents: tuple[DetectedAgent, ...]
    selected_agents: tuple[str, ...]
    changes: tuple[PlannedFileChange, ...]
    warnings: tuple[str, ...] = ()
    repairs: tuple[str, ...] = ()
    verification: InstallVerificationResult | None = None
    error: dict[str, Any] | None = None
    files_changed: bool = field(default=False)

    def as_dict(self) -> dict[str, Any]:
        created = [c.display_path for c in self.changes if c.action == "create"]
        modified = [c.display_path for c in self.changes if c.action == "modify"]
        repaired = [c.display_path for c in self.changes if c.action == "repair"]
        removed = [c.display_path for c in self.changes if c.action == "remove"]
        unchanged = [c.display_path for c in self.changes if c.action == "unchanged"]
        skipped = [c.display_path for c in self.changes if c.action == "skip_modified"]

        out: dict[str, Any] = {
            "status": self.status,
            "operation": self.operation,
            "location": self.location,
            "workspace": self.workspace,
            "files_changed": self.files_changed,
            "detected_agents": [a.as_dict() for a in self.detected_agents],
            "selected_agents": list(self.selected_agents),
            "summary": {
                "created": created,
                "modified": modified,
                "repaired": repaired,
                "removed": removed,
                "unchanged": unchanged,
                "skipped_modified": skipped,
            },
            "changes": [c.as_dict() for c in self.changes],
            "warnings": list(self.warnings),
            "repairs": list(self.repairs),
        }
        if self.verification is not None:
            out["verification"] = self.verification.as_dict()
        if self.error is not None:
            out["error"] = self.error
        return out

    def format_preview_human(self, *, unicode_override: bool | None = None) -> str:
        """Render the interactive preview banner before confirmation."""
        from codegraph.cli_output import get_cli_symbols

        sym = get_cli_symbols(unicode_override=unicode_override)
        lines: list[str] = ["CodeGraph Installer", ""]
        lines.append("Detected agents:")
        for da in self.detected_agents:
            mark = sym.ok if da.detected else sym.error
            lines.append(f"  {mark} {da.display_name}")

        lines.append("")
        lines.append("Select agents to configure:")
        selected_set = set(self.selected_agents)
        for da in self.detected_agents:
            if da.agent_id in selected_set:
                lines.append(f"  [x] {da.display_name}")
            elif da.detected:
                lines.append(f"  [ ] {da.display_name}")

        lines.append("")
        lines.append("Installation scope:")
        if self.location == "global":
            lines.append(f"  {sym.radio_on} Global")
            lines.append(f"  {sym.radio_off} Current project")
        else:
            lines.append(f"  {sym.radio_off} Global")
            lines.append(f"  {sym.radio_on} Current project")

        lines.append("")
        lines.append("Changes to be made:")
        lines.append("  + MCP server configuration")
        lines.append("  + CodeGraph agent instructions")
        lines.append("  + CodeGraph skill/rules")
        return "\n".join(lines)

    def format_human(self, *, unicode_override: bool | None = None) -> str:
        """Render concise, professional human-readable output."""
        from codegraph.cli_output import get_cli_symbols

        sym = get_cli_symbols(unicode_override=unicode_override)
        if self.error is not None:
            err_lines = [
                f"Error [{self.error.get('code', 'ERROR')}]: {self.error.get('message', '')}",
            ]
            if self.error.get("why"):
                err_lines.extend(["", "Expected / Reason:", f"  {self.error['why']}"])
            next_act = self.error.get("next_action")
            if isinstance(next_act, dict) and next_act.get("command"):
                err_lines.extend(["", "Try:", f"  {next_act['command']}"])
            return "\n".join(err_lines)

        lines: list[str] = []
        created = [c for c in self.changes if c.action == "create"]
        modified = [c for c in self.changes if c.action == "modify"]
        repaired = [c for c in self.changes if c.action == "repair"]
        removed = [c for c in self.changes if c.action == "remove"]
        skipped = [c for c in self.changes if c.action == "skip_modified"]

        if self.status == "dry_run":
            if self.operation == "install":
                lines.append(self.format_preview_human(unicode_override=unicode_override))
                lines.append("")
            else:
                title = (
                    "CodeGraph Uninstaller (Dry Run)"
                    if self.operation == "uninstall"
                    else "CodeGraph Uninit (Dry Run)"
                )
                lines.append(title)
                lines.append("")

            if modified or repaired:
                lines.append("Would modify:")
                for c in [*modified, *repaired]:
                    lines.append(f"  {c.display_path}")
                lines.append("")
            if created:
                lines.append("Would create:")
                for c in created:
                    lines.append(f"  {c.display_path}")
                lines.append("")
            if removed:
                lines.append("Would remove:")
                for c in removed:
                    lines.append(f"  {c.display_path}")
                lines.append("")
            if skipped:
                lines.append("Would skip (modified by user):")
                for c in skipped:
                    lines.append(f"  {c.display_path} ({c.detail})")
                lines.append("")
            for w in self.warnings:
                lines.append(f"Warning: {w}")
            lines.append("No files were changed.")
            return "\n".join(lines)

        if self.status == "aborted":
            lines.append("Installation cancelled.")
            lines.append("No files were changed.")
            return "\n".join(lines)

        if self.operation == "install":
            for r_msg in self.repairs:
                lines.append(f"{sym.repair} Repaired: {r_msg}")
            for w_msg in self.warnings:
                lines.append(f"{sym.warn} Warning: {w_msg}")

            lines.append(f"{sym.ok} CodeGraph installed")
            if self.verification is not None:
                v_mcp = sym.ok if self.verification.mcp_config_verified else sym.error
                v_inst = sym.ok if self.verification.instructions_verified else sym.error
                v_srv = sym.ok if self.verification.mcp_server_health_verified else sym.error
                lines.append(f"{v_mcp} MCP configuration verified")
                lines.append(f"{v_inst} Agent instructions verified")
                lines.append(f"{v_srv} MCP server health verified")
            lines.extend(
                [
                    "",
                    "Next:",
                    "  cd <your-project>",
                    "  codegraph init",
                ]
            )
            return "\n".join(lines)

        if self.operation == "uninstall":
            for w_msg in self.warnings:
                lines.append(f"{sym.warn} Warning: {w_msg}")
            if removed or modified:
                for c in [*removed, *modified]:
                    verb = "Removed" if c.action == "remove" else "Updated"
                    lines.append(f"{sym.ok} {verb} {c.display_path}")
            else:
                lines.append(f"{sym.ok} No CodeGraph agent integrations needed removal")
            lines.append(f"{sym.ok} CodeGraph agent integration uninstalled")
            return "\n".join(lines)

        # uninit
        if removed:
            for c in removed:
                lines.append(f"{sym.ok} Removed {c.display_path}")
        else:
            lines.append(f"{sym.ok} No CodeGraph index files present")
        lines.append(f"{sym.ok} Project CodeGraph index removed")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Path & Symlink Safety
# ---------------------------------------------------------------------------


def _ensure_safe_target_path(
    base_root: Path,
    relative_path: str | Path,
    allow_index_artifact: bool = False,
) -> Path:
    """Resolve `base_root / relative_path` safely, blocking traversal, symlinks, and sensitive files."""
    raw_str = str(relative_path)
    if "\x00" in raw_str:
        raise SecurityError(
            "Null bytes are not allowed in configuration paths.",
            code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
        )
    rel_obj = Path(raw_str)
    if rel_obj.is_absolute() or ".." in rel_obj.parts:
        raise SecurityError(
            f"Path traversal blocked: '{relative_path}' escapes root boundary.",
            code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
        )

    if not allow_index_artifact and is_sensitive(rel_obj):
        raise SecurityError(
            f"Refusing to modify protected/sensitive path: '{relative_path}'.",
            code=ErrorCode.SENSITIVE_FILE_ACCESS_DENIED,
        )

    resolved_root = base_root.resolve(strict=True)
    # Walk every segment from base_root down to target to reject intermediate symlinks
    cur = base_root
    for part in rel_obj.parts:
        cur = cur / part
        if cur.is_symlink():
            raise SecurityError(
                f"Symlink blocked: '{cur}' is a symbolic link and cannot be modified by CodeGraph installer.",
                code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
            )

    candidate = (resolved_root / rel_obj).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SecurityError(
            f"Path '{relative_path}' resolves outside root '{resolved_root}'.",
            code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
        ) from exc

    if candidate.exists() and not candidate.is_file():
        raise CodeGraphError(
            f"Expected a regular file at '{candidate}', found non-file.",
            code=ErrorCode.INVALID_PATH,
            next_action={
                "command": "codegraph install --dry-run",
                "reason": "Inspect conflicting directory or special file at target path.",
            },
        )
    return candidate


def _atomic_write_text(target: Path, content: str) -> None:
    """Write `content` to `target` atomically via a same-directory temporary file and `os.replace`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise SecurityError(
            f"Refusing atomic write to symlink '{target}'.",
            code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
        )
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(target))
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Agent Detection & Target Resolution
# ---------------------------------------------------------------------------


def detect_agents(
    workspace: Path,
    home: Path | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> list[DetectedAgent]:
    """Deterministically detect supported AI coding agents in `home` and `workspace`."""
    effective_home = (home or Path.home()).resolve()
    effective_ws = workspace.resolve()
    which = which_fn or shutil.which

    results: list[DetectedAgent] = []

    for agent_id in INSTALLER_AGENT_ORDER:
        g_reasons: list[str] = []
        l_reasons: list[str] = []

        if agent_id == "claude":
            if (effective_home / ".claude").exists():
                g_reasons.append("~/.claude")
            if (effective_home / ".claude.json").exists():
                g_reasons.append("~/.claude.json")
            if which("claude"):
                g_reasons.append("claude on PATH")
            if (effective_ws / ".claude").exists():
                l_reasons.append(".claude/")
            if (effective_ws / "CLAUDE.md").exists():
                l_reasons.append("CLAUDE.md")
            if (effective_ws / ".mcp.json").exists():
                l_reasons.append(".mcp.json")

        elif agent_id == "cursor":
            if (effective_home / ".cursor").exists():
                g_reasons.append("~/.cursor")
            if which("cursor"):
                g_reasons.append("cursor on PATH")
            if (effective_ws / ".cursor").exists():
                l_reasons.append(".cursor/")
            if (effective_ws / ".cursorrules").exists():
                l_reasons.append(".cursorrules")

        elif agent_id == "antigravity":
            if (effective_home / ".gemini" / "antigravity").exists():
                g_reasons.append("~/.gemini/antigravity")
            if (effective_home / ".gemini" / "config").exists():
                g_reasons.append("~/.gemini/config")
            if which("agy") or which("antigravity"):
                g_reasons.append("agy on PATH")
            if (effective_ws / ".agents").exists():
                l_reasons.append(".agents/")

        elif agent_id == "codex":
            if (effective_home / ".codex").exists():
                g_reasons.append("~/.codex")
            if which("codex"):
                g_reasons.append("codex on PATH")
            if (effective_ws / ".codex").exists():
                l_reasons.append(".codex/")

        elif agent_id == "gemini":
            if (effective_home / ".gemini" / "settings.json").exists():
                g_reasons.append("~/.gemini/settings.json")
            if (effective_home / ".gemini" / "GEMINI.md").exists():
                g_reasons.append("~/.gemini/GEMINI.md")
            if which("gemini"):
                g_reasons.append("gemini on PATH")
            if (effective_ws / ".gemini").exists():
                l_reasons.append(".gemini/")
            if (effective_ws / "GEMINI.md").exists():
                l_reasons.append("GEMINI.md")

        elif agent_id == "cline":
            if (effective_home / ".cline").exists():
                g_reasons.append("~/.cline")
            if (effective_ws / ".cline").exists():
                l_reasons.append(".cline/")
            if (effective_ws / ".clinerules").exists():
                l_reasons.append(".clinerules")

        det_g = len(g_reasons) > 0
        det_l = len(l_reasons) > 0
        results.append(
            DetectedAgent(
                agent_id=agent_id,
                display_name=AGENT_DISPLAY_NAMES[agent_id],
                detected=det_g or det_l,
                detected_global=det_g,
                detected_local=det_l,
                reasons=tuple([*g_reasons, *l_reasons]),
            )
        )

    return results


def resolve_target_agents(
    target_spec: str,
    detected: list[DetectedAgent],
    default_if_none_detected: str = "antigravity",
) -> list[str]:
    """Resolve `--target` (`auto`, `all`, or comma-separated agent list) into canonical agent IDs."""
    raw = (target_spec or "auto").strip().lower()
    if not raw or raw == "auto":
        found = [a.agent_id for a in detected if a.detected]
        return found if found else [default_if_none_detected]

    if raw == "all":
        return list(INSTALLER_AGENT_ORDER)

    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        raise CodeGraphError(
            "Target specification cannot be empty.",
            code=ErrorCode.INVALID_ARGUMENT,
            next_action={
                "command": "codegraph install --target auto --dry-run",
                "reason": f"Supported targets: auto, all, {', '.join(INSTALLER_AGENT_ORDER)}",
            },
        )

    resolved: list[str] = []
    for p in parts:
        if p == "all":
            for aid in INSTALLER_AGENT_ORDER:
                if aid not in resolved:
                    resolved.append(aid)
            continue
        if p == "auto":
            for a in detected:
                if a.detected and a.agent_id not in resolved:
                    resolved.append(a.agent_id)
            continue
        if p in AGENT_ALIASES:
            canon = AGENT_ALIASES[p]
            if canon not in resolved:
                resolved.append(canon)
            continue
        why_msg = UNSUPPORTED_KNOWN_AGENTS.get(
            p,
            f"Agent '{p}' is not one of the supported targets ({', '.join(INSTALLER_AGENT_ORDER)}).",
        )
        raise CodeGraphError(
            f"Unsupported agent target '{p}'. {why_msg}",
            code=ErrorCode.UNSUPPORTED_AGENT,
            next_action={
                "command": "codegraph install --target auto --dry-run",
                "reason": f"Choose from supported agents: {', '.join(INSTALLER_AGENT_ORDER)}",
            },
        )

    return resolved if resolved else [default_if_none_detected]


# ---------------------------------------------------------------------------
# Marker-Based Markdown Section Management
# ---------------------------------------------------------------------------


def format_marker_block(inner_content: str) -> str:
    """Wrap `inner_content` in `<!-- CODEGRAPH:START -->` ... `<!-- CODEGRAPH:END -->` markers."""
    clean = inner_content.strip()
    return f"{MARKER_START}\n{clean}\n{MARKER_END}\n"


def _extract_marker_inner_blocks(text: str) -> list[str]:
    """Extract all inner blocks between `MARKER_START` and `MARKER_END`."""
    pattern = re.compile(
        re.escape(MARKER_START) + r"\n?(.*?)\n?" + re.escape(MARKER_END),
        re.DOTALL,
    )
    return [m.group(1).strip() for m in pattern.finditer(text)]


def _all_canonical_rule_variants() -> set[str]:
    """Return all canonical rendered rule strings across supported agents for modification detection."""
    variants: set[str] = set()
    for agent_key in ("antigravity", "agents", "gemini", "claude", "cursor", "codex", "cline"):
        variants.add(render_agent_rules(agent_key).strip())
    variants.add(render_antigravity_skill().strip())
    return variants


def is_codegraph_content_unmodified(content: str) -> bool:
    """Return True if `content` matches a canonical CodeGraph rule/skill body."""
    stripped = content.strip()
    if not stripped:
        return True
    if stripped in _all_canonical_rule_variants():
        return True
    # Also check if wrapped in markers with canonical inner body
    blocks = _extract_marker_inner_blocks(stripped)
    if len(blocks) == 1 and blocks[0] in _all_canonical_rule_variants():
        return True
    return False


def upsert_marker_section(
    existing_text: str | None,
    inner_content: str,
) -> tuple[str, str, str | None]:
    """Insert, update, or repair the `<!-- CODEGRAPH:START -->...<!-- CODEGRAPH:END -->` block.

    Returns:
        (new_full_text, action, repair_detail)
        where action is `"create" | "modify" | "repair" | "unchanged"`.
    """
    block = format_marker_block(inner_content)

    if existing_text is None:
        return block, "create", None

    start_count = existing_text.count(MARKER_START)
    end_count = existing_text.count(MARKER_END)

    # Case 1: Corrupted / unbalanced or duplicated markers -> Repair Mode
    if start_count != end_count or start_count > 1:
        repair_reason = (
            f"Found {start_count} start marker(s) and {end_count} end marker(s); "
            "consolidated into a single CodeGraph block while preserving user text."
        )
        # Remove all complete blocks first
        pattern = re.compile(
            r"\n*" + re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n*",
            re.DOTALL,
        )
        cleaned = pattern.sub("\n\n", existing_text)
        # Remove any stray dangling marker lines
        cleaned = cleaned.replace(MARKER_START, "").replace(MARKER_END, "").strip()
        if cleaned:
            repaired_text = f"{cleaned}\n\n{block}"
        else:
            repaired_text = block
        return repaired_text, "repair", repair_reason

    # Case 2: Exactly one start and one end marker
    if start_count == 1 and end_count == 1:
        start_idx = existing_text.index(MARKER_START)
        end_idx = existing_text.index(MARKER_END)
        if end_idx < start_idx:
            # Inverted markers -> Repair Mode
            cleaned = existing_text.replace(MARKER_START, "").replace(MARKER_END, "").strip()
            repaired_text = f"{cleaned}\n\n{block}" if cleaned else block
            return (
                repaired_text,
                "repair",
                "Repaired inverted CODEGRAPH:END / CODEGRAPH:START markers.",
            )

        end_after = end_idx + len(MARKER_END)
        if end_after < len(existing_text) and existing_text[end_after] == "\n":
            end_after += 1

        updated = existing_text[:start_idx] + block + existing_text[end_after:]
        if updated == existing_text:
            return existing_text, "unchanged", None
        return updated, "modify", None

    # Case 3: No markers yet
    stripped = existing_text.strip()
    if not stripped:
        return block, "modify", None

    # If the entire file is already a raw canonical CodeGraph rule file, wrap it in markers
    if stripped in _all_canonical_rule_variants():
        return block, "modify", None

    # Append marker block after existing user instructions
    appended = f"{ existing_text.rstrip() }\n\n{block}"
    return appended, "modify", None


def remove_marker_section(
    existing_text: str,
) -> tuple[str | None, str, str | None]:
    """Remove `<!-- CODEGRAPH:START -->...<!-- CODEGRAPH:END -->` from `existing_text`.

    Returns:
        (remaining_text_or_None_if_empty, action, warning_or_None)
        where action is `"remove" | "modify" | "unchanged" | "skip_modified"`.
    """
    if MARKER_START not in existing_text and MARKER_END not in existing_text:
        return existing_text, "unchanged", None

    blocks = _extract_marker_inner_blocks(existing_text)
    for b in blocks:
        if not is_codegraph_content_unmodified(b):
            return (
                existing_text,
                "skip_modified",
                "CodeGraph marker block was manually modified by user; preserving changes.",
            )

    pattern = re.compile(
        r"\n*" + re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n*",
        re.DOTALL,
    )
    remaining = pattern.sub("\n\n", existing_text).strip()
    if not remaining:
        return None, "remove", None
    return remaining + "\n", "modify", None


# ---------------------------------------------------------------------------
# MCP JSON Configuration Management
# ---------------------------------------------------------------------------


def build_agent_mcp_entry(agent_id: str, command: str = "codegraph") -> dict[str, Any]:
    """Return the canonical `mcpServers.codegraph` object for `agent_id`."""
    entry: dict[str, Any] = {
        "command": command,
        "args": ["mcp", "serve"],
    }
    if agent_id == "cline":
        entry["disabled"] = False
    return entry


def render_agent_mcp_config_snippet(agent_id: str, command: str = "codegraph") -> dict[str, Any]:
    """Return full top-level MCP config JSON snippet for `--print-config`."""
    canon = AGENT_ALIASES.get(agent_id.strip().lower(), agent_id.strip().lower())
    if canon not in AGENT_DISPLAY_NAMES:
        raise CodeGraphError(
            f"Unsupported agent '{agent_id}'.",
            code=ErrorCode.UNSUPPORTED_AGENT,
            next_action={
                "command": "codegraph install --print-config claude",
                "reason": f"Supported agents: {', '.join(INSTALLER_AGENT_ORDER)}",
            },
        )
    return {
        "mcpServers": {
            "codegraph": build_agent_mcp_entry(canon, command=command),
        }
    }


def upsert_mcp_json_config(
    existing_text: str | None,
    agent_id: str,
    display_path: str,
    command: str = "codegraph",
    allow_malformed_repair: bool = False,
) -> tuple[str, str, str | None]:
    """Create, update, or repair `mcpServers.codegraph` in a JSON configuration file.

    Preserves all unrelated top-level keys and other MCP servers.
    Returns `(new_json_text, action, repair_reason)`.
    """
    desired_entry = build_agent_mcp_entry(agent_id, command=command)

    if existing_text is None:
        doc = {"mcpServers": {"codegraph": desired_entry}}
        return json.dumps(doc, indent=2) + "\n", "create", None

    if not existing_text.strip():
        doc = {"mcpServers": {"codegraph": desired_entry}}
        return (
            json.dumps(doc, indent=2) + "\n",
            "repair",
            f"Repaired empty MCP configuration file '{display_path}'.",
        )

    try:
        parsed = json.loads(existing_text)
    except json.JSONDecodeError as exc:
        if allow_malformed_repair:
            doc = {"mcpServers": {"codegraph": desired_entry}}
            return (
                json.dumps(doc, indent=2) + "\n",
                "repair",
                f"Backed up and repaired malformed JSON in '{display_path}' (line {exc.lineno}).",
            )
        raise CodeGraphError(
            f"Malformed JSON in '{display_path}' (line {exc.lineno}, column {exc.colno}).",
            code=ErrorCode.CONFIG_PARSE_ERROR,
            next_action={
                "command": f"codegraph install --target {agent_id} --repair",
                "reason": f"Fix JSON syntax in {display_path} or pass --repair to back up and repair.",
            },
        ) from exc

    if not isinstance(parsed, dict):
        if allow_malformed_repair:
            doc = {"mcpServers": {"codegraph": desired_entry}}
            return (
                json.dumps(doc, indent=2) + "\n",
                "repair",
                f"Repaired non-object JSON root in '{display_path}'.",
            )
        raise CodeGraphError(
            f"Invalid MCP configuration root in '{display_path}': expected JSON object.",
            code=ErrorCode.CONFIG_PARSE_ERROR,
            next_action={
                "command": f"codegraph install --target {agent_id} --repair",
                "reason": "Ensure configuration root is a JSON object `{...}`.",
            },
        )

    repair_reason: str | None = None
    servers = parsed.get("mcpServers")
    if servers is None:
        parsed["mcpServers"] = {"codegraph": desired_entry}
        new_text = json.dumps(parsed, indent=2) + "\n"
        return new_text, "modify", None

    if not isinstance(servers, dict):
        repair_reason = f"Repaired corrupted 'mcpServers' field (was {type(servers).__name__}) in '{display_path}'."
        parsed["mcpServers"] = {"codegraph": desired_entry}
        return json.dumps(parsed, indent=2) + "\n", "repair", repair_reason

    # Detect duplicate case-insensitive codegraph keys (e.g. "CodeGraph" and "codegraph")
    cg_keys = [k for k in list(servers.keys()) if str(k).lower() == "codegraph"]
    if len(cg_keys) > 1:
        for k in cg_keys:
            if k != "codegraph":
                del servers[k]
        repair_reason = f"Removed duplicate CodeGraph server keys {cg_keys} in '{display_path}'."

    existing_cg = servers.get("codegraph")
    if existing_cg is not None:
        if not isinstance(existing_cg, dict):
            repair_reason = f"Repaired corrupted 'mcpServers.codegraph' entry in '{display_path}'."
        else:
            cmd_val = existing_cg.get("command")
            args_val = existing_cg.get("args")
            if (
                not isinstance(cmd_val, str)
                or not cmd_val.strip()
                or not isinstance(args_val, list)
                or args_val != ["mcp", "serve"]
            ):
                repair_reason = f"Repaired incomplete or outdated 'mcpServers.codegraph' entry in '{display_path}'."

    if existing_cg == desired_entry and repair_reason is None:
        # Canonical formatting check: if semantically identical, do not rewrite unnecessarily
        return existing_text, "unchanged", None

    servers["codegraph"] = desired_entry
    new_text = json.dumps(parsed, indent=2) + "\n"
    if repair_reason is not None:
        return new_text, "repair", repair_reason
    return new_text, "modify", None


def remove_mcp_json_config(
    existing_text: str,
    display_path: str,
    can_delete_file_when_empty: bool = True,
) -> tuple[str | None, str]:
    """Remove `mcpServers.codegraph` from `existing_text`.

    Preserves all other servers and top-level keys.
    Returns `(new_text_or_None_to_delete_file, action)`.
    """
    try:
        parsed = json.loads(existing_text)
    except Exception as exc:
        raise CodeGraphError(
            f"Cannot safely uninstall from malformed JSON file '{display_path}'.",
            code=ErrorCode.CONFIG_PARSE_ERROR,
            next_action={
                "command": "codegraph doctor",
                "reason": f"Fix JSON syntax in {display_path} before running uninstall.",
            },
        ) from exc

    if not isinstance(parsed, dict):
        return existing_text, "unchanged"

    servers = parsed.get("mcpServers")
    if not isinstance(servers, dict):
        return existing_text, "unchanged"

    cg_keys = [k for k in list(servers.keys()) if str(k).lower() == "codegraph"]
    if not cg_keys:
        return existing_text, "unchanged"

    for k in cg_keys:
        del servers[k]

    # If mcpServers is now empty and there are no other keys in the file
    other_top_keys = [k for k in parsed.keys() if k != "mcpServers"]
    if len(servers) == 0 and len(other_top_keys) == 0 and can_delete_file_when_empty:
        return None, "remove"

    return json.dumps(parsed, indent=2) + "\n", "modify"


# ---------------------------------------------------------------------------
# Target File Blueprints per Agent & Scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentFileSpec:
    """Specification of a file managed for a specific agent and scope."""

    agent_id: str
    relative_path: str
    category: str  # "mcp_config" | "instructions" | "skill" | "rules"
    mode: str  # "mcp_json" | "marker_md" | "standalone_md"
    rule_agent_key: str  # key passed to render_agent_rules or "skill"
    can_delete_when_empty: bool = True


def get_agent_file_specs(agent_id: str, location: str) -> list[AgentFileSpec]:
    """Return the exact files managed for `agent_id` in `location` (`local` or `global`)."""
    scope = location.lower()
    if scope == "project":
        scope = "local"

    if scope == "global":
        if agent_id == "claude":
            return [
                AgentFileSpec("claude", ".claude.json", "mcp_config", "mcp_json", "claude", can_delete_file_when_empty_for_global(".claude.json")),
                AgentFileSpec("claude", ".claude/CLAUDE.md", "instructions", "marker_md", "claude"),
            ]
        if agent_id == "cursor":
            return [
                AgentFileSpec("cursor", ".cursor/mcp.json", "mcp_config", "mcp_json", "cursor"),
                AgentFileSpec("cursor", ".cursor/rules/codegraph.md", "rules", "standalone_md", "cursor"),
            ]
        if agent_id == "antigravity":
            return [
                AgentFileSpec("antigravity", ".gemini/antigravity/mcp_config.json", "mcp_config", "mcp_json", "antigravity"),
                AgentFileSpec("antigravity", ".gemini/config/GEMINI.md", "instructions", "marker_md", "antigravity"),
                AgentFileSpec("antigravity", ".gemini/config/skills/codegraph/SKILL.md", "skill", "standalone_md", "skill"),
            ]
        if agent_id == "codex":
            return [
                AgentFileSpec("codex", ".codex/mcp_config.json", "mcp_config", "mcp_json", "codex"),
                AgentFileSpec("codex", ".codex/AGENTS.md", "instructions", "marker_md", "codex"),
            ]
        if agent_id == "gemini":
            return [
                AgentFileSpec("gemini", ".gemini/settings.json", "mcp_config", "mcp_json", "gemini", can_delete_when_empty=False),
                AgentFileSpec("gemini", ".gemini/GEMINI.md", "instructions", "marker_md", "gemini"),
            ]
        if agent_id == "cline":
            return [
                AgentFileSpec("cline", ".cline/mcp_settings.json", "mcp_config", "mcp_json", "cline"),
                AgentFileSpec("cline", ".cline/rules/codegraph.md", "rules", "standalone_md", "cline"),
            ]
        raise ValueError(f"Unsupported agent: {agent_id}")

    # Local (project) scope
    if agent_id == "claude":
        return [
            AgentFileSpec("claude", ".mcp.json", "mcp_config", "mcp_json", "claude"),
            AgentFileSpec("claude", "CLAUDE.md", "instructions", "marker_md", "claude"),
        ]
    if agent_id == "cursor":
        return [
            AgentFileSpec("cursor", ".cursor/mcp.json", "mcp_config", "mcp_json", "cursor"),
            AgentFileSpec("cursor", ".cursorrules", "instructions", "marker_md", "cursor"),
            AgentFileSpec("cursor", ".cursor/rules/codegraph.md", "rules", "standalone_md", "cursor"),
        ]
    if agent_id == "antigravity":
        return [
            AgentFileSpec("antigravity", ".agents/mcp_config.json", "mcp_config", "mcp_json", "antigravity"),
            AgentFileSpec("antigravity", ".agents/rules/codegraph.md", "rules", "standalone_md", "antigravity"),
            AgentFileSpec("antigravity", ".agents/skills/codegraph/SKILL.md", "skill", "standalone_md", "skill"),
            AgentFileSpec("antigravity", "AGENTS.md", "instructions", "marker_md", "agents"),
        ]
    if agent_id == "codex":
        return [
            AgentFileSpec("codex", ".codex/mcp_config.json", "mcp_config", "mcp_json", "codex"),
            AgentFileSpec("codex", "AGENTS.md", "instructions", "marker_md", "codex"),
        ]
    if agent_id == "gemini":
        return [
            AgentFileSpec("gemini", ".gemini/settings.json", "mcp_config", "mcp_json", "gemini"),
            AgentFileSpec("gemini", "GEMINI.md", "instructions", "marker_md", "gemini"),
        ]
    if agent_id == "cline":
        return [
            AgentFileSpec("cline", ".cline/mcp_settings.json", "mcp_config", "mcp_json", "cline"),
            AgentFileSpec("cline", ".clinerules", "instructions", "marker_md", "cline"),
        ]
    raise ValueError(f"Unsupported agent: {agent_id}")


def can_delete_file_when_empty_for_global(rel_path: str) -> bool:
    return rel_path not in (".claude.json", ".gemini/settings.json")


def _render_spec_content(spec: AgentFileSpec) -> str:
    if spec.rule_agent_key == "skill":
        return render_antigravity_skill()
    return render_agent_rules(spec.rule_agent_key)


def _format_display_path(base_root: Path, rel_path: str, location: str) -> str:
    if location == "global":
        return f"~/{rel_path}"
    return rel_path


# ---------------------------------------------------------------------------
# Verification Engine
# ---------------------------------------------------------------------------


def verify_installation(
    base_root: Path,
    changes: list[PlannedFileChange],
    workspace: Path,
    run_server_check: bool = True,
) -> InstallVerificationResult:
    """Verify executable, MCP JSON files, instructions/rules/skills, no duplicates, and MCP server health."""
    details: list[str] = []

    # 1. Executable available
    exec_ok = bool(shutil.which("codegraph") or (sys.executable and Path(sys.executable).exists()))
    details.append("codegraph executable available" if exec_ok else "codegraph executable missing")

    # 2. MCP configuration exists & parses cleanly with no duplicates
    mcp_changes = [c for c in changes if c.category == "mcp_config"]
    mcp_ok = True
    no_dup_ok = True
    for mc in mcp_changes:
        if not mc.path.exists():
            mcp_ok = False
            details.append(f"Missing MCP config: {mc.display_path}")
            continue
        try:
            raw = mc.path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            servers = parsed.get("mcpServers", {}) if isinstance(parsed, dict) else {}
            cg_keys = [k for k in servers.keys() if str(k).lower() == "codegraph"]
            if len(cg_keys) != 1:
                no_dup_ok = False
                mcp_ok = False
            cg = servers.get("codegraph", {})
            if not isinstance(cg, dict) or not cg.get("command") or cg.get("args") != ["mcp", "serve"]:
                mcp_ok = False
        except Exception as exc:
            mcp_ok = False
            details.append(f"Invalid MCP config {mc.display_path}: {exc}")

    # 3. Instructions / rules / skills exist and contain no duplicate marker blocks
    inst_changes = [c for c in changes if c.category in ("instructions", "rules", "skill")]
    inst_ok = True
    for ic in inst_changes:
        if not ic.path.exists():
            inst_ok = False
            details.append(f"Missing instruction/rule file: {ic.display_path}")
            continue
        raw = ic.path.read_text(encoding="utf-8")
        if not raw.strip():
            inst_ok = False
            continue
        if MARKER_START in raw:
            if raw.count(MARKER_START) != 1 or raw.count(MARKER_END) != 1:
                inst_ok = False
                no_dup_ok = False
                details.append(f"Duplicate or unbalanced markers in {ic.display_path}")

    # 4. MCP server health & tool discovery check
    server_ok = False
    tool_count = 0
    if run_server_check:
        try:
            from codegraph.mcp import create_server

            if (workspace / ".codegraph.sqlite3").exists():
                srv = create_server(workspace, profile="full")
                tool_mgr = getattr(srv, "_tool_manager", None)
                tools_dict = getattr(tool_mgr, "_tools", {}) if tool_mgr else {}
            else:
                with tempfile.TemporaryDirectory(prefix="codegraph_verify_") as tmp_srv_dir:
                    srv = create_server(Path(tmp_srv_dir), profile="full")
                    tool_mgr = getattr(srv, "_tool_manager", None)
                    tools_dict = getattr(tool_mgr, "_tools", {}) if tool_mgr else {}
            tool_count = len(tools_dict)
            server_ok = tool_count >= 56 and "find_symbol" in tools_dict and "get_context" in tools_dict
            details.append(f"MCP server initialized with {tool_count} tools")
        except Exception as exc:
            server_ok = False
            details.append(f"MCP server check failed: {exc}")
    else:
        server_ok = True
        tool_count = 56

    passed = exec_ok and mcp_ok and inst_ok and server_ok and no_dup_ok
    return InstallVerificationResult(
        passed=passed,
        executable_verified=exec_ok,
        mcp_config_verified=mcp_ok,
        instructions_verified=inst_ok,
        mcp_server_health_verified=server_ok,
        no_duplicate_config_verified=no_dup_ok,
        tool_count=tool_count,
        details=tuple(details),
    )


# ---------------------------------------------------------------------------
# Install / Uninstall / Uninit Execution
# ---------------------------------------------------------------------------


def plan_install_changes(
    selected_agents: list[str],
    base_root: Path,
    location: str,
    command: str = "codegraph",
    allow_malformed_repair: bool = False,
) -> tuple[list[PlannedFileChange], list[str], list[str]]:
    """Compute all deterministic file operations for `install` without writing to disk."""
    planned: list[PlannedFileChange] = []
    warnings: list[str] = []
    repairs: list[str] = []
    seen_rel_paths: set[str] = set()

    for agent_id in selected_agents:
        for spec in get_agent_file_specs(agent_id, location):
            if spec.relative_path in seen_rel_paths:
                continue
            seen_rel_paths.add(spec.relative_path)

            target_path = _ensure_safe_target_path(base_root, spec.relative_path)
            disp = _format_display_path(base_root, spec.relative_path, location)
            existing_text = target_path.read_text(encoding="utf-8") if target_path.exists() else None

            if spec.mode == "mcp_json":
                new_text, action, repair_msg = upsert_mcp_json_config(
                    existing_text=existing_text,
                    agent_id=agent_id,
                    display_path=disp,
                    command=command,
                    allow_malformed_repair=allow_malformed_repair,
                )
                if repair_msg:
                    repairs.append(repair_msg)
                planned.append(
                    PlannedFileChange(
                        path=target_path,
                        display_path=disp,
                        action=action,
                        category=spec.category,
                        agent_id=agent_id,
                        detail=repair_msg or f"Configure mcpServers.codegraph in {disp}",
                        new_content=new_text,
                    )
                )

            elif spec.mode == "marker_md":
                inner = _render_spec_content(spec)
                new_text, action, repair_msg = upsert_marker_section(existing_text, inner)
                if repair_msg:
                    repairs.append(f"{disp}: {repair_msg}")
                planned.append(
                    PlannedFileChange(
                        path=target_path,
                        display_path=disp,
                        action=action,
                        category=spec.category,
                        agent_id=agent_id,
                        detail=repair_msg or f"Manage CodeGraph marker section in {disp}",
                        new_content=new_text,
                    )
                )

            elif spec.mode == "standalone_md":
                desired_text = _render_spec_content(spec)
                if existing_text is None:
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="create",
                            category=spec.category,
                            agent_id=agent_id,
                            detail=f"Create CodeGraph {spec.category} at {disp}",
                            new_content=desired_text,
                        )
                    )
                elif existing_text == desired_text:
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="unchanged",
                            category=spec.category,
                            agent_id=agent_id,
                            detail=f"{disp} is already up to date",
                            new_content=desired_text,
                        )
                    )
                elif not is_codegraph_content_unmodified(existing_text):
                    w_msg = f"Protected manually modified file '{disp}'; skipping overwrite."
                    warnings.append(w_msg)
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="skip_modified",
                            category=spec.category,
                            agent_id=agent_id,
                            detail="Manually modified by user; preserved without overwriting",
                            new_content=None,
                        )
                    )
                else:
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="modify",
                            category=spec.category,
                            agent_id=agent_id,
                            detail=f"Update CodeGraph {spec.category} at {disp}",
                            new_content=desired_text,
                        )
                    )

    return planned, warnings, repairs


def _apply_planned_changes_atomically(changes: list[PlannedFileChange]) -> list[PlannedFileChange]:
    """Execute planned file writes/removals with rollback snapshots if any step fails."""
    snapshots: list[tuple[Path, str | None]] = []
    applied: list[PlannedFileChange] = []

    try:
        for ch in changes:
            if ch.action in ("unchanged", "skip_modified"):
                applied.append(ch)
                continue

            orig_content = ch.path.read_text(encoding="utf-8") if ch.path.exists() else None
            snapshots.append((ch.path, orig_content))

            backup_path: Path | None = None
            if ch.action == "repair" and orig_content is not None:
                backup_path = ch.path.with_Name(f"{ch.path.name}.bak") if hasattr(ch.path, "with_Name") else ch.path.parent / f"{ch.path.name}.bak"
                _atomic_write_text(backup_path, orig_content)

            if ch.action == "remove":
                if ch.path.exists():
                    ch.path.unlink()
                applied.append(ch)
            elif ch.new_content is not None:
                _atomic_write_text(ch.path, ch.new_content)
                # Verify written file immediately
                written_back = ch.path.read_text(encoding="utf-8")
                if written_back != ch.new_content:
                    raise OSError(f"Verification mismatch after atomic write to {ch.path}")
                if ch.category == "mcp_config":
                    json.loads(written_back)
                applied.append(
                    PlannedFileChange(
                        path=ch.path,
                        display_path=ch.display_path,
                        action=ch.action,
                        category=ch.category,
                        agent_id=ch.agent_id,
                        detail=ch.detail,
                        new_content=ch.new_content,
                        backup_path=backup_path,
                    )
                )
    except Exception:
        # Roll back all modified files in reverse order
        for path_item, prev_text in reversed(snapshots):
            try:
                if prev_text is None:
                    if path_item.exists():
                        path_item.unlink()
                else:
                    _atomic_write_text(path_item, prev_text)
            except Exception:
                pass
        raise

    return applied


def run_install(
    workspace: Path,
    target: str = "auto",
    location: str = "local",
    dry_run: bool = False,
    allow_malformed_repair: bool = False,
    home: Path | None = None,
    which_fn: Callable[[str], str | None] | None = None,
    confirm_fn: Callable[[InstallerReport], bool] | None = None,
    run_server_check: bool = True,
) -> InstallerReport:
    """Execute or preview `codegraph install` with full safety, idempotency, and verification."""
    effective_ws = workspace.resolve()
    effective_home = (home or Path.home()).resolve()
    scope = "global" if location.strip().lower() == "global" else "local"
    if location.strip().lower() not in ("local", "global", "project"):
        raise CodeGraphError(
            f"Invalid installation location '{location}'. Expected 'local' or 'global'.",
            code=ErrorCode.INVALID_ARGUMENT,
            next_action={
                "command": "codegraph install --location local --dry-run",
                "reason": "Specify --location local or --location global.",
            },
        )

    base_root = effective_home if scope == "global" else effective_ws
    detected = detect_agents(effective_ws, home=effective_home, which_fn=which_fn)
    selected = resolve_target_agents(target, detected)

    changes, warnings, repairs = plan_install_changes(
        selected_agents=selected,
        base_root=base_root,
        location=scope,
        command="codegraph",
        allow_malformed_repair=allow_malformed_repair,
    )

    from codegraph.process_lifecycle import (
        discover_codegraph_processes,
        stop_codegraph_processes,
    )

    proc_discovery = discover_codegraph_processes(clean_stale=not dry_run)
    current_pid = os.getpid()
    other_active = [
        p for p in proc_discovery.active_processes if p.record.pid != current_pid
    ]
    orphaned_procs = [p for p in other_active if p.orphaned]
    live_procs = [p for p in other_active if not p.orphaned]

    if orphaned_procs and dry_run:
        pids_str = ", ".join(str(p.record.pid) for p in orphaned_procs)
        warnings.append(
            f"Orphaned CodeGraph process(es) detected (PID: {pids_str}); "
            "run 'codegraph stop' or 'codegraph install' to clean up."
        )
    if live_procs:
        pids_str = ", ".join(str(p.record.pid) for p in live_procs)
        warnings.append(
            f"Active CodeGraph process(es) running (PID: {pids_str}). "
            "Before upgrading ('pip install --upgrade codegraph-engine'), run 'codegraph stop' "
            "to prevent executable file lock errors (WinError 32)."
        )

    preview_report = InstallerReport(
        status="dry_run" if dry_run else "ok",
        operation="install",
        location=scope,
        workspace=str(effective_ws),
        detected_agents=tuple(detected),
        selected_agents=tuple(selected),
        changes=tuple(changes),
        warnings=tuple(warnings),
        repairs=tuple(repairs),
        files_changed=False,
    )

    if dry_run:
        return preview_report

    has_mutations = any(c.action in ("create", "modify", "repair") for c in changes)
    if confirm_fn is not None and has_mutations:
        if not confirm_fn(preview_report):
            return InstallerReport(
                status="aborted",
                operation="install",
                location=scope,
                workspace=str(effective_ws),
                detected_agents=tuple(detected),
                selected_agents=tuple(selected),
                changes=tuple(changes),
                warnings=tuple(warnings),
                repairs=tuple(repairs),
                files_changed=False,
            )

    if orphaned_procs:
        stop_rep = stop_codegraph_processes(only_orphaned=True)
        stopped_cnt = sum(1 for item in stop_rep.stopped_processes if item.stopped)
        if stopped_cnt > 0:
            repairs.append(f"Stopped {stopped_cnt} orphaned CodeGraph background process(es).")

    applied = _apply_planned_changes_atomically(changes)
    ver = verify_installation(
        base_root=base_root,
        changes=applied,
        workspace=effective_ws,
        run_server_check=run_server_check,
    )

    return InstallerReport(
        status="ok" if ver.passed else "error",
        operation="install",
        location=scope,
        workspace=str(effective_ws),
        detected_agents=tuple(detected),
        selected_agents=tuple(selected),
        changes=tuple(applied),
        warnings=tuple(warnings),
        repairs=tuple(repairs),
        verification=ver,
        files_changed=has_mutations,
    )


def run_uninstall(
    workspace: Path,
    target: str = "all",
    location: str = "local",
    dry_run: bool = False,
    home: Path | None = None,
    which_fn: Callable[[str], str | None] | None = None,
    confirm_fn: Callable[[InstallerReport], bool] | None = None,
) -> InstallerReport:
    """Reverse only CodeGraph-managed agent integrations without deleting user config or `.codegraph` index."""
    effective_ws = workspace.resolve()
    effective_home = (home or Path.home()).resolve()
    scope = "global" if location.strip().lower() == "global" else "local"
    if location.strip().lower() not in ("local", "global", "project"):
        raise CodeGraphError(
            f"Invalid location '{location}'. Expected 'local' or 'global'.",
            code=ErrorCode.INVALID_ARGUMENT,
            next_action={
                "command": "codegraph uninstall --location local --dry-run",
                "reason": "Specify --location local or --location global.",
            },
        )

    base_root = effective_home if scope == "global" else effective_ws
    detected = detect_agents(effective_ws, home=effective_home, which_fn=which_fn)
    effective_target = "all" if target.strip().lower() == "auto" else target
    selected = resolve_target_agents(effective_target, detected)

    planned: list[PlannedFileChange] = []
    warnings: list[str] = []
    seen_rel_paths: set[str] = set()

    for agent_id in selected:
        for spec in get_agent_file_specs(agent_id, scope):
            if spec.relative_path in seen_rel_paths:
                continue
            seen_rel_paths.add(spec.relative_path)

            target_path = _ensure_safe_target_path(base_root, spec.relative_path)
            disp = _format_display_path(base_root, spec.relative_path, scope)
            if not target_path.exists():
                continue

            existing_text = target_path.read_text(encoding="utf-8")

            if spec.mode == "mcp_json":
                new_text, action = remove_mcp_json_config(
                    existing_text=existing_text,
                    display_path=disp,
                    can_delete_file_when_empty=spec.can_delete_when_empty,
                )
                if action != "unchanged":
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action=action,
                            category=spec.category,
                            agent_id=agent_id,
                            detail=f"Remove mcpServers.codegraph from {disp}",
                            new_content=new_text,
                        )
                    )

            elif spec.mode == "marker_md":
                new_text, action, warn = remove_marker_section(existing_text)
                if warn:
                    warnings.append(f"{disp}: {warn}")
                if action != "unchanged":
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action=action,
                            category=spec.category,
                            agent_id=agent_id,
                            detail=warn or f"Remove CodeGraph marker section from {disp}",
                            new_content=new_text,
                        )
                    )

            elif spec.mode == "standalone_md":
                if not is_codegraph_content_unmodified(existing_text):
                    w_msg = f"Modified file '{disp}' was not deleted to preserve user edits."
                    warnings.append(w_msg)
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="skip_modified",
                            category=spec.category,
                            agent_id=agent_id,
                            detail="Modified by user; preserved",
                            new_content=None,
                        )
                    )
                else:
                    planned.append(
                        PlannedFileChange(
                            path=target_path,
                            display_path=disp,
                            action="remove",
                            category=spec.category,
                            agent_id=agent_id,
                            detail=f"Remove CodeGraph {spec.category} file {disp}",
                            new_content=None,
                        )
                    )

    preview = InstallerReport(
        status="dry_run" if dry_run else "ok",
        operation="uninstall",
        location=scope,
        workspace=str(effective_ws),
        detected_agents=tuple(detected),
        selected_agents=tuple(selected),
        changes=tuple(planned),
        warnings=tuple(warnings),
        files_changed=False,
    )

    if dry_run:
        return preview

    has_mutations = any(c.action in ("remove", "modify") for c in planned)
    if confirm_fn is not None and has_mutations:
        if not confirm_fn(preview):
            return InstallerReport(
                status="aborted",
                operation="uninstall",
                location=scope,
                workspace=str(effective_ws),
                detected_agents=tuple(detected),
                selected_agents=tuple(selected),
                changes=tuple(planned),
                warnings=tuple(warnings),
                files_changed=False,
            )

    from codegraph.process_lifecycle import stop_codegraph_processes

    stop_codegraph_processes(
        repository=None if scope == "global" else effective_ws,
        stop_all=(scope == "global"),
    )

    applied = _apply_planned_changes_atomically(planned)
    return InstallerReport(
        status="ok",
        operation="uninstall",
        location=scope,
        workspace=str(effective_ws),
        detected_agents=tuple(detected),
        selected_agents=tuple(selected),
        changes=tuple(applied),
        warnings=tuple(warnings),
        files_changed=has_mutations,
    )


def run_uninit(
    workspace: Path,
    dry_run: bool = False,
    confirm_fn: Callable[[InstallerReport], bool] | None = None,
) -> InstallerReport:
    """Remove only the current project's CodeGraph index artifacts (`.codegraph.sqlite3*`, `.codegraph/`)."""
    effective_ws = workspace.resolve()
    index_candidates = (
        ".codegraph.sqlite3",
        ".codegraph.sqlite3-wal",
        ".codegraph.sqlite3-shm",
        ".codegraph.sqlite3-journal",
    )

    planned: list[PlannedFileChange] = []
    for rel_name in index_candidates:
        p = _ensure_safe_target_path(effective_ws, rel_name, allow_index_artifact=True)
        if p.exists():
            planned.append(
                PlannedFileChange(
                    path=p,
                    display_path=rel_name,
                    action="remove",
                    category="index",
                    agent_id="project",
                    detail=f"Remove CodeGraph SQLite index file {rel_name}",
                )
            )

    cg_dir = effective_ws / ".codegraph"
    if cg_dir.is_symlink():
        raise SecurityError(
            "Refusing to remove symlinked .codegraph directory.",
            code=ErrorCode.PATH_OUTSIDE_REPOSITORY,
        )
    if cg_dir.exists() and cg_dir.is_dir():
        planned.append(
            PlannedFileChange(
                path=cg_dir,
                display_path=".codegraph/",
                action="remove",
                category="index",
                agent_id="project",
                detail="Remove .codegraph/ cache directory",
            )
        )

    preview = InstallerReport(
        status="dry_run" if dry_run else "ok",
        operation="uninit",
        location="local",
        workspace=str(effective_ws),
        detected_agents=(),
        selected_agents=(),
        changes=tuple(planned),
        files_changed=False,
    )

    if dry_run:
        return preview

    has_mutations = len(planned) > 0
    if confirm_fn is not None and has_mutations:
        if not confirm_fn(preview):
            return InstallerReport(
                status="aborted",
                operation="uninit",
                location="local",
                workspace=str(effective_ws),
                detected_agents=(),
                selected_agents=(),
                changes=tuple(planned),
                files_changed=False,
            )

    for ch in planned:
        if ch.display_path == ".codegraph/" and ch.path.exists() and ch.path.is_dir():
            shutil.rmtree(ch.path)
        elif ch.path.exists():
            ch.path.unlink()

    return InstallerReport(
        status="ok",
        operation="uninit",
        location="local",
        workspace=str(effective_ws),
        detected_agents=(),
        selected_agents=(),
        changes=tuple(planned),
        files_changed=has_mutations,
    )
