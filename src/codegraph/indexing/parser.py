"""Single-pass scope-aware source parsers for Python, JavaScript, and TypeScript.

Architectural Invariants:
1. Exactly ONE scoped traversal per source file.
2. Framework route analyzers consume AST node visit events during this primary traversal;
   there is NEVER a second full-tree scan.
3. Lexical scope context (classes, functions, closures, methods) is maintained continuously
   on an explicit traversal stack without line-number or string-based heuristics.
4. ParseResult is an immutable contract between parsing and indexing.
"""
from __future__ import annotations

import ast
import hashlib
import posixpath
import re
from dataclasses import asdict, dataclass

from codegraph.frameworks import (
    AnalysisContext,
    FrameworkAnalyzer,
    RouteDetection,
    analyze_js_ts_line,
    get_python_analyzers,
)

from .models import (
    CallRef,
    ImportRef,
    InheritanceRef,
    Symbol,
    build_canonical_id,
    normalize_module,
)

PARSER_VERSION = "3.0"

_PYTHON_BUILTINS = {
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "breakpoint",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "compile",
    "complex",
    "delattr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "exec",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "memoryview",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "AttributeError",
    "NotImplementedError",
    "OSError",
    "FileNotFoundError",
}

_JS_KEYWORDS_AND_BUILTINS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "function",
    "return",
    "typeof",
    "instanceof",
    "new",
    "delete",
    "void",
    "yield",
    "await",
    "super",
    "this",
    "import",
    "require",
    "console",
    "Math",
    "JSON",
    "Object",
    "Array",
    "String",
    "Number",
    "Boolean",
    "Promise",
    "Set",
    "Map",
    "Error",
    "TypeError",
    "Date",
    "RegExp",
    "parseInt",
    "parseFloat",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
}

_PY_IMPORT = re.compile(
    r"""^(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))""",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ParseResult:
    path: str
    language: str
    parser_version: str = PARSER_VERSION
    source_hash: str = ""
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[ImportRef, ...] = ()
    calls: tuple[CallRef, ...] = ()
    inheritance: tuple[InheritanceRef, ...] = ()
    routes: tuple[RouteDetection, ...] = ()
    exports: tuple[str, ...] = ()
    parse_failed: bool = False
    parse_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "language": self.language,
            "parser_version": self.parser_version,
            "source_hash": self.source_hash,
            "symbols": [s.as_dict() for s in self.symbols],
            "imports": [i.as_dict() for i in self.imports],
            "calls": [c.qualified_callee or c.callee for c in self.calls],
            "inheritance": [asdict(inh) for inh in self.inheritance],
            "routes": [r.as_dict() for r in self.routes],
            "exports": list(self.exports),
            "parse_failed": self.parse_failed,
            "parse_error": self.parse_error,
        }

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


def parse(content: str, language: str, file_path: str) -> ParseResult:
    """Parse a source file in a single scoped pass."""
    if language == "python":
        return _parse_python(content, file_path)
    return _parse_js_ts(content, language, file_path)


def parse_symbols(
    content: str, language: str, file_path: str
) -> tuple[list[Symbol], list[str]]:
    """Backward-compatible helper returning symbols and unique imported module names."""
    result = parse(content, language, file_path)
    seen: list[str] = []
    for imp in result.imports:
        if imp.module and imp.module not in seen:
            seen.append(imp.module)
    return list(result.symbols), seen


def _normalized_body_hash(lines: list[str], start_line: int, end_line: int) -> str:
    """Compute a content hash of a symbol body independent of absolute line numbers."""
    snippet = "\n".join(line.rstrip() for line in lines[max(0, start_line - 1) : end_line]).strip()
    return hashlib.sha256(snippet.encode("utf-8", errors="replace")).hexdigest()[:16]


def _resolve_relative_py_module(file_path: str, level: int, module: str | None) -> str:
    """Resolve a Python relative import using source file directory depth."""
    if level <= 0:
        return module or ""
    norm_dir = posixpath.dirname(file_path.replace("\\", "/").lstrip("./"))
    parts = [p for p in norm_dir.split("/") if p and p != "."]
    up = level - 1
    if up > 0 and up <= len(parts):
        parts = parts[: len(parts) - up]
    elif up > len(parts):
        parts = []
    base = ".".join(parts)
    if base and module:
        return f"{base}.{module}"
    if base:
        return base
    if module:
        return module
    return "." * level


