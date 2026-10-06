"""React and JSX/TSX Component Architecture and Composition Analyzer (Pillar 4).

Extracts deterministic facts from React components:
- Component definitions (Functional components, React.FC, memo, forwardRef)
- Custom hooks (useAuth, useInvoices)
- JSX component composition hierarchy (ParentComponent -> RENDERS -> ChildComponent)
- Hook invocations (Component -> USES_HOOK -> Hook)
- Context provider mountings (Component -> PROVIDES -> Context)
- Client-side data fetching (Component/Hook -> FETCHES_ROUTE -> RouteEndpoint)
- Stylesheet imports and CSS class usages (IMPORTS_STYLE, USES_STYLE_CLASS)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from codegraph.indexing.models import BindingRef, Symbol

_REACT_BUILTINS = frozenset({
    "Fragment",
    "React.Fragment",
    "Suspense",
    "React.Suspense",
    "StrictMode",
    "React.StrictMode",
    "Profiler",
    "React.Profiler",
})

# React component function / arrow definition patterns
_REACT_FUNC_COMP = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Z][A-Za-z0-9_$]*)\s*\("
)
_REACT_CONST_COMP = re.compile(
    r"^(?:export\s+)?(?:const|let)\s+([A-Z][A-Za-z0-9_$]*)\s*(?::\s*(?:React\.)?(?:FC|FunctionComponent)(?:<[^>]+>)?)?\s*=\s*"
    r"(?:(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*=>|function\b|(?:React\.)?(?:memo|forwardRef)\s*\()"
)

# Custom hook definition patterns (starts with 'use' followed by uppercase letter)
_REACT_HOOK_DEF = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(use[A-Z][A-Za-z0-9_$]*)\s*\("
    r"|^(?:export\s+)?(?:const|let)\s+(use[A-Z][A-Za-z0-9_$]*)\s*(?::\s*[^=]+)?=\s*"
)

# JSX element tag opening: <ComponentName ... or <ComponentName/> or <Namespace.Component
_JSX_ELEMENT_TAG = re.compile(
    r"<([A-Z][A-Za-z0-9_$]*(?:\.[A-Z][A-Za-z0-9_$]*)?)[\s/>]"
)

# Context provider: <AuthContext.Provider
_CONTEXT_PROVIDER_TAG = re.compile(
    r"<([A-Za-z0-9_$]+Context)\.Provider[\s>]"
)

# Hook invocation call: useAuth(), useInvoices(), useState()
_HOOK_CALL = re.compile(
    r"\b(use[A-Z][A-Za-z0-9_$]*)\s*\("
)

# Client-side data fetching calls across all major modern libraries (fetch, axios, useSWR, useQuery, etc.)
_FETCH_CALL_PATTERNS = (
    # fetch<ResponseType>('/api/...') or fetch(`/api/...`)
    re.compile(
        r"""\bfetch\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*[`'"](/[^`'"]+)[`'"]"""
    ),
    # (axios|api|apiClient|client|http|httpClient|request).verb<ResponseType>('/api/...')
    re.compile(
        r"""\b(?:axios|api|apiClient|client|http|httpClient|request)\.(get|post|put|delete|patch)\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*[`'"](/[^`'"]+)[`'"]"""
    ),
    # axios<ResponseType>('/api/...') or axios({ url: '/api/...' })
    re.compile(
        r"""\baxios\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*(?:\{\s*url:\s*)?[`'"](/[^`'"]+)[`'"]"""
    ),
    # useSWR<ResponseType>('/api/...')
    re.compile(
        r"""\buseSWR\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*(?:\[\s*)?[`'"](/[^`'"]+)[`'"]"""
    ),
    # useQuery<ResponseType>(['/api/...']) or useQuery({ queryKey: ['/api/...'] })
    re.compile(
        r"""\buseQuery\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*(?:\[\s*|\{\s*queryKey:\s*\[\s*)?[`'"](/[^`'"]+)[`'"]"""
    ),
    # $fetch<ResponseType>('/api/...') or useFetch<ResponseType>('/api/...') (Vue / Nuxt)
    re.compile(
        r"""\b(?:\$fetch|useFetch)\s*(?:<([A-Za-z0-9_$,\s\[\]]+)>)?\s*\(\s*[`'"](/[^`'"]+)[`'"]"""
    ),
)

