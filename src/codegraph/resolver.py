"""Dedicated Reference & Symbol Resolution Engine.

Pipeline:
  Parser IR (Symbols, Imports, Calls, Inheritance, Routes)
      ↓
  Module Resolver (deterministic file/package resolution)
      ↓
  Re-export Chain Resolver
      ↓
  Symbol & Relationship Resolver (lexical -> canonical -> alias -> qualified -> module -> framework)
      ↓
  Confidence & Source-Hash Evidence Assignment
      ↓
  Deduplicated References & Graph Edges
"""
from __future__ import annotations

import json
import posixpath
import re
import sqlite3
from dataclasses import dataclass, field

from codegraph.binding_resolver import LocalBindingResolver
from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.frameworks import RouteDetection
from codegraph.graph.models import GraphEdge
from codegraph.indexing.models import (
    BindingRef,
    CallRef,
    ImportRef,
    InheritanceRef,
    Reference,
    Symbol,
    normalize_module,
)
from codegraph.monorepo import WorkspaceInfo
from codegraph.route_composer import ComposedMountEdge

_TEST_FILE_RE = re.compile(
    r"(^|[_/])test[_s]?[_/]|[_/]spec[_/]|test[_s]?\.(py|js|ts|jsx|tsx)$|spec\.(py|js|ts|jsx|tsx)$",
    re.IGNORECASE,
)

DEFAULT_MAX_REEXPORT_DEPTH = 16
DEFAULT_MAX_WILDCARD_EXPANSIONS = 64


def resolve_module_to_path(
    imported_module: str,
    source_file: str,
    known_files: set[str],
    workspace: WorkspaceInfo | None = None,
) -> str | None:
    """Deterministically resolve an import specifier to a repository-relative file path.

    Never guesses files outside `known_files`.
    """
    if not imported_module:
        return None

    # 0. Check workspace package mappings for cross-package imports
    if workspace is not None:
        target_pkg, entrypoint = workspace.resolve_package_import(imported_module, source_file)
        if entrypoint:
            clean_entry = entrypoint.replace("\\", "/").lstrip("./")
            if clean_entry in known_files:
                return clean_entry
            for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                if f"{clean_entry}{ext}" in known_files:
                    return f"{clean_entry}{ext}"
                if f"{clean_entry}/index{ext}" in known_files:
                    return f"{clean_entry}/index{ext}"
                if f"{clean_entry}/__init__{ext}" in known_files:
                    return f"{clean_entry}/__init__{ext}"

    src_clean = source_file.replace("\\", "/").lstrip("./")
    src_dir = posixpath.dirname(src_clean)

    candidates: list[str] = []

    if imported_module.startswith(".") or "/" in imported_module:
        # Relative or path-based import (JS/TS or relative path)
        if imported_module.startswith("."):
            joined = posixpath.normpath(posixpath.join(src_dir, imported_module)) if src_dir else posixpath.normpath(imported_module)
        else:
            joined = posixpath.normpath(imported_module.lstrip("/"))

        if joined.startswith(".."):
            return None
        if joined == ".":
            joined = src_dir

        candidates.append(joined)
        for ext in (".ts", ".tsx", ".js", ".jsx", ".py", ".mjs", ".cjs"):
            candidates.append(f"{joined}{ext}")
        for idx_file in ("index.ts", "index.tsx", "index.js", "index.jsx", "__init__.py"):
            candidates.append(posixpath.join(joined, idx_file) if joined else idx_file)
    else:
        # Dotted module specifier (Python or package root path)
        mod_path = imported_module.replace(".", "/")
        prefixes = [""]
        if src_dir:
            prefixes.append(f"{src_dir}/")
            # Also try top-level package root (e.g. 'src/')
            first_seg = src_dir.split("/")[0]
            if f"{first_seg}/" not in prefixes:
                prefixes.append(f"{first_seg}/")
        if "src/" not in prefixes:
            prefixes.append("src/")

        for prefix in prefixes:
            base = f"{prefix}{mod_path}"
            candidates.append(f"{base}.py")
            candidates.append(f"{base}/__init__.py")
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                candidates.append(f"{base}{ext}")
                candidates.append(f"{base}/index{ext}")

    for cand in candidates:
        norm = cand.lstrip("./")
        if norm in known_files:
            return norm
    return None


@dataclass
class ResolutionOutput:
    references: list[Reference]
    edges: list[GraphEdge]
    resolved_imports: dict[tuple[str, int, str], tuple[str | None, str | None]]
    resolved_calls: dict[tuple[str, int, str], tuple[str | None, str]]
    findings: list[dict[str, object]] = field(default_factory=list)



