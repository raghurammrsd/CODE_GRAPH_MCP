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

import posixpath
import sqlite3
from dataclasses import dataclass

from codegraph.frameworks import RouteDetection
from codegraph.graph.models import GraphEdge
from codegraph.indexing.models import (
    CallRef,
    ImportRef,
    InheritanceRef,
    Reference,
    Symbol,
    normalize_module,
)


def resolve_module_to_path(
    imported_module: str,
    source_file: str,
    known_files: set[str],
) -> str | None:
    """Deterministically resolve an import specifier to a repository-relative file path.

    Never guesses files outside `known_files`.
    """
    if not imported_module:
        return None

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
    ) -> None:
        self.symbols = symbols
        self.imports = imports
        self.calls = calls
        self.inheritance = inheritance
        self.routes = routes
        self.known_files = known_files
        self.file_hashes = file_hashes
        self.indexed_commit = indexed_commit

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

    @staticmethod
    def resolve_symbol_diagnostic(con: sqlite3.Connection, query: str) -> dict[str, object]:
        return resolve_symbol_diagnostic(con, query)

    def _resolve_import_target_module(self, imp: ImportRef) -> tuple[str | None, str | None]:
        """Return (resolved_file_path, resolved_module) for an ImportRef."""
        target_path = resolve_module_to_path(
            imp.imported_module, imp.source_file, self.known_files
        )
        if target_path:
            return target_path, normalize_module(target_path)

        # Maybe imported_module is `pkg.mod.Symbol` where `pkg.mod` is a file
        if "." in imp.imported_module and not imp.imported_module.startswith("."):
            parent_mod, last_seg = imp.imported_module.rsplit(".", 1)
            parent_path = resolve_module_to_path(
                parent_mod, imp.source_file, self.known_files
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
                self.wildcard_reexports.setdefault(src_mod, []).append(target_mod)
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
    ) -> Symbol | None:
        """Resolve `symbol_name` in `module`, following re-export chains deterministically."""
        visited = visited or set()
        key = (module, symbol_name)
        if key in visited:
            return None
        visited.add(key)

        # 1. Direct symbol in module
        mod_syms = self.module_to_symbols.get(module, {})
        if symbol_name in mod_syms:
            return mod_syms[symbol_name]

        # Check canonical ID directly
        canon_cand = f"{module}.{symbol_name}"
        if canon_cand in self.canonical_to_symbol:
            return self.canonical_to_symbol[canon_cand]

        # If symbol_name is dotted (e.g. AS.login or AuthService.login), resolve prefix first
        if "." in symbol_name:
            prefix, rest = symbol_name.split(".", 1)
            base_sym = self.resolve_symbol_in_module(module, prefix, visited=set(visited))
            if base_sym:
                method_canon = f"{base_sym.canonical_id}.{rest}"
                if method_canon in self.canonical_to_symbol:
                    return self.canonical_to_symbol[method_canon]

        # 2. Named re-export in this module
        if key in self.reexport_map:
            target_mod, orig_name = self.reexport_map[key]
            return self.resolve_symbol_in_module(target_mod, orig_name, visited)

        # 3. Wildcard re-exports in this module
        for target_mod in self.wildcard_reexports.get(module, []):
            found = self.resolve_symbol_in_module(target_mod, symbol_name, visited)
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
    ) -> tuple[Symbol | None, str, str]:
        """Resolve an identifier or dotted expression inside `source_file`.

        Returns (Symbol | None, confidence, resolution_reason).
        """
        src_mod = normalize_module(source_file)

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

        # Level 5: Exact qualified name match if unique across repository
        if "." in identifier and identifier in self.qualified_to_symbols:
            cands = self.qualified_to_symbols[identifier]
            if len(cands) == 1:
                return (
                    cands[0],
                    "MEDIUM",
                    f"Unique qualified symbol match '{cands[0].canonical_id}'",
                )

        return None, "UNKNOWN", "No matching local or imported symbol found."

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

        # 3. Resolve Call Sites
        for call in self.calls:
            f_hash = self.file_hashes.get(call.source_file, "")
            caller_id = call.caller_canonical_id or normalize_module(call.source_file)
            expr = call.qualified_callee or call.callee

            target_sym, conf, reason = self.resolve_identifier_in_file(
                expr, call.source_file, caller_id
            )

            # Check inherited method on base class if receiver was self/cls or local class
            if not target_sym and "." in expr:
                recv_part, method_part = expr.rsplit(".", 1)
                recv_sym, _rconf, _rreason = self.resolve_identifier_in_file(
                    recv_part, call.source_file, caller_id
                )
                if recv_sym and recv_sym.canonical_id in class_bases_map:
                    for base_canon in class_bases_map[recv_sym.canonical_id]:
                        cand_canon = f"{base_canon}.{method_part}"
                        if cand_canon in self.canonical_to_symbol:
                            target_sym = self.canonical_to_symbol[cand_canon]
                            conf = "HIGH"
                            reason = f"Inherited method on base class '{base_canon}'"
                            break

                # Conservative factory return type resolution
                if not target_sym and recv_sym and recv_sym.kind in ("function", "method") and recv_sym.return_type:
                    clean_ret = recv_sym.return_type.split("[")[0].strip()
                    ret_sym, _ret_conf, _ret_reason = self.resolve_identifier_in_file(
                        clean_ret, recv_sym.path, recv_sym.canonical_id
                    )
                    target_class_canon = ret_sym.canonical_id if ret_sym else f"{recv_sym.module}.{clean_ret}"
                    cand_canon = f"{target_class_canon}.{method_part}"
                    if cand_canon in self.canonical_to_symbol:
                        target_sym = self.canonical_to_symbol[cand_canon]
                        conf = "HIGH"
                        reason = f"Resolved via factory return type '{recv_sym.canonical_id}() -> {cand_canon}'"
                    elif target_class_canon in class_bases_map:
                        for base_canon in class_bases_map[target_class_canon]:
                            cand_base_canon = f"{base_canon}.{method_part}"
                            if cand_base_canon in self.canonical_to_symbol:
                                target_sym = self.canonical_to_symbol[cand_base_canon]
                                conf = "HIGH"
                                reason = f"Resolved via factory return inherited method '{recv_sym.canonical_id}() -> {cand_base_canon}'"
                                break

                    if target_sym:
                        add_ref(
                            Reference(
                                source_symbol_id=caller_id,
                                target_symbol_id=recv_sym.canonical_id,
                                relationship="CALLS",
                                confidence="HIGH",
                                path=call.source_file,
                                start_line=call.line,
                                end_line=call.end_line,
                                evidence=f"Call factory '{recv_sym.canonical_id}()' at {call.source_file}:{call.line}",
                                source_hash=f_hash,
                                indexed_commit=self.indexed_commit,
                            )
                        )
                        add_edge(
                            GraphEdge(
                                source=caller_id,
                                target=recv_sym.canonical_id,
                                relationship="CALLS",
                                confidence="HIGH",
                                file=call.source_file,
                                start_line=call.line,
                                end_line=call.end_line,
                                evidence=f"Resolved factory call {caller_id} -> {recv_sym.canonical_id} at {call.source_file}:{call.line}",
                            )
                        )

            if target_sym:
                resolved_calls[(call.source_file, call.line, call.callee)] = (
                    target_sym.canonical_id,
                    conf,
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
                        evidence=f"Resolved call {caller_id} -> {target_sym.canonical_id} at {call.source_file}:{call.line}",
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
                rt.handler_name, rt.file_path
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
                )
            )

        return ResolutionOutput(
            references=references,
            edges=edges,
            resolved_imports=resolved_imports,
            resolved_calls=resolved_calls,
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
