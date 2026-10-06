"""Integration tests for TypeScript Path Aliases (tsconfig.json / jsconfig.json) (Pillar 4).

Validates:
- baseUrl and paths mapping (@/* -> src/*)
- JSON comment stripping (// and /* */)
- Cross-file import and call resolution across path aliases
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.tsconfig import TsConfigResolver, strip_json_comments


def test_strip_json_comments():
    raw = """{
  // Compiler options for project
  "compilerOptions": {
    /* Base URL */
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"], // alias for src
    },
  },
}"""
    cleaned = strip_json_comments(raw)
    assert "Compiler options" not in cleaned
    assert "Base URL" not in cleaned
    assert "alias for src" not in cleaned
    assert '"@/*": ["src/*"]' in cleaned


def test_tsconfig_path_aliases_resolver():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)
        comps = src / "components"
        comps.mkdir(parents=True, exist_ok=True)

        # 1. tsconfig.json with comments and trailing commas
        (repo / "tsconfig.json").write_text("""{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "~components/*": ["src/components/*"],
    },
  },
}""")

        # 2. Target components
        (comps / "Button.tsx").write_text("""
export function Button() {
  return <button>Click</button>;
}
""")

        (comps / "Header.tsx").write_text("""
export function Header() {
  return <header>Title</header>;
}
""")

        # 3. Consumer using @/ and ~components/ path aliases
        (src / "App.tsx").write_text("""
import { Button } from "@/components/Button";
import { Header } from "~components/Header";

export function App() {
  return (
    <div>
      <Header />
      <Button />
    </div>
  );
}
""")

        # Test TsConfigResolver directly
        resolver = TsConfigResolver.load_from_repo(repo)
        known_files = {"src/components/Button.tsx", "src/components/Header.tsx", "src/App.tsx"}
        resolved_btn = resolver.resolve_alias("@/components/Button", "src/App.tsx", known_files)
        assert resolved_btn == "src/components/Button.tsx"

        resolved_hdr = resolver.resolve_alias("~components/Header", "src/App.tsx", known_files)
        assert resolved_hdr == "src/components/Header.tsx"

        # Test full indexer integration
        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # Check resolved imports targeting the real files
            imports = con.execute("SELECT imported_module, resolved_path FROM imports WHERE source_path = 'src/App.tsx'").fetchall()
            resolved_paths = {i["resolved_path"] for i in imports}
            assert "src/components/Button.tsx" in resolved_paths
            assert "src/components/Header.tsx" in resolved_paths

            # Check RENDERS edges: App -> Header and App -> Button
            edges = con.execute("SELECT source, target, relationship FROM graph_edges WHERE relationship = 'RENDERS'").fetchall()
            render_pairs = {(e["source"], e["target"]) for e in edges}
            assert any("App" in s and "Header" in t for s, t in render_pairs)
            assert any("App" in s and "Button" in t for s, t in render_pairs)
