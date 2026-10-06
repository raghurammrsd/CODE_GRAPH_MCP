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
import json
import posixpath
import re
from dataclasses import asdict, dataclass

from codegraph.frameworks import (
    AnalysisContext,
    FrameworkAnalyzer,
    RouteDetection,
    RouterDefinition,
    RouterMountDetection,
    analyze_js_ts_line,
    analyze_js_ts_mounts,
    get_python_analyzers,
)
from codegraph.frameworks_nestjs import analyze_nestjs_file
from codegraph.frameworks_nextjs import analyze_nextjs_file
from codegraph.frameworks_react import analyze_react_file
from codegraph.semantic_decorators import analyze_symbol_decorators

from .models import (
    BindingRef,
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
    mounts: tuple[RouterMountDetection, ...] = ()
    router_definitions: tuple[RouterDefinition, ...] = ()
    bindings: tuple[BindingRef, ...] = ()
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
            "mounts": [m.as_dict() for m in self.mounts],
            "router_definitions": [d.as_dict() for d in self.router_definitions],
            "bindings": [b.as_dict() for b in self.bindings],
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
    if language == "html" or file_path.lower().endswith((".html", ".htm", ".jinja", ".jinja2", ".njk", ".ejs")):
        from codegraph.indexing.templates import parse_html_template
        return parse_html_template(content, file_path)
    if language in ("sql", "prisma"):
        source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        return ParseResult(
            path=file_path,
            language=language,
            source_hash=source_hash,
            parse_failed=False,
        )
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
    """Conservatively infer return type from explicit annotation or unambiguous constructor/factory return."""
    clean_ann: str | None = None
    # 1. Explicit return annotation
    if node.returns and hasattr(ast, "unparse"):
        raw = ast.unparse(node.returns).strip()
        if "|" in raw:
            parts = [p.strip() for p in raw.split("|") if p.strip() not in ("None", "NoneType")]
            if len(parts) != 1:
                return None
            raw = parts[0]
        m_union = re.match(r"^(?:Union|typing\.Union)\[\s*(.+)\s*\]$", raw)
        if m_union:
            parts = [p.strip() for p in m_union.group(1).split(",") if p.strip() not in ("None", "NoneType")]
            if len(parts) != 1:
                return None
            raw = parts[0]
        m_opt = re.match(r"^(?:Optional|typing\.Optional)\[\s*([A-Za-z_][\w.]*)\s*\]$", raw)
        if m_opt:
            raw = m_opt.group(1)
        raw = raw.strip("'\"")
        clean = raw.split("[")[0].strip()
        if clean and clean not in _PYTHON_BUILTINS and clean not in ("Any", "typing.Any", "object", "Callable", "typing.Callable", "Union", "typing.Union"):
            clean_ann = clean

    # 2. Inspect function body for constructor/factory returns and detect conflicting/dynamic branches
    local_types: dict[str, str] = {}
    for arg in list(node.args.args) + list(node.args.kwonlyargs):
        if arg.annotation and hasattr(ast, "unparse"):
            a_type = ast.unparse(arg.annotation).split("[")[0].strip().strip("'\"")
            if a_type and a_type not in _PYTHON_BUILTINS:
                local_types[arg.arg] = a_type

    ctor_candidates: set[str] = set()

    def _walk_body_stmts(stmts: list[ast.stmt], in_cond: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                var_name = stmt.targets[0].id
                rhs_type = "<DYNAMIC>"
                if isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        fn_id = stmt.value.func.id
                        if fn_id not in ("getattr", "globals", "locals", "__import__", "eval") and fn_id not in _PYTHON_BUILTINS:
                            rhs_type = fn_id
                    elif isinstance(stmt.value.func, ast.Attribute) and hasattr(ast, "unparse"):
                        rhs_type = ast.unparse(stmt.value.func).strip()
                elif isinstance(stmt.value, ast.Name):
                    rhs_type = local_types.get(stmt.value.id, "<DYNAMIC>")
                if in_cond or (var_name in local_types and local_types[var_name] != rhs_type):
                    local_types[var_name] = "<AMBIGUOUS>"
                else:
                    local_types[var_name] = rhs_type
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and hasattr(ast, "unparse"):
                var_name = stmt.target.id
                ann_t = ast.unparse(stmt.annotation).split("[")[0].strip().strip("'\"")
                if in_cond or (var_name in local_types and local_types[var_name] != ann_t):
                    local_types[var_name] = "<AMBIGUOUS>"
                elif ann_t and ann_t not in _PYTHON_BUILTINS:
                    local_types[var_name] = ann_t
            elif isinstance(stmt, ast.Return) and stmt.value is not None:
                val = stmt.value
                if isinstance(val, ast.Constant) and val.value is None:
                    continue
                if isinstance(val, ast.Call):
                    if isinstance(val.func, ast.Name):
                        c_name = val.func.id
                        if c_name in ("getattr", "globals", "locals", "__import__", "eval") or c_name in _PYTHON_BUILTINS:
                            ctor_candidates.add("<DYNAMIC>")
                        elif c_name in local_types:
                            ctor_candidates.add(local_types[c_name])
                        else:
                            ctor_candidates.add(c_name)
                    elif isinstance(val.func, ast.Attribute) and hasattr(ast, "unparse"):
                        ctor_candidates.add(ast.unparse(val.func).strip())
                    else:
                        ctor_candidates.add("<DYNAMIC>")
                elif isinstance(val, ast.Name):
                    mapped = local_types.get(val.id)
                    if mapped:
                        ctor_candidates.add(mapped)
                    else:
                        ctor_candidates.add("<DYNAMIC>")
                else:
                    ctor_candidates.add("<DYNAMIC>")
            elif isinstance(stmt, ast.If):
                _walk_body_stmts(stmt.body, True)
                _walk_body_stmts(stmt.orelse, True)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                _walk_body_stmts(stmt.body, True)
                _walk_body_stmts(getattr(stmt, "orelse", []), True)
            elif isinstance(stmt, ast.Try):
                _walk_body_stmts(stmt.body, True)
                for h in stmt.handlers:
                    _walk_body_stmts(h.body, True)
                _walk_body_stmts(stmt.orelse, True)
                _walk_body_stmts(stmt.finalbody, True)

    _walk_body_stmts(node.body, False)

    # If the body has multiple distinct return constructors or dynamic dispatch, do not claim a single static return type
    real_ctors = {c for c in ctor_candidates if c not in ("<DYNAMIC>", "<AMBIGUOUS>")}
    if len(real_ctors) > 1 or "<AMBIGUOUS>" in ctor_candidates:
        return None
    if "<DYNAMIC>" in ctor_candidates and not clean_ann:
        return None
    if clean_ann:
        return clean_ann
    if len(real_ctors) == 1:
        only_cand = next(iter(real_ctors))
        if only_cand not in _PYTHON_BUILTINS:
            return only_cand
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
        all_file_imports: list[ImportRef] | None = None,
    ) -> None:
        self.content = content
        self.lines = lines
        self.file_path = file_path
        self.module = normalize_module(file_path, "python")
        self.is_init = file_path.replace("\\", "/").endswith("__init__.py")
        self.analyzers = analyzers
        self.fn_return_types = fn_return_types or {}
        self.known_classes = known_classes or set()
        self.all_file_imports = all_file_imports or []

        self.symbols: list[Symbol] = []
        self.imports: list[ImportRef] = []
        self.calls: list[CallRef] = []
        self.inheritance: list[InheritanceRef] = []
        self.routes: list[RouteDetection] = []
        self.mounts: list[RouterMountDetection] = []
        self.router_definitions: list[RouterDefinition] = []
        self.bindings: list[BindingRef] = []
        self.exports: list[str] = []
        self.conditional_depth: int = 0
        self.di_type_aliases: dict[str, str] = {}

        # Scope stack: (name, kind, qualified_name, canonical_id)
        self.scope_stack: list[tuple[str, str, str, str]] = []
        # Local variable -> class/alias bindings per scope
        self.local_bindings_stack: list[dict[str, str]] = [{}]
        self.import_modules_set: set[str] = set()
        self._cached_binding_resolver: tuple[int, int, object] | None = None

    def _get_local_binding_resolver(self) -> object:
        if (
            self._cached_binding_resolver is not None
            and self._cached_binding_resolver[0] == len(self.bindings)
            and self._cached_binding_resolver[1] == len(self.symbols)
        ):
            return self._cached_binding_resolver[2]
        from codegraph.binding_resolver import LocalBindingResolver

        resolver = LocalBindingResolver(
            bindings=self.bindings,
            symbols=self.symbols,
            imports=self.all_file_imports or self.imports,
            known_files={self.file_path},
            resolve_symbol_in_module=lambda m, s: None,
            resolve_import_target=lambda imp: (None, imp.imported_module),
        )
        self._cached_binding_resolver = (len(self.bindings), len(self.symbols), resolver)
        return resolver

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
                val = env[var_name]
                if val in ("<AMBIGUOUS>", "<DYNAMIC>"):
                    return None
                return val
        return None

    def _bind_in_local_scope(self, var_name: str, inferred_type: str) -> None:
        if not self.local_bindings_stack:
            return
        env = self.local_bindings_stack[-1]
        if self.conditional_depth > 0:
            env[var_name] = "<AMBIGUOUS>"
        elif var_name in env and env[var_name] != inferred_type:
            env[var_name] = "<AMBIGUOUS>"
        else:
            env[var_name] = inferred_type

    def _bind_in_class_scope(self, attr_name: str, inferred_type: str) -> None:
        self._bind_in_local_scope(attr_name, inferred_type)
        if len(self.local_bindings_stack) >= 2 and len(self.scope_stack) >= 2:
            for idx in range(len(self.scope_stack) - 1, -1, -1):
                if self.scope_stack[idx][1] == "class" and idx + 1 < len(self.local_bindings_stack):
                    cls_env = self.local_bindings_stack[idx + 1]
                    if self.conditional_depth > 0:
                        cls_env[attr_name] = "<AMBIGUOUS>"
                    elif attr_name in cls_env and cls_env[attr_name] != inferred_type:
                        cls_env[attr_name] = "<AMBIGUOUS>"
                    else:
                        cls_env[attr_name] = inferred_type
                    break

    def _extract_decorators(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> list[str]:
        if not node.decorator_list:
            return []
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
        decorators = self._extract_decorators(node)

        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif parent_kind == "class":
            kind = "property" if "property" in decorators else "method"
        else:
            kind = "function"

        qname = f"{parent_scope}.{node.name}" if parent_scope else node.name
        canon_id = build_canonical_id(self.module, parent_scope, node.name)
        end_line = node.end_lineno or node.lineno

        sig = ""
        ret_type: str | None = None
        param_count: int | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            param_count = len(args)
            if qname in self.fn_return_types:
                ret_type = self.fn_return_types[qname]
            elif node.name in self.fn_return_types:
                ret_type = self.fn_return_types[node.name]
            else:
                ret_type = _infer_function_return(node)
            sig_ret = ast.unparse(node.returns) if (node.returns and hasattr(ast, "unparse")) else ret_type
            sig = f"({', '.join(args)})" + (f" -> {sig_ret}" if sig_ret else "")
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

        # Avoid duplicate canonical symbol IDs for @name.setter within the same class
        is_setter = any(d.endswith(".setter") for d in decorators)
        existing_prop = None
        if is_setter and parent_kind == "class":
            for s in self.symbols:
                if s.canonical_id == canon_id and s.kind == "property":
                    existing_prop = s
                    break

        if existing_prop is not None:
            # Merge setter signature/span into the existing property symbol
            idx = self.symbols.index(existing_prop)
            self.symbols[idx] = Symbol(
                id=existing_prop.id,
                canonical_id=existing_prop.canonical_id,
                name=existing_prop.name,
                qualified_name=existing_prop.qualified_name,
                kind="property",
                language=existing_prop.language,
                module=existing_prop.module,
                path=existing_prop.path,
                file_path=existing_prop.file_path,
                scope=existing_prop.scope,
                signature=f"{existing_prop.signature} | setter: {sig}" if existing_prop.signature else sig,
                start_line=existing_prop.start_line,
                end_line=max(existing_prop.end_line, end_line),
                content_hash=c_hash,
                parent_symbol_id=existing_prop.parent_symbol_id,
                decorators=list(dict.fromkeys(existing_prop.decorators + decorators)),
                return_type=existing_prop.return_type,
                parameter_count=existing_prop.parameter_count,
                documentation=existing_prop.documentation or doc,
            )
        else:
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

        # Framework analyzer hook: check function/class for route decorators during this traversal
        if node.decorator_list or isinstance(node, ast.ClassDef):
            ctx = self._make_context()
            for analyzer in self.analyzers:
                detected = analyzer.analyze_python_node(node, ctx)
                if detected:
                    self.routes.extend(detected)

        # Semantic Decorators (Celery, Click, Typer, Django receiver, Registry)
        if node.decorator_list:
            local_resolver = self._get_local_binding_resolver()
            dec_detections = analyze_symbol_decorators(
                node=node,
                file_path=self.file_path,
                target_canonical_id=canon_id,
                imports=self.all_file_imports or self.imports,
                binding_resolver=local_resolver,  # type: ignore[arg-type]
                conditional_depth=self.conditional_depth,
            )
        else:
            dec_detections = []
        for det in dec_detections:
            self.bindings.append(
                BindingRef(
                    target_name=det.target_canonical_id,
                    file_path=self.file_path,
                    line=det.line,
                    column=getattr(node, "col_offset", None),
                    scope=self.current_scope_qname,
                    expr_kind="SEMANTIC_DECORATOR",
                    source_expr=det.decorator_expr,
                    is_conditional=det.is_conditional,
                    base_expr=det.framework,
                    attr_name=det.semantic_role,
                    subscript_key=json.dumps(det.metadata),
                    subscript_target=det.reason if det.is_dynamic_arg else None,
                )
            )

        # Test fixture usage & fixture definition detection
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_test_ctx = node.name.startswith("test_") or "test" in self.file_path.lower()
            if is_test_ctx:
                for a in node.args.args:
                    if a.arg not in ("self", "cls"):
                        self.bindings.append(
                            BindingRef(
                                target_name=a.arg,
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(a, "col_offset", None),
                                scope=qname,
                                expr_kind="TEST_FIXTURE_USE",
                                source_expr=a.arg,
                                base_expr=node.name,
                            )
                        )
            if any("fixture" in d.lower() for d in decorators):
                self.bindings.append(
                    BindingRef(
                        target_name=node.name,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=parent_scope,
                        expr_kind="PYTEST_FIXTURE_DEF",
                        source_expr=ret_type or node.name,
                        base_expr=node.name,
                    )
                )

        # Dependency Injection parameter analysis (FastAPI Depends & Constructor/Type-based injection)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._extract_di_parameters(node, canon_id, parent_canon, decorators)

        # Push scope and visit children in single pass
        self.scope_stack.append((node.name, kind, qname, canon_id))
        param_bindings: dict[str, str] = {}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.annotation and hasattr(ast, "unparse"):
                    ann_type = ast.unparse(arg.annotation).split("[")[0].strip()
                    if ann_type and ann_type not in _PYTHON_BUILTINS:
                        param_bindings[arg.arg] = ann_type
        self.local_bindings_stack.append(param_bindings)
        for child in node.body:
            self.visit(child)
        self.local_bindings_stack.pop()
        self.scope_stack.pop()

    def _extract_di_parameters(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        canon_id: str,
        parent_canon: str | None,
        decorators: list[str],
    ) -> None:
        is_cond = self.conditional_depth > 0
        has_inject_decorator = any("inject" in d.lower() for d in decorators)
        is_init = (node.name == "__init__")

        # Map positional arguments to defaults
        pos_args = node.args.args
        num_pos_defaults = len(node.args.defaults)
        defaults_map: dict[str, ast.expr] = {}
        if num_pos_defaults > 0:
            for arg, def_val in zip(pos_args[-num_pos_defaults:], node.args.defaults, strict=False):
                defaults_map[arg.arg] = def_val
        for arg, kw_def in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False):
            if kw_def is not None:
                defaults_map[arg.arg] = kw_def

        all_args = list(node.args.args) + list(node.args.kwonlyargs)
        for arg in all_args:
            if arg.arg in ("self", "cls"):
                continue

            dep_expr: str | None = None
            is_dynamic_dep = False

            # Check default value: param = Depends(get_db) or Depends(dependency=get_db)
            def_node = defaults_map.get(arg.arg)
            if isinstance(def_node, ast.Call):
                func_nm = getattr(def_node.func, "id", None) or (
                    getattr(def_node.func, "attr", None) if isinstance(def_node.func, ast.Attribute) else ""
                )
                if func_nm == "Depends":
                    dep_arg: ast.expr | None = def_node.args[0] if def_node.args else None
                    if dep_arg is None:
                        dep_kw = next((kw for kw in def_node.keywords if kw.arg == "dependency"), None)
                        if dep_kw is not None:
                            dep_arg = dep_kw.value
                    if dep_arg is not None:
                        if isinstance(dep_arg, (ast.Name, ast.Attribute)) and hasattr(ast, "unparse"):
                            dep_expr = ast.unparse(dep_arg)
                        else:
                            dep_expr = "<DYNAMIC>"
                            is_dynamic_dep = True
                    elif arg.annotation and hasattr(ast, "unparse"):
                        dep_expr = ast.unparse(arg.annotation).split("[")[0].strip()

            # Check annotation: param: Annotated[Session, Depends(get_db)]
            if not dep_expr and isinstance(arg.annotation, ast.Subscript) and hasattr(ast, "unparse"):
                ann_val = getattr(arg.annotation.value, "id", None) or (
                    getattr(arg.annotation.value, "attr", None) if isinstance(arg.annotation.value, ast.Attribute) else ""
                )
                if ann_val == "Annotated":
                    slice_node = arg.annotation.slice
                    elts = slice_node.elts if isinstance(slice_node, (ast.Tuple, ast.List)) else [slice_node]
                    for elt in elts[1:]:
                        if isinstance(elt, ast.Call):
                            f_nm = getattr(elt.func, "id", None) or (
                                getattr(elt.func, "attr", None) if isinstance(elt.func, ast.Attribute) else ""
                            )
                            if f_nm == "Depends":
                                elt_arg: ast.expr | None = elt.args[0] if elt.args else None
                                if elt_arg is None:
                                    elt_kw = next((kw for kw in elt.keywords if kw.arg == "dependency"), None)
                                    if elt_kw is not None:
                                        elt_arg = elt_kw.value
                                if elt_arg is not None:
                                    if isinstance(elt_arg, (ast.Name, ast.Attribute)):
                                        dep_expr = ast.unparse(elt_arg)
                                    else:
                                        dep_expr = "<DYNAMIC>"
                                        is_dynamic_dep = True
                                elif hasattr(ast, "unparse"):
                                    dep_expr = ast.unparse(elts[0]).split("[")[0].strip()
                                break

            # Check if annotation refers to an Annotated type alias: e.g. session: SessionDep, current_user: CurrentUser
            if not dep_expr and arg.annotation and hasattr(ast, "unparse"):
                ann_text = ast.unparse(arg.annotation).strip()
                ann_short = ann_text.split("[")[0].strip().split(".")[-1]
                if ann_short in self.di_type_aliases:
                    dep_expr = self.di_type_aliases[ann_short]
                elif (
                    ann_short not in _PYTHON_BUILTINS
                    and not ann_short.startswith("_")
                    and ann_short not in (
                        "Any", "Optional", "Union", "List", "Dict", "Set", "Tuple",
                        "int", "str", "float", "bool", "bytes", "dict", "list", "set", "tuple",
                    )
                ):
                    self.bindings.append(
                        BindingRef(
                            target_name=canon_id,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="PARAM_TYPE_DI",
                            source_expr=ann_text,
                            is_conditional=is_cond,
                            base_expr="fastapi",
                            attr_name="Depends",
                            subscript_key=json.dumps({"param": arg.arg, "alias": ann_short, "framework": "fastapi"}),
                        )
                    )

            if dep_expr:
                self.bindings.append(
                    BindingRef(
                        target_name=canon_id,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="DI_INJECTS",
                        source_expr=dep_expr,
                        is_conditional=is_cond,
                        base_expr="fastapi",
                        attr_name="Depends",
                        subscript_target="dynamic_provider" if is_dynamic_dep else None,
                        subscript_key=json.dumps({"param": arg.arg, "framework": "fastapi"}),
                    )
                )

            # Constructor or @inject parameter annotation
            if (is_init or has_inject_decorator) and arg.annotation and hasattr(ast, "unparse"):
                ann_str = ast.unparse(arg.annotation).split("[")[0].strip()
                if ann_str and ann_str not in _PYTHON_BUILTINS and not ann_str.startswith("_"):
                    tgt_id = parent_canon if (is_init and parent_canon) else canon_id
                    self.bindings.append(
                        BindingRef(
                            target_name=tgt_id,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="CONSTRUCTOR_PARAM",
                            source_expr=ann_str,
                            is_conditional=is_cond,
                            base_expr="inject_decorator" if has_inject_decorator else "constructor",
                            attr_name=arg.arg,
                            subscript_key=json.dumps({"param": arg.arg, "type": ann_str}),
                        )
                    )

        # Route decorator dependencies=[Depends(...)]
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Call):
                                f_nm = getattr(elt.func, "id", None) or (
                                    getattr(elt.func, "attr", None) if isinstance(elt.func, ast.Attribute) else ""
                                )
                                if f_nm == "Depends" and hasattr(ast, "unparse"):
                                    d_arg: ast.expr | None = elt.args[0] if elt.args else None
                                    if d_arg is None:
                                        d_kw = next((k for k in elt.keywords if k.arg == "dependency"), None)
                                        if d_kw is not None:
                                            d_arg = d_kw.value
                                    if d_arg is not None:
                                        if isinstance(d_arg, (ast.Name, ast.Attribute)):
                                            dep_str = ast.unparse(d_arg)
                                            dyn_sub = None
                                        else:
                                            dep_str = "<DYNAMIC>"
                                            dyn_sub = "dynamic_provider"
                                        self.bindings.append(
                                            BindingRef(
                                                target_name=canon_id,
                                                file_path=self.file_path,
                                                line=node.lineno,
                                                column=getattr(node, "col_offset", None),
                                                scope=self.current_scope_qname,
                                                expr_kind="DI_INJECTS",
                                                source_expr=dep_str,
                                                is_conditional=is_cond,
                                                base_expr="fastapi",
                                                attr_name="Depends",
                                                subscript_target=dyn_sub,
                                                subscript_key=json.dumps({"param": "dependencies", "framework": "fastapi"}),
                                            )
                                        )

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

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self.conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        self.conditional_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self.conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        self.conditional_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        self.conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        self.conditional_depth -= 1

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        self.conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        self.conditional_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:
        self.conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        for h in node.handlers:
            self.visit(h)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)
        self.conditional_depth -= 1

    def _extract_binding_from_assign(
        self,
        target_name: str,
        value_node: ast.AST,
        line: int,
        col: int | None,
        scope_override: str | None = None,
    ) -> None:
        if not target_name or target_name.startswith("__"):
            return

        is_cond = self.conditional_depth > 0
        scope = scope_override if scope_override is not None else self.current_scope_qname

        # 1. Identifier alias: b = a
        if isinstance(value_node, ast.Name):
            self.bindings.append(
                BindingRef(
                    target_name=target_name,
                    file_path=self.file_path,
                    line=line,
                    column=col,
                    scope=scope,
                    expr_kind="IDENTIFIER",
                    source_expr=value_node.id,
                    is_conditional=is_cond,
                    base_expr=value_node.id,
                )
            )
            return

        # 2. Attribute access: handler = controller.get_users
        if isinstance(value_node, ast.Attribute) and hasattr(ast, "unparse"):
            attr_name = value_node.attr
            base_expr = ast.unparse(value_node.value)
            self.bindings.append(
                BindingRef(
                    target_name=target_name,
                    file_path=self.file_path,
                    line=line,
                    column=col,
                    scope=scope,
                    expr_kind="ATTRIBUTE",
                    source_expr=ast.unparse(value_node),
                    is_conditional=is_cond,
                    base_expr=base_expr,
                    attr_name=attr_name,
                )
            )
            return

        # 3. Dict literal: handlers = {"create": handle_create} or providers = {UserRepository: PostgresRepository}
        if isinstance(value_node, ast.Dict) and hasattr(ast, "unparse"):
            target_lower = target_name.lower()
            is_provider_dict = (
                target_lower in ("providers", "bindings", "container", "services", "dependencies")
                or target_lower.endswith(("_providers", "_bindings"))
            )
            dict_entries: list[tuple[str, str]] = []
            valid = True
            for k, v in zip(value_node.keys, value_node.values, strict=False):
                k_str: str | None = None
                v_str: str | None = None
                if k is not None:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        k_str = k.value
                    elif isinstance(k, (ast.Name, ast.Attribute)):
                        k_str = ast.unparse(k)
                if isinstance(v, ast.Name):
                    v_str = v.id
                elif isinstance(v, ast.Attribute):
                    v_str = ast.unparse(v)

                if k_str and v_str:
                    dict_entries.append((k_str, v_str))
                    if is_provider_dict:
                        self.bindings.append(
                            BindingRef(
                                target_name=k_str,
                                file_path=self.file_path,
                                line=line,
                                column=col,
                                scope=scope,
                                expr_kind="DI_PROVIDES",
                                source_expr=v_str,
                                is_conditional=is_cond,
                                base_expr=target_name,
                            )
                        )
                else:
                    valid = False
            if valid and dict_entries:
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="DICT_LITERAL",
                        source_expr=ast.unparse(value_node),
                        is_conditional=is_cond,
                        dict_entries=tuple(dict_entries),
                    )
                )
                return

        # 4. List / Tuple literal: handlers = [get_users, post_users]
        if isinstance(value_node, (ast.List, ast.Tuple)) and hasattr(ast, "unparse"):
            list_entries: list[str] = []
            valid = True
            for elt in value_node.elts:
                if isinstance(elt, ast.Name):
                    list_entries.append(elt.id)
                elif isinstance(elt, ast.Attribute):
                    list_entries.append(ast.unparse(elt))
                else:
                    valid = False
                    break
            if valid and list_entries:
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="LIST_LITERAL",
                        source_expr=ast.unparse(value_node),
                        is_conditional=is_cond,
                        list_entries=tuple(list_entries),
                    )
                )
                return

        # 5. Subscript access: h = handlers["create"] or h = handlers[0]
        if isinstance(value_node, ast.Subscript) and hasattr(ast, "unparse"):
            sub_target = ast.unparse(value_node.value)
            sub_key: str | None = None
            sub_idx: int | None = None
            if isinstance(value_node.slice, ast.Constant):
                if isinstance(value_node.slice.value, str):
                    sub_key = value_node.slice.value
                elif isinstance(value_node.slice.value, int):
                    sub_idx = value_node.slice.value

            if sub_key is not None or sub_idx is not None:
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="SUBSCRIPT",
                        source_expr=ast.unparse(value_node),
                        is_conditional=is_cond,
                        subscript_target=sub_target,
                        subscript_key=sub_key,
                        subscript_index=sub_idx,
                    )
                )
                return

        # 6. Dynamic calls: getattr(mod, name), globals()[x], locals()[x]
        if isinstance(value_node, ast.Call) and hasattr(ast, "unparse"):
            func_name = ""
            if isinstance(value_node.func, ast.Name):
                func_name = value_node.func.id
            if func_name in ("getattr", "globals", "locals", "__import__"):
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="DYNAMIC",
                        source_expr=ast.unparse(value_node),
                        is_conditional=is_cond,
                    )
                )
                return

        # 7. Environment variable & configuration assignment: db_url = os.getenv("DATABASE_URL") or os.environ["DATABASE_URL"]
        if isinstance(value_node, ast.Call) and hasattr(ast, "unparse"):
            if isinstance(value_node.func, ast.Attribute):
                b_name = ast.unparse(value_node.func.value)
                attr_nm = value_node.func.attr
                if (b_name == "os" and attr_nm == "getenv") or (b_name == "os.environ" and attr_nm in ("get", "getenv")):
                    var_name = "<DYNAMIC>"
                    is_dyn = True
                    if value_node.args and isinstance(value_node.args[0], ast.Constant) and isinstance(value_node.args[0].value, str):
                        var_name = value_node.args[0].value
                        is_dyn = False
                    self.bindings.append(
                        BindingRef(
                            target_name=var_name,
                            file_path=self.file_path,
                            line=line,
                            column=col,
                            scope=self.current_scope_canonical_id or self.current_scope_qname,
                            expr_kind="ENV_CONFIG",
                            source_expr=target_name,
                            is_conditional=is_cond,
                            base_expr=b_name,
                            attr_name=attr_nm,
                            subscript_target="runtime_configuration" if is_dyn else None,
                            subscript_key=json.dumps({"env_var": var_name, "target_var": target_name}),
                        )
                    )
                    return
        elif isinstance(value_node, ast.Subscript) and hasattr(ast, "unparse"):
            sub_target = ast.unparse(value_node.value)
            if sub_target == "os.environ":
                var_name = "<DYNAMIC>"
                is_dyn = True
                if isinstance(value_node.slice, ast.Constant) and isinstance(value_node.slice.value, str):
                    var_name = value_node.slice.value
                    is_dyn = False
                self.bindings.append(
                    BindingRef(
                        target_name=var_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=self.current_scope_canonical_id or self.current_scope_qname,
                        expr_kind="ENV_CONFIG",
                        source_expr=target_name,
                        is_conditional=is_cond,
                        base_expr=sub_target,
                        subscript_target="runtime_configuration" if is_dyn else None,
                        subscript_key=json.dumps({"env_var": var_name, "target_var": target_name}),
                    )
                )
                return
            elif sub_target.lower() in ("config", "settings", "configuration"):
                self.bindings.append(
                    BindingRef(
                        target_name="<DYNAMIC>",
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=self.current_scope_canonical_id or self.current_scope_qname,
                        expr_kind="ENV_CONFIG",
                        source_expr=target_name,
                        is_conditional=is_cond,
                        base_expr=sub_target,
                        subscript_target="runtime_configuration",
                    )
                )
                return

        # 8. Router / App instantiation with dependencies=[Depends(...)]
        if isinstance(value_node, ast.Call) and hasattr(ast, "unparse"):
            for kw in value_node.keywords:
                if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Call):
                            f_nm = getattr(elt.func, "id", None) or (
                                getattr(elt.func, "attr", None) if isinstance(elt.func, ast.Attribute) else ""
                            )
                            if f_nm == "Depends":
                                d_arg: ast.expr | None = elt.args[0] if elt.args else None
                                if d_arg is None:
                                    d_kw = next((k for k in elt.keywords if k.arg == "dependency"), None)
                                    if d_kw is not None:
                                        d_arg = d_kw.value
                                if d_arg is not None:
                                    if isinstance(d_arg, (ast.Name, ast.Attribute)):
                                        dep_str = ast.unparse(d_arg)
                                        dyn_sub = None
                                    else:
                                        dep_str = "<DYNAMIC>"
                                        dyn_sub = "dynamic_provider"
                                    self.bindings.append(
                                        BindingRef(
                                            target_name=target_name,
                                            file_path=self.file_path,
                                            line=line,
                                            column=col,
                                            scope=scope,
                                            expr_kind="ROUTER_DI_INJECTS",
                                            source_expr=dep_str,
                                            is_conditional=is_cond,
                                            base_expr="fastapi",
                                            attr_name="Depends",
                                            subscript_target=dyn_sub,
                                        )
                                    )

        # 9. Factory / Constructor / Function call assignment: service = get_inventory_service() or service = InventoryService()
        if isinstance(value_node, ast.Call) and hasattr(ast, "unparse"):
            if isinstance(value_node.func, ast.Name):
                callee_fn = value_node.func.id
                if callee_fn not in _PYTHON_BUILTINS:
                    self.bindings.append(
                        BindingRef(
                            target_name=target_name,
                            file_path=self.file_path,
                            line=line,
                            column=col,
                            scope=scope,
                            expr_kind="CALL_RETURN",
                            source_expr=callee_fn,
                            is_conditional=is_cond,
                            base_expr=callee_fn,
                        )
                    )
            elif isinstance(value_node.func, ast.Attribute):
                callee_fn = ast.unparse(value_node.func).strip()
                base_str = ast.unparse(value_node.func.value).strip()
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="CALL_RETURN",
                        source_expr=callee_fn,
                        is_conditional=is_cond,
                        base_expr=base_str,
                        attr_name=value_node.func.attr,
                    )
                )
            elif isinstance(value_node.func, ast.Subscript):
                self.bindings.append(
                    BindingRef(
                        target_name=target_name,
                        file_path=self.file_path,
                        line=line,
                        column=col,
                        scope=scope,
                        expr_kind="DYNAMIC",
                        source_expr=ast.unparse(value_node),
                        is_conditional=is_cond,
                    )
                )

        # 10. Modern FastAPI / typing Annotated DI alias
        # e.g., SessionDep = Annotated[Session, Depends(get_db)]
        #       CurrentUser = Annotated[User, Depends(get_current_user)]
        #       TokenDep = Annotated[str, Depends(reusable_oauth2)]
        if isinstance(value_node, ast.Subscript) and hasattr(ast, "unparse"):
            val_id = getattr(value_node.value, "id", None) or (
                getattr(value_node.value, "attr", None) if isinstance(value_node.value, ast.Attribute) else ""
            )
            val_unparse = ast.unparse(value_node.value) if hasattr(ast, "unparse") else ""
            if val_id in ("Annotated", "typing.Annotated", "typing_extensions.Annotated") or "Annotated" in val_unparse:
                slice_node = value_node.slice
                elts = slice_node.elts if isinstance(slice_node, (ast.Tuple, ast.List)) else [slice_node]
                for elt in elts[1:]:
                    if isinstance(elt, ast.Call):
                        f_nm = getattr(elt.func, "id", None) or (
                            getattr(elt.func, "attr", None) if isinstance(elt.func, ast.Attribute) else ""
                        )
                        if f_nm == "Depends":
                            elt_arg: ast.expr | None = elt.args[0] if elt.args else None
                            if elt_arg is None:
                                elt_kw = next((kw for kw in elt.keywords if kw.arg == "dependency"), None)
                                if elt_kw is not None:
                                    elt_arg = elt_kw.value
                            dep_alias_str: str | None = None
                            if elt_arg is not None:
                                if isinstance(elt_arg, (ast.Name, ast.Attribute)):
                                    dep_alias_str = ast.unparse(elt_arg)
                                else:
                                    dep_alias_str = "<DYNAMIC>"
                            elif hasattr(ast, "unparse"):
                                dep_alias_str = ast.unparse(elts[0]).split("[")[0].strip()
                            if dep_alias_str:
                                self.di_type_aliases[target_name] = dep_alias_str
                                self.bindings.append(
                                    BindingRef(
                                        target_name=target_name,
                                        file_path=self.file_path,
                                        line=line,
                                        column=col,
                                        scope=scope,
                                        expr_kind="DI_ALIAS_INJECTS",
                                        source_expr=dep_alias_str,
                                        is_conditional=is_cond,
                                        base_expr="fastapi",
                                        attr_name="Depends",
                                        subscript_key=json.dumps({"alias": target_name, "framework": "fastapi"}),
                                    )
                                )
                            break

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._extract_binding_from_assign(
                    target.id, node.value, node.lineno, getattr(node, "col_offset", None)
                )
                if target.id in ("template_name", "template") and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    self.bindings.append(
                        BindingRef(
                            target_name=node.value.value,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname or "",
                            expr_kind="RENDERS_TEMPLATE",
                            base_expr=self.current_scope_canonical_id or "",
                            source_expr=node.value.value,
                        )
                    )
                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                    # Unfold bitwise OR chain (e.g. prompt | llm | output_parser)
                    pipe_steps: list[str] = []
                    curr: ast.expr = node.value
                    is_valid_pipe = True
                    while isinstance(curr, ast.BinOp) and isinstance(curr.op, ast.BitOr):
                        r_text = ast.unparse(curr.right).strip() if hasattr(ast, "unparse") else ""
                        if not r_text or isinstance(curr.right, ast.Constant):
                            is_valid_pipe = False
                            break
                        pipe_steps.append(r_text)
                        curr = curr.left
                    l_text = ast.unparse(curr).strip() if hasattr(ast, "unparse") else ""
                    if is_valid_pipe and l_text and not isinstance(curr, ast.Constant):
                        pipe_steps.append(l_text)
                        pipe_steps.reverse()
                        if len(pipe_steps) >= 2:
                            self.bindings.append(
                                BindingRef(
                                    target_name=target.id,
                                    file_path=self.file_path,
                                    line=node.lineno,
                                    column=getattr(node, "col_offset", None),
                                    scope=self.current_scope_qname or "",
                                    expr_kind="LCEL_PIPELINE",
                                    base_expr="|".join(pipe_steps),
                                    source_expr=json.dumps(pipe_steps),
                                )
                            )
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and self.current_enclosing_class
            ):
                self._extract_binding_from_assign(
                    f"self.{target.attr}",
                    node.value,
                    node.lineno,
                    getattr(node, "col_offset", None),
                    scope_override=self.current_enclosing_class,
                )
                if isinstance(node.value, ast.Name):
                    bound_param = self._lookup_local_binding(node.value.id)
                    if bound_param:
                        self._bind_in_class_scope(f"self.{target.attr}", bound_param)
                        self.bindings.append(
                            BindingRef(
                                target_name=f"self.{target.attr}",
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(node, "col_offset", None),
                                scope=self.current_enclosing_class,
                                expr_kind="TYPE_ANNOTATION",
                                source_expr=bound_param,
                                is_conditional=(self.conditional_depth > 0),
                                base_expr=node.value.id,
                            )
                        )
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
                            self._bind_in_local_scope(target.id, self.fn_return_types[callee_name])
                        elif callee_name in self.known_classes or (callee_name[0].isupper() and "_" not in callee_name):
                            self._bind_in_local_scope(target.id, callee_name)
                        elif any(callee_name.endswith(sfx) for sfx in ("Service", "Client", "Repository", "Manager", "Store", "View")):
                            self._bind_in_local_scope(target.id, callee_name)
                elif isinstance(node.value.func, ast.Attribute) and hasattr(ast, "unparse"):
                    attr_expr = ast.unparse(node.value.func)
                    if attr_expr in self.fn_return_types:
                        self._bind_in_local_scope(target.id, self.fn_return_types[attr_expr])
                    elif attr_expr.split(".")[-1][0].isupper():
                        self._bind_in_local_scope(target.id, attr_expr.split(".")[-1])
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(node.value, ast.Call)
            ):
                if isinstance(node.value.func, ast.Name):
                    callee_name = node.value.func.id
                    if callee_name in self.fn_return_types:
                        self._bind_in_class_scope(f"self.{target.attr}", self.fn_return_types[callee_name])
                    elif callee_name in self.known_classes or (callee_name[0].isupper() and "_" not in callee_name):
                        self._bind_in_class_scope(f"self.{target.attr}", callee_name)
                elif isinstance(node.value.func, ast.Attribute) and hasattr(ast, "unparse"):
                    attr_expr = ast.unparse(node.value.func)
                    if attr_expr in self.fn_return_types:
                        self._bind_in_class_scope(f"self.{target.attr}", self.fn_return_types[attr_expr])
                    elif attr_expr.split(".")[-1][0].isupper():
                        self._bind_in_class_scope(f"self.{target.attr}", attr_expr.split(".")[-1])
            elif isinstance(target, ast.Subscript) and hasattr(ast, "unparse"):
                sub_target = ast.unparse(target.value)
                lowered_target = sub_target.lower()
                is_provider_map = (
                    lowered_target in ("providers", "bindings", "container", "services", "dependencies")
                    or lowered_target.endswith(("_providers", "_bindings"))
                )
                if is_provider_map:
                    iface_str = ast.unparse(target.slice) if isinstance(target.slice, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                    impl_str = ast.unparse(node.value) if isinstance(node.value, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                    self.bindings.append(
                        BindingRef(
                            target_name=iface_str,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="DI_PROVIDES",
                            source_expr=impl_str,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=sub_target,
                            subscript_target="dynamic_provider" if (iface_str == "<DYNAMIC>" or impl_str == "<DYNAMIC>") else None,
                        )
                    )

                sub_key: str | None = None
                is_dyn_key = False
                if isinstance(target.slice, ast.Constant):
                    if isinstance(target.slice.value, str):
                        sub_key = target.slice.value
                    elif isinstance(target.slice.value, int):
                        sub_key = str(target.slice.value)
                elif isinstance(target.slice, (ast.Name, ast.Attribute)):
                    sub_key = ast.unparse(target.slice)
                else:
                    is_dyn_key = True
                    sub_key = "<DYNAMIC>"

                val_expr = ast.unparse(node.value)
                is_dyn_val = not (isinstance(node.value, (ast.Name, ast.Attribute)))

                lowered_target = sub_target.lower()
                is_event = (
                    "event" in lowered_target
                    or "listener" in lowered_target
                    or "emitter" in lowered_target
                    or (sub_key and "." in sub_key and not is_dyn_key)
                )
                expr_kind = "EVENT_ON" if is_event else "DICT_ASSIGN"

                self.bindings.append(
                    BindingRef(
                        target_name=sub_target,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind=expr_kind,
                        source_expr="<DYNAMIC>" if is_dyn_val else val_expr,
                        is_conditional=(self.conditional_depth > 0),
                        base_expr=sub_target,
                        subscript_target=sub_target,
                        subscript_key=sub_key,
                    )
                )

        ctx = self._make_context()
        for analyzer in self.analyzers:
            r_defs = analyzer.analyze_python_definitions(node, ctx)
            if r_defs:
                self.router_definitions.extend(r_defs)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value:
            self._extract_binding_from_assign(
                node.target.id, node.value, node.lineno, getattr(node, "col_offset", None)
            )
        elif (
            isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
            and self.current_enclosing_class
        ):
            if node.value:
                self._extract_binding_from_assign(
                    f"self.{node.target.attr}",
                    node.value,
                    node.lineno,
                    getattr(node, "col_offset", None),
                    scope_override=self.current_enclosing_class,
                )
            if hasattr(ast, "unparse"):
                ann = ast.unparse(node.annotation).split("[")[0].strip().strip("'\"")
                if ann and ann not in _PYTHON_BUILTINS:
                    self._bind_in_class_scope(f"self.{node.target.attr}", ann)
                    self.bindings.append(
                        BindingRef(
                            target_name=f"self.{node.target.attr}",
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_enclosing_class,
                            expr_kind="TYPE_ANNOTATION",
                            source_expr=ann,
                            is_conditional=(self.conditional_depth > 0),
                        )
                    )
        if isinstance(node.target, ast.Name) and hasattr(ast, "unparse"):
            ann = ast.unparse(node.annotation).split("[")[0].strip().strip("'\"")
            if ann and ann not in _PYTHON_BUILTINS:
                self._bind_in_local_scope(node.target.id, ann)
                self.bindings.append(
                    BindingRef(
                        target_name=node.target.id,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="TYPE_ANNOTATION",
                        source_expr=ann,
                        is_conditional=(self.conditional_depth > 0),
                    )
                )
        ctx = self._make_context()
        for analyzer in self.analyzers:
            r_defs = analyzer.analyze_python_definitions(node, ctx)
            if r_defs:
                self.router_definitions.extend(r_defs)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Framework analyzer hook: check calls (e.g. Django path("login/", handler) or app.include_router(...))
        ctx = self._make_context()
        for analyzer in self.analyzers:
            detected = analyzer.analyze_python_node(node, ctx)
            if detected:
                self.routes.extend(detected)
            mounts = analyzer.analyze_python_mounts(node, ctx)
            if mounts:
                self.mounts.extend(mounts)

        caller_qname = self.current_scope_qname or None
        caller_canon = self.current_scope_canonical_id
        end_ln = node.end_lineno or node.lineno

        # Python View -> Template rendering (Flask render_template, Django render, FastAPI TemplateResponse)
        template_name: str | None = None
        if isinstance(node.func, ast.Name):
            if node.func.id == "render_template" and node.args:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    template_name = node.args[0].value
            elif node.func.id == "render" and len(node.args) >= 2:
                if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    template_name = node.args[1].value
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr == "TemplateResponse" and node.args:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    template_name = node.args[0].value
                elif len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    template_name = node.args[1].value
                for kw in node.keywords:
                    if kw.arg in ("name", "template_name") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        template_name = kw.value.value

        if template_name:
            self.bindings.append(
                BindingRef(
                    target_name=template_name,
                    file_path=self.file_path,
                    line=node.lineno,
                    column=getattr(node, "col_offset", None),
                    scope=caller_qname or "",
                    expr_kind="RENDERS_TEMPLATE",
                    base_expr=caller_canon or "",
                    source_expr=template_name,
                )
            )

        if isinstance(node.func, ast.Name):
            callee_name = node.func.id
            if callee_name == "subscribe" and len(node.args) >= 2 and hasattr(ast, "unparse"):
                event_node = node.args[0]
                target_node = node.args[1]
                event_str = (
                    event_node.value
                    if isinstance(event_node, ast.Constant) and isinstance(event_node.value, str)
                    else "<DYNAMIC>"
                )
                target_expr = (
                    ast.unparse(target_node)
                    if isinstance(target_node, (ast.Name, ast.Attribute))
                    else "<DYNAMIC>"
                )
                self.bindings.append(
                    BindingRef(
                        target_name="subscribe",
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="SUBSCRIBE",
                        source_expr=target_expr,
                        is_conditional=(self.conditional_depth > 0),
                        base_expr="subscribe",
                        subscript_target="subscribe",
                        subscript_key=event_str,
                    )
                )
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
            if isinstance(node.func.value, ast.Call) and hasattr(ast, "unparse"):
                recv_clean = ast.unparse(node.func.value.func).strip()
            else:
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

            # app.include_router(router, dependencies=[Depends(...)])
            if attr_name == "include_router" and node.args and hasattr(ast, "unparse"):
                router_arg = node.args[0]
                if isinstance(router_arg, (ast.Name, ast.Attribute)):
                    r_name = ast.unparse(router_arg)
                    for kw in node.keywords:
                        if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Call):
                                    f_nm = getattr(elt.func, "id", None) or (
                                        getattr(elt.func, "attr", None) if isinstance(elt.func, ast.Attribute) else ""
                                    )
                                    if f_nm == "Depends":
                                        d_arg: ast.expr | None = elt.args[0] if elt.args else None
                                        if d_arg is None:
                                            d_kw = next((k for k in elt.keywords if k.arg == "dependency"), None)
                                            if d_kw is not None:
                                                d_arg = d_kw.value
                                        if d_arg is not None:
                                            if isinstance(d_arg, (ast.Name, ast.Attribute)):
                                                dep_str = ast.unparse(d_arg)
                                                dyn_sub = None
                                            else:
                                                dep_str = "<DYNAMIC>"
                                                dyn_sub = "dynamic_provider"
                                            self.bindings.append(
                                                BindingRef(
                                                    target_name=r_name,
                                                    file_path=self.file_path,
                                                    line=node.lineno,
                                                    column=getattr(node, "col_offset", None),
                                                    scope=self.current_scope_qname,
                                                    expr_kind="ROUTER_DI_INJECTS",
                                                    source_expr=dep_str,
                                                    is_conditional=(self.conditional_depth > 0),
                                                    base_expr=recv_clean,
                                                    attr_name="Depends",
                                                    subscript_target=dyn_sub,
                                                )
                                            )

            # Known semantic registry pattern (.register())
            if attr_name == "register" and hasattr(ast, "unparse"):
                recv_lower = recv_clean.lower()
                is_known_registry = (
                    recv_lower == "registry"
                    or recv_lower.endswith("_registry")
                    or recv_lower.endswith("registry")
                    or recv_lower in (
                        "command_registry",
                        "handler_registry",
                        "plugin_registry",
                        "task_registry",
                        "route_registry",
                    )
                )
                if is_known_registry and len(node.args) >= 2:
                    key_node = node.args[0]
                    target_node = node.args[1]
                    sub_key = (
                        key_node.value
                        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)
                        else "<DYNAMIC>"
                    )
                    target_expr = (
                        ast.unparse(target_node)
                        if isinstance(target_node, (ast.Name, ast.Attribute))
                        else "<DYNAMIC>"
                    )
                    self.bindings.append(
                        BindingRef(
                            target_name=recv_clean,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="CALL_REGISTER",
                            source_expr=target_expr,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=recv_clean,
                            subscript_target=recv_clean,
                            subscript_key=sub_key,
                        )
                    )
            # Known event emitter pattern (.on())
            elif attr_name == "on" and hasattr(ast, "unparse"):
                recv_lower = recv_clean.lower()
                is_known_emitter = (
                    recv_lower in ("event_bus", "bus", "emitter", "event_emitter", "events", "dispatcher")
                    or recv_lower.endswith("_bus")
                    or recv_lower.endswith("_emitter")
                    or recv_lower.endswith("_dispatcher")
                    or recv_lower.endswith("eventemitter")
                )
                if is_known_emitter and len(node.args) >= 2:
                    event_node = node.args[0]
                    target_node = node.args[1]
                    event_str = (
                        event_node.value
                        if isinstance(event_node, ast.Constant) and isinstance(event_node.value, str)
                        else "<DYNAMIC>"
                    )
                    target_expr = (
                        ast.unparse(target_node)
                        if isinstance(target_node, (ast.Name, ast.Attribute))
                        else "<DYNAMIC>"
                    )
                    self.bindings.append(
                        BindingRef(
                            target_name=recv_clean,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="EVENT_ON",
                            source_expr=target_expr,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=recv_clean,
                            subscript_target=recv_clean,
                            subscript_key=event_str,
                        )
                    )
            # Known subscribe pattern (.subscribe())
            elif attr_name == "subscribe" and hasattr(ast, "unparse"):
                recv_lower = recv_clean.lower()
                is_known_sub = (
                    recv_lower in ("event_bus", "bus", "emitter", "event_emitter", "events", "dispatcher", "pubsub")
                    or recv_lower.endswith("_bus")
                    or recv_lower.endswith("_emitter")
                )
                if is_known_sub and len(node.args) >= 2:
                    event_node = node.args[0]
                    target_node = node.args[1]
                    event_str = (
                        event_node.value
                        if isinstance(event_node, ast.Constant) and isinstance(event_node.value, str)
                        else "<DYNAMIC>"
                    )
                    target_expr = (
                        ast.unparse(target_node)
                        if isinstance(target_node, (ast.Name, ast.Attribute))
                        else "<DYNAMIC>"
                    )
                    self.bindings.append(
                        BindingRef(
                            target_name=recv_clean,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="SUBSCRIBE",
                            source_expr=target_expr,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=recv_clean,
                            subscript_target=recv_clean,
                            subscript_key=event_str,
                        )
                    )

            # Known DI container registration (.register(...), .bind(...), .provide(...), .singleton(...), .factory(...))
            recv_lower = recv_clean.lower()
            is_container = (
                recv_lower in ("container", "injector", "di", "ioc", "services", "providers", "provider_registry", "service_registry", "di_registry")
                or recv_lower.endswith(("_container", "_injector", "container", "injector"))
            )
            if is_container and attr_name in ("register", "bind", "provide", "singleton", "factory") and hasattr(ast, "unparse"):
                if len(node.args) >= 2:
                    iface_node = node.args[0]
                    impl_node = node.args[1]
                    iface_str = ast.unparse(iface_node) if isinstance(iface_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                    impl_str = ast.unparse(impl_node) if isinstance(impl_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                    self.bindings.append(
                        BindingRef(
                            target_name=iface_str,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="DI_PROVIDES",
                            source_expr=impl_str,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=recv_clean,
                            attr_name=attr_name,
                            subscript_target="dynamic_provider" if (iface_str == "<DYNAMIC>" or impl_str == "<DYNAMIC>") else None,
                        )
                    )
                elif len(node.args) == 1:
                    to_kw = next((kw for kw in node.keywords if kw.arg in ("to", "implementation", "provider", "cls", "factory")), None)
                    if to_kw:
                        iface_node = node.args[0]
                        impl_node = to_kw.value
                        iface_str = ast.unparse(iface_node) if isinstance(iface_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                        impl_str = ast.unparse(impl_node) if isinstance(impl_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                        self.bindings.append(
                            BindingRef(
                                target_name=iface_str,
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(node, "col_offset", None),
                                scope=self.current_scope_qname,
                                expr_kind="DI_PROVIDES",
                                source_expr=impl_str,
                                is_conditional=(self.conditional_depth > 0),
                                base_expr=recv_clean,
                                attr_name=attr_name,
                                subscript_target="dynamic_provider" if (iface_str == "<DYNAMIC>" or impl_str == "<DYNAMIC>") else None,
                            )
                        )
                    elif attr_name in ("provide", "singleton", "factory"):
                        impl_node = node.args[0]
                        impl_str = ast.unparse(impl_node) if isinstance(impl_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                        self.bindings.append(
                            BindingRef(
                                target_name=impl_str,
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(node, "col_offset", None),
                                scope=self.current_scope_qname,
                                expr_kind="DI_PROVIDES",
                                source_expr=impl_str,
                                is_conditional=(self.conditional_depth > 0),
                                base_expr=recv_clean,
                                attr_name=attr_name,
                                subscript_target="dynamic_provider" if impl_str == "<DYNAMIC>" else None,
                            )
                        )

            # Fluent binding: container.bind(UserRepository).to(PostgresRepository) / .to_class(...) / .to_provider(...)
            if attr_name in ("to", "to_class", "to_provider", "to_singleton", "to_factory") and isinstance(node.func.value, ast.Call) and hasattr(ast, "unparse"):
                inner_c = node.func.value
                if isinstance(inner_c.func, ast.Attribute) and inner_c.func.attr == "bind" and inner_c.args and node.args:
                    inner_recv = ast.unparse(inner_c.func.value).lower()
                    if "container" in inner_recv or "injector" in inner_recv or "binder" in inner_recv:
                        iface_str = ast.unparse(inner_c.args[0]) if isinstance(inner_c.args[0], (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                        impl_str = ast.unparse(node.args[0]) if isinstance(node.args[0], (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                        self.bindings.append(
                            BindingRef(
                                target_name=iface_str,
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(node, "col_offset", None),
                                scope=self.current_scope_qname,
                                expr_kind="DI_PROVIDES",
                                source_expr=impl_str,
                                is_conditional=(self.conditional_depth > 0),
                                base_expr=ast.unparse(inner_c.func.value),
                                attr_name=f"bind.{attr_name}",
                                subscript_target="dynamic_provider" if (iface_str == "<DYNAMIC>" or impl_str == "<DYNAMIC>") else None,
                            )
                        )

            # Known DI container resolution (.resolve(...) or .get(...))
            if is_container and attr_name in ("resolve", "get") and node.args and hasattr(ast, "unparse"):
                iface_node = node.args[0]
                iface_str = ast.unparse(iface_node) if isinstance(iface_node, (ast.Name, ast.Attribute)) else "<DYNAMIC>"
                self.bindings.append(
                    BindingRef(
                        target_name=iface_str,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="DI_RESOLVES",
                        source_expr=iface_str,
                        is_conditional=(self.conditional_depth > 0),
                        base_expr=recv_clean,
                        attr_name=attr_name,
                        subscript_target="dynamic_provider" if iface_str == "<DYNAMIC>" else None,
                    )
                )

            # Environment variable reference (os.getenv(...) or os.environ.get(...))
            if (recv_clean == "os" and attr_name == "getenv") or (recv_clean == "os.environ" and attr_name in ("get", "getenv")):
                var_name = "<DYNAMIC>"
                is_dyn = True
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    var_name = node.args[0].value
                    is_dyn = False
                self.bindings.append(
                    BindingRef(
                        target_name=var_name,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_canonical_id or self.current_scope_qname,
                        expr_kind="ENV_CONFIG",
                        source_expr=var_name,
                        is_conditional=(self.conditional_depth > 0),
                        base_expr=recv_clean,
                        attr_name=attr_name,
                        subscript_target="runtime_configuration" if is_dyn else None,
                        subscript_key=json.dumps({"env_var": var_name}),
                    )
                )

            # Known test client calls (client.get('/path'), test_client.post(...), self.client.get(...))
            is_client = (
                recv_clean.lower() in ("client", "test_client", "testclient", "api_client", "self.client", "self.test_client", "app.test_client()")
                or recv_clean.lower().endswith(("_client", ".client", "client"))
            )
            if is_client and attr_name.lower() in ("get", "post", "put", "delete", "patch", "head", "options", "request"):
                route_str = "<DYNAMIC>"
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    route_str = node.args[0].value
                self.bindings.append(
                    BindingRef(
                        target_name=route_str,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="TEST_ROUTE",
                        source_expr=attr_name.upper(),
                        is_conditional=(self.conditional_depth > 0),
                        base_expr=recv_clean,
                        attr_name=attr_name.upper(),
                        subscript_target=recv_clean,
                        subscript_key=route_str,
                    )
                )

            # Known browser test calls (page.goto('/route'))
            is_page = (
                recv_clean.lower() in ("page", "self.page", "browser_page")
                or recv_clean.lower().endswith(("_page", ".page", "page"))
            )
            if is_page and attr_name == "goto":
                url_str = "<DYNAMIC>"
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    url_str = node.args[0].value
                self.bindings.append(
                    BindingRef(
                        target_name=url_str,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname,
                        expr_kind="TEST_PAGE_GOTO",
                        source_expr="GOTO",
                        is_conditional=(self.conditional_depth > 0),
                        base_expr=recv_clean,
                        attr_name="goto",
                        subscript_target=recv_clean,
                        subscript_key=url_str,
                    )
                )

            # Known event emission calls (bus.emit('event', ...), dispatcher.dispatch(...))
            if attr_name in ("emit", "dispatch", "publish", "trigger", "send"):
                recv_lower = recv_clean.lower()
                is_emitter = (
                    recv_lower in ("event_bus", "bus", "emitter", "event_emitter", "events", "dispatcher")
                    or recv_lower.endswith(("_bus", "_emitter", "_dispatcher"))
                )
                if is_emitter and node.args:
                    ev_str = "<DYNAMIC>"
                    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        ev_str = node.args[0].value
                    self.bindings.append(
                        BindingRef(
                            target_name=recv_clean,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=self.current_scope_qname,
                            expr_kind="EVENT_DISPATCH",
                            source_expr=ev_str,
                            is_conditional=(self.conditional_depth > 0),
                            base_expr=recv_clean,
                            attr_name=attr_name,
                            subscript_target=recv_clean,
                            subscript_key=ev_str,
                        )
                    )
            # Celery / Background task / Ray remote task invocation (.delay(), .apply_async(), .s(), .si(), .signature(), .remote())
            if attr_name in ("delay", "apply_async", "s", "si", "signature", "remote"):
                task_callee = recv_clean.split(".")[-1]
                if task_callee and task_callee not in ("self", "cls"):
                    self.calls.append(
                        CallRef(
                            callee=task_callee,
                            qualified_callee=recv_clean,
                            line=node.lineno,
                            end_line=end_ln,
                            source_file=self.file_path,
                            confidence="HIGH",
                            caller_symbol=caller_qname,
                            caller_canonical_id=caller_canon,
                            receiver=recv_clean if "." in recv_clean else None,
                        )
                    )
                    dispatch_kind = "RAY_REMOTE" if attr_name == "remote" else "CELERY_DISPATCH"
                    self.bindings.append(
                        BindingRef(
                            target_name=task_callee,
                            file_path=self.file_path,
                            line=node.lineno,
                            column=getattr(node, "col_offset", None),
                            scope=caller_qname or "",
                            expr_kind=dispatch_kind,
                            base_expr=attr_name,
                            source_expr=recv_clean,
                        )
                    )
            elif attr_name == "send_task" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                full_task = node.args[0].value
                task_short = full_task.split(".")[-1]
                self.calls.append(
                    CallRef(
                        callee=task_short,
                        qualified_callee=full_task,
                        line=node.lineno,
                        end_line=end_ln,
                        source_file=self.file_path,
                        confidence="HIGH",
                        caller_symbol=caller_qname,
                        caller_canonical_id=caller_canon,
                        receiver=full_task if "." in full_task else None,
                    )
                )
                self.bindings.append(
                    BindingRef(
                        target_name=task_short,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=caller_qname or "",
                        expr_kind="CELERY_DISPATCH",
                        base_expr="send_task",
                        source_expr=full_task,
                    )
                )
            elif attr_name == "connect" and node.args and hasattr(ast, "unparse"):
                receiver_node = node.args[0]
                receiver_name = ast.unparse(receiver_node).strip()
                sender_name = ""
                for kw in node.keywords:
                    if kw.arg == "sender":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            sender_name = kw.value.value
                        elif isinstance(kw.value, (ast.Name, ast.Attribute)):
                            sender_name = ast.unparse(kw.value).strip()
                self.bindings.append(
                    BindingRef(
                        target_name=receiver_name,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname or "",
                        expr_kind="DJANGO_SIGNAL_RECEIVER",
                        base_expr=recv_clean,
                        source_expr=sender_name,
                    )
                )
            elif attr_name in ("send", "send_robust") and hasattr(ast, "unparse"):
                sender_name = ""
                for kw in node.keywords:
                    if kw.arg == "sender":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            sender_name = kw.value.value
                        elif isinstance(kw.value, (ast.Name, ast.Attribute)):
                            sender_name = ast.unparse(kw.value).strip()
                self.bindings.append(
                    BindingRef(
                        target_name=recv_clean,
                        file_path=self.file_path,
                        line=node.lineno,
                        column=getattr(node, "col_offset", None),
                        scope=self.current_scope_qname or "",
                        expr_kind="DJANGO_SIGNAL_SEND",
                        base_expr=attr_name,
                        source_expr=sender_name,
                    )
                )

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
        elif isinstance(node.func, ast.Subscript) and hasattr(ast, "unparse"):
            sub_expr = ast.unparse(node.func)
            sub_recv = ast.unparse(node.func.value)
            self.calls.append(
                CallRef(
                    callee=sub_expr,
                    qualified_callee=sub_expr,
                    line=node.lineno,
                    end_line=end_ln,
                    source_file=self.file_path,
                    confidence="LOW",
                    caller_symbol=caller_qname,
                    caller_canonical_id=caller_canon,
                    receiver=sub_recv,
                )
            )

        # Agent tool registration (e.g. AgentExecutor(tools=[...]), create_openai_tools_agent(..., tools=[...]))
        for kw in node.keywords:
            if kw.arg in ("tools", "functions") and isinstance(kw.value, (ast.List, ast.Tuple)):
                func_label = ast.unparse(node.func).strip() if hasattr(ast, "unparse") else ""
                for elt in kw.value.elts:
                    t_name = ast.unparse(elt).strip() if hasattr(ast, "unparse") else ""
                    if t_name:
                        self.bindings.append(
                            BindingRef(
                                target_name=t_name,
                                file_path=self.file_path,
                                line=node.lineno,
                                column=getattr(node, "col_offset", None),
                                scope=caller_qname or "",
                                expr_kind="AGENT_TOOL_REGISTRATION",
                                base_expr=func_label,
                                source_expr=t_name,
                            )
                        )

        self.generic_visit(node)


def _extract_all_python_imports(
    tree: ast.AST, file_path: str, module: str, is_init: bool
) -> list[ImportRef]:
    imports: list[ImportRef] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportRef(
                        module=alias.name,
                        imported_module=alias.name,
                        imported_name=None,
                        alias=alias.asname,
                        local_name=alias.asname or alias.name.split(".")[0],
                        import_type="namespace" if alias.asname else "module",
                        line=node.lineno,
                        source_file=file_path,
                        source_module=module,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            raw_mod = node.module or ""
            resolved_mod = (
                _resolve_relative_py_module(file_path, node.level, node.module)
                if node.level > 0
                else raw_mod
            )
            display_mod = raw_mod or resolved_mod
            for alias in node.names:
                full = f"{resolved_mod}.{alias.name}" if resolved_mod else alias.name
                is_reexp = is_init
                imports.append(
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
                        source_file=file_path,
                        source_module=module,
                        full=full,
                    )
                )
    return imports


def _repair_python_syntax(content: str) -> str:
    """Repair common syntax patterns from newer or experimental Python versions (e.g. unparenthesized multiple except)."""
    lines = content.splitlines()
    repaired = False
    new_lines = []
    for line in lines:
        # Match 'except A, B:' or 'except A, B as e:' or 'except* A, B:' without enclosing parentheses
        m = re.match(
            r'^(\s*except\*?\s+)([A-Za-z0-9_.\s]+,\s*[A-Za-z0-9_.,\s]+?)(\s+as\s+[A-Za-z0-9_]+)?(\s*:.*)$',
            line,
        )
        if m:
            prefix, types, as_part, suffix = m.group(1), m.group(2).strip(), m.group(3) or "", m.group(4)
            if not types.startswith("("):
                line = f"{prefix}({types}){as_part}{suffix}"
                repaired = True
        new_lines.append(line)
    return "\n".join(new_lines) if repaired else content


def _parse_python(content: str, file_path: str) -> ParseResult:
    source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    tree: ast.Module | None = None
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        repaired = _repair_python_syntax(content)
        if repaired != content:
            try:
                tree = ast.parse(repaired)
            except SyntaxError:
                tree = None
        if tree is None:
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
    module = normalize_module(file_path, "python")
    is_init = file_path.replace("\\", "/").endswith("__init__.py")
    all_imports = _extract_all_python_imports(tree, file_path, module, is_init)

    # Single-pass scoped traversal
    visitor = _PythonScopeVisitor(
        content,
        lines,
        file_path,
        analyzers,
        fn_return_types=fn_returns,
        known_classes=known_classes,
        all_file_imports=all_imports,
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
        mounts=tuple(visitor.mounts),
        router_definitions=tuple(visitor.router_definitions),
        bindings=tuple(visitor.bindings),
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
    r"""import\s+['"]([^'"]+)['"]"""
)
_JS_REQUIRE_ASSIGN = re.compile(
    r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
)
_JS_REQUIRE_DESTRUCTURE = re.compile(
    r"""(?:const|let|var)\s+\{([^}]+)\}\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
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
_JS_CONST_ID = re.compile(
    r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$"
)
_JS_CONST_ATTR = re.compile(
    r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*;?\s*$"
)
_JS_CONST_DICT = re.compile(
    r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\{\s*([^}]+)\s*\}\s*;?\s*$"
)
_JS_SUBSCRIPT_ASSIGN = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\[['\"]([^'\"]+)['\"]\]\s*=\s*([A-Za-z_$][\w$.]*)\s*;?\s*$"
)
_JS_REGISTRY_CALL = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\.register\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_$][\w$.]+)\s*\)\s*;?\s*$"
)
_JS_EVENT_ON = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\.on\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_$][\w$.]+)\s*\)\s*;?\s*$"
)
_JS_SUBSCRIPT_CALL = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\[['\"]([^'\"]+)['\"]\]\s*\("
)
_JS_DI_PROVIDE = re.compile(
    r"""(?:\{\s*provide:\s*([A-Za-z_$][\w$]*)\s*,\s*(?:useClass|useExisting|useValue|useFactory):\s*([A-Za-z_$][\w$.]*)\s*\})"""
)
_JS_CONTAINER_REG = re.compile(
    r"""^\s*([A-Za-z_$][\w$]*)\.register\(\s*([A-Za-z_$][\w$.]+)\s*,\s*([A-Za-z_$][\w$.]+)\s*\)\s*;?\s*$"""
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
    mounts: list[RouterMountDetection] = []
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

    for m in _JS_REQUIRE_ASSIGN.finditer(content):
        local_name = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        imports.append(
            ImportRef(
                module=target_mod,
                imported_module=target_mod,
                name="default",
                imported_name="default",
                alias=local_name,
                local_name=local_name,
                import_type="commonjs",
                line=ln,
                source_file=file_path,
                source_module=module,
            )
        )
        recorded_import_lines.add((target_mod, "default", local_name))

    for m in _JS_REQUIRE_DESTRUCTURE.finditer(content):
        specifiers = m.group(1)
        target_mod = m.group(2)
        ln = line_of(m.start())
        for raw_spec in specifiers.split(","):
            spec = raw_spec.strip()
            if not spec:
                continue
            if ":" in spec:
                orig, aliased = [p.strip() for p in spec.split(":", 1)]
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
                    import_type="commonjs_destructure",
                    line=ln,
                    source_file=file_path,
                    source_module=module,
                )
            )
            recorded_import_lines.add((target_mod, orig, aliased))

    local_new_bindings: dict[str, str] = {}
    for m in _JS_NEW_ASSIGN.finditer(content):
        local_new_bindings[m.group(1)] = m.group(2)

    import_mods_set = {imp.imported_module for imp in imports}
    bindings: list[BindingRef] = []

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

        current_scope = (
            active_func[0]
            if active_func
            else (active_class[0] if active_class else "")
        )

        m_id = _JS_CONST_ID.match(line)
        if m_id:
            v_name, s_name = m_id.group(1), m_id.group(2)
            if v_name not in _JS_KEYWORDS_AND_BUILTINS and s_name not in _JS_KEYWORDS_AND_BUILTINS:
                bindings.append(
                    BindingRef(
                        target_name=v_name,
                        file_path=file_path,
                        line=lineno,
                        scope=current_scope,
                        expr_kind="IDENTIFIER",
                        source_expr=s_name,
                        base_expr=s_name,
                    )
                )
        else:
            m_attr = _JS_CONST_ATTR.match(line)
            if m_attr:
                v_name, b_name, a_name = m_attr.group(1), m_attr.group(2), m_attr.group(3)
                if v_name not in _JS_KEYWORDS_AND_BUILTINS:
                    bindings.append(
                        BindingRef(
                            target_name=v_name,
                            file_path=file_path,
                            line=lineno,
                            scope=current_scope,
                            expr_kind="ATTRIBUTE",
                            source_expr=f"{b_name}.{a_name}",
                            base_expr=b_name,
                            attr_name=a_name,
                        )
                    )
            else:
                m_dict = _JS_CONST_DICT.match(line)
                m_dict_start = re.match(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\{\s*$", line)
                if m_dict:
                    d_name, d_body = m_dict.group(1), m_dict.group(2)
                    entries: list[tuple[str, str]] = []
                    for raw_entry in d_body.split(","):
                        if ":" in raw_entry:
                            ek, ev = raw_entry.split(":", 1)
                            clean_k = ek.strip().strip("'\"")
                            clean_v = ev.strip()
                            if clean_k and clean_v:
                                entries.append((clean_k, clean_v))
                    if entries:
                        bindings.append(
                            BindingRef(
                                target_name=d_name,
                                file_path=file_path,
                                line=lineno,
                                scope=current_scope,
                                expr_kind="DICT_LITERAL",
                                source_expr=line.strip(),
                                dict_entries=tuple(entries),
                            )
                        )
                elif m_dict_start:
                    d_name = m_dict_start.group(1)
                    body_parts: list[str] = []
                    for j in range(idx + 1, min(idx + 50, len(lines))):
                        sub_ln = lines[j].strip()
                        if sub_ln.startswith("}"):
                            break
                        body_parts.append(sub_ln)
                    d_body = " ".join(body_parts)
                    entries = []
                    for raw_entry in d_body.split(","):
                        if ":" in raw_entry:
                            ek, ev = raw_entry.split(":", 1)
                            clean_k = ek.strip().strip("'\"")
                            clean_v = ev.strip()
                            if clean_k and clean_v:
                                entries.append((clean_k, clean_v))
                    if entries:
                        bindings.append(
                            BindingRef(
                                target_name=d_name,
                                file_path=file_path,
                                line=lineno,
                                scope=current_scope,
                                expr_kind="DICT_LITERAL",
                                source_expr=d_name,
                                dict_entries=tuple(entries),
                            )
                        )
                else:
                    m_sub = _JS_SUBSCRIPT_ASSIGN.match(line)
                    if m_sub:
                        s_target, s_key, s_src = m_sub.group(1), m_sub.group(2), m_sub.group(3)
                        bindings.append(
                            BindingRef(
                                target_name=s_target,
                                file_path=file_path,
                                line=lineno,
                                scope=current_scope,
                                expr_kind="DICT_ASSIGN",
                                source_expr=s_src,
                                base_expr=s_target,
                                subscript_target=s_target,
                                subscript_key=s_key,
                            )
                        )
                    else:
                        m_reg = _JS_REGISTRY_CALL.match(line)
                        if m_reg:
                            r_recv, r_key, r_src = m_reg.group(1), m_reg.group(2), m_reg.group(3)
                            r_lower = r_recv.lower()
                            if r_lower == "registry" or r_lower.endswith("_registry") or r_lower.endswith("registry"):
                                bindings.append(
                                    BindingRef(
                                        target_name=r_recv,
                                        file_path=file_path,
                                        line=lineno,
                                        scope=current_scope,
                                        expr_kind="CALL_REGISTER",
                                        source_expr=r_src,
                                        base_expr=r_recv,
                                        subscript_target=r_recv,
                                        subscript_key=r_key,
                                    )
                                )
                        else:
                            m_evt = _JS_EVENT_ON.match(line)
                            if m_evt:
                                e_recv, e_event, e_src = m_evt.group(1), m_evt.group(2), m_evt.group(3)
                                e_lower = e_recv.lower()
                                if (
                                    e_lower in ("eventemitter", "emitter", "bus", "event_bus")
                                    or e_lower.endswith("emitter")
                                    or e_lower.endswith("bus")
                                ):
                                    bindings.append(
                                        BindingRef(
                                            target_name=e_recv,
                                            file_path=file_path,
                                            line=lineno,
                                            scope=current_scope,
                                            expr_kind="EVENT_ON",
                                            source_expr=e_src,
                                            base_expr=e_recv,
                                            subscript_target=e_recv,
                                            subscript_key=e_event,
                                        )
                                    )

                        m_di = _JS_DI_PROVIDE.search(line)
                        if m_di:
                            bindings.append(
                                BindingRef(
                                    target_name=m_di.group(1),
                                    file_path=file_path,
                                    line=lineno,
                                    scope=current_scope,
                                    expr_kind="DI_PROVIDES",
                                    source_expr=m_di.group(2),
                                    base_expr="providers",
                                )
                            )
                        m_creg = _JS_CONTAINER_REG.match(line)
                        if m_creg:
                            r_recv, r_iface, r_impl = m_creg.group(1), m_creg.group(2), m_creg.group(3)
                            if "container" in r_recv.lower() or "injector" in r_recv.lower():
                                bindings.append(
                                    BindingRef(
                                        target_name=r_iface,
                                        file_path=file_path,
                                        line=lineno,
                                        scope=current_scope,
                                        expr_kind="DI_PROVIDES",
                                        source_expr=r_impl,
                                        base_expr=r_recv,
                                    )
                                )

                        # JS/TS Test client (request(app).get('/api/login'), supertest, etc.)
                        m_js_req = re.search(r"""(?:request(?:\([^)]*\))?|client|agent)\.(get|post|put|delete|patch)\s*\(\s*(['"][^'"]+['"])""", line)
                        if m_js_req:
                            http_m = m_js_req.group(1).upper()
                            route_p = m_js_req.group(2).strip("'\"")
                            bindings.append(
                                BindingRef(
                                    target_name=route_p,
                                    file_path=file_path,
                                    line=lineno,
                                    scope=current_scope,
                                    expr_kind="TEST_ROUTE",
                                    source_expr=http_m,
                                    base_expr="request",
                                    attr_name=http_m,
                                    subscript_target="request",
                                    subscript_key=route_p,
                                )
                            )

                        # Playwright browser navigation (page.goto('/route'))
                        m_js_goto = re.search(r"""page\.goto\s*\(\s*(['"][^'"]+['"]|`[^`]+`|[^,\)]+)""", line)
                        if m_js_goto:
                            raw_url = m_js_goto.group(1).strip()
                            if raw_url.startswith(("'", '"', "`")):
                                url_p = raw_url.strip("'\"`")
                            else:
                                url_p = "<DYNAMIC>"
                            bindings.append(
                                BindingRef(
                                    target_name=url_p,
                                    file_path=file_path,
                                    line=lineno,
                                    scope=current_scope,
                                    expr_kind="TEST_PAGE_GOTO",
                                    source_expr="GOTO",
                                    base_expr="page",
                                    attr_name="goto",
                                    subscript_target="page",
                                    subscript_key=url_p,
                                )
                            )

        # Route detection hook per line (Express and Next.js)
        detected_routes = analyze_js_ts_line(line, lineno, file_path, module, import_mods_set)
        if detected_routes:
            routes.extend(detected_routes)
        detected_mounts = analyze_js_ts_mounts(line, lineno, file_path, module)
        if detected_mounts:
            mounts.extend(detected_mounts)

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

        # Jest / Vitest test("...", () => ...) or it("...", () => ...)
        m_test = re.search(r"""\b(?:test|it)\s*\(\s*(['"][^'"]+['"]|`[^`]+`)""", line)
        if m_test:
            raw_title = m_test.group(1).strip("'\"`")
            clean_title = re.sub(r"[^a-zA-Z0-9_]", "_", raw_title).strip("_")
            t_name = f"test_{clean_title}"[:60] if clean_title else "test_case"
            end_ln = _estimate_block_end(lines, idx)
            scope_str = active_class[0] if active_class else ""
            qname = f"{scope_str}.{t_name}" if scope_str else t_name
            canon_id = build_canonical_id(module, scope_str, t_name)
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=t_name,
                        qualified_name=qname,
                        kind="test",
                        language=language,
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope=scope_str,
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
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

            m_sub_call = _JS_SUBSCRIPT_CALL.search(line)
            if m_sub_call:
                sub_recv = m_sub_call.group(1)
                sub_key = m_sub_call.group(2)
                sub_callee = f"{sub_recv}['{sub_key}']"
                calls.append(
                    CallRef(
                        callee=sub_callee,
                        qualified_callee=sub_callee,
                        line=lineno,
                        end_line=lineno,
                        source_file=file_path,
                        confidence="LOW",
                        caller_symbol=caller_qname,
                        caller_canonical_id=caller_canon,
                        receiver=sub_recv,
                    )
                )

    # Framework file-level enhancements (NestJS and Next.js)
    if "@" in content:
        nest_res = analyze_nestjs_file(content, file_path, module)
        if nest_res.routes:
            routes.extend(nest_res.routes)
        if nest_res.mounts:
            mounts.extend(nest_res.mounts)
        if nest_res.bindings:
            bindings.extend(nest_res.bindings)

    next_res = analyze_nextjs_file(content, file_path, module)
    if next_res.routes:
        seen_ep_ids = {r.endpoint_id for r in routes}
        for nr in next_res.routes:
            if nr.endpoint_id not in seen_ep_ids:
                routes.append(nr)
                seen_ep_ids.add(nr.endpoint_id)
    if next_res.bindings:
        bindings.extend(next_res.bindings)

    # React and JSX component architecture (Pillar 4)
    react_res = analyze_react_file(content, file_path, module)
    sym_indices = {s.canonical_id: i for i, s in enumerate(symbols)}
    for sym in react_res.components:
        if sym.canonical_id in sym_indices:
            symbols[sym_indices[sym.canonical_id]] = sym
        else:
            seen_canonical.add(sym.canonical_id)
            symbols.append(sym)
    for h_sym in react_res.hooks:
        if h_sym.canonical_id in sym_indices:
            symbols[sym_indices[h_sym.canonical_id]] = h_sym
        else:
            seen_canonical.add(h_sym.canonical_id)
            symbols.append(h_sym)
    if react_res.bindings:
        bindings.extend(react_res.bindings)

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
        mounts=tuple(mounts),
        bindings=tuple(bindings),
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
