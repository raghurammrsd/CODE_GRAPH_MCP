"""Integration tests for HTML Templates and Asset Links (Pillar 4).

Validates:
- Script inclusions (<script src="..."> -> LOADS_SCRIPT)
- Stylesheet links (<link rel="stylesheet" href="..."> -> LOADS_STYLESHEET)
- DOM root mount points (<div id="root">)
"""
from __future__ import annotations

from codegraph.frontend_html import parse_html_file


def test_html_asset_links_and_mounts():
    html_content = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="stylesheet" href="/src/index.css" />
    <title>App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""
    res = parse_html_file(html_content, "index.html")

    # Check script inclusions (<script src="..."> -> HTML_LOADS_SCRIPT)
    script_bindings = [b for b in res.bindings if b.expr_kind == "HTML_LOADS_SCRIPT"]
    assert any("main.tsx" in b.target_name for b in script_bindings)

    # Check stylesheet links (<link rel="stylesheet" href="..."> -> HTML_LOADS_STYLESHEET)
    style_bindings = [b for b in res.bindings if b.expr_kind == "HTML_LOADS_STYLESHEET"]
    assert any("index.css" in b.target_name for b in style_bindings)

    # Check DOM element symbols: #root
    assert any(s.name == "#root" and s.kind == "dom_element" for s in res.symbols)
