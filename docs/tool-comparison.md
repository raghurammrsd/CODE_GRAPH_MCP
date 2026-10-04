# Repository Retrieval & Navigation Approaches — Detailed Capability Comparison

CodeGraph Engine (`codegraph-engine` **v2.1.7**) is designed to complement—not replace—interactive editor language servers (LSP), structural AST rewrite tools, and lexical search tools.

Legend:
- `✓` — Supported as a documented capability
- `◐` — Partial or workflow/plugin-dependent
- `—` — Not established by cited official documentation
- `?` — Unclear / not verified

---

## 1. CodeGraph Engine vs. Unassisted File/Grep Exploration

| Dimension | Unassisted (`grep` + `read_file`) | CodeGraph Engine (`v2.1.7`) | Operational Difference |
| :--- | :---: | :---: | :--- |
| **Literal string & regex search** | ✓ | ✓ (`search_code`) | Both search `.py`, `.html`, `.js`, `.ts`, `.css`, `.yaml`, `.sql`. |
| **Distinguish definition vs. call vs. import** | — | ✓ | `grep` matches comments and substrings; CodeGraph queries AST symbol and edge records. |
| **Homonym disambiguation (`get`, `run`, `save`, `forward`)** | — | ✓ (`AMBIGUOUS` + canonical IDs) | Avoids opening unrelated files that happen to define a method with the same short name. |
| **Multi-hop path tracing (`A → B → C → D`)** | — | ✓ (`trace_path`, `trace_flow`) | Computes shortest verified call, route, or DI path in a single query. |
| **Composed HTTP route resolution (`MOUNTS`)** | — | ✓ (`find_routes`, `list_routes`) | Joins router mount prefixes (`include_router`, `register_blueprint`, `app.use`) with endpoint paths. |
| **ORM model ↔ table ↔ SQL read/write graph** | — | ✓ (`find_db_*`, `get_db_impact`) | Links Python functions and ORM models to `READS_TABLE` and `WRITES_TABLE` across files. |
| **Built-in secret redaction & `.env` blocking** | — | ✓ | Blocks `.env` / private keys and redacts inline tokens before returning snippets. |

---

## 2. CodeGraph Engine vs. Language Server Protocol (LSP)

LSP ([Official Specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/current/)) standardizes interactive editor operations (`textDocument/definition`, `textDocument/references`, hover, completions, diagnostics, and rename refactoring). CodeGraph targets **agentic MCP interrogation** across code, framework routing, database schemas, and optional runtime traces:

| Capability | Editor LSP (`textDocument/*`) | CodeGraph Engine (`v2.1.7`) | Notes |
| :--- | :---: | :---: | :--- |
| **Interactive editor hover, completions & live diagnostics** | ✓ | — | Use your IDE language server (`pyright`, `tsserver`, `rust-analyzer`) for live editor feedback. |
| **Go to definition & find references** | ✓ | ✓ (`find_symbol`, `find_references`) | LSP takes `(documentUri, line, character)` cursor positions; CodeGraph accepts symbol names or canonical IDs over MCP. |
| **Multi-hop BFS execution path (`trace_path`)** | — | ✓ | Traverses multi-hop paths across calls, routes, and DI providers in one MCP call. |
| **Framework route & mount prefix table** | — | ✓ (`find_routes`, `list_routes`) | Extracts FastAPI, Flask, Django, and Express routes with composed mount prefixes. |
| **Database schema, ORM & migration graph** | — | ✓ (`get_db_schema`, `find_db_writers`) | Maps SQLAlchemy, Django ORM, SQLModel, Prisma, Alembic, and SQL queries to tables and columns. |
| **Opt-in runtime trace ingestion & reconciliation** | — | ✓ (`ingest_runtime_traces`, `reconcile_static_runtime`) | Reconciles OpenTelemetry / JSONL / SQL logs against static graph edges. |
| **Token-budgeted agent context compilation** | — | ✓ (`get_context`) | Selects and compresses symbols, relationships, routes, and tests within `max_tokens`. |

---

## 3. Multi-Tool Architectural Matrix

| Capability | CodeGraph Engine (`v2.1.7`) | Colby McHenry CodeGraph [1] | Sourcegraph + MCP [2] | `ast-grep` [3] | `ripgrep` (`rg`) [4] | GitHub Code Navigation [5] |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Local-First / Offline Execution** | ✓ | ✓ | — (Server/Cloud instance) | ✓ | ✓ | — (GitHub Cloud/Server) |
| **Native MCP Server** | ✓ (14 default / 56 full) | ✓ (`codegraph_explore` + graph tools) | ✓ (Sourcegraph MCP server) | ◐ (CLI / community wrappers) | — | ◐ (GitHub MCP server) |
| **Automated Multi-Agent Installer (`install`)** | ✓ (6 agents + marker sync) | ✓ (`npx @colbymchenry/codegraph`) | — | — | — | — |
| **Semantic Symbol Graph (Callers / Callees)** | ✓ | ✓ | ✓ (SCIP / precise navigation) | ◐ (AST pattern matching) | — | ✓ (Tree-sitter / SCIP) |
| **Multi-Language AST Breadth (10+ languages)** | — (Python, JS/TS + SQL/Prisma) | ✓ (Tree-sitter multi-language) | ✓ (Multi-language) | ✓ (Multi-language AST) | — (Text/Regex) | ✓ (20+ languages) |
| **AST Structural Rewrite / Codemods** | — | — | ◐ (Batch Changes) | ✓ (First-class rewrite rules) | — | — |
| **Multi-Repository Enterprise Search** | — (Single repo / monorepo) | — (Local project) | ✓ (First-class multi-repo) | — | — | ✓ (Global GitHub search) |
| **Framework Route & DI Graph (FastAPI/Flask/Django/Express)** | ✓ (`MOUNTS`, `INJECTS`, `HANDLED_BY`) | — | — | ◐ (Custom YAML rules) | — | — |
| **Database Schema, ORM, Migration & Table R/W Graph** | ✓ (11 DB MCP tools) | — | — | — | — | — |
| **Opt-In Runtime Trace Ingestion & Static Reconciliation** | ✓ (OTel, JSONL, SQL logs) | — | — | — | — | — |
| **Explicit Epistemic States (`FACT` / `POSSIBLE` / `UNKNOWN`)** | ✓ (Fail-closed contract) | — | — | — | — | — |
| **Built-In Secret Redaction & `.env` Blocking** | ✓ | — | ◐ (Access control) | — | — | ◐ (Secret scanning alerts) |

### Official References
1. **Colby McHenry's CodeGraph**: [https://github.com/colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)
2. **Sourcegraph MCP & Code Navigation**: [https://sourcegraph.com/docs/api/mcp](https://sourcegraph.com/docs/api/mcp) & [https://sourcegraph.com/docs/code-navigation](https://sourcegraph.com/docs/code-navigation)
3. **`ast-grep`**: [https://ast-grep.github.io/](https://ast-grep.github.io/)
4. **`ripgrep`**: [https://github.com/BurntSushi/ripgrep](https://github.com/BurntSushi/ripgrep)
5. **GitHub Code Navigation**: [https://docs.github.com/en/repositories/working-with-files/using-files/navigating-code-on-github](https://docs.github.com/en/repositories/working-with-files/using-files/navigating-code-on-github)