_TS_INTERFACE_DEF = re.compile(
    r"""(?:export\s+)?(?:interface|type)\s+([A-Z][A-Za-z0-9_$]*)(?:\s+extends\s+[^{]+)?\s*(?:=\s*)?\{([^}]+)\}""",
    re.MULTILINE | re.DOTALL,
)
_TS_FIELD_DEF = re.compile(r"""([a-zA-Z0-9_$]+)(\?)?\s*:\s*([^;,\n]+)""")


# CSS / SCSS style imports
_STYLE_IMPORT_NAMED = re.compile(
    r"""import\s+([A-Za-z0-9_$]+)\s+from\s+['"]([^'"]+\.(?:module\.(?:css|scss|sass|less)|css|scss|sass|less))['"]"""
)
_STYLE_IMPORT_SIDE_EFFECT = re.compile(
    r"""import\s+['"]([^'"]+\.(?:module\.(?:css|scss|sass|less)|css|scss|sass|less))['"]"""
)

# CSS class usage: styles.headerTitle or styles['header-title']
_MODULE_CLASS_USAGE = re.compile(
    r"""\b([A-Za-z0-9_$]+)\.([A-Za-z0-9_$]+)|\b([A-Za-z0-9_$]+)\['([^']+)'\]"""
)
# className="btn-primary flex items-center"
_CLASSNAME_LITERAL = re.compile(
    r"""className\s*=\s*['"]([^'"]+)['"]"""
)


@dataclass(frozen=True)
class ReactElementRender:
    parent_component: str
    child_component: str
    file_path: str
    line: int


@dataclass(frozen=True)
class ReactHookCall:
    caller_symbol: str
    hook_name: str
    file_path: str
    line: int


@dataclass(frozen=True)
class ReactAnalysisResult:
    components: tuple[Symbol, ...] = ()
    hooks: tuple[Symbol, ...] = ()
    bindings: tuple[BindingRef, ...] = ()
    renders: tuple[ReactElementRender, ...] = ()
    hook_calls: tuple[ReactHookCall, ...] = ()


def _estimate_block_end(lines: list[str], start_idx: int) -> int:
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


def is_react_or_ui_file(file_path: str, content: str) -> bool:
    """Check if file is likely a React or JSX/TSX component file."""
    if file_path.endswith((".jsx", ".tsx")):
        return True
    if any(k in content for k in ("React", "useState", "useEffect", "export default function", "className=")):
        return True
    return False


