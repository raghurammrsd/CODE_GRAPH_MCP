import html
import json
from pathlib import Path

import codegraph.agent_capabilities as ac
from codegraph.mcp.server import create_server


def sync_tools_data() -> list[dict]:
    server = create_server(Path("."))
    mcp_tools = server._tool_manager._tools

    def get_category(name: str) -> str:
        if name.startswith(("find_db_", "get_db_")):
            return "database"
        if "runtime" in name or name in ("trace_call", "trace_flow", "trace_path"):
            return "runtime"
        if "route" in name:
            return "routes"
        if "git" in name or "history" in name or "recent_changes" in name or "change_impact" in name:
            return "git"
        if "test" in name:
            return "tests"
        if "graph" in name or "impact" in name or "callees" in name or "callers" in name:
            return "graph"
        return "core"

    tools_data = []
    for spec in ac.TOOL_CAPABILITY_REGISTRY:
        name = spec.tool_name
        m_tool = mcp_tools[name]
        cat = get_category(name)

        ret_props = {}
        if spec.result_fields:
            for f in spec.result_fields:
                field_type = "string"
                if any(k in f for k in ("count", "tokens", "line", "depth", "limit", "status_code")):
                    field_type = "integer"
                elif any(k in f for k in ("items", "symbols", "files", "routes", "tests", "callers", "callees", "writers", "readers", "queries", "columns", "tables", "edges", "matches", "alternatives")):
                    field_type = "array"
                elif any(k in f for k in ("truncated", "fresh", "observed", "success", "has_more")):
                    field_type = "boolean"
                ret_props[f] = {"type": field_type, "title": f.replace("_", " ").title()}
        else:
            ret_props = {"result": {"type": "object", "title": "Result"}}

        ret_schema = {
            "title": spec.expected_output_type,
            "type": "object",
            "properties": ret_props,
        }

        prob = spec.useful_situations[0] if spec.useful_situations else spec.description

        item = {
            "name": name,
            "category": cat,
            "capability": spec.capability,
            "description": spec.description,
            "problem_solved": prob,
            "profiles": list(spec.profiles),
            "required_inputs": list(spec.required_inputs),
            "optional_inputs": list(spec.optional_inputs),
            "parameters_schema": m_tool.parameters,
            "return_schema": ret_schema,
            "returns": spec.expected_output_type,
            "example_invocation": spec.example_call or spec.minimal_invocation,
            "minimal_invocation": spec.minimal_invocation,
            "advanced_invocation": spec.advanced_invocation,
            "evidence": spec.evidence_guarantees,
            "does_not_prove": spec.does_not_prove,
        }
        tools_data.append(item)

    docs_dir = Path("docs")
    docs_dir.mkdir(parents=True, exist_ok=True)
    with open(docs_dir / "tools_data.json", "w", encoding="utf-8") as f:
        json.dump(tools_data, f, indent=2)

    return tools_data


