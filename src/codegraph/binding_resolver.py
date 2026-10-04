"""Conservative Deterministic Local Binding and Lightweight Data-Flow Engine.

Resolves:
- name -> symbol
- name -> imported symbol
- name -> module.attribute
- name -> function reference
- name -> class reference
- alias -> alias -> target (bounded chain)
- dictionary key -> symbol
- list element -> symbol
- simple assignment chains

Adheres to:
1. Lexical scope priority before module/global fallback (inner scopes shadow outer scopes)
2. Source-order awareness for sequential reassignments
3. Conditional/branching reassignments remain POSSIBLE or UNKNOWN
4. RESOLVES_TO is an identity/binding edge, never a CALLS edge
5. Attribute resolution only occurs when the base object is statically grounded
6. Conservative JS/TS handling
7. Cycle-safe with visited set and max_depth = 10
8. Bounded, deterministic, no runtime execution
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.indexing.models import BindingRef, ImportRef, Symbol

if TYPE_CHECKING:
    pass


class LocalBindingResolver:
    """Pure deterministic local variable binding and alias chain resolver."""

    def __init__(
        self,
        bindings: list[BindingRef],
        symbols: list[Symbol],
        imports: list[ImportRef],
        known_files: set[str],
        resolve_symbol_in_module: Callable[[str, str], Symbol | None],
        resolve_import_target: Callable[[ImportRef], tuple[str | None, str | None]],
    ) -> None:
        self.bindings = bindings
        self.symbols = symbols
        self.imports = imports
        self.known_files = known_files
        self.resolve_symbol_in_module = resolve_symbol_in_module
        self.resolve_import_target = resolve_import_target

        # Index bindings: (file_path, target_name) -> list[BindingRef] and target_name -> list[BindingRef]
        self.bindings_by_file_target: dict[tuple[str, str], list[BindingRef]] = {}
        self.bindings_by_target: dict[str, list[BindingRef]] = {}
        for b in bindings:
            self.bindings_by_file_target.setdefault((b.file_path, b.target_name), []).append(b)
            self.bindings_by_target.setdefault(b.target_name, []).append(b)

        # Ensure all binding lists are deterministically sorted by line
        for b_list in self.bindings_by_file_target.values():
            b_list.sort(key=lambda b: (b.line, b.column or 0))

        # Index symbols by (file_path, name) and canonical_id
        self.file_symbols: dict[tuple[str, str], list[Symbol]] = {}
        self.canonical_map: dict[str, Symbol] = {}
        for s in symbols:
            self.file_symbols.setdefault((s.path, s.name), []).append(s)
            self.canonical_map[s.canonical_id] = s

        # Index imports by (file_path, local_name)
        self.file_imports: dict[tuple[str, str], list[ImportRef]] = {}
        for imp in imports:
            loc = imp.local_name or imp.alias or imp.name or ""
            if loc:
                self.file_imports.setdefault((imp.source_file, loc), []).append(imp)

        self._resolve_cache: dict[
            tuple[str, str, str, int | None],
            tuple[str | None, RelationshipEvidenceClass, str],
        ] = {}

    def resolve(
        self,
        file_path: str,
        name: str,
        scope: str = "",
        use_line: int | None = None,
        visited: set[tuple[str, str, str]] | None = None,
        depth: int = 0,
    ) -> tuple[str | None, RelationshipEvidenceClass, str]:
        """Resolve a variable or alias identifier to its target canonical ID.

        Returns (canonical_id | None, evidence_class, reason).
        """
        is_top_level = visited is None and depth == 0
        cache_key = (file_path, name, scope, use_line)
        if is_top_level and cache_key in self._resolve_cache:
            return self._resolve_cache[cache_key]

        res = self._resolve_impl(file_path, name, scope, use_line, visited, depth)
        if is_top_level:
            self._resolve_cache[cache_key] = res
        return res

    def _resolve_impl(
        self,
        file_path: str,
        name: str,
        scope: str = "",
        use_line: int | None = None,
        visited: set[tuple[str, str, str]] | None = None,
        depth: int = 0,
    ) -> tuple[str | None, RelationshipEvidenceClass, str]:
        visited = visited or set()
        key = (file_path, scope, name)

        # Cycle protection
        if key in visited:
            return None, RelationshipEvidenceClass.UNKNOWN, "cyclic_alias"

        # Bounded depth
        if depth >= 10:
            return None, RelationshipEvidenceClass.UNKNOWN, "max_depth_exceeded"

        visited.add(key)

        # 1. Candidate scope search order (inner scopes shadow outer scopes)
        if scope:
            parts = scope.split(".")
            candidate_scopes = [".".join(parts[:i]) for i in range(len(parts), 0, -1)] + [""]
        else:
            candidate_scopes = [""]

        all_file_bindings = self.bindings_by_file_target.get((file_path, name), [])
        scope_bindings: list[BindingRef] = []
        matching_scope: str | None = None

        for scp in candidate_scopes:
            matched = [b for b in all_file_bindings if b.scope == scp]
            if matched:
                matching_scope = scp
                scope_bindings = matched
                break

        # If no local binding exists in any lexical scope:
        if not scope_bindings or matching_scope is None:
            ev_cls = (
                RelationshipEvidenceClass.DATAFLOW_VERIFIED
                if depth > 0
                else RelationshipEvidenceClass.AST_VERIFIED
            )
            # Check if name is an import in this file
            for imp in self.file_imports.get((file_path, name), []):
                _tpath, target_mod = self.resolve_import_target(imp)
                if target_mod:
                    orig_name = imp.imported_name or name
                    if orig_name != "*":
                        sym = self.resolve_symbol_in_module(target_mod, orig_name)
                        if sym:
                            return (
                                sym.canonical_id,
                                ev_cls,
                                f"imported_symbol -> {sym.canonical_id}",
                            )

            # Check if name is a direct symbol definition in this file
            for s in self.file_symbols.get((file_path, name), []):
                if not s.scope or s.scope in candidate_scopes:
                    return (
                        s.canonical_id,
                        ev_cls,
                        f"direct_symbol -> {s.canonical_id}",
                    )

            return None, RelationshipEvidenceClass.UNKNOWN, f"unresolved_identifier: {name}"

        # 2. Source-order awareness and sequential reassignment (all_file_bindings is pre-sorted)

        if use_line is not None:
            before = [b for b in scope_bindings if b.line <= use_line]
            if not before:
                # Forward reference (used before assignment)
                return None, RelationshipEvidenceClass.UNKNOWN, f"used_before_assignment: {name}"

            selected = before[-1]

            # 3. Conditional / branching assignments must remain POSSIBLE
            if selected.is_conditional:
                return None, RelationshipEvidenceClass.POSSIBLE, "conditional_binding"

            # Check for conditional ambiguity up to use_line
            if any(b.is_conditional for b in before):
                return None, RelationshipEvidenceClass.POSSIBLE, "conditional_ambiguity"
        else:
            if any(b.is_conditional for b in scope_bindings):
                return None, RelationshipEvidenceClass.POSSIBLE, "conditional_binding"
            if len(scope_bindings) > 1:
                return None, RelationshipEvidenceClass.UNKNOWN, "ambiguous_reassignment"
            selected = scope_bindings[0]

        # 4. Resolve RHS based on expression kind
        if selected.expr_kind == "DYNAMIC":
            return None, RelationshipEvidenceClass.UNKNOWN, "runtime_dynamic_attribute"

        if selected.expr_kind == "IDENTIFIER":
            rhs_name = selected.base_expr or selected.source_expr

            # Prevent immediate self-assignment
            if rhs_name == name and selected.scope == matching_scope:
                return None, RelationshipEvidenceClass.UNKNOWN, "cyclic_alias"

            # Check direct symbol in the same file
            for s in self.file_symbols.get((file_path, rhs_name), []):
                if not s.scope or s.scope in candidate_scopes:
                    return (
                        s.canonical_id,
                        RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                        f"local_alias -> {s.canonical_id}",
                    )

            # Check direct import in file
            for imp in self.file_imports.get((file_path, rhs_name), []):
                _tpath, target_mod = self.resolve_import_target(imp)
                if target_mod:
                    orig_name = imp.imported_name or rhs_name
                    if orig_name != "*":
                        sym = self.resolve_symbol_in_module(target_mod, orig_name)
                        if sym:
                            return (
                                sym.canonical_id,
                                RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                                f"imported_alias -> {sym.canonical_id}",
                            )

            # Otherwise recursively follow alias chain in same scope
            return self.resolve(
                file_path=file_path,
                name=rhs_name,
                scope=selected.scope,
                use_line=selected.line,
                visited=set(visited),
                depth=depth + 1,
            )

        if selected.expr_kind == "ATTRIBUTE":
            # Requirement 5: Base object must be statically grounded
            base = selected.base_expr
            attr = selected.attr_name

            grounded_mod: str | None = None
            grounded_sym: Symbol | None = None

            # Check if base is an imported module/symbol
            for imp in self.file_imports.get((file_path, base), []):
                _tpath, target_mod = self.resolve_import_target(imp)
                if target_mod:
                    if imp.import_type in ("namespace", "module") or imp.imported_name in (None, "*"):
                        grounded_mod = target_mod
                    else:
                        orig_name = imp.imported_name or base
                        grounded_sym = self.resolve_symbol_in_module(target_mod, orig_name)
                    break

            # Check if base is a class or top-level symbol in this file
            if not grounded_mod and not grounded_sym:
                if base in ("celery", "click", "app", "django", "typer"):
                    grounded_mod = base
                else:
                    for s in self.file_symbols.get((file_path, base), []):
                        if s.kind in ("class", "function", "method"):
                            grounded_sym = s
                            break

            # Check if base is a local alias that resolves to a grounded symbol
            if not grounded_mod and not grounded_sym:
                base_id, base_ev, _base_reason = self.resolve(
                    file_path=file_path,
                    name=base,
                    scope=selected.scope,
                    use_line=selected.line,
                    visited=set(visited),
                    depth=depth + 1,
                )
                if base_id and base_ev == RelationshipEvidenceClass.DATAFLOW_VERIFIED:
                    if base_id in self.canonical_map:
                        grounded_sym = self.canonical_map[base_id]

            if not grounded_mod and not grounded_sym:
                # Base is UNGROUNDED! Must return UNKNOWN
                return None, RelationshipEvidenceClass.UNKNOWN, f"unknown_attribute_base: {base}"

            # Base is grounded: resolve attribute
            if grounded_mod:
                target_sym = self.resolve_symbol_in_module(grounded_mod, attr)
                if target_sym:
                    return (
                        target_sym.canonical_id,
                        RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                        f"attribute_alias -> {target_sym.canonical_id}",
                    )
                # Framework / external library module attribute
                if grounded_mod in ("celery", "click", "app", "django", "typer") or "." in grounded_mod:
                    return (
                        f"{grounded_mod}.{attr}",
                        RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                        f"external_attribute_alias -> {grounded_mod}.{attr}",
                    )
            elif grounded_sym:
                cand_canon = f"{grounded_sym.canonical_id}.{attr}"
                if cand_canon in self.canonical_map:
                    return (
                        cand_canon,
                        RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                        f"method_alias -> {cand_canon}",
                    )

            return None, RelationshipEvidenceClass.UNKNOWN, f"attribute_not_found_on_base: {base}.{attr}"

        if selected.expr_kind == "SUBSCRIPT":
            target_dict = selected.subscript_target or ""
            sub_key = selected.subscript_key
            idx = selected.subscript_index
            return self.resolve_subscript(
                file_path=file_path,
                target_dict=target_dict,
                key=sub_key,
                index=idx,
                scope=selected.scope,
                use_line=selected.line,
                visited=set(visited),
                depth=depth,
            )

        return None, RelationshipEvidenceClass.UNKNOWN, "unsupported_binding_kind"

    def resolve_subscript(
        self,
        file_path: str,
        target_dict: str,
        key: str | None = None,
        index: int | None = None,
        scope: str = "",
        use_line: int | None = None,
        visited: set[tuple[str, str, str]] | None = None,
        depth: int = 0,
    ) -> tuple[str | None, RelationshipEvidenceClass, str]:
        """Resolve a subscript access (e.g. HANDLERS['create'] or PIPELINE[0]) deterministically."""
        visited = visited or set()
        if depth > 10:
            return None, RelationshipEvidenceClass.UNKNOWN, "max_depth_exceeded"

        if key == "<DYNAMIC>":
            return None, RelationshipEvidenceClass.UNKNOWN, "dynamic_dispatch"

        # 1. Look for bindings of target_dict in the current file
        dict_bindings = self.bindings_by_file_target.get((file_path, target_dict), [])
        dict_candidates = [
            b
            for b in dict_bindings
            if (b.scope == scope or not b.scope)
            and (use_line is None or b.line <= use_line)
        ]

        # Check for subscript assignment in dict_candidates (e.g. HANDLERS["create"] = create_user)
        if key is not None and dict_candidates:
            # Walk backwards from use_line to find latest assignment for this key
            for b in reversed(dict_candidates):
                if (
                    b.expr_kind in ("DICT_ASSIGN", "EVENT_ON", "SUBSCRIPT_ASSIGN", "CALL_REGISTER")
                    and b.subscript_key == key
                ):
                    if b.is_conditional:
                        return None, RelationshipEvidenceClass.POSSIBLE, "conditional_ambiguity"
                    if b.source_expr == "<DYNAMIC>":
                        return None, RelationshipEvidenceClass.UNKNOWN, "dynamic_dispatch"
                    if "." in b.source_expr:
                        base, attr = b.source_expr.split(".", 1)
                        return self._resolve_attribute_expr(
                            file_path, base, attr, scope, b.line, set(visited), depth + 1
                        )
                    target_id, _ev, _rsn = self.resolve(
                        file_path=file_path,
                        name=b.source_expr,
                        scope=scope,
                        use_line=b.line,
                        visited=set(visited),
                        depth=depth + 1,
                    )
                    if target_id:
                        return (
                            target_id,
                            RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                            f"dict_assignment -> {target_id}",
                        )
                    return None, RelationshipEvidenceClass.UNKNOWN, f"unresolved_subscript_val: {b.source_expr}"

        # Check for literal definition (DICT_LITERAL or LIST_LITERAL)
        if dict_candidates:
            dict_b = dict_candidates[-1]
            if dict_b.expr_kind == "DICT_LITERAL" and key is not None:
                for k, val_name in dict_b.dict_entries:
                    if k == key:
                        if "." in val_name:
                            base, attr = val_name.split(".", 1)
                            return self._resolve_attribute_expr(
                                file_path, base, attr, scope, dict_b.line, set(visited), depth + 1
                            )
                        target_id, _ev, _rsn = self.resolve(
                            file_path=file_path,
                            name=val_name,
                            scope=scope,
                            use_line=dict_b.line,
                            visited=set(visited),
                            depth=depth + 1,
                        )
                        if target_id:
                            return (
                                target_id,
                                RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                                f"dict_subscript -> {target_id}",
                            )
                        return None, RelationshipEvidenceClass.UNKNOWN, f"unresolved_subscript_val: {val_name}"
                return None, RelationshipEvidenceClass.UNKNOWN, f"key_not_in_dict: {key}"

            if dict_b.expr_kind == "LIST_LITERAL" and index is not None:
                if 0 <= index < len(dict_b.list_entries):
                    elem_name = dict_b.list_entries[index]
                    if "." in elem_name:
                        base, attr = elem_name.split(".", 1)
                        return self._resolve_attribute_expr(
                            file_path, base, attr, scope, dict_b.line, set(visited), depth + 1
                        )
                    target_id, _ev, _rsn = self.resolve(
                        file_path=file_path,
                        name=elem_name,
                        scope=scope,
                        use_line=dict_b.line,
                        visited=set(visited),
                        depth=depth + 1,
                    )
                    if target_id:
                        return (
                            target_id,
                            RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                            f"list_subscript -> {target_id}",
                        )
                    return None, RelationshipEvidenceClass.UNKNOWN, f"unresolved_subscript_elem: {elem_name}"
                return None, RelationshipEvidenceClass.UNKNOWN, f"index_out_of_bounds: {index}"

        # 2. Check cross-file imports: e.g. from registry import HANDLERS
        for imp in self.file_imports.get((file_path, target_dict), []):
            _tpath, target_mod = self.resolve_import_target(imp)
            if target_mod:
                orig_name = imp.imported_name or target_dict
                return self.resolve_cross_file_registry(
                    target_mod, orig_name, key, visited=set(visited), depth=depth + 1
                )

        return None, RelationshipEvidenceClass.UNKNOWN, f"unknown_subscript_target: {target_dict}"

    def resolve_cross_file_registry(
        self,
        target_mod: str,
        target_name: str,
        key: str | None,
        visited: set[tuple[str, str, str]] | None = None,
        depth: int = 0,
    ) -> tuple[str | None, RelationshipEvidenceClass, str]:
        """Resolve a subscript key in a cross-file shared registry."""
        if key is None or key == "<DYNAMIC>":
            return None, RelationshipEvidenceClass.UNKNOWN, "dynamic_dispatch"

        visited = visited or set()
        v_key = (target_mod, target_name, key)
        if v_key in visited or depth > 10:
            return None, RelationshipEvidenceClass.UNKNOWN, "cycle_or_depth_exceeded"
        visited.add(v_key)

        candidates: list[BindingRef] = []
        for b in self.bindings_by_target.get(target_name, ()):
            if (
                b.expr_kind in ("DICT_ASSIGN", "EVENT_ON", "SUBSCRIPT_ASSIGN", "CALL_REGISTER")
                and b.subscript_key == key
            ):
                candidates.append(b)
            elif b.expr_kind == "DICT_LITERAL":
                for k, _v in b.dict_entries:
                    if k == key:
                        candidates.append(b)
                        break

        if not candidates:
            return None, RelationshipEvidenceClass.UNKNOWN, f"key_not_in_cross_file_registry: {key}"

        # If any candidate is conditional, order/presence is ambiguous -> POSSIBLE
        if any(c.is_conditional for c in candidates):
            return None, RelationshipEvidenceClass.POSSIBLE, "conditional_ambiguity"

        resolved_targets: set[str] = set()
        for cand in candidates:
            if cand.expr_kind == "DICT_LITERAL":
                for k, v in cand.dict_entries:
                    if k == key:
                        tid, _ev, _rsn = self.resolve(
                            cand.file_path,
                            v,
                            scope=cand.scope,
                            use_line=cand.line,
                            visited=set(visited),
                            depth=depth + 1,
                        )
                        if tid:
                            resolved_targets.add(tid)
            else:
                if cand.source_expr == "<DYNAMIC>":
                    return None, RelationshipEvidenceClass.UNKNOWN, "dynamic_dispatch"
                if "." in cand.source_expr:
                    base, attr = cand.source_expr.split(".", 1)
                    tid, _ev, _rsn = self._resolve_attribute_expr(
                        cand.file_path, base, attr, cand.scope, cand.line, set(visited), depth + 1
                    )
                    if tid:
                        resolved_targets.add(tid)
                else:
                    tid, _ev, _rsn = self.resolve(
                        cand.file_path,
                        cand.source_expr,
                        scope=cand.scope,
                        use_line=cand.line,
                        visited=set(visited),
                        depth=depth + 1,
                    )
                    if tid:
                        resolved_targets.add(tid)

        if not resolved_targets:
            return None, RelationshipEvidenceClass.UNKNOWN, f"unresolved_cross_file_registry_key: {key}"

        if len(resolved_targets) > 1:
            # Conflicting mutations across files -> POSSIBLE
            return None, RelationshipEvidenceClass.POSSIBLE, "cross_file_mutation_ambiguity"

        final_id = next(iter(resolved_targets))
        return (
            final_id,
            RelationshipEvidenceClass.DATAFLOW_VERIFIED,
            f"cross_file_registry -> {final_id}",
        )

    def _resolve_attribute_expr(
        self,
        file_path: str,
        base: str,
        attr: str,
        scope: str,
        line: int,
        visited: set[tuple[str, str, str]],
        depth: int,
    ) -> tuple[str | None, RelationshipEvidenceClass, str]:
        """Resolve attribute expression when base is statically grounded."""
        grounded_mod: str | None = None
        grounded_sym: Symbol | None = None

        for imp in self.file_imports.get((file_path, base), []):
            _tpath, target_mod = self.resolve_import_target(imp)
            if target_mod:
                if imp.import_type in ("namespace", "module") or imp.imported_name in (None, "*"):
                    grounded_mod = target_mod
                else:
                    orig_name = imp.imported_name or base
                    grounded_sym = self.resolve_symbol_in_module(target_mod, orig_name)
                break

        if not grounded_mod and not grounded_sym:
            for s in self.file_symbols.get((file_path, base), []):
                if s.kind in ("class", "function", "method"):
                    grounded_sym = s
                    break

        if not grounded_mod and not grounded_sym:
            base_id, base_ev, _base_reason = self.resolve(
                file_path=file_path,
                name=base,
                scope=scope,
                use_line=line,
                visited=set(visited),
                depth=depth + 1,
            )
            if base_id and base_ev == RelationshipEvidenceClass.DATAFLOW_VERIFIED:
                if base_id in self.canonical_map:
                    grounded_sym = self.canonical_map[base_id]

        if not grounded_mod and not grounded_sym:
            return None, RelationshipEvidenceClass.UNKNOWN, f"unknown_attribute_base: {base}"

        if grounded_mod:
            target_sym = self.resolve_symbol_in_module(grounded_mod, attr)
            if target_sym:
                return (
                    target_sym.canonical_id,
                    RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                    f"attribute_alias -> {target_sym.canonical_id}",
                )
        elif grounded_sym:
            cand_canon = f"{grounded_sym.canonical_id}.{attr}"
            if cand_canon in self.canonical_map:
                return (
                    cand_canon,
                    RelationshipEvidenceClass.DATAFLOW_VERIFIED,
                    f"method_alias -> {cand_canon}",
                )

        return None, RelationshipEvidenceClass.UNKNOWN, f"attribute_not_found_on_base: {base}.{attr}"