def _infer_function_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Conservatively infer return type from explicit annotation or direct constructor return."""
    # 1. Explicit return annotation
    if node.returns and hasattr(ast, "unparse"):
        raw = ast.unparse(node.returns).strip()
        m = re.match(r"^(?:Optional|typing\.Optional)\[\s*([A-Za-z_][\w.]*)\s*\]$", raw)
        if m:
            raw = m.group(1)
        clean = raw.split("[")[0].strip()
        if clean and clean not in _PYTHON_BUILTINS:
            return clean

    # 2. Direct constructor return in function body
    ctor_candidates: set[str] = set()
    for child in node.body:
        if isinstance(child, ast.Return) and child.value is not None:
            val = child.value
            if isinstance(val, ast.Call):
                if isinstance(val.func, ast.Name):
                    c_name = val.func.id
                    if c_name not in _PYTHON_BUILTINS and (
                        c_name[0].isupper()
                        or c_name.endswith("Service")
                        or c_name.endswith("Repository")
                        or c_name.endswith("Client")
                        or c_name.endswith("Store")
                    ):
                        ctor_candidates.add(c_name)
                elif isinstance(val.func, ast.Attribute) and hasattr(ast, "unparse"):
                    ctor_candidates.add(ast.unparse(val.func))
        elif isinstance(child, ast.If):
            for sub in child.body + child.orelse:
                if isinstance(sub, ast.Return) and sub.value is not None and isinstance(sub.value, ast.Call):
                    val = sub.value
                    if isinstance(val.func, ast.Name):
                        c_name = val.func.id
                        if c_name not in _PYTHON_BUILTINS and (
                            c_name[0].isupper()
                            or c_name.endswith("Service")
                            or c_name.endswith("Repository")
                            or c_name.endswith("Client")
                            or c_name.endswith("Store")
                        ):
                            ctor_candidates.add(c_name)
                    elif isinstance(val.func, ast.Attribute) and hasattr(ast, "unparse"):
                        ctor_candidates.add(ast.unparse(val.func))

    if len(ctor_candidates) == 1:
        return next(iter(ctor_candidates))
    return None


def _extract_python_file_declarations(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """Extract known return types and class names in a single Python AST."""
    fn_returns: dict[str, str] = {}
    known_classes: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef):
            known_classes.add(node.name)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ret = _infer_function_return(item)
                    if ret:
                        fn_returns[f"{node.name}.{item.name}"] = ret
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ret = _infer_function_return(node)
            if ret:
                fn_returns[node.name] = ret
    return fn_returns, known_classes


class _PythonScopeVisitor(ast.NodeVisitor):
    """Single-pass AST visitor maintaining scope context, bindings, and framework hooks."""

    def __init__(
        self,
        content: str,
        lines: list[str],
        file_path: str,
        analyzers: list[FrameworkAnalyzer],
        fn_return_types: dict[str, str] | None = None,
        known_classes: set[str] | None = None,
    ) -> None:
        self.content = content
        self.lines = lines
        self.file_path = file_path
        self.module = normalize_module(file_path, "python")
        self.is_init = file_path.replace("\\", "/").endswith("__init__.py")
        self.analyzers = analyzers
        self.fn_return_types = fn_return_types or {}
        self.known_classes = known_classes or set()

        self.symbols: list[Symbol] = []
        self.imports: list[ImportRef] = []
        self.calls: list[CallRef] = []
        self.inheritance: list[InheritanceRef] = []
        self.routes: list[RouteDetection] = []
        self.exports: list[str] = []

        # Scope stack: (name, kind, qualified_name, canonical_id)
        self.scope_stack: list[tuple[str, str, str, str]] = []
        # Local variable -> class/alias bindings per scope
        self.local_bindings_stack: list[dict[str, str]] = [{}]
        self.import_modules_set: set[str] = set()

    @property
    def current_scope_qname(self) -> str:
        return self.scope_stack[-1][2] if self.scope_stack else ""

    @property
    def current_scope_canonical_id(self) -> str:
        return self.scope_stack[-1][3] if self.scope_stack else self.module

    @property
    def current_scope_kind(self) -> str:
        return self.scope_stack[-1][1] if self.scope_stack else "module"

    @property
    def current_enclosing_class(self) -> str | None:
        for _name, kind, qname, _canon in reversed(self.scope_stack):
            if kind == "class":
                return qname
        return None

    def _make_context(self) -> AnalysisContext:
        return AnalysisContext(
            file_path=self.file_path,
            module=self.module,
            imports_modules=self.import_modules_set,
            scope_qname=self.current_scope_qname,
            scope_canonical_id=self.current_scope_canonical_id,
            scope_kind=self.current_scope_kind,
        )

    def _lookup_local_binding(self, var_name: str) -> str | None:
        for env in reversed(self.local_bindings_stack):
            if var_name in env:
                return env[var_name]
        return None

    def _extract_decorators(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> list[str]:
        dec_names: list[str] = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                dec_names.append(d.id)
            elif isinstance(d, ast.Attribute):
                dec_names.append(ast.unparse(d) if hasattr(ast, "unparse") else d.attr)
            elif isinstance(d, ast.Call):
                if isinstance(d.func, ast.Name):
                    dec_names.append(d.func.id)
                elif isinstance(d.func, ast.Attribute):
                    dec_names.append(ast.unparse(d.func) if hasattr(ast, "unparse") else d.func.attr)
        return dec_names

    def _visit_symbol_node(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        parent_scope = self.current_scope_qname
        parent_canon = self.scope_stack[-1][3] if self.scope_stack else None
        parent_kind = self.scope_stack[-1][1] if self.scope_stack else None

        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif parent_kind == "class":
            decorators = self._extract_decorators(node)
            kind = "property" if "property" in decorators else "method"
        else:
            kind = "function"

        qname = f"{parent_scope}.{node.name}" if parent_scope else node.name
        canon_id = build_canonical_id(self.module, parent_scope, node.name)
        decorators = self._extract_decorators(node)
        end_line = node.end_lineno or node.lineno

        sig = ""
        ret_type: str | None = None
        param_count: int | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            param_count = len(args)
            if node.returns and hasattr(ast, "unparse"):
                ret_type = ast.unparse(node.returns)
            elif node.name in self.fn_return_types:
                ret_type = self.fn_return_types[node.name]
            elif qname in self.fn_return_types:
                ret_type = self.fn_return_types[qname]
            sig = f"({', '.join(args)})" + (f" -> {ret_type}" if ret_type else "")
        elif isinstance(node, ast.ClassDef):
            bases_str = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
            sig = f"({', '.join(bases_str)})" if bases_str else ""
            for base in node.bases:
                base_name = ast.unparse(base) if hasattr(ast, "unparse") else getattr(base, "id", "")
                base_clean = base_name.split("[")[0].strip()
                if base_clean:
                    self.inheritance.append(
                        InheritanceRef(
                            source_symbol=qname,
                            base_name=base_clean,
                            relationship="EXTENDS",
                            source_file=self.file_path,
                            line=node.lineno,
                            source_canonical_id=canon_id,
                        )
                    )

        doc = ast.get_docstring(node)
        c_hash = _normalized_body_hash(self.lines, node.lineno, end_line)

        self.symbols.append(
            Symbol(
                id=canon_id,
                canonical_id=canon_id,
                name=node.name,
                qualified_name=qname,
                kind=kind,
                language="python",
                module=self.module,
                path=self.file_path,
                file_path=self.file_path,
                scope=parent_scope,
                signature=sig,
                start_line=node.lineno,
                end_line=end_line,
                content_hash=c_hash,
                parent_symbol_id=parent_canon,
                decorators=decorators,
                return_type=ret_type,
                parameter_count=param_count,
                documentation=doc,
            )
        )

        # Framework analyzer hook: check function for route decorators during this traversal
        ctx = self._make_context()
        for analyzer in self.analyzers:
            detected = analyzer.analyze_python_node(node, ctx)
            if detected:
                self.routes.extend(detected)

        # Push scope and visit children in single pass
        self.scope_stack.append((node.name, kind, qname, canon_id))
        self.local_bindings_stack.append({})
        for child in node.body:
            self.visit(child)
        self.local_bindings_stack.pop()
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_symbol_node(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_symbol_node(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_symbol_node(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.import_modules_set.add(alias.name)
            self.imports.append(
                ImportRef(
                    module=alias.name,
                    imported_module=alias.name,
                    imported_name=None,
                    alias=alias.asname,
                    local_name=alias.asname or alias.name.split(".")[0],
                    import_type="namespace" if alias.asname else "module",
                    line=node.lineno,
                    source_file=self.file_path,
                    source_module=self.module,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raw_mod = node.module or ""
        resolved_mod = (
            _resolve_relative_py_module(self.file_path, node.level, node.module)
            if node.level > 0
            else raw_mod
        )
        display_mod = raw_mod or resolved_mod
        if resolved_mod:
            self.import_modules_set.add(resolved_mod)
        if raw_mod:
            self.import_modules_set.add(raw_mod)

        for alias in node.names:
            full = f"{resolved_mod}.{alias.name}" if resolved_mod else alias.name
            is_reexp = self.is_init
            self.imports.append(
                ImportRef(
                    module=display_mod,
                    imported_module=resolved_mod or display_mod,
                    name=alias.name,
                    imported_name=alias.name,
                    alias=alias.asname,
                    local_name=alias.asname or alias.name,
                    import_type="reexport" if is_reexp else ("alias" if alias.asname else "named"),
                    is_reexport=is_reexp,
                    exported_name=alias.asname or alias.name if is_reexp else None,
                    line=node.lineno,
                    source_file=self.file_path,
                    source_module=self.module,
                    full=full,
                )
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self.exports.append(elt.value)
            elif isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name):
                    callee_name = node.value.func.id
                    if callee_name not in _PYTHON_BUILTINS:
                        if callee_name in self.fn_return_types:
                            self.local_bindings_stack[-1][target.id] = self.fn_return_types[callee_name]
                        elif callee_name in self.known_classes or (callee_name[0].isupper() and "_" not in callee_name):
                            self.local_bindings_stack[-1][target.id] = callee_name
                        elif any(callee_name.endswith(sfx) for sfx in ("Service", "Client", "Repository", "Manager", "Store", "View")):
                            self.local_bindings_stack[-1][target.id] = callee_name
                elif isinstance(node.value.func, ast.Attribute) and hasattr(ast, "unparse"):
                    attr_expr = ast.unparse(node.value.func)
                    if attr_expr in self.fn_return_types:
                        self.local_bindings_stack[-1][target.id] = self.fn_return_types[attr_expr]
                    elif attr_expr.split(".")[-1][0].isupper():
                        self.local_bindings_stack[-1][target.id] = attr_expr.split(".")[-1]
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
                callee_name = node.value.func.id
                if callee_name in self.fn_return_types:
                    self.local_bindings_stack[-1][f"self.{target.attr}"] = self.fn_return_types[callee_name]
                elif callee_name in self.known_classes or (callee_name[0].isupper() and "_" not in callee_name):
                    self.local_bindings_stack[-1][f"self.{target.attr}"] = callee_name

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and hasattr(ast, "unparse"):
            ann = ast.unparse(node.annotation).split("[")[0].strip()
            if ann and ann not in _PYTHON_BUILTINS:
                self.local_bindings_stack[-1][node.target.id] = ann
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Framework analyzer hook: check calls (e.g. Django path("login/", handler))
        ctx = self._make_context()
        for analyzer in self.analyzers:
            detected = analyzer.analyze_python_node(node, ctx)
            if detected:
                self.routes.extend(detected)

        caller_qname = self.current_scope_qname or None
        caller_canon = self.current_scope_canonical_id
        end_ln = node.end_lineno or node.lineno

        if isinstance(node.func, ast.Name):
            callee_name = node.func.id
            if callee_name not in _PYTHON_BUILTINS:
                self.calls.append(
                    CallRef(
                        callee=callee_name,
                        qualified_callee=callee_name,
                        line=node.lineno,
                        end_line=end_ln,
                        source_file=self.file_path,
                        confidence="LOW",
                        caller_symbol=caller_qname,
                        caller_canonical_id=caller_canon,
                        receiver=None,
                    )
                )
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            raw_recv = ast.unparse(node.func.value) if hasattr(ast, "unparse") else ""
            recv_clean = raw_recv[:-2].strip() if raw_recv.endswith("()") else raw_recv.strip()

            enclosing_cls = self.current_enclosing_class
            if recv_clean in ("self", "cls") and enclosing_cls:
                resolved_recv = enclosing_cls
            elif recv_clean.startswith("self.") and self._lookup_local_binding(recv_clean):
                resolved_recv = self._lookup_local_binding(recv_clean) or recv_clean
            else:
                bound = self._lookup_local_binding(recv_clean)
                resolved_recv = bound if bound else recv_clean

            q_callee = f"{resolved_recv}.{attr_name}" if resolved_recv else attr_name
            self.calls.append(
                CallRef(
                    callee=attr_name,
                    qualified_callee=q_callee,
                    line=node.lineno,
                    end_line=end_ln,
                    source_file=self.file_path,
                    confidence="LOW",
                    caller_symbol=caller_qname,
                    caller_canonical_id=caller_canon,
                    receiver=resolved_recv or None,
                )
            )

        self.generic_visit(node)


def _parse_python(content: str, file_path: str) -> ParseResult:
    source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return ParseResult(
            path=file_path,
            language="python",
            source_hash=source_hash,
            imports=tuple(_py_imports_fallback(content, file_path)),
            parse_failed=True,
            parse_error=f"SyntaxError at line {exc.lineno}: {exc.msg}",
        )

    # First collect import module names cheaply from top-level imports to configure analyzers
    import_mods: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_mods.add(node.module)

    analyzers = get_python_analyzers(import_mods)
    lines = content.splitlines()
    fn_returns, known_classes = _extract_python_file_declarations(tree)

    # Single-pass scoped traversal
    visitor = _PythonScopeVisitor(
        content,
        lines,
        file_path,
        analyzers,
        fn_return_types=fn_returns,
        known_classes=known_classes,
    )
    visitor.visit(tree)

    # Mark __all__ re-exports
    if visitor.exports:
        exported_set = set(visitor.exports)
        updated_imports: list[ImportRef] = []
        for imp in visitor.imports:
            if imp.local_name in exported_set and not imp.is_reexport:
                updated_imports.append(
                    ImportRef(
                        module=imp.module,
                        imported_module=imp.imported_module,
                        name=imp.name,
                        imported_name=imp.imported_name,
                        alias=imp.alias,
                        local_name=imp.local_name,
                        import_type="reexport",
                        is_reexport=True,
                        exported_name=imp.local_name,
                        line=imp.line,
                        source_file=imp.source_file,
                        source_module=imp.source_module,
                        full=imp.full,
                    )
                )
            else:
                updated_imports.append(imp)
        visitor.imports = updated_imports

    visitor.symbols.sort(key=lambda s: (s.start_line, s.canonical_id))
    return ParseResult(
        path=file_path,
        language="python",
        source_hash=source_hash,
        symbols=tuple(visitor.symbols),
        imports=tuple(visitor.imports),
        calls=tuple(visitor.calls),
        inheritance=tuple(visitor.inheritance),
        routes=tuple(visitor.routes),
        exports=tuple(visitor.exports),
        parse_failed=False,
    )


def _py_imports_fallback(content: str, file_path: str) -> list[ImportRef]:
    imports: list[ImportRef] = []
    for m in _PY_IMPORT.finditer(content):
        module = (m.group(1) or "").strip() or (m.group(2) or "").strip().split(",")[0].strip()
        if module:
            imports.append(ImportRef(module=module, source_file=file_path))
    return imports


# ---------------------------------------------------------------------------
# JavaScript / TypeScript single-pass scoped analyzer
# ---------------------------------------------------------------------------

_JS_CLASS_RE = re.compile(
    r"\b(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+([A-Za-z_$][\w$.]*))?"
    r"(?:\s+implements\s+([A-Za-z_$][\w$.,\s]*))?\s*\{"
)

_TS_INTERFACE_RE = re.compile(
    r"\b(?:export\s+(?:default\s+)?)?interface\s+([A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+([A-Za-z_$][\w$.,\s]*))?"
)

_TS_TYPE_RE = re.compile(
    r"\b(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*="
)

_JS_FUNC_RE = re.compile(
    r"(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
    r"|(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)

_JS_METHOD_RE = re.compile(
    r"^\s{2,}(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*[^{]+)?\{"
)

_JS_IMPORT_NAMED = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]"""
)
_JS_IMPORT_NAMESPACE = re.compile(
    r"""import\s+\*\s+as\s+([A-Za-z_$][\w$]*)\s+from\s+['"]([^'"]+)['"]"""
)
_JS_IMPORT_DEFAULT = re.compile(
    r"""import\s+([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s+from\s+['"]([^'"]+)['"]"""
)
_JS_IMPORT_SIDE_EFFECT = re.compile(
    r"""import\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)"""
)
_JS_REEXPORT_NAMED = re.compile(
    r"""export\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]"""
)
_JS_REEXPORT_ALL = re.compile(
    r"""export\s+\*\s*(?:as\s+([A-Za-z_$][\w$]*)\s+)?from\s+['"]([^'"]+)['"]"""
)
_JS_NEW_ASSIGN = re.compile(
    r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*new\s+([A-Za-z_$][\w$.]*)\s*\("""
)
_JS_CALL_SITE = re.compile(
    r"""(?<!function\s)(?<!new\s)\b(?:([A-Za-z_$][\w$]*)\.)?([A-Za-z_$][\w$]*)\s*\("""
)


def _parse_js_ts(content: str, language: str, file_path: str) -> ParseResult:
    source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    module = normalize_module(file_path, language)
    lines = content.splitlines()

    symbols: list[Symbol] = []
    imports: list[ImportRef] = []
    calls: list[CallRef] = []
    inheritance: list[InheritanceRef] = []
    routes: list[RouteDetection] = []
    exports: list[str] = []

    def line_of(offset: int) -> int:
        return content.count("\n", 0, offset) + 1

    # 1. Imports and Re-exports
    recorded_import_lines: set[tuple[str, str | None, str | None]] = set()

    for m in _JS_REEXPORT_NAMED.finditer(content):
        specifiers = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        for raw_spec in specifiers.split(","):
            spec = raw_spec.strip()
            if not spec:
                continue
            if spec.startswith("type "):
                spec = spec[5:].strip()
            if " as " in spec:
                orig, aliased = [p.strip() for p in spec.split(" as ", 1)]
            else:
                orig, aliased = spec, spec
            exports.append(aliased)
            imports.append(
                ImportRef(
                    module=target_mod,
                    imported_module=target_mod,
                    name=orig,
                    imported_name=orig,
                    alias=aliased if aliased != orig else None,
                    local_name=aliased,
                    import_type="reexport",
                    is_reexport=True,
                    exported_name=aliased,
                    line=ln,
                    source_file=file_path,
                    source_module=module,
                )
            )
            recorded_import_lines.add((target_mod, orig, aliased))

    for m in _JS_REEXPORT_ALL.finditer(content):
        ns_alias = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        imports.append(
            ImportRef(
                module=target_mod,
                imported_module=target_mod,
                name="*",
                imported_name="*",
                alias=ns_alias,
                local_name=ns_alias or "*",
                import_type="reexport",
                is_reexport=True,
                exported_name=ns_alias or "*",
                line=ln,
                source_file=file_path,
                source_module=module,
            )
        )
        recorded_import_lines.add((target_mod, "*", ns_alias))

    for m in _JS_IMPORT_NAMED.finditer(content):
        specifiers = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        for raw_spec in specifiers.split(","):
            spec = raw_spec.strip()
            if not spec:
                continue
            if spec.startswith("type "):
                spec = spec[5:].strip()
            if " as " in spec:
                orig, aliased = [p.strip() for p in spec.split(" as ", 1)]
            else:
                orig, aliased = spec, None
            imports.append(
                ImportRef(
                    module=target_mod,
                    imported_module=target_mod,
                    name=orig,
                    imported_name=orig,
                    alias=aliased,
                    local_name=aliased or orig,
                    import_type="alias" if aliased else "named",
                    line=ln,
                    source_file=file_path,
                    source_module=module,
                )
            )
            recorded_import_lines.add((target_mod, orig, aliased))

    for m in _JS_IMPORT_NAMESPACE.finditer(content):
        ns_alias = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        imports.append(
            ImportRef(
                module=target_mod,
                imported_module=target_mod,
                name="*",
                imported_name="*",
                alias=ns_alias,
                local_name=ns_alias,
                import_type="namespace",
                line=ln,
                source_file=file_path,
                source_module=module,
            )
        )
        recorded_import_lines.add((target_mod, "*", ns_alias))

    for m in _JS_IMPORT_DEFAULT.finditer(content):
        def_name = m.group(1)
        if def_name == "type":
            continue
        target_mod = m.group(2)
        ln = line_of(m.start())
        imports.append(
            ImportRef(
                module=target_mod,
                imported_module=target_mod,
                name="default",
                imported_name="default",
                alias=def_name,
                local_name=def_name,
                import_type="default",
                line=ln,
                source_file=file_path,
                source_module=module,
            )
        )
        recorded_import_lines.add((target_mod, "default", def_name))

    for m in _JS_IMPORT_SIDE_EFFECT.finditer(content):
        target_mod = m.group(1) or m.group(2)
        if target_mod and not any(r[0] == target_mod for r in recorded_import_lines):
            imports.append(
                ImportRef(
                    module=target_mod,
                    imported_module=target_mod,
                    import_type="module",
                    line=line_of(m.start()),
                    source_file=file_path,
                    source_module=module,
                )
            )

    local_new_bindings: dict[str, str] = {}
    for m in _JS_NEW_ASSIGN.finditer(content):
        local_new_bindings[m.group(1)] = m.group(2)

    import_mods_set = {imp.imported_module for imp in imports}

    # 2. Single-pass scoped line scan
    active_class: tuple[str, str, int] | None = None
    active_func: tuple[str, str, int] | None = None
    seen_canonical: set[str] = set()

    for idx, line in enumerate(lines):
        lineno = idx + 1
        if active_class and lineno > active_class[2]:
            active_class = None
        if active_func and lineno > active_func[2]:
            active_func = None

        # Route detection hook per line (Express and Next.js)
        detected_routes = analyze_js_ts_line(line, lineno, file_path, module, import_mods_set)
        if detected_routes:
            routes.extend(detected_routes)

        # Class declaration
        cls_match = _JS_CLASS_RE.search(line)
        if cls_match:
            cls_name = cls_match.group(1)
            extends_name = cls_match.group(2)
            implements_raw = cls_match.group(3)
            end_ln = _estimate_block_end(lines, idx)
            canon_id = build_canonical_id(module, "", cls_name)
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=cls_name,
                        qualified_name=cls_name,
                        kind="class",
                        language=language,
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                    )
                )
            if extends_name:
                inheritance.append(
                    InheritanceRef(
                        source_symbol=cls_name,
                        base_name=extends_name.strip(),
                        relationship="EXTENDS",
                        source_file=file_path,
                        line=lineno,
                        source_canonical_id=canon_id,
                    )
                )
            if implements_raw:
                for iface in implements_raw.split(","):
                    iface_clean = iface.split("<")[0].strip()
                    if iface_clean:
                        inheritance.append(
                            InheritanceRef(
                                source_symbol=cls_name,
                                base_name=iface_clean,
                                relationship="IMPLEMENTS",
                                source_file=file_path,
                                line=lineno,
                                source_canonical_id=canon_id,
                            )
                        )
            active_class = (cls_name, canon_id, end_ln)

        # TypeScript interface / type
        if language == "typescript":
            iface_match = _TS_INTERFACE_RE.search(line)
            if iface_match:
                iface_name = iface_match.group(1)
                extends_raw = iface_match.group(2)
                end_ln = _estimate_block_end(lines, idx)
                canon_id = build_canonical_id(module, "", iface_name)
                if canon_id not in seen_canonical:
                    seen_canonical.add(canon_id)
                    symbols.append(
                        Symbol(
                            id=canon_id,
                            canonical_id=canon_id,
                            name=iface_name,
                            qualified_name=iface_name,
                            kind="interface",
                            language=language,
                            module=module,
                            path=file_path,
                            file_path=file_path,
                            scope="",
                            start_line=lineno,
                            end_line=end_ln,
                            content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        )
                    )
                if extends_raw:
                    for base_if in extends_raw.split(","):
                        base_clean = base_if.split("<")[0].strip()
                        if base_clean:
                            inheritance.append(
                                InheritanceRef(
                                    source_symbol=iface_name,
                                    base_name=base_clean,
                                    relationship="EXTENDS",
                                    source_file=file_path,
                                    line=lineno,
                                    source_canonical_id=canon_id,
                                )
                            )

            type_match = _TS_TYPE_RE.search(line)
            if type_match:
                t_name = type_match.group(1)
                canon_id = build_canonical_id(module, "", t_name)
                if canon_id not in seen_canonical:
                    seen_canonical.add(canon_id)
                    symbols.append(
                        Symbol(
                            id=canon_id,
                            canonical_id=canon_id,
                            name=t_name,
                            qualified_name=t_name,
                            kind="type",
                            language=language,
                            module=module,
                            path=file_path,
                            file_path=file_path,
                            scope="",
                            start_line=lineno,
                            end_line=lineno,
                            content_hash=_normalized_body_hash(lines, lineno, lineno),
                        )
                    )

        # Method inside active class
        if active_class:
            m_match = _JS_METHOD_RE.match(line)
            if m_match:
                m_name = m_match.group(1)
                if m_name and m_name not in _JS_KEYWORDS_AND_BUILTINS:
                    end_ln = _estimate_block_end(lines, idx)
                    cls_name, cls_canon, _ = active_class
                    qname = f"{cls_name}.{m_name}"
                    canon_id = build_canonical_id(module, cls_name, m_name)
                    if canon_id not in seen_canonical:
                        seen_canonical.add(canon_id)
                        symbols.append(
                            Symbol(
                                id=canon_id,
                                canonical_id=canon_id,
                                name=m_name,
                                qualified_name=qname,
                                kind="method",
                                language=language,
                                module=module,
                                path=file_path,
                                file_path=file_path,
                                scope=cls_name,
                                start_line=lineno,
                                end_line=end_ln,
                                content_hash=_normalized_body_hash(lines, lineno, end_ln),
                                parent_symbol_id=cls_canon,
                            )
                        )
                    active_func = (qname, canon_id, end_ln)

        # Top-level or nested function / arrow function
        for fn_match in _JS_FUNC_RE.finditer(line):
            fn_name = fn_match.group(1) or fn_match.group(3)
            if fn_name and fn_name not in _JS_KEYWORDS_AND_BUILTINS:
                end_ln = _estimate_block_end(lines, idx)
                scope_str = active_class[0] if active_class else ""
                qname = f"{scope_str}.{fn_name}" if scope_str else fn_name
                canon_id = build_canonical_id(module, scope_str, fn_name)
                parent_id = active_class[1] if active_class else None
                kind = "method" if active_class else "function"
                if canon_id not in seen_canonical:
                    seen_canonical.add(canon_id)
                    symbols.append(
                        Symbol(
                            id=canon_id,
                            canonical_id=canon_id,
                            name=fn_name,
                            qualified_name=qname,
                            kind=kind,
                            language=language,
                            module=module,
                            path=file_path,
                            file_path=file_path,
                            scope=scope_str,
                            start_line=lineno,
                            end_line=end_ln,
                            content_hash=_normalized_body_hash(lines, lineno, end_ln),
                            parent_symbol_id=parent_id,
                        )
                    )
                active_func = (qname, canon_id, end_ln)

        # Call sites
        stripped = line.strip()
        if not stripped.startswith(("import ", "export {", "export *", "interface ", "type ", "//")):
            caller_qname = (
                active_func[0]
                if active_func
                else (active_class[0] if active_class else None)
            )
            caller_canon = (
                active_func[1]
                if active_func
                else (active_class[1] if active_class else module)
            )
            for cm in _JS_CALL_SITE.finditer(line):
                recv = cm.group(1)
                callee_nm = cm.group(2)
                if callee_nm in _JS_KEYWORDS_AND_BUILTINS:
                    continue
                if recv in _JS_KEYWORDS_AND_BUILTINS and recv != "this":
                    continue
                resolved_recv = recv
                if recv == "this" and active_class:
                    resolved_recv = active_class[0]
                elif recv and recv in local_new_bindings:
                    resolved_recv = local_new_bindings[recv]
                q_callee = f"{resolved_recv}.{callee_nm}" if resolved_recv else callee_nm
                calls.append(
                    CallRef(
                        callee=callee_nm,
                        qualified_callee=q_callee,
                        line=lineno,
                        end_line=lineno,
                        source_file=file_path,
                        confidence="LOW",
                        caller_symbol=caller_qname,
                        caller_canonical_id=caller_canon,
                        receiver=resolved_recv,
                    )
                )

    symbols.sort(key=lambda s: (s.start_line, s.canonical_id))
    return ParseResult(
        path=file_path,
        language=language,
        source_hash=source_hash,
        symbols=tuple(symbols),
        imports=tuple(imports),
        calls=tuple(calls),
        inheritance=tuple(inheritance),
        routes=tuple(routes),
        exports=tuple(exports),
        parse_failed=False,
    )


def _estimate_block_end(lines: list[str], start_idx: int) -> int:
    """Walk forward counting braces to estimate block end line."""
    depth = 0
    opened = False
    for i, line in enumerate(lines[start_idx:], start=start_idx):
        opens = line.count("{")
        closes = line.count("}")
        if opens > 0:
            opened = True
        depth += opens - closes
        if opened and depth <= 0:
            return i + 1
        if not opened and i == start_idx and ";" in line:
            return i + 1
    return len(lines)
