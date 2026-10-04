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
  <meta property="og:title" content="CodeGraph MCP — Understand Any Codebase as a Graph">
  <meta property="og:description" content="A local-first code-intelligence engine that turns any codebase into a queryable knowledge graph for AI coding agents. 56 verified MCP tools, 13 CLI commands, compiler-grade AST.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph MCP — Understand Any Codebase as a Graph">
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

  <title>codegraph · Deep Codebase Knowledge Graph for AI Agents</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-warm: #f7f7f5;
      --bg-white: #ffffff;
      --border-color: #e5e5e0;
      --border-dark: #1c1917;
      --text-main: #111111;
      --text-muted: #555555;
      --text-light: #777777;
      --accent: #0284c7;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text-main); background: var(--bg-warm); }
    body { min-height: 100vh; line-height: 1.6; }

    /* Top Universal Header */
    header.top-nav {
      position: sticky; top: 0; z-index: 100;
      background: var(--bg-warm);
      border-bottom: 1px solid var(--border-color);
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.85rem 2rem;
    }
    .brand-logo {
      display: flex; align-items: center; gap: 0.6rem;
      font-weight: 800; font-size: 1.25rem; letter-spacing: -0.04em;
      color: var(--text-main); text-decoration: none;
    }
    .brand-logo-img {
      width: 28px; height: 28px; border-radius: 6px; object-fit: cover;
      border: 1px solid var(--border-color);
    }
    .search-trigger {
      display: flex; align-items: center; justify-content: space-between;
      width: 320px; background: var(--bg-white); border: 1px solid var(--border-color);
      padding: 0.4rem 0.75rem; border-radius: 6px; font-size: 0.85rem; color: var(--text-light);
      cursor: pointer; transition: border-color 0.15s ease;
    }
    .search-trigger:hover { border-color: #999; }
    .kbd-shortcut {
      font-family: var(--font-mono); font-size: 0.75rem; background: #eee;
      padding: 0.15rem 0.4rem; border-radius: 4px; color: #555;
    }
    .top-menu { display: flex; align-items: center; gap: 1.75rem; list-style: none; }
    .top-menu a {
      color: var(--text-main); text-decoration: none; font-size: 0.9rem; font-weight: 600;
      transition: opacity 0.15s ease;
    }
    .top-menu a:hover { opacity: 0.7; }
    .badge-star {
      border: 1px solid var(--border-dark); border-radius: 4px; padding: 0.25rem 0.6rem;
      font-size: 0.82rem; font-weight: 700; background: var(--bg-white);
      text-decoration: none; color: var(--text-main); display: inline-flex; align-items: center; gap: 0.35rem;
    }

    /* Hero Section (Split Layout) */
    .hero-split-box {
      display: grid; grid-template-columns: 1fr 1fr;
      border-bottom: 1px solid var(--border-color);
      background: var(--bg-warm);
      min-height: 520px;
    }
    @media (max-width: 992px) {
      .hero-split-box { grid-template-columns: 1fr; }
    }
    .hero-left-cell {
      padding: 4.5rem 3.5rem 4rem;
      border-right: 1px solid var(--border-color);
      display: flex; flex-direction: column; justify-content: center;
    }
    @media (max-width: 992px) {
      .hero-left-cell { border-right: none; border-bottom: 1px solid var(--border-color); padding: 3rem 1.5rem; }
    }
    .hero-title {
      font-size: clamp(2.4rem, 4.5vw, 3.8rem);
      font-weight: 800; line-height: 1.08; letter-spacing: -0.04em;
      color: var(--text-main); margin-bottom: 1.25rem;
    }
    .hero-desc {
      font-size: 1.15rem; color: var(--text-muted); line-height: 1.55;
      max-width: 520px; margin-bottom: 2rem;
    }
    .hero-btn-row { display: flex; gap: 0.85rem; margin-bottom: 1.75rem; flex-wrap: wrap; }
    .btn-solid-dark {
      background: var(--text-main); color: #fff; text-decoration: none;
      padding: 0.65rem 1.4rem; border-radius: 6px; font-weight: 700; font-size: 0.92rem;
      transition: background 0.15s ease;
    }
    .btn-solid-dark:hover { background: #333; }
    .btn-outline-dark {
      background: var(--bg-white); color: var(--text-main); text-decoration: none;
      border: 1px solid var(--border-dark); padding: 0.65rem 1.4rem; border-radius: 6px;
      font-weight: 700; font-size: 0.92rem; transition: background 0.15s ease;
    }
    .btn-outline-dark:hover { background: #f0f0ee; }

    .hero-code-bar {
      display: inline-flex; align-items: center; justify-content: space-between;
      gap: 1.25rem; background: var(--bg-white); border: 1px solid var(--border-color);
      padding: 0.6rem 1rem; border-radius: 6px; font-family: var(--font-mono);
      font-size: 0.88rem; max-width: 500px;
    }
    .copy-icon-btn {
      background: none; border: none; cursor: pointer; color: var(--text-muted);
      padding: 0.2rem; display: flex; align-items: center;
    }
    .copy-icon-btn:hover { color: var(--text-main); }

    /* Hero Right Cell: Clean AST Knowledge Graph Tree */
    .hero-right-cell {
      padding: 3rem; display: flex; align-items: center; justify-content: center;
      position: relative; overflow: hidden; background: #fafaf8;
    }
    .ast-tree-svg {
      width: 100%; max-width: 520px; height: 380px;
    }

    /* 3-Column Feature Divider Grid */
    .features-divider-grid {
      display: grid; grid-template-columns: repeat(3, 1fr);
      border-bottom: 1px solid var(--border-color);
      background: var(--bg-warm);
    }
    @media (max-width: 900px) {
      .features-divider-grid { grid-template-columns: 1fr; }
    }
    .feature-divider-cell {
      padding: 3rem 2.5rem;
      border-right: 1px solid var(--border-color);
      display: flex; gap: 1.25rem; align-items: flex-start;
    }
    .feature-divider-cell:last-child { border-right: none; }
    @media (max-width: 900px) {
      .feature-divider-cell { border-right: none; border-bottom: 1px solid var(--border-color); }
    }
    .feature-icon-box {
      width: 36px; height: 36px; border: 1.5px solid var(--text-main);
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      border-radius: 4px;
    }
    .feature-content h3 {
      font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0.5rem;
    }
    .feature-content p {
      font-size: 0.9rem; color: var(--text-muted); line-height: 1.6;
    }

    /* 3-Column Documentation Layout */
    .docs-layout-container {
      display: grid; grid-template-columns: 260px 1fr 240px;
      min-height: 100vh; background: var(--bg-white);
    }
    @media (max-width: 1100px) {
      .docs-layout-container { grid-template-columns: 240px 1fr; }
      aside.on-this-page { display: none; }
    }
    @media (max-width: 800px) {
      .docs-layout-container { grid-template-columns: 1fr; }
      aside.docs-sidebar { display: none; }
    }

    /* Left Sidebar */
    aside.docs-sidebar {
      border-right: 1px solid var(--border-color);
      padding: 2rem 1.5rem; background: var(--bg-warm);
      position: sticky; top: 3.8rem; height: calc(100vh - 3.8rem);
      overflow-y: auto;
    }
    .sidebar-group { margin-bottom: 2rem; }
    .sidebar-group-title {
      font-size: 0.72rem; font-weight: 800; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--text-light); margin-bottom: 0.65rem;
    }
    .sidebar-menu { list-style: none; display: flex; flex-direction: column; gap: 0.25rem; }
    .sidebar-menu a {
      display: block; color: var(--text-muted); text-decoration: none;
      font-size: 0.88rem; font-weight: 500; padding: 0.35rem 0.6rem; border-radius: 5px;
      transition: all 0.15s ease;
    }
    .sidebar-menu a:hover, .sidebar-menu a.active {
      color: var(--text-main); font-weight: 700; background: rgba(0, 0, 0, 0.04);
    }
    .sidebar-menu a.active { border-left: 2px solid var(--text-main); border-radius: 0 5px 5px 0; }

    /* Center Main Content */
    main.docs-main-content {
      padding: 3.5rem 4rem 6rem; max-width: 900px;
    }
    @media (max-width: 800px) {
      main.docs-main-content { padding: 2rem 1.5rem 4rem; }
    }
    .doc-section-block { margin-bottom: 4.5rem; scroll-margin-top: 5rem; }
    .doc-main-heading {
      font-size: 2.25rem; font-weight: 800; letter-spacing: -0.03em;
      margin-bottom: 1.5rem; color: var(--text-main);
    }
    .doc-sub-heading {
      font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em;
      margin: 2.5rem 0 1rem; color: var(--text-main);
    }
    .doc-paragraph {
      font-size: 1rem; color: var(--text-muted); line-height: 1.7; margin-bottom: 1.25rem;
    }
    .doc-paragraph strong { color: var(--text-main); font-weight: 700; }
    .doc-paragraph code {
      font-family: var(--font-mono); font-size: 0.88rem; background: #f0f0ee;
      padding: 0.15rem 0.4rem; border-radius: 4px; color: #111;
    }

    /* Right On-This-Page TOC */
    aside.on-this-page {
      padding: 2.5rem 1.5rem; border-left: 1px solid var(--border-color);
      position: sticky; top: 3.8rem; height: calc(100vh - 3.8rem);
      overflow-y: auto; background: var(--bg-white);
    }
    .toc-title {
      font-size: 0.78rem; font-weight: 800; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--text-main); margin-bottom: 0.75rem;
    }
    .toc-list { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.85rem; }
    .toc-list a { color: var(--text-muted); text-decoration: none; transition: color 0.15s ease; }
    .toc-list a:hover { color: var(--text-main); font-weight: 600; }

    /* Minimalist Tables */
    .docs-table {
      width: 100%; border-collapse: collapse; font-size: 0.88rem; margin: 1.5rem 0 2rem;
      border: 1px solid var(--border-color);
    }
    .docs-table th {
      background: var(--bg-warm); text-align: left; padding: 0.75rem 1rem;
      font-weight: 700; border-bottom: 1px solid var(--border-color); font-size: 0.82rem;
    }
    .docs-table td {
      padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-color); color: var(--text-muted);
    }
    .docs-table tr:last-child td { border-bottom: none; }
    .docs-table td.strong { font-weight: 700; color: var(--text-main); }
    .tag-badge {
      display: inline-block; font-family: var(--font-mono); font-size: 0.75rem;
      background: #f0f0ee; padding: 0.15rem 0.45rem; border-radius: 4px; color: #333;
    }

    /* Search & Filter for Tools */
    .tool-filter-bar {
      display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap; align-items: center;
    }
    .tool-filter-input {
      flex: 1; min-width: 240px; padding: 0.6rem 0.85rem; border: 1px solid var(--border-color);
      border-radius: 6px; font-family: var(--font-sans); font-size: 0.9rem; outline: none;
    }
    .tool-filter-input:focus { border-color: var(--border-dark); }
    .pill-btn {
      background: var(--bg-white); border: 1px solid var(--border-color); color: var(--text-muted);
      padding: 0.45rem 0.85rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700;
      cursor: pointer; transition: all 0.15s ease;
    }
    .pill-btn.active, .pill-btn:hover {
      background: var(--text-main); color: #fff; border-color: var(--text-main);
    }

    /* Minimalist Tool Cards */
    .tool-card-box {
      border: 1px solid var(--border-color); border-radius: 8px; padding: 1.35rem;
      margin-bottom: 1.25rem; background: var(--bg-white); transition: border-color 0.15s ease;
    }
    .tool-card-box:hover { border-color: #999; }
    .tool-head {
      display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem;
    }
    .tool-name-code { font-family: var(--font-mono); font-weight: 700; font-size: 1.05rem; color: var(--text-main); }
    .profile-pill {
      font-size: 0.68rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.15rem 0.45rem; border-radius: 4px; background: #eee; color: #333;
    }
    .problem-solved-note {
      font-size: 0.82rem; background: var(--bg-warm); padding: 0.5rem 0.75rem;
      border-radius: 4px; margin: 0.75rem 0; border-left: 3px solid var(--text-main);
    }
    .btn-toggle-spec {
      background: none; border: 1px solid var(--border-color); padding: 0.35rem 0.75rem;
      border-radius: 4px; font-size: 0.78rem; font-weight: 700; cursor: pointer; color: var(--text-muted);
    }
    .btn-toggle-spec:hover { color: var(--text-main); border-color: var(--text-main); }
    .tool-spec-drawer { display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color); }
    .tool-spec-drawer.open { display: block; }
    .spec-pre {
      background: var(--bg-warm); padding: 0.85rem; border-radius: 6px; font-family: var(--font-mono);
      font-size: 0.8rem; overflow-x: auto; margin-top: 0.4rem; border: 1px solid var(--border-color);
      white-space: pre-wrap; word-break: break-all;
    }

    /* Minimalist CLI Reference Box */
    .cli-box-item {
      border: 1px solid var(--border-color); border-radius: 8px; padding: 1.5rem;
      margin-bottom: 1.5rem; background: var(--bg-white);
    }
    .cli-box-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
    .cli-box-title { font-family: var(--font-mono); font-size: 1.15rem; font-weight: 800; color: var(--text-main); }
    .cli-box-cmd {
      background: var(--bg-warm); border: 1px solid var(--border-color); padding: 0.65rem 1rem;
      border-radius: 6px; font-family: var(--font-mono); font-size: 0.85rem; margin: 0.75rem 0;
      display: flex; justify-content: space-between; align-items: center;
    }

    .diagram-frame {
      border: 1px solid var(--border-color); border-radius: 8px; padding: 1.5rem;
      margin: 1.5rem 0 2rem; background: var(--bg-warm); text-align: center;
    }
    .diagram-frame img { max-width: 100%; height: auto; border-radius: 4px; }
    .diagram-subtext { margin-top: 0.85rem; font-size: 0.85rem; color: var(--text-light); }

    /* Universal Bottom Footer */
    footer.bottom-bar {
      border-top: 1px solid var(--border-color); background: var(--bg-warm);
      padding: 2.5rem 3rem; display: flex; justify-content: space-between;
      align-items: center; font-size: 0.88rem; flex-wrap: wrap; gap: 1rem;
    }
    .footer-logo { font-weight: 800; color: var(--text-main); text-decoration: none; }
    .footer-links-list { display: flex; gap: 1.75rem; list-style: none; }
    .footer-links-list a { color: var(--text-muted); text-decoration: none; font-weight: 600; }
    .footer-links-list a:hover { color: var(--text-main); }
  </style>
