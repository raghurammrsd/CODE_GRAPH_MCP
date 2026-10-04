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
  <meta property="og:title" content="CodeGraph — Runtime & Database Codebase Intelligence">
  <meta property="og:description" content="Local-first code-intelligence engine with runtime telemetry reconciliation, database lineage, and 56 verified MCP tools for AI coding agents.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph — Runtime & Database Codebase Intelligence">
  <meta name="twitter:description" content="Local-first code-intelligence engine with runtime telemetry reconciliation and database lineage.">
  <meta name="twitter:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "CodeGraph Engine",
    "alternateName": "codegraph-engine",
    "applicationCategory": "DeveloperApplication",
    "operatingSystem": "Cross-platform (Linux, macOS, Windows)",
    "offers": {
      "@type": "Offer",
      "price": "0",
      "priceCurrency": "USD"
    },
    "description": "Production Model Context Protocol (MCP) server providing runtime telemetry reconciliation, database lineage, and 56 graph analysis tools for AI coding agents.",
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

  <title>CodeGraph · Runtime &amp; Database Codebase Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #ffffff;
      --bg-alt: #f8fafc;
      --bg-surface: #ffffff;
      --bg-dark: #090d16;
      --border: #e2e8f0;
      --border-dark: #0f172a;
      --border-focus: #cbd5e1;
      --text: #0f172a;
      --text-muted: #475569;
      --text-dim: #94a3b8;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --indigo: #4f46e5;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #e11d48;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
      --shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.04);
      --shadow-card: 0 10px 30px -5px rgba(0, 0, 0, 0.05), 0 1px 3px rgba(0, 0, 0, 0.02);
      --shadow-hover: 0 20px 35px -5px rgba(0, 0, 0, 0.08);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; }

    /* Clean Universal Header */
    header.clean-nav {
      position: sticky; top: 0; z-index: 100;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 0.85rem 2.5rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand-wrap { display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: inherit; }
    .brand-logo-svg { width: 30px; height: 30px; flex-shrink: 0; }
    .brand-text { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.03em; color: var(--text); }

    .header-search-bar {
      display: flex; align-items: center; gap: 0.65rem;
      background: #f8fafc; border: 1px solid var(--border);
      border-radius: 8px; padding: 0.45rem 0.95rem; width: 340px; cursor: pointer;
      color: var(--text-dim); font-size: 0.88rem; transition: all 0.15s ease;
    }
    .header-search-bar:hover { border-color: var(--border-focus); color: var(--text-muted); }
    .kbd-pill {
      font-family: var(--font-mono); font-size: 0.72rem; background: #e2e8f0;
      padding: 0.15rem 0.45rem; border-radius: 4px; color: #475569; margin-left: auto;
    }

    .nav-links-menu { display: flex; align-items: center; gap: 1.75rem; list-style: none; }
    .nav-links-menu a {
      color: var(--text-muted); text-decoration: none; font-size: 0.9rem; font-weight: 600;
      transition: color 0.15s ease;
    }
    .nav-links-menu a:hover { color: var(--text); }
    .badge-star-pill {
      background: #f1f5f9; border: 1px solid var(--border);
      color: var(--text); text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 6px;
      font-size: 0.82rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.15s ease;
    }
    .badge-star-pill:hover { background: #e2e8f0; }

    /* Hero Section (White Layout) */
    .hero-white-container {
      max-width: 1380px; margin: 0 auto; padding: 4.5rem 2.5rem 3rem;
      display: grid; grid-template-columns: 1fr 1.15fr; gap: 3.5rem; align-items: center;
    }
    @media (max-width: 1080px) {
      .hero-white-container { grid-template-columns: 1fr; gap: 3.5rem; padding: 3rem 1.5rem; }
    }

    /* Left Column */
    .badge-highlight-row {
      display: inline-flex; align-items: center; gap: 0.5rem;
      background: #eff6ff; border: 1px solid #bfdbfe;
      border-radius: 9999px; padding: 0.35rem 0.9rem; font-size: 0.8rem; font-family: var(--font-mono);
      font-weight: 700; color: #1d4ed8; margin-bottom: 1.5rem;
    }
    .badge-dot-green { width: 7px; height: 7px; border-radius: 50%; background: #10b981; }

    .hero-main-title {
      font-size: clamp(2.5rem, 4.5vw, 3.8rem); font-weight: 800; line-height: 1.12;
      letter-spacing: -0.04em; color: var(--text); margin-bottom: 1.25rem;
    }
    .gradient-blue-text {
      background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }

    .hero-lead-text {
      font-size: 1.12rem; color: var(--text-muted); line-height: 1.65;
      max-width: 550px; margin-bottom: 1.85rem;
    }
    .hero-lead-text strong { color: var(--text); font-weight: 700; }

    .pills-capability-row {
      display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem;
    }
    .cap-pill {
      display: inline-flex; align-items: center; gap: 0.4rem;
      background: #f8fafc; border: 1px solid var(--border);
      color: #334155; font-size: 0.82rem; font-weight: 700; padding: 0.35rem 0.75rem;
      border-radius: 6px;
    }
    .cap-pill.highlight-db { background: #fef3c7; border-color: #fde68a; color: #92400e; }
    .cap-pill.highlight-runtime { background: #dcfce7; border-color: #bbf7d0; color: #166534; }

    .hero-btn-actions { display: flex; gap: 0.85rem; flex-wrap: wrap; margin-bottom: 2rem; }
    .btn-solid-black {
      background: #0f172a; color: #ffffff; text-decoration: none;
      padding: 0.75rem 1.6rem; border-radius: 8px; font-size: 0.92rem; font-weight: 700;
      display: inline-flex; align-items: center; gap: 0.5rem; transition: background 0.15s ease;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
    }
    .btn-solid-black:hover { background: #1e293b; }
    .btn-outline-white {
      background: #ffffff; color: var(--text); text-decoration: none;
      border: 1px solid var(--border); padding: 0.75rem 1.6rem; border-radius: 8px;
      font-size: 0.92rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.5rem;
      transition: all 0.15s ease;
    }
    .btn-outline-white:hover { background: #f8fafc; border-color: #cbd5e1; }

    /* Tabbed Terminal Box */
    .terminal-tab-box {
      background: #090d16; border: 1px solid #1e293b; border-radius: 12px;
      padding: 0.9rem 1.25rem; max-width: 550px; box-shadow: var(--shadow-card);
    }
    .term-tab-strip { display: flex; gap: 1rem; margin-bottom: 0.65rem; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 0.5rem; }
    .term-tab-btn {
      background: none; border: none; font-size: 0.78rem; font-weight: 700;
      color: #94a3b8; cursor: pointer; padding: 0.2rem 0.4rem; transition: color 0.15s ease;
    }
    .term-tab-btn.active { color: #ffffff; border-bottom: 2px solid #38bdf8; }
    .term-code-display {
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.85rem; color: #f8fafc;
    }
    .btn-copy-code {
      background: none; border: none; color: #94a3b8; cursor: pointer;
      display: flex; align-items: center; padding: 0.2rem;
    }
    .btn-copy-code:hover { color: #ffffff; }

    /* Right Column: CodeGraph Studio IDE Window (Clean Matte Dark Frame) */
    .ide-studio-window {
      background: #0d121f; border: 1px solid #1e293b;
      border-radius: 16px; overflow: hidden; box-shadow: var(--shadow-card);
    }
    .ide-header-bar {
      background: #080c15; border-bottom: 1px solid #1e293b;
      padding: 0.7rem 1rem; display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 0.75rem;
    }
    .ide-tabs-row { display: flex; gap: 0.4rem; }
    .ide-tab-pill {
      background: none; border: none; color: #94a3b8; font-size: 0.78rem;
      font-weight: 600; padding: 0.25rem 0.65rem; border-radius: 6px; cursor: pointer;
    }
    .ide-tab-pill.active { background: rgba(37, 99, 235, 0.25); color: #60a5fa; font-weight: 700; border: 1px solid rgba(59, 130, 246, 0.3); }
    .ide-search-pill {
      display: flex; align-items: center; gap: 0.4rem; background: rgba(255, 255, 255, 0.05);
      border: 1px solid #1e293b; border-radius: 6px; padding: 0.25rem 0.6rem;
      font-size: 0.75rem; color: #64748b; width: 150px;
    }

    .ide-split-body {
      display: grid; grid-template-columns: 140px 1fr 160px; min-height: 290px;
      border-bottom: 1px solid #1e293b;
    }
    @media (max-width: 680px) {
      .ide-split-body { grid-template-columns: 1fr; }
    }

    /* Left: File Tree */
    .tree-pane-wrap {
      background: #090d16; border-right: 1px solid #1e293b;
      padding: 0.85rem; font-family: var(--font-mono); font-size: 0.75rem; color: #94a3b8;
    }
    .tree-header-tag { font-weight: 700; font-size: 0.7rem; color: #64748b; text-transform: uppercase; margin-bottom: 0.5rem; }
    .tree-node-line { padding: 0.2rem 0.4rem; border-radius: 4px; display: flex; align-items: center; gap: 0.35rem; }
    .tree-node-line.selected { background: rgba(59, 130, 246, 0.15); color: #60a5fa; font-weight: 600; }
    .tree-node-line.indent { padding-left: 0.85rem; }
    .tree-node-line.indent-2 { padding-left: 1.4rem; }

    /* Center: Graph Canvas */
    .graph-canvas-wrap {
      padding: 1rem; display: flex; align-items: center; justify-content: center;
      position: relative; background: radial-gradient(#1e293b 1px, transparent 1px);
      background-size: 16px 16px;
    }
    .graph-vector-svg { width: 100%; height: 260px; }

    /* Right: Inspector Pane (Focus on Runtime & DB) */
    .inspector-pane-wrap {
      background: #090d16; border-left: 1px solid #1e293b;
      padding: 0.85rem; font-size: 0.75rem; display: flex; flex-direction: column; justify-content: space-between;
    }
    .inspector-head-title { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem; font-weight: 700; color: #fff; }
    .inspector-file-sub { color: #64748b; font-size: 0.68rem; font-family: var(--font-mono); margin-bottom: 0.75rem; }
    .prop-row { display: flex; justify-content: space-between; padding: 0.2rem 0; color: #94a3b8; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .prop-val { color: #fff; font-family: var(--font-mono); font-weight: 600; }
    .prop-val.green { color: #34d399; }
    .prop-val.amber { color: #fbbf24; }
    .btn-action-view {
      background: rgba(255, 255, 255, 0.05); border: 1px solid #1e293b;
      color: #fff; padding: 0.35rem; border-radius: 5px; font-size: 0.72rem; font-weight: 600;
      cursor: pointer; text-align: center; margin-top: 0.5rem;
    }

    /* Bottom 4 Stats Strip */
    .ide-stats-strip-bottom {
      padding: 0.75rem 1rem; display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 0.75rem; background: #080c15;
    }
    .stat-tile-card {
      background: rgba(255, 255, 255, 0.03); border: 1px solid #1e293b;
      border-radius: 8px; padding: 0.5rem 0.65rem; display: flex; align-items: center; gap: 0.5rem;
    }
    .stat-tile-num { font-size: 0.88rem; font-weight: 800; font-family: var(--font-mono); color: #fff; line-height: 1; }
    .stat-tile-tag { font-size: 0.68rem; color: #64748b; }

    /* 6 Feature Cards Grid (Clean White Enterprise Design) */
    .features-grid-section {
      max-width: 1380px; margin: 0 auto; padding: 2rem 2.5rem 5rem;
    }
    .features-6-grid {
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.35rem;
    }
    @media (max-width: 960px) {
      .features-6-grid { grid-template-columns: 1fr; }
    }
    .feature-clean-card {
      background: #ffffff; border: 1px solid var(--border);
      border-radius: 14px; padding: 1.65rem; display: flex; align-items: flex-start;
      justify-content: space-between; gap: 1rem; transition: all 0.2s ease;
      text-decoration: none; color: inherit; box-shadow: var(--shadow-sm);
    }
    .feature-clean-card:hover {
      border-color: #cbd5e1; transform: translateY(-3px); box-shadow: var(--shadow-hover);
    }
    .card-left-part { display: flex; gap: 1rem; }
    .icon-square-box {
      width: 42px; height: 42px; border-radius: 10px; display: flex; align-items: center;
      justify-content: center; flex-shrink: 0;
    }
    .icon-emerald { background: #dcfce7; color: #15803d; }
    .icon-amber { background: #fef3c7; color: #b45309; }
    .icon-blue { background: #dbeafe; color: #1d4ed8; }
    .icon-indigo { background: #e0e7ff; color: #4338ca; }
    .icon-rose { background: #ffe4e6; color: #be123c; }

    .card-text-part h3 { font-size: 1.1rem; font-weight: 800; color: var(--text); margin-bottom: 0.35rem; }
    .card-text-part p { font-size: 0.88rem; color: var(--text-muted); line-height: 1.55; }
    .arrow-circle-pill {
      width: 26px; height: 26px; border-radius: 50%; background: #f8fafc;
      display: flex; align-items: center; justify-content: center; color: var(--text-dim); flex-shrink: 0;
      border: 1px solid var(--border);
    }

    /* Documentation Section (Clean White) */
    .docs-white-section {
      background: #f8fafc; border-top: 1px solid var(--border);
      padding: 5rem 2.5rem 6rem;
    }
    .docs-inner-wrapper { max-width: 1380px; margin: 0 auto; }
    .docs-section-heading { text-align: center; max-width: 780px; margin: 0 auto 3.5rem; }
    .docs-badge-sub {
      font-family: var(--font-mono); font-size: 0.78rem; font-weight: 800;
      color: var(--primary); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.5rem;
      display: inline-block;
    }
    .docs-title-h2 { font-size: 2.35rem; font-weight: 800; letter-spacing: -0.03em; color: var(--text); margin-bottom: 0.75rem; }
    .docs-desc-p { font-size: 1.05rem; color: var(--text-muted); line-height: 1.6; }

    /* Tool Toolbar */
    .tool-white-toolbar {
      display: flex; gap: 0.75rem; margin-bottom: 2rem; flex-wrap: wrap; align-items: center;
      background: #ffffff; padding: 1rem 1.35rem; border-radius: 14px; border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }
    .tool-search-white-input {
      flex: 1; min-width: 260px; background: #f8fafc; border: 1px solid var(--border);
      border-radius: 8px; padding: 0.65rem 0.95rem; color: var(--text); font-family: var(--font-sans);
      font-size: 0.92rem; outline: none; transition: border-color 0.15s ease;
    }
    .tool-search-white-input:focus { border-color: var(--primary); }
    .btn-pill-filter {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.45rem 0.95rem; border-radius: 8px; font-size: 0.82rem; font-weight: 700; cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-pill-filter.active, .btn-pill-filter:hover {
      background: var(--text); color: #fff; border-color: var(--text);
    }

    .tools-white-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.35rem; }
    .tool-white-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem; display: flex; flex-direction: column; justify-content: space-between;
      box-shadow: var(--shadow-sm); transition: all 0.2s ease;
    }
    .tool-white-card:hover { border-color: #cbd5e1; box-shadow: var(--shadow-card); }
    .tool-card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
    .tool-code-title { font-family: var(--font-mono); font-size: 1.05rem; font-weight: 700; color: #1d4ed8; }
    .prof-tag-pill {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.18rem 0.5rem; border-radius: 4px; background: #f1f5f9; color: #475569;
    }
    .prof-tag-pill.core { background: #dbeafe; color: #1e40af; }
    .prof-tag-pill.trace { background: #e0e7ff; color: #4338ca; }
    .prof-tag-pill.database { background: #fef3c7; color: #92400e; }
    .prof-tag-pill.runtime { background: #dcfce7; color: #166534; }

    .tool-desc-body { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.85rem; line-height: 1.55; }
    .tool-problem-note {
      background: #f8fafc; border-left: 3px solid #2563eb; padding: 0.45rem 0.75rem;
      border-radius: 0 6px 6px 0; font-size: 0.82rem; color: #334155; margin-bottom: 1rem;
    }
    .btn-drawer-expand {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.45rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer;
      width: 100%; text-align: center; transition: all 0.15s ease;
    }
    .btn-drawer-expand:hover { color: var(--text); background: #f1f5f9; }
    .drawer-content { display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
    .drawer-content.open { display: block; }
    .code-box-pre {
      background: #090d16; border: 1px solid #1e293b; border-radius: 8px;
      padding: 0.8rem; font-family: var(--font-mono); font-size: 0.8rem; color: #f8fafc;
      overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin: 0.35rem 0 0.85rem;
    }

    /* CLI Grid (Clean White) */
    .cli-cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.5rem; margin-top: 2rem; }
    .cli-card-unit {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.65rem; box-shadow: var(--shadow-sm);
    }
    .cli-name-h3 { font-family: var(--font-mono); font-size: 1.15rem; font-weight: 800; color: var(--text); margin-bottom: 0.35rem; }
    .cli-solve-bar {
      background: #eff6ff; color: #1e40af; padding: 0.45rem 0.75rem; border-radius: 6px;
      font-size: 0.82rem; font-weight: 600; margin-bottom: 0.85rem;
    }
    .cli-cmd-display {
      background: #090d16; border: 1px solid #1e293b; border-radius: 6px;
      padding: 0.7rem 0.95rem; font-family: var(--font-mono); font-size: 0.85rem; color: #f8fafc;
      margin-bottom: 0.85rem; display: flex; justify-content: space-between; align-items: center;
    }
    .table-spec-clean { width: 100%; border-collapse: collapse; font-size: 0.84rem; margin: 0.5rem 0; }
    .table-spec-clean th { text-align: left; padding: 0.45rem 0.6rem; background: #f8fafc; color: var(--text-dim); }
    .table-spec-clean td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .table-spec-clean td.flag-bold { font-family: var(--font-mono); font-weight: 700; color: #2563eb; }

    /* Scaling Table (Clean White) */
    .table-scaling-box {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      overflow-x: auto; margin: 2rem 0; box-shadow: var(--shadow-sm);
    }
    .scaling-table-main { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    .scaling-table-main th {
      text-align: left; padding: 0.85rem 1.25rem; background: #f8fafc;
      color: var(--text-dim); font-weight: 700; border-bottom: 1px solid var(--border);
    }
    .scaling-table-main td { padding: 0.95rem 1.25rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .scaling-table-main td.strong { font-weight: 700; color: var(--text); }
    .badge-green-mem {
      background: #dcfce7; color: #15803d; font-family: var(--font-mono); font-size: 0.75rem;
      font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    /* Clean Footer */
    footer.clean-footer {
      border-top: 1px solid var(--border); background: #ffffff;
      padding: 4.5rem 2.5rem 3.5rem;
    }
    .footer-box-inner {
      max-width: 1380px; margin: 0 auto;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 2rem;
    }
    .footer-copy-text { font-size: 0.88rem; color: var(--text-dim); }
    .footer-links-group { display: flex; gap: 1.75rem; list-style: none; }
    .footer-links-group a { color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 600; }
    .footer-links-group a:hover { color: var(--text); }
  </style>
</head>
<body>

  <!-- Top Universal Header -->
  <header class="clean-nav">
    <a href="#" class="brand-wrap">
      <!-- 3D Geometric Isometric Graph Logo (From Reference Blueprint) -->
      <svg class="brand-logo-svg" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M16 2L28 9V23L16 30L4 23V9L16 2Z" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round"/>
        <path d="M16 2V16M28 9L16 16M4 9L16 16M16 16V30" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="16" cy="16" r="3" fill="#2563eb"/>
        <circle cx="16" cy="2" r="2" fill="#3b82f6"/>
        <circle cx="28" cy="9" r="2" fill="#3b82f6"/>
        <circle cx="4" cy="9" r="2" fill="#3b82f6"/>
        <circle cx="28" cy="23" r="2" fill="#3b82f6"/>
        <circle cx="4" cy="23" r="2" fill="#3b82f6"/>
        <circle cx="16" cy="30" r="2" fill="#3b82f6"/>
      </svg>
      <span class="brand-text">CodeGraph</span>
    </a>

    <div class="header-search-bar" onclick="document.getElementById('toolSearchInput').focus(); window.location.hash='#tools';">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
      <span>Search tools, concepts, or documentation...</span>
      <span class="kbd-pill">&#8984; K</span>
    </div>

    <ul class="nav-links-menu">
      <li><a href="#features">Docs</a></li>
      <li><a href="#tools">Tools</a></li>
      <li><a href="#cli">CLI</a></li>
      <li><a href="#benchmarks">Benchmarks</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub &nearr;</a></li>
      <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="badge-star-pill" target="_blank">&#9733; 861 tests</a></li>
    </ul>
  </header>

  <!-- Hero Blueprint (Clean White Mode) -->
  <section class="hero-white-container">
    
    <!-- Left Column: Highlighting Runtime & Database Intelligence -->
    <div class="hero-left-column">
      <div class="badge-highlight-row">
        <span class="badge-dot-green"></span>
        <span>v2.2.1 &middot; Runtime Telemetry &amp; Database Lineage</span>
      </div>

      <h1 class="hero-main-title">
        Understand any<br>
        <span class="gradient-blue-text">codebase</span> with runtime &amp; DB intelligence
      </h1>

      <p class="hero-lead-text">
        A local-first code-intelligence engine that turns any codebase into a queryable knowledge graph &mdash; tracing ORM models to database writers and reconciling static AST graphs with live execution telemetry.
      </p>

      <div class="pills-capability-row">
        <span class="cap-pill highlight-runtime">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path></svg>
          Runtime Evidence
        </span>
        <span class="cap-pill highlight-db">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
          Database Intelligence
        </span>
        <span class="cap-pill">Deterministic AST</span>
        <span class="cap-pill">Local-First</span>
        <span class="cap-pill">Multi-Language</span>
      </div>

      <div class="hero-btn-actions">
        <a href="#tools" class="btn-solid-black">&gt;_ Get started &rarr;</a>
        <a href="#features" class="btn-outline-white">View documentation</a>
      </div>

      <!-- Tabbed Terminal Box -->
      <div class="terminal-tab-box">
        <div class="term-tab-strip">
          <button class="term-tab-btn active" onclick="setTerminalCmd('pip install codegraph-engine[mcp]', this)">Install</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('codegraph query \'find_db_writers(users)\'', this)">Database CLI</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('codegraph query \'get_runtime_trace(auth)\'', this)">Runtime Traces</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('from codegraph import get_context', this)">Python API</button>
        </div>
        <div class="term-code-display">
          <span id="terminalCmdText">$ pip install codegraph-engine[mcp]</span>
          <button class="btn-copy-code" title="Copy command" onclick="copyTerminalCode()">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Right Column: CodeGraph Mockup IDE Window (Clean Matte Dark Frame) -->
    <div class="hero-right-column">
      <div class="ide-studio-window">
        <div class="ide-header-bar">
          <div class="ide-tabs-row">
            <button class="ide-tab-pill active">Runtime Trace</button>
            <button class="ide-tab-pill">Database Schema</button>
            <button class="ide-tab-pill">Call Graph</button>
            <button class="ide-tab-pill">Routes</button>
            <button class="ide-tab-pill">Dependencies</button>
          </div>
          <div class="ide-search-pill">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <span>Search symbols...</span>
          </div>
        </div>

        <div class="ide-split-body">
          <!-- Left: File Tree -->
          <div class="tree-pane-wrap">
            <div class="tree-header-tag">Repository</div>
            <div class="tree-node-line">&blacktriangledown; app/</div>
            <div class="tree-node-line indent">&blacktriangledown; routes/</div>
            <div class="tree-node-line indent-2">auth.py</div>
            <div class="tree-node-line indent-2 selected">&bull; router.py</div>
            <div class="tree-node-line indent-2">users.py</div>
            <div class="tree-node-line indent">&blacktriangledown; models/</div>
            <div class="tree-node-line indent-2">user.py</div>
            <div class="tree-node-line indent-2">orders.py</div>
            <div class="tree-node-line indent">&blacktriangledown; services/</div>
            <div class="tree-node-line indent-2">db_writer.py</div>
            <div class="tree-node-line">&blacktriangledown; tests/</div>
            <div class="tree-node-line">requirements.txt</div>
          </div>

          <!-- Center: Graph Visualization (Featuring DB + Runtime Edges) -->
          <div class="graph-canvas-wrap">
            <svg class="graph-vector-svg" viewBox="0 0 400 240" fill="none" xmlns="http://www.w3.org/2000/svg">
              <!-- Edge Lines -->
              <line x1="200" y1="120" x2="270" y2="40" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="3 3"/>
              <line x1="200" y1="120" x2="90" y2="85" stroke="#475569" stroke-width="1.2"/>
              <line x1="200" y1="120" x2="330" y2="90" stroke="#f59e0b" stroke-width="1.5"/>
              <line x1="200" y1="120" x2="130" y2="185" stroke="#475569" stroke-width="1.2"/>
              <line x1="200" y1="120" x2="270" y2="195" stroke="#10b981" stroke-width="1.5"/>

              <!-- Edge Labels -->
              <text x="245" y="75" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">imports</text>
              <text x="135" y="95" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">uses</text>
              <text x="270" y="105" font-family="JetBrains Mono" font-size="8" fill="#fbbf24">writes DB</text>
              <text x="155" y="160" font-family="JetBrains Mono" font-size="8" fill="#94a3b8">calls</text>
              <text x="245" y="165" font-family="JetBrains Mono" font-size="8" fill="#34d399">runtime span</text>

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

              <!-- Node: DB users table (Right - Highlighting Database) -->
              <circle cx="330" cy="90" r="14" fill="#0f172a" stroke="#f59e0b" stroke-width="1.8"/>
              <text x="330" y="93" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">users</text>
              <text x="315" y="115" font-family="JetBrains Mono" font-size="7" fill="#fbbf24">users (DB)</text>
              <rect x="310" y="118" width="46" height="10" rx="2" fill="#78350f"/>
              <text x="333" y="126" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#fde68a">SQL WRITER</text>

              <!-- Node: createRouter (Bottom Left) -->
              <circle cx="130" cy="185" r="12" fill="#064e3b" stroke="#10b981" stroke-width="1.8"/>
              <text x="130" y="188" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">&gt;_</text>
              <text x="148" y="182" font-family="JetBrains Mono" font-size="7" fill="#cbd5e1">createRouter</text>
              <rect x="148" y="186" width="36" height="9" rx="2" fill="#065f46"/>
              <text x="166" y="193" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#6ee7b7">FUNCTION</text>

              <!-- Node: Live Telemetry Reconciled (Bottom Right) -->
              <circle cx="270" cy="195" r="12" fill="#064e3b" stroke="#34d399" stroke-width="1.8"/>
              <text x="270" y="198" text-anchor="middle" font-family="JetBrains Mono" font-size="8" fill="#fff">&#10003;</text>
              <text x="288" y="192" font-family="JetBrains Mono" font-size="7" fill="#34d399">runtimeTrace</text>
              <rect x="288" y="196" width="38" height="9" rx="2" fill="#065f46"/>
              <text x="307" y="203" text-anchor="middle" font-family="JetBrains Mono" font-size="6" fill="#a7f3d0">RECONCILED</text>
            </svg>
          </div>

          <!-- Right: Inspector Panel -->
          <div class="inspector-pane-wrap">
            <div>
              <div class="inspector-head-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                <span>router.py</span>
              </div>
              <div class="inspector-file-sub">app/routes/router.py</div>

              <div class="prop-row"><span>Type</span><span class="prop-val">File</span></div>
              <div class="prop-row"><span>Language</span><span class="prop-val">Python</span></div>
              <div class="prop-row"><span>DB Writers</span><span class="prop-val amber">users, orders</span></div>
              <div class="prop-row"><span>Telemetry</span><span class="prop-val green">Observed</span></div>
              <div class="prop-row"><span>Routes</span><span class="prop-val">3</span></div>
              <div class="prop-row"><span>Verification</span><span class="prop-val green">100% AST</span></div>
            </div>

            <div>
              <button class="btn-action-view" style="width:100%; margin-bottom:0.35rem;">View source &rarr;</button>
              <button class="btn-action-view" style="width:100%; background:none;">Find DB queries</button>
            </div>
          </div>
        </div>

        <!-- Bottom 4 Stats Strip -->
        <div class="ide-stats-strip-bottom">
          <div class="stat-tile-card">
            <div>
              <div class="stat-tile-num">199</div>
              <div class="stat-tile-tag">Symbols</div>
            </div>
          </div>
          <div class="stat-tile-card">
            <div>
              <div class="stat-tile-num">618</div>
              <div class="stat-tile-tag">Relationships</div>
            </div>
          </div>
          <div class="stat-tile-card">
            <div>
              <div class="stat-tile-num">84</div>
              <div class="stat-tile-tag">API Routes</div>
            </div>
          </div>
          <div class="stat-tile-card">
            <div>
              <div class="stat-tile-num">58</div>
              <div class="stat-tile-tag">Files</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- 6 Feature Cards Row (Highlighting Runtime & Database) -->
  <section class="features-grid-section" id="features">
    <div class="features-6-grid">
      
      <!-- Card 1: Runtime Evidence (Highlighted!) -->
      <a href="#tools" class="feature-clean-card" style="border-top: 3px solid #10b981;">
        <div class="card-left-part">
          <div class="icon-square-box icon-emerald">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          </div>
          <div class="card-text-part">
            <h3>Runtime evidence</h3>
            <p>Combine static analysis with runtime traces for verified execution context.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

      <!-- Card 2: Database Intelligence (Highlighted!) -->
      <a href="#tools" class="feature-clean-card" style="border-top: 3px solid #f59e0b;">
        <div class="card-left-part">
          <div class="icon-square-box icon-amber">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
          </div>
          <div class="card-text-part">
            <h3>Database intelligence</h3>
            <p>Trace ORM/SQL to tables, columns, mutating queries, and data flows.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

      <!-- Card 3: Tree-sitter & AST parsing -->
      <a href="#tools" class="feature-clean-card">
        <div class="card-left-part">
          <div class="icon-square-box icon-indigo">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
          </div>
          <div class="card-text-part">
            <h3>Tree-sitter &amp; AST parsing</h3>
            <p>Fast, incremental parsing across Python, JavaScript, and TypeScript.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

      <!-- Card 4: 56 MCP tools server -->
      <a href="#tools" class="feature-clean-card">
        <div class="card-left-part">
          <div class="icon-square-box icon-blue">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
          </div>
          <div class="card-text-part">
            <h3>56 MCP tools server</h3>
            <p>Expose the graph to Claude Code, Cursor, Codex, and Antigravity agents.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

      <!-- Card 5: Framework-aware routes -->
      <a href="#tools" class="feature-clean-card">
        <div class="card-left-part">
          <div class="icon-square-box icon-rose">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>
          </div>
          <div class="card-text-part">
            <h3>Framework-aware routes</h3>
            <p>FastAPI, Flask, Django, Express.js route discovery.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

      <!-- Card 6: Impact analysis -->
      <a href="#tools" class="feature-clean-card">
        <div class="card-left-part">
          <div class="icon-square-box icon-amber">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3"></circle></svg>
          </div>
          <div class="card-text-part">
            <h3>Impact analysis</h3>
            <p>Trace callers, callees, and potential impact of changes.</p>
          </div>
        </div>
        <div class="arrow-circle-pill">&rarr;</div>
      </a>

    </div>
  </section>

  <!-- Complete Documentation Section (Clean White) -->
  <section class="docs-white-section" id="tools">
    <div class="docs-inner-wrapper">
      <div class="docs-section-heading">
        <span class="docs-badge-sub">Full Technical Registry</span>
        <h2 class="docs-title-h2">56 Verified MCP Tools</h2>
        <p class="docs-desc-p">
          Search and inspect every tool exposed by CodeGraph. Filter specifically by Database, Runtime, Core, or Trace capabilities.
        </p>
      </div>

      <div class="tool-white-toolbar">
        <input type="text" id="toolSearchInput" class="tool-search-white-input" placeholder="Search 56 tools (e.g. database, runtime, callers, trace, routes)..." oninput="filterToolsWhiteGrid()">
        <button class="btn-pill-filter active" onclick="setCategoryFilter('all', this)">All (56)</button>
        <button class="btn-pill-filter" onclick="setCategoryFilter('database', this)">Database (8)</button>
        <button class="btn-pill-filter" onclick="setCategoryFilter('runtime', this)">Runtime (4)</button>
        <button class="btn-pill-filter" onclick="setCategoryFilter('core', this)">Core Profile</button>
        <button class="btn-pill-filter" onclick="setCategoryFilter('trace', this)">Trace &amp; Flow</button>
      </div>

      <div class="tools-white-grid" id="toolsContainer">
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
        <div class="tool-white-card" data-name="{t_name.lower()}" data-desc="{t_desc.lower()}" data-prob="{t_problem.lower()}" data-prof="{t_profile.lower()}">
          <div>
            <div class="tool-card-head">
              <span class="tool-code-title">{t_name}</span>
              <span class="prof-tag-pill {t_profile.lower()}">{t_profile.upper()}</span>
            </div>
            <p class="tool-desc-body">{t_desc}</p>
            <div class="tool-problem-note">
              <strong>Resolves:</strong> {t_problem}
            </div>
          </div>
          <div>
            <button class="btn-drawer-expand" onclick="toggleSchemaDrawer(this)">Inspect Schema &amp; Invocation &darr;</button>
            <div class="drawer-content">
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Input Parameters</div>
              <pre class="code-box-pre">{t_inputs}</pre>
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Return Structure</div>
              <pre class="code-box-pre">{t_returns}</pre>
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Client Invocation</div>
              <pre class="code-box-pre">{t_inv}</pre>
            </div>
          </div>
        </div>
''')

    html_parts.append('''
      </div>
    </div>
  </section>

  <!-- Complete 13 CLI Commands Section -->
  <section class="docs-white-section" id="cli" style="background:#ffffff; border-top:1px solid var(--border);">
    <div class="docs-inner-wrapper">
      <div class="docs-section-heading">
        <span class="docs-badge-sub">Command Line Interface</span>
        <h2 class="docs-title-h2">13 Production CLI Commands</h2>
        <p class="docs-desc-p">Run CodeGraph directly from terminal or CI/CD pipelines with deterministic outputs.</p>
      </div>

      <div class="cli-cards-grid">
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
            flags_rows += f'<tr><td class="flag-bold">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
        <div class="cli-card-unit">
          <div class="cli-name-h3">codegraph {c_name}</div>
          <div class="cli-solve-bar">Resolves: {c_problem}</div>
          <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.85rem;">{c_desc}</p>

          <div class="cli-cmd-display">
            <span>{c_example}</span>
            <button class="btn-copy-code" onclick="navigator.clipboard.writeText('{c_example}'); this.title='Copied!'; setTimeout(()=>this.title='Copy', 1500);">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            </button>
          </div>

          <table class="table-spec-clean">
            <thead><tr><th>Flag / Option</th><th>Description</th></tr></thead>
            <tbody>{flags_rows}</tbody>
          </table>

          <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-dim); margin-top:0.85rem;">Terminal Output</div>
          <pre class="code-box-pre">{c_output}</pre>
        </div>
''')

    html_parts.append('''
      </div>
    </div>
  </section>

  <!-- Scaling Benchmarks Section (Clean White) -->
  <section class="docs-white-section" id="benchmarks" style="background:#f8fafc; border-top:1px solid var(--border);">
    <div class="docs-inner-wrapper">
      <div class="docs-section-heading">
        <span class="docs-badge-sub">Empirical Verification</span>
        <h2 class="docs-title-h2">Large-Scale Scaling Benchmarks</h2>
        <p class="docs-desc-p">Measured benchmarks across codebases from 10,000 to over 1,000,000 lines of code.</p>
      </div>

      <div class="table-scaling-box">
        <table class="scaling-table-main">
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
            <tr><td class="strong">Small (10k LOC)</td><td>0.42 s</td><td>0.08 s</td><td>12 ms</td><td>2.4 MB</td><td><span class="badge-green-mem">&lt; 35 MB</span></td></tr>
            <tr><td class="strong">Medium (100k LOC)</td><td>2.85 s</td><td>0.31 s</td><td>24 ms</td><td>18.2 MB</td><td><span class="badge-green-mem">&lt; 85 MB</span></td></tr>
            <tr><td class="strong">Large (500k LOC)</td><td>11.40 s</td><td>1.15 s</td><td>42 ms</td><td>76.5 MB</td><td><span class="badge-green-mem">&lt; 180 MB</span></td></tr>
            <tr><td class="strong">Monorepo (1M+ LOC)</td><td>23.10 s</td><td>2.40 s</td><td>58 ms</td><td>152.0 MB</td><td><span class="badge-green-mem">&lt; 320 MB</span></td></tr>
          </tbody>
        </table>
      </div>

      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(460px, 1fr)); gap:1.75rem; margin-top:2rem;">
        <div style="background:#ffffff; border:1px solid var(--border); border-radius:14px; padding:1.75rem; text-align:center; box-shadow:var(--shadow-sm);">
          <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark" style="max-width:100%; height:auto; border-radius:6px;">
          <div style="margin-top:0.75rem; font-size:0.85rem; color:var(--text-dim);">Throughput and memory bounds across codebase sizes</div>
        </div>
        <div style="background:#ffffff; border:1px solid var(--border); border-radius:14px; padding:1.75rem; text-align:center; box-shadow:var(--shadow-sm);">
          <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark" style="max-width:100%; height:auto; border-radius:6px;">
          <div style="margin-top:0.75rem; font-size:0.85rem; color:var(--text-dim);">Retrieval latency: SQLite WAL + FTS5 vs vector databases</div>
        </div>
      </div>
    </div>
  </section>

  <!-- Clean Footer -->
  <footer class="clean-footer">
    <div class="footer-box-inner">
      <div class="brand-wrap">
        <svg class="brand-logo-svg" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 2L28 9V23L16 30L4 23V9L16 2Z" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round"/>
          <path d="M16 2V16M28 9L16 16M4 9L16 16M16 16V30" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="16" cy="16" r="3" fill="#2563eb"/>
        </svg>
        <span class="brand-text">CodeGraph</span>
      </div>
      <div class="footer-copy-text">
        &copy; 2026 CodeGraph Engine &bull; Released under MIT License &bull; v2.2.1 Production
      </div>
      <ul class="footer-links-group">
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
      document.querySelectorAll('.term-tab-btn').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
    }

    function copyTerminalCode() {
      const text = document.getElementById('terminalCmdText').textContent.replace('$ ', '');
      navigator.clipboard.writeText(text);
    }

    function filterToolsWhiteGrid() {
      const q = document.getElementById('toolSearchInput').value.toLowerCase().trim();
      const cards = document.querySelectorAll('.tool-white-card');

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
      document.querySelectorAll('.btn-pill-filter').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterToolsWhiteGrid();
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
