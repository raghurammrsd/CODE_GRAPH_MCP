"""Constraint Guard for CodeGraph MCP v2.1.

Enforces deterministic hard constraints across every retrieval and compilation stage:
- Explicit excluded symbols, hierarchical descendants, and canonical IDs
- Explicit excluded files, directories, and path-component matching
- Excluded modules and namespaces
- Scope paths and scope modules
- Repository and security boundary protection

Architectural Invariant:
  Hard constraints are HARD FILTERS, never ranking penalties.
  No entity violating a hard constraint may participate in candidate generation,
  graph traversal, ranking, coverage, or appear in the final ContextPacket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


def _normalize_path(p: str | None) -> str:
    if not p:
        return ""
    norm = p.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.strip("/")


def _is_hierarchical_symbol_match(sym: str, excl: str) -> bool:
    """Return True if `sym` matches `excl` or is a hierarchical descendant of `excl`.

    Examples:
      - excl="AuthService", sym="AuthService" -> True
      - excl="AuthService", sym="AuthService.login" -> True
      - excl="AuthService", sym="auth.AuthService.login" -> True
      - excl="AuthService", sym="AuthServiceHelper" -> False (distinct symbol)
      - excl="AuthService", sym="UserAuthService" -> False (distinct symbol)
    """
    if not sym or not excl:
        return False
    if sym == excl:
        return True
    if sym.startswith(f"{excl}.") or sym.startswith(f"{excl}:"):
        return True

    # Check dot-separated hierarchy components
    parts = sym.split(".")
    for part in parts:
        if part == excl:
            return True

    # Check colon-separated hierarchy components (e.g. file:Class.method)
    col_parts = sym.split(":")
    for part in col_parts:
        if part == excl or part.startswith(f"{excl}."):
            return True
    return False


@dataclass(frozen=True)
class ConstraintGuard:
    """Central hard-constraint enforcement guard."""

    excluded_symbols: frozenset[str] = field(default_factory=frozenset)
    excluded_files: frozenset[str] = field(default_factory=frozenset)
    excluded_modules: frozenset[str] = field(default_factory=frozenset)
    scope_paths: frozenset[str] = field(default_factory=frozenset)
    scope_modules: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_task_spec(cls, task_spec: Any) -> ConstraintGuard:
        """Construct a ConstraintGuard from a TaskSpec or dictionary."""
        if not task_spec:
            return cls()

        excl_syms: set[str] = set()
        excl_files: set[str] = set()
        excl_mods: set[str] = set()

        raw_exclusions = getattr(task_spec, "exclusions", ()) or ()
        if isinstance(raw_exclusions, (list, tuple, set)):
            for item in raw_exclusions:
                if not item:
                    continue
                s = str(item).strip()
                if "/" in s or "\\" in s or s.endswith(".py") or s.endswith(".ts") or s.endswith(".js"):
                    excl_files.add(_normalize_path(s))
                else:
                    excl_syms.add(s)

        raw_scope_paths = getattr(task_spec, "scope_paths", ()) or ()
        scope_p = {_normalize_path(str(p)) for p in raw_scope_paths if p}

        raw_scope_mods = getattr(task_spec, "scope_modules", ()) or ()
        scope_m = {str(m).strip() for m in raw_scope_mods if m}

        return cls(
            excluded_symbols=frozenset(excl_syms),
            excluded_files=frozenset(excl_files),
            excluded_modules=frozenset(excl_mods),
            scope_paths=frozenset(scope_p),
            scope_modules=frozenset(scope_m),
        )

    def allows_symbol(self, symbol: str | None) -> bool:
        """Check if symbol is permitted under exclusion and scope constraints."""
        if not symbol:
            return True
        s = symbol.strip()
        for excl in self.excluded_symbols:
            if _is_hierarchical_symbol_match(s, excl):
                return False
        return True

    def allows_canonical_id(self, canonical_id: str | None) -> bool:
        """Check if canonical symbol ID is permitted."""
        if not canonical_id:
            return True
        cid = canonical_id.strip()
        if not self.allows_symbol(cid):
            return False
        # If canonical_id encodes a file path, verify file is allowed
        if ":" in cid:
            path_part = cid.split(":", 1)[0]
            if "/" in path_part or path_part.endswith((".py", ".ts", ".js")):
                if not self.allows_file(path_part):
                    return False
        return True

    def allows_file(self, file_path: str | None) -> bool:
        """Check if file path is permitted under exclusion, path-component, and scope constraints."""
        if not file_path:
            return True
        path_norm = _normalize_path(file_path)

        # 1. Security check: reject path traversal
        path_obj = PurePosixPath(path_norm)
        if ".." in path_obj.parts:
            return False

        # 2. Hard exclusions
        for excl in self.excluded_files:
            excl_norm = _normalize_path(excl)
            if not excl_norm:
                continue
            # Exact path match
            if path_norm == excl_norm:
                return False
            # Directory prefix match (e.g. excl="src/admin_panel", path="src/admin_panel/views.py")
            if path_norm.startswith(f"{excl_norm}/"):
                return False
            # Suffix / component match if exclusion is just a filename
            if "/" not in excl_norm and path_obj.name == excl_norm:
                return False

        # 3. Scope constraints (if scope paths specified, path must match at least one)
        if self.scope_paths:
            in_scope = False
            for sp in self.scope_paths:
                if path_norm == sp or path_norm.startswith(f"{sp}/"):
                    in_scope = True
                    break
            if not in_scope:
                return False

        return True

    def allows_module(self, module_name: str | None) -> bool:
        """Check if module is permitted."""
        if not module_name:
            return True
        m = module_name.strip()
        for excl in self.excluded_modules:
            if m == excl or m.startswith(f"{excl}."):
                return False
        if self.scope_modules:
            in_scope = False
            for sm in self.scope_modules:
                if m == sm or m.startswith(f"{sm}."):
                    in_scope = True
                    break
            if not in_scope:
                return False
        return True

    def allows_relationship(
        self,
        source_id: str | None,
        rel_type: str | None,
        target_id: str | None,
    ) -> bool:
        """Check if relationship endpoints are permitted."""
        if source_id and not self.allows_canonical_id(source_id) and not self.allows_symbol(source_id):
            return False
        if target_id and not self.allows_canonical_id(target_id) and not self.allows_symbol(target_id):
            return False
        return True

    def allows_test(
        self,
        test_file: str | None,
        test_symbol: str | None = None,
    ) -> bool:
        """Check if test artifact is permitted."""
        if test_file and not self.allows_file(test_file):
            return False
        if test_symbol and not self.allows_symbol(test_symbol):
            return False
        return True

    def allows_endpoint(
        self,
        route_path: str | None,
        handler_name: str | None = None,
        file_path: str | None = None,
    ) -> bool:
        """Check if framework route is permitted."""
        if file_path and not self.allows_file(file_path):
            return False
        if handler_name and not self.allows_symbol(handler_name):
            return False
        if route_path and route_path in self.excluded_symbols:
            return False
        return True

    def allows_evidence(
        self,
        file_path: str | None,
        symbol: str | None = None,
    ) -> bool:
        """Check if evidence item is permitted."""
        if file_path and not self.allows_file(file_path):
            return False
        if symbol and not self.allows_symbol(symbol):
            return False
        return True