def generate_docs():
    docs_dir = Path("docs")
    tools = sync_tools_data()

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
  <meta property="og:title" content="CodeGraph - Runtime & Database Codebase Intelligence">
  <meta property="og:description" content="Local-first code-intelligence engine with runtime telemetry reconciliation, database lineage, and 56 verified MCP tools for AI coding agents.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph - Runtime & Database Codebase Intelligence">
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
      --purple: #9333ea;
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
      background: rgba(255, 255, 255, 0.94);
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
      border-radius: 6px; cursor: pointer; text-decoration: none; transition: all 0.15s ease;
    }
    .cap-pill:hover { border-color: var(--primary); }
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
      color: #64748b; cursor: pointer; padding: 0.2rem 0; font-family: var(--font-mono);
      transition: color 0.15s ease;
    }
    .term-tab-btn.active, .term-tab-btn:hover { color: #f8fafc; }
    .term-line-exec {
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.85rem; color: #f8fafc;
    }
    .btn-copy-term {
      background: rgba(255, 255, 255, 0.08); border: none; border-radius: 4px;
      padding: 0.3rem 0.5rem; cursor: pointer; color: #94a3b8; transition: all 0.15s ease;
    }
    .btn-copy-term:hover { background: rgba(255, 255, 255, 0.18); color: #fff; }

    /* IDE Mockup (Right Column) */
    .ide-mockup-window {
      background: #090d16; border: 1px solid #1e293b; border-radius: 16px;
      overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);
      display: flex; flex-direction: column;
    }
    .ide-window-topbar {
      background: #0d121f; border-bottom: 1px solid #1e293b;
      padding: 0.75rem 1rem; display: flex; align-items: center; justify-content: space-between;
    }
    .window-dots { display: flex; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; }
    .dot-red { background: #ef4444; }
    .dot-yellow { background: #eab308; }
    .dot-green { background: #22c55e; }
    .window-title-tab {
      font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600;
      color: #94a3b8; background: #090d16; padding: 0.25rem 0.75rem; border-radius: 6px;
      border: 1px solid #1e293b;
    }
    .window-status-pill {
      font-family: var(--font-mono); font-size: 0.7rem; font-weight: 700;
      color: #10b981; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25);
      padding: 0.2rem 0.5rem; border-radius: 9999px; display: inline-flex; align-items: center; gap: 4px;
    }

    .ide-body-split {
      display: grid; grid-template-columns: 190px 1fr 200px;
      height: 380px; background: #090d16;
    }
    @media (max-width: 900px) {
      .ide-body-split { grid-template-columns: 1fr; height: auto; }
    }

    .tree-pane-wrap {
      border-right: 1px solid #1e293b; padding: 0.75rem 0.5rem; font-family: var(--font-mono);
      font-size: 0.78rem; color: #94a3b8;
    }
    .tree-pane-head {
      font-size: 0.7rem; font-weight: 700; color: #475569; text-transform: uppercase;
      letter-spacing: 0.05em; padding: 0.25rem 0.5rem; margin-bottom: 0.35rem;
    }
    .tree-item-row {
      padding: 0.3rem 0.5rem; border-radius: 4px; display: flex; align-items: center; gap: 0.45rem;
      cursor: pointer; transition: background 0.15s ease;
    }
    .tree-item-row:hover { background: rgba(255, 255, 255, 0.04); color: #f8fafc; }
    .tree-item-row.active { background: rgba(37, 99, 235, 0.15); color: #60a5fa; font-weight: 600; }
    .tree-item-row.db-item { color: #f59e0b; }
    .tree-item-row.runtime-item { color: #34d399; }

    .graph-visual-canvas {
      position: relative; background: #090d16; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
    }
    .graph-svg-elem { width: 100%; height: 100%; }

    .inspector-pane-wrap {
      border-left: 1px solid #1e293b; padding: 0.9rem; font-family: var(--font-mono);
      font-size: 0.78rem; color: #94a3b8; display: flex; flex-direction: column; justify-content: space-between;
    }
    .inspector-head-title { font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 0.45rem; margin-bottom: 0.25rem; }
    .inspector-file-sub { font-size: 0.7rem; color: #64748b; margin-bottom: 0.85rem; }
    .prop-row { display: flex; justify-content: space-between; margin-bottom: 0.45rem; }
    .prop-val { color: #f8fafc; font-weight: 600; }
    .prop-val.amber { color: #f59e0b; }
    .prop-val.green { color: #10b981; }

    .btn-action-view {
      background: #1e293b; border: 1px solid #334155; color: #f8fafc;
      padding: 0.45rem; border-radius: 6px; font-size: 0.75rem; font-weight: 600;
      cursor: pointer; text-align: center; font-family: var(--font-sans);
    }
    .btn-action-view:hover { background: #334155; }

    .ide-stats-strip-bottom {
      background: #0d121f; border-top: 1px solid #1e293b;
      padding: 0.75rem 1.25rem; display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
    }
    .stat-tile-card { display: flex; align-items: center; gap: 0.65rem; }
    .stat-tile-num { font-family: var(--font-mono); font-size: 1.15rem; font-weight: 800; color: #f8fafc; line-height: 1; }
    .stat-tile-tag { font-size: 0.72rem; color: #64748b; font-weight: 600; }

    /* 6 Features Grid (Clean White) */
    .features-grid-section {
      background: #ffffff; border-top: 1px solid var(--border);
      padding: 4rem 2.5rem;
    }
    .features-6-grid {
      max-width: 1380px; margin: 0 auto;
      display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.25rem;
    }
    .feature-clean-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 12px;
      padding: 1.35rem 1.5rem; display: flex; align-items: center; justify-content: space-between;
      text-decoration: none; color: inherit; transition: all 0.2s ease;
      box-shadow: var(--shadow-sm); cursor: pointer;
    }
    .feature-clean-card:hover {
      border-color: var(--border-focus); transform: translateY(-2px);
      box-shadow: var(--shadow-card);
    }
    .card-left-part { display: flex; align-items: center; gap: 1.1rem; }
    .icon-square-box {
      width: 44px; height: 44px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .icon-blue { background: #eff6ff; color: #2563eb; }
    .icon-emerald { background: #dcfce7; color: #10b981; }
    .icon-amber { background: #fef3c7; color: #f59e0b; }
    .icon-indigo { background: #e0e7ff; color: #4f46e5; }
    .icon-rose { background: #ffe4e6; color: #e11d48; }

    .card-text-part h3 { font-size: 1.05rem; font-weight: 700; color: var(--text); margin-bottom: 0.2rem; }
    .card-text-part p { font-size: 0.85rem; color: var(--text-muted); line-height: 1.45; }
    .arrow-circle-pill {
      width: 28px; height: 28px; border-radius: 50%;
      background: #f1f5f9; display: flex; align-items: center; justify-content: center;
      color: var(--text-dim); font-size: 0.85rem; flex-shrink: 0; transition: all 0.15s ease;
    }
    .feature-clean-card:hover .arrow-circle-pill { background: var(--text); color: #fff; }

    /* Documentation Section (Clean White) */
    .docs-white-section {
      background: #f8fafc; border-top: 1px solid var(--border);
      padding: 5rem 2.5rem 6rem;
    }
    .docs-inner-wrapper { max-width: 1380px; margin: 0 auto; }
    .docs-section-heading { text-align: center; max-width: 780px; margin: 0 auto 3rem; }
    .docs-badge-sub {
      font-family: var(--font-mono); font-size: 0.78rem; font-weight: 800;
      color: var(--primary); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.5rem;
      display: inline-block;
    }
    .docs-title-h2 { font-size: 2.35rem; font-weight: 800; letter-spacing: -0.03em; color: var(--text); margin-bottom: 0.75rem; }
    .docs-desc-p { font-size: 1.05rem; color: var(--text-muted); line-height: 1.6; }

    /* Tool Toolbar & Search */
    .tool-white-toolbar {
      display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.5rem;
      background: #ffffff; padding: 1.25rem 1.5rem; border-radius: 14px; border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }
    .tool-search-input-wrap {
      position: relative; display: flex; align-items: center; width: 100%;
    }
    .search-lens-icon {
      position: absolute; left: 1rem; color: var(--text-dim); pointer-events: none;
    }
    .tool-search-white-input {
      width: 100%; background: #f8fafc; border: 1px solid var(--border);
      border-radius: 8px; padding: 0.75rem 2.8rem 0.75rem 2.75rem; color: var(--text); font-family: var(--font-sans);
      font-size: 0.95rem; outline: none; transition: border-color 0.15s ease;
    }
    .tool-search-white-input:focus { border-color: var(--primary); background: #ffffff; }
    .clear-search-btn {
      position: absolute; right: 0.85rem; background: #e2e8f0; border: none; border-radius: 50%;
      width: 22px; height: 22px; cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 0.75rem; color: #475569; transition: background 0.15s ease;
    }
    .clear-search-btn:hover { background: #cbd5e1; }

    .filter-pills-row {
      display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;
    }
    .btn-pill-filter {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.45rem 0.85rem; border-radius: 8px; font-size: 0.82rem; font-weight: 700; cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-pill-filter.active, .btn-pill-filter:hover {
      background: var(--text); color: #fff; border-color: var(--text);
    }
    .btn-pill-filter.cat-db.active { background: #d97706; border-color: #d97706; color: #fff; }
    .btn-pill-filter.cat-runtime.active { background: #059669; border-color: #059669; color: #fff; }
    .btn-pill-filter.cat-graph.active { background: #2563eb; border-color: #2563eb; color: #fff; }

    .filter-results-status {
      font-size: 0.85rem; color: var(--text-dim); margin-bottom: 1.5rem;
      display: flex; justify-content: space-between; align-items: center;
    }
    .filter-results-status strong { color: var(--text); }

    /* Tool Cards Grid */
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
      font-size: 0.68rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.2rem 0.55rem; border-radius: 4px; border: 1px solid transparent;
    }
    .prof-tag-pill.core { background: #f1f5f9; color: #334155; border-color: #e2e8f0; }
    .prof-tag-pill.database { background: #fef3c7; color: #92400e; border-color: #fde68a; }
    .prof-tag-pill.runtime { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
    .prof-tag-pill.graph { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
    .prof-tag-pill.routes { background: #ffe4e6; color: #9f1239; border-color: #fecdd3; }
    .prof-tag-pill.git { background: #e0e7ff; color: #3730a3; border-color: #c7d2fe; }
    .prof-tag-pill.tests { background: #f3e8ff; color: #6b21a8; border-color: #e9d5ff; }

    .tool-desc-body { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.85rem; line-height: 1.55; }
    .tool-problem-note {
      background: #f8fafc; border-left: 3px solid #2563eb; padding: 0.5rem 0.8rem;
      border-radius: 0 6px 6px 0; font-size: 0.82rem; color: #334155; margin-bottom: 0.85rem;
    }
    .tool-meta-tags-row {
      display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;
    }
    .meta-tag-spec {
      font-family: var(--font-mono); font-size: 0.72rem; color: #475569;
      background: #f1f5f9; padding: 0.15rem 0.45rem; border-radius: 4px;
    }
    .meta-tag-spec.returns { color: #2563eb; background: #eff6ff; }

    .btn-drawer-expand {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.55rem; border-radius: 6px; font-size: 0.82rem; font-weight: 700; cursor: pointer;
      width: 100%; text-align: center; transition: all 0.15s ease;
    }
    .btn-drawer-expand:hover { color: var(--text); background: #f1f5f9; border-color: #cbd5e1; }
    .drawer-content { display: none; margin-top: 1.15rem; padding-top: 1.15rem; border-top: 1px solid var(--border); }
    .drawer-content.open { display: block; }

    .schema-block-heading {
      display: flex; justify-content: space-between; align-items: center;
      font-size: 0.75rem; font-weight: 700; color: var(--text-dim); text-transform: uppercase;
      letter-spacing: 0.05em; margin-bottom: 0.35rem; margin-top: 0.85rem;
    }
    .schema-block-heading:first-child { margin-top: 0; }
    .badge-tag-tiny {
      font-family: var(--font-mono); font-size: 0.68rem; text-transform: none;
      background: #e2e8f0; color: #475569; padding: 0.1rem 0.4rem; border-radius: 4px;
    }
    .btn-copy-mini {
      background: #f1f5f9; border: 1px solid var(--border); font-size: 0.7rem;
      padding: 0.15rem 0.45rem; border-radius: 4px; cursor: pointer; color: #475569;
      font-family: var(--font-mono); transition: all 0.15s ease;
    }
    .btn-copy-mini:hover { background: #e2e8f0; color: #0f172a; }

    .code-box-pre {
      background: #090d16; border: 1px solid #1e293b; border-radius: 8px;
      padding: 0.85rem; font-family: var(--font-mono); font-size: 0.78rem; color: #f8fafc;
      overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin: 0.25rem 0 0.85rem;
      line-height: 1.45;
    }

    .verification-note-box {
      background: #f8fafc; border: 1px solid var(--border); border-radius: 8px;
      padding: 0.65rem 0.85rem; font-size: 0.76rem; color: #475569; margin-top: 0.85rem;
    }
    .verification-note-box strong { color: var(--text); }

    .empty-state-notice {
      grid-column: 1 / -1; text-align: center; padding: 4rem 2rem;
      background: #ffffff; border: 1px dashed var(--border); border-radius: 14px;
    }
    .empty-state-title { font-size: 1.25rem; font-weight: 700; color: var(--text); margin-bottom: 0.5rem; }
    .empty-state-desc { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1.25rem; }
    .btn-reset-filters {
      background: var(--text); color: #fff; border: none; border-radius: 6px;
      padding: 0.5rem 1.2rem; font-size: 0.85rem; font-weight: 700; cursor: pointer;
    }

    /* CLI Grid (Clean White) */
    .cli-cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.5rem; margin-top: 2rem; }
    .cli-card-unit {
      background: #ffffff; border: 1px solid var(--border); border-radius: 14px;
      padding: 1.65rem; box-shadow: var(--shadow-sm); display: flex; flex-direction: column; justify-content: space-between;
    }
    .cli-name-h3 { font-family: var(--font-mono); font-size: 1.12rem; font-weight: 800; color: var(--text); margin-bottom: 0.35rem; }
    .cli-solve-bar {
      background: #eff6ff; color: #1e40af; padding: 0.45rem 0.75rem; border-radius: 6px;
      font-size: 0.82rem; font-weight: 600; margin-bottom: 0.85rem;
    }
    .cli-cmd-display {
      background: #090d16; border: 1px solid #1e293b; border-radius: 6px;
      padding: 0.7rem 0.95rem; font-family: var(--font-mono); font-size: 0.85rem; color: #f8fafc;
      margin-bottom: 0.85rem; display: flex; justify-content: space-between; align-items: center;
    }
    .btn-copy-code {
      background: none; border: none; color: #94a3b8; cursor: pointer; display: flex; align-items: center;
    }
    .btn-copy-code:hover { color: #f8fafc; }
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
    .footer-links-group { display: flex; gap: 1.5rem; list-style: none; font-size: 0.9rem; }
    .footer-links-group a { color: var(--text-muted); text-decoration: none; font-weight: 600; }
    .footer-links-group a:hover { color: var(--text); }
  </style>
</head>
<body>

  <!-- Universal Clean Header -->
  <header class="clean-nav">
    <a href="#" class="brand-wrap">
      <!-- 3D Isometric Graph Cube Logo from Reference -->
      <svg class="brand-logo-svg" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M16 2L28 9V23L16 30L4 23V9L16 2Z" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round"/>
        <path d="M16 2V16M28 9L16 16M4 9L16 16M16 16V30" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="16" cy="16" r="3" fill="#2563eb"/>
      </svg>
      <span class="brand-text">CodeGraph</span>
    </a>

    <!-- Top Search Bar Trigger (⌘ K) -->
    <div class="header-search-bar" onclick="focusSearch()">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
      <span>Search 56 tools, routes, tables (Press ⌘ K)</span>
      <kbd class="kbd-pill">⌘ K</kbd>
    </div>

    <!-- Navigation Menu -->
    <ul class="nav-links-menu">
      <li><a href="#features">Features</a></li>
      <li><a href="#tools">MCP Tools (56)</a></li>
      <li><a href="#cli">CLI (13)</a></li>
      <li><a href="#benchmarks">Benchmarks</a></li>
      <li>
        <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank" class="badge-star-pill">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
          <span>Star</span>
        </a>
      </li>
    </ul>
  </header>

  <!-- Split Hero Section -->
  <section class="hero-white-container">
    
    <!-- Left Column: Copy & Interactive Quickstart -->
    <div>
      <div class="badge-highlight-row">
        <span class="badge-dot-green"></span>
        <span>v2.2.1 Production · Runtime &amp; Database Verified</span>
      </div>

      <h1 class="hero-main-title">
        The deterministic<br>
        <span class="gradient-blue-text">code-intelligence</span> engine.
      </h1>

      <p class="hero-lead-text">
        CodeGraph indexes repository relationships with <strong>runtime telemetry reconciliation</strong> and <strong>database lineage</strong>. AI agents resolve call hierarchies, mutating SQL queries, and API routes in <strong>&lt; 50ms</strong> without token waste.
      </p>

      <div class="pills-capability-row">
        <span class="cap-pill highlight-runtime" onclick="filterByCategory('runtime')">&#10003; Runtime Reconciliation</span>
        <span class="cap-pill highlight-db" onclick="filterByCategory('database')">&#9670; Database Lineage</span>
        <span class="cap-pill" onclick="filterByCategory('routes')">Routes &amp; Handlers</span>
        <span class="cap-pill" onclick="filterByCategory('core')">Deterministic AST</span>
        <span class="cap-pill" onclick="filterByCategory('all')">56 Verified Tools</span>
      </div>

      <div class="hero-btn-actions">
        <a href="#tools" class="btn-solid-black">
          <span>Explore 56 MCP Tools</span>
          <span>&darr;</span>
        </a>
        <a href="#cli" class="btn-outline-white">CLI Documentation</a>
      </div>

      <!-- Tabbed Terminal Box -->
      <div class="terminal-tab-box">
        <div class="term-tab-strip">
          <button class="term-tab-btn active" onclick="setTerminalCmd('pip install codegraph-engine[mcp]', this)">Install</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('codegraph search --database \'users table writes\'', this)">Database CLI</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('codegraph run --record pytest', this)">Runtime Traces</button>
          <button class="term-tab-btn" onclick="setTerminalCmd('from codegraph import get_context', this)">Python API</button>
        </div>
        <div class="term-line-exec">
          <span id="terminalCmdText">$ pip install codegraph-engine[mcp]</span>
          <button class="btn-copy-term" onclick="copyTerminalCode()" title="Copy command">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Right Column: Interactive IDE Visualizer -->
    <div>
      <div class="ide-mockup-window">
        
        <!-- IDE Topbar -->
        <div class="ide-window-topbar">
          <div class="window-dots">
            <div class="dot dot-red"></div>
            <div class="dot dot-yellow"></div>
            <div class="dot dot-green"></div>
          </div>
          <div class="window-title-tab">CodeGraph Graph Visualizer</div>
          <div class="window-status-pill">&#10003; Synchronized</div>
        </div>

        <!-- 3-Pane Visual Split -->
        <div class="ide-body-split">
          
          <!-- Left: File Tree -->
          <div class="tree-pane-wrap">
            <div class="tree-pane-head">Repository Explorer</div>
            <div class="tree-item-row">&bull; app/</div>
            <div class="tree-item-row">&nbsp;&nbsp;&bull; api/</div>
            <div class="tree-item-row active">&nbsp;&nbsp;&nbsp;&nbsp;router.py</div>
            <div class="tree-item-row">&nbsp;&nbsp;&nbsp;&nbsp;auth.py</div>
            <div class="tree-item-row db-item">&nbsp;&nbsp;&bull; db/users.sql</div>
            <div class="tree-item-row runtime-item">&nbsp;&nbsp;&bull; traces/live.json</div>
            <div class="tree-item-row">&bull; tests/test_api.py</div>
          </div>

          <!-- Center: Graph Canvas -->
          <div class="graph-visual-canvas">
            <svg class="graph-svg-elem" viewBox="0 0 420 280">
              <defs>
                <linearGradient id="edgeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.6"/>
                  <stop offset="100%" stop-color="#60a5fa" stop-opacity="0.2"/>
                </linearGradient>
                <linearGradient id="dbGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.6"/>
                  <stop offset="100%" stop-color="#fbbf24" stop-opacity="0.2"/>
                </linearGradient>
                <linearGradient id="rtGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#10b981" stop-opacity="0.6"/>
                  <stop offset="100%" stop-color="#34d399" stop-opacity="0.2"/>
                </linearGradient>
              </defs>

              <!-- Connection Edges -->
              <path d="M200 120 L90 85" stroke="url(#edgeGrad)" stroke-width="1.8" stroke-dasharray="3 3"/>
              <path d="M200 120 L330 90" stroke="url(#dbGrad)" stroke-width="2"/>
              <path d="M200 120 L130 185" stroke="url(#edgeGrad)" stroke-width="1.8"/>
              <path d="M200 120 L270 195" stroke="url(#rtGrad)" stroke-width="2"/>
              <path d="M90 85 L270 40" stroke="url(#edgeGrad)" stroke-width="1.5" stroke-opacity="0.4"/>

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
              <button class="btn-action-view" style="width:100%; margin-bottom:0.35rem;" onclick="filterByCategory('core')">View tools &rarr;</button>
              <button class="btn-action-view" style="width:100%; background:none;" onclick="filterByCategory('database')">Find DB queries</button>
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
      <a href="#tools" class="feature-clean-card" style="border-top: 3px solid #10b981;" onclick="filterByCategory('runtime'); return true;">
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
      <a href="#tools" class="feature-clean-card" style="border-top: 3px solid #f59e0b;" onclick="filterByCategory('database'); return true;">
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
      <a href="#tools" class="feature-clean-card" onclick="filterByCategory('core'); return true;">
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
      <a href="#tools" class="feature-clean-card" onclick="filterByCategory('all'); return true;">
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
      <a href="#tools" class="feature-clean-card" onclick="filterByCategory('routes'); return true;">
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
      <a href="#tools" class="feature-clean-card" onclick="filterByCategory('graph'); return true;">
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
          Search and inspect every tool exposed by CodeGraph. Filter specifically by Database, Runtime, Graph, Routes, Git, Tests, or Core capabilities.
        </p>
      </div>

      <!-- Functional Filter Toolbar -->
      <div class="tool-white-toolbar">
        <div class="tool-search-input-wrap">
          <svg class="search-lens-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <input type="text" id="toolSearchInput" class="tool-search-white-input" placeholder="Search 56 tools by name, description, parameter, or capability (e.g. database, runtime, callers, trace, routes)..." oninput="filterToolsGrid()">
          <button id="clearSearchBtn" class="clear-search-btn" onclick="clearToolSearch()" style="display:none;" title="Clear search">&times;</button>
        </div>

        <div class="filter-pills-row">
          <button class="btn-pill-filter active" data-cat="all" onclick="setCategoryFilter('all', this)">All (56)</button>
          <button class="btn-pill-filter cat-db" data-cat="database" onclick="setCategoryFilter('database', this)">Database (11)</button>
          <button class="btn-pill-filter cat-runtime" data-cat="runtime" onclick="setCategoryFilter('runtime', this)">Runtime (6)</button>
          <button class="btn-pill-filter cat-graph" data-cat="graph" onclick="setCategoryFilter('graph', this)">Graph &amp; Impact (8)</button>
          <button class="btn-pill-filter" data-cat="core" onclick="setCategoryFilter('core', this)">Core Profile (23)</button>
          <button class="btn-pill-filter" data-cat="routes" onclick="setCategoryFilter('routes', this)">Routes (2)</button>
          <button class="btn-pill-filter" data-cat="git" onclick="setCategoryFilter('git', this)">Git &amp; History (4)</button>
          <button class="btn-pill-filter" data-cat="tests" onclick="setCategoryFilter('tests', this)">Tests (2)</button>
        </div>
      </div>

      <div class="filter-results-status">
        <div>Showing <strong id="visibleCount">56</strong> of 56 tools</div>
        <div style="font-family:var(--font-mono); font-size:0.75rem;">Status: <span style="color:#10b981; font-weight:700;">Deterministic AST &amp; Runtime Verified</span></div>
      </div>

      <div class="tools-white-grid" id="toolsContainer">
''')

    for t in tools:
        t_name = html.escape(t.get("name", ""))
        t_cat = html.escape(t.get("category", "core"))
        t_capability = html.escape(t.get("capability", ""))
        t_desc = html.escape(t.get("description", ""))
        t_problem = html.escape(t.get("problem_solved", ""))
        t_returns_type = html.escape(t.get("returns", "object"))

        params_schema = t.get("parameters_schema", {})
        returns_schema = t.get("return_schema", {})
        t_inputs = html.escape(json.dumps(params_schema, indent=2))
        t_returns = html.escape(json.dumps(returns_schema, indent=2))
        t_inv = html.escape(t.get("example_invocation", ""))
        t_evidence = html.escape(t.get("evidence", "AST-verified deterministic relationship."))
        t_does_not_prove = html.escape(t.get("does_not_prove", "Requires runtime observation to confirm execution."))

        req_inputs = t.get("required_inputs", [])
        opt_inputs = t.get("optional_inputs", [])
        inputs_badge_text = f"{len(req_inputs)} req" + (f", {len(opt_inputs)} opt" if opt_inputs else "")

        # Search index metadata
        search_blob = f"{t_name} {t_desc} {t_problem} {t_cat} {t_capability} {' '.join(req_inputs)} {' '.join(opt_inputs)} {t_returns_type}".lower()

        html_parts.append(f'''
        <div class="tool-white-card" 
             data-name="{t_name.lower()}" 
             data-desc="{t_desc.lower()}" 
             data-prob="{t_problem.lower()}" 
             data-cat="{t_cat.lower()}" 
             data-capability="{t_capability.lower()}" 
             data-blob="{html.escape(search_blob)}">
          <div>
            <div class="tool-card-head">
              <span class="tool-code-title">{t_name}</span>
              <span class="prof-tag-pill {t_cat.lower()}">{t_cat.upper()}</span>
            </div>
            <p class="tool-desc-body">{t_desc}</p>
            <div class="tool-problem-note">
              <strong>Resolves:</strong> {t_problem}
            </div>
            <div class="tool-meta-tags-row">
              <span class="meta-tag-spec">{inputs_badge_text}</span>
              <span class="meta-tag-spec returns">&rarr; {t_returns_type}</span>
            </div>
          </div>
          <div>
            <button class="btn-drawer-expand" onclick="toggleSchemaDrawer(this)">Inspect Schema &amp; Invocation &darr;</button>
            <div class="drawer-content">
              <div class="schema-block-heading">
                <span>Input Parameters Schema</span>
                <span class="badge-tag-tiny">{len(req_inputs)} required &bull; {len(opt_inputs)} optional</span>
              </div>
              <pre class="code-box-pre">{t_inputs}</pre>
              
              <div class="schema-block-heading">
                <span>Return Structure Schema</span>
                <span class="badge-tag-tiny">{t_returns_type}</span>
              </div>
              <pre class="code-box-pre">{t_returns}</pre>
              
              <div class="schema-block-heading">
                <span>Client Invocation</span>
                <button class="btn-copy-mini" onclick="copyPreCode(this)">Copy Call</button>
              </div>
              <pre class="code-box-pre">{t_inv}</pre>

              <div class="verification-note-box">
                <div><strong>Evidence:</strong> {t_evidence}</div>
                <div style="margin-top:0.35rem;"><strong>Boundaries:</strong> {t_does_not_prove}</div>
              </div>
            </div>
          </div>
        </div>
''')

    html_parts.append('''
        <!-- Empty State Container -->
        <div id="noResultsBox" class="empty-state-notice" style="display:none;">
          <div class="empty-state-title">No matching tools found</div>
          <div class="empty-state-desc">No tools matched your current search and filter criteria.</div>
          <button class="btn-reset-filters" onclick="resetAllFilters()">Reset All Filters</button>
        </div>

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
        c_cmd = html.escape(cmd.get("command", ""))
        c_cat = html.escape(cmd.get("category", "CLI"))
        c_desc = html.escape(cmd.get("summary", ""))
        c_problem = html.escape(cmd.get("problem_solved", ""))
        c_example = html.escape(cmd.get("example", ""))
        c_output = html.escape(cmd.get("output", ""))

        flags_rows = ""
        for flag in cmd.get("flags", []):
            if ":" in flag:
                f_name, f_desc = flag.split(":", 1)
            else:
                f_name, f_desc = flag, ""
            f_name = html.escape(f_name.strip())
            f_desc = html.escape(f_desc.strip())
            flags_rows += f'<tr><td class="flag-bold">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
        <div class="cli-card-unit">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:0.4rem;">
              <div class="cli-name-h3">{c_cmd}</div>
              <span class="prof-tag-pill core">{c_cat.upper()}</span>
            </div>
            <div class="cli-solve-bar">Resolves: {c_problem}</div>
            <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:0.85rem;">{c_desc}</p>

            <div class="cli-cmd-display">
              <span class="cli-cmd-text">{c_example}</span>
              <button class="btn-copy-code" onclick="copyCliCmd(this)" title="Copy command">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              </button>
            </div>

            <table class="table-spec-clean">
              <thead><tr><th>Flag / Option</th><th>Description</th></tr></thead>
              <tbody>{flags_rows}</tbody>
            </table>
          </div>

          <div>
            <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-dim); margin-top:0.85rem;">Terminal Output</div>
            <pre class="code-box-pre">{c_output}</pre>
          </div>
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

    function setCategoryFilter(cat, btn) {
      currentCategory = cat;
      document.querySelectorAll('.btn-pill-filter').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-cat') === cat);
      });
      filterToolsGrid();
    }

    function clearToolSearch() {
      const input = document.getElementById('toolSearchInput');
      if (input) {
        input.value = '';
        input.focus();
      }
      document.getElementById('clearSearchBtn').style.display = 'none';
      filterToolsGrid();
    }

    function resetAllFilters() {
      currentCategory = 'all';
      const input = document.getElementById('toolSearchInput');
      if (input) input.value = '';
      const clearBtn = document.getElementById('clearSearchBtn');
      if (clearBtn) clearBtn.style.display = 'none';
      document.querySelectorAll('.btn-pill-filter').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-cat') === 'all');
      });
      filterToolsGrid();
    }

    function filterToolsGrid() {
      const input = document.getElementById('toolSearchInput');
      const q = input ? input.value.toLowerCase().trim() : '';
      const clearBtn = document.getElementById('clearSearchBtn');
      if (clearBtn) clearBtn.style.display = q ? 'inline-flex' : 'none';

      const cards = document.querySelectorAll('.tool-white-card');
      let visibleCount = 0;

      cards.forEach(card => {
        const cat = card.getAttribute('data-cat') || '';
        const blob = card.getAttribute('data-blob') || '';

        const matchesQuery = !q || blob.includes(q);
        const matchesCat = currentCategory === 'all' || cat === currentCategory;

        if (matchesQuery && matchesCat) {
          card.style.display = 'flex';
          visibleCount++;
        } else {
          card.style.display = 'none';
        }
      });

      const countEl = document.getElementById('visibleCount');
      if (countEl) countEl.textContent = visibleCount;

      const noResultsEl = document.getElementById('noResultsBox');
      if (noResultsEl) {
        noResultsEl.style.display = visibleCount === 0 ? 'block' : 'none';
      }
    }

    function filterByCategory(cat) {
      const btn = document.querySelector(`.btn-pill-filter[data-cat="${cat}"]`);
      if (btn) {
        setCategoryFilter(cat, btn);
      } else {
        currentCategory = cat;
        filterToolsGrid();
      }
      const toolsSection = document.getElementById('tools');
      if (toolsSection) {
        toolsSection.scrollIntoView({ behavior: 'smooth' });
      }
    }

    function focusSearch() {
      const toolsSection = document.getElementById('tools');
      if (toolsSection) {
        toolsSection.scrollIntoView({ behavior: 'smooth' });
      }
      const search = document.getElementById('toolSearchInput');
      if (search) {
        setTimeout(() => {
          search.focus();
          search.select();
        }, 200);
      }
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

    function copyPreCode(btn) {
      const heading = btn.closest('.schema-block-heading');
      if (heading && heading.nextElementSibling) {
        const text = heading.nextElementSibling.textContent.trim();
        navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1500);
      }
    }

    function copyCliCmd(btn) {
      const container = btn.closest('.cli-cmd-display');
      if (container) {
        const span = container.querySelector('.cli-cmd-text');
        if (span) {
          navigator.clipboard.writeText(span.textContent.trim());
          const origTitle = btn.title;
          btn.title = 'Copied!';
          setTimeout(() => { btn.title = origTitle || 'Copy command'; }, 1500);
        }
      }
    }

    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        focusSearch();
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