def analyze_react_file(
    content: str,
    file_path: str,
    module: str,
) -> ReactAnalysisResult:
    """Parse React components, JSX renders, custom hooks, style links, and data fetches."""
    if not is_react_or_ui_file(file_path, content):
        return ReactAnalysisResult()

    lines = content.splitlines()
    components: list[Symbol] = []
    hooks: list[Symbol] = []
    bindings: list[BindingRef] = []
    renders: list[ReactElementRender] = []
    hook_calls: list[ReactHookCall] = []

    # Map line number intervals to active component/hook name
    scope_intervals: list[tuple[int, int, str]] = []

    # 1. First pass: Discover component definitions and custom hooks
    for idx, line in enumerate(lines):
        lineno = idx + 1
        stripped = line.strip()

        # Component definition
        m_comp = _REACT_FUNC_COMP.match(stripped) or _REACT_CONST_COMP.match(stripped)
        if m_comp:
            c_name = m_comp.group(1)
            end_ln = _estimate_block_end(lines, idx)
            scope_intervals.append((lineno, end_ln, c_name))
            canon_id = f"{module}.{c_name}" if module else c_name
            components.append(
                Symbol(
                    id=canon_id,
                    canonical_id=canon_id,
                    name=c_name,
                    qualified_name=c_name,
                    kind="component",
                    language="typescript" if file_path.endswith((".ts", ".tsx")) else "javascript",
                    module=module,
                    path=file_path,
                    file_path=file_path,
                    scope="",
                    start_line=lineno,
                    end_line=end_ln,
                )
            )
            continue

        # Hook definition
        m_hook = _REACT_HOOK_DEF.match(stripped)
        if m_hook:
            h_name = m_hook.group(1) or m_hook.group(2)
            end_ln = _estimate_block_end(lines, idx)
            scope_intervals.append((lineno, end_ln, h_name))
            canon_id = f"{module}.{h_name}" if module else h_name
            hooks.append(
                Symbol(
                    id=canon_id,
                    canonical_id=canon_id,
                    name=h_name,
                    qualified_name=h_name,
                    kind="hook",
                    language="typescript" if file_path.endswith((".ts", ".tsx")) else "javascript",
                    module=module,
                    path=file_path,
                    file_path=file_path,
                    scope="",
                    start_line=lineno,
                    end_line=end_ln,
                )
            )

    # 2. Extract style imports at file level
    style_bindings: dict[str, str] = {}  # binding variable -> stylesheet path
    for idx, line in enumerate(lines):
        lineno = idx + 1
        m_style = _STYLE_IMPORT_NAMED.search(line)
        if m_style:
            var_name, style_path = m_style.group(1), m_style.group(2)
            style_bindings[var_name] = style_path
            bindings.append(
                BindingRef(
                    target_name=style_path,
                    file_path=file_path,
                    line=lineno,
                    scope="",
                    expr_kind="REACT_IMPORTS_STYLE",
                    source_expr=var_name,
                    base_expr="IMPORTS_STYLE",
                )
            )
        else:
            m_side = _STYLE_IMPORT_SIDE_EFFECT.search(line)
            if m_side:
                style_path = m_side.group(1)
                bindings.append(
                    BindingRef(
                        target_name=style_path,
                        file_path=file_path,
                        line=lineno,
                        scope="",
                        expr_kind="REACT_IMPORTS_STYLE",
                        source_expr="",
                        base_expr="IMPORTS_STYLE",
                    )
                )

    def find_active_scope(ln: int) -> str:
        for start, end, name in scope_intervals:
            if start <= ln <= end:
                return name
        return ""

    # 3. Second pass: Scan for JSX renders, hook invocations, context providers, fetch calls, class usages
    seen_renders: set[tuple[str, str, int]] = set()

    for idx, line in enumerate(lines):
        lineno = idx + 1
        active_sym = find_active_scope(lineno)

        # JSX Elements (<Button ...>)
        for m_jsx in _JSX_ELEMENT_TAG.finditer(line):
            child_name = m_jsx.group(1)
            if child_name not in _REACT_BUILTINS:
                if active_sym and (active_sym, child_name, lineno) not in seen_renders:
                    seen_renders.add((active_sym, child_name, lineno))
                    renders.append(
                        ReactElementRender(
                            parent_component=active_sym,
                            child_component=child_name,
                            file_path=file_path,
                            line=lineno,
                        )
                    )
                    bindings.append(
                        BindingRef(
                            target_name=child_name,
                            file_path=file_path,
                            line=lineno,
                            scope=active_sym,
                            expr_kind="REACT_RENDERS",
                            source_expr=active_sym,
                            base_expr="RENDERS",
                        )
                    )

        # Context Providers (<AuthContext.Provider ...>)
        for m_ctx in _CONTEXT_PROVIDER_TAG.finditer(line):
            ctx_name = m_ctx.group(1)
            bindings.append(
                BindingRef(
                    target_name=ctx_name,
                    file_path=file_path,
                    line=lineno,
                    scope=active_sym,
                    expr_kind="REACT_CONTEXT_PROVIDER",
                    source_expr=active_sym,
                    base_expr="PROVIDES",
                )
            )

        # Hook invocations (useAuth(), useQuery())
        for m_hcall in _HOOK_CALL.finditer(line):
            hook_name = m_hcall.group(1)
            # Avoid self-reference if inside definition line
            if active_sym and active_sym != hook_name:
                hook_calls.append(
                    ReactHookCall(
                        caller_symbol=active_sym,
                        hook_name=hook_name,
                        file_path=file_path,
                        line=lineno,
                    )
                )
                bindings.append(
                    BindingRef(
                        target_name=hook_name,
                        file_path=file_path,
                        line=lineno,
                        scope=active_sym,
                        expr_kind="REACT_USES_HOOK",
                        source_expr=active_sym,
                        base_expr="USES_HOOK",
                    )
                )

        # Client-side API fetch calls across all modern libraries
        for p in _FETCH_CALL_PATTERNS:
            for m_fetch in p.finditer(line):
                groups = m_fetch.groups()
                method = "GET"
                resp_type = ""
                raw_path = ""

                if len(groups) == 3:
                    method = (groups[0] or "GET").upper()
                    resp_type = (groups[1] or "").strip()
                    raw_path = groups[2] or ""
                elif len(groups) == 2:
                    resp_type = (groups[0] or "").strip()
                    raw_path = groups[1] or ""
                elif len(groups) == 1:
                    raw_path = groups[0] or ""

                if raw_path:
                    m_method = re.search(r"""\bmethod\s*:\s*['"]([A-Za-z]+)['"]""", line, re.IGNORECASE)
                    if m_method:
                        method = m_method.group(1).upper()

                    bindings.append(
                        BindingRef(
                            target_name=raw_path,
                            file_path=file_path,
                            line=lineno,
                            scope=active_sym,
                            expr_kind="REACT_FETCH_ROUTE",
                            source_expr=active_sym or file_path,
                            base_expr=method,
                            attr_name=resp_type,
                        )
                    )


        # CSS Class references via styles object (e.g. styles.invoiceHeader)
        for m_mod in _MODULE_CLASS_USAGE.finditer(line):
            mod_obj = m_mod.group(1) or m_mod.group(3)
            cls_name = m_mod.group(2) or m_mod.group(4)
            if mod_obj in style_bindings and cls_name:
                bindings.append(
                    BindingRef(
                        target_name=cls_name,
                        file_path=file_path,
                        line=lineno,
                        scope=active_sym,
                        expr_kind="REACT_USES_STYLE_CLASS",
                        source_expr=active_sym or file_path,
                        base_expr=style_bindings[mod_obj],
                        attr_name=cls_name,
                    )
                )

        # Plain className strings: className="btn-primary active"
        for m_cls in _CLASSNAME_LITERAL.finditer(line):
            classes_str = m_cls.group(1)
            for single_cls in classes_str.split():
                clean_cls = single_cls.strip()
                if clean_cls and not clean_cls.startswith("{"):
                    bindings.append(
                        BindingRef(
                            target_name=clean_cls,
                            file_path=file_path,
                            line=lineno,
                            scope=active_sym,
                            expr_kind="REACT_USES_STYLE_CLASS",
                            source_expr=active_sym or file_path,
                            base_expr="CLASSNAME",
                        )
                    )

    # 4. Extract TypeScript interfaces and types for cross-language contract verification
    if file_path.endswith((".ts", ".tsx")):
        for m_iface in _TS_INTERFACE_DEF.finditer(content):
            iface_name = m_iface.group(1)
            raw_body = m_iface.group(2)
            clean_body = re.sub(r"/\*.*?\*/", "", raw_body, flags=re.DOTALL)
            clean_body = re.sub(r"//.*$", "", clean_body, flags=re.MULTILINE)
            fields: list[tuple[str, str]] = []
            for f in _TS_FIELD_DEF.finditer(clean_body):
                fname = f.group(1).strip()
                is_opt = bool(f.group(2))
                ftype = f.group(3).strip().rstrip(";,").strip()
                fields.append((fname, f"{ftype}?" if is_opt else ftype))
            if fields:
                start_line = content[: m_iface.start()].count("\n") + 1
                bindings.append(
                    BindingRef(
                        target_name=iface_name,
                        file_path=file_path,
                        line=start_line,
                        scope="",
                        expr_kind="TS_INTERFACE",
                        source_expr=iface_name,
                        dict_entries=tuple(fields),
                    )
                )

    return ReactAnalysisResult(

        components=tuple(components),
        hooks=tuple(hooks),
        bindings=tuple(bindings),
        renders=tuple(renders),
        hook_calls=tuple(hook_calls),
    )
