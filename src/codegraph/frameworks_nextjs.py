"""Deterministic Next.js App Router and Server Actions analyzer.

Features:
- App Router directory-derived route mapping (`app/**/route.ts` and `app/**/page.tsx`).
- Route group unwrapping: `app/(auth)/login/route.ts` -> `/login`.
- Dynamic segment normalization: `[id]` -> `{id}`, `[...slug]` -> `{slug}`, `[[...slug]]` -> `{slug}`.
- HTTP method route handlers: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`.
- Page routes: default exports from `page.tsx` mapped to `GET` routes.
- Server Actions detection:
  - File-level `'use server'` marks all exported async functions as `SERVER_ACTION`.
  - Function-level `'use server'` marks specific functions as `SERVER_ACTION`.
- Client Component hydration boundary detection: file-level `'use client'`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from codegraph.frameworks import FrameworkEvidence, RouteDetection, normalize_route_path
from codegraph.indexing.models import BindingRef

_NEXT_ROUTE_METHODS = frozenset({
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "OPTIONS",
    "HEAD",
})

# Matches export (async) function NAME
_EXPORT_FUNC_RE = re.compile(
    r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
)

# Matches export const NAME = (async) (
_EXPORT_CONST_FUNC_RE = re.compile(
    r"\bexport\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)

# Matches export default function/const
_EXPORT_DEFAULT_RE = re.compile(
    r"\bexport\s+default\s+(?:async\s+)?(?:function\s*([A-Za-z_$][\w$]*)?|class\s*([A-Za-z_$][\w$]*)?|([A-Za-z_$][\w$]*))"
)

# Function body scan for inline 'use server'
_INLINE_USE_SERVER_RE = re.compile(
    r"(?:async\s+function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*async)[\s\S]*?\{[\s\S]*?['\"`]use server['\"`]"
)


@dataclass
class NextjsAnalysisResult:
    routes: list[RouteDetection] = field(default_factory=list)
    evidence: list[FrameworkEvidence] = field(default_factory=list)
    bindings: list[BindingRef] = field(default_factory=list)
    server_actions: list[str] = field(default_factory=list)
    is_client_component: bool = False
    is_server_actions_file: bool = False


def resolve_nextjs_route_path(file_path: str) -> tuple[str, str]:
    """Derive canonical URL route and normalized route from Next.js App Router file path.

    Handles:
    - Root and nested app dirs: `app/...` or `src/app/...`
    - Route groups: `app/(dashboard)/invoices/page.tsx` -> `/invoices`
    - Dynamic params: `[id]` -> `{id}`, `[...slug]` -> `{slug}`
    """
    norm_path = file_path.replace("\\", "/").strip("/")

    # Find where app/ or pages/ starts
    app_idx = -1
    for prefix in ("/src/app/", "src/app/", "/app/", "app/"):
        idx = norm_path.find(prefix)
        if idx != -1:
            app_idx = idx + len(prefix)
            break

    if app_idx == -1:
        # Fallback: check if path contains route.ts/page.tsx directly
        subpath = norm_path.rsplit("/", 1)[0] if "/" in norm_path else ""
    else:
        subpath = norm_path[app_idx:]
        if "/" in subpath:
            subpath = subpath.rsplit("/", 1)[0]
        else:
            subpath = ""

    # Split into path segments and strip route groups (parenthesized folders) and parallel routes (@)
    raw_segments = subpath.split("/") if subpath else []
    cleaned_segments: list[str] = []
    for seg in raw_segments:
        s = seg.strip()
        if not s:
            continue
        # Route groups like (auth), (dashboard) are omitted from route path
        if s.startswith("(") and s.endswith(")"):
            continue
        # Parallel slots like @modal are omitted from route path
        if s.startswith("@"):
            continue
        cleaned_segments.append(s)

    raw_route = "/" + "/".join(cleaned_segments) if cleaned_segments else "/"
    normalized = normalize_route_path(raw_route, "nextjs")
    return raw_route, normalized


def analyze_nextjs_file(
    content: str,
    file_path: str,
    module: str,
) -> NextjsAnalysisResult:
    """Analyze a TypeScript/JavaScript file for Next.js App Router routes, Server Actions, and Client Components."""
    res = NextjsAnalysisResult()
    if not content:
        return res

    norm_path = file_path.replace("\\", "/").lower()
    is_route_file = (
        norm_path.endswith("/route.ts")
        or norm_path.endswith("/route.js")
        or norm_path.endswith("/route.mjs")
        or norm_path == "route.ts"
        or norm_path == "route.js"
    )
    is_page_file = (
        norm_path.endswith("/page.tsx")
        or norm_path.endswith("/page.jsx")
        or norm_path.endswith("/page.ts")
        or norm_path.endswith("/page.js")
        or norm_path == "page.tsx"
        or norm_path == "page.jsx"
    )

    lines = content.splitlines()

    # 1. Inspect top directives: 'use server' or 'use client'
    top_use_server = False
    for line_idx, line in enumerate(lines[:15], start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        if stripped in ("'use server';", '"use server";', "'use server'", '"use server"'):
            top_use_server = True
            res.is_server_actions_file = True
            res.evidence.append(
                FrameworkEvidence(
                    framework="nextjs",
                    construct_type="SERVER_ACTION_FILE",
                    file_path=file_path,
                    line=line_idx,
                    column=line.find(stripped),
                    evidence="File-level 'use server' directive",
                )
            )
            break
        elif stripped in ("'use client';", '"use client";', "'use client'", '"use client"'):
            res.is_client_component = True
            res.evidence.append(
                FrameworkEvidence(
                    framework="nextjs",
                    construct_type="CLIENT_COMPONENT",
                    file_path=file_path,
                    line=line_idx,
                    column=line.find(stripped),
                    evidence="Client component hydration boundary ('use client')",
                )
            )
            break
        # First non-comment statement that is not a directive terminates directive search
        if not stripped.startswith(("import ", "'use ", '"use ')):
            break

    # 2. Server Actions:
    # If file has file-level 'use server', any exported async function is a Server Action
    if top_use_server:
        for line_idx, line in enumerate(lines, start=1):
            for m in _EXPORT_FUNC_RE.finditer(line):
                fn_name = m.group(1)
                res.server_actions.append(fn_name)
                res.evidence.append(
                    FrameworkEvidence(
                        framework="nextjs",
                        construct_type="SERVER_ACTION",
                        file_path=file_path,
                        line=line_idx,
                        column=m.start(),
                        evidence=f"Next.js Server Action: export async function {fn_name}",
                    )
                )
                res.bindings.append(
                    BindingRef(
                        target_name=f"{module}.{fn_name}",
                        source_expr=fn_name,
                        file_path=file_path,
                        line=line_idx,
                        scope="",
                        expr_kind="SERVER_ACTION",
                        base_expr="nextjs_server_action",
                        attr_name=fn_name,
                    )
                )
            for m in _EXPORT_CONST_FUNC_RE.finditer(line):
                fn_name = m.group(1)
                res.server_actions.append(fn_name)
                res.evidence.append(
                    FrameworkEvidence(
                        framework="nextjs",
                        construct_type="SERVER_ACTION",
                        file_path=file_path,
                        line=line_idx,
                        column=m.start(),
                        evidence=f"Next.js Server Action: export const {fn_name} = async ...",
                    )
                )
                res.bindings.append(
                    BindingRef(
                        target_name=f"{module}.{fn_name}",
                        source_expr=fn_name,
                        file_path=file_path,
                        line=line_idx,
                        scope="",
                        expr_kind="SERVER_ACTION",
                        base_expr="nextjs_server_action",
                        attr_name=fn_name,
                    )
                )
    else:
        # Check for inline 'use server' inside function bodies
        for m in _INLINE_USE_SERVER_RE.finditer(content):
            fn_name = m.group(1) or m.group(2)
            if fn_name:
                line_no = content[: m.start()].count("\n") + 1
                res.server_actions.append(fn_name)
                res.evidence.append(
                    FrameworkEvidence(
                        framework="nextjs",
                        construct_type="SERVER_ACTION",
                        file_path=file_path,
                        line=line_no,
                        column=None,
                        evidence=f"Next.js inline Server Action {fn_name}",
                    )
                )
                res.bindings.append(
                    BindingRef(
                        target_name=f"{module}.{fn_name}",
                        source_expr=fn_name,
                        file_path=file_path,
                        line=line_no,
                        scope="",
                        expr_kind="SERVER_ACTION",
                        base_expr="nextjs_server_action",
                        attr_name=fn_name,
                    )
                )

    # 3. Route Handlers: app/**/route.ts
    if is_route_file:
        raw_route, norm_route = resolve_nextjs_route_path(file_path)
        for line_idx, line in enumerate(lines, start=1):
            # Check function exports
            for m in _EXPORT_FUNC_RE.finditer(line):
                method_name = m.group(1).upper()
                if method_name in _NEXT_ROUTE_METHODS:
                    res.routes.append(
                        RouteDetection(
                            framework="nextjs",
                            http_method=method_name,
                            route_path=raw_route,
                            normalized_route=norm_route,
                            handler_name=method_name,
                            handler_canonical_id=f"{module}.{method_name}",
                            file_path=file_path,
                            line=line_idx,
                            column=m.start(),
                            confidence="HIGH",
                            resolution_status="RESOLVED",
                            evidence=f"Next.js App Router HTTP handler {method_name} in {file_path}",
                            module=module,
                            router_name="export",
                        )
                    )
            # Check const exports
            for m in _EXPORT_CONST_FUNC_RE.finditer(line):
                method_name = m.group(1).upper()
                if method_name in _NEXT_ROUTE_METHODS:
                    res.routes.append(
                        RouteDetection(
                            framework="nextjs",
                            http_method=method_name,
                            route_path=raw_route,
                            normalized_route=norm_route,
                            handler_name=method_name,
                            handler_canonical_id=f"{module}.{method_name}",
                            file_path=file_path,
                            line=line_idx,
                            column=m.start(),
                            confidence="HIGH",
                            resolution_status="RESOLVED",
                            evidence=f"Next.js App Router HTTP handler {method_name} in {file_path}",
                            module=module,
                            router_name="export",
                        )
                    )

    # 4. Page Routes: app/**/page.tsx
    elif is_page_file:
        raw_route, norm_route = resolve_nextjs_route_path(file_path)
        for line_idx, line in enumerate(lines, start=1):
            page_m = _EXPORT_DEFAULT_RE.search(line)
            if page_m:
                fn_name = page_m.group(1) or page_m.group(2) or page_m.group(3) or "default"
                res.routes.append(
                    RouteDetection(
                        framework="nextjs",
                        http_method="GET",
                        route_path=raw_route,
                        normalized_route=norm_route,
                        handler_name=fn_name,
                        handler_canonical_id=f"{module}.{fn_name}",
                        file_path=file_path,
                        line=line_idx,
                        column=page_m.start(),
                        confidence="HIGH",
                        resolution_status="RESOLVED",
                        evidence=f"Next.js App Router Page route GET {raw_route} ({fn_name})",
                        module=module,
                        router_name="page",
                    )
                )
                break

    return res
