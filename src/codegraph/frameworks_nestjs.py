"""Deterministic NestJS framework and dependency injection analyzer.

Inspects TypeScript/JavaScript classes for:
- @Controller('prefix') class decorators and HTTP method decorators (@Get, @Post, @Put, @Delete, @Patch, @Options, @Head, @All).
- Constructor dependency injection: typed parameters (e.g. `private readonly service: InvoicesService`)
  and @Inject('TOKEN') / @Inject(TokenClass) parameter decorators.
- @Module({ controllers: [...], providers: [...], imports: [...] }) module declarations.

Emits:
- RouteDetection records for HTTP endpoints.
- BindingRef records with expr_kind='NESTJS_INJECTS' (for DI) and expr_kind='NESTJS_CONTROLLER' / 'DI_PROVIDES'.
- RouterMountDetection records for module-controller wiring.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from codegraph.frameworks import (
    RouteDetection,
    RouterMountDetection,
    join_route_prefixes,
    normalize_route_path,
)
from codegraph.indexing.models import BindingRef, build_canonical_id

_NESTJS_HTTP_METHODS: dict[str, str] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
    "all": "ANY",
}

_TS_PRIMITIVE_TYPES = frozenset({
    "string",
    "number",
    "boolean",
    "any",
    "void",
    "unknown",
    "object",
    "never",
    "null",
    "undefined",
    "symbol",
    "bigint",
    "function",
    "record",
    "array",
    "promise",
})

# Matches @Controller('path') or @Controller()
_CONTROLLER_DEC_RE = re.compile(
    r"@Controller\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)"
)

# Matches @Module({ ... })
_MODULE_DEC_RE = re.compile(r"@Module\s*\(")

# Matches @Injectable()
_INJECTABLE_DEC_RE = re.compile(r"@Injectable\s*\(")

# Matches @Get('path'), @Post(), etc.
_METHOD_DEC_RE = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Options|Head|All)\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)",
    re.IGNORECASE,
)

# Matches class declaration
_CLASS_DECL_RE = re.compile(
    r"\b(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
)

# Matches method declaration inside class
_METHOD_DECL_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\("
)

# Matches constructor declaration
_CONSTRUCTOR_START_RE = re.compile(r"\bconstructor\s*\(")

# Matches @Inject('TOKEN') or @Inject(TOKEN) inside constructor param
_INJECT_PARAM_DEC_RE = re.compile(
    r"@Inject\s*\(\s*(?:['\"`]([^'\"`]*)['\"`]|([A-Za-z_$][\w$]*))\s*\)"
)


@dataclass
class NestjsAnalysisResult:
    routes: list[RouteDetection] = field(default_factory=list)
    mounts: list[RouterMountDetection] = field(default_factory=list)
    bindings: list[BindingRef] = field(default_factory=list)


def _split_constructor_params(params_text: str) -> list[str]:
    """Split comma-separated constructor parameters respecting nested generics, parens, brackets, braces."""
    params: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    depth_angle = 0
    in_quote = False
    quote_char = ""

    for ch in params_text:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
            continue
        if ch in ('"', "'", "`"):
            in_quote = True
            quote_char = ch
            current.append(ch)
            continue

        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket = max(0, depth_bracket - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
        elif ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)

        if (
            ch == ","
            and depth_paren == 0
            and depth_bracket == 0
            and depth_brace == 0
            and depth_angle == 0
        ):
            p = "".join(current).strip()
            if p:
                params.append(p)
            current = []
        else:
            current.append(ch)

    p = "".join(current).strip()
    if p:
        params.append(p)
    return params


def _extract_module_array(body: str, key: str) -> list[str]:
    """Extract list of identifiers or objects from a @Module({ key: [...] }) configuration."""
    m = re.search(rf"\b{key}\s*:\s*\[([\s\S]*?)\]", body)
    if not m:
        return []
    items_raw = m.group(1)
    results: list[str] = []
    tokens: list[str] = []
    current: list[str] = []
    brace_depth = 0
    for ch in items_raw:
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        if ch == "," and brace_depth == 0:
            item = "".join(current).strip()
            if item:
                tokens.append(item)
            current = []
        else:
            current.append(ch)
    item = "".join(current).strip()
    if item:
        tokens.append(item)

    for clean in tokens:
        clean = re.sub(r"//.*$", "", clean).strip()
        if not clean or clean.startswith("{"):
            continue
        ident_m = re.match(r"^([A-Za-z_$][\w$]*)", clean)
        if ident_m:
            results.append(ident_m.group(1))
    return results


def _extract_custom_providers(body: str) -> list[tuple[str, str]]:
    """Extract { provide: 'TOKEN' | Type, useClass: Impl } custom providers."""
    providers: list[tuple[str, str]] = []
    for m in re.finditer(r"\{\s*provide\s*:\s*(['\"`]?[\w$]+['\"`]?)\s*,\s*useClass\s*:\s*([A-Za-z_$][\w$]*)\s*,?\s*\}", body, re.DOTALL):
        token = m.group(1).strip("'\"`")
        use_class = m.group(2)
        if token and use_class:
            providers.append((token, use_class))
    return providers


def analyze_nestjs_file(
    content: str,
    file_path: str,
    module: str,
) -> NestjsAnalysisResult:
    """Analyze a TypeScript/JavaScript file for NestJS controllers, routes, modules, and constructor DI."""
    res = NestjsAnalysisResult()

    if "@" not in content:
        return res

    lines = content.splitlines()
    total_lines = len(lines)

    # 1. Parse @Module definitions
    for mod_m in _MODULE_DEC_RE.finditer(content):
        start_idx = mod_m.start()
        line_no = content[:start_idx].count("\n") + 1
        # Extract the object literal argument for @Module({ ... })
        brace_start = content.find("{", start_idx)
        if brace_start != -1:
            depth = 1
            idx = brace_start + 1
            while idx < len(content) and depth > 0:
                if content[idx] == "{":
                    depth += 1
                elif content[idx] == "}":
                    depth -= 1
                idx += 1
            mod_body = content[brace_start + 1 : idx - 1]

            # Find following class name
            post_content = content[idx:]
            cls_m = _CLASS_DECL_RE.search(post_content)
            mod_class = cls_m.group(1) if cls_m else "AppModule"
            mod_canon = build_canonical_id(module, "", mod_class)

            # Controllers
            controllers = _extract_module_array(mod_body, "controllers")
            for ctrl in controllers:
                res.bindings.append(
                    BindingRef(
                        target_name=mod_canon,
                        source_expr=ctrl,
                        file_path=file_path,
                        line=line_no,
                        scope=mod_class,
                        expr_kind="NESTJS_CONTROLLER",
                        base_expr="nestjs_module",
                        attr_name="controller",
                    )
                )

            # Class providers
            class_providers = _extract_module_array(mod_body, "providers")
            for prov in class_providers:
                res.bindings.append(
                    BindingRef(
                        target_name=mod_canon,
                        source_expr=prov,
                        file_path=file_path,
                        line=line_no,
                        scope=mod_class,
                        expr_kind="DI_PROVIDES",
                        base_expr="nestjs_module",
                        attr_name="provider",
                    )
                )

            # Custom providers
            custom_providers = _extract_custom_providers(mod_body)
            for token, use_class in custom_providers:
                res.bindings.append(
                    BindingRef(
                        target_name=token,
                        source_expr=use_class,
                        file_path=file_path,
                        line=line_no,
                        scope=mod_class,
                        expr_kind="DI_PROVIDES",
                        base_expr="nestjs_provider",
                        attr_name="useClass",
                        subscript_key=json.dumps({"token": token, "provider": use_class}),
                    )
                )
                res.bindings.append(
                    BindingRef(
                        target_name=mod_canon,
                        source_expr=use_class,
                        file_path=file_path,
                        line=line_no,
                        scope=mod_class,
                        expr_kind="DI_PROVIDES",
                        base_expr="nestjs_module",
                        attr_name="custom_provider",
                    )
                )

    # 2. Parse Classes, Controllers, Route Methods, and Constructor DI
    i = 0
    pending_class_decorators: list[tuple[str, str, int]] = []  # (decorator_name, arg, line_no)

    while i < total_lines:
        line = lines[i]
        stripped = line.strip()

        # Check for class-level decorators
        ctrl_m = _CONTROLLER_DEC_RE.search(stripped)
        if ctrl_m:
            prefix = ctrl_m.group(1) or ""
            pending_class_decorators.append(("Controller", prefix, i + 1))
            i += 1
            continue

        if _INJECTABLE_DEC_RE.search(stripped):
            pending_class_decorators.append(("Injectable", "", i + 1))
            i += 1
            continue

        # Check for class declaration
        class_m = _CLASS_DECL_RE.search(stripped)
        if class_m:
            class_name = class_m.group(1)
            class_canon = build_canonical_id(module, "", class_name)

            # Determine if this class is a Controller
            is_controller = False
            controller_prefix = ""
            for dec_name, dec_arg, _ in pending_class_decorators:
                if dec_name == "Controller":
                    is_controller = True
                    controller_prefix = dec_arg
                    break

            pending_class_decorators.clear()

            # Now scan inside the class body for methods, decorators, and constructor
            # Find class closing brace
            class_depth = line.count("{") - line.count("}")
            j = i + 1
            pending_method_decorators: list[tuple[str, str, int]] = []

            while j < total_lines and class_depth > 0:
                inner_line = lines[j]
                inner_stripped = inner_line.strip()
                class_depth += inner_line.count("{") - inner_line.count("}")

                # Method decorators: @Get, @Post, etc.
                method_dec_m = _METHOD_DEC_RE.search(inner_stripped)
                if method_dec_m:
                    m_http = method_dec_m.group(1).lower()
                    m_path = method_dec_m.group(2) or ""
                    pending_method_decorators.append((m_http, m_path, j + 1))
                    j += 1
                    continue

                # Constructor declaration
                if _CONSTRUCTOR_START_RE.search(inner_stripped):
                    const_line = j + 1
                    # Collect constructor parameter block up to matching ')'
                    paren_depth = inner_line.count("(") - inner_line.count(")")
                    const_lines = [inner_line]
                    k = j + 1
                    while k < total_lines and paren_depth > 0:
                        const_lines.append(lines[k])
                        paren_depth += lines[k].count("(") - lines[k].count(")")
                        k += 1

                    full_const_sig = " ".join(c_line.strip() for c_line in const_lines)
                    start_paren = full_const_sig.find("(")
                    if start_paren != -1:
                        p_depth = 1
                        idx_c = start_paren + 1
                        while idx_c < len(full_const_sig) and p_depth > 0:
                            if full_const_sig[idx_c] == "(":
                                p_depth += 1
                            elif full_const_sig[idx_c] == ")":
                                p_depth -= 1
                            idx_c += 1
                        raw_params = full_const_sig[start_paren + 1 : idx_c - 1].strip()
                        if raw_params:
                            params = _split_constructor_params(raw_params)
                            for param_str in params:
                                # Check for @Inject('TOKEN') or @Inject(TOKEN)
                                inject_m = _INJECT_PARAM_DEC_RE.search(param_str)
                                inject_token = (
                                    inject_m.group(1) or inject_m.group(2)
                                    if inject_m
                                    else None
                                )

                                # Clean out decorators and access modifiers to extract param_name: Type
                                clean_p = _INJECT_PARAM_DEC_RE.sub("", param_str).strip()
                                clean_p = re.sub(
                                    r"\b(private|public|protected|readonly)\b",
                                    "",
                                    clean_p,
                                ).strip()

                                # Match name: Type
                                name_type_m = re.match(
                                    r"^([A-Za-z_$][\w$]*)\s*(?:\??\s*:\s*([^=,]+))?",
                                    clean_p,
                                )
                                if name_type_m:
                                    p_name = name_type_m.group(1)
                                    p_type_raw = name_type_m.group(2)
                                    p_type = p_type_raw.strip().split("<")[0].strip() if p_type_raw else ""

                                    if inject_token:
                                        res.bindings.append(
                                            BindingRef(
                                                target_name=class_canon,
                                                source_expr=inject_token,
                                                file_path=file_path,
                                                line=const_line,
                                                scope=class_name,
                                                expr_kind="NESTJS_INJECTS",
                                                base_expr="nestjs_inject",
                                                attr_name=p_name,
                                                subscript_key=json.dumps({
                                                    "param": p_name,
                                                    "type": p_type,
                                                    "token": inject_token,
                                                }),
                                            )
                                        )
                                    elif p_type and p_type.lower() not in _TS_PRIMITIVE_TYPES:
                                        res.bindings.append(
                                            BindingRef(
                                                target_name=class_canon,
                                                source_expr=p_type,
                                                file_path=file_path,
                                                line=const_line,
                                                scope=class_name,
                                                expr_kind="NESTJS_INJECTS",
                                                base_expr="nestjs",
                                                attr_name=p_name,
                                                subscript_key=json.dumps({
                                                    "param": p_name,
                                                    "type": p_type,
                                                }),
                                            )
                                        )
                    j = k
                    continue

                # Method declaration inside controller
                meth_m = _METHOD_DECL_RE.match(inner_stripped)
                if meth_m and is_controller:
                    method_name = meth_m.group(1)

                    if method_name not in ("constructor", "if", "for", "while", "switch"):
                        for http_m_raw, path_arg, dec_line in pending_method_decorators:
                            method_upper = _NESTJS_HTTP_METHODS.get(http_m_raw.lower(), "GET")
                            full_route = join_route_prefixes(controller_prefix, path_arg)
                            norm_route = normalize_route_path(full_route, "nestjs")
                            handler_canon = f"{module}.{class_name}.{method_name}"

                            res.routes.append(
                                RouteDetection(
                                    framework="nestjs",
                                    http_method=method_upper,
                                    route_path=full_route,
                                    normalized_route=norm_route,
                                    handler_name=method_name,
                                    handler_canonical_id=handler_canon,
                                    file_path=file_path,
                                    line=dec_line,
                                    confidence="HIGH",
                                    resolution_status="RESOLVED",
                                    evidence=f"NestJS @{http_m_raw.capitalize()}('{path_arg}') on {class_name}.{method_name}",
                                    module=module,
                                    router_name=class_name,
                                )
                            )

                    pending_method_decorators.clear()

                elif not inner_stripped.startswith("@"):
                    if not inner_stripped.startswith("//") and inner_stripped:
                        pending_method_decorators.clear()

                j += 1

            i = j
            continue

        # Non-decorator, non-blank statement outside class clears pending decorators
        if not stripped.startswith("@") and not stripped.startswith("//") and stripped:
            pending_class_decorators.clear()

        i += 1

    return res
