"""Branch Architecture Comparison Engine.

Provides hierarchical structural comparisons between Git branches:
    package
      ↓
      module
        ↓
        symbol
          ↓
          relationships (routes, tests, DB writes, calls)

Supports:
- deterministic ordering
- token-budget awareness (max_tokens)
- cursor-based pagination
- explicit summary of changed routes, services, database models, and affected tests
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.monorepo import detect_workspace
from codegraph.structural_diff import compare_branches


@dataclass
class SymbolChangeItem:
    name: str
    kind: str
    change_type: str  # "ADDED" | "MODIFIED" | "REMOVED"
    line: int | None
    relationships: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "change_type": self.change_type,
            "line": self.line,
            "relationships": self.relationships,
        }


@dataclass
class ModuleChangeItem:
    module: str
    file_path: str
    symbols: list[SymbolChangeItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "file_path": self.file_path,
            "symbols": [s.as_dict() for s in self.symbols],
        }


@dataclass
class PackageChangeItem:
    package_id: str
    modules: list[ModuleChangeItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "modules": [m.as_dict() for m in self.modules],
        }


@dataclass
class BranchArchitectureReport:
    base_branch: str
    head_branch: str
    packages: list[PackageChangeItem] = field(default_factory=list)
    changed_routes: list[dict[str, str]] = field(default_factory=list)
    changed_services: list[str] = field(default_factory=list)
    changed_db: list[dict[str, str]] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    total_packages: int = 0
    total_symbols: int = 0
    estimated_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "packages": [p.as_dict() for p in self.packages],
            "changed_routes": self.changed_routes,
            "changed_services": self.changed_services,
            "changed_db": self.changed_db,
            "affected_tests": self.affected_tests,
            "next_cursor": self.next_cursor,
            "total_packages": self.total_packages,
            "total_symbols": self.total_symbols,
            "estimated_tokens": self.estimated_tokens,
        }


def compare_branch_architecture(
    repository: Path,
    base_branch: str = "main",
    head_branch: str = "HEAD",
    con: sqlite3.Connection | None = None,
    limit: int = 50,
    cursor: str | None = None,
    max_tokens: int = 4000,
) -> BranchArchitectureReport:
    """Compare two branches and return hierarchical architecture diff."""
    if base_branch == head_branch:
        return BranchArchitectureReport(base_branch=base_branch, head_branch=head_branch)

    # 1. Run structural branch diff
    diff_report = compare_branches(repository, base_branch=base_branch, head_branch=head_branch, con=con)

    # 2. Workspace package mapper
    ws = detect_workspace(repository, con=con)

    # 3. Build hierarchical package -> module -> symbol map
    package_map: dict[str, dict[str, list[SymbolChangeItem]]] = {}
    services: set[str] = set()

    all_symbols = diff_report.added_symbols + diff_report.changed_symbols + diff_report.removed_symbols
    # Sort deterministically by path and name
    all_symbols.sort(key=lambda s: (s.path, s.name))

    # Apply cursor pagination if cursor provided
    start_idx = 0
    if cursor and cursor.isdigit():
        start_idx = int(cursor)

    paged_symbols = all_symbols[start_idx : start_idx + limit]
    next_cursor = str(start_idx + limit) if (start_idx + limit) < len(all_symbols) else None

    for s in paged_symbols:
        pkg = ws.get_package_for_file(s.path)
        pkg_id = pkg.package_id if pkg else "root"

        if pkg_id not in package_map:
            package_map[pkg_id] = {}
        if s.path not in package_map[pkg_id]:
            package_map[pkg_id][s.path] = []

        # Find associated relationships
        rels: list[str] = []
        for r in diff_report.changed_routes:
            if r.handler == s.name:
                rels.append(f"{r.change_type} ROUTE {r.method} {r.path}")
        for db in diff_report.db_impact:
            if db.get("symbol") == s.name:
                rels.append(f"{db.get('change_type')} DB {db.get('operation')} {db.get('table')}")

        if "service" in s.name.lower() or "service" in s.path.lower():
            services.add(s.name)

        package_map[pkg_id][s.path].append(
            SymbolChangeItem(
                name=s.name,
                kind=s.kind,
                change_type=s.change_type,
                line=s.new_line or s.old_line,
                relationships=rels,
            )
        )

    # Build ordered PackageChangeItem objects
    package_items: list[PackageChangeItem] = []
    total_sym_count = 0

    for pkg_id in sorted(package_map.keys()):
        module_items: list[ModuleChangeItem] = []
        for f_path in sorted(package_map[pkg_id].keys()):
            mod_name = Path(f_path).stem
            sym_items = package_map[pkg_id][f_path]
            total_sym_count += len(sym_items)
            module_items.append(ModuleChangeItem(module=mod_name, file_path=f_path, symbols=sym_items))
        package_items.append(PackageChangeItem(package_id=pkg_id, modules=module_items))

    # Rough token estimation: ~25 tokens per symbol + overhead
    token_est = total_sym_count * 25 + len(diff_report.changed_routes) * 15 + 150

    return BranchArchitectureReport(
        base_branch=base_branch,
        head_branch=head_branch,
        packages=package_items,
        changed_routes=[r.as_dict() for r in diff_report.changed_routes],
        changed_services=sorted(services),
        changed_db=diff_report.db_impact,
        affected_tests=diff_report.affected_tests,
        next_cursor=next_cursor,
        total_packages=len(package_items),
        total_symbols=total_sym_count,
        estimated_tokens=token_est,
    )