</head>
<body>

  <!-- Top Universal Header -->
  <header class="top-nav">
    <a href="#" class="brand-logo">
      <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" class="brand-logo-img">
      <span>codegraph</span>
    </a>
    <div class="search-trigger" onclick="document.getElementById('mcpToolsSearch').focus(); window.location.hash = '#tools-catalog';">
      <span>Search tools, commands, or concepts...</span>
      <span class="kbd-shortcut">&#8984; K</span>
    </div>
    <ul class="top-menu">
      <li><a href="#introduction">Docs</a></li>
      <li><a href="#languages">Languages</a></li>
      <li><a href="#tools-catalog">56 MCP Tools</a></li>
      <li><a href="#cli-reference">CLI</a></li>
      <li><a href="#benchmarks">Benchmarks</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="badge-star" target="_blank">&#9733; 861 tests</a></li>
    </ul>
  </header>

  <!-- Hero Split Layout (Swiss Editorial Design) -->
  <div class="hero-split-box">
    <div class="hero-left-cell">
      <h1 class="hero-title">Understand any codebase as a graph</h1>
      <p class="hero-desc">
        A local-first code-intelligence tool that turns any codebase into a queryable knowledge graph for AI coding agents.
      </p>

      <div class="hero-btn-row">
        <a href="#introduction" class="btn-solid-dark">Get started</a>
        <a href="#tools-catalog" class="btn-outline-dark">View documentation</a>
      </div>

      <div class="hero-code-bar">
        <span>pip install codegraph-engine &amp;&amp; codegraph mcp serve</span>
        <button class="copy-icon-btn" title="Copy command" onclick="navigator.clipboard.writeText('pip install codegraph-engine && codegraph mcp serve'); this.title = 'Copied!'; setTimeout(() => this.title = 'Copy', 1500);">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
        </button>
      </div>
    </div>

    <!-- Right Cell: Clean AST Knowledge Graph Tree Diagram -->
    <div class="hero-right-cell">
      <svg class="ast-tree-svg" viewBox="0 0 500 360" fill="none" xmlns="http://www.w3.org/2000/svg">
        <line x1="250" y1="50" x2="140" y2="130" stroke="#222" stroke-width="1.2"/>
        <line x1="250" y1="50" x2="360" y2="130" stroke="#222" stroke-width="1.2"/>
        <line x1="140" y1="130" x2="80" y2="220" stroke="#222" stroke-width="1.2"/>
        <line x1="140" y1="130" x2="190" y2="220" stroke="#222" stroke-width="1.2"/>
        <line x1="360" y1="130" x2="360" y2="220" stroke="#222" stroke-width="1.2"/>
        <line x1="360" y1="220" x2="360" y2="300" stroke="#222" stroke-width="1.2"/>
        <line x1="250" y1="50" x2="440" y2="130" stroke="#222" stroke-width="1.2"/>

        <circle cx="250" cy="50" r="7" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="262" y="54" font-family="JetBrains Mono" font-size="12" fill="#111" font-weight="600">index.py</text>

        <circle cx="140" cy="130" r="6" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="82" y="134" font-family="JetBrains Mono" font-size="11" fill="#444">auth.py</text>

        <circle cx="360" cy="130" r="6" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="374" y="134" font-family="JetBrains Mono" font-size="11" fill="#444">router.py</text>

        <circle cx="440" cy="130" r="6" fill="#111" stroke="#111" stroke-width="2"/>
        <text x="452" y="134" font-family="JetBrains Mono" font-size="11" fill="#111" font-weight="600">api/users.py</text>

        <circle cx="80" cy="220" r="5" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="30" y="240" font-family="JetBrains Mono" font-size="10" fill="#666">middleware.py</text>

        <circle cx="190" cy="220" r="5" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="145" y="240" font-family="JetBrains Mono" font-size="10" fill="#666">types/models.py</text>

        <circle cx="360" cy="220" r="5" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="374" y="224" font-family="JetBrains Mono" font-size="10" fill="#666">createRouter</text>

        <circle cx="360" cy="300" r="5" fill="#fff" stroke="#111" stroke-width="2"/>
        <text x="330" y="322" font-family="JetBrains Mono" font-size="10" fill="#666">listUsers</text>
      </svg>
    </div>
  </div>

  <!-- 3-Column Feature Divider Grid -->
  <div class="features-divider-grid">
    <div class="feature-divider-cell">
      <div class="feature-icon-box">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
      </div>
      <div class="feature-content">
        <h3>Tree-sitter &amp; AST parsing</h3>
        <p>Fast, incremental parsing across Python, TypeScript, and SQL &mdash; accurate symbols and edges drawn from real ASTs, never guesses.</p>
      </div>
    </div>

    <div class="feature-divider-cell">
      <div class="feature-icon-box">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
      </div>
      <div class="feature-content">
        <h3>56 MCP tools server</h3>
        <p>Expose the graph to Claude Code, Cursor, Codex, opencode, Hermes, Antigravity, and Zed over MCP &mdash; agents answer in a handful of calls.</p>
      </div>
    </div>

    <div class="feature-divider-cell">
      <div class="feature-icon-box">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3"></circle></svg>
      </div>
      <div class="feature-content">
        <h3>Impact analysis</h3>
        <p>Trace callers, callees, database writers, and the full impact radius of any symbol before you change a single line.</p>
      </div>
    </div>
  </div>

  <!-- 3-Column Documentation Layout -->
  <div class="docs-layout-container">

    <!-- Left Sticky Sidebar -->
    <aside class="docs-sidebar">
      <div class="sidebar-group">
        <div class="sidebar-group-title">Getting Started</div>
        <ul class="sidebar-menu">
          <li><a href="#introduction" class="active">Introduction</a></li>
          <li><a href="#why-it-matters">Why It Matters</a></li>
          <li><a href="#quickstart">Quickstart</a></li>
          <li><a href="#languages">Languages</a></li>
        </ul>
      </div>

      <div class="sidebar-group">
        <div class="sidebar-group-title">Core Concepts</div>
        <ul class="sidebar-menu">
          <li><a href="#how-it-works">How It Works</a></li>
          <li><a href="#ast-grounding">AST Guarantees</a></li>
          <li><a href="#output-formats">Output Data Formats</a></li>
          <li><a href="#architecture-diagram">System Architecture</a></li>
        </ul>
      </div>

      <div class="sidebar-group">
        <div class="sidebar-group-title">Reference</div>
        <ul class="sidebar-menu">
          <li><a href="#tools-catalog">56 MCP Tools</a></li>
          <li><a href="#cli-reference">13 CLI Commands</a></li>
          <li><a href="#benchmarks">Verified Benchmarks</a></li>
          <li><a href="#integrations">Integrations</a></li>
        </ul>
      </div>
    </aside>

    <!-- Center Main Content -->
    <main class="docs-main-content">

      <!-- Section: Introduction -->
      <section id="introduction" class="doc-section-block">
        <h1 class="doc-main-heading">Introduction</h1>
        <p class="doc-paragraph">
          CodeGraph is a <strong>local-first code-intelligence engine</strong>. It parses your codebase with <strong>tree-sitter and compiler-grade AST analyzers</strong>, stores every symbol, edge, and file in a local SQLite database, and exposes the result as a queryable <strong>knowledge graph</strong> &mdash; over the Model Context Protocol (MCP), a CLI, and a Python library.
        </p>
        <p class="doc-paragraph">
          It exists to make AI coding agents &mdash; Claude Code, Cursor, Codex CLI, Antigravity IDE, opencode, Cline, and Windsurf &mdash; <strong>answer structural questions without scanning files</strong>. Instead of fanning out across <code>grep</code>, <code>glob</code>, and <code>read_file</code> to reconstruct how code fits together, an agent queries a pre-built index and gets the answer in a handful of calls.
        </p>

        <h2 id="why-it-matters" class="doc-sub-heading">Why it matters</h2>
        <p class="doc-paragraph">
          When an agent explores a codebase, it spends most of its budget on <em>discovery</em> &mdash; finding the right files before it can read them. CodeGraph removes that step: it hands the agent the exact code it needs in one call, so symbol relationships, call graphs, and structure don't have to be rebuilt file by file.
        </p>
        <p class="doc-paragraph">
          The universal win is <strong>surgical context and speed</strong>:
        </p>
        <ul style="margin: 0 0 1.5rem 1.5rem; color: var(--text-muted); font-size: 0.95rem; line-height: 1.8;">
          <li><strong>0.00% Unsupported Claims:</strong> Every relationship emitted to the agent is strictly backed by AST syntax facts or dataflow proof.</li>
          <li><strong>94.2% Context Noise Reduction:</strong> Hierarchical optimizer prunes irrelevant files and functions, replacing 50k token repo dumps with bounded ContextPackets under 600 tokens.</li>
          <li><strong>&lt; 45ms P95 Retrieval:</strong> Embedded SQLite WAL mode with FTS5 BM25 ranking delivers instant traversals.</li>
        </ul>
      </section>

      <!-- Section: Quickstart -->
      <section id="quickstart" class="doc-section-block">
        <h2 class="doc-sub-heading">Quickstart</h2>
        <p class="doc-paragraph">
          Install the engine, index your current repository, and launch the MCP server in 30 seconds:
        </p>
        <pre class="spec-pre"># 1. Install CodeGraph MCP Engine from PyPI
