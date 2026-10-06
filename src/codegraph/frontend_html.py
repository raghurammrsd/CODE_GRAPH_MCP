"""HTML Template and Web Asset Linkage Analyzer (Pillar 4).

Extracts deterministic facts from HTML documents:
- Script bundle inclusions (<script src="..."> -> LOADS_SCRIPT)
- Stylesheet links (<link rel="stylesheet" href="..."> -> LOADS_STYLESHEET)
- DOM mount containers (<div id="root">, <div id="app">)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from codegraph.indexing.models import BindingRef, Symbol

_SCRIPT_SRC_RE = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

_LINK_STYLESHEET_RE = re.compile(
    r"""<link\b[^>]*\bhref\s*=\s*['"]([^'"]+)['"][^>]*\brel\s*=\s*['"]stylesheet['"]|<link\b[^>]*\brel\s*=\s*['"]stylesheet['"][^>]*\bhref\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

_ELEMENT_ID_RE = re.compile(
    r"""<([A-Za-z0-9_-]+)\b[^>]*\bid\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HtmlParseResult:
    symbols: tuple[Symbol, ...] = ()
    bindings: tuple[BindingRef, ...] = ()


def is_html_file(file_path: str) -> bool:
    """Check if file is an HTML document or template."""
    lower = file_path.lower()
    return lower.endswith((".html", ".htm"))


def parse_html_file(content: str, file_path: str) -> HtmlParseResult:
    """Extract script, stylesheet, and DOM mount container references from HTML."""
    if not is_html_file(file_path):
        return HtmlParseResult()

    clean_file = file_path.replace("\\", "/").lstrip("./")
    symbols: list[Symbol] = []
    bindings: list[BindingRef] = []

    for idx, line in enumerate(content.splitlines()):
        lineno = idx + 1

        # <script src="...">
        for m_script in _SCRIPT_SRC_RE.finditer(line):
            src_val = m_script.group(1).lstrip("/")
            bindings.append(
                BindingRef(
                    target_name=src_val,
                    file_path=clean_file,
                    line=lineno,
                    scope="",
                    expr_kind="HTML_LOADS_SCRIPT",
                    source_expr=clean_file,
                    base_expr="LOADS_SCRIPT",
                )
            )

        # <link rel="stylesheet" href="...">
        for m_link in _LINK_STYLESHEET_RE.finditer(line):
            href_val = (m_link.group(1) or m_link.group(2)).lstrip("/")
            bindings.append(
                BindingRef(
                    target_name=href_val,
                    file_path=clean_file,
                    line=lineno,
                    scope="",
                    expr_kind="HTML_LOADS_STYLESHEET",
                    source_expr=clean_file,
                    base_expr="LOADS_STYLESHEET",
                )
            )

        # <div id="...">
        for m_elem in _ELEMENT_ID_RE.finditer(line):
            elem_id = m_elem.group(2)
            canon_id = f"{clean_file}#{elem_id}"
            symbols.append(
                Symbol(
                    id=canon_id,
                    canonical_id=canon_id,
                    name=f"#{elem_id}",
                    qualified_name=f"#{elem_id}",
                    kind="dom_element",
                    language="html",
                    module=clean_file,
                    path=clean_file,
                    file_path=clean_file,
                    scope="",
                    start_line=lineno,
                    end_line=lineno,
                )
            )

    return HtmlParseResult(
        symbols=tuple(symbols),
        bindings=tuple(bindings),
    )
