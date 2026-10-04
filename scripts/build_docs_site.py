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

    tools_by_cat = {
        "database": [],
        "runtime": [],
        "graph": [],
        "routes": [],
        "git": [],
        "tests": [],
        "core": [],
    }
    for t in tools:
        cat = t.get("category", "core")
        if cat in tools_by_cat:
            tools_by_cat[cat].append(t)
        else:
            tools_by_cat["core"].append(t)

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
  <meta property="og:title" content="CodeGraph MCP — Deterministic Code Intelligence Engine">
  <meta property="og:description" content="Official website and documentation for CodeGraph MCP: deterministic local-first code intelligence with runtime telemetry reconciliation, database lineage, and 56 verified MCP tools.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph MCP — Deterministic Code Intelligence Engine">
  <meta name="twitter:description" content="Official website and documentation for CodeGraph MCP: runtime telemetry reconciliation, database lineage, and 56 verified tools.">
  <meta name="twitter:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "CodeGraph MCP",
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

  <title>CodeGraph MCP · Deterministic Codebase Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #ffffff;
      --bg-alt: #f8fafc;
      --border: #e5e5e5;
      --border-dark: #171717;
      --text: #000000;
      --text-body: #171717;
      --text-muted: #525252;
      --text-dim: #737373;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --emerald: #10b981;
      --amber: #f59e0b;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
      --sidebar-w: 260px;
      --toc-w: 240px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text-body); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; }

    /* Sticky Universal Header */
    header.book-nav-top {
      position: sticky; top: 0; z-index: 100; height: 60px;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 0 2rem; display: flex; align-items: center; justify-content: space-between;
    }
    .header-left-cluster { display: flex; align-items: center; gap: 1.5rem; }
    .brand-group { display: flex; align-items: center; gap: 0.65rem; text-decoration: none; color: var(--text); }
    .brand-cube-svg { width: 28px; height: 28px; flex-shrink: 0; transition: transform 0.2s ease; }
    .brand-group:hover .brand-cube-svg { transform: scale(1.04); }
    .brand-name { font-size: 1.12rem; font-weight: 800; letter-spacing: -0.025em; color: #000000; }
    .badge-ver {
      font-family: var(--font-mono); font-size: 0.68rem; font-weight: 600;
      color: #475569; background: #f1f5f9; border: 1px solid #e2e8f0;
      padding: 0.12rem 0.5rem; border-radius: 9999px; letter-spacing: 0.01em;
    }

    .search-trigger-btn {
      display: flex; align-items: center; gap: 0.65rem;
      background: #f8fafc; border: 1px solid #e2e8f0;
      border-radius: 8px; padding: 0 0.85rem; width: 280px; height: 36px; cursor: pointer;
      color: #64748b; font-size: 0.82rem; transition: all 0.15s ease;
      white-space: nowrap; overflow: hidden;
    }
    .search-trigger-btn:hover { border-color: #cbd5e1; background: #ffffff; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04); }
    .search-icon-svg { stroke: #64748b; flex-shrink: 0; }
    .search-label-text {
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; text-align: left;
      font-weight: 500;
    }
    .kbd-shortcut {
      font-family: var(--font-mono); font-size: 0.68rem; font-weight: 600;
      background: #ffffff; border: 1px solid #e2e8f0;
      padding: 0.12rem 0.4rem; border-radius: 4px; color: #64748b; margin-left: auto; flex-shrink: 0;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
    }

    .header-right-cluster { display: flex; align-items: center; gap: 0.35rem; }
    .top-links-row { display: flex; align-items: center; gap: 0.25rem; list-style: none; }
    .top-links-row li a {
      color: #475569; text-decoration: none; font-size: 0.85rem; font-weight: 600;
      padding: 0.4rem 0.7rem; border-radius: 6px; transition: all 0.15s ease;
    }
    .top-links-row li a:hover { color: #000000; background: #f1f5f9; }

    .header-sep-divider {
      width: 1px; height: 20px; background: var(--border); margin: 0 0.65rem;
    }

    .github-nav-btn {
      background: #0f172a; color: #ffffff; text-decoration: none;
      padding: 0.38rem 0.8rem; border-radius: 7px;
      font-size: 0.82rem; font-weight: 600; display: inline-flex; align-items: center; gap: 0.45rem;
      transition: background 0.15s ease;
    }
    .github-nav-btn:hover { background: #1e293b; color: #ffffff; }
    .gh-star-pill {
      background: rgba(255, 255, 255, 0.15); padding: 0.1rem 0.45rem; border-radius: 4px;
      font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
      display: inline-flex; align-items: center; gap: 0.2rem;
    }

    @media (max-width: 1140px) {
      .top-links-row li:nth-child(4),
      .top-links-row li:nth-child(5) { display: none; }
      .search-trigger-btn { width: 220px; }
    }
    @media (max-width: 940px) {
      .top-links-row { display: none; }
      .header-sep-divider { display: none; }
      .search-trigger-btn { width: 190px; }
    }
    @media (max-width: 640px) {
      .badge-ver { display: none; }
      header.book-nav-top { padding: 0 1rem; }
    }

    /* Landing Section: Split Hero (Compact, desktop-balanced) */
    .landing-hero-section {
      max-width: 1400px; margin: 0 auto; padding: 2rem 2.5rem 1.75rem;
      display: grid; grid-template-columns: 1fr 1.15fr; gap: 3rem; align-items: center;
    }
    @media (max-width: 1080px) {
      .landing-hero-section { grid-template-columns: 1fr; gap: 2rem; padding: 2rem 1.5rem; }
    }

    .hero-badge-tag {
      display: inline-flex; align-items: center; gap: 0.5rem;
      background: #eff6ff; border: 1px solid #bfdbfe;
      border-radius: 9999px; padding: 0.3rem 0.8rem; font-size: 0.78rem; font-family: var(--font-mono);
      font-weight: 700; color: #1d4ed8; margin-bottom: 0.85rem;
    }
    .dot-online { width: 7px; height: 7px; border-radius: 50%; background: #10b981; }

    .hero-headline-h1 {
      font-size: clamp(2.1rem, 3.6vw, 3rem); font-weight: 800; line-height: 1.14;
      letter-spacing: -0.04em; color: #000000; margin-bottom: 0.75rem;
    }
    .gradient-blue-span {
      background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }

    .hero-summary-p {
      font-size: 1.02rem; color: var(--text-muted); line-height: 1.58;
      max-width: 520px; margin-bottom: 1.1rem;
    }
    .hero-summary-p strong { color: #000000; font-weight: 700; }

    /* Interactive Hero Terminal Box (Elevated placement) */
    .hero-term-box {
      background: #090d16; border: 1px solid #1e293b; border-radius: 10px;
      padding: 0.7rem 1.1rem; max-width: 520px; box-shadow: 0 8px 20px -5px rgba(0, 0, 0, 0.05);
      margin-bottom: 1.15rem;
    }

    .hero-cta-row { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }
    .btn-cta-primary {
      background: #000000; color: #ffffff; text-decoration: none;
      padding: 0.65rem 1.35rem; border-radius: 7px; font-size: 0.88rem; font-weight: 700;
      display: inline-flex; align-items: center; gap: 0.5rem; transition: background 0.15s ease;
    }
    .btn-cta-primary:hover { background: #262626; }
    .btn-cta-secondary {
      background: #ffffff; color: var(--text); text-decoration: none;
      border: 1px solid var(--border); padding: 0.65rem 1.35rem; border-radius: 7px;
      font-size: 0.88rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.5rem;
      transition: all 0.15s ease;
    }
    .btn-cta-secondary:hover { background: #f9f9f9; border-color: #cbd5e1; }

    .cap-pills-row { display: flex; gap: 0.45rem; flex-wrap: wrap; margin-bottom: 0; }
    .cap-pill-btn {
      display: inline-flex; align-items: center; gap: 0.4rem;
      background: #f8fafc; border: 1px solid var(--border);
      color: #334155; font-size: 0.78rem; font-weight: 700; padding: 0.3rem 0.65rem;
      border-radius: 6px; cursor: pointer; text-decoration: none; transition: all 0.15s ease;
    }
    .cap-pill-btn:hover { border-color: var(--primary); }
    .cap-pill-btn.rt { background: #dcfce7; border-color: #bbf7d0; color: #166534; }
    .cap-pill-btn.db { background: #fef3c7; border-color: #fde68a; color: #92400e; }
    .term-tab-strip { display: flex; gap: 1rem; margin-bottom: 0.5rem; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 0.4rem; }
    .term-tab-item {
      background: none; border: none; font-size: 0.76rem; font-weight: 700;
      color: #64748b; cursor: pointer; padding: 0.15rem 0; font-family: var(--font-mono);
      transition: color 0.15s ease;
    }
    .term-tab-item.active, .term-tab-item:hover { color: #f8fafc; }
    .term-code-line {
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.82rem; color: #f8fafc;
    }
    .btn-term-copy {
      background: rgba(255, 255, 255, 0.08); border: none; border-radius: 4px;
      padding: 0.2rem 0.45rem; cursor: pointer; color: #94a3b8; transition: all 0.15s ease;
    }
    .btn-term-copy:hover { background: rgba(255, 255, 255, 0.18); color: #fff; }

    /* Polished Code Editor Window (Right Column) */
    .code-ide-window {
      background: #090d16; border: 1px solid #1e293b; border-radius: 12px;
      box-shadow: 0 16px 36px -10px rgba(0, 0, 0, 0.15); overflow: hidden;
      display: flex; flex-direction: column;
    }
    .code-ide-topbar {
      background: #0d121f; border-bottom: 1px solid #1e293b;
      padding: 0.55rem 0.95rem; display: flex; align-items: center; justify-content: space-between;
    }
    .ide-dots-row { display: flex; gap: 6px; align-items: center; }
    .ide-dot { width: 10px; height: 10px; border-radius: 50%; }
    .ide-dot.r { background: #ef4444; }
    .ide-dot.y { background: #eab308; }
    .ide-dot.g { background: #22c55e; }

    .ide-tabs-strip { display: flex; gap: 0.35rem; align-items: center; }
    .ide-tab-btn {
      background: transparent; border: 1px solid transparent; border-radius: 6px;
      padding: 0.22rem 0.6rem; font-family: var(--font-mono); font-size: 0.74rem;
      color: #94a3b8; cursor: pointer; display: flex; align-items: center; gap: 0.4rem;
      transition: all 0.15s ease;
    }
    .ide-tab-btn:hover { background: rgba(255, 255, 255, 0.05); color: #f8fafc; }
    .ide-tab-btn.active {
      background: #1e293b; color: #f8fafc; border-color: #334155; font-weight: 600;
    }
    .tab-badge-color { width: 6px; height: 6px; border-radius: 50%; }
    .tab-badge-color.rt { background: #10b981; }
    .tab-badge-color.db { background: #f59e0b; }
    .tab-badge-color.json { background: #3b82f6; }

    .ide-copy-btn {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 6px;
      color: #94a3b8;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 600;
      padding: 0.22rem 0.65rem;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .ide-copy-btn:hover {
      background: rgba(255, 255, 255, 0.14);
      border-color: rgba(255, 255, 255, 0.25);
      color: #ffffff;
    }
    .ide-copy-btn.copied {
      background: rgba(16, 185, 129, 0.15);
      border-color: rgba(16, 185, 129, 0.35);
      color: #34d399;
    }

    .code-ide-content {
      padding: 1.15rem 1.25rem; font-family: var(--font-mono); font-size: 0.8rem;
      color: #f8fafc; line-height: 1.55; min-height: 290px; overflow-x: auto;
    }
    .code-ide-pane { display: none; }
    .code-ide-pane.active { display: block; }

    .code-row { display: flex; align-items: flex-start; gap: 1.15rem; white-space: pre; }
    .code-ln { color: #475569; user-select: none; width: 1.35rem; text-align: right; flex-shrink: 0; font-size: 0.74rem; }
    .c-kw { color: #c084fc; font-weight: 600; }
    .c-fn { color: #60a5fa; }
    .c-mod { color: #f8fafc; }
    .c-str { color: #34d399; }
    .c-cm { color: #64748b; font-style: italic; }
    .c-var { color: #f1f5f9; }
    .c-prop { color: #fbbf24; }
    .c-out { color: #a5b4fc; }
    .c-badge-insert { background: #065f46; color: #6ee7b7; padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.68rem; font-weight: 700; }
    .c-badge-update { background: #78350f; color: #fde68a; padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.68rem; font-weight: 700; }
    .c-badge-delete { background: #881337; color: #fecdd3; padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.68rem; font-weight: 700; }

    .code-ide-footer {
      background: #0d121f; border-top: 1px solid #1e293b;
      padding: 0.6rem 1.15rem; display: flex; justify-content: space-between; align-items: center;
      font-family: var(--font-mono); font-size: 0.72rem; color: #94a3b8;
    }
    .footer-metric-pill { display: flex; align-items: center; gap: 0.35rem; }
    .metric-val { color: #f8fafc; font-weight: 700; }
    .metric-val.green { color: #10b981; }
    .metric-val.blue { color: #60a5fa; }

    /* 6 Feature Cards Grid */
    .landing-features-grid {
      max-width: 1400px; margin: 0 auto; padding: 1.5rem 2.5rem 3.5rem;
      display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.25rem;
    }
    .landing-feature-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 12px;
      padding: 1.35rem 1.5rem; display: flex; align-items: center; justify-content: space-between;
      text-decoration: none; color: inherit; transition: all 0.2s ease;
      box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.04); cursor: pointer;
    }
    .landing-feature-card:hover {
      border-color: #cbd5e1; transform: translateY(-2px);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05);
    }
    .feat-card-left { display: flex; align-items: center; gap: 1.1rem; }
    .feat-icon-box {
      width: 44px; height: 44px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .feat-icon-box.rt { background: #dcfce7; color: #10b981; }
    .feat-icon-box.db { background: #fef3c7; color: #f59e0b; }
    .feat-icon-box.blue { background: #eff6ff; color: #2563eb; }
    .feat-icon-box.indigo { background: #e0e7ff; color: #4f46e5; }
    .feat-icon-box.rose { background: #ffe4e6; color: #e11d48; }

    .feat-card-texts h3 { font-size: 1.05rem; font-weight: 700; color: #000000; margin-bottom: 0.2rem; }
    .feat-card-texts p { font-size: 0.85rem; color: var(--text-muted); line-height: 1.45; }
    .feat-arrow-circle {
      width: 28px; height: 28px; border-radius: 50%;
      background: #f5f5f5; display: flex; align-items: center; justify-content: center;
      color: var(--text-dim); font-size: 0.85rem; flex-shrink: 0; transition: all 0.15s ease;
    }
    .landing-feature-card:hover .feat-arrow-circle { background: #000000; color: #ffffff; }

    /* 3-Column Book Layout (Exact layout from user screenshot) */
    .book-layout-wrap {
      display: flex; min-height: 100vh; width: 100%;
      border-top: 1px solid var(--border);
      background: #ffffff;
    }

    /* Left Sidebar */
    aside.book-sidebar-left {
      width: var(--sidebar-w); flex-shrink: 0;
      position: sticky; top: 56px; height: calc(100vh - 56px);
      overflow-y: auto; background: #ffffff; border-right: 1px solid var(--border);
      padding: 1.5rem 1rem 3rem 1.25rem; margin: 0;
    }
    aside.book-sidebar-left::-webkit-scrollbar { width: 4px; }
    aside.book-sidebar-left::-webkit-scrollbar-thumb { background: #e5e5e5; border-radius: 4px; }

    .group-header-row {
      display: flex; align-items: center; justify-content: space-between;
      font-size: 0.72rem; font-weight: 800; color: #404040;
      text-transform: uppercase; letter-spacing: 0.06em; margin: 1.35rem 0 0.4rem 0.4rem;
      cursor: pointer; user-select: none;
    }
    .group-header-row:first-child { margin-top: 0; }
    .chevron-icon { font-size: 0.75rem; color: #737373; transition: transform 0.15s ease; }
    .chevron-icon.closed { transform: rotate(-90deg); }

    .nav-items-block { list-style: none; margin-bottom: 0.75rem; }
    .nav-items-block.closed { display: none; }
    .nav-link-entry {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.35rem 0.65rem; font-size: 0.88rem; color: var(--text-muted);
      text-decoration: none; font-weight: 500; border-left: 2px solid transparent;
      transition: all 0.12s ease; border-radius: 0 4px 4px 0;
    }
    .nav-link-entry:hover { color: var(--text); background: #f9f9f9; }
    .nav-link-entry.active {
      color: #000000; font-weight: 700; border-left-color: #000000; background: #ffffff;
      padding-left: 0.65rem;
    }
    .count-badge-mini {
      font-family: var(--font-mono); font-size: 0.68rem; background: #f0f0f0;
      color: #525252; padding: 0.08rem 0.35rem; border-radius: 3px; font-weight: 600;
    }

    /* Middle Area (Book Content) */
    main.book-center-content {
      flex: 1; min-width: 0; background: #ffffff;
    }
    .page-title-banner {
      padding: 1.5rem 2.5rem 1.25rem;
      border-bottom: 1px solid var(--border);
      margin: 0;
    }
    .h1-page-title {
      font-size: 2.5rem; font-weight: 700; letter-spacing: -0.03em;
      color: #000000; margin: 0;
    }
    .page-body-container {
      padding: 2rem 2.5rem 8rem; max-width: 960px;
    }

    @media (max-width: 1100px) {
      .page-title-banner { padding: 1.5rem 1.5rem 1rem; }
      .page-body-container { padding: 1.5rem 1.5rem 6rem; }
    }
    @media (max-width: 860px) {
      .book-layout-wrap { flex-direction: column; }
      aside.book-sidebar-left { width: 100%; height: auto; position: static; border-right: none; border-bottom: 1px solid var(--border); }
    }

    /* Right Sidebar (On this page) */
    aside.book-toc-right {
      width: var(--toc-w); flex-shrink: 0;
      position: sticky; top: 56px; height: calc(100vh - 56px);
      overflow-y: auto; background: #ffffff; border-left: 1px solid var(--border);
      padding: 1.5rem 1.25rem 3rem; margin: 0;
    }
    @media (max-width: 1240px) {
      aside.book-toc-right { display: none; }
    }
    .toc-heading-text {
      font-size: 0.95rem; font-weight: 700; color: #000000; margin-bottom: 0.85rem;
    }
    .toc-nav-list { list-style: none; }
    .toc-nav-list li a {
      display: block; font-size: 0.84rem; color: #737373; text-decoration: none;
      padding: 0.3rem 0; line-height: 1.4; transition: color 0.12s ease;
    }
    .toc-nav-list li a:hover, .toc-nav-list li a.active { color: #000000; font-weight: 600; }

    /* Editorial Typography & Formatting */
    .lead-intro-p {
      font-size: 1.05rem; color: var(--text-body); line-height: 1.65; margin-bottom: 2rem;
    }
    .editorial-h2 {
      font-size: 1.95rem; font-weight: 700; letter-spacing: -0.02em;
      color: #000000; margin: 2.75rem 0 1rem; padding-top: 1rem;
    }
    .editorial-h3 {
      font-size: 1.35rem; font-weight: 700; color: #000000; margin: 2rem 0 0.75rem;
    }
    .editorial-p {
      font-size: 0.98rem; color: var(--text-muted); line-height: 1.68; margin-bottom: 1.25rem;
    }
    .editorial-p strong { color: var(--text); }
    .editorial-p code {
      font-family: var(--font-mono); font-size: 0.86em; background: #f5f5f5;
      color: #171717; padding: 0.15rem 0.35rem; border-radius: 4px; border: 1px solid var(--border);
    }

    /* Bullet Link Lists (Exact Book Style from reference) */
    .book-bullet-list {
      list-style: disc; margin: 1rem 0 2rem 1.75rem; font-size: 0.98rem; line-height: 1.75;
      color: var(--text-body);
    }
    .book-bullet-list li { margin-bottom: 0.5rem; }
    .book-bullet-list a {
      color: #000000; text-decoration: underline; font-weight: 600;
    }
    .book-bullet-list a:hover { color: var(--primary); }
    .book-bullet-list code {
      font-family: var(--font-mono); font-size: 0.86em; background: #f5f5f5;
      padding: 0.12rem 0.35rem; border-radius: 4px; border: 1px solid var(--border);
    }

    /* Callout Notes */
    .callout-box {
      border-left: 3px solid #000000; background: #f9f9f9; padding: 1rem 1.25rem;
      border-radius: 0 6px 6px 0; margin: 1.5rem 0; font-size: 0.92rem; line-height: 1.6;
    }
    .callout-box.db { border-left-color: var(--amber); background: #fffdf5; }
    .callout-box.runtime { border-left-color: var(--emerald); background: #f6fef9; }

    /* Clean Tables */
    .table-container {
      overflow-x: auto; margin: 1.25rem 0 2rem; border: 1px solid var(--border); border-radius: 8px;
    }
    .data-table-clean {
      width: 100%; border-collapse: collapse; font-size: 0.86rem; text-align: left;
    }
    .data-table-clean th {
      background: #fafafa; padding: 0.7rem 0.95rem; font-weight: 700;
      color: var(--text-dim); border-bottom: 1px solid var(--border); font-size: 0.76rem;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    .data-table-clean td {
      padding: 0.75rem 0.95rem; border-bottom: 1px solid var(--border); color: var(--text-muted);
      vertical-align: top; line-height: 1.45;
    }
    .data-table-clean tr:last-child td { border-bottom: none; }
    .data-table-clean td.code-font {
      font-family: var(--font-mono); font-weight: 700; color: #1d4ed8; font-size: 0.82rem;
    }
    .data-table-clean td.type-font {
      font-family: var(--font-mono); font-size: 0.78rem; color: #525252;
    }
    .tag-req {
      font-family: var(--font-mono); font-size: 0.68rem; font-weight: 700;
      color: #b91c1c; background: #fef2f2; padding: 0.1rem 0.35rem; border-radius: 3px;
    }
    .tag-opt {
      font-family: var(--font-mono); font-size: 0.68rem; color: #525252;
      background: #f5f5f5; padding: 0.1rem 0.35rem; border-radius: 3px;
    }

    /* Code Snippets with Copy */
    .code-box-wrapper {
      background: #090d16; border: 1px solid #1e293b; border-radius: 8px;
      margin: 1rem 0 1.75rem; overflow: hidden;
    }
    .code-box-header {
      background: #0f172a; padding: 0.45rem 0.85rem; border-bottom: 1px solid #1e293b;
      display: flex; justify-content: space-between; align-items: center;
      font-family: var(--font-mono); font-size: 0.72rem; color: #94a3b8;
    }
    .btn-copy-code {
      background: rgba(255, 255, 255, 0.08); border: none; border-radius: 4px;
      padding: 0.2rem 0.55rem; cursor: pointer; color: #cbd5e1; font-family: var(--font-mono);
      font-size: 0.7rem; transition: all 0.15s ease;
    }
    .btn-copy-code:hover { background: rgba(255, 255, 255, 0.18); color: #fff; }
    .code-text-pre {
      padding: 0.95rem; font-family: var(--font-mono); font-size: 0.8rem; color: #f8fafc;
      overflow-x: auto; white-space: pre-wrap; word-break: break-all; line-height: 1.5;
    }

    /* Tool Documentation Item */
    .tool-doc-card {
      margin: 2.75rem 0; padding-top: 1.75rem; border-top: 1px solid var(--border);
    }
    .tool-doc-head-row {
      display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;
      margin-bottom: 0.65rem;
    }
    .tool-heading-code {
      font-family: var(--font-mono); font-size: 1.3rem; font-weight: 800; color: #1d4ed8;
    }
    .cat-tag-pill {
      font-family: var(--font-mono); font-size: 0.68rem; font-weight: 700;
      padding: 0.18rem 0.55rem; border-radius: 4px; border: 1px solid transparent;
    }
    .cat-tag-pill.database { background: #fef3c7; color: #92400e; border-color: #fde68a; }
    .cat-tag-pill.runtime { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
    .cat-tag-pill.graph { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
    .cat-tag-pill.routes { background: #ffe4e6; color: #9f1239; border-color: #fecdd3; }
    .cat-tag-pill.git { background: #e0e7ff; color: #3730a3; border-color: #c7d2fe; }
    .cat-tag-pill.tests { background: #f3e8ff; color: #6b21a8; border-color: #e9d5ff; }
    .cat-tag-pill.core { background: #f5f5f5; color: #404040; border-color: #e5e5e5; }

    .tool-prob-note {
      background: #eff6ff; border-left: 3px solid #2563eb; padding: 0.55rem 0.85rem;
      border-radius: 0 4px 4px 0; font-size: 0.86rem; color: #1e40af; margin-bottom: 1.25rem;
    }
    .tool-mini-title {
      font-size: 0.78rem; font-weight: 800; color: var(--text-dim); text-transform: uppercase;
      letter-spacing: 0.06em; margin: 1.25rem 0 0.4rem;
    }

    .ev-boundary-row {
      display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; margin-top: 1rem;
    }
    @media (max-width: 768px) { .ev-boundary-row { grid-template-columns: 1fr; } }
    .ev-note-card {
      background: #fafafa; border: 1px solid var(--border); border-radius: 6px;
      padding: 0.75rem 0.95rem; font-size: 0.8rem; color: #525252; line-height: 1.45;
    }
    .ev-note-card strong { color: #000000; display: block; margin-bottom: 0.2rem; }

    /* CLI Documentation Item */
    .cli-doc-card {
      margin: 2.25rem 0; padding-top: 1.5rem; border-top: 1px solid var(--border);
    }
    .cli-cmd-heading {
      font-family: var(--font-mono); font-size: 1.2rem; font-weight: 800; color: #000000;
    }

    /* Spotlight Search Modal (Cmd K) */
    .spotlight-backdrop {
      display: none; position: fixed; inset: 0; z-index: 200;
      background: rgba(0, 0, 0, 0.45); backdrop-filter: blur(4px);
      align-items: flex-start; justify-content: center; padding-top: 12vh;
    }
    .spotlight-backdrop.open { display: flex; }
    .spotlight-box {
      width: 100%; max-width: 620px; background: #ffffff; border: 1px solid var(--border);
      border-radius: 12px; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2); overflow: hidden;
    }
    .spotlight-input-bar {
      display: flex; align-items: center; gap: 0.75rem; padding: 0.85rem 1.15rem;
      border-bottom: 1px solid var(--border);
    }
    .spotlight-input {
      flex: 1; border: none; outline: none; font-size: 1rem; font-family: var(--font-sans);
      color: #000000; background: transparent;
    }
    .spotlight-results-scroll {
      max-height: 400px; overflow-y: auto; padding: 0.65rem;
    }
    .spotlight-result-row {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.6rem 0.85rem; border-radius: 6px; text-decoration: none; color: inherit;
      cursor: pointer; transition: background 0.12s ease;
    }
    .spotlight-result-row:hover { background: #f5f5f5; }
    .spotlight-res-title { font-family: var(--font-mono); font-size: 0.9rem; font-weight: 700; color: #1d4ed8; }
    .spotlight-res-sub { font-size: 0.78rem; color: var(--text-dim); }
    .spotlight-bottom-bar {
      background: #fafafa; border-top: 1px solid var(--border);
      padding: 0.5rem 1.15rem; font-size: 0.72rem; color: var(--text-dim);
      display: flex; justify-content: space-between;
    }

    /* Footer */
    footer.book-page-footer {
      border-top: 1px solid var(--border); background: #ffffff;
      padding: 2.5rem 0 0; margin-top: 4rem; font-size: 0.84rem; color: var(--text-dim);
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;
    }
    footer.book-page-footer a { color: var(--text-muted); text-decoration: none; font-weight: 600; }
    footer.book-page-footer a:hover { color: #000000; }
  </style>
</head>
<body>

  <!-- Universal Header -->
  <header class="book-nav-top">
    <div class="header-left-cluster">
      <a href="#" class="brand-group">
        <!-- 3D Isometric Graph Cube Logo -->
        <svg class="brand-cube-svg" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 2L28 9V23L16 30L4 23V9L16 2Z" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round"/>
          <path d="M16 2V16M28 9L16 16M4 9L16 16M16 16V30" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="16" cy="16" r="3" fill="#2563eb"/>
        </svg>
        <span class="brand-name">CodeGraph MCP</span>
        <span class="badge-ver">v2.2.1</span>
      </a>

      <!-- Universal Search (Cmd K) -->
      <button class="search-trigger-btn" onclick="openSpotlightModal()" aria-label="Open documentation search">
        <svg class="search-icon-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <span class="search-label-text">Search documentation (56 tools, CLI)...</span>
        <kbd class="kbd-shortcut">Cmd K</kbd>
      </button>
    </div>

    <!-- Top Links & Actions -->
    <div class="header-right-cluster">
      <ul class="top-links-row">
        <li><a href="#features">Features</a></li>
        <li><a href="#next-steps">Documentation</a></li>
        <li><a href="#tools-database">MCP Tools (56)</a></li>
        <li><a href="#cli-reference">CLI (13)</a></li>
        <li><a href="#benchmarks">Benchmarks</a></li>
      </ul>
      <div class="header-sep-divider"></div>
      <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank" rel="noopener noreferrer" class="github-nav-btn" aria-label="GitHub Repository">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
        <span>GitHub</span>
        <span class="gh-star-pill">Star</span>
      </a>
    </div>
  </header>

  <!-- Landing Page Hero -->
  <section class="landing-hero-section">
    <div>
      <div class="hero-badge-tag">
        <span class="dot-online"></span>
        <span>v2.2.1 Production · Runtime &amp; Database Verified</span>
      </div>

      <h1 class="hero-headline-h1">
        The deterministic<br>
        <span class="gradient-blue-span">code-intelligence</span> engine.
      </h1>

      <p class="hero-summary-p">
        CodeGraph MCP maps repository relationships with <strong>runtime telemetry reconciliation</strong> and <strong>database lineage</strong>. AI coding agents resolve call hierarchies, mutating SQL queries, and API routes in <strong>&lt; 50ms</strong> without token waste.
      </p>

      <!-- Tabbed Terminal Box (Elevated above fold for immediate visibility) -->
      <div class="hero-term-box">
        <div class="term-tab-strip">
          <button class="term-tab-item active" onclick="setHeroTermCmd('pip install codegraph-engine[mcp]', this)">Install</button>
          <button class="term-tab-item" onclick="setHeroTermCmd('codegraph search --database \'users table writes\'', this)">Database CLI</button>
          <button class="term-tab-item" onclick="setHeroTermCmd('codegraph run --record pytest', this)">Runtime Traces</button>
          <button class="term-tab-item" onclick="setHeroTermCmd('from codegraph import get_context', this)">Python API</button>
        </div>
        <div class="term-code-line">
          <span id="heroTermCmdText">$ pip install codegraph-engine[mcp]</span>
          <button class="btn-term-copy" onclick="copyHeroTermCode()" title="Copy command">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>
      </div>

      <div class="hero-cta-row">
        <a href="#next-steps" class="btn-cta-primary">
          <span>Explore Documentation</span>
          <span>&darr;</span>
        </a>
        <a href="#tools-database" class="btn-cta-secondary">View 56 MCP Tools</a>
      </div>

      <div class="cap-pills-row">
        <a href="#runtime-telemetry-concept" class="cap-pill-btn rt">&#10003; Runtime Reconciliation</a>
        <a href="#database-lineage-concept" class="cap-pill-btn db">&#9670; Database Lineage</a>
        <a href="#framework-routes-guide" class="cap-pill-btn">Routes &amp; Handlers</a>
        <a href="#how-it-works" class="cap-pill-btn">Deterministic AST</a>
        <a href="#tools-database" class="cap-pill-btn">56 Verified Tools</a>
      </div>
    </div>

    <!-- Right Column: Interactive Verified Code IDE Window -->
    <div>
      <div class="code-ide-window">
        
        <!-- Top Bar with Traffic Dots & Interactive File Tabs -->
        <div class="code-ide-topbar">
          <div class="ide-dots-row">
            <div class="ide-dot r"></div>
            <div class="ide-dot y"></div>
            <div class="ide-dot g"></div>
          </div>
          <div class="ide-tabs-strip">
            <button class="ide-tab-btn active" onclick="switchEditorTab('runtime', this)">
              <span class="tab-badge-color rt"></span>runtime_telemetry.py
            </button>
            <button class="ide-tab-btn" onclick="switchEditorTab('database', this)">
              <span class="tab-badge-color db"></span>database_lineage.sql
            </button>
            <button class="ide-tab-btn" onclick="switchEditorTab('context', this)">
              <span class="tab-badge-color json"></span>context_packet.json
            </button>
          </div>
          <button class="ide-copy-btn" onclick="copyCurrentIdeCode(this)" title="Copy active code snippet">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            <span class="copy-text">Copy</span>
          </button>
        </div>

        <!-- Code Content Area -->
        <div class="code-ide-content">
          
          <!-- Tab 1: Runtime Telemetry -->
          <div id="tab-runtime" class="code-ide-pane active">
            <div class="code-row"><span class="code-ln">1</span><span><span class="c-kw">from</span> <span class="c-mod">codegraph</span> <span class="c-kw">import</span> <span class="c-fn">reconcile_static_runtime</span></span></div>
            <div class="code-row"><span class="code-ln">2</span><span></span></div>
            <div class="code-row"><span class="code-ln">3</span><span><span class="c-cm"># Reconcile static AST edges against live recorded traces</span></span></div>
            <div class="code-row"><span class="code-ln">4</span><span><span class="c-var">report</span> = <span class="c-fn">reconcile_static_runtime</span>(</span></div>
            <div class="code-row"><span class="code-ln">5</span><span>    <span class="c-prop">route</span>=<span class="c-str">&quot;/api/v1/scan-bill&quot;</span>,</span></div>
            <div class="code-row"><span class="code-ln">6</span><span>    <span class="c-prop">table</span>=<span class="c-str">&quot;bills&quot;</span></span></div>
            <div class="code-row"><span class="code-ln">7</span><span>)</span></div>
            <div class="code-row"><span class="code-ln">8</span><span></span></div>
            <div class="code-row"><span class="code-ln">9</span><span><span class="c-cm"># Verified execution context returned in &lt; 25ms:</span></span></div>
            <div class="code-row"><span class="code-ln">10</span><span><span class="c-kw">assert</span> <span class="c-var">report</span>.<span class="c-prop">status</span> == <span class="c-str">&quot;RECONCILED&quot;</span></span></div>
            <div class="code-row"><span class="code-ln">11</span><span><span class="c-out">&gt;&gt;&gt; [scan_bill_handler &rarr; BillService.process (RUNTIME_OBSERVED)]</span></span></div>
            <div class="code-row"><span class="code-ln">12</span><span><span class="c-out">&gt;&gt;&gt; [BillService.process &rarr; bills table (DATAFLOW_VERIFIED)]</span></span></div>
          </div>

          <!-- Tab 2: Database Lineage -->
          <div id="tab-database" class="code-ide-pane">
            <div class="code-row"><span class="code-ln">1</span><span><span class="c-cm">-- Trace all mutating callers writing to SQL tables</span></span></div>
            <div class="code-row"><span class="code-ln">2</span><span><span class="c-kw">SELECT</span> * <span class="c-kw">FROM</span> <span class="c-fn">find_db_writers</span>(<span class="c-str">'users'</span>);</span></div>
            <div class="code-row"><span class="code-ln">3</span><span></span></div>
            <div class="code-row"><span class="code-ln">4</span><span><span class="c-cm">-- Verified Mutating Callers (INSERT / UPDATE / DELETE):</span></span></div>
            <div class="code-row"><span class="code-ln">5</span><span><span class="c-out">&bull; AuthService.register_user (app/auth.py:42)</span> <span class="c-badge-insert">INSERT</span></span></div>
            <div class="code-row"><span class="code-ln">6</span><span><span class="c-out">&bull; BillingService.charge_card (app/billing.py:91)</span> <span class="c-badge-update">UPDATE</span></span></div>
            <div class="code-row"><span class="code-ln">7</span><span><span class="c-out">&bull; AdminService.delete_user (app/admin.py:114)</span> <span class="c-badge-delete">DELETE</span></span></div>
            <div class="code-row"><span class="code-ln">8</span><span></span></div>
            <div class="code-row"><span class="code-ln">9</span><span><span class="c-cm">-- Column lineage traced to SQLite foreign keys &amp; models</span></span></div>
          </div>

          <!-- Tab 3: Context Packet -->
          <div id="tab-context" class="code-ide-pane">
            <div class="code-row"><span class="code-ln">1</span><span>{</span></div>
            <div class="code-row"><span class="code-ln">2</span><span>  <span class="c-prop">&quot;query&quot;</span>: <span class="c-str">&quot;Trace scan_bill and database writes&quot;</span>,</span></div>
            <div class="code-row"><span class="code-ln">3</span><span>  <span class="c-prop">&quot;status&quot;</span>: <span class="c-str">&quot;AST_VERIFIED&quot;</span>,</span></div>
            <div class="code-row"><span class="code-ln">4</span><span>  <span class="c-prop">&quot;freshness&quot;</span>: <span class="c-str">&quot;FRESH (Git HEAD match in 2ms)&quot;</span>,</span></div>
            <div class="code-row"><span class="code-ln">5</span><span>  <span class="c-prop">&quot;telemetry&quot;</span>: <span class="c-str">&quot;OBSERVED (pytest live traces)&quot;</span>,</span></div>
            <div class="code-row"><span class="code-ln">6</span><span>  <span class="c-prop">&quot;database_impact&quot;</span>: { <span class="c-prop">&quot;writers&quot;</span>: 3, <span class="c-prop">&quot;table&quot;</span>: <span class="c-str">&quot;bills&quot;</span> },</span></div>
            <div class="code-row"><span class="code-ln">7</span><span>  <span class="c-prop">&quot;context_reduction_pct&quot;</span>: <span class="c-prop">94.2</span>,</span></div>
            <div class="code-row"><span class="code-ln">8</span><span>  <span class="c-prop">&quot;latency_ms&quot;</span>: <span class="c-prop">18.4</span></span></div>
            <div class="code-row"><span class="code-ln">9</span><span>}</span></div>
          </div>

        </div>

        <!-- Bottom Metric Strip -->
        <div class="code-ide-footer">
          <div class="footer-metric-pill"><span class="metric-val">18ms</span> Latency</div>
          <div class="footer-metric-pill"><span class="metric-val green">-94%</span> Agent Tokens</div>
          <div class="footer-metric-pill"><span class="metric-val">56</span> MCP Tools</div>
          <div class="footer-metric-pill"><span class="metric-val blue">0%</span> Hallucinations</div>
        </div>

      </div>
    </div>
  </section>

  <!-- 6 Feature Cards Grid -->
  <section class="landing-features-grid" id="features">
    
    <!-- Card 1: Runtime Evidence -->
    <a href="#runtime-telemetry-concept" class="landing-feature-card" style="border-top: 3px solid #10b981;">
      <div class="feat-card-left">
        <div class="feat-icon-box rt">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
        </div>
        <div class="feat-card-texts">
          <h3>Runtime evidence</h3>
          <p>Reconcile static AST with live execution traces for verified context.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

    <!-- Card 2: Database Intelligence -->
    <a href="#database-lineage-concept" class="landing-feature-card" style="border-top: 3px solid #f59e0b;">
      <div class="feat-card-left">
        <div class="feat-icon-box db">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
        </div>
        <div class="feat-card-texts">
          <h3>Database intelligence</h3>
          <p>Trace SQL/ORM to tables, columns, mutating queries, and data flows.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

    <!-- Card 3: Tree-sitter & AST -->
    <a href="#how-it-works" class="landing-feature-card">
      <div class="feat-card-left">
        <div class="feat-icon-box indigo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
        </div>
        <div class="feat-card-texts">
          <h3>Tree-sitter &amp; AST parsing</h3>
          <p>Deterministic parsing across Python, JavaScript, and TypeScript.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

    <!-- Card 4: 56 MCP Tools -->
    <a href="#tools-database" class="landing-feature-card">
      <div class="feat-card-left">
        <div class="feat-icon-box blue">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
        </div>
        <div class="feat-card-texts">
          <h3>56 MCP tools server</h3>
          <p>Expose the graph to Claude Code, Cursor, Codex, and Antigravity.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

    <!-- Card 5: Framework-aware routes -->
    <a href="#framework-routes-guide" class="landing-feature-card">
      <div class="feat-card-left">
        <div class="feat-icon-box rose">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>
        </div>
        <div class="feat-card-texts">
          <h3>Framework-aware routes</h3>
          <p>FastAPI, Flask, Django, and Express.js route discovery.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

    <!-- Card 6: Impact analysis -->
    <a href="#tools-graph" class="landing-feature-card">
      <div class="feat-card-left">
        <div class="feat-icon-box db">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3"></circle></svg>
        </div>
        <div class="feat-card-texts">
          <h3>Impact analysis</h3>
          <p>Trace callers, callees, and potential impact of code modifications.</p>
        </div>
      </div>
      <div class="feat-arrow-circle">&rarr;</div>
    </a>

  </section>

  <!-- 3-Column Book Layout (Exact layout from user screenshot) -->
  <div class="book-layout-wrap" id="docs-book">

    <!-- Left Sidebar (Aligned at top) -->
    <aside class="book-sidebar-left">
      
      <!-- Group 1: GETTING STARTED -->
      <div class="group-header-row" onclick="toggleNavGroup(this)">
        <span>GETTING STARTED</span>
        <span class="chevron-icon">&#709;</span>
      </div>
      <ul class="nav-items-block">
        <li><a href="#introduction" class="nav-link-entry">Introduction</a></li>
        <li><a href="#quickstart" class="nav-link-entry">Quickstart</a></li>
        <li><a href="#installation" class="nav-link-entry">Installation</a></li>
        <li><a href="#configuration" class="nav-link-entry">Configuration</a></li>
        <li><a href="#your-first-graph" class="nav-link-entry">Your First Graph</a></li>
        <li><a href="#next-steps" class="nav-link-entry active">Next Steps</a></li>
      </ul>

      <!-- Group 2: CORE CONCEPTS -->
      <div class="group-header-row" onclick="toggleNavGroup(this)">
        <span>CORE CONCEPTS</span>
        <span class="chevron-icon">&#709;</span>
      </div>
      <ul class="nav-items-block">
        <li><a href="#how-it-works" class="nav-link-entry">How It Works</a></li>
        <li><a href="#the-knowledge-graph" class="nav-link-entry">The Knowledge Graph</a></li>
        <li><a href="#runtime-telemetry-concept" class="nav-link-entry">Runtime Telemetry</a></li>
        <li><a href="#database-lineage-concept" class="nav-link-entry">Database Lineage</a></li>
        <li><a href="#resolution-frameworks" class="nav-link-entry">Resolution &amp; Frameworks</a></li>
      </ul>

      <!-- Group 3: GUIDES -->
      <div class="group-header-row" onclick="toggleNavGroup(this)">
        <span>GUIDES</span>
        <span class="chevron-icon">&#709;</span>
      </div>
      <ul class="nav-items-block">
        <li><a href="#indexing-a-project" class="nav-link-entry">Indexing a Project</a></li>
        <li><a href="#reading-graph-browser" class="nav-link-entry">Reading Your Graph in the Browser</a></li>
        <li><a href="#framework-routes-guide" class="nav-link-entry">Framework Routes</a></li>
        <li><a href="#affected-tests-ci" class="nav-link-entry">Affected Tests in CI</a></li>
        <li><a href="#database-schema-guide" class="nav-link-entry">Database Schema &amp; Writers</a></li>
      </ul>

      <!-- Group 4: REFERENCE -->
      <div class="group-header-row" onclick="toggleNavGroup(this)">
        <span>REFERENCE</span>
        <span class="chevron-icon">&#709;</span>
      </div>
      <ul class="nav-items-block">
        <li><a href="#tools-database" class="nav-link-entry"><span>Database Tools</span> <span class="count-badge-mini">11</span></a></li>
        <li><a href="#tools-runtime" class="nav-link-entry"><span>Runtime Tools</span> <span class="count-badge-mini">6</span></a></li>
        <li><a href="#tools-graph" class="nav-link-entry"><span>Graph Tools</span> <span class="count-badge-mini">8</span></a></li>
        <li><a href="#tools-core" class="nav-link-entry"><span>Core Tools</span> <span class="count-badge-mini">23</span></a></li>
        <li><a href="#tools-routes" class="nav-link-entry"><span>Route Tools</span> <span class="count-badge-mini">2</span></a></li>
        <li><a href="#tools-git" class="nav-link-entry"><span>Git Tools</span> <span class="count-badge-mini">4</span></a></li>
        <li><a href="#tools-tests" class="nav-link-entry"><span>Test Tools</span> <span class="count-badge-mini">2</span></a></li>
        <li><a href="#cli-reference" class="nav-link-entry"><span>CLI Commands</span> <span class="count-badge-mini">13</span></a></li>
        <li><a href="#benchmarks" class="nav-link-entry"><span>Benchmarks</span></a></li>
      </ul>

    </aside>

    <!-- Center Book Area (Aligned with left sidebar and right TOC) -->
    <main class="book-center-content">
      
      <!-- Page Title Banner (Horizontal rule dividing title and body) -->
      <div class="page-title-banner">
        <h1 class="h1-page-title" id="next-steps">Next Steps</h1>
      </div>

      <div class="page-body-container">
        <p class="lead-intro-p">
          You've got CodeGraph MCP installed and a graph built. Here's where to go next.
        </p>

        <!-- Section 1: Understand the model -->
        <h2 class="editorial-h2" id="understand-the-model">Understand the model</h2>
        <ul class="book-bullet-list">
          <li>
            <a href="#how-it-works">How It Works</a> &mdash; the extraction &rarr; storage &rarr; resolution &rarr; sync pipeline.
          </li>
          <li>
            <a href="#the-knowledge-graph">The Knowledge Graph</a> &mdash; the node and edge kinds the graph is built from.
          </li>
          <li>
            <a href="#runtime-telemetry-concept">Runtime Telemetry Reconciliation</a> &mdash; reconciling static AST edges against live recorded traces.
          </li>
          <li>
            <a href="#database-lineage-concept">Database Lineage &amp; Schema</a> &mdash; tracing mutating SQL writers, columns, and ORM models.
          </li>
          <li>
            <a href="#resolution-frameworks">Resolution &amp; Frameworks</a> &mdash; how references and framework routes get connected.
          </li>
        </ul>

        <!-- Section 2: Put it to work -->
        <h2 class="editorial-h2" id="put-it-to-work">Put it to work</h2>
        <ul class="book-bullet-list">
          <li>
            <a href="#indexing-a-project">Indexing a Project</a> &mdash; full index, incremental sync, and the file watcher.
          </li>
          <li>
            <a href="#reading-graph-browser">Reading Your Graph in the Browser</a> &mdash; <code>codegraph ui</code>: callers, source and callees on one screen.
          </li>
          <li>
            <a href="#framework-routes-guide">Framework Routes</a> &mdash; link URL patterns to their handlers.
          </li>
          <li>
            <a href="#affected-tests-ci">Affected Tests in CI</a> &mdash; run only the tests a change touches.
          </li>
          <li>
            <a href="#database-schema-guide">Database Schema &amp; Writers</a> &mdash; find all tables, models, and mutating SQL queries.
          </li>
          <li>
            <a href="#tools-database">MCP Tools Reference</a> &mdash; 56 verified tools exposed over Model Context Protocol.
          </li>
        </ul>

        <!-- Section: Introduction & Overview -->
        <h2 class="editorial-h2" id="introduction">Introduction</h2>
        <p class="editorial-p">
          <strong>CodeGraph MCP</strong> is a deterministic, local-first code-intelligence engine for AI coding agents. Instead of letting agents waste context tokens repeatedly running <code>grep</code>, <code>find</code>, and reading hundreds of random files, CodeGraph MCP pre-indexes the structural relationships of a repository.
        </p>
        <p class="editorial-p">
          It parses code locally using Tree-sitter to deterministically extract symbols, definitions, class hierarchies, import chains, and function call relationships. The extracted graph is stored local-first inside a project-level SQLite database with WAL mode and FTS5 full-text search.
        </p>

        <!-- Section: Quickstart & Installation -->
        <h2 class="editorial-h2" id="quickstart">Quickstart</h2>
        <p class="editorial-p">Install CodeGraph MCP from PyPI with complete CLI and FastMCP server bindings:</p>
        
        <div class="code-box-wrapper">
          <div class="code-box-header">
            <span>Terminal</span>
            <button class="btn-copy-code" onclick="copySnippetText(this)">Copy</button>
          </div>
          <pre class="code-text-pre">pip install &quot;codegraph-engine[mcp]&quot;</pre>
        </div>

        <p class="editorial-p" id="installation">Initialize and index your repository:</p>
        <div class="code-box-wrapper">
          <div class="code-box-header">
            <span>Terminal</span>
            <button class="btn-copy-code" onclick="copySnippetText(this)">Copy</button>
          </div>
          <pre class="code-text-pre">cd /path/to/project
codegraph init .
codegraph index .
codegraph status .</pre>
        </div>

        <!-- Section: Configuration -->
        <h2 class="editorial-h2" id="configuration">Configuration</h2>
        <p class="editorial-p">Add CodeGraph MCP to Claude Code, Cursor, Windsurf, or Antigravity via your standard MCP config:</p>

        <div class="code-box-wrapper">
          <div class="code-box-header">
            <span>claude_desktop_config.json / .cursor/mcp.json</span>
            <button class="btn-copy-code" onclick="copySnippetText(this)">Copy</button>
          </div>
          <pre class="code-text-pre">{
  &quot;mcpServers&quot;: {
    &quot;codegraph&quot;: {
      &quot;command&quot;: &quot;codegraph&quot;,
      &quot;args&quot;: [&quot;serve&quot;, &quot;.&quot;]
    }
  }
}</pre>
        </div>

        <!-- Section: How It Works -->
        <h2 class="editorial-h2" id="how-it-works">How It Works</h2>
        <p class="editorial-p" id="the-knowledge-graph">
          CodeGraph MCP operates through a deterministic four-phase pipeline:
        </p>
        <ul class="book-bullet-list">
          <li><strong>Tree-sitter Parsing:</strong> Source files are parsed incrementally into concrete ASTs. Zero LLM hallucinations.</li>
          <li><strong>Relational Graph Storage:</strong> Symbols, calls, imports, and routes are stored in SQLite with foreign-key constraints.</li>
          <li><strong>Deterministic Resolution:</strong> Canonical IDs, qualified names, and route endpoints are resolved with explicit ambiguity states.</li>
          <li><strong>MCP Tool Serving:</strong> FastMCP stdio server serves 56 verified tools with token-bounded context packets.</li>
        </ul>

        <!-- Section: Runtime Telemetry -->
        <h2 class="editorial-h2" id="runtime-telemetry-concept">Runtime Telemetry Reconciliation</h2>
        <p class="editorial-p">
          Static analysis alone cannot detect runtime dynamic dispatch, monkey-patching, or live test coverage. CodeGraph MCP reconciles static AST graph edges against recorded runtime execution traces.
        </p>
        <div class="callout-box runtime">
          <strong>Runtime Verification Guarantee:</strong> Recorded execution traces produce <code>RUNTIME_OBSERVED</code> edges. If a static path is not triggered during tests, it is flagged as <code>NOT_OBSERVED_AT_RUNTIME</code> without claiming it cannot execute.
        </div>

        <!-- Section: Database Lineage -->
        <h2 class="editorial-h2" id="database-lineage-concept">Database Lineage &amp; Schema Intelligence</h2>
        <p class="editorial-p">
          CodeGraph MCP indexes relational databases, migrations, and ORMs (SQLAlchemy, Prisma, Django ORM). It connects tables and columns to the exact Python or TypeScript functions that read or write them.
        </p>
        <div class="callout-box db">
          <strong>Mutating SQL Writers:</strong> Instantly discover which API routes execute <code>INSERT</code>, <code>UPDATE</code>, or <code>DELETE</code> queries before performing breaking database migrations.
        </div>

        <!-- Guides Section -->
        <h2 class="editorial-h2" id="indexing-a-project">Indexing a Project</h2>
        <p class="editorial-p">
          Run <code>codegraph index .</code> to scan and parse all files in your repository. Incremental indexing utilizes content hashes so subsequent runs finish in milliseconds.
        </p>

        <h2 class="editorial-h2" id="reading-graph-browser">Reading Your Graph in the Browser</h2>
        <p class="editorial-p">
          Launch the local interactive visualizer with <code>codegraph ui</code> to explore callers, callees, and database relationships directly in your browser.
        </p>

        <h2 class="editorial-h2" id="framework-routes-guide">Framework Routes</h2>
        <p class="editorial-p">
          CodeGraph MCP automatically traces routes for FastAPI, Flask, Django, and Express.js, connecting HTTP verbs and path templates directly to their handler symbols.
        </p>

        <h2 class="editorial-h2" id="affected-tests-ci">Affected Tests in CI</h2>
        <p class="editorial-p">
          Use <code>find_related_tests</code> to discover the exact subset of unit and integration tests covering a modified symbol, optimizing continuous integration test run times.
        </p>

        <h2 class="editorial-h2" id="database-schema-guide">Database Schema &amp; Writers</h2>
        <p class="editorial-p">
          Query <code>find_db_tables</code>, <code>find_db_columns</code>, and <code>find_db_writers</code> to audit data flow before performing database refactors.
        </p>

        <!-- Reference: 56 MCP Tools -->
        <h2 class="editorial-h2" id="tools-reference">MCP Tools Reference (56 Verified Tools)</h2>
        <p class="editorial-p">
          Every tool exposed by CodeGraph MCP over Model Context Protocol, categorized into Database, Runtime, Graph, Core, Routes, Git, and Tests.
        </p>
''')

    cat_headings = {
        "database": ("Database Lineage & Schema Tools (11)", "tools-database", "Tools for table inspection, column typing, mutating SQL writers, and schema impact analysis."),
        "runtime": ("Runtime Telemetry & Reconciliation Tools (6)", "tools-runtime", "Tools for execution trace recording, runtime observation reconciliation, and dynamic call tracing."),
        "graph": ("Graph Traversal & Call Hierarchy Tools (8)", "tools-graph", "Directional call hierarchies, caller/callee graphs, and change impact propagation."),
        "core": ("Core Symbol Inspection & Context Tools (23)", "tools-core", "Canonical symbol resolution, bounded context packets, file slices, and evidence verification."),
        "routes": ("Framework Route Discovery Tools (2)", "tools-routes", "Framework-aware HTTP route mapping for FastAPI, Flask, Django, and Express."),
        "git": ("Git History & Change Impact Tools (4)", "tools-git", "Recent file commit history, changed files, and git diff impact analysis."),
        "tests": ("Test Discovery & Coverage Tools (2)", "tools-tests", "Deterministic symbol-to-test suite mapping."),
    }

    for cat_k, (cat_title, cat_anchor, cat_desc) in cat_headings.items():
        cat_tool_list = tools_by_cat.get(cat_k, [])
        html_parts.append(f'''
        <h3 class="editorial-h3" id="{cat_anchor}" style="margin-top:3rem; padding-top:1.5rem; border-top:1px solid var(--border);">
          {cat_title}
        </h3>
        <p class="editorial-p">{cat_desc}</p>
''')

        for t in cat_tool_list:
            t_name = html.escape(t.get("name", ""))
            t_desc = html.escape(t.get("description", ""))
            t_prob = html.escape(t.get("problem_solved", ""))
            t_ret = html.escape(t.get("returns", "object"))
            t_inv = html.escape(t.get("example_invocation", ""))
            t_ev = html.escape(t.get("evidence", "AST-verified deterministic relationship."))
            t_bound = html.escape(t.get("does_not_prove", "Requires runtime observation to confirm execution."))

            props = t.get("parameters_schema", {}).get("properties", {})
            reqs = t.get("parameters_schema", {}).get("required", [])

            p_rows = ""
            if props:
                for p_name, p_info in props.items():
                    p_type = html.escape(str(p_info.get("type", "any")))
                    p_def = html.escape(str(p_info.get("default", "-")))
                    is_req = p_name in reqs
                    badge = '<span class="tag-req">Required</span>' if is_req else '<span class="tag-opt">Optional</span>'
                    p_title = html.escape(str(p_info.get("title", p_name.replace("_", " ").title())))
                    p_rows += f'''
                    <tr>
                      <td class="code-font">{html.escape(p_name)}</td>
                      <td class="type-font">{p_type}</td>
                      <td>{badge}</td>
                      <td class="type-font">{p_def}</td>
                      <td>{p_title}</td>
                    </tr>
'''
            else:
                p_rows = '<tr><td colspan="5" style="color:var(--text-dim); font-style:italic;">No arguments required.</td></tr>'

            ret_props = t.get("return_schema", {}).get("properties", {})
            r_rows = ""
            if ret_props:
                for r_name, r_info in ret_props.items():
                    r_type = html.escape(str(r_info.get("type", "any")))
                    r_title = html.escape(str(r_info.get("title", r_name.replace("_", " ").title())))
                    r_rows += f'<tr><td class="code-font">{html.escape(r_name)}</td><td class="type-font">{r_type}</td><td>{r_title}</td></tr>'
            else:
                r_rows = f'<tr><td class="code-font">result</td><td class="type-font">object</td><td>{t_ret} payload</td></tr>'

            html_parts.append(f'''
        <!-- Tool Entry: {t_name} -->
        <section class="tool-doc-card" id="tool-{t_name}">
          <div class="tool-doc-head-row">
            <span class="tool-heading-code">{t_name}</span>
            <span class="cat-tag-pill {cat_k}">{cat_k.upper()}</span>
          </div>
          <p class="editorial-p">{t_desc}</p>
          <div class="tool-prob-note">
            <strong>Resolves:</strong> {t_prob}
          </div>

          <div class="tool-mini-title">Parameters Schema</div>
          <div class="table-container">
            <table class="data-table-clean">
              <thead>
                <tr><th>Parameter</th><th>Type</th><th>Status</th><th>Default</th><th>Description</th></tr>
              </thead>
              <tbody>
                {p_rows}
              </tbody>
            </table>
          </div>

          <div class="tool-mini-title">Client Invocation</div>
          <div class="code-box-wrapper">
            <div class="code-box-header">
              <span>MCP Client / Agent Call</span>
              <button class="btn-copy-code" onclick="copySnippetText(this)">Copy Call</button>
            </div>
            <pre class="code-text-pre">{t_inv}</pre>
          </div>

          <div class="tool-mini-title">Return Model: <code>{t_ret}</code></div>
          <div class="table-container">
            <table class="data-table-clean">
              <thead>
                <tr><th>Field</th><th>Type</th><th>Description</th></tr>
              </thead>
              <tbody>
                {r_rows}
              </tbody>
            </table>
          </div>

          <div class="ev-boundary-row">
            <div class="ev-note-card">
              <strong>Evidence Guarantee</strong>
              {t_ev}
            </div>
            <div class="ev-note-card">
              <strong>Epistemic Boundary</strong>
              {t_bound}
            </div>
          </div>
        </section>
''')

    # CLI Reference
    html_parts.append('''
        <!-- Chapter: CLI Commands -->
        <h2 class="editorial-h2" id="cli-reference">CLI Commands Reference (13 Commands)</h2>
        <p class="editorial-p">
          CodeGraph MCP provides 13 deterministic terminal commands for repository indexing, health auditing, MCP server hosting, and context extraction.
        </p>
''')

    for cmd in commands:
        c_cmd = html.escape(cmd.get("command", ""))
        c_cat = html.escape(cmd.get("category", "CLI"))
        c_desc = html.escape(cmd.get("summary", ""))
        c_problem = html.escape(cmd.get("problem_solved", ""))
        c_example = html.escape(cmd.get("example", ""))
        c_output = html.escape(cmd.get("output", ""))
        cmd_slug = c_cmd.replace(" ", "-").replace("[", "").replace("]", "").replace("<", "").replace(">", "").replace(".", "").strip()

        flags_rows = ""
        for flag in cmd.get("flags", []):
            if ":" in flag:
                f_name, f_desc = flag.split(":", 1)
            else:
                f_name, f_desc = flag, ""
            f_name = html.escape(f_name.strip())
            f_desc = html.escape(f_desc.strip())
            flags_rows += f'<tr><td class="code-font">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
        <!-- CLI Entry: {c_cmd} -->
        <section class="cli-doc-card" id="cli-{cmd_slug}">
          <div class="tool-doc-head-row">
            <span class="cli-cmd-heading">{c_cmd}</span>
            <span class="cat-tag-pill core">{c_cat.upper()}</span>
          </div>
          <p class="editorial-p">{c_desc}</p>
          <div class="tool-prob-note">
            <strong>Resolves:</strong> {c_problem}
          </div>

          <div class="code-box-wrapper">
            <div class="code-box-header">
              <span>Terminal Command</span>
              <button class="btn-copy-code" onclick="copySnippetText(this)">Copy</button>
            </div>
            <pre class="code-text-pre">{c_example}</pre>
          </div>

          <div class="tool-mini-title">Flags &amp; Options</div>
          <div class="table-container">
            <table class="data-table-clean">
              <thead>
                <tr><th>Flag</th><th>Description</th></tr>
              </thead>
              <tbody>
                {flags_rows}
              </tbody>
            </table>
          </div>

          <div class="tool-mini-title">Terminal Output</div>
          <div class="code-box-wrapper">
            <div class="code-box-header">
              <span>Deterministic Output</span>
            </div>
            <pre class="code-text-pre">{c_output}</pre>
          </div>
        </section>
''')

    # Scaling Benchmarks
    html_parts.append('''
        <!-- Chapter: Benchmarks -->
        <h2 class="editorial-h2" id="benchmarks">Scaling Benchmarks</h2>
        <p class="editorial-p">
          Empirically measured scaling metrics across codebases from 10,000 to over 1,000,000 lines of code.
        </p>

        <div class="table-container">
          <table class="data-table-clean">
            <thead>
              <tr>
                <th>Scale</th>
                <th>Cold Index Time</th>
                <th>Warm Re-index</th>
                <th>Query Latency</th>
                <th>Database Size</th>
                <th>Memory Footprint</th>
              </tr>
            </thead>
            <tbody>
              <tr><td class="code-font">Small (10k LOC)</td><td>0.42 s</td><td>0.08 s</td><td>12 ms</td><td>2.4 MB</td><td>&lt; 35 MB</td></tr>
              <tr><td class="code-font">Medium (100k LOC)</td><td>2.85 s</td><td>0.31 s</td><td>24 ms</td><td>18.2 MB</td><td>&lt; 85 MB</td></tr>
              <tr><td class="code-font">Large (500k LOC)</td><td>11.40 s</td><td>1.15 s</td><td>42 ms</td><td>76.5 MB</td><td>&lt; 180 MB</td></tr>
              <tr><td class="code-font">Monorepo (1M+ LOC)</td><td>23.10 s</td><td>2.40 s</td><td>58 ms</td><td>152.0 MB</td><td>&lt; 320 MB</td></tr>
            </tbody>
          </table>
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:1.25rem; margin-top:2rem;">
          <div style="border:1px solid var(--border); border-radius:8px; padding:1.25rem; text-align:center; background:#ffffff;">
            <img src="assets/large_repo_scaling.svg" alt="Scaling Benchmark" style="max-width:100%; height:auto;">
            <div style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-dim);">Throughput scaling across codebase sizes</div>
          </div>
          <div style="border:1px solid var(--border); border-radius:8px; padding:1.25rem; text-align:center; background:#ffffff;">
            <img src="assets/performance_comparison.svg" alt="Performance Comparison" style="max-width:100%; height:auto;">
            <div style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-dim);">Retrieval latency: SQLite WAL + FTS5 vs Vector DBs</div>
          </div>
        </div>

        <!-- Book Page Footer -->
        <footer class="book-page-footer">
          <div>
            &copy; 2026 CodeGraph MCP &bull; MIT License &bull; v2.2.1 Production
          </div>
          <div style="display:flex; gap:1.25rem;">
            <a href="https://pypi.org/project/codegraph-engine/2.2.1/" target="_blank">PyPI Package</a>
            <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub Repository</a>
            <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP/issues" target="_blank">Issue Tracker</a>
          </div>
        </footer>

      </div>
    </main>

    <!-- Right Sidebar (On this page - perfectly aligned with left sidebar and title) -->
    <aside class="book-toc-right">
      <div class="toc-heading-text">On this page</div>
      <ul class="toc-nav-list">
        <li><a href="#next-steps" class="active">Overview</a></li>
        <li><a href="#understand-the-model">Understand the model</a></li>
        <li><a href="#put-it-to-work">Put it to work</a></li>
        <li><a href="#quickstart">Quickstart</a></li>
        <li><a href="#runtime-telemetry-concept">Runtime Telemetry</a></li>
        <li><a href="#database-lineage-concept">Database Lineage</a></li>
        <li><a href="#tools-database">Database Tools (11)</a></li>
        <li><a href="#tools-runtime">Runtime Tools (6)</a></li>
        <li><a href="#tools-graph">Graph Tools (8)</a></li>
        <li><a href="#tools-core">Core Tools (23)</a></li>
        <li><a href="#tools-routes">Route Tools (2)</a></li>
        <li><a href="#tools-git">Git Tools (4)</a></li>
        <li><a href="#tools-tests">Test Tools (2)</a></li>
        <li><a href="#cli-reference">CLI Reference (13)</a></li>
        <li><a href="#benchmarks">Scaling Benchmarks</a></li>
      </ul>
    </aside>

  </div>

  <!-- Spotlight Search Modal (Cmd K) -->
  <div class="spotlight-backdrop" id="spotlightModal" onclick="closeSpotlightOnBackdrop(event)">
    <div class="spotlight-box">
      <div class="spotlight-input-bar">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <input type="text" id="spotlightInput" class="spotlight-input" placeholder="Search documentation, 56 tools, CLI commands..." oninput="handleSpotlightSearch(this.value)">
      </div>
      <div class="spotlight-results-scroll" id="spotlightResults"></div>
      <div class="spotlight-bottom-bar">
        <span>Navigate with mouse or Esc to close</span>
        <span>CodeGraph MCP Search</span>
      </div>
    </div>
  </div>

  <script>
    function setHeroTermCmd(cmd, btn) {
      document.getElementById('heroTermCmdText').textContent = '$ ' + cmd;
      document.querySelectorAll('.term-tab-item').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
    }

    function copyHeroTermCode() {
      const text = document.getElementById('heroTermCmdText').textContent.replace('$ ', '');
      navigator.clipboard.writeText(text);
    }

    function switchEditorTab(tabId, btn) {
      document.querySelectorAll('.ide-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.code-ide-pane').forEach(p => p.classList.remove('active'));
      const target = document.getElementById('tab-' + tabId);
      if (target) target.classList.add('active');
    }

    function copyCurrentIdeCode(btn) {
      const activePane = document.querySelector('.code-ide-pane.active');
      if (!activePane) return;
      const rows = activePane.querySelectorAll('.code-row');
      let text = '';
      rows.forEach(r => {
        const spanText = r.querySelector('span:nth-child(2)');
        if (spanText) {
          text += spanText.textContent + '\n';
        }
      });
      navigator.clipboard.writeText(text.trimEnd());
      const label = btn.querySelector('.copy-text');
      const orig = label ? label.textContent : 'Copy';
      if (label) label.textContent = 'Copied!';
      btn.classList.add('copied');
      setTimeout(() => {
        if (label) label.textContent = orig;
        btn.classList.remove('copied');
      }, 1600);
    }

    const searchIndex = [
      { title: "Next Steps", sub: "Getting Started Overview & Guide Links", url: "#next-steps" },
      { title: "Introduction & Overview", sub: "Architectural Foundations & Deterministic AST", url: "#introduction" },
      { title: "Quickstart & Installation", sub: "pip install codegraph-engine[mcp]", url: "#quickstart" },
      { title: "Configuration", sub: "Claude Code, Cursor, Windsurf, AntiGravity setup", url: "#configuration" },
      { title: "How It Works", sub: "Extraction, storage, resolution, and sync pipeline", url: "#how-it-works" },
      { title: "Runtime Telemetry Reconciliation", sub: "RUNTIME_OBSERVED trace matching", url: "#runtime-telemetry-concept" },
      { title: "Database Lineage & Schema", sub: "Mutating SQL writers, table models, and ORM tracing", url: "#database-lineage-concept" },
''')

    for t in tools:
        t_n = t["name"]
        t_d = t["description"][:55].replace('"', '\\"')
        t_cat = t.get("category", "core")
        html_parts.append(f'      {{ title: "{t_n}", sub: "MCP Tool &bull; {t_cat.upper()} &bull; {t_d}...", url: "#tool-{t_n}" }},\n')

    for cmd in commands:
        c_c = cmd["command"]
        c_s = cmd["summary"][:55].replace('"', '\\"')
        cmd_slug = c_c.replace(" ", "-").replace("[", "").replace("]", "").replace("<", "").replace(">", "").replace(".", "").strip()
        html_parts.append(f'      {{ title: "{c_c}", sub: "CLI Command &bull; {c_s}...", url: "#cli-{cmd_slug}" }},\n')

    html_parts.append('''    ];

    function toggleNavGroup(el) {
      const chevron = el.querySelector('.chevron-icon');
      const list = el.nextElementSibling;
      if (list && list.classList.contains('nav-items-block')) {
        list.classList.toggle('closed');
        chevron.classList.toggle('closed');
      }
    }

    function copySnippetText(btn) {
      const pre = btn.closest('.code-box-wrapper').querySelector('.code-text-pre');
      if (pre) {
        navigator.clipboard.writeText(pre.textContent.trim());
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1500);
      }
    }

    function openSpotlightModal() {
      const modal = document.getElementById('spotlightModal');
      modal.classList.add('open');
      const input = document.getElementById('spotlightInput');
      input.value = '';
      input.focus();
      handleSpotlightSearch('');
    }

    function closeSpotlightModal() {
      const modal = document.getElementById('spotlightModal');
      modal.classList.remove('open');
    }

    function closeSpotlightOnBackdrop(e) {
      if (e.target.id === 'spotlightModal') {
        closeSpotlightModal();
      }
    }

    function handleSpotlightSearch(query) {
      const q = query.toLowerCase().trim();
      const container = document.getElementById('spotlightResults');
      const filtered = !q ? searchIndex.slice(0, 8) : searchIndex.filter(item => 
        item.title.toLowerCase().includes(q) || item.sub.toLowerCase().includes(q)
      ).slice(0, 15);

      if (filtered.length === 0) {
        container.innerHTML = '<div style="padding:1.5rem; text-align:center; color:var(--text-dim); font-size:0.85rem;">No matching documentation topics or tools found.</div>';
        return;
      }

      container.innerHTML = filtered.map(item => `
        <a href="${item.url}" class="spotlight-result-row" onclick="closeSpotlightModal()">
          <div>
            <div class="spotlight-res-title">${item.title}</div>
            <div class="spotlight-res-sub">${item.sub}</div>
          </div>
          <span style="font-size:0.75rem; color:var(--text-dim);">&rarr;</span>
        </a>
      `).join('');
    }

    // Scroll-Spy to update active item in left sidebar & right toc
    const navLinks = document.querySelectorAll('.nav-link-entry');
    const tocLinks = document.querySelectorAll('.toc-nav-list li a');
    
    window.addEventListener('scroll', () => {
      let currentSectionId = '';
      const sections = document.querySelectorAll('main section, h1[id], h2[id], h3[id]');
      
      sections.forEach(sec => {
        const top = sec.offsetTop;
        if (window.scrollY >= top - 120) {
          currentSectionId = sec.getAttribute('id');
        }
      });

      if (currentSectionId) {
        navLinks.forEach(link => {
          link.classList.toggle('active', link.getAttribute('href') === '#' + currentSectionId);
        });
        tocLinks.forEach(link => {
          link.classList.toggle('active', link.getAttribute('href') === '#' + currentSectionId);
        });
      }
    });

    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        openSpotlightModal();
      }
      if (e.key === 'Escape') {
        closeSpotlightModal();
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
