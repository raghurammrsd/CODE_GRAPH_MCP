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
  <title>CodeGraph MCP Documentation | Deterministic Codebase Intelligence</title>
  <meta name="description" content="Production documentation for CodeGraph MCP Engine (v2.2.1). Compiler-grade AST code relationships, database lineages, route mapping, and runtime telemetry for AI coding agents.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --bg-card: rgba(16, 24, 40, 0.75);
      --bg-card-hover: rgba(23, 35, 59, 0.9);
      --border: rgba(255, 255, 255, 0.08);
      --border-accent: rgba(59, 130, 246, 0.35);
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --primary: #3b82f6;
      --primary-glow: rgba(59, 130, 246, 0.25);
      --emerald: #10b981;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; background: var(--bg); color: var(--text); font-family: var(--font-sans); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; }
    
    .bg-canvas {
      position: fixed; inset: 0; pointer-events: none; z-index: -1;
      background: 
        radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 85% 65%, rgba(16, 185, 129, 0.08) 0%, transparent 45%),
        linear-gradient(to bottom, #090d16 0%, #060911 100%);
    }
    .grid-lines {
      position: fixed; inset: 0; pointer-events: none; z-index: -1; opacity: 0.15;
      background-size: 40px 40px;
      background-image: linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
                        linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
    }

    .app-container { display: flex; flex-direction: column; min-height: 100vh; }
    header.navbar {
      position: sticky; top: 0; z-index: 50;
      backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      background: rgba(9, 13, 22, 0.85);
      border-bottom: 1px solid var(--border);
      padding: 0.75rem 2rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand { display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: inherit; }
    .brand img { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--border); }
    .brand-title { font-weight: 700; font-size: 1.15rem; letter-spacing: -0.02em; }
    .brand-badge {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 600;
      background: rgba(59, 130, 246, 0.15); color: #60a5fa;
      border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 9999px; padding: 0.15rem 0.5rem;
    }
    .nav-links { display: flex; gap: 1.5rem; align-items: center; }
    .nav-link {
      color: var(--text-muted); text-decoration: none; font-size: 0.9rem; font-weight: 500;
      transition: color 0.15s ease;
    }
    .nav-link:hover { color: var(--text); }
    .btn-github {
      background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border);
      color: var(--text); padding: 0.45rem 0.9rem; border-radius: 8px; font-size: 0.85rem;
      font-weight: 600; text-decoration: none; display: flex; align-items: center; gap: 0.5rem;
      transition: all 0.15s ease;
    }
    .btn-github:hover { background: rgba(255, 255, 255, 0.12); border-color: rgba(255, 255, 255, 0.2); }

    .hero {
      padding: 5rem 2rem 3rem; text-align: center; max-width: 1040px; margin: 0 auto;
    }
    .pill-announcement {
      display: inline-flex; align-items: center; gap: 0.5rem;
      background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25);
      color: #34d399; font-size: 0.8rem; font-weight: 600; font-family: var(--font-mono);
      padding: 0.35rem 0.9rem; border-radius: 9999px; margin-bottom: 1.75rem;
    }
    .hero h1 {
      font-size: clamp(2.2rem, 5vw, 3.8rem); font-weight: 800; line-height: 1.15;
      letter-spacing: -0.03em; margin-bottom: 1.25rem;
      background: linear-gradient(135deg, #ffffff 40%, #94a3b8 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .hero p.lead {
      font-size: 1.15rem; color: var(--text-muted); max-width: 780px; margin: 0 auto 2.5rem;
      font-weight: 400; line-height: 1.65;
    }
    .hero-actions { display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 3rem; }
    .btn-primary {
      background: var(--primary); color: #fff; padding: 0.75rem 1.6rem; border-radius: 10px;
      font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 0.5rem;
      box-shadow: 0 4px 20px var(--primary-glow); transition: all 0.2s ease;
    }
    .btn-primary:hover { background: #2563eb; transform: translateY(-1px); }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.05); color: var(--text); border: 1px solid var(--border);
      padding: 0.75rem 1.6rem; border-radius: 10px; font-weight: 600; text-decoration: none;
      transition: all 0.2s ease;
    }
    .btn-secondary:hover { background: rgba(255, 255, 255, 0.1); }

    .quick-install {
      background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border);
      border-radius: 12px; padding: 0.75rem 1.25rem; max-width: 580px; margin: 0 auto;
      display: flex; align-items: center; justify-content: space-between; font-family: var(--font-mono);
      font-size: 0.9rem; color: #cbd5e1;
    }
    .copy-btn {
      background: transparent; border: none; color: var(--text-muted); cursor: pointer;
      font-size: 0.85rem; font-family: var(--font-sans); font-weight: 600; padding: 0.25rem 0.5rem;
      border-radius: 6px; transition: all 0.15s ease;
    }
    .copy-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.1); }

    .content-layout {
      max-width: 1400px; margin: 0 auto; width: 100%;
      display: grid; grid-template-columns: 280px 1fr; gap: 2.5rem;
      padding: 2rem;
    }
    @media (max-width: 960px) {
      .content-layout { grid-template-columns: 1fr; }
      aside.sidebar { display: none; }
    }

    aside.sidebar {
      position: sticky; top: 5.5rem; height: calc(100vh - 7rem);
      overflow-y: auto; padding-right: 1rem;
    }
    .sidebar-section { margin-bottom: 1.5rem; }
    .sidebar-title {
      font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--text-dim); font-weight: 700; margin-bottom: 0.6rem;
    }
    .sidebar-nav { list-style: none; display: flex; flex-direction: column; gap: 0.25rem; }
    .sidebar-link {
      display: block; color: var(--text-muted); text-decoration: none;
      font-size: 0.875rem; padding: 0.4rem 0.75rem; border-radius: 6px;
      transition: all 0.15s ease;
    }
    .sidebar-link:hover, .sidebar-link.active {
      color: #fff; background: rgba(255, 255, 255, 0.06);
    }
    .sidebar-link.active { color: #60a5fa; font-weight: 600; }

    main.main-content { min-width: 0; }
    .doc-section { margin-bottom: 4.5rem; scroll-margin-top: 6rem; }
    .section-header { margin-bottom: 1.75rem; }
    .section-badge {
      display: inline-block; font-size: 0.75rem; font-family: var(--font-mono); font-weight: 600;
      color: var(--primary); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;
    }
    .section-title { font-size: 1.85rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0.5rem; }
    .section-desc { color: var(--text-muted); font-size: 1rem; max-width: 850px; }

    .grid-cards-3 {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.25rem;
    }
    .card {
      background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem; transition: all 0.2s ease;
    }
    .card:hover { border-color: var(--border-accent); transform: translateY(-2px); background: var(--bg-card-hover); }
    .card-icon {
      font-size: 1.2rem; margin-bottom: 0.75rem; color: #60a5fa; font-family: var(--font-mono); font-weight: 700;
    }
    .card h3 { font-size: 1.15rem; font-weight: 700; margin-bottom: 0.4rem; color: #fff; }
    .card p { font-size: 0.9rem; color: var(--text-muted); line-height: 1.55; }

    .benchmark-table {
      width: 100%; border-collapse: collapse; margin-top: 1.25rem; font-size: 0.9rem;
      background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
    }
    .benchmark-table th, .benchmark-table td {
      padding: 0.85rem 1.15rem; text-align: left; border-bottom: 1px solid var(--border);
    }
    .benchmark-table th {
      background: rgba(255, 255, 255, 0.03); color: var(--text-dim);
      font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em;
    }
    .benchmark-table tr:last-child td { border-bottom: none; }
    .badge-pass {
      display: inline-block; background: rgba(16, 185, 129, 0.15); color: #34d399;
      font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
      padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    .diagram-container {
      background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem; margin-top: 1.5rem; overflow-x: auto; text-align: center;
    }
    .diagram-container img { max-width: 100%; height: auto; border-radius: 8px; }

    .filter-container {
      display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; align-items: center;
    }
    .search-input {
      flex: 1; min-width: 260px; background: rgba(16, 24, 40, 0.8);
      border: 1px solid var(--border); border-radius: 8px; padding: 0.65rem 1rem;
      color: #fff; font-family: var(--font-sans); font-size: 0.9rem; outline: none;
      transition: border-color 0.15s ease;
    }
    .search-input:focus { border-color: var(--primary); }
    .tag-filter {
      display: flex; gap: 0.5rem; flex-wrap: wrap;
    }
    .filter-btn {
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
      color: var(--text-muted); padding: 0.4rem 0.8rem; border-radius: 6px;
      font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.15s ease;
    }
    .filter-btn.active, .filter-btn:hover {
      background: rgba(59, 130, 246, 0.15); color: #60a5fa; border-color: rgba(59, 130, 246, 0.35);
    }

    .item-card {
      background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
      padding: 1.5rem; margin-bottom: 1rem; transition: border-color 0.15s ease;
    }
    .item-card:hover { border-color: var(--border-accent); }
    .item-header {
      display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
      gap: 0.75rem; margin-bottom: 0.6rem;
    }
    .item-title {
      font-family: var(--font-mono); font-size: 1.05rem; font-weight: 700; color: #60a5fa;
    }
    .item-badges { display: flex; gap: 0.4rem; }
    .item-badge {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 600; padding: 0.15rem 0.45rem;
      border-radius: 4px; background: rgba(255, 255, 255, 0.06); color: var(--text-muted);
    }
    .item-badge.profile { background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.3); }
    .item-desc { color: var(--text); font-size: 0.95rem; margin-bottom: 0.85rem; }
    .item-subfield { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem; }
    .item-subfield strong { color: #cbd5e1; font-weight: 600; }

    .code-box {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 8px; padding: 0.85rem 1rem; font-family: var(--font-mono);
      font-size: 0.85rem; color: #e2e8f0; overflow-x: auto; margin-top: 0.5rem;
      position: relative;
    }
    .code-box pre { margin: 0; white-space: pre-wrap; word-break: break-all; }

    footer {
      border-top: 1px solid var(--border); padding: 3rem 2rem; text-align: center;
      color: var(--text-dim); font-size: 0.85rem; margin-top: 5rem;
    }
    footer a { color: var(--text-muted); text-decoration: none; }
    footer a:hover { color: var(--text); }
  </style>
</head>
<body>
  <div class="bg-canvas"></div>
  <div class="grid-lines"></div>

  <div class="app-container">
    <header class="navbar">
      <a href="#" class="brand">
        <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo">
        <span class="brand-title">CodeGraph MCP</span>
        <span class="brand-badge">v2.2.1</span>
      </a>
      <nav class="nav-links">
        <a href="#overview" class="nav-link">Overview</a>
        <a href="#cli-reference" class="nav-link">CLI Commands</a>
        <a href="#tools-catalog" class="nav-link">56 MCP Tools</a>
        <a href="#benchmarks" class="nav-link">Benchmarks</a>
        <a href="https://pypi.org/project/codegraph-engine/2.2.1/" class="nav-link" target="_blank">PyPI</a>
        <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="btn-github" target="_blank">
          <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
          GitHub
        </a>
      </nav>
    </header>

    <section class="hero">
      <div class="pill-announcement">v2.2.1 Production Release Live on PyPI</div>
      <h1>Deterministic Codebase Intelligence for AI Coding Agents</h1>
      <p class="lead">
        Stop AI hallucinations. CodeGraph MCP equips LLM coding agents with compiler-grade AST semantics, live route hierarchies, database table lineages, and non-invasive runtime telemetry.
      </p>
      <div class="hero-actions">
        <a href="#quickstart" class="btn-primary">Quickstart in 30 Seconds</a>
        <a href="#tools-catalog" class="btn-secondary">Explore 56 MCP Tools</a>
      </div>
      <div class="quick-install">
        <span>pip install &quot;codegraph-engine[mcp]&quot;</span>
        <button class="copy-btn" onclick="navigator.clipboard.writeText('pip install &quot;codegraph-engine[mcp]&quot;'); this.innerText='Copied!'; setTimeout(()=>this.innerText='Copy', 1800);">Copy</button>
      </div>
    </section>

    <div class="content-layout">
      <aside class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-title">Getting Started</div>
          <ul class="sidebar-nav">
            <li><a href="#overview" class="sidebar-link">Overview</a></li>
            <li><a href="#quickstart" class="sidebar-link">30s Quickstart</a></li>
            <li><a href="#architecture" class="sidebar-link">Architecture</a></li>
          </ul>
        </div>
        <div class="sidebar-section">
          <div class="sidebar-title">Capabilities</div>
          <ul class="sidebar-nav">
            <li><a href="#cli-reference" class="sidebar-link">CLI Reference (13 cmds)</a></li>
            <li><a href="#tools-catalog" class="sidebar-link">56 MCP Tools Catalog</a></li>
            <li><a href="#benchmarks" class="sidebar-link">Performance Benchmarks</a></li>
          </ul>
        </div>
      </aside>

      <main class="main-content">
        <section id="overview" class="doc-section">
          <div class="section-header">
            <span class="section-badge">Core Philosophy</span>
            <h2 class="section-title">The Problem with AI Code Exploration</h2>
            <p class="section-desc">
              AI coding agents currently rely on brute-force text search (grep / ripgrep) to navigate repositories. In enterprise codebases, this pattern introduces major operational bottlenecks:
            </p>
          </div>

          <div class="grid-cards-3">
            <div class="card">
              <div class="card-icon">01</div>
              <h3>Context Window Saturation</h3>
              <p>Dumping 2,000-line files to find one caller exhausts 80% of an LLM prompt. CodeGraph slices targeted 50-line AST ranges, reducing token usage by 65% to 85%.</p>
            </div>
            <div class="card">
              <div class="card-icon">02</div>
              <h3>Relationship Hallucinations</h3>
              <p>Text search cannot determine if a function is called, injected, or overridden. CodeGraph proves multi-hop call chains with fail-closed evidence.</p>
            </div>
            <div class="card">
              <div class="card-icon">03</div>
              <h3>Database &amp; Route Blindspots</h3>
              <p>Agents lose track of FastAPI prefix mounts and ORM table writers. CodeGraph indexes composite route trees and database readers/writers statically.</p>
            </div>
          </div>
        </section>

        <section id="quickstart" class="doc-section">
          <div class="section-header">
            <span class="section-badge">Setup Guide</span>
            <h2 class="section-title">30-Second Quickstart</h2>
            <p class="section-desc">Install from PyPI, automatically onboard your AI editor, and initialize your project index.</p>
          </div>

          <div class="item-card">
            <div class="item-title">1. Install Package</div>
            <p class="item-desc">Install the engine and MCP server dependencies:</p>
            <div class="code-box"><pre>pip install &quot;codegraph-engine[mcp]&quot;</pre></div>
          </div>

          <div class="item-card">
            <div class="item-title">2. Onboard AI Agents Automatically</div>
            <p class="item-desc">Detects Claude Code, Cursor, Antigravity, and Cline; configures `mcpServers` and safe instructions:</p>
            <div class="code-box"><pre>codegraph install --yes --target auto --location local</pre></div>
          </div>

          <div class="item-card">
            <div class="item-title">3. Initialize Index &amp; Verify Readiness</div>
            <p class="item-desc">Indexes the local codebase into an embedded SQLite database (`.codegraph.sqlite3`):</p>
            <div class="code-box"><pre>cd my-project
codegraph init
codegraph doctor --database</pre></div>
          </div>

          <div class="item-card">
            <div class="item-title">4. Optional: Run With Dev Server Telemetry</div>
            <p class="item-desc">Transparent 1-line wrapper to capture live HTTP routes and exceptions directly into the graph:</p>
            <div class="code-box"><pre>codegraph run npm run dev
# or for Python FastAPI:
codegraph run uvicorn main:app --reload</pre></div>
          </div>
        </section>

        <section id="architecture" class="doc-section">
          <div class="section-header">
            <span class="section-badge">Architecture &amp; Concurrency</span>
            <h2 class="section-title">Low-Latency Concurrency Pipeline</h2>
            <p class="section-desc">Enforced SQLite WAL mode, sub-5ms Git commit freshness checks, and dual-transport stdio/SSE communication.</p>
          </div>
          <div class="diagram-container">
            <img src="assets/v22_concurrency_runtime_pipeline.svg" alt="CodeGraph Architecture Pipeline">
          </div>
        </section>

        <section id="cli-reference" class="doc-section">
          <div class="section-header">
            <span class="section-badge">Command Line Interface</span>
            <h2 class="section-title">CLI Reference &amp; Problem Solving Guide</h2>
            <p class="section-desc">Detailed breakdown of every `codegraph` command, what operational bottlenecks it resolves, and real execution outputs.</p>
          </div>

          <div id="cli-list">''')

    for cmd in commands:
        flags_items = "".join([f"<li><code>{f.split(':')[0]}</code>: {f.split(':')[1] if ':' in f else ''}</li>" for f in cmd['flags']])
        html_parts.append(f'''
            <div class="item-card">
              <div class="item-header">
                <span class="item-title">{cmd['command']}</span>
                <span class="item-badge">{cmd['category']}</span>
              </div>
              <p class="item-desc">{cmd['summary']}</p>
              <div class="item-subfield"><strong>Problem Solved:</strong> {cmd['problem_solved']}</div>
              <div class="item-subfield"><strong>Flags &amp; Options:</strong>
                <ul style="margin-left: 1.5rem; margin-top: 0.25rem;">{flags_items}</ul>
              </div>
              <div class="code-box"><pre>$ {cmd['example']}\n\n{cmd['output']}</pre></div>
            </div>''')

    html_parts.append('''
          </div>
        </section>

        <section id="tools-catalog" class="doc-section">
          <div class="section-header">
            <span class="section-badge">MCP Capabilities</span>
            <h2 class="section-title">56 Model Context Protocol (MCP) Tools</h2>
            <p class="section-desc">Search and filter all 56 deterministic repository tools across profiles and task types.</p>
          </div>

          <div class="filter-container">
            <input type="text" id="tool-search" class="search-input" placeholder="Search tool by name, intent, or keyword (e.g. callers, db, routes)..." oninput="filterTools()">
            <div class="tag-filter">
              <button class="filter-btn active" onclick="setCategoryFilter('ALL', this)">All (56)</button>
              <button class="filter-btn" onclick="setCategoryFilter('agent', this)">Agent Profile (14)</button>
              <button class="filter-btn" onclick="setCategoryFilter('database', this)">Database (11)</button>
              <button class="filter-btn" onclick="setCategoryFilter('runtime', this)">Runtime (3)</button>
              <button class="filter-btn" onclick="setCategoryFilter('graph', this)">Graph &amp; Tracing</button>
            </div>
          </div>

          <div id="tools-grid">''')

    for t in tools:
        req_inputs = ', '.join([f"<code>{i}</code>" for i in t['required_inputs']]) or 'None'
        opt_inputs = ', '.join([f"<code>{i}</code>" for i in t['optional_inputs']]) or 'None'
        profiles_badges = "".join([f'<span class="item-badge profile">{p}</span>' for p in t['profiles']])
        
        html_parts.append(f'''
            <div class="item-card tool-item" data-name="{t['name'].lower()}" data-desc="{t['description'].lower()}" data-profiles="{' '.join(t['profiles']).lower()}">
              <div class="item-header">
                <span class="item-title">{t['name']}</span>
                <div class="item-badges">
                  {profiles_badges}
                </div>
              </div>
              <p class="item-desc">{t['description']}</p>
              <div class="item-subfield"><strong>Required Inputs:</strong> {req_inputs}</div>
              <div class="item-subfield"><strong>Optional Inputs:</strong> {opt_inputs}</div>
              <div class="item-subfield"><strong>Guaranteed Output:</strong> {t['returns']}</div>
              <div class="code-box"><pre>{t['example_call']}</pre></div>
            </div>''')

    html_parts.append('''
          </div>
        </section>

        <section id="benchmarks" class="doc-section">
          <div class="section-header">
            <span class="section-badge">Empirical Results</span>
            <h2 class="section-title">Measured Performance &amp; Monorepo Scaling</h2>
            <p class="section-desc">Strict 50-task evaluation across 10 benchmark categories, audited for 0% unsupported claims and sub-50ms query response times.</p>
          </div>

          <table class="benchmark-table">
            <thead>
              <tr>
                <th>Trust &amp; Efficiency Dimension</th>
                <th>Measured Result (v2.2.1)</th>
                <th>Target Threshold</th>
                <th>Quality Gate</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>FACT Correctness</strong></td>
                <td>100.0%</td>
                <td>&ge; 98.0%</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
              <tr>
                <td><strong>Unsupported Claims (Hallucinations)</strong></td>
                <td>0.0%</td>
                <td>&le; 1.0%</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
              <tr>
                <td><strong>Task Coverage</strong></td>
                <td>88.0%</td>
                <td>&ge; 80.0%</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
              <tr>
                <td><strong>Token Reduction vs Raw File Reads</strong></td>
                <td>41.8% to 85.6%</td>
                <td>&ge; 35.0%</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
              <tr>
                <td><strong>Average Query Latency</strong></td>
                <td>40.52 ms</td>
                <td>&le; 100 ms</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
              <tr>
                <td><strong>Commit Freshness Check</strong></td>
                <td>&lt; 5 ms</td>
                <td>&le; 50 ms</td>
                <td><span class="badge-pass">PASS</span></td>
              </tr>
            </tbody>
          </table>

          <div class="diagram-container">
            <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark">
          </div>
          <div class="diagram-container" style="margin-top: 1.5rem;">
            <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark">
          </div>
        </section>
      </main>
    </div>

    <footer>
      <p>CodeGraph MCP Engine (v2.2.1) • Open source software under the MIT License • Published on PyPI &amp; GitHub.</p>
    </footer>
  </div>

  <script>
    let currentCategory = 'ALL';

    function setCategoryFilter(category, btn) {
      currentCategory = category;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterTools();
    }

    function filterTools() {
      const query = document.getElementById('tool-search').value.toLowerCase().trim();
      const tools = document.querySelectorAll('.tool-item');

      tools.forEach(tool => {
        const name = tool.getAttribute('data-name');
        const desc = tool.getAttribute('data-desc');
        const profiles = tool.getAttribute('data-profiles');

        let matchesCategory = true;
        if (currentCategory === 'agent') {
          matchesCategory = profiles.includes('agent');
        } else if (currentCategory === 'database') {
          matchesCategory = name.includes('db');
        } else if (currentCategory === 'runtime') {
          matchesCategory = name.includes('runtime') || name.includes('trace');
        } else if (currentCategory === 'graph') {
          matchesCategory = profiles.includes('graph') || name.includes('call') || name.includes('path') || name.includes('flow');
        }

        const matchesQuery = query === '' || name.includes(query) || desc.includes(query);
        tool.style.display = (matchesCategory && matchesQuery) ? 'block' : 'none';
      });
    }
  </script>
</body>
</html>
''')

    final_html = "".join(html_parts)
    with open(docs_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(final_html)
    print("Wrote docs/index.html successfully, length:", len(final_html))

if __name__ == "__main__":
    generate_docs()
