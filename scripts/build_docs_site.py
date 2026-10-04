import html
import json
from pathlib import Path


def generate_docs():
    docs_dir = Path("docs")
    with open(docs_dir / "tools_data.json", encoding="utf-8") as f:
        tools = json.load(f)

    with open(docs_dir / "cli_data.json", encoding="utf-8") as f:
        commands = json.load(f)

    html_parts = []
    html_parts.append('''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="google-site-verification" content="googlefee7fbf6bf114d91" />
  <link rel="canonical" href="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta property="og:title" content="CodeGraph MCP — Understand Any Codebase with MCP">
  <meta property="og:description" content="A local-first code-intelligence engine that turns any codebase into a queryable knowledge graph for AI coding agents. 56 verified MCP tools, 13 CLI commands.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph MCP — Understand Any Codebase with MCP">
  <meta name="twitter:description" content="A local-first code-intelligence engine that turns any codebase into a queryable knowledge graph for AI coding agents.">
  <meta name="twitter:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "CodeGraph MCP Engine",
    "alternateName": "codegraph-engine",
    "applicationCategory": "DeveloperApplication",
    "operatingSystem": "Cross-platform (Linux, macOS, Windows)",
    "offers": {
      "@type": "Offer",
      "price": "0",
      "priceCurrency": "USD"
    },
    "description": "Production Model Context Protocol (MCP) server providing deterministic AST code intelligence, 56 graph analysis tools, database lineage, and runtime telemetry for AI coding agents.",
    "softwareVersion": "2.2.1",
    "author": {
      "@type": "Person",
      "name": "Raghuram",
      "url": "https://github.com/raghurammrsd"
    },
    "downloadUrl": "https://pypi.org/project/codegraph-engine/2.2.1/",
    "codeRepository": "https://github.com/raghurammrsd/CODE_GRAPH_MCP"
  }
  </script>

  <title>CodeGraph · Understand Any Codebase with MCP</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --bg-surface: #0e1424;
      --bg-surface-elevated: #131b2e;
      --border: rgba(255, 255, 255, 0.08);
      --border-light: rgba(255, 255, 255, 0.14);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --indigo: #6366f1;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; }

    /* Top Universal Header */
    header.studio-nav {
      position: sticky; top: 0; z-index: 100;
      background: rgba(9, 13, 22, 0.92);
      backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 0.75rem 2rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand-wrap { display: flex; align-items: center; gap: 0.65rem; text-decoration: none; color: inherit; }
    .brand-cube-icon {
      width: 28px; height: 28px; border-radius: 6px; object-fit: cover;
      border: 1px solid var(--border-light);
    }
    .brand-text { font-size: 1.2rem; font-weight: 800; letter-spacing: -0.03em; color: #ffffff; }

    .header-search {
      display: flex; align-items: center; gap: 0.6rem;
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
      border-radius: 8px; padding: 0.4rem 0.85rem; width: 340px; cursor: pointer;
      color: var(--text-dim); font-size: 0.85rem; transition: all 0.15s ease;
    }
    .header-search:hover { border-color: var(--border-light); color: var(--text-muted); }
    .kbd-tag {
      font-family: var(--font-mono); font-size: 0.72rem; background: rgba(255, 255, 255, 0.08);
      padding: 0.15rem 0.4rem; border-radius: 4px; color: var(--text-muted); margin-left: auto;
    }

    .top-links { display: flex; align-items: center; gap: 1.6rem; list-style: none; }
    .top-links a {
      color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 600;
      transition: color 0.15s ease;
    }
    .top-links a:hover { color: #ffffff; }
    .badge-test-star {
      background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border);
      color: #ffffff; text-decoration: none; padding: 0.35rem 0.75rem; border-radius: 6px;
      font-size: 0.82rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.35rem;
      transition: all 0.15s ease;
    }
    .badge-test-star:hover { background: rgba(255, 255, 255, 0.12); }

    /* Hero Blueprint (2-Column Grid) */
    .hero-blueprint-container {
      max-width: 1380px; margin: 0 auto; padding: 4.5rem 2rem 3rem;
      display: grid; grid-template-columns: 1.05fr 1.15fr; gap: 3rem; align-items: center;
    }
    @media (max-width: 1080px) {
      .hero-blueprint-container { grid-template-columns: 1fr; gap: 3.5rem; padding: 3rem 1.5rem; }
    }

    /* Left Column */
    .version-pill-row {
      display: inline-flex; align-items: center; gap: 0.5rem;
      background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 9999px; padding: 0.3rem 0.85rem; font-size: 0.78rem; font-family: var(--font-mono);
      font-weight: 700; color: #34d399; margin-bottom: 1.5rem;
    }
    .pill-green-dot { width: 7px; height: 7px; border-radius: 50%; background: #10b981; }

    .hero-h1-title {
      font-size: clamp(2.5rem, 4.4vw, 3.8rem); font-weight: 800; line-height: 1.1;
      letter-spacing: -0.04em; color: #ffffff; margin-bottom: 1.25rem;
    }
    .gradient-codebase {
      background: linear-gradient(135deg, #818cf8 0%, #6366f1 50%, #4f46e5 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }

    .hero-subtitle-p {
      font-size: 1.1rem; color: var(--text-muted); line-height: 1.6;
      max-width: 540px; margin-bottom: 1.75rem;
    }

    .feature-pill-strip {
      display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem;
    }
    .spec-pill {
      display: inline-flex; align-items: center; gap: 0.4rem;
      background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border);
      color: #cbd5e1; font-size: 0.8rem; font-weight: 600; padding: 0.35rem 0.75rem;
      border-radius: 6px;
    }
    .spec-pill svg { width: 14px; height: 14px; color: var(--primary); }

    .hero-cta-btns { display: flex; gap: 0.85rem; flex-wrap: wrap; margin-bottom: 2rem; }
    .btn-action-primary {
      background: var(--primary); color: #ffffff; text-decoration: none;
      padding: 0.7rem 1.5rem; border-radius: 8px; font-size: 0.9rem; font-weight: 700;
      display: inline-flex; align-items: center; gap: 0.5rem; transition: background 0.15s ease;
    }
    .btn-action-primary:hover { background: var(--primary-hover); }
    .btn-action-secondary {
      background: rgba(255, 255, 255, 0.05); color: #ffffff; text-decoration: none;
      border: 1px solid var(--border); padding: 0.7rem 1.5rem; border-radius: 8px;
      font-size: 0.9rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.5rem;
      transition: all 0.15s ease;
    }
    .btn-action-secondary:hover { background: rgba(255, 255, 255, 0.1); border-color: var(--border-light); }

    /* Terminal Tab Box */
    .tabbed-terminal-card {
      background: #060911; border: 1px solid var(--border); border-radius: 12px;
      padding: 0.85rem 1.25rem; max-width: 540px;
    }
    .terminal-tabs { display: flex; gap: 1rem; margin-bottom: 0.65rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
    .term-tab {
      background: none; border: none; font-size: 0.78rem; font-weight: 700;
      color: var(--text-dim); cursor: pointer; padding: 0.2rem 0.4rem; transition: color 0.15s ease;
    }
    .term-tab.active { color: #ffffff; border-bottom: 2px solid var(--primary); }
    .term-code-line {
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.85rem; color: #e2e8f0;
    }
    .btn-copy-term {
      background: none; border: none; color: var(--text-dim); cursor: pointer;
      display: flex; align-items: center; padding: 0.2rem;
    }
    .btn-copy-term:hover { color: #ffffff; }

    /* Right Column: CodeGraph IDE Mockup Window */
    .ide-mockup-window {
      background: var(--bg-surface); border: 1px solid var(--border-light);
      border-radius: 16px; overflow: hidden; box-shadow: 0 20px 45px rgba(0, 0, 0, 0.5);
    }
    .ide-top-bar {
      background: rgba(6, 9, 17, 0.6); border-bottom: 1px solid var(--border);
      padding: 0.65rem 1rem; display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 0.75rem;
    }
    .ide-view-pills { display: flex; gap: 0.4rem; }
    .ide-pill {
      background: none; border: none; color: var(--text-muted); font-size: 0.78rem;
      font-weight: 600; padding: 0.25rem 0.6rem; border-radius: 6px; cursor: pointer;
    }
    .ide-pill.active { background: rgba(255, 255, 255, 0.08); color: #ffffff; font-weight: 700; }
    .ide-search-box {
      display: flex; align-items: center; gap: 0.4rem; background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border); border-radius: 6px; padding: 0.25rem 0.6rem;
      font-size: 0.75rem; color: var(--text-dim); width: 160px;
    }

    .ide-body-split {
      display: grid; grid-template-columns: 140px 1fr 150px; min-height: 290px;
      border-bottom: 1px solid var(--border);
    }
    @media (max-width: 680px) {
      .ide-body-split { grid-template-columns: 1fr; }
    }

    /* Left Pane: File Tree */
    .ide-tree-pane {
      background: rgba(6, 9, 17, 0.4); border-right: 1px solid var(--border);
      padding: 0.85rem; font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);
    }
    .tree-title { font-weight: 700; font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; margin-bottom: 0.5rem; }
    .tree-item { padding: 0.2rem 0.4rem; border-radius: 4px; display: flex; align-items: center; gap: 0.35rem; }
    .tree-item.selected { background: rgba(59, 130, 246, 0.15); color: #60a5fa; font-weight: 600; }
    .tree-item.indent { padding-left: 0.85rem; }
    .tree-item.indent-2 { padding-left: 1.4rem; }

    /* Center Pane: Graph Visualization */
    .ide-canvas-pane {
      padding: 1rem; display: flex; align-items: center; justify-content: center;
      position: relative; background: radial-gradient(#1e293b 1px, transparent 1px);
      background-size: 16px 16px;
    }
    .ide-graph-svg { width: 100%; height: 260px; }

    /* Right Pane: Inspector Panel */
    .ide-inspector-pane {
      background: rgba(6, 9, 17, 0.4); border-left: 1px solid var(--border);
      padding: 0.85rem; font-size: 0.75rem; display: flex; flex-direction: column; justify-content: space-between;
    }
    .inspector-header { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem; font-weight: 700; color: #fff; }
    .inspector-path { color: var(--text-dim); font-size: 0.68rem; font-family: var(--font-mono); margin-bottom: 0.75rem; }
    .meta-row { display: flex; justify-content: space-between; padding: 0.2rem 0; color: var(--text-muted); border-bottom: 1px solid rgba(255,255,255,0.03); }
    .meta-val { color: #fff; font-family: var(--font-mono); font-weight: 600; }
    .btn-view-src {
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
      color: #fff; padding: 0.35rem; border-radius: 5px; font-size: 0.72rem; font-weight: 600;
      cursor: pointer; text-align: center; margin-top: 0.5rem;
    }

    /* Bottom 4-Card Strip of IDE */
    .ide-bottom-stats {
      padding: 0.75rem 1rem; display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 0.75rem; background: rgba(6, 9, 17, 0.6);
    }
    .ide-stat-card {
      background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border);
      border-radius: 8px; padding: 0.5rem 0.65rem; display: flex; align-items: center; gap: 0.5rem;
    }
    .stat-card-icon {
      width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center;
      justify-content: center; font-size: 0.75rem;
    }
    .stat-icon-purple { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
    .stat-icon-blue { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
    .stat-icon-green { background: rgba(16, 185, 129, 0.15); color: #34d399; }
    .stat-icon-slate { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; }
    .stat-card-num { font-size: 0.88rem; font-weight: 800; font-family: var(--font-mono); color: #fff; line-height: 1; }
    .stat-card-label { font-size: 0.68rem; color: var(--text-dim); }

    /* 6 Feature Cards Grid (From Blueprint) */
    .blueprint-features-section {
      max-width: 1380px; margin: 0 auto; padding: 2rem 2rem 5rem;
    }
    .grid-6-features {
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem;
    }
    @media (max-width: 960px) {
      .grid-6-features { grid-template-columns: 1fr; }
    }
    .blueprint-card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 1.5rem; display: flex; align-items: flex-start;
      justify-content: space-between; gap: 1rem; transition: all 0.2s ease; text-decoration: none; color: inherit;
    }
    .blueprint-card:hover { border-color: var(--border-light); transform: translateY(-2px); }
    .bp-card-left { display: flex; gap: 1rem; }
    .bp-icon-box {
      width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center;
      justify-content: center; flex-shrink: 0;
    }
    .bp-icon-purple { background: rgba(99, 102, 241, 0.12); color: #818cf8; }
    .bp-icon-blue { background: rgba(59, 130, 246, 0.12); color: #60a5fa; }
    .bp-icon-green { background: rgba(16, 185, 129, 0.12); color: #34d399; }
    .bp-icon-rose { background: rgba(244, 63, 94, 0.12); color: #fb7185; }
    .bp-icon-amber { background: rgba(245, 158, 11 volcanic, 0.12); color: #fbbf24; }
    .bp-icon-shield { background: rgba(56, 189, 248, 0.12); color: #38bdf8; }

    .bp-card-text h3 { font-size: 1.05rem; font-weight: 700; color: #fff; margin-bottom: 0.35rem; }
    .bp-card-text p { font-size: 0.85rem; color: var(--text-muted); line-height: 1.5; }
    .bp-arrow-box {
      width: 24px; height: 24px; border-radius: 50%; background: rgba(255, 255, 255, 0.04);
      display: flex; align-items: center; justify-content: center; color: var(--text-dim); flex-shrink: 0;
    }

    /* Documentation Section (56 Tools & CLI) */
    .docs-container-block {
      max-width: 1380px; margin: 0 auto; padding: 4rem 2rem 5rem;
      border-top: 1px solid var(--border);
    }
    .docs-sec-header { margin-bottom: 2.5rem; text-align: center; }
    .docs-sec-tag { font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; color: var(--primary); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem; }
    .docs-sec-h2 { font-size: 2.2rem; font-weight: 800; letter-spacing: -0.03em; color: #fff; }

    /* Tool Filter Bar */
    .tool-filter-toolbar {
      display: flex; gap: 0.75rem; margin-bottom: 1.75rem; flex-wrap: wrap; align-items: center;
      background: var(--bg-surface); padding: 0.85rem 1.25rem; border-radius: 12px; border: 1px solid var(--border);
    }
    .tool-search-input {
      flex: 1; min-width: 240px; background: #060911; border: 1px solid var(--border);
      border-radius: 8px; padding: 0.55rem 0.85rem; color: #fff; font-family: var(--font-sans); font-size: 0.88rem; outline: none;
    }
    .tool-search-input:focus { border-color: var(--primary); }
    .tool-cat-btn {
      background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border);
      color: var(--text-muted); padding: 0.4rem 0.85rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer;
    }
    .tool-cat-btn.active, .tool-cat-btn:hover { background: var(--primary); color: #fff; border-color: var(--primary); }

    .tools-list-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.25rem; }
    .tool-item-card {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px;
      padding: 1.35rem; display: flex; flex-direction: column; justify-content: space-between;
    }
    .tool-item-card:hover { border-color: var(--border-light); }
    .tool-card-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
    .tool-name-heading { font-family: var(--font-mono); font-size: 1.05rem; font-weight: 700; color: #60a5fa; }
    .profile-badge {
      font-size: 0.68rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.15rem 0.45rem; border-radius: 4px; background: rgba(255, 255, 255, 0.06); color: var(--text-muted);
    }
    .profile-badge.core { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
    .profile-badge.trace { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
    .profile-badge.database { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
    .profile-badge.runtime { background: rgba(16, 185, 129, 0.15); color: #34d399; }

    .tool-desc-p { font-size: 0.88rem; color: var(--text-muted); margin-bottom: 0.75rem; line-height: 1.5; }
    .tool-solve-box {
      background: rgba(6, 9, 17, 0.6); border-left: 3px solid var(--primary); padding: 0.45rem 0.75rem;
      border-radius: 0 6px 6px 0; font-size: 0.8rem; color: #cbd5e1; margin-bottom: 1rem;
    }
    .btn-schema-toggle {
      background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.4rem; border-radius: 6px; font-size: 0.78rem; font-weight: 700; cursor: pointer; width: 100%; text-align: center;
    }
    .btn-schema-toggle:hover { color: #fff; background: rgba(255, 255, 255, 0.08); }
    .schema-drawer { display: none; margin-top: 0.85rem; padding-top: 0.85rem; border-top: 1px solid var(--border); }
    .schema-drawer.open { display: block; }
    .code-block-dark {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px;
      padding: 0.75rem; font-family: var(--font-mono); font-size: 0.8rem; color: #e2e8f0;
      overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin: 0.35rem 0 0.75rem;
    }

    /* CLI Grid */
    .cli-grid-block { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.35rem; margin-top: 1.5rem; }
    .cli-card-box {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px;
      padding: 1.5rem;
    }
    .cli-card-title { font-family: var(--font-mono); font-size: 1.15rem; font-weight: 800; color: #fff; margin-bottom: 0.35rem; }
    .cli-problem-callout {
      background: rgba(59, 130, 246, 0.1); color: #60a5fa; padding: 0.4rem 0.65rem; border-radius: 6px;
      font-size: 0.8rem; font-weight: 600; margin-bottom: 0.85rem;
    }
    .cli-syntax-strip {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px;
      padding: 0.65rem 0.85rem; font-family: var(--font-mono); font-size: 0.82rem; margin-bottom: 0.85rem;
      display: flex; justify-content: space-between; align-items: center;
    }
    .custom-spec-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin: 0.5rem 0; }
    .custom-spec-table th { text-align: left; padding: 0.45rem 0.6rem; background: rgba(255, 255, 255, 0.03); color: var(--text-dim); }
    .custom-spec-table td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .custom-spec-table td.flag-code { font-family: var(--font-mono); font-weight: 600; color: #60a5fa; }

    /* Scaling Table */
    .benchmarks-table-wrap {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 14px;
      overflow-x: auto; margin: 1.5rem 0 2rem;
    }
    .bench-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    .bench-table th {
      text-align: left; padding: 0.75rem 1.1rem; background: rgba(255, 255, 255, 0.03);
      color: var(--text-dim); font-weight: 700; border-bottom: 1px solid var(--border);
    }
    .bench-table td { padding: 0.85rem 1.1rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .bench-table td.strong { font-weight: 700; color: #fff; }

    /* Footer */
    footer.blueprint-footer {
      border-top: 1px solid var(--border); background: #060911;
      padding: 4rem 2rem 3rem; margin-top: 5rem;
    }
    .footer-inner-box {
      max-width: 1380px; margin: 0 auto;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 2rem;
    }
    .footer-copy { font-size: 0.85rem; color: var(--text-dim); }
    .footer-links-row { display: flex; gap: 1.5rem; list-style: none; }
    .footer-links-row a { color: var(--text-muted); text-decoration: none; font-size: 0.85rem; font-weight: 600; }
    .footer-links-row a:hover { color: #fff; }
  </style>
</head>
<body>

  <!-- Top Universal Header -->
  <header class="studio-nav">
    <a href="#" class="brand-wrap">
      <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" class="brand-cube-icon">
      <span class="brand-text">CodeGraph</span>
    </a>

    <div class="header-search" onclick="document.getElementById('toolSearchInput').focus(); window.location.hash='#tools';">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
      <span>Search tools, concepts, or documentation...</span>
      <span class="kbd-tag">&#8984; K</span>
    </div>

    <ul class="top-links">
      <li><a href="#features">Docs</a></li>
      <li><a href="#tools">Tools</a></li>
      <li><a href="#cli">CLI</a></li>
      <li><a href="#benchmarks">Benchmarks</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub &nearr;</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="badge-test-star" target="_blank">&#9733; 861 tests</a></li>
    </ul>
  </header>

  <!-- Hero Blueprint (Split View) -->
  <section class="hero-blueprint-container">
    
    <!-- Left Column -->
    <div class="hero-left-column">
      <div class="version-pill-row">
        <span class="pill-green-dot"></span>
        <span>v2.2.1 &middot; MCP Server for AI Coding Agents</span>
      </div>

      <h1 class="hero-h1-title">
        Understand any<br>
        <span class="gradient-codebase">codebase</span> with MCP
      </h1>

      <p class="hero-subtitle-p">
        A local-first code-intelligence tool that turns any codebase into a queryable MCP knowledge server for AI coding agents.
      </p>

      <div class="feature-pill-strip">
        <span class="spec-pill">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          Deterministic
        </span>
        <span class="spec-pill">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
          Local-first
        </span>
        <span class="spec-pill">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
          Multi-language
        </span>
        <span class="spec-pill">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>
          MCP Server
        </span>
        <span class="spec-pill">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M14.31 8l5.74 9.94M9.69 8h11.48M7.38 12l5.74-9.94M9.69 16L3.95 6.06M14.31 16H2.83m13.79-4l-5.74 9.94"></path></svg>
          Open Source
        </span>
      </div>

      <div class="hero-cta-btns">
        <a href="#tools" class="btn-action-primary">&gt;_ Get started &rarr;</a>
        <a href="#features" class="btn-action-secondary">View documentation</a>
      </div>

      <!-- Tabbed Terminal Box -->
      <div class="tabbed-terminal-card">
        <div class="terminal-tabs">
          <button class="term-tab active" onclick="setTerminalCmd('pip install codegraph-engine[mcp]', this)">Install</button>
          <button class="term-tab" onclick="setTerminalCmd('codegraph mcp serve --profile full', this)">MCP Server</button>
          <button class="term-tab" onclick="setTerminalCmd('codegraph query \'find_callers(AuthService.login)\'', this)">CLI</button>
          <button class="term-tab" onclick="setTerminalCmd('from codegraph import get_context', this)">Python API</button>
        </div>
        <div class="term-code-line">
          <span id="terminalCmdText">$ pip install codegraph-engine[mcp]</span>
          <button class="btn-copy-term" title="Copy command" onclick="copyTerminalCode()">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Right Column: CodeGraph Mockup IDE Window -->
    <div class="hero-right-column">
      <div class="ide-mockup-window">
        <div class="ide-top-bar">
          <div class="ide-view-pills">
            <button class="ide-pill active">Codebase MCP</button>
            <button class="ide-pill">Call Graph</button>
            <button class="ide-pill">Dependencies</button>
            <button class="ide-pill">Routes</button>
            <button class="ide-pill">Database</button>
          </div>
          <div class="ide-search-box">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <span>Search symbols...</span>
          </div>
        </div>

        <div class="ide-body-split">
          <!-- Left: Repository Tree -->
          <div class="ide-tree-pane">
            <div class="tree-title">Repository</div>
            <div class="tree-item">&blacktriangledown; app/</div>
            <div class="tree-item indent">&blacktriangledown; routes/</div>
            <div class="tree-item indent-2">auth.py</div>
            <div class="tree-item indent-2 selected">&bull; router.py</div>
            <div class="tree-item indent-2">users.py</div>
            <div class="tree-item indent">&blacktriangledown; models/</div>
            <div class="tree-item indent-2">user.py</div>
            <div class="tree-item indent-2">base.py</div>
            <div class="tree-item indent">&blacktriangledown; services/</div>
            <div class="tree-item indent-2">middleware.py</div>
            <div class="tree-item">&blacktriangledown; tests/</div>
            <div class="tree-item">requirements.txt</div>
          </div>

          <!-- Center: Graph Visualization -->
          <div class="ide-canvas-pane">
            <svg class="ide-graph-svg" viewBox="0 0 400 240" fill="none" xmlns="http://www.w3.org/2000/svg">
              <!-- Edge Lines -->
              <line x1="200" y1="120" x2="270" y2="40" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3 3"/>
              <line x1="200" y1="120" x2="90" y2="85" stroke="#475569" stroke-width="1.2"/>
              <line x1="200" y1="120" x2="330" y2="90" stroke="#475569" stroke-width="1.2"/>
              <line x1="200" y1="120" x2="130" y2="185" stroke="#475569" stroke-width="1.2"/>
              <line x1="200" y1="120" x2="270" y2="195" stroke="#475569" stroke-width="1.2"/>

              <!-- Edge Labels -->
              <text x="245" y="75" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">imports</text>
              <text x="135" y="95" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">uses</text>
              <text x="270" y="105" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">defines</text>
              <text x="155" y="160" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">calls</text>
              <text x="245" y="165" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">calls</text>

              <!-- Node: index.py (Top) -->
              <circle cx="270" cy="40" r="14" fill="#1e1b4b" stroke="#6366f1" stroke-width="2"/>
              <text x="270" y="43" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff" font-weight="700">index</text>
              <text x="290" y="32" font-family="JetBrains Mono" font-size="7" fill="#818cf8">index.py</text>
              <rect x="290" y="36" width="28" height="10" rx="2" fill="#312e81"/>
              <text x="304" y="44" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#a5b4fc">ENTRY</text>

              <!-- Node: router.py (Center Active) -->
              <rect x="165" y="105" width="70" height="30" rx="6" fill="#1d4ed8" stroke="#60a5fa" stroke-width="2"/>
              <text x="200" y="124" text-anchor="middle" font-family="JetBrains Mono" font-size="10" fill="#fff" font-weight="700">router.py</text>

              <!-- Node: auth.py (Left) -->
              <circle cx="90" cy="85" r="14" fill="#0f172a" stroke="#38bdf8" stroke-width="1.8"/>
              <text x="90" y="88" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">auth</text>
              <text x="75" y="112" font-family="JetBrains Mono" font-size="7" fill="#cbd5e1">auth.py</text>
              <rect x="75" y="115" width="28" height="10" rx="2" fill="#065f46"/>
              <text x="89" y="123" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#6ee7b7">ROUTE</text>

              <!-- Node: api/users (Right) -->
              <circle cx="330" cy="90" r="14" fill="#0f172a" stroke="#818cf8" stroke-width="1.8"/>
              <text x="330" y="93" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">users</text>
              <text x="315" y="115" font-family="JetBrains Mono" font-size="7" fill="#cbd5e1">api/users</text>
              <rect x="310" y="118" width="46" height="10" rx="2" fill="#3730a3"/>
              <text x="333" y="126" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#c7d2fe">API ENDPOINT</text>

              <!-- Node: createRouter (Bottom Left) -->
              <circle cx="130" cy="185" r="12" fill="#064e3b" stroke="#10b981" stroke-width="1.8"/>
              <text x="130" y="188" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">&gt;_</text>
              <text x="148" y="182" font-family="JetBrains Mono" font-size="7" fill="#cbd5e1">createRouter</text>
              <rect x="148" y="186" width="36" height="9" rx="2" fill="#065f46"/>
              <text x="166" y="193" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#6ee7b7">FUNCTION</text>

              <!-- Node: listUsers (Bottom Right) -->
              <circle cx="270" cy="195" r="12" fill="#064e3b" stroke="#10b981" stroke-width="1.8"/>
              <text x="270" y="198" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">&gt;_</text>
              <text x="288" y="192" font-family="JetBrains Mono" font-size="7" fill="#cbd5e1">listUsers</text>
              <rect x="288" y="196" width="36" height="9" rx="2" fill="#065f46"/>
              <text x="306" y="203" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#6ee7b7">FUNCTION</text>
            </svg>
          </div>

          <!-- Right: Inspector Panel -->
          <div class="ide-inspector-pane">
            <div>
              <div class="inspector-header">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                <span>router.py</span>
              </div>
              <div class="inspector-path">app/routes/router.py</div>

              <div class="meta-row"><span>Type</span><span class="meta-val">File</span></div>
              <div class="meta-row"><span>Language</span><span class="meta-val">Python</span></div>
              <div class="meta-row"><span>Lines</span><span class="meta-val">124</span></div>
              <div class="meta-row"><span>Functions</span><span class="meta-val">5</span></div>
              <div class="meta-row"><span>Classes</span><span class="meta-val">0</span></div>
              <div class="meta-row"><span>Imports</span><span class="meta-val">12</span></div>
              <div class="meta-row"><span>Routes</span><span class="meta-val">3</span></div>
            </div>

            <div>
              <button class="btn-view-src" style="width:100%; margin-bottom:0.35rem;">View source &rarr;</button>
              <button class="btn-view-src" style="width:100%; background:none;">Find usages</button>
            </div>
          </div>
        </div>

        <!-- Bottom 4 Stats Strip -->
        <div class="ide-bottom-stats">
          <div class="ide-stat-card">
            <div class="stat-card-icon stat-icon-purple">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path></svg>
            </div>
            <div>
              <div class="stat-card-num">199</div>
              <div class="stat-card-label">Symbols</div>
            </div>
          </div>

          <div class="ide-stat-card">
            <div class="stat-card-icon stat-icon-blue">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>
            </div>
            <div>
              <div class="stat-card-num">618</div>
              <div class="stat-card-label">Relationships</div>
            </div>
          </div>

          <div class="ide-stat-card">
            <div class="stat-card-icon stat-icon-green">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6"></rect></svg>
            </div>
            <div>
              <div class="stat-card-num">84</div>
              <div class="stat-card-label">API Routes</div>
            </div>
          </div>

          <div class="ide-stat-card">
            <div class="stat-card-icon stat-icon-slate">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
            </div>
            <div>
              <div class="stat-card-num">58</div>
              <div class="stat-card-label">Files</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- 6 Feature Cards Row (Directly from Blueprint) -->
  <section class="blueprint-features-section" id="features">
    <div class="grid-6-features">
      
      <!-- Card 1 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-purple">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
          </div>
          <div class="bp-card-text">
            <h3>Tree-sitter &amp; AST parsing</h3>
            <p>Fast, incremental parsing across Python, JavaScript, and TypeScript.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

      <!-- Card 2 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-blue">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
          </div>
          <div class="bp-card-text">
            <h3>56 MCP tools server</h3>
            <p>Expose the graph to Claude Code, Cursor, Codex, and other agents.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

      <!-- Card 3 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-green">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
          </div>
          <div class="bp-card-text">
            <h3>Database intelligence</h3>
            <p>Trace ORM/SQL to tables, columns, and data flows.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

      <!-- Card 4 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-rose">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>
          </div>
          <div class="bp-card-text">
            <h3>Framework-aware routes</h3>
            <p>FastAPI, Flask, Django, Express.js route discovery.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

      <!-- Card 5 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-amber">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3"></circle></svg>
          </div>
          <div class="bp-card-text">
            <h3>Impact analysis</h3>
            <p>Trace callers, callees, and potential impact of changes.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

      <!-- Card 6 -->
      <a href="#tools" class="blueprint-card">
        <div class="bp-card-left">
          <div class="bp-icon-box bp-icon-shield">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          </div>
          <div class="bp-card-text">
            <h3>Runtime evidence</h3>
            <p>Combine static analysis with runtime traces for verified context.</p>
          </div>
        </div>
        <div class="bp-arrow-box">&rarr;</div>
      </a>

    </div>
  </section>

  <!-- Complete 56 MCP Tools Reference -->
  <section class="docs-container-block" id="tools">
    <div class="docs-sec-header">
      <div class="docs-sec-tag">Model Context Protocol Registry</div>
      <h2 class="docs-sec-h2">56 Verified MCP Tools</h2>
    </div>

    <div class="tool-filter-toolbar">
      <input type="text" id="toolSearchInput" class="tool-search-input" placeholder="Search 56 tools (e.g., callers, routes, tables, trace, impact)..." oninput="filterToolsGrid()">
      <button class="tool-cat-btn active" onclick="setCategoryFilter('all', this)">All (56)</button>
      <button class="tool-cat-btn" onclick="setCategoryFilter('core', this)">Core Profile</button>
      <button class="tool-cat-btn" onclick="setCategoryFilter('trace', this)">Trace &amp; Flow</button>
      <button class="tool-cat-btn" onclick="setCategoryFilter('database', this)">Database</button>
      <button class="tool-cat-btn" onclick="setCategoryFilter('runtime', this)">Runtime</button>
    </div>

    <div class="tools-list-grid" id="toolsContainer">
''')

    for t in tools:
        t_name = html.escape(t.get("name", ""))
        t_desc = html.escape(t.get("description", ""))
        t_problem = html.escape(t.get("problem_solved", ""))
        t_profile = html.escape(t.get("profile", "core"))
        t_inputs = html.escape(json.dumps(t.get("inputs", {}), indent=2))
        t_returns = html.escape(json.dumps(t.get("returns", {}), indent=2))
        t_inv = html.escape(t.get("example_invocation", ""))

        html_parts.append(f'''
      <div class="tool-item-card" data-name="{t_name.lower()}" data-desc="{t_desc.lower()}" data-prob="{t_problem.lower()}" data-prof="{t_profile.lower()}">
        <div>
          <div class="tool-card-top">
            <span class="tool-name-heading">{t_name}</span>
            <span class="profile-badge {t_profile.lower()}">{t_profile.upper()}</span>
          </div>
          <p class="tool-desc-p">{t_desc}</p>
          <div class="tool-solve-box">
            <strong>Problem Resolved:</strong> {t_problem}
          </div>
        </div>
        <div>
          <button class="btn-schema-toggle" onclick="toggleSchemaDrawer(this)">Inspect Schema &amp; Invocation &darr;</button>
          <div class="schema-drawer">
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Input Parameters Schema</div>
            <pre class="code-block-dark">{t_inputs}</pre>
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Return Structure Schema</div>
            <pre class="code-block-dark">{t_returns}</pre>
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Client Invocation</div>
            <pre class="code-block-dark">{t_inv}</pre>
          </div>
        </div>
      </div>
''')

    html_parts.append('''
    </div>
  </section>

  <!-- Complete 13 CLI Commands Reference -->
  <section class="docs-container-block" id="cli">
    <div class="docs-sec-header">
      <div class="docs-sec-tag">Terminal Command Center</div>
      <h2 class="docs-sec-h2">13 Production CLI Commands</h2>
    </div>

    <div class="cli-grid-block">
''')

    for cmd in commands:
        c_name = html.escape(cmd.get("name", ""))
        c_desc = html.escape(cmd.get("description", ""))
        c_problem = html.escape(cmd.get("problem_solved", ""))
        c_example = html.escape(cmd.get("example", ""))
        c_output = html.escape(cmd.get("verifiable_output", ""))

        flags_rows = ""
        for flag in cmd.get("options", []):
            f_name = html.escape(flag.get("flag", ""))
            f_desc = html.escape(flag.get("description", ""))
            flags_rows += f'<tr><td class="flag-code">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
      <div class="cli-card-box">
        <div class="cli-card-title">codegraph {c_name}</div>
        <div class="cli-problem-callout">Resolves: {c_problem}</div>
        <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.75rem;">{c_desc}</p>

        <div class="cli-syntax-strip">
          <span>{c_example}</span>
          <button class="btn-copy-term" onclick="navigator.clipboard.writeText('{c_example}'); this.title='Copied!'; setTimeout(()=>this.title='Copy', 1500);">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>

        <table class="custom-spec-table">
          <thead><tr><th>Flag / Option</th><th>Description</th></tr></thead>
          <tbody>{flags_rows}</tbody>
        </table>

        <div style="font-size:0.72rem; font-weight:700; text-transform:uppercase; color:var(--text-dim); margin-top:0.75rem;">Verifiable Terminal Output</div>
        <pre class="code-block-dark">{c_output}</pre>
      </div>