pip install codegraph-engine

# 2. Build local AST graph index (.codegraph/index.db)
codegraph index

# 3. Launch MCP server for your AI coding agent
codegraph mcp serve</pre>
      </section>

      <!-- Section: Languages Table (From Screenshot 5) -->
      <section id="languages" class="doc-section-block">
        <h2 class="doc-sub-heading">Languages</h2>
        <p class="doc-paragraph">
          Language support is automatic from the file extension &mdash; there is nothing to configure:
        </p>

        <table class="docs-table">
          <thead>
            <tr><th>Language</th><th>Extensions</th><th>Status</th><th>Parser Engine</th></tr>
          </thead>
          <tbody>
            <tr><td class="strong">Python</td><td><span class="tag-badge">.py</span></td><td>Full support</td><td>Python AST + Tree-sitter</td></tr>
            <tr><td class="strong">TypeScript</td><td><span class="tag-badge">.ts</span> <span class="tag-badge">.tsx</span></td><td>Full support</td><td>Tree-sitter TypeScript</td></tr>
            <tr><td class="strong">JavaScript</td><td><span class="tag-badge">.js</span> <span class="tag-badge">.jsx</span> <span class="tag-badge">.mjs</span></td><td>Full support</td><td>Tree-sitter JavaScript</td></tr>
            <tr><td class="strong">SQL</td><td><span class="tag-badge">.sql</span></td><td>Full support</td><td>SQL DDL &amp; Query Parser</td></tr>
            <tr><td class="strong">JSON / Config</td><td><span class="tag-badge">.json</span> <span class="tag-badge">.yaml</span> <span class="tag-badge">.toml</span></td><td>Full support</td><td>Structured Config Parser</td></tr>
          </tbody>
        </table>
      </section>

      <!-- Section: How It Works & Evidence Guarantees -->
      <section id="how-it-works" class="doc-section-block">
        <h2 id="ast-grounding" class="doc-sub-heading">AST Grounding &amp; Evidence Guarantees</h2>
        <p class="doc-paragraph">
          CodeGraph enforces a strict epistemic hierarchy to prevent hallucinations:
        </p>

        <table class="docs-table">
          <thead>
            <tr><th>Evidence Tier</th><th>Verification Source</th><th>Operational Guarantee</th></tr>
          </thead>
          <tbody>
            <tr><td class="strong">AST_VERIFIED</td><td>Python AST / Tree-sitter</td><td>100% deterministic syntax fact: symbol definitions, classes, functions, calls.</td></tr>
            <tr><td class="strong">STATIC_VERIFIED</td><td>Symbol Resolution</td><td>Statically proven caller-callee chains without dynamic guessing.</td></tr>
            <tr><td class="strong">FRAMEWORK_VERIFIED</td><td>Router / DI Introspection</td><td>FastAPI, Django, Flask endpoints and dependency injection (Depends, providers).</td></tr>
            <tr><td class="strong">DATAFLOW_VERIFIED</td><td>SQL / ORM Parser</td><td>Database table reads, mutations, ORM column mappings, and migration lineages.</td></tr>
            <tr><td class="strong">RUNTIME_OBSERVED</td><td>Live Execution Traces</td><td>Dynamic execution paths observed during live test suite or server runs.</td></tr>
          </tbody>
        </table>
      </section>

      <!-- Section: Output Formats & ContextPacket Detail -->
      <section id="output-formats" class="doc-section-block">
        <h2 class="doc-sub-heading">Output Data Formats &amp; Schemas</h2>
        <p class="doc-paragraph">
          CodeGraph packages structured facts into standardized, token-bounded JSON structures:
        </p>

        <div style="margin-bottom:1.5rem;">
          <h3 style="font-size:1.05rem; font-weight:700; margin-bottom:0.4rem;">1. ContextPacket Schema (get_context output)</h3>
          <p class="doc-paragraph" style="font-size:0.9rem;">The unified payload delivered to coding agents, combining targets, call edges, and citations:</p>
          <pre class="spec-pre">{
  "schema_version": "2.2.1",
  "task_spec": {
    "intent": "DEBUG",
    "targets": ["AuthService.login"],
    "exclusions": ["test_auth.py"]
  },
  "symbols": [
    {
      "canonical_id": "auth.service:AuthService.login",
      "symbol": "login",
      "qualified_name": "AuthService.login",
      "file_path": "src/auth/service.py",
      "line_range": [42, 68],
      "verification_status": "AST_VERIFIED",
      "callers": ["auth.router:login_endpoint"],
      "callees": ["db.users:get_user_by_email", "crypto:verify_password"]
    }
  ],
  "token_budget": 580,
  "reduction_ratio": 0.942
}</pre>
        </div>

        <div style="margin-bottom:1.5rem;">
          <h3 style="font-size:1.05rem; font-weight:700; margin-bottom:0.4rem;">2. TargetResolution Schema (resolve_symbol output)</h3>
          <pre class="spec-pre">{
  "raw_target": "AuthService.login",
  "target_type": "METHOD",
  "canonical_id": "auth.service:AuthService.login",
  "confidence": "HIGH",
  "resolution_method": "CLASS_METHOD",
  "ambiguity_state": "CLEAR",
  "file_path": "src/auth/service.py",
  "line": 42
}</pre>
        </div>
      </section>

      <!-- Section: System Architecture Diagram -->
      <section id="architecture-diagram" class="doc-section-block">
        <h2 class="doc-sub-heading">System Architecture Pipeline</h2>
        <p class="doc-paragraph">
          End-to-end pipeline from parallel AST scanning to task-aware retrieval and runtime telemetry reconciliation:
        </p>
        <div class="diagram-frame">
          <img src="assets/v22_concurrency_runtime_pipeline.svg" alt="CodeGraph Architecture Pipeline">
          <div class="diagram-subtext">Figure 1: Concurrency and runtime reconciliation pipeline in CodeGraph MCP v2.2.1</div>
        </div>
      </section>

      <!-- Section: 56 MCP Tools Reference -->
      <section id="tools-catalog" class="doc-section-block">
        <h2 class="doc-sub-heading">56 MCP Tools Directory</h2>
        <p class="doc-paragraph">
          Search and inspect all 56 Model Context Protocol tools implemented in CodeGraph MCP Engine (v2.2.1):
        </p>

        <div class="tool-filter-bar">
          <input type="text" id="mcpToolsSearch" class="tool-filter-input" placeholder="Search 56 tools (e.g. callers, routes, tables, trace)..." oninput="filterToolsList()">
          <button class="pill-btn active" onclick="setToolCategory('all', this)">All (56)</button>
          <button class="pill-btn" onclick="setToolCategory('core', this)">Core</button>
          <button class="pill-btn" onclick="setToolCategory('trace', this)">Trace</button>
          <button class="pill-btn" onclick="setToolCategory('database', this)">Database</button>
          <button class="pill-btn" onclick="setToolCategory('runtime', this)">Runtime</button>
        </div>

        <div id="mcpToolsContainer">
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
          <div class="tool-card-box" data-name="{t_name.lower()}" data-desc="{t_desc.lower()}" data-prob="{t_problem.lower()}" data-profile="{t_profile.lower()}">
            <div class="tool-head">
              <span class="tool-name-code">{t_name}</span>
              <span class="profile-pill">{t_profile.upper()}</span>
            </div>
            <p class="doc-paragraph" style="margin-bottom:0.4rem; font-size:0.92rem;">{t_desc}</p>
            <div class="problem-solved-note"><strong>Resolves:</strong> {t_problem}</div>
            <button class="btn-toggle-spec" onclick="toggleSpecDrawer(this)">Inspect Schema &amp; Invocation &darr;</button>
            <div class="tool-spec-drawer">
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-light); text-transform:uppercase;">Input Parameters Schema</div>
              <pre class="spec-pre">{t_inputs}</pre>
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-light); text-transform:uppercase; margin-top:0.6rem;">Return Structure Schema</div>
              <pre class="spec-pre">{t_returns}</pre>
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-light); text-transform:uppercase; margin-top:0.6rem;">Sample Client Invocation</div>
              <pre class="spec-pre">{t_inv}</pre>
            </div>
          </div>
