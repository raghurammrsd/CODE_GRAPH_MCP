"""CSS, SCSS, and CSS Modules Architecture and Selector Analyzer (Pillar 4).

Extracts deterministic facts from stylesheets:
- CSS class selectors (.btn-primary, .invoice-card, .header_title)
- CSS custom properties/variables (--primary-color, --spacing-md)
- CSS module boundaries
- Emits Symbol entities for style search and cross-component impact analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from codegraph.indexing.models import Symbol

# CSS Class Selector pattern: .className { or .className:hover or .className.active
# Excludes decimals like .5s, .75em, .0
_CSS_CLASS_RE = re.compile(
    r"""(?<![\w\.\-])\.([A-Za-z_][A-Za-z0-9_-]*)(?=[ \t\r\n\.:,\{>+~])"""
)

# CSS Custom Property / Variable declaration: --primary-color: #0070f3;
_CSS_VAR_RE = re.compile(
    r"""(--[A-Za-z_][A-Za-z0-9_-]*)\s*:"""
)

# Hex color detector to ignore #fff, #123456 as ID selectors
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass(frozen=True)
class CssClassDef:
    name: str
    file_path: str
    line: int
    is_module: bool


@dataclass(frozen=True)
class CssVariableDef:
    name: str
    file_path: str
    line: int


@dataclass(frozen=True)
class StyleFileResult:
    classes: tuple[CssClassDef, ...] = ()
    variables: tuple[CssVariableDef, ...] = ()
    symbols: tuple[Symbol, ...] = ()


def is_style_file(file_path: str) -> bool:
    """Check if file is a CSS, SCSS, Sass, or Less stylesheet."""
    lower = file_path.lower()
    return lower.endswith((".css", ".scss", ".sass", ".less"))


def parse_style_file(content: str, file_path: str) -> StyleFileResult:
    """Extract CSS classes, custom properties, and symbols from stylesheet."""
    if not is_style_file(file_path):
        return StyleFileResult()

    is_module = ".module." in file_path.lower()
    classes: list[CssClassDef] = []
    variables: list[CssVariableDef] = []
    symbols: list[Symbol] = []

    seen_classes: set[str] = set()
    seen_vars: set[str] = set()

    clean_file = file_path.replace("\\", "/").lstrip("./")

    for idx, line in enumerate(content.splitlines()):
        lineno = idx + 1
        stripped = line.strip()

        # Skip comment-only lines
        if stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//"):
            continue

        # Extract CSS variables
        for m_var in _CSS_VAR_RE.finditer(line):
            v_name = m_var.group(1)
            if v_name not in seen_vars:
                seen_vars.add(v_name)
                variables.append(CssVariableDef(name=v_name, file_path=clean_file, line=lineno))
                canon_id = f"{clean_file}::{v_name}"
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=v_name,
                        qualified_name=v_name,
                        kind="style_var",
                        language="css",
                        module=clean_file,
                        path=clean_file,
                        file_path=clean_file,
                        scope="",
                        start_line=lineno,
                        end_line=lineno,
                    )
                )

        # Extract CSS classes
        for m_cls in _CSS_CLASS_RE.finditer(line):
            c_name = m_cls.group(1)
            # Avoid pseudo-elements and animations
            if c_name in ("hover", "focus", "active", "visited", "disabled", "first-child", "last-child"):
                continue
            if c_name not in seen_classes:
                seen_classes.add(c_name)
                classes.append(
                    CssClassDef(
                        name=c_name,
                        file_path=clean_file,
                        line=lineno,
                        is_module=is_module,
                    )
                )
                canon_id = f"{clean_file}::{c_name}"
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=f".{c_name}",
                        qualified_name=f".{c_name}",
                        kind="style_class",
                        language="css",
                        module=clean_file,
                        path=clean_file,
                        file_path=clean_file,
                        scope="",
                        start_line=lineno,
                        end_line=lineno,
                    )
                )

    return StyleFileResult(
        classes=tuple(classes),
        variables=tuple(variables),
        symbols=tuple(symbols),
    )
