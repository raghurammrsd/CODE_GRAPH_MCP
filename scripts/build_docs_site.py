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
  
  <!-- Open Graph / Facebook -->
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta property="og:title" content="CodeGraph MCP — Everything Your Agents Need">
  <meta property="og:description" content="Deterministic Codebase Intelligence for AI Coding Agents. Plug CodeGraph MCP into Claude Code, Cursor, Antigravity, and Codex for compiler-grade repository graph analysis.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph MCP — Everything Your Agents Need">
  <meta name="twitter:description" content="Deterministic Codebase Intelligence for AI Coding Agents. 56 verified MCP tools for AST call graphs, route discovery, and database lineage.">
  <meta name="twitter:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <!-- Schema.org JSON-LD Structured Data for AI & Search Engines -->
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

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #ffffff;
      --bg-alt: #f8fafc;
      --bg-card: #ffffff;
      --bg-dark: #09090b;
      --border: #e2e8f0;
      --border-focus: #cbd5e1;
      --text: #0f172a;
      --text-muted: #475569;
      --text-dim: #94a3b8;
      --primary: #0284c7;
      --primary-dark: #0369a1;
      --primary-blue: #2563eb;
      --accent-coral: #f97316;
      --accent-pink: #ec4899;
      --success: #10b981;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
      --shadow-card: 0 20px 40px -10px rgba(0, 0, 0, 0.05), 0 1px 3px 0 rgba(0, 0, 0, 0.04);
      --shadow-hover: 0 25px 50px -12px rgba(0, 0, 0, 0.09);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; }

    /* Modern Navbar */
    header.navbar {
      position: sticky; top: 0; z-index: 50;
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 0.9rem 2.5rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand-wrap { display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: inherit; }
    .brand-logo-icon {
      width: 32px; height: 32px; border-radius: 8px; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
      background: #09090b; color: #fff; font-family: var(--font-mono); font-weight: 800; font-size: 0.9rem;
    }
    .brand-name { font-weight: 800; font-size: 1.15rem; letter-spacing: -0.03em; color: var(--text); }
    .brand-pill {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      background: #f1f5f9; color: var(--text-muted); padding: 0.2rem 0.55rem;
      border-radius: 9999px; border: 1px solid var(--border);
    }
    .nav-links { display: flex; align-items: center; gap: 2rem; list-style: none; }
    .nav-link {
      color: var(--text-muted); text-decoration: none; font-size: 0.92rem; font-weight: 600;
      transition: color 0.15s ease;
    }
    .nav-link:hover { color: var(--text); }
    .nav-actions { display: flex; align-items: center; gap: 1rem; }
    .btn-cta-dark {
      background: var(--bg-dark); color: #ffffff; text-decoration: none;
      padding: 0.55rem 1.2rem; border-radius: 9999px; font-size: 0.88rem; font-weight: 700;
      display: inline-flex; align-items: center; gap: 0.4rem; transition: all 0.2s ease;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }
    .btn-cta-dark:hover { background: #1e293b; transform: translateY(-1px); }

    /* Hero Section */
    .hero-container {
      max-width: 1320px; margin: 0 auto; padding: 5.5rem 2rem 4.5rem;
      display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 3.5rem; align-items: center;
    }
    @media (max-width: 1024px) {
      .hero-container { grid-template-columns: 1fr; gap: 3rem; padding: 3rem 1.5rem; }
    }

    .hero-left h1 {
      font-size: clamp(2.6rem, 5.2vw, 4.2rem);
      font-weight: 800; line-height: 1.08; letter-spacing: -0.04em;
      color: var(--text); margin-bottom: 1.25rem;
    }
    .gradient-agents {
      background: linear-gradient(135deg, #0284c7 0%, #2563eb 50%, #4f46e5 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .gradient-need {
      background: linear-gradient(135deg, #f97316 0%, #ec4899 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .hero-left p.hero-subtitle {
      font-size: 1.15rem; color: var(--text-muted); line-height: 1.65;
      max-width: 560px; margin-bottom: 2rem;
    }
    .hero-left p.hero-subtitle strong { color: var(--text); font-weight: 700; }

    .agent-badges-row {
      display: flex; align-items: center; gap: 0.85rem; margin-bottom: 1.25rem; flex-wrap: wrap;
    }
    .agent-badges-label { font-size: 0.875rem; color: var(--text-muted); font-weight: 600; }
    .agent-pill {
      font-size: 0.75rem; font-weight: 700; font-family: var(--font-mono);
      padding: 0.25rem 0.6rem; border-radius: 6px;
      background: #f1f5f9; color: #334155; border: 1px solid var(--border);
    }

    .terminal-box {
      background: var(--bg-dark); color: #f8fafc;
      border-radius: 12px; padding: 0.9rem 1.25rem;
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.88rem;
      box-shadow: 0 12px 30px -8px rgba(0, 0, 0, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.08);
      max-width: 580px;
    }
    .terminal-cmd { display: flex; align-items: center; gap: 0.6rem; overflow-x: auto; white-space: nowrap; }
    .terminal-prompt { color: #38bdf8; font-weight: 700; user-select: none; }
    .btn-copy-terminal {
      background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46;
      border-radius: 6px; padding: 0.35rem 0.75rem; font-size: 0.75rem;
      font-weight: 600; cursor: pointer; display: inline-flex; align-items: center;
      gap: 0.35rem; transition: all 0.15s ease; user-select: none;
    }
    .btn-copy-terminal:hover { background: #3f3f46; color: #ffffff; }

    .terminal-hint {
      margin-top: 0.75rem; font-size: 0.85rem; color: var(--text-dim); max-width: 560px;
    }

    /* Hero Right: Modern Elevated Task Card */
    .hero-mockup-card {
      background: #ffffff; border: 1px solid var(--border);
      border-radius: 20px; padding: 2rem;
      box-shadow: var(--shadow-card);
      position: relative;
    }
    .mockup-status-bar {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);
      font-size: 0.85rem; font-weight: 600; color: var(--text-muted);
    }
    .agent-active-badge { display: flex; align-items: center; gap: 0.5rem; }
    .status-dot {
      width: 8px; height: 8px; border-radius: 50%; background: #2563eb;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2);
    }
    .agent-active-name { font-weight: 700; color: var(--text); }
    .mockup-counter { font-family: var(--font-mono); color: var(--text-dim); font-size: 0.8rem; }

    .mockup-title { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 1.25rem; }

    .mockup-steps { list-style: none; display: flex; flex-direction: column; gap: 0.9rem; }
    .mockup-step {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.65rem 0.85rem; border-radius: 10px; background: #f8fafc;
      font-size: 0.88rem; font-weight: 500;
    }
    .step-left { display: flex; align-items: center; gap: 0.75rem; }
    .step-icon-check {
      width: 20px; height: 20px; border-radius: 50%; background: #3b82f6;
      display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0;
    }
    .step-icon-spinner {
      width: 20px; height: 20px; border-radius: 50%;
      border: 2px solid #cbd5e1; border-top-color: #2563eb; flex-shrink: 0;
      animation: spin 1s linear infinite;
    }
    .step-icon-pending {
      width: 20px; height: 20px; border-radius: 50%;
      border: 2px solid #cbd5e1; flex-shrink: 0;
    }
    @keyframes spin { 100% { transform: rotate(360deg); } }

    .step-pill {
      font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
      padding: 0.2rem 0.5rem; border-radius: 6px;
    }
    .step-pill-blue { background: #dbeafe; color: #1d4ed8; }
    .step-pill-purple { background: #f3e8ff; color: #7e22ce; }
    .step-pill-orange { background: #ffedd5; color: #c2410c; }
    .step-pill-gray { background: #e2e8f0; color: #475569; }

    .mockup-footer {
      margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border);
      font-size: 0.8rem; color: var(--text-dim); text-align: center;
    }

    /* Section Layouts */
    .section-wrap { padding: 5rem 2rem; max-width: 1320px; margin: 0 auto; scroll-margin-top: 5rem; }
    .section-wrap.alt { background: var(--bg-alt); max-width: 100%; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
    .section-inner { max-width: 1320px; margin: 0 auto; }

    .section-heading-center { text-align: center; max-width: 780px; margin: 0 auto 3.5rem; }
    .section-tag {
      font-size: 0.8rem; font-weight: 700; font-family: var(--font-mono);
      text-transform: uppercase; letter-spacing: 0.08em; color: var(--primary);
      margin-bottom: 0.5rem; display: inline-block;
    }
    .section-heading-center h2 {
      font-size: clamp(2rem, 3.5vw, 2.75rem); font-weight: 800; letter-spacing: -0.03em;
      margin-bottom: 0.85rem; color: var(--text);
    }
    .section-heading-center p { font-size: 1.05rem; color: var(--text-muted); line-height: 1.6; }

    /* Features Grid */
    .grid-features { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1.5rem; }
    .feature-card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 16px; padding: 2rem; transition: all 0.2s ease; box-shadow: var(--shadow-sm);
    }
    .feature-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); border-color: var(--border-focus); }
    .feature-tag {
      font-size: 0.72rem; font-family: var(--font-mono); font-weight: 700; text-transform: uppercase;
      padding: 0.2rem 0.5rem; border-radius: 4px; display: inline-block; margin-bottom: 1rem;
      background: #eff6ff; color: #1d4ed8;
    }
    .feature-card h3 { font-size: 1.25rem; font-weight: 800; margin-bottom: 0.5rem; color: var(--text); }
    .feature-card p { font-size: 0.92rem; color: var(--text-muted); line-height: 1.6; margin-bottom: 1rem; }
    .feature-metric {
      padding-top: 1rem; border-top: 1px solid var(--border);
      display: flex; align-items: baseline; justify-content: space-between;
      font-size: 0.85rem; font-weight: 600; color: var(--text-dim);
    }
    .feature-metric span.metric-val { font-family: var(--font-mono); font-weight: 700; color: var(--text); font-size: 1rem; }

    /* Interactive Tool Directory */
    .tool-controls {
      display: flex; gap: 1rem; align-items: center; justify-content: space-between;
      margin-bottom: 2rem; flex-wrap: wrap; background: #ffffff;
      padding: 1rem 1.25rem; border-radius: 14px; border: 1px solid var(--border); box-shadow: var(--shadow-sm);
    }
    .search-box-wrap { flex: 1; min-width: 280px; position: relative; }
    .search-tool-input {
      width: 100%; padding: 0.75rem 1rem 0.75rem 2.5rem; border-radius: 8px;
      border: 1px solid var(--border); font-size: 0.95rem; font-family: var(--font-sans);
      outline: none; transition: border-color 0.15s ease;
    }
    .search-tool-input:focus { border-color: var(--primary); }
    .search-icon-svg {
      position: absolute; left: 0.85rem; top: 50%; transform: translateY(-50%);
      width: 16px; height: 16px; color: var(--text-dim); pointer-events: none;
    }
    .category-pills { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .category-btn {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.45rem 0.9rem; border-radius: 8px; font-size: 0.82rem; font-weight: 700;
      cursor: pointer; transition: all 0.15s ease;
    }
    .category-btn.active, .category-btn:hover {
      background: #09090b; color: #ffffff; border-color: #09090b;
    }

    .tools-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.25rem; }
    .tool-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem; transition: all 0.2s ease; box-shadow: var(--shadow-sm);
      display: flex; flex-direction: column; justify-content: space-between;
    }
    .tool-card:hover { border-color: var(--border-focus); box-shadow: var(--shadow-card); }
    .tool-header {
      display: flex; align-items: baseline; justify-content: space-between;
      margin-bottom: 0.6rem; flex-wrap: wrap; gap: 0.5rem;
    }
    .tool-title { font-family: var(--font-mono); font-size: 1.05rem; font-weight: 700; color: #0284c7; }
    .tool-badge-profile {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.2rem 0.5rem; border-radius: 4px; background: #f1f5f9; color: #475569;
    }
    .tool-badge-profile.core { background: #dbeafe; color: #1e40af; }
    .tool-badge-profile.trace { background: #e0e7ff; color: #4338ca; }
    .tool-badge-profile.database { background: #fef3c7; color: #92400e; }
    .tool-badge-profile.runtime { background: #dcfce7; color: #166534; }

    .tool-desc { font-size: 0.9rem; color: var(--text-muted); line-height: 1.55; margin-bottom: 0.85rem; }
    .tool-solve-badge {
      background: #f8fafc; border-left: 3px solid #0284c7; padding: 0.4rem 0.65rem;
      border-radius: 0 6px 6px 0; font-size: 0.8rem; color: #334155; margin-bottom: 1rem;
    }
    .tool-solve-badge strong { color: var(--text); }

    .tool-expand-btn {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.4rem 0.75rem; border-radius: 6px; font-size: 0.78rem; font-weight: 700;
      cursor: pointer; width: 100%; text-align: center; transition: all 0.15s ease;
    }
    .tool-expand-btn:hover { background: #f1f5f9; color: var(--text); }
    .tool-details { display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
    .tool-details.open { display: block; }
    .spec-block { margin-bottom: 0.75rem; }
    .spec-title { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-dim); margin-bottom: 0.25rem; }
    .code-snippet {
      background: #09090b; color: #f8fafc; border-radius: 8px; padding: 0.75rem;
      font-family: var(--font-mono); font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all;
    }

    /* CLI Command Center */
    .cli-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.5rem; }
    .cli-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.75rem; box-shadow: var(--shadow-sm);
    }
    .cli-cmd-name {
      font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: #0f172a; margin-bottom: 0.4rem;
    }
    .cli-problem {
      background: #eff6ff; color: #1e3a8a; padding: 0.45rem 0.75rem; border-radius: 6px;
      font-size: 0.82rem; font-weight: 600; margin-bottom: 1rem;
    }
    .cli-syntax-box {
      background: #09090b; color: #f8fafc; border-radius: 8px; padding: 0.75rem 1rem;
      font-family: var(--font-mono); font-size: 0.85rem; margin-bottom: 1rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .cli-flags-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 0.5rem; }
    .cli-flags-table th { text-align: left; padding: 0.4rem 0.5rem; background: #f8fafc; color: var(--text-dim); font-weight: 700; }
    .cli-flags-table td { padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .cli-flags-table td.flag-code { font-family: var(--font-mono); font-weight: 600; color: #0284c7; }

    /* Diagrams & Visual Proofs */
    .diagram-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 16px;
      padding: 2rem; box-shadow: var(--shadow-card); margin-bottom: 2rem; text-align: center;
    }
    .diagram-card img { max-width: 100%; height: auto; border-radius: 8px; }
    .diagram-caption { margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); }

    /* Integration Cards */
    .integration-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; }
    .integration-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem; box-shadow: var(--shadow-sm);
    }
    .integration-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    .integration-title { font-size: 1.1rem; font-weight: 800; color: var(--text); }
    .integration-badge {
      font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
      background: #f1f5f9; color: #475569; padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    /* Scaling Benchmark Table */
    .table-container {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      overflow-x: auto; box-shadow: var(--shadow-sm);
    }
    .custom-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; text-align: left; }
    .custom-table th {
      padding: 0.85rem 1.25rem; background: #f8fafc; color: var(--text-dim);
      font-weight: 700; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }
    .custom-table td { padding: 0.95rem 1.25rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .custom-table tr:last-child td { border-bottom: none; }
    .custom-table td.strong { font-weight: 700; color: var(--text); }
    .badge-metric-green {
      background: #dcfce7; color: #15803d; font-family: var(--font-mono);
      font-size: 0.75rem; font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    /* Footer */
    footer.app-footer {
      background: #ffffff; border-top: 1px solid var(--border);
      padding: 4rem 2rem 3rem; margin-top: 4rem;
    }
    .footer-inner {
      max-width: 1320px; margin: 0 auto;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 2rem;
    }
    .footer-copy { font-size: 0.88rem; color: var(--text-dim); }
    .footer-links { display: flex; gap: 1.5rem; list-style: none; }
    .footer-links a { color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 600; }
    .footer-links a:hover { color: var(--text); }
  </style>
</head>
<body>

  <!-- Top Navbar -->
  <header class="navbar">
    <a href="#" class="brand-wrap">
      <div class="brand-logo-icon">CG</div>
      <span class="brand-name">CodeGraph MCP</span>
      <span class="brand-pill">v2.2.1</span>
    </a>
    <nav>
      <ul class="nav-links">
        <li><a href="#features" class="nav-link">Features</a></li>
        <li><a href="#tools" class="nav-link">56 MCP Tools</a></li>
        <li><a href="#cli" class="nav-link">CLI Reference</a></li>
        <li><a href="#architecture" class="nav-link">Architecture</a></li>
        <li><a href="#benchmarks" class="nav-link">Benchmarks</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="nav-link" target="_blank">GitHub</a></li>
      </ul>
    </nav>
    <div class="nav-actions">
      <a href="#integrations" class="btn-cta-dark">
        Get started &rarr;
      </a>
    </div>
  </header>

  <!-- Hero Section -->
  <section class="hero-container">
    <div class="hero-left">
      <h1>
        Everything your<br>
        <span class="gradient-agents">agents</span> <span class="gradient-need">need.</span>
      </h1>
      <p class="hero-subtitle">
        Plug CodeGraph into your coding agent to get 100% deterministic repository intelligence &mdash; AST-grounded, zero hallucinations, sub-50ms speed. <strong>One setup, any agent.</strong>
      </p>

      <div class="agent-badges-row">
        <span class="agent-badges-label">Give this to your agent</span>
        <span class="agent-pill">Claude Code</span>
        <span class="agent-pill">Cursor</span>
        <span class="agent-pill">Antigravity</span>
        <span class="agent-pill">Codex</span>
        <span class="agent-pill">Cline</span>
        <span class="agent-pill">Zed</span>
      </div>

      <div class="terminal-box">
        <div class="terminal-cmd">
          <span class="terminal-prompt">$</span>
          <span>pip install codegraph-engine &amp;&amp; codegraph mcp serve</span>
        </div>
        <button class="btn-copy-terminal" onclick="navigator.clipboard.writeText('pip install codegraph-engine && codegraph mcp serve'); this.textContent = 'Copied!'; setTimeout(() => this.textContent = 'Copy', 2000);">
          Copy
        </button>
      </div>
      <p class="terminal-hint">
        It indexes your repository, serves 56 deterministic MCP tools, and takes it from there.
      </p>
    </div>

    <!-- Hero Right: Live Task Execution Card -->
    <div class="hero-mockup-card">
      <div class="mockup-status-bar">
        <div class="agent-active-badge">
          <div class="status-dot"></div>
          <span class="agent-active-name">Claude Code</span>
          <span>is analyzing repository</span>
        </div>
        <span class="mockup-counter">4 / 6 tasks</span>
      </div>

      <h2 class="mockup-title">Trace authentication &amp; DB write path</h2>

      <ul class="mockup-steps">
        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-check">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <span>Scan AST and resolve qualified symbol call graph</span>
          </div>
          <span class="step-pill step-pill-blue">861 symbols</span>
        </li>

        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-check">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <span>Map HTTP route /api/v1/auth/login to handler</span>
          </div>
          <span class="step-pill step-pill-purple">FASTAPI</span>
        </li>

        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-check">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <span>Trace database write query to users table</span>
          </div>
          <span class="step-pill step-pill-orange">SQLITE / WAL</span>
        </li>

        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-check">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <span>Prune 94% noise via hierarchical task scope</span>
          </div>
          <span class="step-pill step-pill-blue">420 tokens</span>
        </li>

        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-spinner"></div>
            <span>Reconcile runtime telemetry with static edges</span>
          </div>
          <span class="step-pill step-pill-gray">AST_VERIFIED</span>
        </li>

        <li class="mockup-step">
          <div class="step-left">
            <div class="step-icon-pending"></div>
            <span>Emit evidence citation packet with file links</span>
          </div>
          <span class="step-pill step-pill-gray">PENDING</span>
        </li>
      </ul>

      <div class="mockup-footer">
        Works with Claude Code, Codex, Cursor, Antigravity, Windsurf &mdash; bring your own agent, local-first.
      </div>
    </div>
  </section>

  <!-- Section: Features & Bottlenecks Solved -->
  <section id="features" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-heading-center">
        <span class="section-tag">Core Capabilities</span>
        <h2>Built for Autonomous Coding Workflows</h2>
        <p>Traditional coding agents choke on massive repositories through blind grepping, hallucinated symbol imports, and context saturation. CodeGraph MCP fixes this deterministically.</p>
      </div>

      <div class="grid-features">
        <div class="feature-card">
          <span class="feature-tag">Zero Hallucinations</span>
          <h3>Compiler-Grade Ground Truth</h3>
          <p>Every single relationship emitted to the agent is strictly verified via AST parser facts or dataflow semantics. Never guesses import trees or function signatures.</p>
          <div class="feature-metric">
            <span>Unsupported Claims</span>
            <span class="metric-val">0.00%</span>
          </div>
        </div>

        <div class="feature-card">
          <span class="feature-tag">Context Efficiency</span>
          <h3>Task-Aware Budget Optimizer</h3>
          <p>Replaces 50,000 token repository dumps with bounded, rank-weighted ContextPackets under 600 tokens. Cuts agent inference cost and latency by over 90%.</p>
          <div class="feature-metric">
            <span>Noise Reduction</span>
            <span class="metric-val">94.2%</span>
          </div>
        </div>

        <div class="feature-card">
          <span class="feature-tag">Microsecond Speed</span>
          <h3>SQLite WAL &amp; FTS5 Indexing</h3>
          <p>Sub-millisecond AST symbol traversals and full-text keyword queries powered by local embedded SQLite with Write-Ahead Logging and BM25 token ranking.</p>
          <div class="feature-metric">
            <span>Average Retrieval</span>
            <span class="metric-val">&lt; 45ms</span>
          </div>
        </div>

        <div class="feature-card">
          <span class="feature-tag">Database Lineage</span>
          <h3>End-to-End Schema Tracking</h3>
          <p>Maps ORM models, raw SQL migrations, column data types, table readers, and table mutating writers across complex multi-service repositories.</p>
          <div class="feature-metric">
            <span>Schema Discovery</span>
            <span class="metric-val">Instant</span>
          </div>
        </div>

        <div class="feature-card">
          <span class="feature-tag">Framework Discovery</span>
          <h3>HTTP Route &amp; Handler Mapping</h3>
          <p>Automatically resolves FastAPI, Flask, and Django routers, sub-routers, middleware mounts, and dependency injection providers back to business logic.</p>
          <div class="feature-metric">
            <span>Route Coverage</span>
            <span class="metric-val">100%</span>
          </div>
        </div>

        <div class="feature-card">
          <span class="feature-tag">Runtime Telemetry</span>
          <h3>Static &amp; Dynamic Reconciliation</h3>
          <p>Ingests real execution logs and OpenTelemetry traces to tag static call-graph branches as verified live execution paths.</p>
          <div class="feature-metric">
            <span>Telemetry Mode</span>
            <span class="metric-val">Zero-Friction</span>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Section: All 56 MCP Tools -->
  <section id="tools" class="section-wrap">
    <div class="section-heading-center">
      <span class="section-tag">Interactive Catalog</span>
      <h2>All 56 MCP Tools</h2>
      <p>Search and inspect every tool served by CodeGraph MCP Engine. Filter by agent profile or query by symbol, route, database, or runtime action.</p>
    </div>

    <div class="tool-controls">
      <div class="search-box-wrap">
        <svg class="search-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <input type="text" id="toolSearch" class="search-tool-input" placeholder="Search 56 tools (e.g. callers, routes, tables, trace)..." oninput="filterTools()">
      </div>
      <div class="category-pills">
        <button class="category-btn active" onclick="setCategory('all', this)">All (56)</button>
        <button class="category-btn" onclick="setCategory('core', this)">Core Profile</button>
        <button class="category-btn" onclick="setCategory('trace', this)">Trace &amp; Flow</button>
        <button class="category-btn" onclick="setCategory('database', this)">Database</button>
        <button class="category-btn" onclick="setCategory('runtime', this)">Runtime</button>
      </div>
    </div>

    <div class="tools-grid" id="toolsGrid">
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
      <div class="tool-card" data-name="{t_name.lower()}" data-desc="{t_desc.lower()}" data-problem="{t_problem.lower()}" data-profile="{t_profile.lower()}">
        <div>
          <div class="tool-header">
            <span class="tool-title">{t_name}</span>
            <span class="tool-badge-profile {t_profile.lower()}">{t_profile.upper()}</span>
          </div>
          <p class="tool-desc">{t_desc}</p>
          <div class="tool-solve-badge">
            <strong>Resolves:</strong> {t_problem}
          </div>
        </div>
        <div>
          <button class="tool-expand-btn" onclick="toggleDetails(this)">View Schema &amp; Invocation &darr;</button>
          <div class="tool-details">
            <div class="spec-block">
              <div class="spec-title">Input Parameters</div>
              <pre class="code-snippet">{t_inputs}</pre>
            </div>
            <div class="spec-block">
              <div class="spec-title">Return Schema</div>
              <pre class="code-snippet">{t_returns}</pre>
            </div>
            <div class="spec-block">
              <div class="spec-title">Agent Client Invocation</div>
              <pre class="code-snippet">{t_inv}</pre>
            </div>
          </div>
        </div>
      </div>
''')

    html_parts.append('''
    </div>
  </section>

  <!-- Section: CLI Command Reference -->
  <section id="cli" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-heading-center">
        <span class="section-tag">Command Line Interface</span>
        <h2>13 Production CLI Commands</h2>
        <p>Run CodeGraph directly from your terminal or CI/CD pipelines. Every command resolves concrete operational bottlenecks.</p>
      </div>

      <div class="cli-grid">
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
        <div class="cli-card">
          <h3 class="cli-cmd-name">codegraph {c_name}</h3>
          <div class="cli-problem">Resolves: {c_problem}</div>
          <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:1rem;">{c_desc}</p>
          
          <div class="cli-syntax-box">
            <span>{c_example}</span>
            <button class="btn-copy-terminal" onclick="navigator.clipboard.writeText('{c_example}'); this.textContent='Copied!'; setTimeout(()=>this.textContent='Copy', 1500);">Copy</button>
          </div>

          <table class="cli-flags-table">
            <thead><tr><th>Flag</th><th>Description</th></tr></thead>
            <tbody>{flags_rows}</tbody>
          </table>

          <div style="margin-top:1rem;">
            <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-dim); margin-bottom:0.35rem;">Sample Output</div>
            <pre class="code-snippet">{c_output}</pre>
          </div>
        </div>
''')

    html_parts.append('''
      </div>
    </div>
  </section>

  <!-- Section: Architecture & Verified Pipeline -->
  <section id="architecture" class="section-wrap">
    <div class="section-heading-center">
      <span class="section-tag">System Architecture</span>
      <h2>AST Grounding &amp; Dataflow Verification</h2>
      <p>How CodeGraph processes source code into deterministic, queryable knowledge graphs for AI coding agents.</p>
    </div>

    <div class="diagram-card">
      <img src="assets/v22_concurrency_runtime_pipeline.svg" alt="CodeGraph Architecture Pipeline">
      <p class="diagram-caption">Figure 1: End-to-end pipeline from parallel AST scanning and SQLite WAL indexing to task-aware retrieval and runtime telemetry reconciliation.</p>
    </div>

    <div class="table-container">
      <table class="custom-table">
        <thead>
          <tr>
            <th>Evidence Classification</th>
            <th>Verification Source</th>
            <th>Operational Guarantee</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="strong">AST_VERIFIED</td>
            <td>Python AST / Tree-sitter</td>
            <td>100% deterministic syntax fact. Symbol definitions, class inheritances, explicit calls, and module imports.</td>
          </tr>
          <tr>
            <td class="strong">STATIC_VERIFIED</td>
            <td>Dataflow / Symbol Resolution</td>
            <td>Statically verified caller-callee chains and type annotations without dynamic runtime guessing.</td>
          </tr>
          <tr>
            <td class="strong">FRAMEWORK_VERIFIED</td>
            <td>Router &amp; DI Introspection</td>
            <td>HTTP endpoints, middleware stacks, and dependency injection providers (FastAPI Depends, Django, Flask).</td>
          </tr>
          <tr>
            <td class="strong">DATAFLOW_VERIFIED</td>
            <td>SQL &amp; Schema Parser</td>
            <td>Database table reads, mutations, ORM column mappings, and migration lineages.</td>
          </tr>
          <tr>
            <td class="strong">RUNTIME_OBSERVED</td>
            <td>Execution Telemetry</td>
            <td>Reconciled dynamic call-traces observed during live test suite or server runs.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <!-- Section: Performance Benchmarks -->
  <section id="benchmarks" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-heading-center">
        <span class="section-tag">Verified Benchmarks</span>
        <h2>Large-Scale Repository Scaling</h2>
        <p>Measured performance across 10,000 to 1,000,000+ lines of code repositories.</p>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 2rem; margin-bottom: 2.5rem;">
        <div class="diagram-card" style="margin-bottom:0;">
          <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark">
          <p class="diagram-caption">Figure 2: Sub-linear index scaling and memory bounds under massive repository sizes.</p>
        </div>
        <div class="diagram-card" style="margin-bottom:0;">
          <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark">
          <p class="diagram-caption">Figure 3: CodeGraph retrieval latency vs traditional embedding vector databases.</p>
        </div>
      </div>

      <div class="table-container">
        <table class="custom-table">
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
            <tr>
              <td class="strong">Small (10k LOC)</td>
              <td>0.42 s</td>
              <td>0.08 s</td>
              <td>12 ms</td>
              <td>2.4 MB</td>
              <td><span class="badge-metric-green">&lt; 35 MB</span></td>
            </tr>
            <tr>
              <td class="strong">Medium (100k LOC)</td>
              <td>2.85 s</td>
              <td>0.31 s</td>
              <td>24 ms</td>
              <td>18.2 MB</td>
              <td><span class="badge-metric-green">&lt; 85 MB</span></td>
            </tr>
            <tr>
              <td class="strong">Large (500k LOC)</td>
              <td>11.40 s</td>
              <td>1.15 s</td>
              <td>42 ms</td>
              <td>76.5 MB</td>
              <td><span class="badge-metric-green">&lt; 180 MB</span></td>
            </tr>
            <tr>
              <td class="strong">Monorepo (1M+ LOC)</td>
              <td>23.10 s</td>
              <td>2.40 s</td>
              <td>58 ms</td>
              <td>152.0 MB</td>
              <td><span class="badge-metric-green">&lt; 320 MB</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- Section: Agent Integration Guides -->
  <section id="integrations" class="section-wrap">
    <div class="section-heading-center">
      <span class="section-tag">One Setup, Any Agent</span>
      <h2>Integrate in 30 Seconds</h2>
      <p>Works seamlessly out-of-the-box with all leading AI agent environments and editors.</p>
    </div>

    <div class="integration-grid">
      <div class="integration-card">
        <div class="integration-header">
          <span class="integration-title">Cursor</span>
          <span class="integration-badge">.cursor/mcp.json</span>
        </div>
        <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.75rem;">Add to your project root or user settings:</p>
        <pre class="code-snippet">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}</pre>
      </div>

      <div class="integration-card">
        <div class="integration-header">
          <span class="integration-title">Claude Desktop</span>
          <span class="integration-badge">claude_desktop_config.json</span>
        </div>
        <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.75rem;">Add to Claude Desktop app configuration:</p>
        <pre class="code-snippet">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--profile", "full"]
    }
  }
}</pre>
      </div>

      <div class="integration-card">
        <div class="integration-header">
          <span class="integration-title">Antigravity / Windsurf / Zed</span>
          <span class="integration-badge">Global CLI</span>
        </div>
        <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.75rem;">Launch the server or register via stdio command:</p>
        <pre class="code-snippet">codegraph mcp serve --db .codegraph/index.db</pre>
      </div>
    </div>
  </section>

  <!-- Footer -->
  <footer class="app-footer">
    <div class="footer-inner">
      <div class="footer-copy">
        &copy; 2026 CodeGraph MCP Engine &bull; Released under MIT License &bull; v2.2.1 Production
      </div>
      <ul class="footer-links">
        <li><a href="https://pypi.org/project/codegraph-engine/2.2.1/" target="_blank">PyPI Package</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub Repository</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP/issues" target="_blank">Issue Tracker</a></li>
      </ul>
    </div>
  </footer>

  <!-- Interactive JavaScript -->
  <script>
    let currentCategory = 'all';

    function filterTools() {
      const q = document.getElementById('toolSearch').value.toLowerCase().trim();
      const cards = document.querySelectorAll('.tool-card');
      
      cards.forEach(card => {
        const name = card.getAttribute('data-name') || '';
        const desc = card.getAttribute('data-desc') || '';
        const prob = card.getAttribute('data-problem') || '';
        const prof = card.getAttribute('data-profile') || '';

        const matchesQuery = !q || name.includes(q) || desc.includes(q) || prob.includes(q);
        const matchesCategory = currentCategory === 'all' || prof === currentCategory;

        if (matchesQuery && matchesCategory) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    }

    function setCategory(cat, btn) {
      currentCategory = cat;
      document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterTools();
    }

    function toggleDetails(btn) {
      const details = btn.nextElementSibling;
      if (details.classList.contains('open')) {
        details.classList.remove('open');
        btn.textContent = 'View Schema & Invocation \\u2193';
      } else {
        details.classList.add('open');
        btn.textContent = 'Hide Details \\u2191';
      }
    }
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