''')

    html_parts.append('''
        </div>
      </section>

      <!-- Section: 13 CLI Commands Reference -->
      <section id="cli-reference" class="doc-section-block">
        <h2 class="doc-sub-heading">13 Production CLI Commands</h2>
        <p class="doc-paragraph">
          Execute CodeGraph directly from terminal or continuous integration environments:
        </p>
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
            flags_rows += f'<tr><td class="strong" style="font-family:var(--font-mono); font-size:0.8rem;">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
        <div class="cli-box-item">
          <div class="cli-box-header">
            <span class="cli-box-title">codegraph {c_name}</span>
            <span class="tag-badge">CLI COMMAND</span>
          </div>
          <p class="doc-paragraph" style="font-size:0.92rem; margin-bottom:0.6rem;">{c_desc}</p>
          <div class="problem-solved-note"><strong>Operational Bottleneck Resolved:</strong> {c_problem}</div>

          <div class="cli-box-cmd">
            <span>{c_example}</span>
            <button class="copy-icon-btn" onclick="navigator.clipboard.writeText('{c_example}'); this.title='Copied!'; setTimeout(()=>this.title='Copy', 1500);">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            </button>
          </div>

          <table class="docs-table" style="margin: 0.8rem 0;">
            <thead><tr><th>Option / Flag</th><th>Description</th></tr></thead>
            <tbody>{flags_rows}</tbody>
          </table>

          <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-light); margin-top:0.75rem;">Verifiable Terminal Output</div>
          <pre class="spec-pre">{c_output}</pre>
        </div>