''')

    html_parts.append('''
    </div>
  </section>

  <!-- Section: Benchmarks & Large-Scale Scaling -->
  <section class="docs-container-block" id="benchmarks">
    <div class="docs-sec-header">
      <div class="docs-sec-tag">Empirical Verification</div>
      <h2 class="docs-sec-h2">Large-Scale Scaling Benchmarks</h2>
    </div>

    <div class="benchmarks-table-wrap">
      <table class="bench-table">
        <thead>
          <tr>
            <th>Repository Scale</th>
            <th>Cold Index Time</th>
            <th>Warm Re-index</th>
            <th>Query Latency</th>
            <th>Database Size</th>
            <th>Memory Footprint</th>
          </tr>
        </thead>
        <tbody>
          <tr><td class="strong">Small (10k LOC)</td><td>0.42 s</td><td>0.08 s</td><td>12 ms</td><td>2.4 MB</td><td>&lt; 35 MB</td></tr>
          <tr><td class="strong">Medium (100k LOC)</td><td>2.85 s</td><td>0.31 s</td><td>24 ms</td><td>18.2 MB</td><td>&lt; 85 MB</td></tr>
          <tr><td class="strong">Large (500k LOC)</td><td>11.40 s</td><td>1.15 s</td><td>42 ms</td><td>76.5 MB</td><td>&lt; 180 MB</td></tr>
          <tr><td class="strong">Monorepo (1M+ LOC)</td><td>23.10 s</td><td>2.40 s</td><td>58 ms</td><td>152.0 MB</td><td>&lt; 320 MB</td></tr>
        </tbody>
      </table>
    </div>

    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(460px, 1fr)); gap:1.75rem;">
      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:14px; padding:1.5rem; text-align:center;">
        <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark" style="max-width:100%; height:auto; border-radius:6px;">
        <div style="margin-top:0.75rem; font-size:0.82rem; color:var(--text-dim);">Throughput and memory bounds across codebase sizes</div>
      </div>
      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:14px; padding:1.5rem; text-align:center;">
        <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark" style="max-width:100%; height:auto; border-radius:6px;">
        <div style="margin-top:0.75rem; font-size:0.82rem; color:var(--text-dim);">Retrieval latency: SQLite WAL + FTS5 vs vector databases</div>
      </div>
    </div>
  </section>

  <!-- Section: Client Integrations -->
  <section class="docs-container-block" id="integrations">
    <div class="docs-sec-header">
      <div class="docs-sec-tag">Drop-In Configuration</div>
      <h2 class="docs-sec-h2">AI Agent Integration Setup</h2>
    </div>

    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:1.5rem;">
      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:12px; padding:1.5rem;">
        <div style="font-weight:700; color:#fff; font-size:1.1rem; margin-bottom:0.75rem;">Cursor (.cursor/mcp.json)</div>
        <pre class="code-block-dark">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}</pre>
      </div>

      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:12px; padding:1.5rem;">
        <div style="font-weight:700; color:#fff; font-size:1.1rem; margin-bottom:0.75rem;">Claude Desktop</div>
        <pre class="code-block-dark">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--profile", "full"]
    }
  }
}</pre>
      </div>

      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:12px; padding:1.5rem;">
        <div style="font-weight:700; color:#fff; font-size:1.1rem; margin-bottom:0.75rem;">Antigravity / Zed / Windsurf</div>
        <pre class="code-block-dark">codegraph mcp serve --db .codegraph/index.db</pre>
      </div>
    </div>
  </section>

  <!-- Universal Footer -->
  <footer class="blueprint-footer">
    <div class="footer-inner-box">
      <div class="brand-wrap">
        <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" class="brand-cube-icon">
        <span class="brand-text">CodeGraph</span>
      </div>
      <div class="footer-copy">
        &copy; 2026 CodeGraph MCP Engine &bull; Released under MIT License &bull; v2.2.1 Production
      </div>
      <ul class="footer-links-row">
        <li><a href="https://pypi.org/project/codegraph-engine/2.2.1/" target="_blank">PyPI Package</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub Repository</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP/issues" target="_blank">Issue Tracker</a></li>
      </ul>
    </div>
  </footer>

  <!-- Script Engine -->
  <script>
    let currentCategory = 'all';

    function setTerminalCmd(cmd, btn) {
      document.getElementById('terminalCmdText').textContent = '$ ' + cmd;
      document.querySelectorAll('.term-tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
    }

    function copyTerminalCode() {
      const text = document.getElementById('terminalCmdText').textContent.replace('$ ', '');
      navigator.clipboard.writeText(text);
    }

    function filterToolsGrid() {
      const q = document.getElementById('toolSearchInput').value.toLowerCase().trim();
      const cards = document.querySelectorAll('.tool-item-card');

      cards.forEach(card => {
        const name = card.getAttribute('data-name') || '';
        const desc = card.getAttribute('data-desc') || '';
        const prob = card.getAttribute('data-prob') || '';
        const prof = card.getAttribute('data-prof') || '';

        const matchesQuery = !q || name.includes(q) || desc.includes(q) || prob.includes(q);
        const matchesCat = currentCategory === 'all' || prof === currentCategory;

        if (matchesQuery && matchesCat) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    }

    function setCategoryFilter(cat, btn) {
      currentCategory = cat;
      document.querySelectorAll('.tool-cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterToolsGrid();
    }

    function toggleSchemaDrawer(btn) {
      const drawer = btn.nextElementSibling;
      if (drawer.classList.contains('open')) {
        drawer.classList.remove('open');
        btn.innerHTML = 'Inspect Schema &amp; Invocation &darr;';
      } else {
        drawer.classList.add('open');
        btn.innerHTML = 'Hide Schema &amp; Invocation &uarr;';
      }
    }

    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const search = document.getElementById('toolSearchInput');
        if (search) {
          search.focus();
          window.location.hash = '#tools';
        }
      }
    });
  </script>
</body>
</html>
''')

    output_path = docs_dir / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

    print(f"Wrote docs/index.html successfully, length: {len(''.join(html_parts))}")


if __name__ == "__main__":
    generate_docs()
