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
  <meta property="og:title" content="CodeGraph MCP — Deterministic Codebase Intelligence">
  <meta property="og:description" content="Compiler-grade repository intelligence for AI coding agents. 56 verified MCP tools, 13 CLI commands, SQLite WAL search, and end-to-end AST dataflow mapping.">
  <meta property="og:image" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/assets/codegraph_logo.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="https://raghurammrsd.github.io/CODE_GRAPH_MCP/">
  <meta name="twitter:title" content="CodeGraph MCP — Deterministic Codebase Intelligence">
  <meta name="twitter:description" content="Compiler-grade repository intelligence for AI coding agents. 56 verified MCP tools, 13 CLI commands.">
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

  <title>CodeGraph MCP &middot; Deterministic Repository Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --bg-surface: #0e1524;
      --bg-card: rgba(16, 24, 40, 0.7);
      --border: rgba(255, 255, 255, 0.08);
      --border-highlight: rgba(56, 189, 248, 0.3);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --cyan: #38bdf8;
      --blue: #3b82f6;
      --indigo: #6366f1;
      --emerald: #10b981;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
      --glow: radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.12) 0%, transparent 60%);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; position: relative; }

    /* Ambient Glow Canvas & Backdrop */
    .ambient-mesh {
      position: fixed; inset: 0; pointer-events: none; z-index: -1;
      background:
        radial-gradient(circle at 20% 15%, rgba(56, 189, 248, 0.09) 0%, transparent 45%),
        radial-gradient(circle at 80% 30%, rgba(99, 102, 241, 0.08) 0%, transparent 50%),
        radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.05) 0%, transparent 55%),
        linear-gradient(to bottom, #090d16 0%, #060911 100%);
    }
    .grid-mesh {
      position: fixed; inset: 0; pointer-events: none; z-index: -1; opacity: 0.12;
      background-size: 44px 44px;
      background-image:
        linear-gradient(to right, rgba(255, 255, 255, 0.06) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
    }

    /* Studio Header */
    header.studio-nav {
      position: sticky; top: 0; z-index: 100;
      background: rgba(9, 13, 22, 0.85);
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      padding: 0.85rem 2.5rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand-cluster { display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: inherit; }
    .brand-logo-img {
      width: 32px; height: 32px; border-radius: 8px; object-fit: cover;
      border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }
    .brand-title-wrap { display: flex; align-items: baseline; gap: 0.45rem; }
    .brand-title { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.03em; color: #ffffff; }
    .brand-badge {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      background: rgba(56, 189, 248, 0.12); color: var(--cyan);
      border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 9999px; padding: 0.15rem 0.5rem;
    }

    .nav-links { display: flex; align-items: center; gap: 2rem; list-style: none; }
    .nav-link {
      color: var(--text-muted); text-decoration: none; font-size: 0.9rem; font-weight: 600;
      transition: color 0.15s ease;
    }
    .nav-link:hover { color: #ffffff; }

    .nav-actions { display: flex; align-items: center; gap: 1rem; }
    .btn-github-pill {
      background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border);
      color: #ffffff; text-decoration: none; padding: 0.45rem 1rem; border-radius: 9999px;
      font-size: 0.85rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.45rem;
      transition: all 0.2s ease;
    }
    .btn-github-pill:hover { background: rgba(255, 255, 255, 0.12); border-color: rgba(255, 255, 255, 0.2); }

    /* Studio Hero Section */
    .hero-container {
      max-width: 1340px; margin: 0 auto; padding: 5.5rem 2.5rem 4.5rem;
      display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 3.5rem; align-items: center;
    }
    @media (max-width: 1024px) {
      .hero-container { grid-template-columns: 1fr; padding: 3.5rem 1.5rem; }
    }

    .hero-pill-badge {
      display: inline-flex; align-items: center; gap: 0.5rem;
      background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25);
      color: var(--cyan); font-family: var(--font-mono); font-size: 0.78rem; font-weight: 700;
      padding: 0.35rem 0.9rem; border-radius: 9999px; margin-bottom: 1.5rem;
    }
    .hero-pill-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }

    .hero-title {
      font-size: clamp(2.5rem, 4.8vw, 4.2rem); font-weight: 800; line-height: 1.1;
      letter-spacing: -0.04em; color: #ffffff; margin-bottom: 1.5rem;
    }
    .gradient-text-electric {
      background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }

    .hero-desc {
      font-size: 1.15rem; color: var(--text-muted); line-height: 1.65;
      max-width: 580px; margin-bottom: 2.25rem;
    }
    .hero-desc strong { color: #ffffff; }

    .hero-actions-row { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
    .btn-hero-primary {
      background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
      color: #ffffff; text-decoration: none; padding: 0.75rem 1.6rem; border-radius: 10px;
      font-size: 0.92rem; font-weight: 700; display: inline-flex; align-items: center; gap: 0.5rem;
      box-shadow: 0 6px 20px rgba(37, 99, 235, 0.3); transition: all 0.2s ease;
    }
    .btn-hero-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 25px rgba(37, 99, 235, 0.45); }
    .btn-hero-secondary {
      background: rgba(255, 255, 255, 0.05); color: #ffffff; text-decoration: none;
      border: 1px solid var(--border); padding: 0.75rem 1.6rem; border-radius: 10px;
      font-size: 0.92rem; font-weight: 700; transition: all 0.2s ease;
    }
    .btn-hero-secondary:hover { background: rgba(255, 255, 255, 0.1); border-color: rgba(255, 255, 255, 0.2); }

    .terminal-quick-box {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px; padding: 0.9rem 1.25rem; font-family: var(--font-mono);
      font-size: 0.88rem; display: flex; align-items: center; justify-content: space-between;
      max-width: 560px; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
    }
    .terminal-snippet { color: #e2e8f0; display: flex; align-items: center; gap: 0.65rem; }
    .terminal-prompt { color: var(--cyan); font-weight: 700; user-select: none; }
    .btn-copy-box {
      background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.1);
      color: var(--text-muted); padding: 0.35rem 0.75rem; border-radius: 6px; font-size: 0.75rem;
      font-weight: 700; cursor: pointer; transition: all 0.15s ease;
    }
    .btn-copy-box:hover { color: #fff; background: rgba(255, 255, 255, 0.16); }

    /* Interactive Graph Radar Widget (Bespoke Hero Component) */
    .hero-radar-card {
      background: var(--bg-surface);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 20px; padding: 1.75rem;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.4), 0 0 30px rgba(56, 189, 248, 0.08);
      position: relative; overflow: hidden;
    }
    .radar-header {
      display: flex; align-items: center; justify-content: space-between;
      padding-bottom: 1rem; border-bottom: 1px solid var(--border); margin-bottom: 1.25rem;
      font-size: 0.85rem; font-weight: 700; color: var(--text-muted);
    }
    .radar-pill-live {
      display: inline-flex; align-items: center; gap: 0.45rem;
      background: rgba(16, 185, 129, 0.15); color: #34d399;
      padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.72rem; font-family: var(--font-mono);
    }
    .radar-pill-live-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }

    .radar-pipeline-list { display: flex; flex-direction: column; gap: 0.85rem; }
    .pipeline-item {
      background: rgba(16, 24, 40, 0.6); border: 1px solid var(--border);
      border-radius: 12px; padding: 0.85rem 1rem; display: flex; align-items: center;
      justify-content: space-between; transition: all 0.2s ease;
    }
    .pipeline-item:hover { border-color: var(--border-highlight); transform: translateX(3px); }
    .pipeline-item-left { display: flex; align-items: center; gap: 0.85rem; }
    .pipeline-badge {
      font-family: var(--font-mono); font-size: 0.7rem; font-weight: 800;
      padding: 0.25rem 0.55rem; border-radius: 6px;
    }
    .badge-ast { background: rgba(56, 189, 248, 0.15); color: var(--cyan); border: 1px solid rgba(56, 189, 248, 0.3); }
    .badge-route { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
    .badge-db { background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.3); }
    .badge-runtime { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }

    .pipeline-label { font-size: 0.88rem; font-weight: 600; color: #f1f5f9; }
    .pipeline-sublabel { font-size: 0.76rem; color: var(--text-dim); font-family: var(--font-mono); }
    .pipeline-status-tag {
      font-size: 0.72rem; font-family: var(--font-mono); font-weight: 700;
      color: #94a3b8; background: rgba(255, 255, 255, 0.05); padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    .radar-stats-footer {
      margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid var(--border);
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; text-align: center;
    }
    .radar-stat-num { font-size: 1.15rem; font-weight: 800; font-family: var(--font-mono); color: #ffffff; }
    .radar-stat-desc { font-size: 0.75rem; color: var(--text-dim); }

    /* 4-Stat Metric Banner */
    .metric-strip-container {
      max-width: 1340px; margin: 0 auto; padding: 0 2.5rem 4rem;
    }
    .metric-grid-strip {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 18px; padding: 2rem 2.5rem; display: grid;
      grid-template-columns: repeat(4, 1fr); gap: 2.5rem;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    }
    @media (max-width: 900px) {
      .metric-grid-strip { grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }
    }
    @media (max-width: 560px) {
      .metric-grid-strip { grid-template-columns: 1fr; }
    }
    .metric-box-num {
      font-size: 2.4rem; font-weight: 800; font-family: var(--font-mono);
      letter-spacing: -0.03em; color: #ffffff; line-height: 1; margin-bottom: 0.4rem;
    }
    .metric-box-num span.accent-cyan { color: var(--cyan); }
    .metric-box-num span.accent-emerald { color: var(--emerald); }
    .metric-box-title { font-size: 0.95rem; font-weight: 700; color: #f1f5f9; margin-bottom: 0.2rem; }
    .metric-box-desc { font-size: 0.8rem; color: var(--text-dim); }

    /* Studio Content Sections */
    .section-wrap {
      max-width: 1340px; margin: 0 auto; padding: 5rem 2.5rem;
      scroll-margin-top: 5rem;
    }
    .section-wrap.alt {
      background: rgba(14, 21, 36, 0.5); max-width: 100%;
      border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
    }
    .section-inner { max-width: 1340px; margin: 0 auto; }

    .section-header-center { text-align: center; max-width: 820px; margin: 0 auto 3.5rem; }
    .section-kicker {
      font-family: var(--font-mono); font-size: 0.78rem; font-weight: 800;
      text-transform: uppercase; letter-spacing: 0.1em; color: var(--cyan);
      margin-bottom: 0.6rem; display: inline-block;
    }
    .section-headline {
      font-size: clamp(2.1rem, 3.8vw, 3rem); font-weight: 800; letter-spacing: -0.03em;
      color: #ffffff; margin-bottom: 0.85rem;
    }
    .section-lead { font-size: 1.08rem; color: var(--text-muted); line-height: 1.65; }

    /* Feature Pillars Grid */
    .grid-pillars { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.75rem; }
    .pillar-card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 18px; padding: 2.25rem; transition: all 0.25s ease;
      position: relative; overflow: hidden;
    }
    .pillar-card:hover {
      border-color: var(--border-highlight); transform: translateY(-4px);
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3), 0 0 25px rgba(56, 189, 248, 0.1);
    }
    .pillar-tag {
      font-family: var(--font-mono); font-size: 0.72rem; font-weight: 800;
      text-transform: uppercase; padding: 0.25rem 0.6rem; border-radius: 6px;
      display: inline-block; margin-bottom: 1.25rem;
      background: rgba(56, 189, 248, 0.12); color: var(--cyan); border: 1px solid rgba(56, 189, 248, 0.25);
    }
    .pillar-card h3 { font-size: 1.35rem; font-weight: 800; color: #ffffff; margin-bottom: 0.65rem; }
    .pillar-card p { font-size: 0.95rem; color: var(--text-muted); line-height: 1.65; margin-bottom: 1.5rem; }
    .pillar-foot {
      padding-top: 1rem; border-top: 1px solid var(--border);
      display: flex; align-items: baseline; justify-content: space-between;
      font-size: 0.85rem; font-weight: 600; color: var(--text-dim);
    }
    .pillar-foot-val { font-family: var(--font-mono); font-weight: 700; color: #ffffff; }

    /* Interactive 56 Tools Directory */
    .tool-explorer-bar {
      display: flex; gap: 1rem; align-items: center; justify-content: space-between;
      margin-bottom: 2rem; flex-wrap: wrap; background: var(--bg-surface);
      padding: 1.1rem 1.4rem; border-radius: 16px; border: 1px solid var(--border);
    }
    .tool-search-input-wrap { flex: 1; min-width: 280px; position: relative; }
    .tool-search-input {
      width: 100%; padding: 0.8rem 1rem 0.8rem 2.6rem; border-radius: 10px;
      background: #060911; border: 1px solid var(--border); font-size: 0.92rem;
      font-family: var(--font-sans); color: #ffffff; outline: none; transition: border-color 0.15s ease;
    }
    .tool-search-input:focus { border-color: var(--cyan); }
    .search-icon {
      position: absolute; left: 0.9rem; top: 50%; transform: translateY(-50%);
      width: 16px; height: 16px; color: var(--text-dim); pointer-events: none;
    }
    .filter-pills-row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .filter-btn {
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
      color: var(--text-muted); padding: 0.5rem 1rem; border-radius: 8px;
      font-size: 0.82rem; font-weight: 700; cursor: pointer; transition: all 0.15s ease;
    }
    .filter-btn.active, .filter-btn:hover {
      background: var(--cyan); color: #090d16; border-color: var(--cyan); font-weight: 800;
    }

    .tools-grid-layout { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.5rem; }
    .tool-studio-card {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 16px;
      padding: 1.65rem; transition: all 0.2s ease; display: flex; flex-direction: column; justify-content: space-between;
    }
    .tool-studio-card:hover { border-color: var(--border-highlight); transform: translateY(-2px); }
    .tool-studio-header {
      display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;
    }
    .tool-func-title { font-family: var(--font-mono); font-size: 1.08rem; font-weight: 700; color: var(--cyan); }
    .tool-prof-badge {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.2rem 0.55rem; border-radius: 5px; background: rgba(255, 255, 255, 0.06); color: var(--text-muted);
    }
    .tool-prof-badge.core { background: rgba(56, 189, 248, 0.15); color: var(--cyan); }
    .tool-prof-badge.trace { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
    .tool-prof-badge.database { background: rgba(249, 115, 22, 0.15); color: #fb923c; }
    .tool-prof-badge.runtime { background: rgba(16, 185, 129, 0.15); color: #34d399; }

    .tool-summary-text { font-size: 0.92rem; color: var(--text-muted); line-height: 1.55; margin-bottom: 0.85rem; }
    .tool-solve-callout {
      background: rgba(6, 9, 17, 0.7); border-left: 3px solid var(--cyan); padding: 0.55rem 0.8rem;
      border-radius: 0 8px 8px 0; font-size: 0.82rem; color: #cbd5e1; margin-bottom: 1.1rem;
    }
    .tool-solve-callout strong { color: #ffffff; }

    .btn-inspect-spec {
      background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.5rem 0.85rem; border-radius: 8px; font-size: 0.82rem; font-weight: 700;
      cursor: pointer; width: 100%; text-align: center; transition: all 0.15s ease;
    }
    .btn-inspect-spec:hover { background: rgba(255, 255, 255, 0.08); color: #ffffff; }
    .spec-drawer { display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
    .spec-drawer.open { display: block; }
    .drawer-sec-title { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-dim); margin-bottom: 0.35rem; }
    .code-box-dark {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;
      padding: 0.85rem; font-family: var(--font-mono); font-size: 0.82rem; color: #e2e8f0;
      overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin-bottom: 0.85rem;
    }

    /* CLI Studio Grid */
    .cli-studio-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.65rem; }
    .cli-command-card {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 16px;
      padding: 1.85rem; transition: all 0.2s ease;
    }
    .cli-command-card:hover { border-color: rgba(255, 255, 255, 0.2); }
    .cli-title-row { font-family: var(--font-mono); font-size: 1.18rem; font-weight: 800; color: #ffffff; margin-bottom: 0.5rem; }
    .cli-solve-pill {
      background: rgba(56, 189, 248, 0.1); color: var(--cyan); padding: 0.45rem 0.8rem;
      border-radius: 8px; font-size: 0.82rem; font-weight: 600; margin-bottom: 1rem;
    }
    .cli-code-strip {
      background: #060911; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;
      padding: 0.75rem 1rem; font-family: var(--font-mono); font-size: 0.85rem; margin-bottom: 1rem;
      display: flex; align-items: center; justify-content: space-between;
    }

    .studio-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; margin: 1rem 0; }
    .studio-table th {
      text-align: left; padding: 0.6rem 0.75rem; background: rgba(255, 255, 255, 0.03);
      color: var(--text-dim); font-weight: 700; border-bottom: 1px solid var(--border);
    }
    .studio-table td {
      padding: 0.7rem 0.75rem; border-bottom: 1px solid var(--border); color: var(--text-muted);
    }
    .studio-table td.strong { font-weight: 700; color: #ffffff; }

    /* Visual Architecture Display Frames */
    .diagram-showcase-frame {
      background: var(--bg-surface); border: 1px solid var(--border); border-radius: 18px;
      padding: 2.25rem; margin: 2rem 0; text-align: center; box-shadow: 0 15px 40px rgba(0, 0, 0, 0.4);
    }
    .diagram-showcase-frame img { max-width: 100%; height: auto; border-radius: 8px; }
    .diagram-caption-text { margin-top: 1rem; font-size: 0.88rem; color: var(--text-dim); }

    /* Studio Footer */
    footer.studio-footer {
      border-top: 1px solid var(--border); background: #060911;
      padding: 4.5rem 2.5rem 3.5rem; margin-top: 5rem;
    }
    .footer-content-wrap {
      max-width: 1340px; margin: 0 auto;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 2rem;
    }
    .footer-left-copy { font-size: 0.88rem; color: var(--text-dim); }
    .footer-nav-list { display: flex; gap: 1.75rem; list-style: none; }
    .footer-nav-list a { color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 600; }
    .footer-nav-list a:hover { color: #ffffff; }
  </style>
</head>
<body>

  <!-- Ambient Backdrop -->
  <div class="ambient-mesh"></div>
  <div class="grid-mesh"></div>

  <!-- Studio Header -->
  <header class="studio-nav">
    <a href="#" class="brand-cluster">
      <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" class="brand-logo-img">
      <div class="brand-title-wrap">
        <span class="brand-title">CodeGraph MCP</span>
        <span class="brand-badge">v2.2.1</span>
      </div>
    </a>
    <nav>
      <ul class="nav-links">
        <li><a href="#features" class="nav-link">Architecture</a></li>
        <li><a href="#tools" class="nav-link">56 MCP Tools</a></li>
        <li><a href="#cli" class="nav-link">CLI Commands</a></li>
        <li><a href="#benchmarks" class="nav-link">Benchmarks</a></li>
        <li><a href="#integrations" class="nav-link">Integrations</a></li>
      </ul>
    </nav>
    <div class="nav-actions">
      <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" class="btn-github-pill" target="_blank">
        <svg height="15" width="15" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
        GitHub Repository
      </a>
    </div>
  </header>

  <!-- Hero Section -->
  <section class="hero-container">
    <div class="hero-left">
      <div class="hero-pill-badge">
        <span class="hero-pill-dot"></span>
        v2.2.1 Production Release &middot; 861 Automated Tests Passing
      </div>
      <h1 class="hero-title">
        Deterministic Codebase Intelligence for <span class="gradient-text-electric">Autonomous AI Agents.</span>
      </h1>
      <p class="hero-desc">
        Eliminate hallucinations, token inflation, and blind grepping. CodeGraph MCP equips Claude Code, Cursor, Antigravity, and Codex with compiler-grade AST call graphs, database lineages, and runtime verification.
      </p>

      <div class="hero-actions-row">
        <a href="#tools" class="btn-hero-primary">Explore 56 MCP Tools &rarr;</a>
        <a href="#cli" class="btn-hero-secondary">CLI Reference</a>
      </div>

      <div class="terminal-quick-box">
        <div class="terminal-snippet">
          <span class="terminal-prompt">$</span>
          <span>pip install codegraph-engine &amp;&amp; codegraph mcp serve</span>
        </div>
        <button class="btn-copy-box" onclick="navigator.clipboard.writeText('pip install codegraph-engine && codegraph mcp serve'); this.textContent = 'Copied!'; setTimeout(() => this.textContent = 'Copy', 1500);">
          Copy
        </button>
      </div>
    </div>

    <!-- Right Hero: Live Multi-Layer Verification Radar -->
    <div class="hero-radar-card">
      <div class="radar-header">
        <span>Active Telemetry Radar</span>
        <div class="radar-pill-live">
          <span class="radar-pill-live-dot"></span>
          <span>AST ENGINE ACTIVE</span>
        </div>
      </div>

      <div class="radar-pipeline-list">
        <div class="pipeline-item">
          <div class="pipeline-item-left">
            <span class="pipeline-badge badge-ast">AST_VERIFIED</span>
            <div>
              <div class="pipeline-label">Caller &amp; Callee Call Graph</div>
              <div class="pipeline-sublabel">AuthService.login &rarr; hash_password</div>
            </div>
          </div>
          <span class="pipeline-status-tag">0.08ms</span>
        </div>

        <div class="pipeline-item">
          <div class="pipeline-item-left">
            <span class="pipeline-badge badge-route">FRAMEWORK</span>
            <div>
              <div class="pipeline-label">HTTP Route to Handler Mapping</div>
              <div class="pipeline-sublabel">POST /api/v1/auth &rarr; login_view</div>
            </div>
          </div>
          <span class="pipeline-status-tag">FASTAPI</span>
        </div>

        <div class="pipeline-item">
          <div class="pipeline-item-left">
            <span class="pipeline-badge badge-db">DATAFLOW</span>
            <div>
              <div class="pipeline-label">Database Model &amp; Writer Lineage</div>
              <div class="pipeline-sublabel">UPDATE users SET last_login = now()</div>
            </div>
          </div>
          <span class="pipeline-status-tag">SQLITE WAL</span>
        </div>

        <div class="pipeline-item">
          <div class="pipeline-item-left">
            <span class="pipeline-badge badge-runtime">RUNTIME</span>
            <div>
              <div class="pipeline-label">Trace Telemetry Reconciliation</div>
              <div class="pipeline-sublabel">Live OpenTelemetry Spans Ingested</div>
            </div>
          </div>
          <span class="pipeline-status-tag">100% PROVEN</span>
        </div>
      </div>

      <div class="radar-stats-footer">
        <div>
          <div class="radar-stat-num">56</div>
          <div class="radar-stat-desc">Deterministic Tools</div>
        </div>
        <div>
          <div class="radar-stat-num">0.00%</div>
          <div class="radar-stat-desc">Unsupported Claims</div>
        </div>
        <div>
          <div class="radar-stat-num">&lt; 45ms</div>
          <div class="radar-stat-desc">P95 Retrieval</div>
        </div>
      </div>
    </div>
  </section>

  <!-- Metric Banner -->
  <div class="metric-strip-container">
    <div class="metric-grid-strip">
      <div>
        <div class="metric-box-num"><span class="accent-cyan">56</span></div>
        <div class="metric-box-title">Model Context Protocol Tools</div>
        <div class="metric-box-desc">Structured across 5 specialized profiles</div>
      </div>
      <div>
        <div class="metric-box-num"><span class="accent-emerald">861</span></div>
        <div class="metric-box-title">Regression Tests Passing</div>
        <div class="metric-box-desc">100% static &amp; dynamic test suite pass</div>
      </div>
      <div>
        <div class="metric-box-num">0.00%</div>
        <div class="metric-box-title">Hallucinated Claims</div>
        <div class="metric-box-desc">Deterministic facts backed by AST evidence</div>
      </div>
      <div>
        <div class="metric-box-num">94.2%</div>
        <div class="metric-box-title">Context Noise Reduction</div>
        <div class="metric-box-desc">Cuts 50k token dumps into sub-600 token packets</div>
      </div>
    </div>
  </div>

  <!-- Section: Architecture & Verification Hierarchy -->
  <section id="features" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-header-center">
        <span class="section-kicker">Epistemic Foundation</span>
        <h2 class="section-headline">Why CodeGraph Outperforms Blind Grep</h2>
        <p class="section-lead">
          AI agents fail on complex repositories because text search treats code as raw strings. CodeGraph analyzes code as a compiler does, establishing mathematical relationship certainty.
        </p>
      </div>

      <div class="grid-pillars">
        <div class="pillar-card">
          <span class="pillar-tag">Syntactic Ground Truth</span>
          <h3>AST-Verified Call Graph</h3>
          <p>Maps every class definition, inheritance tree, and explicit caller-callee relationship with zero LLM generation overhead or hallucination.</p>
          <div class="pillar-foot">
            <span>Accuracy Guarantee</span>
            <span class="pillar-foot-val">100% Deterministic</span>
          </div>
        </div>

        <div class="pillar-card">
          <span class="pillar-tag">Framework Discovery</span>
          <h3>Router &amp; Mount Introspection</h3>
          <p>Extracts FastAPI, Flask, and Django route mounts, sub-routers, middleware stacks, and dependency injection providers back to handler logic.</p>
          <div class="pillar-foot">
            <span>Route Discovery</span>
            <span class="pillar-foot-val">Sub-millisecond</span>
          </div>
        </div>

        <div class="pillar-card">
          <span class="pillar-tag">Dataflow Lineage</span>
          <h3>Database Schema &amp; Writers</h3>
          <p>Discovers ORM models, raw SQL queries, schema migrations, and column mutations so agents never guess table relationships.</p>
          <div class="pillar-foot">
            <span>Storage Engine</span>
            <span class="pillar-foot-val">SQLite WAL + FTS5</span>
          </div>
        </div>
      </div>

      <div class="diagram-showcase-frame">
        <img src="assets/v22_concurrency_runtime_pipeline.svg" alt="CodeGraph Architecture Pipeline">
        <div class="diagram-caption-text">Figure 1: Concurrency and runtime telemetry reconciliation pipeline in CodeGraph MCP v2.2.1</div>
      </div>

      <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:16px; overflow-x:auto; margin-top:2rem;">
        <table class="studio-table" style="margin:0;">
          <thead>
            <tr>
              <th>Evidence Level</th>
              <th>Verification Engine</th>
              <th>Operational Semantic</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="strong" style="color:var(--cyan);">AST_VERIFIED</td>
              <td>Python AST / Tree-sitter</td>
              <td>Guaranteed syntax fact. Direct call, definition, import, or class hierarchy.</td>
            </tr>
            <tr>
              <td class="strong" style="color:#818cf8;">STATIC_VERIFIED</td>
              <td>Symbol Resolution Engine</td>
              <td>Statically proven caller-callee chains without dynamic runtime guessing.</td>
            </tr>
            <tr>
              <td class="strong" style="color:#c084fc;">FRAMEWORK_VERIFIED</td>
              <td>Router / DI Introspector</td>
              <td>HTTP routes, middleware chains, and dependency injection providers.</td>
            </tr>
            <tr>
              <td class="strong" style="color:#fb923c;">DATAFLOW_VERIFIED</td>
              <td>SQL / ORM Parser</td>
              <td>Database table reads, mutations, ORM column mappings, and migration lineages.</td>
            </tr>
            <tr>
              <td class="strong" style="color:#34d399;">RUNTIME_OBSERVED</td>
              <td>Execution Telemetry</td>
              <td>Live execution traces observed during live test suite or server runs.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- Section: Interactive 56 MCP Tools Catalog -->
  <section id="tools" class="section-wrap">
    <div class="section-header-center">
      <span class="section-kicker">Model Context Protocol</span>
      <h2 class="section-headline">Interactive Catalog of 56 MCP Tools</h2>
      <p class="section-lead">
        Search and inspect every tool exposed by CodeGraph MCP Engine. Filter by agent profile or search by keyword, parameter, or return schema.
      </p>
    </div>

    <div class="tool-explorer-bar">
      <div class="tool-search-input-wrap">
        <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <input type="text" id="toolInputSearch" class="tool-search-input" placeholder="Search 56 tools (e.g., callers, routes, tables, trace, impact)..." oninput="filterStudioTools()">
      </div>
      <div class="filter-pills-row">
        <button class="filter-btn active" onclick="setStudioCategory('all', this)">All (56)</button>
        <button class="filter-btn" onclick="setStudioCategory('core', this)">Core Profile</button>
        <button class="filter-btn" onclick="setStudioCategory('trace', this)">Trace &amp; Flow</button>
        <button class="filter-btn" onclick="setStudioCategory('database', this)">Database</button>
        <button class="filter-btn" onclick="setStudioCategory('runtime', this)">Runtime</button>
      </div>
    </div>

    <div class="tools-grid-layout" id="toolsGridLayout">
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
      <div class="tool-studio-card" data-name="{t_name.lower()}" data-desc="{t_desc.lower()}" data-prob="{t_problem.lower()}" data-prof="{t_profile.lower()}">
        <div>
          <div class="tool-studio-header">
            <span class="tool-func-title">{t_name}</span>
            <span class="tool-prof-badge {t_profile.lower()}">{t_profile.upper()}</span>
          </div>
          <p class="tool-summary-text">{t_desc}</p>
          <div class="tool-solve-callout">
            <strong>Problem Resolved:</strong> {t_problem}
          </div>
        </div>
        <div>
          <button class="btn-inspect-spec" onclick="toggleStudioDrawer(this)">Inspect Schema &amp; Invocation &darr;</button>
          <div class="spec-drawer">
            <div class="drawer-sec-title">Input Parameters Schema</div>
            <pre class="code-box-dark">{t_inputs}</pre>
            <div class="drawer-sec-title">Return Schema Structure</div>
            <pre class="code-box-dark">{t_returns}</pre>
            <div class="drawer-sec-title">Client JSON-RPC Invocation</div>
            <pre class="code-box-dark">{t_inv}</pre>
          </div>
        </div>
      </div>
''')

    html_parts.append('''
    </div>
  </section>

  <!-- Section: 13 Production CLI Commands -->
  <section id="cli" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-header-center">
        <span class="section-kicker">Developer Command Center</span>
        <h2 class="section-headline">13 Production CLI Commands</h2>
        <p class="section-lead">
          Operate CodeGraph from your terminal, GitHub Actions, or CI/CD pipelines. Every command resolves concrete engineering bottlenecks.
        </p>
      </div>

      <div class="cli-studio-grid">
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
            flags_rows += f'<tr><td class="strong" style="font-family:var(--font-mono); color:var(--cyan);">{f_name}</td><td>{f_desc}</td></tr>'

        html_parts.append(f'''
        <div class="cli-command-card">
          <div class="cli-title-row">codegraph {c_name}</div>
          <div class="cli-solve-pill">Resolves: {c_problem}</div>
          <p style="font-size:0.92rem; color:var(--text-muted); margin-bottom:1rem;">{c_desc}</p>

          <div class="cli-code-strip">
            <span>{c_example}</span>
            <button class="btn-copy-box" onclick="navigator.clipboard.writeText('{c_example}'); this.textContent='Copied!'; setTimeout(()=>this.textContent='Copy', 1500);">Copy</button>
          </div>

          <table class="studio-table">
            <thead><tr><th>Flag / Option</th><th>Description</th></tr></thead>
            <tbody>{flags_rows}</tbody>
          </table>

          <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-dim); margin-top:1rem; margin-bottom:0.35rem;">Verifiable Terminal Output</div>
          <pre class="code-box-dark">{c_output}</pre>
        </div>
''')

    html_parts.append('''
      </div>
    </div>
  </section>

  <!-- Section: Benchmarks & Large-Scale Scaling -->
  <section id="benchmarks" class="section-wrap">
    <div class="section-header-center">
      <span class="section-kicker">Empirical Verification</span>
      <h2 class="section-headline">Large-Scale Scaling Benchmarks</h2>
      <p class="section-lead">
        Measured performance across repositories from 10,000 to over 1,000,000 lines of code.
      </p>
    </div>

    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(480px, 1fr)); gap:2rem; margin-bottom:2.5rem;">
      <div class="diagram-showcase-frame" style="margin:0;">
        <img src="assets/large_repo_scaling.svg" alt="Large Repository Scaling Benchmark">
        <div class="diagram-caption-text">Figure 2: Memory footprint and throughput scaling curves</div>
      </div>
      <div class="diagram-showcase-frame" style="margin:0;">
        <img src="assets/performance_comparison.svg" alt="Performance Comparison Benchmark">
        <div class="diagram-caption-text">Figure 3: Retrieval latency vs embedding vector databases</div>
      </div>
    </div>

    <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:16px; overflow-x:auto;">
      <table class="studio-table" style="margin:0;">
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
  </section>

  <!-- Section: Client Integrations -->
  <section id="integrations" class="section-wrap alt">
    <div class="section-inner">
      <div class="section-header-center">
        <span class="section-kicker">Ecosystem Connectivity</span>
        <h2 class="section-headline">Integrate in 30 Seconds</h2>
        <p class="section-lead">Drop-in configuration for leading AI agent environments and editors.</p>
      </div>

      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:1.75rem;">
        <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:16px; padding:1.75rem;">
          <div style="font-size:1.15rem; font-weight:800; color:#fff; margin-bottom:0.75rem;">Cursor (.cursor/mcp.json)</div>
          <pre class="code-box-dark">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}</pre>
        </div>

        <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:16px; padding:1.75rem;">
          <div style="font-size:1.15rem; font-weight:800; color:#fff; margin-bottom:0.75rem;">Claude Desktop</div>
          <pre class="code-box-dark">{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--profile", "full"]
    }
  }
}</pre>
        </div>

        <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:16px; padding:1.75rem;">
          <div style="font-size:1.15rem; font-weight:800; color:#fff; margin-bottom:0.75rem;">Antigravity / Zed / Windsurf</div>
          <pre class="code-box-dark">codegraph mcp serve --db .codegraph/index.db</pre>
        </div>
      </div>
    </div>
  </section>

  <!-- Studio Footer -->
  <footer class="studio-footer">
    <div class="footer-content-wrap">
      <div class="brand-cluster">
        <img src="assets/codegraph_logo.jpg" alt="CodeGraph Logo" class="brand-logo-img">
        <span class="brand-title">CodeGraph MCP</span>
      </div>
      <div class="footer-left-copy">
        &copy; 2026 CodeGraph MCP Engine &bull; Released under MIT License &bull; v2.2.1 Production
      </div>
      <ul class="footer-nav-list">
        <li><a href="https://pypi.org/project/codegraph-engine/2.2.1/" target="_blank">PyPI Package</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP" target="_blank">GitHub Repository</a></li>
        <li><a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP/issues" target="_blank">Issue Tracker</a></li>
      </ul>
    </div>
  </footer>

  <!-- Interactive JavaScript Engine -->
  <script>
    let currentStudioCategory = 'all';

    function filterStudioTools() {
      const q = document.getElementById('toolInputSearch').value.toLowerCase().trim();
      const cards = document.querySelectorAll('.tool-studio-card');

      cards.forEach(card => {
        const name = card.getAttribute('data-name') || '';
        const desc = card.getAttribute('data-desc') || '';
        const prob = card.getAttribute('data-prob') || '';
        const prof = card.getAttribute('data-prof') || '';

        const matchesQuery = !q || name.includes(q) || desc.includes(q) || prob.includes(q);
        const matchesCategory = currentStudioCategory === 'all' || prof === currentStudioCategory;

        if (matchesQuery && matchesCategory) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    }

    function setStudioCategory(cat, btn) {
      currentStudioCategory = cat;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterStudioTools();
    }

    function toggleStudioDrawer(btn) {
      const drawer = btn.nextElementSibling;
      if (drawer.classList.contains('open')) {
        drawer.classList.remove('open');
        btn.innerHTML = 'Inspect Schema &amp; Invocation &darr;';
      } else {
        drawer.classList.add('open');
        btn.innerHTML = 'Hide Schema &amp; Invocation &uarr;';
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