class ReferenceResolver:
    """Resolves imports, aliases, re-exports, inheritance, calls, and routes across a repository."""

    def __init__(
        self,
        symbols: list[Symbol],
        imports: list[ImportRef],
        calls: list[CallRef],
        inheritance: list[InheritanceRef],
        routes: list[RouteDetection],
        known_files: set[str],
        file_hashes: dict[str, str],
        indexed_commit: str | None = None,
        mount_edges: list[ComposedMountEdge] | None = None,
        bindings: list[BindingRef] | None = None,
        workspace: WorkspaceInfo | None = None,
        max_reexport_depth: int = 16,
        max_wildcard_expansions: int = 64,
    ) -> None:
        self.symbols = symbols
        self.imports = imports
        self.calls = calls
        self.inheritance = inheritance
        self.routes = routes
        self.mount_edges = mount_edges or []
        self.bindings = bindings or []
        self.known_files = known_files
        self.file_hashes = file_hashes
        self.indexed_commit = indexed_commit
        self.workspace = workspace
        self.max_reexport_depth = max_reexport_depth
        self.max_wildcard_expansions = max_wildcard_expansions

        # Memoization caches and budget tracking
        self._import_target_cache: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        self._symbol_in_module_cache: dict[tuple[str, str], Symbol | None] = {}
        self.budget_findings: list[dict[str, object]] = []
        self._seen_budget_keys: set[tuple[str, str]] = set()

        # Indexed lookup maps (O(1) lookup)
        self.canonical_to_symbol: dict[str, Symbol] = {}
        self.qualified_to_symbols: dict[str, list[Symbol]] = {}
        self.module_to_symbols: dict[str, dict[str, Symbol]] = {}
        self.short_to_symbols: dict[str, list[Symbol]] = {}
        self.path_to_symbols: dict[str, list[Symbol]] = {}
        self.file_to_module: dict[str, str] = {
            f: normalize_module(f) for f in known_files
        }
        self.module_to_file: dict[str, str] = {
            normalize_module(f): f for f in sorted(known_files)
        }

        for sym in symbols:
            self.canonical_to_symbol[sym.canonical_id] = sym
            self.qualified_to_symbols.setdefault(sym.qualified_name, []).append(sym)
            mod_map = self.module_to_symbols.setdefault(sym.module, {})
            mod_map[sym.qualified_name] = sym
            mod_map.setdefault(sym.name, sym)
            self.short_to_symbols.setdefault(sym.name, []).append(sym)
            self.path_to_symbols.setdefault(sym.path, []).append(sym)

        self.file_imports: dict[str, list[ImportRef]] = {}
        for imp in imports:
            self.file_imports.setdefault(imp.source_file, []).append(imp)

        # Map (source_module, exported_name) -> (target_module, target_name)
        self.reexport_map: dict[tuple[str, str], tuple[str, str]] = {}
        self.wildcard_reexports: dict[str, list[str]] = {}
        self._build_reexport_maps()

        # Local deterministic binding and data-flow engine
        self.binding_resolver = LocalBindingResolver(
            bindings=self.bindings,
            symbols=self.symbols,
            imports=self.imports,
            known_files=self.known_files,
            resolve_symbol_in_module=self.resolve_symbol_in_module,
            resolve_import_target=self._resolve_import_target_module,
        )

    def _record_budget_exceeded(
        self,
        module: str,
        symbol_name: str,
        file_path: str | None = None,
        line: int = 1,
    ) -> None:
        b_key = (module, symbol_name)
        if b_key in self._seen_budget_keys:
            return
        self._seen_budget_keys.add(b_key)
        self.budget_findings.append(
            {
                "pattern": "WILDCARD_OR_REEXPORT_RESOLUTION",
                "status": "UNKNOWN",
                "reason": "resolution_budget_exceeded",
                "module": module,
                "symbol": symbol_name,
                "file": file_path or self.module_to_file.get(module, ""),
                "line": line,
            }
        )

    @staticmethod
    def resolve_symbol_diagnostic(con: sqlite3.Connection, query: str) -> dict[str, object]:
        return resolve_symbol_diagnostic(con, query)

    def _resolve_import_target_module(self, imp: ImportRef) -> tuple[str | None, str | None]:
        """Return (resolved_file_path, resolved_module) for an ImportRef."""
        if self.workspace is not None:
            cache_ctx = imp.source_file
        else:
            cache_ctx = posixpath.dirname(imp.source_file.replace("\\", "/").lstrip("./"))
        cache_key = (imp.imported_module, cache_ctx)
        if cache_key in self._import_target_cache:
            return self._import_target_cache[cache_key]

        res = self._resolve_import_target_module_uncached(imp)
        self._import_target_cache[cache_key] = res
        return res

    def _resolve_import_target_module_uncached(self, imp: ImportRef) -> tuple[str | None, str | None]:
        target_path = resolve_module_to_path(
            imp.imported_module, imp.source_file, self.known_files, workspace=self.workspace
        )
        if target_path:
            return target_path, normalize_module(target_path)

        # Maybe imported_module is `pkg.mod.Symbol` where `pkg.mod` is a file
        if "." in imp.imported_module and not imp.imported_module.startswith("."):
            parent_mod, last_seg = imp.imported_module.rsplit(".", 1)
            parent_path = resolve_module_to_path(
                parent_mod, imp.source_file, self.known_files, workspace=self.workspace
            )
            if parent_path:
                return parent_path, normalize_module(parent_path)
            # Check if normalized module exists directly
            if imp.imported_module in self.module_to_file:
                p = self.module_to_file[imp.imported_module]
                return p, imp.imported_module
            if f"src.{imp.imported_module}" in self.module_to_file:
                mod = f"src.{imp.imported_module}"
                return self.module_to_file[mod], mod
            del last_seg

        if imp.imported_module in self.module_to_file:
            p = self.module_to_file[imp.imported_module]
            return p, imp.imported_module
        if f"src.{imp.imported_module}" in self.module_to_file:
            mod = f"src.{imp.imported_module}"
            return self.module_to_file[mod], mod

        return None, None

    def _build_reexport_maps(self) -> None:
        for imp in self.imports:
            if not imp.is_reexport:
                continue
            _target_path, target_mod = self._resolve_import_target_module(imp)
            if not target_mod:
                continue
            src_mod = imp.source_module or normalize_module(imp.source_file)
            if imp.imported_name == "*" and not imp.alias:
                targets = self.wildcard_reexports.setdefault(src_mod, [])
                if target_mod not in targets:
                    targets.append(target_mod)
            else:
                exported_nm = imp.exported_name or imp.alias or imp.imported_name or imp.local_name
                orig_nm = imp.imported_name or exported_nm
                if exported_nm and orig_nm:
                    self.reexport_map[(src_mod, exported_nm)] = (target_mod, orig_nm)

    def resolve_symbol_in_module(
        self,
        module: str,
        symbol_name: str,
        visited: set[tuple[str, str]] | None = None,
        depth: int = 0,
        budget: list[int] | None = None,
    ) -> Symbol | None:
        """Resolve `symbol_name` in `module`, following re-export chains deterministically with bounded budgets."""
        is_top_level = visited is None and depth == 0
        cache_key = (module, symbol_name)
        if is_top_level and cache_key in self._symbol_in_module_cache:
            return self._symbol_in_module_cache[cache_key]

        if budget is None:
            budget = [0]

        res = self._resolve_symbol_in_module_impl(
            module, symbol_name, visited, depth, budget, root_module=module, root_symbol=symbol_name
        )
        if is_top_level:
            self._symbol_in_module_cache[cache_key] = res
        return res

    def _resolve_symbol_in_module_impl(
        self,
        module: str,
        symbol_name: str,
        visited: set[tuple[str, str]] | None,
        depth: int,
        budget: list[int],
        root_module: str,
        root_symbol: str,
    ) -> Symbol | None:
        if depth > self.max_reexport_depth or budget[0] > self.max_wildcard_expansions:
            self._record_budget_exceeded(root_module, root_symbol)
            self._record_budget_exceeded(module, symbol_name)
            return None

        visited = visited or set()
        key = (module, symbol_name)
        if key in visited:
            return None
        visited.add(key)

        # 1. Direct symbol in module
        mod_syms = self.module_to_symbols.get(module)
        if mod_syms and symbol_name in mod_syms:
            return mod_syms[symbol_name]

        # Check canonical ID directly
        canon_cand = f"{module}.{symbol_name}"
        if canon_cand in self.canonical_to_symbol:
            return self.canonical_to_symbol[canon_cand]

        # If symbol_name is dotted (e.g. AS.login or AuthService.login), resolve prefix first
        if "." in symbol_name:
            prefix, rest = symbol_name.split(".", 1)
            base_sym = self._resolve_symbol_in_module_impl(
                module, prefix, set(visited), depth + 1, budget, root_module, root_symbol
            )
            if base_sym:
                method_canon = f"{base_sym.canonical_id}.{rest}"
                if method_canon in self.canonical_to_symbol:
                    return self.canonical_to_symbol[method_canon]

        # 2. Named re-export in this module
        if key in self.reexport_map:
            target_mod, orig_name = self.reexport_map[key]
            return self._resolve_symbol_in_module_impl(
                target_mod, orig_name, visited, depth + 1, budget, root_module, root_symbol
            )

        # 3. Wildcard re-exports in this module (bounded by max_wildcard_expansions)
        for target_mod in self.wildcard_reexports.get(module, ()):
            budget[0] += 1
            if budget[0] > self.max_wildcard_expansions:
                self._record_budget_exceeded(root_module, root_symbol)
                self._record_budget_exceeded(module, symbol_name)
                return None
            found = self._resolve_symbol_in_module_impl(
                target_mod, symbol_name, visited, depth + 1, budget, root_module, root_symbol
            )
            if found:
                return found

        # 4. Default export fallback: if symbol_name == "default" and module has a single class/function
        if symbol_name == "default" and mod_syms:
            top_level = [s for s in mod_syms.values() if not s.scope]
            if len(top_level) == 1:
                return top_level[0]

        return None

    def resolve_identifier_in_file(
        self,
        identifier: str,
        source_file: str,
        caller_canonical_id: str | None = None,
        use_line: int | None = None,
    ) -> tuple[Symbol | None, str, str]:
        """Resolve an identifier or dotted expression inside `source_file`.

        Returns (Symbol | None, confidence, resolution_reason).
        """
        src_mod = self.file_to_module.get(source_file) or normalize_module(source_file)

        # Level 1: Lexical / local scope
        if caller_canonical_id and caller_canonical_id in self.canonical_to_symbol:
            caller_sym = self.canonical_to_symbol[caller_canonical_id]
            # Check nested symbol inside caller or sibling in same scope
            nested_canon = f"{caller_sym.canonical_id}.{identifier}"
            if nested_canon in self.canonical_to_symbol:
                return (
                    self.canonical_to_symbol[nested_canon],
                    "HIGH",
                    "Local nested symbol in lexical scope",
                )
            if caller_sym.scope:
                sibling_canon = f"{src_mod}.{caller_sym.scope}.{identifier}"
                if sibling_canon in self.canonical_to_symbol:
                    return (
                        self.canonical_to_symbol[sibling_canon],
                        "HIGH",
                        f"Class/scope member in {caller_sym.scope}",
                    )

        # Same-module symbol
        local_sym = self.resolve_symbol_in_module(src_mod, identifier)
        if local_sym:
            return local_sym, "HIGH", f"Defined in same module '{src_mod}'"
        if (src_mod, identifier) in self._seen_budget_keys:
            return None, "UNKNOWN", "resolution_budget_exceeded"

        # Level 2: Exact canonical symbol match
        if identifier in self.canonical_to_symbol:
            return (
                self.canonical_to_symbol[identifier],
                "HIGH",
                "Exact canonical symbol match",
            )

        # Level 3 & 4: Imported alias, named import, default import, or namespace/qualified import
        imps = self.file_imports.get(source_file, [])
        if "." in identifier:
            prefix, rest = identifier.split(".", 1)
            # Check if prefix is a local class in same module
            local_cls = self.resolve_symbol_in_module(src_mod, prefix)
            if local_cls:
                member_canon = f"{local_cls.canonical_id}.{rest}"
                if member_canon in self.canonical_to_symbol:
                    return (
                        self.canonical_to_symbol[member_canon],
                        "HIGH",
                        f"Resolved method '{rest}' on local class '{local_cls.canonical_id}'",
                    )

            # Check if prefix is an imported symbol/alias or namespace
            for imp in imps:
                if imp.local_name == prefix or imp.alias == prefix or imp.name == prefix:
                    _tpath, target_mod = self._resolve_import_target_module(imp)
                    if target_mod:
                        if imp.import_type in ("namespace", "module") or imp.imported_name in (None, "*"):
                            sym = self.resolve_symbol_in_module(target_mod, rest)
                            if sym:
                                return (
                                    sym,
                                    "HIGH",
                                    f"Resolved via namespace import '{prefix}' -> '{sym.canonical_id}'",
                                )
                            if (target_mod, rest) in self._seen_budget_keys:
                                return None, "UNKNOWN", "resolution_budget_exceeded"
                        else:
                            orig_cls = imp.imported_name or prefix
                            cls_sym = self.resolve_symbol_in_module(
                                target_mod, orig_cls
                            ) or self.resolve_symbol_in_module(target_mod, prefix)
                            if cls_sym:
                                method_canon = f"{cls_sym.canonical_id}.{rest}"
                                if method_canon in self.canonical_to_symbol:
                                    return (
                                        self.canonical_to_symbol[method_canon],
                                        "HIGH",
                                        f"Resolved via imported symbol '{prefix}' -> '{method_canon}'",
                                    )
                            # Or target_mod is actually a package and orig_cls is a submodule
                            sub_sym = self.resolve_symbol_in_module(f"{target_mod}.{orig_cls}", rest)
                            if sub_sym:
                                return (
                                    sub_sym,
                                    "HIGH",
                                    f"Resolved via submodule import '{prefix}.{rest}' -> '{sub_sym.canonical_id}'",
                                )
        else:
            wildcard_imps: list[ImportRef] = []
            for imp in imps:
                if imp.local_name == identifier or imp.alias == identifier:
                    _tpath, target_mod = self._resolve_import_target_module(imp)
                    if target_mod:
                        if imp.import_type == "default":
                            sym = self.resolve_symbol_in_module(
                                target_mod, imp.local_name
                            ) or self.resolve_symbol_in_module(target_mod, "default")
                        else:
                            target_name = imp.imported_name or identifier
                            sym = self.resolve_symbol_in_module(target_mod, target_name)
                        if sym:
                            return (
                                sym,
                                "HIGH",
                                f"Resolved via import '{imp.local_name}' from '{target_mod}'",
                            )
                        if (target_mod, imp.imported_name or identifier) in self._seen_budget_keys:
                            return None, "UNKNOWN", "resolution_budget_exceeded"
                elif imp.imported_name == "*" and not imp.alias:
                    wildcard_imps.append(imp)

            if wildcard_imps and not identifier.startswith("_"):
                if len(wildcard_imps) > self.max_wildcard_expansions:
                    self._record_budget_exceeded(src_mod, identifier, file_path=source_file, line=use_line or 1)
                    return None, "UNKNOWN", "resolution_budget_exceeded"
                wildcard_matches: dict[str, tuple[Symbol, str]] = {}
                wc_budget = [0]
                for w_imp in wildcard_imps:
                    _tpath, target_mod = self._resolve_import_target_module(w_imp)
                    if not target_mod:
                        continue
                    wc_budget[0] += 1
                    if wc_budget[0] > self.max_wildcard_expansions:
                        self._record_budget_exceeded(src_mod, identifier, file_path=source_file, line=use_line or 1)
                        return None, "UNKNOWN", "resolution_budget_exceeded"
                    w_sym = self.resolve_symbol_in_module(target_mod, identifier, budget=wc_budget)
                    if (target_mod, identifier) in self._seen_budget_keys or wc_budget[0] > self.max_wildcard_expansions:
                        self._record_budget_exceeded(src_mod, identifier, file_path=source_file, line=use_line or 1)
                        return None, "UNKNOWN", "resolution_budget_exceeded"
                    if w_sym:
                        wildcard_matches[w_sym.canonical_id] = (w_sym, target_mod)
                if len(wildcard_matches) == 1:
                    only_sym, only_mod = next(iter(wildcard_matches.values()))
                    return (
                        only_sym,
                        "HIGH",
                        f"Resolved via wildcard import from '{only_mod}'",
                    )
                if len(wildcard_matches) > 1:
                    return None, "UNKNOWN", "ambiguous_wildcard_import"

        # Level 5: Exact qualified name match if unique across repository
        if "." in identifier and identifier in self.qualified_to_symbols:
            cands = self.qualified_to_symbols[identifier]
            if len(cands) == 1:
                return (
                    cands[0],
                    "MEDIUM",
                    f"Unique qualified symbol match '{cands[0].canonical_id}'",
                )

        # Level 6: Local Binding and Data-Flow resolution
        caller_scope = ""
        if caller_canonical_id and caller_canonical_id in self.canonical_to_symbol:
            caller_scope = self.canonical_to_symbol[caller_canonical_id].scope

        canon_id, ev_class, reason = self.binding_resolver.resolve(
            file_path=source_file,
            name=identifier,
            scope=caller_scope,
            use_line=use_line,
        )
        if canon_id:
            if canon_id in self.canonical_to_symbol:
                return self.canonical_to_symbol[canon_id], "HIGH", reason
            # Dotted or submodule symbol
            target_sym = self.resolve_symbol_in_module(src_mod, canon_id)
            if target_sym:
                return target_sym, "HIGH", reason

        return None, "UNKNOWN", f"No matching local or imported symbol found ({reason if canon_id is None else ''})."

    def resolve_all(self) -> ResolutionOutput:
        """Run the full resolution pipeline and emit deduplicated References and GraphEdges."""
        references: list[Reference] = []
        edges: list[GraphEdge] = []
        seen_refs: set[tuple[str, str | None, str, str, int]] = set()
        seen_edges: set[tuple[str, str, str, str, int]] = set()
        resolved_imports: dict[tuple[str, int, str], tuple[str | None, str | None]] = {}
        resolved_calls: dict[tuple[str, int, str], tuple[str | None, str]] = {}

        def add_ref(ref: Reference) -> None:
            key = (
                ref.source_symbol_id,
                ref.target_symbol_id,
                ref.relationship,
                ref.path,
                ref.start_line,
            )
            if key not in seen_refs:
                seen_refs.add(key)
                references.append(ref)

        def add_edge(edge: GraphEdge) -> None:
            key = (
                edge.source,
                edge.target,
                edge.relationship,
                edge.file,
                edge.start_line,
            )
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(edge)

        # 0. Definition & Containment edges
        for sym in self.symbols:
            f_hash = self.file_hashes.get(sym.path, "")
            if sym.parent_symbol_id:
                add_edge(
                    GraphEdge(
                        source=sym.parent_symbol_id,
                        target=sym.canonical_id,
                        relationship="CONTAINS",
                        confidence="HIGH",
                        file=sym.path,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        evidence=f"Scope containment {sym.parent_symbol_id} -> {sym.canonical_id}",
                    )
                )
            else:
                add_edge(
                    GraphEdge(
                        source=sym.path,
                        target=sym.canonical_id,
                        relationship="DEFINES",
                        confidence="HIGH",
                        file=sym.path,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        evidence=f"File {sym.path} defines {sym.canonical_id}",
                    )
                )
            del f_hash

        # 1. Resolve Imports & Re-exports
        for imp in self.imports:
            src_mod = imp.source_module or normalize_module(imp.source_file)
            f_hash = self.file_hashes.get(imp.source_file, "")
            target_path, target_mod = self._resolve_import_target_module(imp)
            resolved_imports[(imp.source_file, imp.line, imp.local_name)] = (
                target_path,
                target_mod,
            )

            if imp.is_reexport:
                exp_name = imp.exported_name or imp.alias or imp.imported_name or "*"
                orig_name = imp.imported_name or exp_name
                target_sym = (
                    self.resolve_symbol_in_module(target_mod, orig_name)
                    if (target_mod and orig_name != "*")
                    else None
                )
                target_id = (
                    target_sym.canonical_id
                    if target_sym
                    else (f"{target_mod}.{orig_name}" if target_mod else f"{imp.imported_module}.{orig_name}")
                )
                conf = "HIGH" if (target_sym or target_mod) else "LOW"
                src_id = f"{src_mod}.{exp_name}" if exp_name != "*" else src_mod
                add_ref(
                    Reference(
                        source_symbol_id=src_id,
                        target_symbol_id=target_id,
                        relationship="REEXPORTS",
                        confidence=conf,
                        path=imp.source_file,
                        start_line=imp.line,
                        end_line=imp.line,
                        evidence=f"Re-export '{exp_name}' from '{imp.imported_module}' -> '{target_id}'",
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=src_id,
                        target=target_id,
                        relationship="REEXPORTS",
                        confidence=conf,
                        file=imp.source_file,
                        start_line=imp.line,
                        end_line=imp.line,
                        evidence=f"Re-export '{exp_name}' from '{imp.imported_module}'",
                    )
                )
            else:
                target_sym = None
                if target_mod and imp.imported_name and imp.imported_name != "*":
                    target_sym = self.resolve_symbol_in_module(target_mod, imp.imported_name)
                target_id = (
                    target_sym.canonical_id
                    if target_sym
                    else (target_mod or imp.imported_module)
                )
                conf = "HIGH"
                add_ref(
                    Reference(
                        source_symbol_id=src_mod,
                        target_symbol_id=target_id,
                        relationship="IMPORTS",
                        confidence=conf,
                        path=imp.source_file,
                        start_line=imp.line,
                        end_line=imp.line,
                        evidence=f"Import '{imp.local_name}' from '{imp.imported_module}'",
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=imp.source_file,
                        target=target_path or imp.imported_module,
                        relationship="IMPORTS",
                        confidence="HIGH",
                        file=imp.source_file,
                        start_line=imp.line,
                        end_line=imp.line,
                        evidence=f"Import '{imp.imported_module}' at {imp.source_file}:{imp.line}",
                    )
                )

        # 2. Resolve Inheritance (EXTENDS / IMPLEMENTS) inside a map so inherited methods can also resolve
        class_bases_map: dict[str, list[str]] = {}
        for inh in self.inheritance:
            f_hash = self.file_hashes.get(inh.source_file, "")
            target_sym, conf, reason = self.resolve_identifier_in_file(
                inh.base_name, inh.source_file, inh.source_canonical_id
            )
            target_id = target_sym.canonical_id if target_sym else inh.base_name
            if target_sym:
                class_bases_map.setdefault(inh.source_canonical_id, []).append(
                    target_sym.canonical_id
                )
            add_ref(
                Reference(
                    source_symbol_id=inh.source_canonical_id,
                    target_symbol_id=target_id,
                    relationship=inh.relationship,
                    confidence=conf,
                    path=inh.source_file,
                    start_line=inh.line,
                    end_line=inh.line,
                    evidence=f"{inh.source_canonical_id} {inh.relationship} {target_id} ({reason})",
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=inh.source_canonical_id,
                    target=target_id,
                    relationship=inh.relationship,
                    confidence=conf,
                    file=inh.source_file,
                    start_line=inh.line,
                    end_line=inh.line,
                    evidence=f"{inh.source_canonical_id} {inh.relationship} {target_id}",
                )
            )

        # 3. Resolve Call Sites (with shared receiver, local binding, and factory return resolution)
        file_bindings_map: dict[str, list[BindingRef]] = {}
        receiver_bindings_by_fts: dict[tuple[str, str, str], list[BindingRef]] = {}
        call_return_bindings_by_file: dict[str, list[BindingRef]] = {}
        _RECEIVER_EXPR_KINDS = frozenset(
            ("CALL_RETURN", "TYPE_ANNOTATION", "IDENTIFIER", "ATTRIBUTE", "DYNAMIC", "DYNAMIC_CALL_RETURN")
        )
        for b_item in self.bindings:
            file_bindings_map.setdefault(b_item.file_path, []).append(b_item)
            if b_item.expr_kind in _RECEIVER_EXPR_KINDS:
                receiver_bindings_by_fts.setdefault(
                    (b_item.file_path, b_item.target_name, b_item.scope), []
                ).append(b_item)
            if b_item.expr_kind == "CALL_RETURN" and not b_item.is_conditional:
                call_return_bindings_by_file.setdefault(b_item.file_path, []).append(b_item)

        def _lookup_method_on_class(class_canon: str, method_name: str) -> tuple[Symbol | None, str]:
            direct_cand = f"{class_canon}.{method_name}"
            if direct_cand in self.canonical_to_symbol:
                return self.canonical_to_symbol[direct_cand], class_canon
            visited_bases: set[str] = {class_canon}
            base_queue: list[str] = list(class_bases_map.get(class_canon, []))
            while base_queue and len(visited_bases) <= 15:
                base_canon = base_queue.pop(0)
                if base_canon in visited_bases:
                    continue
                visited_bases.add(base_canon)
                cand = f"{base_canon}.{method_name}"
                if cand in self.canonical_to_symbol:
                    return self.canonical_to_symbol[cand], base_canon
                base_queue.extend(class_bases_map.get(base_canon, []))
            return None, class_canon

        factory_return_cache: dict[str, tuple[Symbol | None, str]] = {}

        def _resolve_factory_return_class(f_sym: Symbol, depth: int = 0) -> tuple[Symbol | None, str]:
            if depth == 0 and f_sym.canonical_id in factory_return_cache:
                return factory_return_cache[f_sym.canonical_id]
            if depth > 5 or not f_sym.return_type:
                return None, ""
            raw_ret = f_sym.return_type.strip()
            if raw_ret in ("<AMBIGUOUS>", "<DYNAMIC>") or "|" in raw_ret:
                return None, ""
            clean_ret = raw_ret.split("[")[0].strip().strip("'\"")
            if not clean_ret:
                return None, ""
            ret_sym, _rc, _rr = self.resolve_identifier_in_file(
                clean_ret, f_sym.path, f_sym.canonical_id
            )
            if not ret_sym:
                cand_c = f"{f_sym.module}.{clean_ret}"
                ret_sym = self.canonical_to_symbol.get(cand_c)
            if not ret_sym:
                if depth == 0:
                    factory_return_cache[f_sym.canonical_id] = (None, "")
                return None, ""
            if ret_sym.kind == "class":
                res = (ret_sym, f"factory '{f_sym.canonical_id}()' -> '{ret_sym.canonical_id}'")
                if depth == 0:
                    factory_return_cache[f_sym.canonical_id] = res
                return res
            if ret_sym.kind in ("function", "method"):
                sub_cls, sub_rsn = _resolve_factory_return_class(ret_sym, depth + 1)
                if sub_cls:
                    res = (sub_cls, f"factory '{f_sym.canonical_id}()' -> {sub_rsn}")
                    if depth == 0:
                        factory_return_cache[f_sym.canonical_id] = res
                    return res
            if depth == 0:
                factory_return_cache[f_sym.canonical_id] = (None, "")
            return None, ""

        def _resolve_receiver_class(
            recv_part: str,
            source_file: str,
            caller_id: str,
            caller_qname: str,
            use_line: int,
            depth: int = 0,
        ) -> tuple[Symbol | None, Symbol | None, str]:
            if depth > 5 or not recv_part:
                return None, None, ""

            f_bindings = file_bindings_map.get(source_file)
            if f_bindings:
                caller_sym_obj = self.canonical_to_symbol.get(caller_id)
                eff_qname = caller_qname or (caller_sym_obj.qualified_name if caller_sym_obj else "")
                enclosing_cls = (
                    caller_sym_obj.scope
                    if (caller_sym_obj and caller_sym_obj.scope)
                    else (eff_qname.rsplit(".", 1)[0] if "." in eff_qname else "")
                )
                candidate_scopes: list[str] = []
                for sc_cand in (
                    eff_qname,
                    caller_id,
                    enclosing_cls,
                    f"{caller_sym_obj.module}.{enclosing_cls}" if (caller_sym_obj and enclosing_cls) else "",
                    "",
                ):
                    if sc_cand not in candidate_scopes:
                        candidate_scopes.append(sc_cand)

                matched_scope_bindings: list[BindingRef] = []
                for sc in candidate_scopes:
                    sc_matches = receiver_bindings_by_fts.get((source_file, recv_part, sc))
                    if sc_matches:
                        prior = [b for b in sc_matches if b.line <= use_line]
                        matched_scope_bindings = prior if prior else (sc_matches if recv_part.startswith("self.") else [])
                        if matched_scope_bindings:
                            break

                if matched_scope_bindings:
                    if any(b.expr_kind in ("DYNAMIC", "DYNAMIC_CALL_RETURN") or b.source_expr == "<DYNAMIC>" for b in matched_scope_bindings):
                        return None, None, "Dynamic receiver assignment"
                    if any(b.is_conditional for b in matched_scope_bindings):
                        return None, None, "Conditional receiver assignment"
                    call_or_id_exprs = {
                        b.source_expr for b in matched_scope_bindings
                        if b.expr_kind in ("CALL_RETURN", "IDENTIFIER", "ATTRIBUTE")
                    }
                    if len(call_or_id_exprs) > 1:
                        return None, None, "Conflicting receiver assignments in scope"

                    # Prefer CALL_RETURN / IDENTIFIER / ATTRIBUTE first (to preserve factory provenance), then TYPE_ANNOTATION
                    chosen_b = next(
                        (b for b in reversed(matched_scope_bindings) if b.expr_kind in ("CALL_RETURN", "IDENTIFIER", "ATTRIBUTE")),
                        matched_scope_bindings[-1],
                    )
                    if chosen_b.expr_kind == "TYPE_ANNOTATION":
                        ann_sym, _, _ = self.resolve_identifier_in_file(
                            chosen_b.source_expr, chosen_b.file_path, caller_id, use_line=chosen_b.line
                        )
                        if ann_sym and ann_sym.kind == "class":
                            return ann_sym, None, f"Type annotation '{chosen_b.source_expr}' -> '{ann_sym.canonical_id}'"
                    else:
                        src_expr = chosen_b.source_expr[:-2].strip() if chosen_b.source_expr.endswith("()") else chosen_b.source_expr.strip()
                        cal_sym, _, _ = self.resolve_identifier_in_file(
                            src_expr, chosen_b.file_path, caller_id, use_line=chosen_b.line
                        )
                        if not cal_sym and "." in src_expr:
                            f_recv, f_meth = src_expr.rsplit(".", 1)
                            f_cls_sym, _, _ = _resolve_receiver_class(
                                f_recv, chosen_b.file_path, caller_id, caller_qname, chosen_b.line, depth + 1
                            )
                            if f_cls_sym:
                                cal_sym, _ = _lookup_method_on_class(f_cls_sym.canonical_id, f_meth)
                        if cal_sym:
                            if cal_sym.kind == "class":
                                return cal_sym, None, f"Constructed instance of '{cal_sym.canonical_id}'"
                            if cal_sym.kind in ("function", "method"):
                                ret_cls, ret_rsn = _resolve_factory_return_class(cal_sym, depth + 1)
                                if ret_cls:
                                    return ret_cls, cal_sym, f"Resolved via {ret_rsn}"

            # Direct symbol lookup for receiver (class name or factory function name in chained call)
            recv_sym, _rconf, _rreason = self.resolve_identifier_in_file(
                recv_part, source_file, caller_id, use_line=use_line
            )
            if recv_sym:
                if recv_sym.kind == "class":
                    return recv_sym, None, f"Direct receiver class '{recv_sym.canonical_id}'"
                if recv_sym.kind in ("function", "method"):
                    ret_cls, ret_rsn = _resolve_factory_return_class(recv_sym, depth + 1)
                    if ret_cls:
                        return ret_cls, recv_sym, f"Resolved via {ret_rsn}"
            elif "." in recv_part:
                sub_recv, sub_meth = recv_part.rsplit(".", 1)
                sub_cls, _, _ = _resolve_receiver_class(
                    sub_recv, source_file, caller_id, caller_qname, use_line, depth + 1
                )
                if sub_cls:
                    meth_sym, _ = _lookup_method_on_class(sub_cls.canonical_id, sub_meth)
                    if meth_sym:
                        ret_cls, ret_rsn = _resolve_factory_return_class(meth_sym, depth + 1)
                        if ret_cls:
                            return ret_cls, meth_sym, f"Resolved via {ret_rsn}"

            # Fallback if parser substituted local variable with same-file factory's return type string
            cr_bindings = call_return_bindings_by_file.get(source_file)
            if cr_bindings:
                for b in reversed(cr_bindings):
                    if b.line <= use_line:
                        f_sym, _, _ = self.resolve_identifier_in_file(
                            b.source_expr, b.file_path, caller_id, use_line=b.line
                        )
                        if f_sym and f_sym.kind in ("function", "method"):
                            ret_cls, ret_rsn = _resolve_factory_return_class(f_sym, depth + 1)
                            if ret_cls and (ret_cls.name == recv_part or ret_cls.qualified_name == recv_part):
                                return ret_cls, f_sym, f"Resolved via {ret_rsn}"

            return None, None, ""

        for call in self.calls:
            f_hash = self.file_hashes.get(call.source_file, "")
            caller_id = call.caller_canonical_id or (self.file_to_module.get(call.source_file) or normalize_module(call.source_file))
            caller_sym_for_qname = self.canonical_to_symbol.get(caller_id)
            caller_qname = call.caller_symbol or (caller_sym_for_qname.qualified_name if caller_sym_for_qname else "")
            expr = call.qualified_callee or call.callee
            via_factory_sym: Symbol | None = None
            resolved_via_dataflow = False

            target_sym, conf, reason = self.resolve_identifier_in_file(
                expr, call.source_file, caller_id, use_line=call.line
            )

            # Check receiver resolution (local binding, self.<attr>, inherited method, or factory return type)
            if "." in expr:
                recv_part, method_part = expr.rsplit(".", 1)
                if not target_sym:
                    recv_cls_sym, via_factory_sym, recv_reason = _resolve_receiver_class(
                        recv_part, call.source_file, caller_id, caller_qname, call.line
                    )
                    if recv_cls_sym:
                        meth_sym, owner_canon = _lookup_method_on_class(recv_cls_sym.canonical_id, method_part)
                        if meth_sym:
                            target_sym = meth_sym
                            conf = "HIGH"
                            resolved_via_dataflow = True
                            if owner_canon != recv_cls_sym.canonical_id:
                                reason = f"{recv_reason}; inherited method on '{owner_canon}'"
                            else:
                                reason = recv_reason
                else:
                    # Even if parser substituted receiver -> ClassName, check if it came from a local factory binding
                    for b in call_return_bindings_by_file.get(call.source_file, ()):
                        if b.scope in (caller_qname, caller_id) and b.line <= call.line:
                            f_sym, _, _ = self.resolve_identifier_in_file(
                                b.source_expr, b.file_path, caller_id, use_line=b.line
                            )
                            if f_sym and f_sym.kind in ("function", "method"):
                                ret_cls, ret_rsn = _resolve_factory_return_class(f_sym)
                                if ret_cls and target_sym.canonical_id.startswith(ret_cls.canonical_id + "."):
                                    via_factory_sym = f_sym
                                    resolved_via_dataflow = True
                                    reason = f"Resolved via {ret_rsn}"
                                    break

                if target_sym and via_factory_sym:
                    add_ref(
                        Reference(
                            source_symbol_id=caller_id,
                            target_symbol_id=via_factory_sym.canonical_id,
                            relationship="CALLS",
                            confidence="HIGH",
                            path=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=f"Call factory '{via_factory_sym.canonical_id}()' at {call.source_file}:{call.line}",
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=caller_id,
                            target=via_factory_sym.canonical_id,
                            relationship="CALLS",
                            confidence="HIGH",
                            file=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=f"Resolved factory call {caller_id} -> {via_factory_sym.canonical_id} at {call.source_file}:{call.line}",
                        )
                    )

            if target_sym:
                resolved_calls[(call.source_file, call.line, call.callee)] = (
                    target_sym.canonical_id,
                    conf,
                )
                call_ev_cls = (
                    RelationshipEvidenceClass.DATAFLOW_VERIFIED.value
                    if resolved_via_dataflow
                    else RelationshipEvidenceClass.AST_VERIFIED.value
                )
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=target_sym.canonical_id,
                        relationship="CALLS",
                        confidence=conf,
                        path=call.source_file,
                        start_line=call.line,
                        end_line=call.end_line,
                        evidence=f"Call '{expr}()' at {call.source_file}:{call.line} -> {target_sym.canonical_id} ({reason})",
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=target_sym.canonical_id,
                        relationship="CALLS",
                        confidence=conf,
                        file=call.source_file,
                        start_line=call.line,
                        end_line=call.end_line,
                        evidence=f"Resolved call {caller_id} -> {target_sym.canonical_id} at {call.source_file}:{call.line} ({reason})",
                        evidence_class=call_ev_cls,
                    )
                )
            elif "[" in expr and "]" in expr:
                dict_part, raw_k = expr.split("[", 1)
                raw_k = raw_k.rstrip("]")
                clean_k = raw_k.strip("'\"")
                idx_val = int(clean_k) if clean_k.isdigit() else None
                key_val = None if idx_val is not None else clean_k
                disp_target, disp_ev, disp_rsn = self.binding_resolver.resolve_subscript(
                    call.source_file, dict_part, key=key_val, index=idx_val, use_line=call.line
                )
                if disp_target:
                    add_ref(
                        Reference(
                            source_symbol_id=caller_id,
                            target_symbol_id=disp_target,
                            relationship="DISPATCHES_TO",
                            confidence="HIGH",
                            path=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=f"Dispatch call '{expr}()' -> {disp_target} ({disp_rsn})",
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=caller_id,
                            target=disp_target,
                            relationship="DISPATCHES_TO",
                            confidence="HIGH",
                            file=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=f"Dispatch call '{expr}()' -> {disp_target} at {call.source_file}:{call.line}",
                            evidence_class=disp_ev.value,
                            reason=disp_rsn,
                        )
                    )
                else:
                    resolved_calls[(call.source_file, call.line, call.callee)] = (
                        None,
                        "UNKNOWN",
                    )
                    add_ref(
                        Reference(
                            source_symbol_id=caller_id,
                            target_symbol_id=None,
                            relationship="UNRESOLVED_REFERENCE",
                            confidence="UNKNOWN",
                            path=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=f"Unresolved dispatch call '{expr}()' at {call.source_file}:{call.line} ({disp_rsn})",
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
            else:
                # Target cannot be statically resolved via lexical/import/module rules
                resolved_calls[(call.source_file, call.line, call.callee)] = (
                    None,
                    "UNKNOWN",
                )
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=None,
                        relationship="UNRESOLVED_REFERENCE",
                        confidence="UNKNOWN",
                        path=call.source_file,
                        start_line=call.line,
                        end_line=call.end_line,
                        evidence=f"Unresolved call '{expr}()' at {call.source_file}:{call.line} ({reason})",
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )

        # 4. Framework Route -> Handler edges
        for rt in self.routes:
            f_hash = self.file_hashes.get(rt.file_path, "")
            handler_sym, conf, _reason = self.resolve_identifier_in_file(
                rt.handler_name, rt.file_path, use_line=rt.line
            )
            target_id = handler_sym.canonical_id if handler_sym else rt.handler_canonical_id
            edge_conf = "HIGH" if handler_sym else conf
            add_ref(
                Reference(
                    source_symbol_id=rt.endpoint_id,
                    target_symbol_id=target_id,
                    relationship="ROUTES_TO",
                    confidence=edge_conf,
                    path=rt.file_path,
                    start_line=rt.line,
                    end_line=rt.line,
                    evidence=rt.evidence,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=rt.endpoint_id,
                    target=target_id,
                    relationship="ROUTES_TO",
                    confidence=edge_conf,
                    file=rt.file_path,
                    start_line=rt.line,
                    end_line=rt.line,
                    evidence=rt.evidence,
                    evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                )
            )

        # 5. Verified Router Mount edges (MOUNTS)
        for me in self.mount_edges:
            f_hash = self.file_hashes.get(me.file_path, "")
            add_ref(
                Reference(
                    source_symbol_id=me.parent_canonical_id,
                    target_symbol_id=me.child_canonical_id,
                    relationship="MOUNTS",
                    confidence="HIGH",
                    path=me.file_path,
                    start_line=me.line,
                    end_line=me.line,
                    evidence=me.evidence,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=me.parent_canonical_id,
                    target=me.child_canonical_id,
                    relationship="MOUNTS",
                    confidence="HIGH",
                    file=me.file_path,
                    start_line=me.line,
                    end_line=me.line,
                    evidence=me.evidence,
                    evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                    reason="router_mount",
                )
            )

        # Pre-group bindings by expr_kind and pre-index inheritance/routes for O(1) lookups
        bindings_by_kind: dict[str, list[BindingRef]] = {}
        event_listeners_by_key: dict[str, list[BindingRef]] = {}
        _EVENT_LISTENER_KINDS = frozenset(
            ("EVENT_ON", "SUBSCRIBE", "CALL_REGISTER", "REGISTRY_ADD", "REGISTRY_CALL", "DECORATOR_REGISTER")
        )
        for b in self.bindings:
            bindings_by_kind.setdefault(b.expr_kind, []).append(b)
            if b.expr_kind in _EVENT_LISTENER_KINDS and b.subscript_key:
                event_listeners_by_key.setdefault(b.subscript_key, []).append(b)

        inheritance_by_source: dict[str, list[InheritanceRef]] = {}
        for inh in self.inheritance:
            inheritance_by_source.setdefault(inh.source_canonical_id, []).append(inh)

        # 6. Local Bindings and Alias Chains (RESOLVES_TO)
        for b in (
            bindings_by_kind.get("IDENTIFIER", [])
            + bindings_by_kind.get("ATTRIBUTE", [])
            + bindings_by_kind.get("SUBSCRIPT", [])
        ):
            b_target_id, ev_class, reason = self.binding_resolver.resolve(
                file_path=b.file_path,
                name=b.target_name,
                scope=b.scope,
                use_line=b.line,
            )
            if b_target_id and ev_class == RelationshipEvidenceClass.DATAFLOW_VERIFIED:
                f_hash = self.file_hashes.get(b.file_path, "")
                src_mod = self.file_to_module.get(b.file_path) or normalize_module(b.file_path)
                source_id = f"{src_mod}.{b.scope}.{b.target_name}" if b.scope else f"{src_mod}.{b.target_name}"
                add_ref(
                    Reference(
                        source_symbol_id=source_id,
                        target_symbol_id=b_target_id,
                        relationship="RESOLVES_TO",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=f"Local binding alias '{b.target_name}' -> '{b_target_id}' ({b.source_expr})",
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=source_id,
                        target=b_target_id,
                        relationship="RESOLVES_TO",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=f"Local binding alias '{b.target_name}' -> '{b_target_id}' ({b.source_expr})",
                        evidence_class=RelationshipEvidenceClass.DATAFLOW_VERIFIED.value,
                        reason=reason,
                    )
                )

        # 7. Registries, Event Listeners, and Dispatch Registrations
        findings: list[dict[str, object]] = list(self.budget_findings)

        # Pre-compute static overwrite state for DICT_ASSIGN bindings in the same (file_path, scope, target_name, subscript_key)
        dict_assign_groups: dict[tuple[str, str, str, str], list[BindingRef]] = {}
        for b in bindings_by_kind.get("DICT_ASSIGN", ()):
            if b.subscript_key and b.subscript_key != "<DYNAMIC>":
                g_key = (b.file_path, b.scope, b.target_name, b.subscript_key)
                dict_assign_groups.setdefault(g_key, []).append(b)

        overwritten_dict_assign_lines: set[tuple[str, str, str, str, int]] = set()
        ambiguous_dict_assign_keys: set[tuple[str, str, str, str]] = set()
        for g_key, g_list in dict_assign_groups.items():
            if len(g_list) <= 1:
                continue
            g_sorted = sorted(g_list, key=lambda x: (x.line, x.column or 0))
            last_uncond_idx = -1
            for idx, item in enumerate(g_sorted):
                if not item.is_conditional:
                    last_uncond_idx = idx
            if last_uncond_idx >= 0:
                for idx in range(last_uncond_idx):
                    overwritten_dict_assign_lines.add((*g_key, g_sorted[idx].line))
                if last_uncond_idx < len(g_sorted) - 1:
                    ambiguous_dict_assign_keys.add(g_key)
            else:
                ambiguous_dict_assign_keys.add(g_key)

        for b in self.bindings:
            if b.expr_kind == "LIST_LITERAL" and b.list_entries:
                t_lower = b.target_name.lower()
                if t_lower in ("handlers", "registry", "callbacks", "plugins", "listeners", "handler_list", "plugin_list"):
                    f_hash = self.file_hashes.get(b.file_path, "")
                    source_id = f"{self.file_to_module.get(b.file_path) or normalize_module(b.file_path)}.{b.target_name}"
                    for idx_elt, elt_expr in enumerate(b.list_entries):
                        target_sym, _conf, _rsn = self.resolve_identifier_in_file(
                            elt_expr, b.file_path, use_line=b.line
                        )
                        if not target_sym:
                            continue
                        target_canon = target_sym.canonical_id
                        ev_class = RelationshipEvidenceClass.POSSIBLE if b.is_conditional else RelationshipEvidenceClass.DATAFLOW_VERIFIED
                        edge_conf = "LOW" if b.is_conditional else "HIGH"
                        edge_reason = "ambiguous_dispatch_assignment" if b.is_conditional else f"Statically verified list handler registration [{idx_elt}] -> '{target_canon}'"
                        evidence_str = f"{b.target_name} DISPATCHES_TO {target_canon} (index={idx_elt})"
                        add_ref(
                            Reference(
                                source_symbol_id=source_id,
                                target_symbol_id=target_canon,
                                relationship="DISPATCHES_TO",
                                confidence=edge_conf,
                                path=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=evidence_str,
                                source_hash=f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=source_id,
                                target=target_canon,
                                relationship="DISPATCHES_TO",
                                confidence=edge_conf,
                                file=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=evidence_str,
                                evidence_class=ev_class.value,
                                reason=edge_reason,
                            )
                        )
                continue

            if b.expr_kind not in ("CALL_REGISTER", "DICT_ASSIGN", "EVENT_ON", "SUBSCRIBE"):
                continue

            if b.expr_kind == "DICT_ASSIGN" and b.subscript_key and b.subscript_key != "<DYNAMIC>":
                g_key = (b.file_path, b.scope, b.target_name, b.subscript_key)
                if (*g_key, b.line) in overwritten_dict_assign_lines:
                    findings.append({
                        "pattern": "DICT_ASSIGN",
                        "status": "OVERWRITTEN",
                        "reason": "overwritten_by_later_static_assignment",
                        "file": b.file_path,
                        "line": b.line,
                        "target_name": b.target_name,
                        "key": b.subscript_key,
                        "source_expr": b.source_expr,
                    })
                    continue

            f_hash = self.file_hashes.get(b.file_path, "")
            is_dynamic = (b.subscript_key == "<DYNAMIC>" or b.source_expr == "<DYNAMIC>")

            if is_dynamic:
                reason = (
                    "dynamic_dispatch"
                    if b.expr_kind == "DICT_ASSIGN"
                    else (
                        "dynamic_event_name"
                        if b.subscript_key == "<DYNAMIC>"
                        else "dynamic_registration"
                    )
                )
                findings.append({
                    "pattern": b.expr_kind,
                    "status": "UNKNOWN",
                    "reason": reason,
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })
                # Invariant: NEVER emit an edge with fake/unknown target canonical ID (Correction 2)
                continue

            target_sym, _conf, _reason = self.resolve_identifier_in_file(
                b.source_expr, b.file_path, use_line=b.line
            )

            if not target_sym:
                findings.append({
                    "pattern": b.expr_kind,
                    "status": "UNKNOWN",
                    "reason": "unknown_registry_target",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                    "source_expr": b.source_expr,
                })
                # Invariant: NEVER emit an edge with fake/unknown target canonical ID (Correction 2)
                continue

            # Target is statically grounded!
            target_canon = target_sym.canonical_id
            if b.expr_kind == "CALL_REGISTER":
                rel = "REGISTERS"
            elif b.expr_kind in ("EVENT_ON", "SUBSCRIBE"):
                rel = "EVENT_LISTENER"
            else:
                rel = "DISPATCHES_TO"

            is_ambig_key = (
                b.expr_kind == "DICT_ASSIGN"
                and b.subscript_key is not None
                and (b.file_path, b.scope, b.target_name, b.subscript_key) in ambiguous_dict_assign_keys
            )
            if b.is_conditional or is_ambig_key:
                ev_class = RelationshipEvidenceClass.POSSIBLE
                edge_conf = "LOW"
                edge_reason = "ambiguous_dispatch_assignment"
            else:
                ev_class = RelationshipEvidenceClass.DATAFLOW_VERIFIED
                edge_conf = "HIGH"
                edge_reason = f"Statically verified registration of '{b.subscript_key}' -> '{target_canon}'"

            source_id = f"{self.file_to_module.get(b.file_path) or normalize_module(b.file_path)}.{b.target_name}"
            evidence_str = f"{b.target_name} {rel} {target_canon} (key='{b.subscript_key}')"

            add_ref(
                Reference(
                    source_symbol_id=source_id,
                    target_symbol_id=target_canon,
                    relationship=rel,
                    confidence=edge_conf,
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=evidence_str,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=source_id,
                    target=target_canon,
                    relationship=rel,
                    confidence=edge_conf,
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=evidence_str,
                    evidence_class=ev_class.value,
                    reason=edge_reason,
                )
            )

        # 8. Semantic Decorators (TASK_HANDLER, COMMAND_HANDLER, EVENT_LISTENER, REGISTERS)
        for b in bindings_by_kind.get("SEMANTIC_DECORATOR", ()):
            f_hash = self.file_hashes.get(b.file_path, "")
            is_dynamic = b.subscript_target is not None
            metadata: dict[str, object] = {}
            if b.subscript_key:
                try:
                    metadata = json.loads(b.subscript_key)
                except Exception:
                    metadata = {}

            if is_dynamic:
                findings.append({
                    "pattern": "SEMANTIC_DECORATOR",
                    "role": b.attr_name,
                    "status": "UNKNOWN",
                    "reason": b.subscript_target or "dynamic_argument",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                    "decorator": b.source_expr,
                })
                # Invariant: Never emit edge for dynamic/unknown targets
                continue

            rel = b.attr_name
            assert rel != "CALLS", f"Invariant violated: Semantic decorator {rel} cannot be CALLS"

            target_canon = b.target_name
            meta_ev = str(metadata.get("evidence_class", ""))
            ev_class = (
                RelationshipEvidenceClass.POSSIBLE
                if b.is_conditional
                else (
                    RelationshipEvidenceClass(meta_ev)
                    if meta_ev in RelationshipEvidenceClass._value2member_map_
                    else (
                        RelationshipEvidenceClass.DATAFLOW_VERIFIED
                        if b.base_expr == "registry"
                        else RelationshipEvidenceClass.FRAMEWORK_VERIFIED
                    )
                )
            )
            edge_conf = "LOW" if b.is_conditional else "HIGH"
            edge_reason = (
                f"Conditional registration via '@{b.source_expr}'"
                if b.is_conditional
                else f"Statically verified registration via '@{b.source_expr}'"
            )

            if rel == "EVENT_LISTENER":
                events = metadata.get("events")
                if isinstance(events, list) and events:
                    for ev in events:
                        ev_str = str(ev)
                        ev_sym, _conf, _ = self.resolve_identifier_in_file(
                            ev_str, b.file_path, use_line=b.line
                        )
                        src_id = ev_sym.canonical_id if ev_sym else ev_str
                        ev_evidence = f"Event listener '{target_canon}' registered for event '{ev_str}' via '@{b.source_expr}'"

                        add_ref(
                            Reference(
                                source_symbol_id=src_id,
                                target_symbol_id=target_canon,
                                relationship=rel,
                                confidence=edge_conf,
                                path=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_evidence,
                                source_hash=f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=src_id,
                                target=target_canon,
                                relationship=rel,
                                confidence=edge_conf,
                                file=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_evidence,
                                evidence_class=ev_class.value,
                                reason=edge_reason,
                            )
                        )
                else:
                    src_id = b.source_expr
                    ev_evidence = f"Event listener '{target_canon}' registered via '@{b.source_expr}'"
                    add_ref(
                        Reference(
                            source_symbol_id=src_id,
                            target_symbol_id=target_canon,
                            relationship=rel,
                            confidence=edge_conf,
                            path=b.file_path,
                            start_line=b.line,
                            end_line=b.line,
                            evidence=ev_evidence,
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=src_id,
                            target=target_canon,
                            relationship=rel,
                            confidence=edge_conf,
                            file=b.file_path,
                            start_line=b.line,
                            end_line=b.line,
                            evidence=ev_evidence,
                            evidence_class=ev_class.value,
                            reason=edge_reason,
                        )
                    )

            elif rel == "COMMAND_HANDLER":
                cmd_name = str(metadata.get("command") or target_canon.split(".")[-1])
                source_id = f"{b.base_expr}:{cmd_name}" if b.base_expr else cmd_name
                ev_evidence = f"Command handler '{target_canon}' registered for command '{cmd_name}' via '@{b.source_expr}'"
                add_ref(
                    Reference(
                        source_symbol_id=source_id,
                        target_symbol_id=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=source_id,
                        target=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        evidence_class=ev_class.value,
                        reason=edge_reason,
                    )
                )

            elif rel == "TASK_HANDLER":
                task_name = str(metadata.get("task_name") or target_canon)
                source_id = task_name if task_name != target_canon else b.source_expr
                ev_evidence = f"Task handler '{target_canon}' registered via '@{b.source_expr}'"
                add_ref(
                    Reference(
                        source_symbol_id=source_id,
                        target_symbol_id=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=source_id,
                        target=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        evidence_class=ev_class.value,
                        reason=edge_reason,
                    )
                )

            elif rel == "REGISTERS":
                source_id = f"{self.file_to_module.get(b.file_path) or normalize_module(b.file_path)}.{b.source_expr.split('.')[0]}"
                ev_evidence = f"Registry handler '{target_canon}' registered via '@{b.source_expr}'"
                add_ref(
                    Reference(
                        source_symbol_id=source_id,
                        target_symbol_id=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=source_id,
                        target=target_canon,
                        relationship=rel,
                        confidence=edge_conf,
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_evidence,
                        evidence_class=ev_class.value,
                        reason=edge_reason,
                    )
                )

        # 9. Dependency Injection & Configuration Intelligence
        # 9a. Statically grounded provider registration (PROVIDES)
        provider_map: dict[str, list[tuple[str, BindingRef, str]]] = {}
        for b in self.bindings:
            if b.expr_kind == "SEMANTIC_DECORATOR" and b.attr_name == "PROVIDES":
                if b.subscript_target is not None:
                    findings.append({
                        "pattern": "DI_PROVIDES",
                        "status": "UNKNOWN",
                        "reason": b.subscript_target or "dynamic_provider",
                        "file": b.file_path,
                        "line": b.line,
                        "target_name": b.target_name,
                    })
                    continue
                dec_meta: dict[str, object] = {}
                if b.subscript_key:
                    try:
                        dec_meta = json.loads(b.subscript_key)
                    except Exception:
                        dec_meta = {}
                iface_raw = str(dec_meta.get("interface") or "")
                impl_canon = b.target_name
                iface_canon = impl_canon
                if iface_raw and iface_raw != impl_canon.split(".")[-1]:
                    if_sym, _, _ = self.resolve_identifier_in_file(iface_raw, b.file_path, use_line=b.line)
                    if not if_sym and len(self.short_to_symbols.get(iface_raw, [])) == 1:
                        if_sym = self.short_to_symbols[iface_raw][0]
                    if if_sym:
                        iface_canon = if_sym.canonical_id
                provider_map.setdefault(iface_canon, []).append((impl_canon, b, "decorator_provider"))
                continue

            if b.expr_kind != "DI_PROVIDES":
                continue

            if (
                b.subscript_target == "dynamic_provider"
                or b.target_name == "<DYNAMIC>"
                or b.source_expr == "<DYNAMIC>"
            ):
                findings.append({
                    "pattern": "DI_PROVIDES",
                    "status": "UNKNOWN",
                    "reason": "dynamic_provider",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })
                continue

            iface_sym, _, _ = self.resolve_identifier_in_file(b.target_name, b.file_path, use_line=b.line)
            if not iface_sym and len(self.short_to_symbols.get(b.target_name, [])) == 1:
                iface_sym = self.short_to_symbols[b.target_name][0]

            impl_sym, _, _ = self.resolve_identifier_in_file(b.source_expr, b.file_path, use_line=b.line)
            if not impl_sym and len(self.short_to_symbols.get(b.source_expr, [])) == 1:
                impl_sym = self.short_to_symbols[b.source_expr][0]

            if not iface_sym or not impl_sym:
                findings.append({
                    "pattern": "DI_PROVIDES",
                    "status": "UNKNOWN",
                    "reason": "dynamic_provider",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                    "source_expr": b.source_expr,
                })
                continue

            iface_canon = iface_sym.canonical_id
            impl_canon = impl_sym.canonical_id
            # For 1-arg container.provide(Impl) / container.singleton(Impl), check if Impl extends a base interface
            if iface_canon == impl_canon and b.target_name == b.source_expr:
                for inh in inheritance_by_source.get(impl_canon, ()):
                    base_sym, _, _ = self.resolve_identifier_in_file(inh.base_name, inh.source_file, use_line=inh.line)
                    if not base_sym and len(self.short_to_symbols.get(inh.base_name, [])) == 1:
                        base_sym = self.short_to_symbols[inh.base_name][0]
                    if base_sym:
                        iface_canon = base_sym.canonical_id
                        break
            provider_map.setdefault(iface_canon, []).append((impl_canon, b, "provider_mapping"))

        # Emit PROVIDES edges (Ambiguity: multiple distinct providers -> POSSIBLE)
        for iface_canon, reg_list in provider_map.items():
            distinct_impls = set(impl_c for impl_c, _, _ in reg_list)
            is_ambiguous = len(distinct_impls) > 1

            for impl_canon, b, _ in reg_list:
                f_hash = self.file_hashes.get(b.file_path, "")
                if is_ambiguous:
                    ev_class = RelationshipEvidenceClass.POSSIBLE
                    edge_conf = "LOW"
                    edge_reason = "multiple_providers"
                elif b.is_conditional:
                    ev_class = RelationshipEvidenceClass.POSSIBLE
                    edge_conf = "LOW"
                    edge_reason = "conditional_provider"
                else:
                    ev_class = RelationshipEvidenceClass.DATAFLOW_VERIFIED
                    edge_conf = "HIGH"
                    edge_reason = f"Statically verified provider mapping '{b.target_name}' -> '{impl_canon}'"

                ev_str = f"Provider mapping: {iface_canon} PROVIDES {impl_canon} at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=iface_canon,
                        target_symbol_id=impl_canon,
                        relationship="PROVIDES",
                        confidence=edge_conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=iface_canon,
                        target=impl_canon,
                        relationship="PROVIDES",
                        confidence=edge_conf,
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=ev_class.value,
                        reason=edge_reason,
                    )
                )

        # 9b. Dependency Resolution (RESOLVES_DEPENDENCY)
        for b in bindings_by_kind.get("DI_RESOLVES", ()):
            if b.subscript_target == "dynamic_provider" or b.target_name == "<DYNAMIC>":
                findings.append({
                    "pattern": "DI_RESOLVES",
                    "status": "UNKNOWN",
                    "reason": "dynamic_provider",
                    "file": b.file_path,
                    "line": b.line,
                })
                continue

            iface_sym, _, _ = self.resolve_identifier_in_file(b.target_name, b.file_path, use_line=b.line)
            if not iface_sym and len(self.short_to_symbols.get(b.target_name, [])) == 1:
                iface_sym = self.short_to_symbols[b.target_name][0]

            if not iface_sym:
                findings.append({
                    "pattern": "DI_RESOLVES",
                    "status": "UNKNOWN",
                    "reason": "unknown_dependency_interface",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })
                continue

            iface_canon = iface_sym.canonical_id
            if iface_canon not in provider_map:
                findings.append({
                    "pattern": "DI_RESOLVES",
                    "status": "UNKNOWN",
                    "reason": "no_provider_registered",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })
                continue

            reg_list = provider_map[iface_canon]
            distinct_impls = set(impl_c for impl_c, _, _ in reg_list)
            is_ambiguous = len(distinct_impls) > 1

            if is_ambiguous:
                findings.append({
                    "pattern": "DI_RESOLVES",
                    "status": "POSSIBLE",
                    "reason": "multiple_providers",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })

            for impl_canon, _orig_b, _ in reg_list:
                f_hash = self.file_hashes.get(b.file_path, "")
                if is_ambiguous:
                    ev_class = RelationshipEvidenceClass.POSSIBLE
                    edge_conf = "LOW"
                    edge_reason = "multiple_providers"
                else:
                    ev_class = RelationshipEvidenceClass.DATAFLOW_VERIFIED
                    edge_conf = "HIGH"
                    edge_reason = f"Deterministic dependency resolution '{iface_canon}' -> '{impl_canon}'"

                ev_str = f"Dependency resolution: {iface_canon} RESOLVES_DEPENDENCY {impl_canon} at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=iface_canon,
                        target_symbol_id=impl_canon,
                        relationship="RESOLVES_DEPENDENCY",
                        confidence=edge_conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=iface_canon,
                        target=impl_canon,
                        relationship="RESOLVES_DEPENDENCY",
                        confidence=edge_conf,
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=ev_class.value,
                        reason=edge_reason,
                    )
                )

        # 9c. FastAPI Depends(...) Injection (INJECTS)
        for b in (
            bindings_by_kind.get("ROUTER_DI_INJECTS", [])
            + bindings_by_kind.get("DI_INJECTS", [])
        ):
            if b.expr_kind == "ROUTER_DI_INJECTS":
                if b.subscript_target == "dynamic_provider" or b.source_expr == "<DYNAMIC>":
                    findings.append({
                        "pattern": "DI_INJECTS",
                        "status": "UNKNOWN",
                        "reason": "dynamic_provider",
                        "file": b.file_path,
                        "line": b.line,
                        "target_name": b.target_name,
                    })
                    continue

                dep_sym, _, _ = self.resolve_identifier_in_file(b.source_expr, b.file_path, use_line=b.line)
                if not dep_sym and len(self.short_to_symbols.get(b.source_expr, [])) == 1:
                    dep_sym = self.short_to_symbols[b.source_expr][0]
                if not dep_sym:
                    findings.append({
                        "pattern": "DI_INJECTS",
                        "status": "UNKNOWN",
                        "reason": "unknown_dependency_target",
                        "file": b.file_path,
                        "line": b.line,
                        "source_expr": b.source_expr,
                    })
                    continue

                dep_canon = dep_sym.canonical_id
                router_var = b.target_name
                # Also resolve if router_var was imported into b.file_path (e.g. app.include_router(users_router, dependencies=[...]))
                router_sym, _, _ = self.resolve_identifier_in_file(router_var, b.file_path, use_line=b.line)
                target_router_names = {router_var}
                if router_sym:
                    target_router_names.add(router_sym.name)
                for imp in self.file_imports.get(b.file_path, ()):
                    if imp.local_name == router_var or imp.alias == router_var or imp.name == router_var:
                        if imp.imported_name:
                            target_router_names.add(imp.imported_name)

                for rt in self.routes:
                    matches_router = (
                        rt.router_name in target_router_names
                        or (router_var == "app" and rt.file_path == b.file_path)
                    )
                    if not matches_router:
                        continue
                    rt_f_hash = self.file_hashes.get(rt.file_path, "")
                    if rt.handler_canonical_id:
                        h_ev = f"Router/App Depends: '{rt.handler_canonical_id}' INJECTS '{dep_canon}' via '{router_var}' at {b.file_path}:{b.line}"
                        add_ref(
                            Reference(
                                source_symbol_id=rt.handler_canonical_id,
                                target_symbol_id=dep_canon,
                                relationship="INJECTS",
                                confidence="HIGH",
                                path=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=h_ev,
                                source_hash=rt_f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=rt.handler_canonical_id,
                                target=dep_canon,
                                relationship="INJECTS",
                                confidence="HIGH",
                                file=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=h_ev,
                                evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                                reason="fastapi_router_depends",
                            )
                        )
                    rt_ev = f"Route endpoint '{rt.endpoint_id}' INJECTS '{dep_canon}' via '{router_var}' at {b.file_path}:{b.line}"
                    add_ref(
                        Reference(
                            source_symbol_id=rt.endpoint_id,
                            target_symbol_id=dep_canon,
                            relationship="INJECTS",
                            confidence="HIGH",
                            path=rt.file_path,
                            start_line=rt.line,
                            end_line=rt.line,
                            evidence=rt_ev,
                            source_hash=rt_f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=rt.endpoint_id,
                            target=dep_canon,
                            relationship="INJECTS",
                            confidence="HIGH",
                            file=rt.file_path,
                            start_line=rt.line,
                            end_line=rt.line,
                            evidence=rt_ev,
                            evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                            reason="fastapi_router_depends",
                        )
                    )
                continue

            if b.subscript_target == "dynamic_provider" or b.source_expr == "<DYNAMIC>":
                findings.append({
                    "pattern": "DI_INJECTS",
                    "status": "UNKNOWN",
                    "reason": "dynamic_provider",
                    "file": b.file_path,
                    "line": b.line,
                    "target_name": b.target_name,
                })
                continue

            dep_sym, _, _ = self.resolve_identifier_in_file(b.source_expr, b.file_path, use_line=b.line)
            if not dep_sym and len(self.short_to_symbols.get(b.source_expr, [])) == 1:
                dep_sym = self.short_to_symbols[b.source_expr][0]

            if not dep_sym:
                findings.append({
                    "pattern": "DI_INJECTS",
                    "status": "UNKNOWN",
                    "reason": "unknown_dependency_target",
                    "file": b.file_path,
                    "line": b.line,
                    "source_expr": b.source_expr,
                })
                continue

            dep_canon = dep_sym.canonical_id
            handler_canon = b.target_name
            f_hash = self.file_hashes.get(b.file_path, "")
            ev_str = f"FastAPI Depends: '{handler_canon}' INJECTS '{dep_canon}' at {b.file_path}:{b.line}"

            add_ref(
                Reference(
                    source_symbol_id=handler_canon,
                    target_symbol_id=dep_canon,
                    relationship="INJECTS",
                    confidence="HIGH",
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=handler_canon,
                    target=dep_canon,
                    relationship="INJECTS",
                    confidence="HIGH",
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                    reason="fastapi_depends",
                )
            )

            # Also link matching route endpoint_id -> dep_canon
            handler_short = handler_canon.split(".")[-1]
            for rt in self.routes:
                if rt.handler_canonical_id == handler_canon or rt.handler_name == handler_short:
                    rt_ev = f"Route endpoint '{rt.endpoint_id}' INJECTS '{dep_canon}' at {rt.file_path}:{rt.line}"
                    add_ref(
                        Reference(
                            source_symbol_id=rt.endpoint_id,
                            target_symbol_id=dep_canon,
                            relationship="INJECTS",
                            confidence="HIGH",
                            path=rt.file_path,
                            start_line=rt.line,
                            end_line=rt.line,
                            evidence=rt_ev,
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=rt.endpoint_id,
                            target=dep_canon,
                            relationship="INJECTS",
                            confidence="HIGH",
                            file=rt.file_path,
                            start_line=rt.line,
                            end_line=rt.line,
                            evidence=rt_ev,
                            evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                            reason="fastapi_depends",
                        )
                    )

        # 9d. Constructor & @inject Type-Based Injection (INJECTS)
        for b in bindings_by_kind.get("CONSTRUCTOR_PARAM", ()):
            ann_sym, _, _ = self.resolve_identifier_in_file(b.source_expr, b.file_path, use_line=b.line)
            if not ann_sym and len(self.short_to_symbols.get(b.source_expr, [])) == 1:
                ann_sym = self.short_to_symbols[b.source_expr][0]

            if not ann_sym:
                continue

            ann_canon = ann_sym.canonical_id
            # Rule: Only create injection relationship when supported DI semantics exist!
            # i.e., provider mapping exists for this interface OR @inject decorator was present
            has_provider = ann_canon in provider_map
            is_inject_dec = (b.base_expr == "inject_decorator")

            if not (has_provider or is_inject_dec):
                continue

            f_hash = self.file_hashes.get(b.file_path, "")
            caller_canon = b.target_name
            ev_str = f"Constructor injection: '{caller_canon}' INJECTS '{ann_canon}' (param='{b.attr_name}') at {b.file_path}:{b.line}"

            add_ref(
                Reference(
                    source_symbol_id=caller_canon,
                    target_symbol_id=ann_canon,
                    relationship="INJECTS",
                    confidence="HIGH",
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=caller_canon,
                    target=ann_canon,
                    relationship="INJECTS",
                    confidence="HIGH",
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=RelationshipEvidenceClass.DATAFLOW_VERIFIED.value,
                    reason="constructor_injection",
                )
            )

        # 9d-cycle. Static DI Cycle Detection (INJECTS / PROVIDES / RESOLVES_DEPENDENCY)
        di_adj: dict[str, list[tuple[str, str, int]]] = {}
        for ed in list(edges):
            if ed.relationship == "INJECTS" or (
                ed.relationship in ("PROVIDES", "RESOLVES_DEPENDENCY") and ed.source != ed.target
            ):
                if not ed.source.startswith("API_ENDPOINT:"):
                    di_adj.setdefault(ed.source, []).append((ed.target, ed.file or "", ed.start_line or 1))

        di_visit_state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited
        di_path_stack: list[str] = []
        reported_cycles: set[tuple[str, ...]] = set()

        def _detect_di_cycles(u_node: str) -> None:
            di_visit_state[u_node] = 1
            di_path_stack.append(u_node)
            for v_node, ed_file, ed_line in di_adj.get(u_node, []):
                st = di_visit_state.get(v_node, 0)
                if st == 1:
                    # Found cycle!
                    if v_node in di_path_stack:
                        c_idx = di_path_stack.index(v_node)
                        cycle_seq = tuple(di_path_stack[c_idx:] + [v_node])
                    else:
                        cycle_seq = (u_node, v_node, u_node)
                    if cycle_seq not in reported_cycles:
                        reported_cycles.add(cycle_seq)
                        cycle_str = " -> ".join(cycle_seq)
                        findings.append({
                            "pattern": "DI_CYCLE",
                            "status": "CONFLICT",
                            "reason": "di_dependency_cycle",
                            "file": ed_file,
                            "line": ed_line,
                            "source": u_node,
                            "target": v_node,
                            "cycle": list(cycle_seq),
                        })
                        add_edge(
                            GraphEdge(
                                source=u_node,
                                target=v_node,
                                relationship="DI_CYCLE",
                                confidence="HIGH",
                                file=ed_file,
                                start_line=ed_line,
                                end_line=ed_line,
                                evidence=f"Circular dependency detected: {cycle_str}",
                                evidence_class=RelationshipEvidenceClass.DATAFLOW_VERIFIED.value,
                                reason="di_dependency_cycle",
                            )
                        )
                elif st == 0:
                    _detect_di_cycles(v_node)
            di_path_stack.pop()
            di_visit_state[u_node] = 2

        for start_n in sorted(di_adj.keys()):
            if di_visit_state.get(start_n, 0) == 0:
                _detect_di_cycles(start_n)

        # 9e. Environment & Configuration References (CONFIGURES)
        for b in (
            bindings_by_kind.get("ENV_CONFIG", [])
            + bindings_by_kind.get("DYNAMIC_CONFIG", [])
        ):
            if (
                b.subscript_target in ("runtime_configuration", "dynamic_provider")
                or b.target_name == "<DYNAMIC>"
            ):
                findings.append({
                    "pattern": b.expr_kind,
                    "status": "UNKNOWN",
                    "reason": b.subscript_target or "runtime_configuration",
                    "file": b.file_path,
                    "line": b.line,
                })
                continue

            var_name = b.target_name
            target_scope = b.scope or (self.file_to_module.get(b.file_path) or normalize_module(b.file_path))
            f_hash = self.file_hashes.get(b.file_path, "")
            ev_str = f"Environment reference '{var_name}' CONFIGURES '{target_scope}' at {b.file_path}:{b.line}"

            add_ref(
                Reference(
                    source_symbol_id=var_name,
                    target_symbol_id=target_scope,
                    relationship="CONFIGURES",
                    confidence="HIGH",
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    source_hash=f_hash,
                    indexed_commit=self.indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=var_name,
                    target=target_scope,
                    relationship="CONFIGURES",
                    confidence="HIGH",
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=RelationshipEvidenceClass.DATAFLOW_VERIFIED.value,
                    reason="environment_reference",
                )
            )

        # 10. Test Intelligence & Deterministic Test Discovery
        def _find_caller_id_for_binding(b: BindingRef) -> str:
            for s in self.path_to_symbols.get(b.file_path, ()):
                if s.start_line <= b.line <= s.end_line:
                    return s.canonical_id
            mod = self.file_to_module.get(b.file_path) or normalize_module(b.file_path)
            return f"{mod}.{b.scope}" if b.scope else mod

        # 10a. Direct Test Calls (TESTS)
        # Any call originating from a test file to a production symbol
        for call in self.calls:
            if not _TEST_FILE_RE.search(call.source_file):
                continue
            t_caller_id: str = call.caller_canonical_id or (self.file_to_module.get(call.source_file) or normalize_module(call.source_file))
            callee_key = (call.source_file, call.line, call.callee)
            if callee_key not in resolved_calls:
                callee_key = (call.source_file, call.line, call.qualified_callee or call.callee)
            if callee_key in resolved_calls:
                res_canon, conf = resolved_calls[callee_key]
                if res_canon and res_canon != t_caller_id:
                    t_target_canon: str = res_canon
                    f_hash = self.file_hashes.get(call.source_file, "")
                    ev_str = f"Test directly exercises symbol '{t_target_canon}' at {call.source_file}:{call.line}"
                    add_ref(
                        Reference(
                            source_symbol_id=t_caller_id,
                            target_symbol_id=t_target_canon,
                            relationship="TESTS",
                            confidence=conf,
                            path=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=ev_str,
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=t_caller_id,
                            target=t_target_canon,
                            relationship="TESTS",
                            confidence=conf,
                            file=call.source_file,
                            start_line=call.line,
                            end_line=call.end_line,
                            evidence=ev_str,
                            evidence_class=RelationshipEvidenceClass.AST_VERIFIED.value,
                            reason="direct_test_call",
                        )
                    )

        # 10b. Test Route Intelligence (TESTS_ROUTE & handler coverage)
        for b in (
            bindings_by_kind.get("TEST_ROUTE", [])
            + bindings_by_kind.get("TEST_PAGE_GOTO", [])
        ):
            if b.expr_kind == "TEST_ROUTE":
                target_route = b.subscript_key
                http_method = b.source_expr.upper()  # e.g. "POST", "GET"
                caller_id = _find_caller_id_for_binding(b)

                if not target_route or target_route == "<DYNAMIC>":
                    findings.append({
                        "pattern": "TEST_ROUTE",
                        "status": "UNKNOWN",
                        "reason": "dynamic_test_route",
                        "file": b.file_path,
                        "line": b.line,
                    })
                    continue

                clean_target = posixpath.normpath(target_route.split("?")[0])
                matched = [
                    r for r in self.routes
                    if (posixpath.normpath(r.route_path) == clean_target or posixpath.normpath(r.normalized_route) == clean_target)
                    and (r.http_method == http_method or http_method in ("REQUEST", ""))
                ]

                if not matched:
                    matched = [
                        r for r in self.routes
                        if (r.route_path.rstrip("/") == clean_target.rstrip("/") or r.normalized_route.rstrip("/") == clean_target.rstrip("/"))
                        and (r.http_method == http_method or http_method in ("REQUEST", ""))
                    ]

                if matched:
                    for r in matched:
                        f_hash = self.file_hashes.get(b.file_path, "")
                        ev_str = f"Test client exercises route '{r.route_path}' [{r.http_method}] at {b.file_path}:{b.line}"
                        add_ref(
                            Reference(
                                source_symbol_id=caller_id,
                                target_symbol_id=r.endpoint_id,
                                relationship="TESTS_ROUTE",
                                confidence="HIGH",
                                path=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_str,
                                source_hash=f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=caller_id,
                                target=r.endpoint_id,
                                relationship="TESTS_ROUTE",
                                confidence="HIGH",
                                file=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_str,
                                evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                                reason=f"http_client_test:{r.http_method} {r.route_path}",
                            )
                        )
                        if r.handler_canonical_id:
                            h_ev = f"Route test exercises handler '{r.handler_name}' via '{r.route_path}' at {b.file_path}:{b.line}"
                            add_ref(
                                Reference(
                                    source_symbol_id=caller_id,
                                    target_symbol_id=r.handler_canonical_id,
                                    relationship="TESTS",
                                    confidence="MEDIUM",
                                    path=b.file_path,
                                    start_line=b.line,
                                    end_line=b.line,
                                    evidence=h_ev,
                                    source_hash=f_hash,
                                    indexed_commit=self.indexed_commit,
                                )
                            )
                            add_edge(
                                GraphEdge(
                                    source=caller_id,
                                    target=r.handler_canonical_id,
                                    relationship="TESTS",
                                    confidence="MEDIUM",
                                    file=b.file_path,
                                    start_line=b.line,
                                    end_line=b.line,
                                    evidence=h_ev,
                                    evidence_class=RelationshipEvidenceClass.POSSIBLE.value,
                                    reason=f"route_handler_test:{r.route_path}",
                                )
                            )
                else:
                    findings.append({
                        "pattern": "TEST_ROUTE",
                        "status": "UNKNOWN",
                        "reason": f"unmatched_test_route:{clean_target}",
                        "file": b.file_path,
                        "line": b.line,
                    })

            elif b.expr_kind == "TEST_PAGE_GOTO":
                target_url = b.subscript_key
                caller_id = _find_caller_id_for_binding(b)

                if not target_url or target_url == "<DYNAMIC>":
                    findings.append({
                        "pattern": "PLAYWRIGHT_ROUTE",
                        "status": "UNKNOWN",
                        "reason": "runtime_navigation",
                        "file": b.file_path,
                        "line": b.line,
                    })
                    continue

                clean_url = target_url
                if "://" in clean_url:
                    clean_url = "/" + clean_url.split("://", 1)[1].split("/", 1)[-1] if "/" in clean_url.split("://", 1)[1] else "/"
                clean_url = posixpath.normpath(clean_url.split("?")[0].split("#")[0])

                matched = [
                    r for r in self.routes
                    if posixpath.normpath(r.route_path) == clean_url or posixpath.normpath(r.normalized_route) == clean_url
                    or r.route_path.rstrip("/") == clean_url.rstrip("/")
                ]
                if matched:
                    for r in matched:
                        f_hash = self.file_hashes.get(b.file_path, "")
                        ev_str = f"Playwright page.goto exercises route '{r.route_path}' at {b.file_path}:{b.line}"
                        add_ref(
                            Reference(
                                source_symbol_id=caller_id,
                                target_symbol_id=r.endpoint_id,
                                relationship="TESTS_ROUTE",
                                confidence="HIGH",
                                path=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_str,
                                source_hash=f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=caller_id,
                                target=r.endpoint_id,
                                relationship="TESTS_ROUTE",
                                confidence="HIGH",
                                file=b.file_path,
                                start_line=b.line,
                                end_line=b.line,
                                evidence=ev_str,
                                evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                                reason=f"playwright_goto:{r.route_path}",
                            )
                        )
                        if r.handler_canonical_id:
                            add_edge(
                                GraphEdge(
                                    source=caller_id,
                                    target=r.handler_canonical_id,
                                    relationship="TESTS",
                                    confidence="MEDIUM",
                                    file=b.file_path,
                                    start_line=b.line,
                                    end_line=b.line,
                                    evidence=ev_str,
                                    evidence_class=RelationshipEvidenceClass.POSSIBLE.value,
                                    reason=f"playwright_handler_test:{r.route_path}",
                                )
                            )
                else:
                    findings.append({
                        "pattern": "PLAYWRIGHT_ROUTE",
                        "status": "POSSIBLE",
                        "reason": f"unmatched_browser_url:{clean_url}",
                        "file": b.file_path,
                        "line": b.line,
                    })

        # 10c. DI / Provider Test Intelligence (TESTS_PROVIDER)
        fixture_defs: dict[str, str] = {}
        for b in bindings_by_kind.get("PYTEST_FIXTURE_DEF", ()):
            fixture_defs[b.target_name] = b.source_expr

        for b in bindings_by_kind.get("TEST_FIXTURE_USE", ()):
            fix_name = b.target_name
            caller_id = _find_caller_id_for_binding(b)

            target_prov_sym = None
            if fix_name in fixture_defs:
                ret_nm = fixture_defs[fix_name]
                target_prov_sym, _, _ = self.resolve_identifier_in_file(ret_nm, b.file_path, use_line=b.line)
                if not target_prov_sym and ret_nm in self.short_to_symbols:
                    target_prov_sym = self.short_to_symbols[ret_nm][0]
            if not target_prov_sym:
                target_prov_sym, _, _ = self.resolve_identifier_in_file(fix_name, b.file_path, use_line=b.line)
            if not target_prov_sym and fix_name in self.short_to_symbols:
                target_prov_sym = self.short_to_symbols[fix_name][0]

            if target_prov_sym:
                f_hash = self.file_hashes.get(b.file_path, "")
                ev_str = f"Test fixture '{fix_name}' provides '{target_prov_sym.canonical_id}' at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=target_prov_sym.canonical_id,
                        relationship="TESTS_PROVIDER",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=self.indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=target_prov_sym.canonical_id,
                        relationship="TESTS_PROVIDER",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.DATAFLOW_VERIFIED.value,
                        reason=f"fixture_dependency_provider:{fix_name}",
                    )
                )

        # 10d. Event Dispatch & Registry Invocations in Tests
        for b in bindings_by_kind.get("EVENT_DISPATCH", ()):
            event_name = b.subscript_key
            caller_id = _find_caller_id_for_binding(b)

            if not event_name or event_name == "<DYNAMIC>":
                findings.append({
                    "pattern": "EVENT_DISPATCH",
                    "status": "UNKNOWN",
                    "reason": "dynamic_event_name",
                    "file": b.file_path,
                    "line": b.line,
                })
                continue

            matched_listeners = event_listeners_by_key.get(event_name, ())
            for b2 in matched_listeners:
                target_handler, _, _ = self.resolve_identifier_in_file(b2.source_expr, b2.file_path, use_line=b2.line)
                if not target_handler and b2.source_expr in self.short_to_symbols:
                    target_handler = self.short_to_symbols[b2.source_expr][0]
                if target_handler:
                    f_hash = self.file_hashes.get(b.file_path, "")
                    ev_str = f"Test dispatches event '{event_name}' exercising listener '{target_handler.canonical_id}' at {b.file_path}:{b.line}"
                    add_ref(
                        Reference(
                            source_symbol_id=caller_id,
                            target_symbol_id=target_handler.canonical_id,
                            relationship="TESTS_EVENT_HANDLER",
                            confidence="MEDIUM",
                            path=b.file_path,
                            start_line=b.line,
                            end_line=b.line,
                            evidence=ev_str,
                            source_hash=f_hash,
                            indexed_commit=self.indexed_commit,
                        )
                    )
                    add_edge(
                        GraphEdge(
                            source=caller_id,
                            target=target_handler.canonical_id,
                            relationship="TESTS_EVENT_HANDLER",
                            confidence="MEDIUM",
                            file=b.file_path,
                            start_line=b.line,
                            end_line=b.line,
                            evidence=ev_str,
                            evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                            reason=f"event_dispatch_test:{event_name}",
                        )
                    )

        # 12. Monorepo / Workspace package dependencies
        if self.workspace and self.workspace.dependencies:
            for dep in self.workspace.dependencies:
                src_pkg = self.workspace.packages.get(dep.source_package_id)
                edge_file = ""
                if src_pkg:
                    for ep in src_pkg.entrypoints:
                        if ep in self.known_files:
                            edge_file = ep
                            break
                    if not edge_file and src_pkg.root_path:
                        for kf in self.known_files:
                            if kf.startswith(f"{src_pkg.root_path}/"):
                                edge_file = kf
                                break
                    if not edge_file and src_pkg.manifest_path in self.known_files:
                        edge_file = src_pkg.manifest_path

                if edge_file:
                    add_edge(
                        GraphEdge(
                            source=dep.source_package_id,
                            target=dep.target_package_id,
                            relationship="DEPENDS_ON_PACKAGE",
                            confidence="HIGH",
                            file=edge_file,
                            start_line=1,
                            end_line=1,
                            evidence=dep.evidence or f"{dep.source_name} depends on {dep.target_name}",
                            evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                            reason="workspace_package_manifest_dependency",
                        )
                    )

        return ResolutionOutput(
            references=references,
            edges=edges,
            resolved_imports=resolved_imports,
            resolved_calls=resolved_calls,
            findings=findings,
        )


