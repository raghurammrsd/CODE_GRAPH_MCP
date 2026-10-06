"""Deterministic HTML, Jinja2, and Web Template Parser.

Extracts:
1. DOM elements with IDs or semantic anchors into Symbol records.
2. Inline JavaScript event handlers (onclick="fn()", @click="fn") into CallRef and Symbol records.
3. Form submission actions (<form action="/api/..." method="POST">) into BindingRef records.
4. Script tag imports (<script src="...">) and stylesheet links into ImportRef records.
5. Embedded <script> JavaScript blocks parsed with exact file line offsets.
6. Jinja/Django/EJS template directives ({% block %}, {% extends %}, {% include %}).
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

from codegraph.indexing.models import (
    BindingRef,
    CallRef,
    ImportRef,
    InheritanceRef,
    Symbol,
    normalize_module,
)
from codegraph.indexing.parser import PARSER_VERSION, ParseResult, _parse_js_ts

# Regex for extracting JS function calls in inline handlers like:
# onclick="quickToggleStock(123)", onsubmit="return handleForm(this, event)"
_JS_CALL_PATTERN = re.compile(r"\b([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(")

# Regex for Jinja2 / Django / EJS template directives
_JINJA_EXTENDS = re.compile(r"""\{%\s*extends\s+['"]([^'"]+)['"]\s*%\}""")
_JINJA_INCLUDE = re.compile(r"""\{%\s*include\s+['"]([^'"]+)['"]\s*%\}""")
_JINJA_BLOCK = re.compile(r"""\{%\s*block\s+([a-zA-Z0-9_]+)\s*%\}""")
_JINJA_URL_FOR = re.compile(r"""\{\{\s*url_for\s*\(\s*['"]([^'"]+)['"]""")
_DJANGO_URL = re.compile(r"""\{%\s*url\s+['"]([^'"]+)['"]""")

# HTMX HTTP request attribute mappings
_HTMX_VERBS = {
    "hx-get": "GET",
    "hx-post": "POST",
    "hx-put": "PUT",
    "hx-delete": "DELETE",
    "hx-patch": "PATCH",
    "data-hx-get": "GET",
    "data-hx-post": "POST",
    "data-hx-put": "PUT",
    "data-hx-delete": "DELETE",
    "data-hx-patch": "PATCH",
}


class _TemplateHTMLParser(HTMLParser):
    def __init__(self, file_path: str, module_name: str) -> None:
        super().__init__()
        self.file_path = file_path
        self.module_name = module_name
        self.symbols: list[Symbol] = []
        self.calls: list[CallRef] = []
        self.imports: list[ImportRef] = []
        self.bindings: list[BindingRef] = []
        self.script_blocks: list[tuple[int, str]] = []  # (start_line, content)
        self._in_script = False
        self._script_start_line = 1
        self._script_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line_num, _ = self.getpos()
        attr_dict: dict[str, str] = {k.lower(): (v or "") for k, v in attrs if k}

        if tag.lower() == "script":
            src = attr_dict.get("src")
            if src:
                self.imports.append(
                    ImportRef(
                        source_file=self.file_path,
                        module=src,
                        line=line_num,
                        import_type="script_src",
                    )
                )
            else:
                self._in_script = True
                self._script_start_line = line_num
                self._script_buf = []

        if tag.lower() == "link" and attr_dict.get("rel") == "stylesheet":
            href = attr_dict.get("href")
            if href:
                self.imports.append(
                    ImportRef(
                        source_file=self.file_path,
                        module=href,
                        line=line_num,
                        import_type="stylesheet",
                    )
                )

        # 1. DOM Elements with ID
        elem_id = attr_dict.get("id")
        if elem_id:
            sym_name = elem_id.strip()
            self.symbols.append(
                Symbol(
                    name=sym_name,
                    qualified_name=f"{tag}#{sym_name}",
                    kind="html_element",
                    language="html",
                    file_path=self.file_path,
                    start_line=line_num,
                    end_line=line_num,
                    scope=tag,
                )
            )

        # 2. Inline JavaScript / Alpine.js Event Handlers (onclick, onsubmit, @click, x-on:click, x-init, etc.)
        for attr_k, attr_v in attr_dict.items():
            is_handler = (
                attr_k.startswith("on")
                or attr_k.startswith("@")
                or attr_k.startswith("v-on:")
                or attr_k.startswith("x-on:")
                or attr_k in ("x-init", "x-effect")
                or (attr_k.startswith("(") and attr_k.endswith(")"))
            )
            if not is_handler or not attr_v:
                continue

            if attr_k.startswith(("@", "x-on:", "x-data", "x-init", "x-show")):
                caller_label = f"{tag}#{elem_id}" if elem_id else tag
                self.bindings.append(
                    BindingRef(
                        target_name=attr_k,
                        file_path=self.file_path,
                        line=line_num,
                        expr_kind="ALPINE_EVENT",
                        source_expr=attr_v,
                        base_expr=caller_label,
                    )
                )

            matches = _JS_CALL_PATTERN.findall(attr_v)
            found_fns: list[str] = list(matches)

            # If attribute value is a bare identifier / method reference (e.g. @click="handleClick" or onclick="handleClick")
            val_clean = attr_v.strip()
            if not found_fns and re.match(r"^[a-zA-Z_$][a-zA-Z0-9_$]*(?:\.[a-zA-Z_$][a-zA-Z0-9_$]*)?$", val_clean):
                found_fns.append(val_clean.split(".")[-1])

            for fn_name in found_fns:
                if fn_name in ("return", "if", "for", "while", "this"):
                    continue

                caller_label = f"{tag}#{elem_id}" if elem_id else tag
                self.calls.append(
                    CallRef(
                        callee=fn_name,
                        source_file=self.file_path,
                        line=line_num,
                        end_line=line_num,
                        caller_symbol=caller_label,
                        caller_canonical_id=f"{self.module_name}.{caller_label}",
                        confidence="HIGH",
                    )
                )

                self.symbols.append(
                    Symbol(
                        name=fn_name,
                        qualified_name=f"{caller_label}[{attr_k}]->{fn_name}",
                        kind="event_handler",
                        language="html",
                        file_path=self.file_path,
                        start_line=line_num,
                        end_line=line_num,
                        scope=caller_label,
                    )
                )

        # 3. Form submissions (<form action="..." method="...">)
        if tag.lower() == "form":
            action = attr_dict.get("action", "").strip()
            method = attr_dict.get("method", "GET").strip().upper()
            if action:
                self.bindings.append(
                    BindingRef(
                        target_name=action,
                        file_path=self.file_path,
                        line=line_num,
                        expr_kind="HTML_FORM_ACTION",
                        base_expr=method,
                    )
                )

        # 4. Modern Python Stack: HTMX attributes (hx-get, hx-post, hx-delete, hx-put, hx-patch, etc.)
        for hx_attr, http_method in _HTMX_VERBS.items():
            if hx_attr in attr_dict and attr_dict[hx_attr]:
                raw_endpoint = attr_dict[hx_attr].strip()
                caller_label = f"{tag}#{elem_id}" if elem_id else tag
                target_sel = attr_dict.get("hx-target") or attr_dict.get("data-hx-target") or ""
                trigger = attr_dict.get("hx-trigger") or attr_dict.get("data-hx-trigger") or ""
                swap = attr_dict.get("hx-swap") or attr_dict.get("data-hx-swap") or ""

                resolved_endpoint = raw_endpoint
                m_django = _DJANGO_URL.search(raw_endpoint)
                if m_django:
                    resolved_endpoint = m_django.group(1)
                else:
                    m_jinja = _JINJA_URL_FOR.search(raw_endpoint)
                    if m_jinja:
                        resolved_endpoint = m_jinja.group(1)

                meta_entries = (
                    ("target", target_sel),
                    ("trigger", trigger),
                    ("swap", swap),
                    ("element", tag),
                    ("element_id", elem_id or ""),
                    ("raw_url", raw_endpoint),
                )

                self.bindings.append(
                    BindingRef(
                        target_name=resolved_endpoint,
                        file_path=self.file_path,
                        line=line_num,
                        expr_kind="HTMX_REQUEST",
                        base_expr=http_method,
                        source_expr=target_sel,
                        attr_name=trigger,
                        dict_entries=meta_entries,
                    )
                )

                self.calls.append(
                    CallRef(
                        callee=resolved_endpoint,
                        qualified_callee=f"{http_method} {resolved_endpoint}",
                        source_file=self.file_path,
                        line=line_num,
                        end_line=line_num,
                        caller_symbol=caller_label,
                        caller_canonical_id=f"{self.module_name}.{caller_label}",
                        confidence="HIGH",
                    )
                )

                self.symbols.append(
                    Symbol(
                        name=resolved_endpoint,
                        qualified_name=f"{caller_label}[{hx_attr}]->{http_method} {resolved_endpoint}",
                        kind="htmx_action",
                        language="html",
                        file_path=self.file_path,
                        start_line=line_num,
                        end_line=line_num,
                        scope=caller_label,
                    )
                )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self._in_script = False
            content = "".join(self._script_buf)
            if content.strip():
                self.script_blocks.append((self._script_start_line, content))
            self._script_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buf.append(data)


def parse_html_template(content: str, file_path: str) -> ParseResult:
    """Parse an HTML or web template file in a single deterministic pass."""
    source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    module_name = normalize_module(file_path, "html")

    parser = _TemplateHTMLParser(file_path=file_path, module_name=module_name)
    try:
        parser.feed(content)
    except Exception as e:
        return ParseResult(
            path=file_path,
            language="html",
            parser_version=PARSER_VERSION,
            source_hash=source_hash,
            parse_failed=True,
            parse_error=f"HTML parse error: {e}",
        )

    symbols = list(parser.symbols)
    calls = list(parser.calls)
    imports = list(parser.imports)
    inheritance: list[InheritanceRef] = []
    bindings = list(parser.bindings)

    # 4. Parse Jinja / Django directives line-by-line
    lines = content.splitlines()
    for idx, line in enumerate(lines, 1):
        # {% extends "base.html" %}
        ext_match = _JINJA_EXTENDS.search(line)
        if ext_match:
            inheritance.append(
                InheritanceRef(
                    source_symbol=module_name,
                    base_name=ext_match.group(1),
                    relationship="EXTENDS",
                    source_file=file_path,
                    line=idx,
                )
            )

        # {% include "nav.html" %}
        inc_match = _JINJA_INCLUDE.search(line)
        if inc_match:
            imports.append(
                ImportRef(
                    source_file=file_path,
                    module=inc_match.group(1),
                    line=idx,
                    import_type="template_include",
                )
            )

        # {% block content %}
        blk_match = _JINJA_BLOCK.search(line)
        if blk_match:
            blk_name = blk_match.group(1)
            symbols.append(
                Symbol(
                    name=blk_name,
                    qualified_name=f"block#{blk_name}",
                    kind="template_block",
                    language="html",
                    file_path=file_path,
                    start_line=idx,
                    end_line=idx,
                    scope=module_name,
                )
            )

        # {{ url_for('user_bp.checkout') }}
        url_match = _JINJA_URL_FOR.search(line)
        if url_match:
            target_endpoint = url_match.group(1)
            calls.append(
                CallRef(
                    callee=target_endpoint,
                    source_file=file_path,
                    line=idx,
                    end_line=idx,
                    caller_symbol=module_name,
                    caller_canonical_id=module_name,
                    confidence="HIGH",
                )
            )

    # 5. Parse embedded <script> tags with JS parser
    for start_line, script_code in parser.script_blocks:
        try:
            js_res = _parse_js_ts(script_code, "javascript", file_path)
            # Offset line numbers by start_line - 1
            line_offset = max(0, start_line - 1)
            for s in js_res.symbols:
                adj_start = s.start_line + line_offset
                adj_end = s.end_line + line_offset
                symbols.append(
                    Symbol(
                        name=s.name,
                        qualified_name=s.qualified_name,
                        kind=s.kind,
                        language="javascript",
                        file_path=file_path,
                        start_line=adj_start,
                        end_line=adj_end,
                        signature=s.signature,
                        scope=s.scope,
                    )
                )
            for c in js_res.calls:
                calls.append(
                    CallRef(
                        callee=c.callee,
                        source_file=file_path,
                        line=c.line + line_offset,
                        end_line=c.end_line + line_offset,
                        caller_symbol=c.caller_symbol,
                        caller_canonical_id=c.caller_canonical_id,
                        confidence=c.confidence,
                    )
                )
            for imp in js_res.imports:
                imports.append(
                    ImportRef(
                        source_file=file_path,
                        module=imp.module,
                        name=imp.name,
                        line=imp.line + line_offset,
                        import_type=imp.import_type,
                    )
                )
        except Exception:
            # Tolerant fallback if inline script cannot be parsed
            pass

    return ParseResult(
        path=file_path,
        language="html",
        parser_version=PARSER_VERSION,
        source_hash=source_hash,
        symbols=tuple(symbols),
        imports=tuple(imports),
        calls=tuple(calls),
        inheritance=tuple(inheritance),
        bindings=tuple(bindings),
        parse_failed=False,
    )
