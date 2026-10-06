# CodeGraph VS Code Extension

Official Visual Studio Code extension for CodeGraph — the deterministic repository knowledge graph, sub-15ms live watcher, and PR blast radius engine.

## Overview

CodeGraph gives your editor and AI coding agents instant AST-verified code intelligence without hallucinations:
- **Interactive Visual Knowledge Graph**: Built-in side-by-side webview showing graph relationships, callers/callees, and data lineage.
- **Full-Stack Route Explorer**: Sidebar tree discovering Next.js Server Actions, FastAPI endpoints, Flask routes, Express/NestJS handlers, and PyTorch forward dispatch.
- **Database Lineage & Models**: Inspect Prisma, Drizzle, SQLAlchemy, and Mongoose tables with exact static readers and writers.
- **PR Blast Radius & Risk Tiering**: Instant calculation of downstream callers, broken contracts, and targeted tests before you commit or merge.
- **Sub-15ms Live Watcher**: SQLite WAL daemon continuously updating graph state on every file save.

## Prerequisites

Install CodeGraph CLI & engine:
```bash
pip install codegraph-engine
```

## Installation & Setup

1. Open this repository or install the `.vsix` package in VS Code:
   ```bash
   code --install-extension codegraph-3.0.0.vsix
   ```
2. Open your workspace containing your code repository.
3. Start the CodeGraph visualizer:
   ```bash
   codegraph ui
   ```
4. Click the CodeGraph icon in the activity bar or run command `CodeGraph: Open Visual Knowledge Graph Dashboard`.

## Extension Commands

- `CodeGraph: Open Visual Knowledge Graph Dashboard` (`codegraph.openUI`): Opens the interactive graph visualizer panel.
- `CodeGraph: Calculate PR Blast Radius for Current File` (`codegraph.showImpact`): Computes downstream impact and targeted tests for the current active file.
- `CodeGraph: Inspect Cross-Language API Drift` (`codegraph.checkApiDrift`): Identifies breaking changes between frontend API calls and backend route signatures.
- `CodeGraph: Start Sub-15ms Live Watcher Daemon` (`codegraph.startWatcher`): Spawns the background SQLite WAL watcher in an integrated terminal.
- `CodeGraph: Safe AST Rename Symbol` (`codegraph.safeRename`): Deterministic symbol refactoring across all call sites and route handlers.

## Configuration

- `codegraph.serverPort` (default: `8765`): HTTP port for the local dashboard and SSE event stream.
- `codegraph.autoStartWatcher` (default: `true`): Automatically inspect index status and launch background watcher if needed.

## License

MIT License.