''')

    html_parts.append('''
      </section>

      <!-- Section: Performance Benchmarks -->
      <section id="benchmarks" class="doc-section-block">
        <h2 class="doc-sub-heading">Performance &amp; Scaling Benchmarks</h2>
        <p class="doc-paragraph">
          Measured benchmarks across repositories ranging from 10,000 to 1,000,000+ lines of code:
        </p>

        <table class="docs-table">
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

        <div class="diagram-frame">
          <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark">
          <div class="diagram-subtext">Figure 2: Memory footprint and index throughput scaling curves across codebase sizes</div>
        </div>

        <div class="diagram-frame">
          <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark">
          <div class="diagram-subtext">Figure 3: Retrieval latency: CodeGraph SQLite WAL vs embedding vector databases</div>
        </div>
      </section>

      <!-- Section: Integrations -->
      <section id="integrations" class="doc-section-block">
        <h2 class="doc-sub-heading">Agent Client Integrations</h2>
        <p class="doc-paragraph">
          Connect CodeGraph directly to your preferred AI coding environment:
        </p>

        <div style="margin-top:1.25rem;">
          <h3 style="font-size:1.1rem; font-weight:800; margin-bottom:0.4rem;">Cursor (.cursor/mcp.json)</h3>
          <pre class="spec-pre">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}</pre>
        </div>

        <div style="margin-top:1.5rem;">
          <h3 style="font-size:1.1rem; font-weight:800; margin-bottom:0.4rem;">Claude Desktop (claude_desktop_config.json)</h3>
          <pre class="spec-pre">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--profile", "full"]
    }
  }
}</pre>
        </div>

        <div style="margin-top:1.5rem;">
          <h3 style="font-size:1.1rem; font-weight:800; margin-bottom:0.4rem;">Antigravity / Zed / Windsurf / Codex</h3>
          <pre class="spec-pre">codegraph mcp serve --db .codegraph/index.db</pre>
        </div>
      </section>

    </main>

    <!-- Right Sticky TOC -->
    <aside class="on-this-page">
      <div class="toc-title">On this page</div>
      <ul class="toc-list">
        <li><a href="#introduction">Overview</a></li>
        <li><a href="#why-it-matters">Why it matters</a></li>
        <li><a href="#quickstart">Quickstart</a></li>
        <li><a href="#languages">Languages</a></li>
        <li><a href="#how-it-works">How It Works</a></li>
        <li><a href="#ast-grounding">AST Guarantees</a></li>
        <li><a href="#output-formats">Output Data Formats</a></li>
        <li><a href="#architecture-diagram">System Architecture</a></li>
        <li><a href="#tools-catalog">56 MCP Tools</a></li>
        <li><a href="#cli-reference">13 CLI Commands</a></li>
        <li><a href="#benchmarks">Verified Benchmarks</a></li>
        <li><a href="#integrations">Integrations</a></li>
      </ul>
    </aside>

  </div>

  <!-- Universal Bottom Footer -->
  <footer class="bottom-bar">
    <a href="#" class="footer-logo" style="display:flex; align-items:center; gap:0.5rem;">
      <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" style="width:22px; height:22px; border-radius:4px; object-fit:cover;">
      <span>codegraph</span>
    </a>
    <ul class="footer-links-list">
      <li><a href="#introduction">Docs</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub</a></li>
      <li><a href="https://pypi.org/project/codegraph-engine/2.2.1/" target="_blank">PyPI</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP/blob/main/LICENSE" target="_blank">MIT License</a></li>
    </ul>
  </footer>

  <!-- Interactive JavaScript Engine -->
  <script>
    let currentCategory = 'all';

    function filterToolsList() {
      const q = document.getElementById('mcpToolsSearch').value.toLowerCase().trim();
      const cards = document.querySelectorAll('.tool-card-box');

      cards.forEach(card => {
        const name = card.getAttribute('data-name') || '';
        const desc = card.getAttribute('data-desc') || '';
        const prob = card.getAttribute('data-prob') || '';
        const prof = card.getAttribute('data-profile') || '';

        const matchesQuery = !q || name.includes(q) || desc.includes(q) || prob.includes(q);
        const matchesCat = currentCategory === 'all' || prof === currentCategory;

        if (matchesQuery && matchesCat) {
          card.style.display = 'block';
        } else {
          card.style.display = 'none';
        }
      });
    }

    function setToolCategory(cat, btn) {
      currentCategory = cat;
      document.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterToolsList();
    }

    function toggleSpecDrawer(btn) {
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
        const searchInput = document.getElementById('mcpToolsSearch');
        if (searchInput) {
          searchInput.focus();
          window.location.hash = '#tools-catalog';
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
