"""Structural Git Diff Engine.

Computes semantic and AST-level differences between Git revisions, branches,
or between working tree and indexed state.

Identifies:
- File-level additions, deletions, modifications, renames/moves
- Symbol-level additions, removals, signature and body modifications
- Relationship-level changes: calls, imports, framework routes, test links, DB models/queries
- Evidence-backed classifications: FACT, POSSIBLE, UNKNOWN
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.indexing.parser import parse
from codegraph.indexing.scanner import LANGUAGES


@dataclass
class RenamedFile:
    old_path: str
    new_path: str
    similarity_score: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "old_path": self.old_path,
            "new_path": self.new_path,
            "similarity_score": self.similarity_score,
        }


@dataclass
class ChangedSymbol:
    name: str
    qualified_name: str
    path: str
    kind: str
    change_type: str  # "ADDED" | "REMOVED" | "MODIFIED" | "MOVED" | "RENAMED"
    old_path: str | None = None
    old_name: str | None = None
    old_line: int | None = None
    new_line: int | None = None
    confidence: str = "FACT"  # FACT | POSSIBLE | UNKNOWN
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "path": self.path,
            "kind": self.kind,
            "change_type": self.change_type,
            "old_path": self.old_path,
            "old_name": self.old_name,
            "old_line": self.old_line,
            "new_line": self.new_line,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class ChangedRelationship:
    relationship_type: str  # "CALLS" | "IMPORTS" | "ROUTES_TO" | "TESTS" | "DB_MUTATION"
    source: str
    target: str
    change_type: str  # "ADDED" | "REMOVED"
    file: str
    confidence: str = "FACT"

    def as_dict(self) -> dict[str, Any]:
        return {
            "relationship_type": self.relationship_type,
            "source": self.source,
            "target": self.target,
            "change_type": self.change_type,
            "file": self.file,
            "confidence": self.confidence,
        }


@dataclass
class ChangedRoute:
    path: str
    method: str
    handler: str
    framework: str
    change_type: str  # "ADDED" | "REMOVED" | "MODIFIED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "handler": self.handler,
            "framework": self.framework,
            "change_type": self.change_type,
        }


@dataclass
class StructuralDiffReport:
    base_ref: str
    head_ref: str
    added_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    renamed_files: list[RenamedFile] = field(default_factory=list)
    added_symbols: list[ChangedSymbol] = field(default_factory=list)
    removed_symbols: list[ChangedSymbol] = field(default_factory=list)
    changed_symbols: list[ChangedSymbol] = field(default_factory=list)
    changed_relationships: list[ChangedRelationship] = field(default_factory=list)
    changed_routes: list[ChangedRoute] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    db_impact: list[dict[str, Any]] = field(default_factory=list)
    total_file_changes: int = 0
    total_symbol_changes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "added_files": self.added_files,
            "deleted_files": self.deleted_files,
            "modified_files": self.modified_files,
            "renamed_files": [r.as_dict() for r in self.renamed_files],
            "added_symbols": [s.as_dict() for s in self.added_symbols],
            "removed_symbols": [s.as_dict() for s in self.removed_symbols],
            "changed_symbols": [s.as_dict() for s in self.changed_symbols],
            "changed_relationships": [r.as_dict() for r in self.changed_relationships],
            "changed_routes": [r.as_dict() for r in self.changed_routes],
            "affected_tests": self.affected_tests,
            "db_impact": self.db_impact,
            "total_file_changes": self.total_file_changes,
            "total_symbol_changes": self.total_symbol_changes,
        }


def _run_git(repository: Path, *args: str, timeout: int = 15) -> str | None:
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


_FILE_CONTENT_AT_REF_CACHE: dict[tuple[str, str, str], str | None] = {}


def _get_file_content_at_ref(repository: Path, ref: str, file_path: str) -> str | None:
    """Read historical or current content of a file at a specific git ref or working tree."""
    if ref == "WORKING_TREE":
        abs_p = repository / file_path
        if abs_p.exists() and abs_p.is_file():
            try:
                return abs_p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return None

    cache_key = (str(repository), ref, file_path)
    if cache_key in _FILE_CONTENT_AT_REF_CACHE:
        return _FILE_CONTENT_AT_REF_CACHE[cache_key]

    # Use git show <ref>:<path>
    raw = _run_git(repository, "show", f"{ref}:{file_path}")
    if len(_FILE_CONTENT_AT_REF_CACHE) > 1000:
        _FILE_CONTENT_AT_REF_CACHE.clear()
    _FILE_CONTENT_AT_REF_CACHE[cache_key] = raw
    return raw


def _get_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return LANGUAGES.get(ext)


_REF_PATTERN = re.compile(r"^[A-Za-z0-9_.~^/-]{1,100}$")


def compare_revisions(
    repository: Path,
    base: str = "HEAD~1",
    head: str = "HEAD",
    con: sqlite3.Connection | None = None,
    max_symbols_per_file: int = 100,
) -> StructuralDiffReport:
    """Compute structural, AST-level difference between two revisions or working tree."""
    if head != "WORKING_TREE" and not _REF_PATTERN.match(head):
        return StructuralDiffReport(base_ref=base, head_ref=head)
    if not _REF_PATTERN.match(base):
        return StructuralDiffReport(base_ref=base, head_ref=head)

    # Identical ref short-circuit (0ms latency)
    if base == head and head != "WORKING_TREE":
        return StructuralDiffReport(base_ref=base, head_ref=head)

    # 1. Get raw diff stats with rename detection
    if head == "WORKING_TREE":
        raw_diff = _run_git(repository, "diff", "-M", "--name-status", base)
    else:
        raw_diff = _run_git(repository, "diff", "-M", "--name-status", base, head)

    if raw_diff is None:
        return StructuralDiffReport(base_ref=base, head_ref=head)

    added_files: list[str] = []
    deleted_files: list[str] = []
    modified_files: list[str] = []
    renamed_files: list[RenamedFile] = []

    for line in raw_diff.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if not parts:
            continue
        status_code = parts[0].strip()
        if status_code.startswith("R") and len(parts) >= 3:
            # Rename: R100 old_path new_path
            score = 1.0
            if len(status_code) > 1 and status_code[1:].isdigit():
                score = float(status_code[1:]) / 100.0
            renamed_files.append(RenamedFile(old_path=parts[1], new_path=parts[2], similarity_score=score))
        elif status_code.startswith("A") and len(parts) >= 2:
            added_files.append(parts[1])
        elif status_code.startswith("D") and len(parts) >= 2:
            deleted_files.append(parts[1])
        elif status_code.startswith("M") and len(parts) >= 2:
            modified_files.append(parts[1])

    added_symbols: list[ChangedSymbol] = []
    removed_symbols: list[ChangedSymbol] = []
    changed_symbols: list[ChangedSymbol] = []
    changed_relationships: list[ChangedRelationship] = []
    changed_routes: list[ChangedRoute] = []
    affected_tests: set[str] = set()
    db_impact: list[dict[str, Any]] = []

    # 2. Inspect renamed files
    for r in renamed_files:
        lang = _get_language(r.new_path)
        if not lang:
            continue
        old_content = _get_file_content_at_ref(repository, base, r.old_path)
        new_content = _get_file_content_at_ref(repository, head, r.new_path)
        if old_content and new_content:
            old_res = parse(old_content, lang, r.old_path)
            new_res = parse(new_content, lang, r.new_path)
            for s in new_res.symbols:
                changed_symbols.append(
                    ChangedSymbol(
                        name=s.name,
                        qualified_name=s.qualified_name or s.name,
                        path=r.new_path,
                        kind=s.kind,
                        change_type="MOVED",
                        old_path=r.old_path,
                        old_name=s.name,
                        confidence="FACT",
                        evidence=f"File moved from {r.old_path} to {r.new_path} (similarity {r.similarity_score:.0%})",
                    )
                )

    # 3. Inspect modified files at AST level
    for m_path in modified_files:
        lang = _get_language(m_path)
        if not lang:
            continue

        old_content = _get_file_content_at_ref(repository, base, m_path) or ""
        new_content = _get_file_content_at_ref(repository, head, m_path) or ""

        old_res = parse(old_content, lang, m_path)
        new_res = parse(new_content, lang, m_path)

        old_sym_map = {s.name: s for s in old_res.symbols}
        new_sym_map = {s.name: s for s in new_res.symbols}

        # Check added symbols in this file
        for name, new_s in new_sym_map.items():
            if name not in old_sym_map:
                added_symbols.append(
                    ChangedSymbol(
                        name=name,
                        qualified_name=new_s.qualified_name or name,
                        path=m_path,
                        kind=new_s.kind,
                        change_type="ADDED",
                        new_line=new_s.start_line,
                        confidence="FACT",
                        evidence=f"Defined at {m_path}:{new_s.start_line}",
                    )
                )

        # Check removed symbols in this file
        for name, old_s in old_sym_map.items():
            if name not in new_sym_map:
                removed_symbols.append(
                    ChangedSymbol(
                        name=name,
                        qualified_name=old_s.qualified_name or name,
                        path=m_path,
                        kind=old_s.kind,
                        change_type="REMOVED",
                        old_line=old_s.start_line,
                        confidence="FACT",
                        evidence=f"Removed from {m_path} (was at line {old_s.start_line})",
                    )
                )

        # Check modified symbols
        for name, new_s in new_sym_map.items():
            if name in old_sym_map:
                old_s = old_sym_map[name]
                # Compare body content hashes or line ranges
                old_lines = old_content.splitlines()
                new_lines = new_content.splitlines()
                old_snippet = "\n".join(old_lines[max(0, old_s.start_line - 1) : old_s.end_line]).strip()
                new_snippet = "\n".join(new_lines[max(0, new_s.start_line - 1) : new_s.end_line]).strip()

                if old_snippet != new_snippet:
                    changed_symbols.append(
                        ChangedSymbol(
                            name=name,
                            qualified_name=new_s.qualified_name or name,
                            path=m_path,
                            kind=new_s.kind,
                            change_type="MODIFIED",
                            old_line=old_s.start_line,
                            new_line=new_s.start_line,
                            confidence="FACT",
                            evidence=f"Body modified at {m_path}:{new_s.start_line}-{new_s.end_line}",
                        )
                    )

        # Check framework routes diff
        old_routes = {(r.route_path, r.http_method): r for r in old_res.routes}
        new_routes = {(r.route_path, r.http_method): r for r in new_res.routes}
        for (r_path, r_method), r_obj in new_routes.items():
            if (r_path, r_method) not in old_routes:
                changed_routes.append(
                    ChangedRoute(
                        path=r_path,
                        method=r_method,
                        handler=r_obj.handler_name or "",
                        framework=r_obj.framework or "",
                        change_type="ADDED",
                    )
                )
            elif old_routes[(r_path, r_method)].handler_name != r_obj.handler_name:
                changed_routes.append(
                    ChangedRoute(
                        path=r_path,
                        method=r_method,
                        handler=r_obj.handler_name or "",
                        framework=r_obj.framework or "",
                        change_type="MODIFIED",
                    )
                )
        for (r_path, r_method), r_obj in old_routes.items():
            if (r_path, r_method) not in new_routes:
                changed_routes.append(
                    ChangedRoute(
                        path=r_path,
                        method=r_method,
                        handler=r_obj.handler_name or "",
                        framework=r_obj.framework or "",
                        change_type="REMOVED",
                    )
                )

        # Check call graph relationships added / removed
        old_calls = {c.callee for c in old_res.calls}
        new_calls = {c.callee for c in new_res.calls}
        for c in new_calls - old_calls:
            changed_relationships.append(
                ChangedRelationship(
                    relationship_type="CALLS",
                    source=m_path,
                    target=c,
                    change_type="ADDED",
                    file=m_path,
                )
            )
        for c in old_calls - new_calls:
            changed_relationships.append(
                ChangedRelationship(
                    relationship_type="CALLS",
                    source=m_path,
                    target=c,
                    change_type="REMOVED",
                    file=m_path,
                )
            )

        # Detect test coverage links if test file
        if "test" in m_path.lower():
            affected_tests.add(m_path)

    # 4. Check added files at AST level
    for a_path in added_files:
        lang = _get_language(a_path)
        if not lang:
            continue
        content = _get_file_content_at_ref(repository, head, a_path) or ""
        res = parse(content, lang, a_path)
        for s in res.symbols:
            added_symbols.append(
                ChangedSymbol(
                    name=s.name,
                    qualified_name=s.qualified_name or s.name,
                    path=a_path,
                    kind=s.kind,
                    change_type="ADDED",
                    new_line=s.start_line,
                    confidence="FACT",
                    evidence=f"Defined in newly added file {a_path}:{s.start_line}",
                )
            )
        for r_obj in res.routes:
            changed_routes.append(
                ChangedRoute(
                    path=r_obj.route_path,
                    method=r_obj.http_method,
                    handler=r_obj.handler_name or "",
                    framework=r_obj.framework or "",
                    change_type="ADDED",
                )
            )
        if "test" in a_path.lower():
            affected_tests.add(a_path)

    # 5. Check deleted files
    for d_path in deleted_files:
        lang = _get_language(d_path)
        if not lang:
            continue
        old_content = _get_file_content_at_ref(repository, base, d_path) or ""
        res = parse(old_content, lang, d_path)
        for s in res.symbols:
            removed_symbols.append(
                ChangedSymbol(
                    name=s.name,
                    qualified_name=s.qualified_name or s.name,
                    path=d_path,
                    kind=s.kind,
                    change_type="REMOVED",
                    old_line=s.start_line,
                    confidence="FACT",
                    evidence=f"Deleted with file {d_path}",
                )
            )
        for r_obj in res.routes:
            changed_routes.append(
                ChangedRoute(
                    path=r_obj.route_path,
                    method=r_obj.http_method,
                    handler=r_obj.handler_name or "",
                    framework=r_obj.framework or "",
                    change_type="REMOVED",
                )
            )

    # 6. Database impact (if con is available)
    if con is not None:
        try:
            for cs in changed_symbols + added_symbols + removed_symbols:
                rows = con.execute(
                    "SELECT table_name, operation FROM database_queries WHERE symbol=? OR caller_symbol=?",
                    (cs.name, cs.name),
                ).fetchall()
                for r in rows:
                    db_impact.append({
                        "symbol": cs.name,
                        "table": r[0],
                        "operation": r[1],
                        "change_type": cs.change_type,
                    })
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    total_files = len(added_files) + len(deleted_files) + len(modified_files) + len(renamed_files)
    total_symbols = len(added_symbols) + len(removed_symbols) + len(changed_symbols)

    return StructuralDiffReport(
        base_ref=base,
        head_ref=head,
        added_files=sorted(added_files),
        deleted_files=sorted(deleted_files),
        modified_files=sorted(modified_files),
        renamed_files=renamed_files,
        added_symbols=added_symbols,
        removed_symbols=removed_symbols,
        changed_symbols=changed_symbols,
        changed_relationships=changed_relationships,
        changed_routes=changed_routes,
        affected_tests=sorted(affected_tests),
        db_impact=db_impact,
        total_file_changes=total_files,
        total_symbol_changes=total_symbols,
    )


def compare_branches(
    repository: Path,
    base_branch: str = "main",
    head_branch: str = "HEAD",
    con: sqlite3.Connection | None = None,
) -> StructuralDiffReport:
    """Compare two branches structurally using their merge-base or direct revision diff."""
    if base_branch == head_branch:
        return StructuralDiffReport(base_ref=base_branch, head_ref=head_branch)
    # Find merge base if available
    merge_base = _run_git(repository, "merge-base", base_branch, head_branch)
    base = merge_base.strip() if merge_base else base_branch
    return compare_revisions(repository, base=base, head=head_branch, con=con)


def compare_head_with_index(
    repository: Path,
    con: sqlite3.Connection | None = None,
) -> StructuralDiffReport:
    """Compare uncommitted working tree changes against current HEAD."""
    return compare_revisions(repository, base="HEAD", head="WORKING_TREE", con=con)
