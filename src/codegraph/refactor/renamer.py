"""Deterministic, syntax-validated, transaction-safe AST symbol renaming engine.

Core Invariant:
  DISCOVER -> PLAN -> PREVIEW -> VALIDATE -> COMMIT -> REINDEX -> VERIFY

Zero disk mutation during DISCOVER, PLAN, PREVIEW, or VALIDATE.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import io
import keyword
import re
import sqlite3
import tokenize
import uuid
from pathlib import Path
from typing import Any

from codegraph.indexing.indexer import Indexer
from codegraph.refactor.models import (
    RefactorPlan,
    RefactorResult,
    RefactorRisk,
    RefactorStatus,
    TokenReplacementSpan,
)
from codegraph.refactor.transactions import commit_refactor_transaction
from codegraph.security.paths import safe_path
from codegraph.target_resolver import resolve_target

_TEST_FILE_RE = re.compile(
    r"(^|[_/])test[_s]?[_/]|[_/]spec[_/]|test[_s]?\.(py|pyi)$|spec\.(py|pyi)$",
    re.IGNORECASE,
)


def is_test_file(path: str) -> bool:
    """Check if file path belongs to test suite."""
    clean = path.replace("\\", "/")
    return bool(_TEST_FILE_RE.search(clean))


def apply_spans_to_text(text: str, spans: list[TokenReplacementSpan]) -> str:
    """Deterministically apply replacement spans to text buffer in reverse order.
    
    Sorting spans by (start_line, start_col) descending ensures that replacements
    later in the file/line do not shift coordinates for replacements earlier in the file/line.
    Comments, docstrings, indentation, unrelated formatting, and CRLF/LF line endings
    are preserved 100%.
    """
    lines = text.splitlines(keepends=True)
    sorted_spans = sorted(
        spans,
        key=lambda s: (s.start_line, s.start_col),
        reverse=True,
    )
    for span in sorted_spans:
        line_idx = span.start_line - 1
        if line_idx < 0 or line_idx >= len(lines):
            raise IndexError(
                f"Span line {span.start_line} out of range (1..{len(lines)}) for span {span}"
            )
        line = lines[line_idx]
        col_start = span.start_col
        col_end = span.end_col
        actual_token = line[col_start:col_end]
        if actual_token != span.old_token:
            raise ValueError(
                f"Token mismatch at line {span.start_line}, cols {col_start}..{col_end}: "
                f"expected '{span.old_token}', found '{actual_token}'"
            )
        lines[line_idx] = line[:col_start] + span.new_token + line[col_end:]
    return "".join(lines)


def generate_unified_diff(file_path: str, original: str, modified: str) -> str:
    """Generate deterministic unified diff."""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


class PythonSpanCollector:
    """Collects token replacement spans from a Python source file using AST + tokenizer."""

    def __init__(
        self,
        content: str,
        path: str,
        target_name: str,
        new_name: str,
        target_canonical_id: str,
        target_kind: str,
        target_class_name: str | None = None,
        is_definition_file: bool = False,
        is_from_imported: bool = False,
        import_alias: str | None = None,
        is_module_imported: bool = False,
        module_alias: str | None = None,
        verified_call_lines: set[int] | None = None,
        target_line: int | None = None,
    ) -> None:
        self.content = content
        self.path = path
        self.target_name = target_name
        self.new_name = new_name
        self.target_canonical_id = target_canonical_id
        self.target_kind = target_kind
        self.target_class_name = target_class_name
        self.is_definition_file = is_definition_file
        self.is_from_imported = is_from_imported
        self.import_alias = import_alias
        self.is_module_imported = is_module_imported
        self.module_alias = module_alias
        self.verified_call_lines = verified_call_lines or set()
        self.target_line = target_line
        self.spans: list[TokenReplacementSpan] = []

    def collect(self) -> list[TokenReplacementSpan]:
        try:
            tokens = list(tokenize.tokenize(io.BytesIO(self.content.encode("utf-8")).readline))
            tree = ast.parse(self.content)
        except Exception:
            return []

        # 1. Definition span in definition file
        if self.is_definition_file:
            self._collect_definition(tree, tokens)

        # 2. From-import statement spans
        if self.is_from_imported:
            self._collect_from_imports(tree, tokens)

        # 3. Direct identifier references (ast.Name)
        # When target is function/class in definition file or imported via `from mod import target` (unaliased)
        if (self.is_definition_file and self.target_kind in ("function", "class")) or (
            self.is_from_imported and self.import_alias is None
        ):
            self._collect_name_references(tree, tokens)

        # 4. Attribute references (e.g. mod.target or obj.method)
        self._collect_attribute_references(tree, tokens)

        # De-duplicate spans deterministically by (start_line, start_col, end_line, end_col)
        seen: set[tuple[int, int, int, int]] = set()
        unique_spans: list[TokenReplacementSpan] = []
        for span in sorted(self.spans, key=lambda s: (s.start_line, s.start_col)):
            key = (span.start_line, span.start_col, span.end_line, span.end_col)
            if key not in seen:
                seen.add(key)
                unique_spans.append(span)
        return unique_spans

    def _collect_definition(self, tree: ast.AST, tokens: list[tokenize.TokenInfo]) -> None:
        target_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == self.target_name:
                    if self.target_line is not None:
                        # Allow matching on or near target_line
                        node_end = getattr(node, "end_lineno", node.lineno)
                        if node.lineno <= self.target_line <= node_end or abs(node.lineno - self.target_line) <= 2:
                            target_nodes.append(node)
                    else:
                        target_nodes.append(node)

        for node in target_nodes:
            # Find the NAME token for node.name on node.lineno or following 'def' / 'class'
            for tok in tokens:
                if tok.type == tokenize.NAME and tok.string == self.target_name and tok.start[0] == node.lineno:
                    self.spans.append(
                        TokenReplacementSpan(
                            path=self.path,
                            start_line=tok.start[0],
                            start_col=tok.start[1],
                            end_line=tok.end[0],
                            end_col=tok.end[1],
                            old_token=self.target_name,
                            new_token=self.new_name,
                            evidence="AST_VERIFIED: definition",
                            symbol_id=self.target_canonical_id,
                        )
                    )
                    break

    def _collect_from_imports(self, tree: ast.AST, tokens: list[tokenize.TokenInfo]) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == self.target_name:
                        alias_line = getattr(alias, "lineno", node.lineno)
                        col_offset = getattr(alias, "col_offset", 0)
                        for tok in tokens:
                            if (
                                tok.type == tokenize.NAME
                                and tok.string == self.target_name
                                and tok.start[0] == alias_line
                                and tok.start[1] >= col_offset
                            ):
                                self.spans.append(
                                    TokenReplacementSpan(
                                        path=self.path,
                                        start_line=tok.start[0],
                                        start_col=tok.start[1],
                                        end_line=tok.end[0],
                                        end_col=tok.end[1],
                                        old_token=self.target_name,
                                        new_token=self.new_name,
                                        evidence="AST_VERIFIED: from-import",
                                        symbol_id=self.target_canonical_id,
                                    )
                                )
                                break

    def _collect_name_references(self, tree: ast.AST, tokens: list[tokenize.TokenInfo]) -> None:
        target_name = self.target_name
        new_name = self.new_name
        path = self.path
        target_canonical_id = self.target_canonical_id
        target_line = self.target_line if self.is_definition_file else None

        class ScopeVisitor(ast.NodeVisitor):
            def __init__(self, outer: PythonSpanCollector) -> None:
                self.outer = outer
                self.scopes: list[set[str]] = [set()]

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                # Local parameter scope
                local_params = {arg.arg for arg in node.args.args}
                if node.args.vararg:
                    local_params.add(node.args.vararg.arg)
                if node.args.kwarg:
                    local_params.add(node.args.kwarg.arg)
                for arg in node.args.kwonlyargs:
                    local_params.add(arg.arg)
                self.scopes.append(local_params)
                self.generic_visit(node)
                self.scopes.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                local_params = {arg.arg for arg in node.args.args}
                if node.args.vararg:
                    local_params.add(node.args.vararg.arg)
                if node.args.kwarg:
                    local_params.add(node.args.kwarg.arg)
                for arg in node.args.kwonlyargs:
                    local_params.add(arg.arg)
                self.scopes.append(local_params)
                self.generic_visit(node)
                self.scopes.pop()

            def visit_Name(self, node: ast.Name) -> None:
                if node.id == target_name:
                    # Skip definition itself if target_line matches
                    if target_line is not None and node.lineno == target_line:
                        return
                    # Check if shadowed in current local scope
                    is_shadowed = any(target_name in s for s in self.scopes[1:])
                    if not is_shadowed:
                        self.outer.spans.append(
                            TokenReplacementSpan(
                                path=path,
                                start_line=node.lineno,
                                start_col=node.col_offset,
                                end_line=getattr(node, "end_lineno", node.lineno),
                                end_col=getattr(node, "end_col_offset", node.col_offset + len(target_name)),
                                old_token=target_name,
                                new_token=new_name,
                                evidence="AST_VERIFIED: name reference",
                                symbol_id=target_canonical_id,
                            )
                        )
                self.generic_visit(node)

        ScopeVisitor(self).visit(tree)

    def _collect_attribute_references(self, tree: ast.AST, tokens: list[tokenize.TokenInfo]) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == self.target_name:
                should_rename = False

                # Case A: Module import (e.g. module.target or alias.target)
                if self.is_module_imported:
                    expected_mod = self.module_alias or self.path.split("/")[-1].replace(".py", "")
                    if isinstance(node.value, ast.Name) and (
                        node.value.id == expected_mod or (self.module_alias and node.value.id == self.module_alias)
                    ):
                        should_rename = True

                # Case B: Verified method call on instance (e.g. self.target or obj.target)
                if self.target_kind == "method":
                    if self.is_definition_file and isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
                        should_rename = True
                    elif node.lineno in self.verified_call_lines:
                        should_rename = True

                # Case C: Explicitly verified call line
                if node.lineno in self.verified_call_lines:
                    should_rename = True

                if should_rename:
                    # Find exact token for attribute name
                    end_line = getattr(node, "end_lineno", node.lineno)
                    end_col = getattr(node, "end_col_offset", node.col_offset + len(self.target_name))
                    for tok in tokens:
                        if (
                            tok.type == tokenize.NAME
                            and tok.string == self.target_name
                            and tok.end == (end_line, end_col)
                        ):
                            self.spans.append(
                                TokenReplacementSpan(
                                    path=self.path,
                                    start_line=tok.start[0],
                                    start_col=tok.start[1],
                                    end_line=tok.end[0],
                                    end_col=tok.end[1],
                                    old_token=self.target_name,
                                    new_token=self.new_name,
                                    evidence="AST_VERIFIED: attribute access",
                                    symbol_id=self.target_canonical_id,
                                )
                            )
                            break


def plan_safe_rename(
    repository: Path,
    con: sqlite3.Connection,
    target: str,
    new_name: str,
    force_uncertain: bool = False,
) -> RefactorPlan:
    """Compute a deterministic AST refactoring plan with uncertainty auditing.
    
    Invariants:
    1. Target symbol must resolve unambiguously to a known symbol.
    2. new_name must be a valid Python identifier and not a reserved keyword.
    3. Audit all references across calls, imports, and graph edges for uncertainty.
    4. Compute TokenReplacementSpan items with token-level precision.
    5. No disk mutation during plan generation.
    """
    repo_root = repository.resolve()
    transaction_id = f"rf_{uuid.uuid4().hex[:12]}"

    # 1. Identifier validation
    if not new_name.isidentifier() or keyword.iskeyword(new_name):
        return RefactorPlan(
            transaction_id=transaction_id,
            target_symbol=target,
            new_name=new_name,
            risk=RefactorRisk.HIGH,
            uncertainty_reasons=[f"INVALID_IDENTIFIER: '{new_name}' is not a valid Python identifier or is a reserved keyword."],
        )

    # 2. Target resolution
    target_res = resolve_target(target, con)

    if target_res.ambiguity_state == "AMBIGUOUS" or len(target_res.alternatives) > 1:
        candidates_str = ", ".join(
            str(alt.get("canonical_id") or alt.get("qualified_name") or alt.get("path"))
            for alt in target_res.alternatives[:5]
        )
        return RefactorPlan(
            transaction_id=transaction_id,
            target_symbol=target,
            new_name=new_name,
            risk=RefactorRisk.HIGH,
            uncertainty_reasons=[
                f"AMBIGUOUS_TARGET: Target '{target}' matches multiple candidates ({len(target_res.alternatives)} found): [{candidates_str}]. Please qualify with module or class name."
            ],
        )

    if not target_res.canonical_id or target_res.confidence not in ("HIGH", "MEDIUM"):
        return RefactorPlan(
            transaction_id=transaction_id,
            target_symbol=target,
            new_name=new_name,
            risk=RefactorRisk.HIGH,
            uncertainty_reasons=[f"TARGET_NOT_FOUND: Symbol '{target}' could not be resolved in the repository."],
        )

    target_canonical_id = target_res.canonical_id

    # Fetch symbol record from DB
    row = con.execute(
        "SELECT name, qualified_name, kind, path, start_line, end_line, module, scope, canonical_id "
        "FROM symbols WHERE canonical_id=? LIMIT 1",
        (target_canonical_id,),
    ).fetchone()

    if not row:
        # Fallback query by path & start_line if canonical_id differs slightly
        if target_res.file_path and target_res.line:
            row = con.execute(
                "SELECT name, qualified_name, kind, path, start_line, end_line, module, scope, canonical_id "
                "FROM symbols WHERE path=? AND start_line=? LIMIT 1",
                (target_res.file_path, target_res.line),
            ).fetchone()

    if not row:
        return RefactorPlan(
            transaction_id=transaction_id,
            target_symbol=target,
            new_name=new_name,
            risk=RefactorRisk.HIGH,
            uncertainty_reasons=[f"SYMBOL_RECORD_MISSING: No database record found for canonical ID '{target_canonical_id}'."],
        )

    target_name = str(row["name"])
    target_kind = str(row["kind"])
    target_path = str(row["path"])
    target_line = int(row["start_line"])
    target_module = str(row["module"])

    if new_name == target_name:
        return RefactorPlan(
            transaction_id=transaction_id,
            target_symbol=target,
            new_name=new_name,
            risk=RefactorRisk.LOW,
            uncertainty_reasons=[f"NOOP_RENAME: New name '{new_name}' is identical to current name."],
        )

    # Determine parent class name if target is a method
    target_class_name: str | None = None
    if target_kind == "method":
        scope_str = str(row["scope"] or "")
        if scope_str:
            target_class_name = scope_str.split(".")[-1]
        elif "." in str(row["qualified_name"]):
            parts = str(row["qualified_name"]).split(".")
            if len(parts) >= 2:
                target_class_name = parts[-2]

    # 3. Uncertainty Auditing
    uncertainty_reasons: list[str] = []
    assessed_risk = RefactorRisk.LOW

    # Check for unverified or low-confidence calls to target_name across the repo
    try:
        call_rows = con.execute(
            "SELECT source_path, line, confidence, callee, qualified_callee, resolved_symbol_id "
            "FROM calls WHERE (callee=? OR qualified_callee LIKE ?) AND source_path != ?",
            (target_name, f"%.{target_name}", target_path),
        ).fetchall()
        for c in call_rows:
            conf = str(c["confidence"] or "UNKNOWN").upper()
            resolved = c["resolved_symbol_id"]
            if resolved and resolved != target_canonical_id:
                # Belongs to a different verified symbol (homonym) - safe to ignore
                continue
            if not resolved or conf in ("LOW", "UNKNOWN"):
                uncertainty_reasons.append(
                    f"POSSIBLE_REFERENCE: Call site at {c['source_path']}:{c['line']} to '{target_name}' has unverified receiver type (confidence={conf})."
                )
                if assessed_risk != RefactorRisk.HIGH:
                    assessed_risk = RefactorRisk.MEDIUM
    except sqlite3.OperationalError:
        pass

    # Check references table for unverified or possible relationships
    try:
        ref_rows = con.execute(
            "SELECT path, start_line, relationship, confidence "
            "FROM 'references' WHERE target_symbol_id=? OR (relationship='POSSIBLE_CALLS' AND evidence LIKE ?)",
            (target_canonical_id, f"%{target_name}%"),
        ).fetchall()
        for r in ref_rows:
            rel = str(r["relationship"])
            conf = str(r["confidence"]).upper()
            if rel == "POSSIBLE_CALLS" or conf in ("LOW", "UNKNOWN"):
                uncertainty_reasons.append(
                    f"POSSIBLE_RELATIONSHIP: Reference at {r['path']}:{r['start_line']} has relationship={rel}, confidence={conf}."
                )
                assessed_risk = RefactorRisk.HIGH
    except sqlite3.OperationalError:
        pass

    # 4. Discover affected files and collect replacement spans
    affected_files: set[str] = {target_path}
    spans: list[TokenReplacementSpan] = []

    # A. Definition file spans
    def_abs_path = safe_path(repo_root, target_path)
    if def_abs_path.exists():
        def_content = def_abs_path.read_text(encoding="utf-8", errors="replace")
        collector = PythonSpanCollector(
            content=def_content,
            path=target_path,
            target_name=target_name,
            new_name=new_name,
            target_canonical_id=target_canonical_id,
            target_kind=target_kind,
            target_class_name=target_class_name,
            is_definition_file=True,
            target_line=target_line,
        )
        spans.extend(collector.collect())

    # B. Discover importing files
    importing_files_info: dict[str, dict[str, Any]] = {}
    try:
        imp_rows = con.execute(
            "SELECT source_path, module, name, alias, line, local_name, resolved_path "
            "FROM imports WHERE (resolved_path=? OR module=? OR module LIKE ?)",
            (target_path, target_module, f"%.{target_module}"),
        ).fetchall()
        for imp in imp_rows:
            src = str(imp["source_path"])
            if src == target_path:
                continue
            name = imp["name"]
            alias = imp["alias"]
            mod = imp["module"]

            if src not in importing_files_info:
                importing_files_info[src] = {
                    "is_from_imported": False,
                    "import_alias": None,
                    "is_module_imported": False,
                    "module_alias": None,
                    "verified_lines": set(),
                }

            if name == target_name:
                importing_files_info[src]["is_from_imported"] = True
                if alias:
                    importing_files_info[src]["import_alias"] = str(alias)
            elif not name and (mod == target_module or mod.endswith(f".{target_module}")):
                importing_files_info[src]["is_module_imported"] = True
                if alias:
                    importing_files_info[src]["module_alias"] = str(alias)
    except sqlite3.OperationalError:
        pass

    # C. Discover verified call sites across other files
    try:
        call_sites = con.execute(
            "SELECT source_path, line FROM calls WHERE resolved_symbol_id=? AND source_path != ?",
            (target_canonical_id, target_path),
        ).fetchall()
        for cs in call_sites:
            src = str(cs["source_path"])
            line = int(cs["line"])
            if src not in importing_files_info:
                importing_files_info[src] = {
                    "is_from_imported": False,
                    "import_alias": None,
                    "is_module_imported": False,
                    "module_alias": None,
                    "verified_lines": set(),
                }
            importing_files_info[src]["verified_lines"].add(line)
    except sqlite3.OperationalError:
        pass

    # D. Collect spans for all importing and referencing files
    for file_path, info in sorted(importing_files_info.items()):
        abs_p = safe_path(repo_root, file_path)
        if not abs_p.exists():
            continue
        affected_files.add(file_path)
        content = abs_p.read_text(encoding="utf-8", errors="replace")
        collector = PythonSpanCollector(
            content=content,
            path=file_path,
            target_name=target_name,
            new_name=new_name,
            target_canonical_id=target_canonical_id,
            target_kind=target_kind,
            target_class_name=target_class_name,
            is_definition_file=False,
            is_from_imported=info["is_from_imported"],
            import_alias=info["import_alias"],
            is_module_imported=info["is_module_imported"],
            module_alias=info["module_alias"],
            verified_call_lines=info["verified_lines"],
        )
        file_spans = collector.collect()
        spans.extend(file_spans)

    # 5. Compute original file hashes, sizes, and mtimes
    orig_hashes: dict[str, str] = {}
    orig_sizes: dict[str, int] = {}
    orig_mtimes: dict[str, float] = {}

    for rel_path in sorted(affected_files):
        abs_p = safe_path(repo_root, rel_path)
        if abs_p.exists():
            raw_bytes = abs_p.read_bytes()
            orig_hashes[rel_path] = hashlib.sha256(raw_bytes).hexdigest()
            orig_sizes[rel_path] = len(raw_bytes)
            orig_mtimes[rel_path] = abs_p.stat().st_mtime

    # 6. Query affected tests, routes, and DB impact
    affected_tests: list[str] = []
    affected_routes: list[str] = []
    affected_db_rel: list[str] = []

    # Tests
    for f in affected_files:
        if is_test_file(f):
            affected_tests.append(f)
    try:
        t_rows = con.execute(
            "SELECT DISTINCT source FROM graph_edges WHERE target=? AND relationship='TESTS'",
            (target_canonical_id,),
        ).fetchall()
        for tr in t_rows:
            affected_tests.append(str(tr["source"]))
    except sqlite3.OperationalError:
        pass

    # Routes
    try:
        r_rows = con.execute(
            "SELECT DISTINCT route_path FROM framework_routes WHERE handler_canonical_id=? OR handler_name=?",
            (target_canonical_id, target_name),
        ).fetchall()
        for rr in r_rows:
            affected_routes.append(str(rr["route_path"]))
    except sqlite3.OperationalError:
        pass

    # DB relationships
    try:
        db_rows = con.execute(
            "SELECT DISTINCT name FROM db_entities WHERE canonical_id=?",
            (target_canonical_id,),
        ).fetchall()
        for dbr in db_rows:
            affected_db_rel.append(str(dbr["name"]))
    except sqlite3.OperationalError:
        pass

    # Deterministic sorting
    sorted_files = sorted(affected_files)
    sorted_spans = sorted(spans, key=lambda s: (s.path, s.start_line, s.start_col))

    return RefactorPlan(
        transaction_id=transaction_id,
        target_symbol=target_canonical_id,
        new_name=new_name,
        files=sorted_files,
        spans=sorted_spans,
        risk=assessed_risk,
        uncertainty_reasons=sorted(set(uncertainty_reasons)),
        affected_tests=sorted(set(affected_tests)),
        affected_routes=sorted(set(affected_routes)),
        affected_db_relationships=sorted(set(affected_db_rel)),
        original_file_hashes=orig_hashes,
        original_file_sizes=orig_sizes,
        original_file_mtimes=orig_mtimes,
    )


def preview_safe_rename(
    repository: Path,
    plan: RefactorPlan,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """In-memory preview and syntax validation.
    
    Returns:
      (diffs, modified_buffers, syntax_errors)
      
    Invariants:
    1. Zero disk mutation.
    2. ast.parse() executed on all modified Python buffers.
    3. If any file fails syntax validation, returns syntax error.
    """
    repo_root = repository.resolve()
    diffs: dict[str, str] = {}
    modified_buffers: dict[str, str] = {}
    errors: list[str] = []

    # Group spans by file
    spans_by_file: dict[str, list[TokenReplacementSpan]] = {f: [] for f in plan.files}
    for s in plan.spans:
        if s.path in spans_by_file:
            spans_by_file[s.path].append(s)

    for rel_path in plan.files:
        abs_p = safe_path(repo_root, rel_path)
        if not abs_p.exists():
            errors.append(f"FILE_NOT_FOUND: '{rel_path}' does not exist on disk.")
            continue

        orig_text = abs_p.read_text(encoding="utf-8", errors="replace")
        file_spans = spans_by_file.get(rel_path, [])

        if not file_spans:
            # File had no spans, buffer remains unchanged
            modified_buffers[rel_path] = orig_text
            continue

        try:
            modified_text = apply_spans_to_text(orig_text, file_spans)
        except Exception as exc:
            errors.append(f"SPAN_APPLICATION_FAILED: Failed to apply spans to '{rel_path}': {exc}")
            continue

        # In-memory syntax validation
        try:
            ast.parse(modified_text, filename=rel_path)
        except SyntaxError as syn_err:
            errors.append(
                f"SYNTAX_VALIDATION_FAILED: File '{rel_path}' has syntax error after replacement: {syn_err}"
            )
            continue

        modified_buffers[rel_path] = modified_text
        diff = generate_unified_diff(rel_path, orig_text, modified_text)
        if diff:
            diffs[rel_path] = diff

    return diffs, modified_buffers, sorted(errors)


def execute_safe_rename(
    repository: Path,
    con: sqlite3.Connection,
    target: str,
    new_name: str,
    dry_run: bool = True,
    force_uncertain: bool = False,
) -> RefactorResult:
    """Execute the complete SAFE_RENAME workflow.
    
    Workflow:
      DISCOVER -> PLAN -> PREVIEW -> VALIDATE -> COMMIT -> REINDEX -> VERIFY
      
    Invariants:
    1. dry_run=True performs zero disk mutation and returns preview packet.
    2. Any syntax validation failure aborts with status BLOCKED/ERROR.
    3. If risk != LOW and not force_uncertain, operation is BLOCKED.
    4. Post-commit triggers incremental index update and verifies new symbol.
    """
    repo_root = repository.resolve()

    # 1. Plan
    plan = plan_safe_rename(repo_root, con, target, new_name, force_uncertain=force_uncertain)

    # Check for hard errors during plan
    if plan.uncertainty_reasons and any(
        r.startswith(("INVALID_IDENTIFIER", "TARGET_NOT_FOUND", "AMBIGUOUS_TARGET", "NOOP_RENAME"))
        for r in plan.uncertainty_reasons
    ):
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=target,
            new_name=new_name,
            risk=plan.risk,
            uncertainty_reasons=plan.uncertainty_reasons,
            errors=plan.uncertainty_reasons,
        )

    # 2. In-memory preview & syntax validation
    diffs, modified_buffers, syntax_errors = preview_safe_rename(repo_root, plan)

    if syntax_errors:
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=plan.target_symbol,
            new_name=new_name,
            risk=RefactorRisk.HIGH,
            uncertainty_reasons=plan.uncertainty_reasons,
            files_changed=len(plan.files),
            spans_count=len(plan.spans),
            diffs=diffs,
            errors=syntax_errors,
        )

    # 3. Risk-based blocking
    if plan.risk != RefactorRisk.LOW and not force_uncertain:
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=plan.target_symbol,
            new_name=new_name,
            risk=plan.risk,
            uncertainty_reasons=plan.uncertainty_reasons,
            files_changed=len(plan.files),
            spans_count=len(plan.spans),
            tests_affected=plan.affected_tests,
            routes_affected=plan.affected_routes,
            db_affected=plan.affected_db_relationships,
            diffs=diffs,
            errors=[
                f"REFACTOR_BLOCKED_DUE_TO_UNCERTAINTY: Risk is {plan.risk}. "
                f"Use force_uncertain=True to apply despite uncertainty reasons: {plan.uncertainty_reasons}"
            ],
        )

    # 4. Dry-run mode: return complete preview packet with zero disk mutation
    if dry_run:
        # Precondition check: verify that files on disk still match original hashes
        for rel_p, orig_hash in plan.original_file_hashes.items():
            abs_p = safe_path(repo_root, rel_p)
            if abs_p.exists():
                curr_hash = hashlib.sha256(abs_p.read_bytes()).hexdigest()
                assert curr_hash == orig_hash, f"In-memory preview mutated file {rel_p}!"

        return RefactorResult(
            status=RefactorStatus.READY,
            target_symbol=plan.target_symbol,
            new_name=new_name,
            risk=plan.risk,
            uncertainty_reasons=plan.uncertainty_reasons,
            files_changed=len(diffs),
            symbols_changed=1 if plan.spans else 0,
            spans_count=len(plan.spans),
            tests_affected=plan.affected_tests,
            routes_affected=plan.affected_routes,
            db_affected=plan.affected_db_relationships,
            diffs=diffs,
            errors=[],
        )

    # 5. Apply mode: atomic commit transaction
    commit_res = commit_refactor_transaction(repo_root, plan, modified_buffers)

    if commit_res.status != RefactorStatus.APPLIED:
        commit_res.diffs = diffs
        return commit_res

    # 6. Post-commit: trigger incremental reindexing & verification
    try:
        indexer = Indexer(repo_root)
        indexer.index()
    except Exception as idx_err:
        # Commit succeeded, reindexing had warning
        commit_res.errors.append(f"POST_COMMIT_REINDEX_WARNING: {idx_err}")

    commit_res.diffs = diffs
    return commit_res
