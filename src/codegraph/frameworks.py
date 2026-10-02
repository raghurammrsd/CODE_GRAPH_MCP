"""Pluggable, evidence-driven framework analyzers for Python and JavaScript/TypeScript.

Supported Frameworks:
  Python: Flask, FastAPI, Django
  JavaScript/TypeScript: Express, Next.js (App Router)

Architectural Invariants:
1. Framework behavior is detected ONLY when concrete source evidence (imports, decorators,
   route registration calls, or verified route handler exports) exists in the file.
2. Route detection NEVER rescans the full AST; it consumes node visit events during
   the primary single-pass parser traversal.
3. Every endpoint produces a stable endpoint_id, human-readable route_signature, original
   source route_path, and canonical normalized_route.
4. Framework endpoints link to handlers via HANDLED_BY semantic edges using the standard
   canonical symbol ID.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class FrameworkEvidence:
    framework: str  # flask | fastapi | django | express | nextjs
    construct_type: str  # ROUTE | CONTROLLER | MIDDLEWARE | DEPENDENCY | MODEL
    file_path: str
    line: int
    column: int | None
    evidence: str
    confidence: str = "HIGH"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_route_path(route_path: str, framework: str) -> str:
    """Normalize framework-specific route parameters into canonical `{param}` format.

    Examples:
      Flask:    /users/<id>       -> /users/{id}
      Flask:    /users/<int:id>   -> /users/{id}
      FastAPI:  /users/{id}       -> /users/{id}
      Express:  /users/:id        -> /users/{id}
      Next.js:  /users/[id]       -> /users/{id}
      Next.js:  /users/[...slug]  -> /users/{slug}
    """
    raw = "/" + route_path.strip().lstrip("/") if route_path.strip() else "/"
    # Strip trailing slash unless root
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw.rstrip("/")

    if framework == "flask":
        # Match <[type:]param>
        return re.sub(r"<(?:\w+:)?([A-Za-z_][\w]*)>", r"{\1}", raw)
    elif framework == "express":
        # Match :param
        return re.sub(r":([A-Za-z_][\w]*)", r"{\1}", raw)
    elif framework == "nextjs":
        # Match [[...param]] or [...param] or [param]
        return re.sub(r"\[(?:\.\.\.)?([A-Za-z_][\w]*)\]", r"{\1}", raw)
    return raw


@dataclass(frozen=True)
class RouteDetection:
    framework: str  # flask | fastapi | django | express | nextjs
    http_method: str  # GET | POST | PUT | DELETE | PATCH | OPTIONS | HEAD | ANY
    route_path: str  # Original framework route string, e.g. /users/<int:id>
    normalized_route: str  # Canonical route string, e.g. /users/{id}
    handler_name: str  # e.g. "login_controller"
    handler_canonical_id: str  # Standard canonical symbol ID, e.g. "src.auth.routes.login_controller"
    file_path: str
    line: int
    column: int | None = None
    confidence: str = "HIGH"
    resolution_status: str = "RESOLVED"  # RESOLVED | UNRESOLVED | AMBIGUOUS
    evidence: str = ""
    module: str = ""
    endpoint_id_override: str | None = None

    @property
    def route_signature(self) -> str:
        """Human-readable route signature, e.g. 'POST /login'."""
        return f"{self.http_method} {self.route_path}"

    @property
    def endpoint_id(self) -> str:
        """Stable, deterministic, globally unique endpoint identifier for a route declaration."""
        if self.endpoint_id_override:
            return self.endpoint_id_override

        clean_path = self.file_path.replace("\\", "/").strip()
        while clean_path.startswith("./"):
            clean_path = clean_path[2:]
        clean_path = clean_path.lstrip("/") or "root"

        handler_part = f"#{self.handler_name}" if self.handler_name else ""
        fw_part = f":{self.framework}" if self.framework else ""
        return f"API_ENDPOINT{fw_part}:{clean_path}:{self.line}:{self.http_method} {self.normalized_route}{handler_part}"

    def as_dict(self) -> dict[str, object]:
        return {
            "endpoint_id": self.endpoint_id,
            "route_signature": self.route_signature,
            "framework": self.framework,
            "http_method": self.http_method,
            "route_path": self.route_path,
            "normalized_route": self.normalized_route,
            "handler_name": self.handler_name,
            "handler_canonical_id": self.handler_canonical_id,
            "file": self.file_path,
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "confidence": self.confidence,
            "resolution_status": self.resolution_status,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class AnalysisContext:
    file_path: str
    module: str
    imports_modules: set[str]
    scope_qname: str
    scope_canonical_id: str
    scope_kind: str


class FrameworkAnalyzer(Protocol):
    framework: str

    def analyze_python_node(
        self,
        node: ast.AST,
        context: AnalysisContext,
    ) -> list[RouteDetection]: ...


# ---------------------------------------------------------------------------
# Python Framework Analyzers
# ---------------------------------------------------------------------------

_FLASK_METHODS = {"route", "get", "post", "put", "delete", "patch"}


class FlaskAnalyzer:
    framework = "flask"

    def analyze_python_node(
        self,
        node: ast.AST,
        context: AnalysisContext,
    ) -> list[RouteDetection]:
        routes: list[RouteDetection] = []
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return routes

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            attr = dec.func.attr.lower()
            if attr not in _FLASK_METHODS or not dec.args:
                continue

            first_arg = dec.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue

            route_path = first_arg.value
            methods = [attr.upper()] if attr != "route" else ["GET"]

            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [
                        e.value.upper()
                        for e in kw.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ] or ["GET"]

            col = getattr(dec, "col_offset", None)
            norm = normalize_route_path(route_path, "flask")
            handler_canon = (
                f"{context.scope_canonical_id}.{node.name}"
                if context.scope_qname
                else f"{context.module}.{node.name}"
            )

            for method in methods:
                routes.append(
                    RouteDetection(
                        framework="flask",
                        http_method=method,
                        route_path=route_path,
                        normalized_route=norm,
                        handler_name=node.name,
                        handler_canonical_id=handler_canon,
                        file_path=context.file_path,
                        line=dec.lineno,
                        column=col,
                        confidence="HIGH",
                        resolution_status="RESOLVED",
                        evidence=f"Flask decorator @{ast.unparse(dec.func)}('{route_path}') on {node.name}",
                        module=context.module,
                    )
                )
        return routes


_FASTAPI_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "api_route"}


class FastAPIAnalyzer:
    framework = "fastapi"

    def analyze_python_node(
        self,
        node: ast.AST,
        context: AnalysisContext,
    ) -> list[RouteDetection]:
        routes: list[RouteDetection] = []
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return routes

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            attr = dec.func.attr.lower()
            if attr not in _FASTAPI_METHODS or not dec.args:
                continue

            first_arg = dec.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue

            route_path = first_arg.value
            methods = [attr.upper()] if attr != "api_route" else ["GET"]

            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [
                        e.value.upper()
                        for e in kw.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ] or ["GET"]

            col = getattr(dec, "col_offset", None)
            norm = normalize_route_path(route_path, "fastapi")
            handler_canon = (
                f"{context.scope_canonical_id}.{node.name}"
                if context.scope_qname
                else f"{context.module}.{node.name}"
            )

            for method in methods:
                routes.append(
                    RouteDetection(
                        framework="fastapi",
                        http_method=method,
                        route_path=route_path,
                        normalized_route=norm,
                        handler_name=node.name,
                        handler_canonical_id=handler_canon,
                        file_path=context.file_path,
                        line=dec.lineno,
                        column=col,
                        confidence="HIGH",
                        resolution_status="RESOLVED",
                        evidence=f"FastAPI decorator @{ast.unparse(dec.func)}('{route_path}') on {node.name}",
                        module=context.module,
                    )
                )
        return routes


class DjangoAnalyzer:
    framework = "django"

    def analyze_python_node(
        self,
        node: ast.AST,
        context: AnalysisContext,
    ) -> list[RouteDetection]:
        routes: list[RouteDetection] = []
        if not isinstance(node, ast.Call):
            return routes

        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in ("path", "re_path") and len(node.args) >= 2:
            arg0, arg1 = node.args[0], node.args[1]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                route_path = "/" + arg0.value.lstrip("/")
                handler_expr = ast.unparse(arg1) if hasattr(ast, "unparse") else "handler"
                handler_clean = handler_expr.replace(".as_view()", "").strip()
                handler_name = handler_clean.split(".")[-1]
                handler_canon = (
                    f"{context.module}.{handler_clean}"
                    if not handler_clean.startswith(context.module)
                    else handler_clean
                )
                col = getattr(node, "col_offset", None)
                norm = normalize_route_path(route_path, "django")

                routes.append(
                    RouteDetection(
                        framework="django",
                        http_method="ANY",
                        route_path=route_path,
                        normalized_route=norm,
                        handler_name=handler_name,
                        handler_canonical_id=handler_canon,
                        file_path=context.file_path,
                        line=node.lineno,
                        column=col,
                        confidence="HIGH",
                        resolution_status="RESOLVED",
                        evidence=f"Django {func_name}('{arg0.value}', {handler_expr})",
                        module=context.module,
                    )
                )
        return routes


def get_python_analyzers(imports_modules: set[str]) -> list[FrameworkAnalyzer]:
    """Select relevant Python framework analyzers based on concrete source import evidence."""
    analyzers: list[FrameworkAnalyzer] = []
    has_flask = any("flask" in m for m in imports_modules)
    has_fastapi = any("fastapi" in m for m in imports_modules)
    has_django = any("django" in m for m in imports_modules)

    if has_flask:
        analyzers.append(FlaskAnalyzer())
    if has_fastapi:
        analyzers.append(FastAPIAnalyzer())
    if has_django:
        analyzers.append(DjangoAnalyzer())

    # If no framework import is explicitly present, enable all 3 conservatively so route decorators
    # in files where imports are implicit or aliased are still recognized
    if not analyzers:
        analyzers = [FlaskAnalyzer(), FastAPIAnalyzer(), DjangoAnalyzer()]

    return analyzers


# ---------------------------------------------------------------------------
# JavaScript / TypeScript Framework Analyzers
# ---------------------------------------------------------------------------

_EXPRESS_CALL_RE = re.compile(
    r"\b(?:app|router)\.(get|post|put|delete|patch|options|head|all)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_$][\w$.]*)",
    re.IGNORECASE,
)

_NEXT_ROUTE_EXPORT_RE = re.compile(
    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\("
)


def analyze_js_ts_line(
    line: str,
    lineno: int,
    file_path: str,
    module: str,
    imports_modules: set[str],
) -> list[RouteDetection]:
    """Analyze a single JS/TS line during single-pass scan for Express and Next.js routes."""
    routes: list[RouteDetection] = []

    # 1. Express route registration
    for m in _EXPRESS_CALL_RE.finditer(line):
        method = m.group(1).upper()
        if method == "ALL":
            method = "ANY"
        route_path = m.group(2)
        handler_expr = m.group(3)
        handler_name = handler_expr.split(".")[-1]
        handler_canon = f"{module}.{handler_expr}"
        norm = normalize_route_path(route_path, "express")

        routes.append(
            RouteDetection(
                framework="express",
                http_method=method,
                route_path=route_path,
                normalized_route=norm,
                handler_name=handler_name,
                handler_canonical_id=handler_canon,
                file_path=file_path,
                line=lineno,
                column=m.start(),
                confidence="HIGH",
                resolution_status="RESOLVED",
                evidence=f"Express route registration {m.group(0)}",
                module=module,
            )
        )

    # 2. Next.js App Router route handlers (e.g. app/api/login/route.ts)
    norm_path = file_path.replace("\\", "/")
    is_next_app_route = "/route." in norm_path or norm_path.startswith("route.")
    has_next_import = any("next" in m.lower() for m in imports_modules)

    if is_next_app_route or has_next_import:
        for m in _NEXT_ROUTE_EXPORT_RE.finditer(line):
            method = m.group(1).upper()
            route_path = "/" + norm_path.rsplit("/", 1)[0] if "/" in norm_path else "/"
            for prefix in ("/src/app", "/app", "/src/pages", "/pages"):
                if route_path.startswith(prefix):
                    route_path = route_path[len(prefix) :] or "/"
                    break
            norm = normalize_route_path(route_path, "nextjs")
            routes.append(
                RouteDetection(
                    framework="nextjs",
                    http_method=method,
                    route_path=route_path,
                    normalized_route=norm,
                    handler_name=method,
                    handler_canonical_id=f"{module}.{method}",
                    file_path=file_path,
                    line=lineno,
                    column=m.start(),
                    confidence="HIGH",
                    resolution_status="RESOLVED",
                    evidence=f"Next.js App Router HTTP export {method} in {file_path}",
                    module=module,
                )
            )

    return routes
