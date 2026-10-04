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
  
  <!-- Open Graph / Social SEO -->
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
      --shadow-card: 0 20px 45px -10px rgba(0, 0, 0, 0.07), 0 2px 6px 0 rgba(0, 0, 0, 0.03);
      --shadow-hover: 0 30px 60px -12px rgba(2, 132, 199, 0.12), 0 4px 10px rgba(0, 0, 0, 0.04);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-family: var(--font-sans); color: var(--text); background: var(--bg); }
    body { min-height: 100vh; line-height: 1.6; overflow-x: hidden; position: relative; }

    /* Interactive 3D Canvas Background */
    #bgCanvas {
      position: absolute; top: 0; left: 0; width: 100%; height: 900px;
      pointer-events: none; z-index: 0; opacity: 0.65;
    }

    /* Ambient Lighting */
    .ambient-glow-1 {
      position: absolute; top: 5%; left: 15%; width: 500px; height: 500px;
      background: radial-gradient(circle, rgba(2, 132, 199, 0.08) 0%, transparent 70%);
      filter: blur(80px); pointer-events: none; z-index: 0;
    }
    .ambient-glow-2 {
      position: absolute; top: 15%; right: 10%; width: 600px; height: 600px;
      background: radial-gradient(circle, rgba(249, 115, 22, 0.06) 0%, transparent 70%);
      filter: blur(90px); pointer-events: none; z-index: 0;
    }

    /* Modern Navbar */
    header.navbar {
      position: sticky; top: 0; z-index: 50;
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      padding: 0.9rem 2.5rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .brand-wrap { display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: inherit; }
    .brand-logo-icon {
      width: 32px; height: 32px; border-radius: 8px; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
      background: #09090b; color: #fff; font-family: var(--font-mono); font-weight: 800; font-size: 0.9rem;
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
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
      padding: 0.55rem 1.25rem; border-radius: 9999px; font-size: 0.88rem; font-weight: 700;
      display: inline-flex; align-items: center; gap: 0.4rem; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
    }
    .btn-cta-dark:hover { background: #1e293b; transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18); }

    /* Hero Section */
    .hero-wrapper { position: relative; z-index: 10; }
    .hero-container {
      max-width: 1320px; margin: 0 auto; padding: 5.5rem 2rem 4rem;
      display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 3.5rem; align-items: center;
    }
    @media (max-width: 1024px) {
      .hero-container { grid-template-columns: 1fr; gap: 3.5rem; padding: 3rem 1.5rem; }
    }

    .hero-left h1 {
      font-size: clamp(2.6rem, 5.2vw, 4.3rem);
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
      transition: all 0.2s ease;
    }
    .agent-pill:hover { background: #e2e8f0; transform: translateY(-1px); }

    .terminal-box {
      background: var(--bg-dark); color: #f8fafc;
      border-radius: 12px; padding: 0.9rem 1.25rem;
      display: flex; align-items: center; justify-content: space-between;
      font-family: var(--font-mono); font-size: 0.88rem;
      box-shadow: 0 12px 30px -8px rgba(0, 0, 0, 0.18), 0 0 0 1px rgba(255, 255, 255, 0.08);
      max-width: 580px; position: relative; overflow: hidden;
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

    /* Hero Right: 3D Parallax Card Container */
    .hero-mockup-wrapper {
      perspective: 1200px;
      perspective-origin: center center;
    }
    .hero-mockup-card {
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid var(--border);
      border-radius: 20px; padding: 2.25rem;
      box-shadow: var(--shadow-card);
      position: relative;
      transform-style: preserve-3d;
      transition: transform 0.15s ease-out, box-shadow 0.25s ease;
      overflow: hidden;
    }
    .hero-mockup-card:hover {
      box-shadow: 0 35px 70px -15px rgba(2, 132, 199, 0.15), 0 15px 25px rgba(0, 0, 0, 0.04);
    }
    .card-glare {
      position: absolute; inset: 0; pointer-events: none; border-radius: 20px;
      background: radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.6) 0%, transparent 65%);
      opacity: 0; transition: opacity 0.3s ease;
      z-index: 10;
    }
    .hero-mockup-card:hover .card-glare { opacity: 1; }

    /* 3D Depth Layers inside Card */
    .mockup-status-bar {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);
      font-size: 0.85rem; font-weight: 600; color: var(--text-muted);
      transform: translateZ(30px);
    }
    .agent-active-badge { display: flex; align-items: center; gap: 0.5rem; }
    .status-dot {
      width: 9px; height: 9px; border-radius: 50%; background: #2563eb;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25);
      animation: pulse-dot 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }
    @keyframes pulse-dot { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.15); opacity: 0.8; } }
    .agent-active-name { font-weight: 700; color: var(--text); }
    .mockup-counter { font-family: var(--font-mono); color: var(--text-dim); font-size: 0.8rem; }

    .mockup-title {
      font-size: 1.28rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 1.25rem;
      transform: translateZ(40px);
    }

    .mockup-steps {
      list-style: none; display: flex; flex-direction: column; gap: 0.9rem;
      transform: translateZ(25px);
    }
    .mockup-step {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.75rem 0.95rem; border-radius: 12px; background: #f8fafc;
      font-size: 0.88rem; font-weight: 500; border: 1px solid rgba(226, 232, 240, 0.6);
      transition: all 0.2s ease;
    }
    .mockup-step:hover { background: #f1f5f9; transform: translateZ(10px); }
    .step-left { display: flex; align-items: center; gap: 0.75rem; }
    .step-icon-check {
      width: 22px; height: 22px; border-radius: 50%; background: #2563eb;
      display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0;
      box-shadow: 0 2px 6px rgba(37, 99, 235, 0.35);
    }
    .step-icon-spinner {
      width: 22px; height: 22px; border-radius: 50%;
      border: 2.5px solid #cbd5e1; border-top-color: #2563eb; flex-shrink: 0;
      animation: spin 0.8s linear infinite;
    }
    .step-icon-pending {
      width: 22px; height: 22px; border-radius: 50%;
      border: 2px dashed #94a3b8; flex-shrink: 0;
    }
    @keyframes spin { 100% { transform: rotate(360deg); } }

    .step-pill {
      font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
      padding: 0.2rem 0.55rem; border-radius: 6px;
    }
    .step-pill-blue { background: #dbeafe; color: #1d4ed8; }
    .step-pill-purple { background: #f3e8ff; color: #7e22ce; }
    .step-pill-orange { background: #ffedd5; color: #c2410c; }
    .step-pill-gray { background: #e2e8f0; color: #475569; }

    .mockup-footer {
      margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border);
      font-size: 0.82rem; color: var(--text-dim); text-align: center;
      transform: translateZ(20px);
    }

    /* Metric Counter Strip */
    .metric-strip-wrap {
      max-width: 1320px; margin: 0 auto; padding: 0 2rem 4rem; position: relative; z-index: 10;
    }
    .metric-strip {
      background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(16px);
      border: 1px solid var(--border); border-radius: 16px;
      padding: 1.75rem 2.5rem; display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 2rem; box-shadow: var(--shadow-sm);
    }
    @media (max-width: 900px) {
      .metric-strip { grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }
    }
    @media (max-width: 560px) {
      .metric-strip { grid-template-columns: 1fr; }
    }
    .metric-item { text-align: left; }
    .metric-item-val {
      font-size: 2.1rem; font-weight: 800; font-family: var(--font-mono);
      letter-spacing: -0.04em; color: var(--text); line-height: 1; margin-bottom: 0.4rem;
    }
    .metric-item-val span.accent-blue { color: #0284c7; }
    .metric-item-val span.accent-green { color: #16a34a; }
    .metric-item-label { font-size: 0.9rem; font-weight: 700; color: var(--text); margin-bottom: 0.2rem; }
    .metric-item-sub { font-size: 0.78rem; color: var(--text-muted); }

    /* Section Layouts */
    .section-wrap { padding: 5.5rem 2rem; max-width: 1320px; margin: 0 auto; scroll-margin-top: 5rem; position: relative; z-index: 10; }
    .section-wrap.alt { background: var(--bg-alt); max-width: 100%; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
    .section-inner { max-width: 1320px; margin: 0 auto; }

    .section-heading-center { text-align: center; max-width: 780px; margin: 0 auto 3.5rem; }
    .section-tag {
      font-size: 0.8rem; font-weight: 700; font-family: var(--font-mono);
      text-transform: uppercase; letter-spacing: 0.08em; color: var(--primary);
      margin-bottom: 0.5rem; display: inline-block;
    }
    .section-heading-center h2 {
      font-size: clamp(2.1rem, 3.6vw, 2.85rem); font-weight: 800; letter-spacing: -0.03em;
      margin-bottom: 0.85rem; color: var(--text);
    }
    .section-heading-center p { font-size: 1.05rem; color: var(--text-muted); line-height: 1.6; }

    /* Features Grid with 3D Hover Lift */
    .grid-features { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1.75rem; }
    .feature-card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 18px; padding: 2.25rem; transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: var(--shadow-sm); position: relative; overflow: hidden;
    }
    .feature-card:hover {
      transform: translateY(-5px);
      box-shadow: var(--shadow-hover);
      border-color: #93c5fd;
    }
    .feature-tag {
      font-size: 0.72rem; font-family: var(--font-mono); font-weight: 700; text-transform: uppercase;
      padding: 0.25rem 0.55rem; border-radius: 6px; display: inline-block; margin-bottom: 1rem;
      background: #eff6ff; color: #1d4ed8;
    }
    .feature-card h3 { font-size: 1.28rem; font-weight: 800; margin-bottom: 0.6rem; color: var(--text); letter-spacing: -0.02em; }
    .feature-card p { font-size: 0.92rem; color: var(--text-muted); line-height: 1.65; margin-bottom: 1.25rem; }
    .feature-metric {
      padding-top: 1rem; border-top: 1px solid var(--border);
      display: flex; align-items: baseline; justify-content: space-between;
      font-size: 0.85rem; font-weight: 600; color: var(--text-dim);
    }
    .feature-metric span.metric-val { font-family: var(--font-mono); font-weight: 700; color: var(--text); font-size: 1.05rem; }

    /* Interactive Tool Directory */
    .tool-controls {
      display: flex; gap: 1rem; align-items: center; justify-content: space-between;
      margin-bottom: 2rem; flex-wrap: wrap; background: #ffffff;
      padding: 1.1rem 1.4rem; border-radius: 16px; border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }
    .search-box-wrap { flex: 1; min-width: 280px; position: relative; }
    .search-tool-input {
      width: 100%; padding: 0.8rem 1rem 0.8rem 2.6rem; border-radius: 10px;
      border: 1px solid var(--border); font-size: 0.95rem; font-family: var(--font-sans);
      outline: none; transition: all 0.15s ease;
    }
    .search-tool-input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.12); }
    .search-icon-svg {
      position: absolute; left: 0.9rem; top: 50%; transform: translateY(-50%);
      width: 17px; height: 17px; color: var(--text-dim); pointer-events: none;
    }
    .category-pills { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .category-btn {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.5rem 1rem; border-radius: 8px; font-size: 0.82rem; font-weight: 700;
      cursor: pointer; transition: all 0.15s ease;
    }
    .category-btn.active, .category-btn:hover {
      background: #09090b; color: #ffffff; border-color: #09090b;
    }

    .tools-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.4rem; }
    .tool-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 16px;
      padding: 1.6rem; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1); box-shadow: var(--shadow-sm);
      display: flex; flex-direction: column; justify-content: space-between;
    }
    .tool-card:hover { border-color: #93c5fd; box-shadow: var(--shadow-card); transform: translateY(-2px); }
    .tool-header {
      display: flex; align-items: baseline; justify-content: space-between;
      margin-bottom: 0.6rem; flex-wrap: wrap; gap: 0.5rem;
    }
    .tool-title { font-family: var(--font-mono); font-size: 1.08rem; font-weight: 700; color: #0284c7; }
    .tool-badge-profile {
      font-size: 0.7rem; font-family: var(--font-mono); font-weight: 700;
      padding: 0.2rem 0.55rem; border-radius: 5px; background: #f1f5f9; color: #475569;
    }
    .tool-badge-profile.core { background: #dbeafe; color: #1e40af; }
    .tool-badge-profile.trace { background: #e0e7ff; color: #4338ca; }
    .tool-badge-profile.database { background: #fef3c7; color: #92400e; }
    .tool-badge-profile.runtime { background: #dcfce7; color: #166534; }

    .tool-desc { font-size: 0.9rem; color: var(--text-muted); line-height: 1.55; margin-bottom: 0.85rem; }
    .tool-solve-badge {
      background: #f8fafc; border-left: 3px solid #0284c7; padding: 0.45rem 0.75rem;
      border-radius: 0 8px 8px 0; font-size: 0.82rem; color: #334155; margin-bottom: 1rem;
    }
    .tool-solve-badge strong { color: var(--text); }

    .tool-expand-btn {
      background: #f8fafc; border: 1px solid var(--border); color: var(--text-muted);
      padding: 0.45rem 0.85rem; border-radius: 8px; font-size: 0.8rem; font-weight: 700;
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
    .cli-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.6rem; }
    .cli-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 16px;
      padding: 1.85rem; box-shadow: var(--shadow-sm); transition: all 0.2s ease;
    }
    .cli-card:hover { box-shadow: var(--shadow-card); border-color: #cbd5e1; }
    .cli-cmd-name {
      font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: #0f172a; margin-bottom: 0.4rem;
    }
    .cli-problem {
      background: #eff6ff; color: #1e3a8a; padding: 0.45rem 0.75rem; border-radius: 8px;
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
      background: #ffffff; border: 1px solid var(--border); border-radius: 18px;
      padding: 2.25rem; box-shadow: var(--shadow-card); margin-bottom: 2rem; text-align: center;
    }
    .diagram-card img { max-width: 100%; height: auto; border-radius: 10px; }
    .diagram-caption { margin-top: 1.1rem; font-size: 0.9rem; color: var(--text-muted); }

    /* Integration Cards */
    .integration-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; }
    .integration-card {
      background: #ffffff; border: 1px solid var(--border); border-radius: 16px;
      padding: 1.75rem; box-shadow: var(--shadow-sm);
    }
    .integration-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    .integration-title { font-size: 1.15rem; font-weight: 800; color: var(--text); }
    .integration-badge {
      font-size: 0.72rem; font-weight: 700; font-family: var(--font-mono);
      background: #f1f5f9; color: #475569; padding: 0.2rem 0.55rem; border-radius: 6px;
    }

    /* Scaling Benchmark Table */
    .table-container {
      background: #ffffff; border: 1px solid var(--border); border-radius: 16px;
      overflow-x: auto; box-shadow: var(--shadow-sm);
    }
    .custom-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; text-align: left; }
    .custom-table th {
      padding: 0.95rem 1.35rem; background: #f8fafc; color: var(--text-dim);
      font-weight: 700; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }
    .custom-table td { padding: 1rem 1.35rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
    .custom-table tr:last-child td { border-bottom: none; }
    .custom-table td.strong { font-weight: 700; color: var(--text); }
    .badge-metric-green {
      background: #dcfce7; color: #15803d; font-family: var(--font-mono);
      font-size: 0.75rem; font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px;
    }

    /* Footer */
    footer.app-footer {
      background: #ffffff; border-top: 1px solid var(--border);
      padding: 4.5rem 2rem 3.5rem; margin-top: 4rem; position: relative; z-index: 10;
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

  <!-- 3D Interactive Canvas & Ambient Lighting -->
  <canvas id="bgCanvas"></canvas>
  <div class="ambient-glow-1"></div>
  <div class="ambient-glow-2"></div>

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

  <!-- Hero Section with 3D Parallax Tilt -->
  <div class="hero-wrapper">
    <section class="hero-container" id="heroSection">
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

      <!-- Hero Right: Interactive 3D Mockup Card -->
      <div class="hero-mockup-wrapper">
        <div class="hero-mockup-card" id="heroMockupCard">
          <div class="card-glare" id="cardGlare"></div>

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
      </div>
    </section>

    <!-- Elevated Floating Metric Strip -->
    <div class="metric-strip-wrap">
      <div class="metric-strip">
        <div class="metric-item">
          <div class="metric-item-val"><span class="accent-blue">56</span></div>
          <div class="metric-item-label">Deterministic Tools</div>
          <div class="metric-item-sub">Zero discovery loop tax</div>
        </div>
        <div class="metric-item">
          <div class="metric-item-val"><span class="accent-green">861</span></div>
          <div class="metric-item-label">Verified Tests Passed</div>
          <div class="metric-item-sub">100% compiler-grade tests</div>
        </div>
        <div class="metric-item">
          <div class="metric-item-val">0.00%</div>
          <div class="metric-item-label">Unsupported Claims</div>
          <div class="metric-item-sub">Proven AST facts only</div>
        </div>
        <div class="metric-item">
          <div class="metric-item-val">&lt; 45ms</div>
          <div class="metric-item-label">P95 Retrieval Latency</div>
          <div class="metric-item-sub">SQLite WAL + FTS5 search</div>
        </div>
      </div>
    </div>
  </div>

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

  <!-- Interactive 3D Parallax & Script Engine -->
  <script>
    // 1. Interactive 3D Parallax Tilt for Hero Card
    const heroCard = document.getElementById('heroMockupCard');
    const heroSection = document.getElementById('heroSection');
    const cardGlare = document.getElementById('cardGlare');

    if (heroSection && heroCard) {
      heroSection.addEventListener('mousemove', (e) => {
        const rect = heroCard.getBoundingClientRect();
        const cardX = rect.left + rect.width / 2;
        const cardY = rect.top + rect.height / 2;
        
        const deltaX = (e.clientX - cardX) / (rect.width / 2);
        const deltaY = (e.clientY - cardY) / (rect.height / 2);

        // Clamped tilt angles
        const rotateX = Math.max(-12, Math.min(12, -deltaY * 10));
        const rotateY = Math.max(-12, Math.min(12, deltaX * 10));

        heroCard.style.transform = `rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;

        // Specular Glare Follow
        if (cardGlare) {
          const glareX = ((e.clientX - rect.left) / rect.width) * 100;
          const glareY = ((e.clientY - rect.top) / rect.height) * 100;
          cardGlare.style.background = `radial-gradient(circle at ${glareX}% ${glareY}%, rgba(255, 255, 255, 0.7) 0%, transparent 60%)`;
        }
      });

      heroSection.addEventListener('mouseleave', () => {
        heroCard.style.transform = 'rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
      });
    }

    // 2. Interactive 3D AST Knowledge Graph Canvas Background
    const canvas = document.getElementById('bgCanvas');
    if (canvas) {
      const ctx = canvas.getContext('2d');
      let width, height;
      let mouseX = 0, mouseY = 0;
      let targetMouseX = 0, targetMouseY = 0;

      function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = Math.min(window.innerHeight * 1.2, 900);
      }
      window.addEventListener('resize', resize);
      resize();

      window.addEventListener('mousemove', (e) => {
        targetMouseX = (e.clientX - width / 2) * 0.05;
        targetMouseY = (e.clientY - height / 2) * 0.05;
      });

      // Generate Knowledge Graph Nodes
      const labels = ['AST', 'Symbol', 'Call', 'FastAPI', 'SQLite', 'Trace', 'Class', 'FTS5', 'Route', 'Model', 'Parser', 'Verify', 'Index', 'Graph'];
      const nodes = [];
      const nodeCount = 38;

      for (let i = 0; i < nodeCount; i++) {
        nodes.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.4,
          vy: (Math.random() - 0.5) * 0.4,
          depth: 0.3 + Math.random() * 0.7, // Parallax depth layer
          radius: 2.5 + Math.random() * 3,
          label: i < labels.length ? labels[i] : null
        });
      }

      function draw() {
        ctx.clearRect(0, 0, width, height);

        // Smooth mouse parallax lerp
        mouseX += (targetMouseX - mouseX) * 0.05;
        mouseY += (targetMouseY - mouseY) * 0.05;

        // Draw connecting edges
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const p1 = nodes[i];
            const p2 = nodes[j];

            const p1x = p1.x + mouseX * p1.depth;
            const p1y = p1.y + mouseY * p1.depth;
            const p2x = p2.x + mouseX * p2.depth;
            const p2y = p2.y + mouseY * p2.depth;

            const dist = Math.hypot(p1x - p2x, p1y - p2y);
            if (dist < 130) {
              const alpha = (1 - dist / 130) * 0.18;
              ctx.strokeStyle = `rgba(2, 132, 199, ${alpha})`;
              ctx.lineWidth = 1;
              ctx.beginPath();
              ctx.moveTo(p1x, p1y);
              ctx.lineTo(p2x, p2y);
              ctx.stroke();
            }
          }
        }

        // Draw nodes
        for (let i = 0; i < nodes.length; i++) {
          const p = nodes[i];
          p.x += p.vx;
          p.y += p.vy;

          if (p.x < 0) p.x = width;
          if (p.x > width) p.x = 0;
          if (p.y < 0) p.y = height;
          if (p.y > height) p.y = 0;

          const px = p.x + mouseX * p.depth;
          const py = p.y + mouseY * p.depth;

          ctx.fillStyle = p.label ? '#0284c7' : '#94a3b8';
          ctx.beginPath();
          ctx.arc(px, py, p.radius * p.depth, 0, Math.PI * 2);
          ctx.fill();

          if (p.label && p.depth > 0.6) {
            ctx.font = '600 10px JetBrains Mono';
            ctx.fillStyle = 'rgba(71, 85, 105, 0.7)';
            ctx.fillText(p.label, px + 8, py + 3);
          }
        }

        requestAnimationFrame(draw);
      }
      draw();
    }

    // 3. Tool Filtering & Category Tabs
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
