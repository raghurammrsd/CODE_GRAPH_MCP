"""Context Freshness Validation Engine.

Validates whether a previously compiled ContextPacket remains valid against
the current repository state or whether it has become STALE or PARTIALLY_STALE.

CRITICAL INVARIANT:
Do NOT invalidate context merely because an unrelated file changed!
A context containing files A/B must remain VALID when an unrelated file Z changes.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.git_state import GitStateReport, get_git_state


class ContextFreshnessStatus(StrEnum):
    VALID = "VALID"                     # None of the files/symbols in the context were modified
    PARTIALLY_STALE = "PARTIALLY_STALE" # Secondary files/tests in context changed, primary target unaffected
    STALE = "STALE"                     # Primary targets or core symbols in context were modified or removed
    UNKNOWN = "UNKNOWN"                 # Cannot verify (e.g. no git history or commit not found)


@dataclass
class ContextFreshnessReport:
    status: ContextFreshnessStatus
    base_commit: str | None
    current_head: str | None
    repository_dirty: bool
    context_files: list[str]
    changed_relevant_files: list[str] = field(default_factory=list)
    unrelated_changed_files: list[str] = field(default_factory=list)
    invalidated_symbols: list[str] = field(default_factory=list)
    reason: str = ""
    recommended_action: str = "NONE"  # "NONE" | "RECOMPILE_CONTEXT" | "REFRESH_PERIPHERAL"

    @property
    def is_valid(self) -> bool:
        return self.status == ContextFreshnessStatus.VALID

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "base_commit": self.base_commit,
            "current_head": self.current_head,
            "repository_dirty": self.repository_dirty,
            "context_files": self.context_files,
            "changed_relevant_files": self.changed_relevant_files,
            "unrelated_changed_files": self.unrelated_changed_files,
            "invalidated_symbols": self.invalidated_symbols,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
        }


def _run_git(repository: Path, *args: str, timeout: int = 10) -> str | None:
    for arg in args:
        if any(c in arg for c in (";", "|", "&", "`", "$", "\n", "\r")):
            return None
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.stdout if res.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


_REF_PATTERN = re.compile(r"^[A-Za-z0-9_.~^/-]{1,100}$")

_COMMIT_DIFF_FILES_CACHE: dict[tuple[str, str, str], tuple[str, ...]] = {}


def _get_cached_commit_diff_files(repository: Path, base: str, head: str) -> tuple[str, ...] | None:
    """Cache immutable diff between two commits to avoid repeated subprocess invocations."""
    cache_key = (str(repository), base, head)
    if cache_key in _COMMIT_DIFF_FILES_CACHE:
        return _COMMIT_DIFF_FILES_CACHE[cache_key]
    diff_raw = _run_git(repository, "diff", "--name-only", base, head)
    if diff_raw is None:
        return None
    files = tuple(line.strip() for line in diff_raw.splitlines() if line.strip())
    if len(_COMMIT_DIFF_FILES_CACHE) > 500:
        _COMMIT_DIFF_FILES_CACHE.clear()
    _COMMIT_DIFF_FILES_CACHE[cache_key] = files
    return files


def check_context_freshness(
    context_packet: dict[str, Any] | Any,
    repository: Path,
    con: sqlite3.Connection | None = None,
    state: GitStateReport | None = None,
) -> ContextFreshnessReport:
    """Evaluate whether previously generated ContextPacket is still valid against repository state.

    Guarantees:
    - Context remains VALID when changes occur only in unrelated files.
    - Becomes PARTIALLY_STALE if secondary files (e.g. related tests) changed.
    - Becomes STALE if primary target symbols or core files changed.
    """
    # 1. Normalize packet data
    packet_dict: dict[str, Any]
    if hasattr(context_packet, "model_dump"):
        packet_dict = context_packet.model_dump()
    elif hasattr(context_packet, "as_dict"):
        packet_dict = context_packet.as_dict()
    elif isinstance(context_packet, dict):
        packet_dict = context_packet
    else:
        return ContextFreshnessReport(
            status=ContextFreshnessStatus.UNKNOWN,
            base_commit=None,
            current_head=None,
            repository_dirty=False,
            context_files=[],
            reason="Invalid context packet data type.",
            recommended_action="RECOMPILE_CONTEXT",
        )

    # 2. Extract base commit from packet
    meta = packet_dict.get("metadata", {}) if isinstance(packet_dict.get("metadata"), dict) else {}
    base_commit = (
        packet_dict.get("current_commit")
        or packet_dict.get("indexed_commit")
        or meta.get("indexed_commit")
        or meta.get("current_commit")
    )
    if isinstance(base_commit, str):
        base_commit = base_commit.strip()

    # 3. Collect all files and symbols mentioned in context
    context_files: set[str] = set()
    core_files: set[str] = set()
    peripheral_files: set[str] = set()
    context_symbols: set[str] = set()
    primary_targets: set[str] = set()

    # Files section
    for f_obj in packet_dict.get("files", []):
        f_path: str | None = None
        if isinstance(f_obj, str):
            f_path = f_obj
        elif isinstance(f_obj, dict):
            val = f_obj.get("file") or f_obj.get("path")
            f_path = str(val) if val else None
        else:
            val = getattr(f_obj, "file", getattr(f_obj, "path", None))
            f_path = str(val) if val else None
        if f_path:
            context_files.add(f_path)
            core_files.add(f_path)

    # Symbols section
    for s_obj in packet_dict.get("symbols", []):
        s_file = s_obj.get("file") if isinstance(s_obj, dict) else getattr(s_obj, "file", None)
        s_name = s_obj.get("symbol") if isinstance(s_obj, dict) else getattr(s_obj, "symbol", None)
        if s_file:
            context_files.add(str(s_file))
            core_files.add(str(s_file))
        if s_name:
            context_symbols.add(str(s_name))

    # Evidence section
    for e_obj in packet_dict.get("evidence", []):
        e_file = e_obj.get("file") if isinstance(e_obj, dict) else getattr(e_obj, "file", None)
        if e_file:
            context_files.add(str(e_file))

    # Tests section (treated as peripheral)
    for t_obj in packet_dict.get("tests", []):
        t_file = t_obj.get("file") if isinstance(t_obj, dict) else getattr(t_obj, "file", None)
        if t_file:
            context_files.add(str(t_file))
            if str(t_file) not in core_files:
                peripheral_files.add(str(t_file))

    # Target info
    target_obj = packet_dict.get("target")
    if isinstance(target_obj, dict):
        t_file = target_obj.get("file")
        if t_file:
            context_files.add(str(t_file))
            core_files.add(str(t_file))
        t_sym = target_obj.get("symbol")
        if t_sym:
            primary_targets.add(str(t_sym))

    # 4. Check Git state
    git_state = state if state is not None else get_git_state(repository, con=con)
    if not git_state.is_git:
        return ContextFreshnessReport(
            status=ContextFreshnessStatus.UNKNOWN,
            base_commit=base_commit,
            current_head=None,
            repository_dirty=False,
            context_files=sorted(context_files),
            reason="Not a git repository.",
            recommended_action="NONE",
        )

    current_head = git_state.current_head
    state = git_state

    # 5. Determine which files changed since base_commit (including working tree)
    all_changed_files: set[str] = set()

    is_at_head = (
        not base_commit
        or base_commit == "HEAD"
        or (current_head and (base_commit == current_head or current_head.startswith(base_commit)))
    )

    if is_at_head:
        # Fast path: context was generated at current HEAD.
        # Only working tree uncommitted changes can invalidate it.
        wt = state.working_tree
        if not wt.is_dirty:
            # Absolute zero changes anywhere in repository!
            return ContextFreshnessReport(
                status=ContextFreshnessStatus.VALID,
                base_commit=base_commit,
                current_head=current_head,
                repository_dirty=False,
                context_files=sorted(context_files),
                changed_relevant_files=[],
                unrelated_changed_files=[],
                invalidated_symbols=[],
                reason="Context is completely fresh. Repository state is unchanged.",
                recommended_action="NONE",
            )
        all_changed_files.update(wt.modified_files)
        all_changed_files.update(wt.staged_files)
        all_changed_files.update(wt.deleted_files)
        all_changed_files.update(wt.untracked_files)
    elif base_commit and _REF_PATTERN.match(base_commit):
        # Diff base_commit against current HEAD using cached immutable diff, then add working tree
        head_ref = current_head or "HEAD"
        commit_diff = _get_cached_commit_diff_files(repository, base_commit, head_ref)
        if commit_diff is not None:
            all_changed_files.update(commit_diff)
            wt = state.working_tree
            all_changed_files.update(wt.modified_files)
            all_changed_files.update(wt.staged_files)
            all_changed_files.update(wt.deleted_files)
            all_changed_files.update(wt.untracked_files)
        else:
            # Fallback direct diff
            diff_raw = _run_git(repository, "diff", "--name-only", base_commit)
            if diff_raw is not None:
                for line in diff_raw.splitlines():
                    if line.strip():
                        all_changed_files.add(line.strip())
                all_changed_files.update(state.working_tree.untracked_files)
            else:
                return ContextFreshnessReport(
                    status=ContextFreshnessStatus.UNKNOWN,
                    base_commit=base_commit,
                    current_head=current_head,
                    repository_dirty=state.working_tree.is_dirty,
                    context_files=sorted(context_files),
                    reason=f"Base commit {base_commit} not reachable in git repository.",
                    recommended_action="RECOMPILE_CONTEXT",
                )
    else:
        wt = state.working_tree
        all_changed_files.update(wt.modified_files)
        all_changed_files.update(wt.staged_files)
        all_changed_files.update(wt.deleted_files)
        all_changed_files.update(wt.untracked_files)

    # 6. Intersect changed files with context files
    changed_relevant = sorted(all_changed_files.intersection(context_files))
    unrelated_changed = sorted(all_changed_files - context_files)

    # 7. Evaluate Freshness
    if not changed_relevant:
        # None of the files in context were modified!
        if unrelated_changed:
            reason = f"Context remains VALID. {len(unrelated_changed)} unrelated file(s) changed in repository, but none belong to this context packet."
        else:
            reason = "Context is completely fresh. Repository state is unchanged."
        return ContextFreshnessReport(
            status=ContextFreshnessStatus.VALID,
            base_commit=base_commit,
            current_head=current_head,
            repository_dirty=state.working_tree.is_dirty,
            context_files=sorted(context_files),
            changed_relevant_files=[],
            unrelated_changed_files=unrelated_changed,
            invalidated_symbols=[],
            reason=reason,
            recommended_action="NONE",
        )

    # Some relevant files did change! Check if they are core or peripheral
    invalidated_symbols: list[str] = []
    core_hit = False

    for crf in changed_relevant:
        if crf in core_files or crf not in peripheral_files:
            core_hit = True

        # Find which symbols were in this file
        for s_obj in packet_dict.get("symbols", []):
            s_file = s_obj.get("file") if isinstance(s_obj, dict) else getattr(s_obj, "file", None)
            s_name = s_obj.get("symbol") if isinstance(s_obj, dict) else getattr(s_obj, "symbol", None)
            if s_file == crf and s_name:
                invalidated_symbols.append(str(s_name))

    # Check if primary targets were hit
    primary_hit = any(t in invalidated_symbols for t in primary_targets)

    if core_hit or primary_hit:
        return ContextFreshnessReport(
            status=ContextFreshnessStatus.STALE,
            base_commit=base_commit,
            current_head=current_head,
            repository_dirty=state.working_tree.is_dirty,
            context_files=sorted(context_files),
            changed_relevant_files=changed_relevant,
            unrelated_changed_files=unrelated_changed,
            invalidated_symbols=sorted(set(invalidated_symbols)),
            reason=f"Context is STALE. Core file(s) ({', '.join(changed_relevant[:3])}) were modified or deleted.",
            recommended_action="RECOMPILE_CONTEXT",
        )
    else:
        return ContextFreshnessReport(
            status=ContextFreshnessStatus.PARTIALLY_STALE,
            base_commit=base_commit,
            current_head=current_head,
            repository_dirty=state.working_tree.is_dirty,
            context_files=sorted(context_files),
            changed_relevant_files=changed_relevant,
            unrelated_changed_files=unrelated_changed,
            invalidated_symbols=sorted(set(invalidated_symbols)),
            reason=f"Context is PARTIALLY_STALE. Secondary file(s) ({', '.join(changed_relevant[:3])}) were modified, but primary targets remain valid.",
            recommended_action="REFRESH_PERIPHERAL",
        )
