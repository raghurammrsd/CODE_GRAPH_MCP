"""Integration tests for CSS, SCSS, and CSS Modules Intelligence (Pillar 4).

Validates:
- CSS class selector and variable extraction (.btn-primary, --primary-color)
- IMPORTS_STYLE edges linking components to stylesheets
- USES_STYLE_CLASS edges linking components to CSS classes
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.styles import parse_style_file


def test_parse_style_file():
    css_content = """
:root {
  --primary-color: #0070f3;
  --spacing-md: 16px;
}

.btn-primary {
  background: var(--primary-color);
  padding: var(--spacing-md);
}

.btn-primary:hover {
  opacity: 0.9;
}

.invoice-card {
  border: 1px solid #ccc;
}
"""
    res = parse_style_file(css_content, "src/styles.css")
    class_names = {c.name for c in res.classes}
    assert "btn-primary" in class_names
    assert "invoice-card" in class_names

    var_names = {v.name for v in res.variables}
    assert "--primary-color" in var_names
    assert "--spacing-md" in var_names


def test_component_style_linkage():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Stylesheet
        (src / "Button.module.css").write_text("""
.btnBase {
  border-radius: 4px;
}

.btnActive {
  background-color: blue;
}
""")

        # 2. Component importing stylesheet
        (src / "Button.tsx").write_text("""
import React from 'react';
import styles from './Button.module.css';

export function Button({ active }: { active: boolean }) {
  return (
    <button className={styles.btnBase}>
      Click
    </button>
  );
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # Check IMPORTS_STYLE edge: Button.tsx -> Button.module.css
            style_edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'IMPORTS_STYLE'"
            ).fetchall()
            assert any("Button" in e["source"] and "Button.module.css" in e["target"] for e in style_edges)

            # Check USES_STYLE_CLASS edge: Button -> .btnBase
            class_edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'USES_STYLE_CLASS'"
            ).fetchall()
            assert any("Button" in e["source"] and ".btnBase" in e["target"] for e in class_edges)
