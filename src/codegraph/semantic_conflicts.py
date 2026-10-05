"""Semantic and Contract Merge Conflict Engine.

Analyzes two branches or revisions to identify semantic/contractual merge conflicts
that standard Git text-based merge algorithms cannot detect:
- A symbol's signature/parameters changed in one branch, but the other branch calls the old signature.
- A symbol was deleted/renamed in one branch, but the other branch adds new references/calls to it.
- A route handler or DB model changed in one branch, breaking endpoints/queries in the other.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.indexing.parser import parse
from codegraph.indexing.scanner import LANGUAGES
from codegraph.structural_diff import (
    _get_file_content_at_ref,
    _run_git,
    compare_revisions,
)


class SemanticConflictType(StrEnum):
    CALL_SIGNATURE_MISMATCH = "CALL_SIGNATURE_MISMATCH"
    DELETED_SYMBOL_REFERENCED = "DELETED_SYMBOL_REFERENCED"
    ROUTE_HANDLER_MISMATCH = "ROUTE_HANDLER_MISMATCH"
    UNRESOLVED_IMPORT = "UNRESOLVED_IMPORT"


class SemanticConflictSeverity(StrEnum):
    ERROR = "ERROR"       # Definite runtime failure or missing symbol
    WARNING = "WARNING"   # Plausible contract drift or signature change


@dataclass
class SemanticConflict:
    conflict_type: SemanticConflictType
    symbol: str
    base_file: str
    head_file: str
    severity: SemanticConflictSeverity
    description: str
    base_evidence: str
    head_evidence: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "conflict_type": self.conflict_type.value,
            "symbol": self.symbol,
            "base_file": self.base_file,
            "head_file": self.head_file,
            "severity": self.severity.value,
            "description": self.description,
            "base_evidence": self.base_evidence,
            "head_evidence": self.head_evidence,
            "line": self.line,
        }


@dataclass
class SemanticConflictReport:
    base_branch: str
    head_branch: str
    has_conflicts: bool
    total_conflicts: int
    conflicts: list[SemanticConflict] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "has_conflicts": self.has_conflicts,
            "total_conflicts": self.total_conflicts,
            "conflicts": [c.as_dict() for c in self.conflicts],
            "summary": self.summary,
        }


def detect_semantic_conflicts(
    repository: Path,
    base_branch: str = "main",
    head_branch: str = "HEAD",
    con: sqlite3.Connection | None = None,
) -> SemanticConflictReport:
    """Detect semantic and contract conflicts between two branches using 3-way merge-base analysis."""
    # Fast path: identical branches have zero conflicts
    if base_branch == head_branch:
        return SemanticConflictReport(
            base_branch=base_branch,
            head_branch=head_branch,
            has_conflicts=False,
            total_conflicts=0,
            summary=f"Branches {base_branch} and {head_branch} are identical; 0 semantic conflicts.",
        )

    # 1. Resolve merge base
    merge_base_raw = _run_git(repository, "merge-base", base_branch, head_branch)
    merge_base = merge_base_raw.strip() if merge_base_raw else base_branch

    # 2. What changed on base vs merge-base, and what changed on head vs merge-base
    base_diff = compare_revisions(repository, base=merge_base, head=base_branch, con=con)
    head_diff = compare_revisions(repository, base=merge_base, head=head_branch, con=con)

    conflicts: list[SemanticConflict] = []
    seen_conflict_keys: set[str] = set()

    # Case A: Symbols removed or modified on base, but invoked on head
    base_removed = {s.name: s for s in base_diff.removed_symbols}
    base_modified = {s.name: s for s in base_diff.changed_symbols}

    for m_path in (head_diff.modified_files + head_diff.added_files):
        ext = Path(m_path).suffix.lower()
        lang = LANGUAGES.get(ext)
        if not lang:
            continue

        head_content = _get_file_content_at_ref(repository, head_branch, m_path)
        if not head_content:
            continue

        try:
            parsed = parse(head_content, lang, m_path)
        except Exception:
            continue

        for call in parsed.calls:
            target = call.callee
            if not target:
                continue

            if target in base_removed:
                rem_s = base_removed[target]
                c_key = f"A_DEL:{target}:{m_path}:{call.line}"
                if c_key not in seen_conflict_keys:
                    seen_conflict_keys.add(c_key)
                    conflicts.append(
                        SemanticConflict(
                            conflict_type=SemanticConflictType.DELETED_SYMBOL_REFERENCED,
                            symbol=target,
                            base_file=rem_s.path,
                            head_file=m_path,
                            severity=SemanticConflictSeverity.ERROR,
                            description=f"Branch '{head_branch}' invokes '{target}' at {m_path}:{call.line}, but symbol was removed in '{base_branch}' ({rem_s.path}).",
                            base_evidence=f"Symbol '{target}' removed in '{base_branch}'",
                            head_evidence=f"Call site {m_path}:{call.line} -> {target}",
                            line=call.line,
                        )
                    )
            elif target in base_modified:
                mod_s = base_modified[target]
                c_key = f"A_MOD:{target}:{m_path}:{call.line}"
                if c_key not in seen_conflict_keys:
                    seen_conflict_keys.add(c_key)
                    conflicts.append(
                        SemanticConflict(
                            conflict_type=SemanticConflictType.CALL_SIGNATURE_MISMATCH,
                            symbol=target,
                            base_file=mod_s.path,
                            head_file=m_path,
                            severity=SemanticConflictSeverity.WARNING,
                            description=f"Branch '{head_branch}' invokes '{target}' at {m_path}:{call.line}, whose body or signature was modified in '{base_branch}' ({mod_s.path}).",
                            base_evidence=f"Symbol '{target}' modified in '{base_branch}'",
                            head_evidence=f"Call site at {m_path}:{call.line}",
                            line=call.line,
                        )
                    )

        for imp in parsed.imports:
            target_imp = imp.imported_name or imp.name
            if target_imp and target_imp in base_removed:
                rem_s = base_removed[target_imp]
                c_key = f"A_IMP:{target_imp}:{m_path}:{imp.line}"
                if c_key not in seen_conflict_keys:
                    seen_conflict_keys.add(c_key)
                    conflicts.append(
                        SemanticConflict(
                            conflict_type=SemanticConflictType.UNRESOLVED_IMPORT,
                            symbol=target_imp,
                            base_file=rem_s.path,
                            head_file=m_path,
                            severity=SemanticConflictSeverity.ERROR,
                            description=f"Branch '{head_branch}' imports '{target_imp}' at {m_path}:{imp.line}, which was removed in '{base_branch}' ({rem_s.path}).",
                            base_evidence=f"Symbol '{target_imp}' removed in '{base_branch}'",
                            head_evidence=f"Import statement at {m_path}:{imp.line}",
                            line=imp.line,
                        )
                    )

        for r in parsed.routes:
            handler = r.handler_name
            if handler and handler in base_removed:
                rem_s = base_removed[handler]
                c_key = f"A_ROUTE:{handler}:{m_path}:{r.line}"
                if c_key not in seen_conflict_keys:
                    seen_conflict_keys.add(c_key)
                    conflicts.append(
                        SemanticConflict(
                            conflict_type=SemanticConflictType.ROUTE_HANDLER_MISMATCH,
                            symbol=handler,
                            base_file=rem_s.path,
                            head_file=m_path,
                            severity=SemanticConflictSeverity.ERROR,
                            description=f"Branch '{head_branch}' registers route '{r.http_method} {r.route_path}' pointing to handler '{handler}', which was deleted in '{base_branch}'.",
                            base_evidence=f"Handler '{handler}' deleted in '{base_branch}'",
                            head_evidence=f"Route '{r.http_method} {r.route_path}' at {m_path}:{r.line}",
                            line=r.line,
                        )
                    )

    # Case B: Symbols removed or modified on head, but invoked on base
    head_removed = {s.name: s for s in head_diff.removed_symbols}
    for b_path in (base_diff.modified_files + base_diff.added_files):
        ext = Path(b_path).suffix.lower()
        lang = LANGUAGES.get(ext)
        if not lang:
            continue

        base_content = _get_file_content_at_ref(repository, base_branch, b_path)
        if not base_content:
            continue

        try:
            parsed = parse(base_content, lang, b_path)
        except Exception:
            continue

        for call in parsed.calls:
            target = call.callee
            if not target:
                continue

            if target in head_removed:
                rem_s = head_removed[target]
                c_key = f"B_DEL:{target}:{b_path}:{call.line}"
                if c_key not in seen_conflict_keys:
                    seen_conflict_keys.add(c_key)
                    conflicts.append(
                        SemanticConflict(
                            conflict_type=SemanticConflictType.DELETED_SYMBOL_REFERENCED,
                            symbol=target,
                            base_file=b_path,
                            head_file=rem_s.path,
                            severity=SemanticConflictSeverity.ERROR,
                            description=f"Branch '{base_branch}' invokes '{target}' at {b_path}:{call.line}, but symbol was removed in '{head_branch}' ({rem_s.path}).",
                            base_evidence=f"Call site at {b_path}:{call.line}",
                            head_evidence=f"Symbol '{target}' removed in '{head_branch}'",
                            line=call.line,
                        )
                    )

    has_conflicts = len(conflicts) > 0
    summary = (
        f"Detected {len(conflicts)} semantic conflict(s) between {base_branch} and {head_branch}."
        if has_conflicts
        else f"Clean semantic comparison between {base_branch} and {head_branch} (0 semantic conflicts detected)."
    )

    return SemanticConflictReport(
        base_branch=base_branch,
        head_branch=head_branch,
        has_conflicts=has_conflicts,
        total_conflicts=len(conflicts),
        conflicts=conflicts,
        summary=summary,
    )