def resolve_symbol_diagnostic(
    con: sqlite3.Connection,
    expression: str,
    context_file: str | None = None,
) -> dict[str, object]:
    """Provide structured diagnostic output for `codegraph resolve <expression>`."""
    expr = expression.strip()
    if not expr:
        return {
            "input": expr,
            "confidence": "UNKNOWN",
            "reason": "Empty symbol expression.",
        }

    # 1. Direct canonical or qualified match in symbols table
    direct = con.execute(
        "SELECT canonical_id, qualified_name, module, path, start_line "
        "FROM symbols WHERE canonical_id=? OR qualified_name=? ORDER BY path, start_line LIMIT 1",
        (expr, expr),
    ).fetchone()

    # Check if expr starts with an imported alias first (e.g., AS.login or authenticate)
    prefix = expr.split(".", 1)[0]
    rest = expr.split(".", 1)[1] if "." in expr else ""

    imp_query = (
        "SELECT source_path, module, imported_module, name, imported_name, alias, local_name, resolved_module "
        "FROM imports WHERE (alias=? OR local_name=?)"
    )
    params: list[object] = [prefix, prefix]
    if context_file:
        imp_query += " AND source_path=?"
        params.append(context_file)
    imp_rows = con.execute(imp_query, params).fetchall()

    for imp in imp_rows:
        target_mod = imp["resolved_module"] or imp["imported_module"] or imp["module"]
        orig_name = imp["imported_name"] or imp["name"] or prefix
        candidate_qname = f"{orig_name}.{rest}" if rest else orig_name
        sym_row = con.execute(
            "SELECT canonical_id, qualified_name, module, path, start_line "
            "FROM symbols WHERE (module=? OR module LIKE ?) AND (qualified_name=? OR name=?) "
            "ORDER BY path, start_line LIMIT 1",
            (target_mod, f"%.{target_mod}", candidate_qname, candidate_qname),
        ).fetchone()
        if sym_row:
            return {
                "input": expr,
                "alias": imp["alias"] or imp["local_name"],
                "resolved_module": target_mod,
                "resolved_symbol": sym_row["qualified_name"],
                "canonical_id": sym_row["canonical_id"],
                "confidence": "HIGH",
                "evidence": f"{sym_row['path']}:{sym_row['start_line']}",
            }

    if direct:
        return {
            "input": expr,
            "alias": None,
            "resolved_module": direct["module"],
            "resolved_symbol": direct["qualified_name"],
            "canonical_id": direct["canonical_id"],
            "confidence": "HIGH",
            "evidence": f"{direct['path']}:{direct['start_line']}",
        }

    # Check short name match
    short_rows = con.execute(
        "SELECT canonical_id, qualified_name, module, path, start_line FROM symbols WHERE name=?",
        (expr,),
    ).fetchall()
    if len(short_rows) == 1:
        r = short_rows[0]
        return {
            "input": expr,
            "alias": None,
            "resolved_module": r["module"],
            "resolved_symbol": r["qualified_name"],
            "canonical_id": r["canonical_id"],
            "confidence": "MEDIUM",
            "evidence": f"{r['path']}:{r['start_line']}",
        }
    if len(short_rows) > 1:
        return {
            "input": expr,
            "confidence": "LOW",
            "reason": f"Ambiguous symbol '{expr}' found in {len(short_rows)} modules: "
            + ", ".join(r["canonical_id"] for r in short_rows[:5]),
        }

    return {
        "input": expr,
        "confidence": "UNKNOWN",
        "reason": "No matching imported symbol found.",
    }
