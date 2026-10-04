# Changelog

## 2.1.7 (Large Repository Indexing, Windows Output Safety & MCP Process Lifecycle Hardening)

### Windows Output Safety, MCP Process Lifecycle & Dynamic Hot-Reload
- **Windows Terminal Encoding Safety (`src/codegraph/cli_output.py`)**: Centralized stream encoding detection (`detect_stream_encoding`, `supports_unicode`, `cli_echo`) that safely degrades Unicode symbols (`✓` → `[OK]`, `✗` → `[ERROR]`, `⚠` → `[WARN]`, `↻` → `[REPAIRED]`, `(•)` → `(*)`) on Windows `cp1252` / `cp437` / ASCII terminals and redirected pipes while preserving rich Unicode on UTF-8 terminals and keeping `--json` strictly machine-readable.
- **Deterministic MCP Process Lifecycle & Orphan Prevention (`src/codegraph/process_lifecycle.py`)**: `codegraph mcp serve` records verified process ownership metadata (`pid`, `parent_pid`, creation timestamps, executable signature, repository path) in `~/.codegraph/processes/pid_<pid>.json` and monitors `stdin` EOF and parent-process liveness across Windows (`kernel32`), macOS (`libSystem` `proc_pidinfo`), and Linux (`/proc`) so MCP servers shut down cleanly when the parent IDE/agent closes or crashes.
- **Safe `codegraph stop` & `codegraph doctor --processes`**: Added `codegraph stop` (`--all`, `--repo`, `--timeout`, `--json`), `codegraph mcp stop`, `codegraph mcp kill`, and `codegraph doctor --processes` to release Windows `codegraph.exe` locks (`WinError 32` prevention) while verifying PID creation timestamps so reused/unrelated PIDs are never terminated.
- **Dynamic Index Hot-Reloading (`src/codegraph/mcp/server.py`)**: If `codegraph mcp serve` starts before `codegraph init` is run, the running MCP server automatically detects `.codegraph.sqlite3` creation or modification on the next tool call and invalidates stale in-memory graph/parse caches without requiring an IDE or MCP server restart.

### Performance & Scalability
- **16-Phase Indexing Telemetry (`src/codegraph/indexing/telemetry.py`)**: Deterministic phase timing, item/file counters, throughput (`files/sec`, `edges/sec`), RSS memory tracking (`rss_before_mb`, `post_parse_rss_mb`, `peak_rss_mb`, `steady_state_rss_mb`), `peak_tracemalloc_mb`, and SQLite WAL size tracking across all 16 indexing phases.
- **Streaming & Token-Gated Database Intelligence (`5.79x` Faster)**: Eliminated in-memory full-repository `file_contents` caching and redundant AST parses during post-processing; added `has_potential_database_activity` and `has_potential_orm_models` fast token pre-filters and single-AST-parse sharing per candidate file, plus dirty-file incremental database updates.
- **Pre-Indexed Symbol & Binding Resolution (`2.83x` Faster)**: Replaced $O(N_{\text{bindings}} \times N_{\text{symbols}})$ linear scans in `resolver.py` with pre-indexed lookup maps (`bindings_by_target`, `bindings_by_kind`, `receiver_bindings_by_fts`, `call_return_bindings_by_file`, `inheritance_by_source`, `event_listeners_by_key`, `symbols_by_file`) and `@lru_cache(maxsize=65536)` on `normalize_module`.
- **Bounded Wildcard & Re-Export Safeguards**: Enforced configurable cycle-safe depth and work bounds (`max_reexport_depth=16`, `max_wildcard_expansions=64`). When exceeded, emits explicit `UNKNOWN` (`POSSIBLE_CALLS` / `ResolutionFinding` with `reason="resolution_budget_exceeded"`).
- **Chunked SQLite Batch Commits & WAL Checkpoints (`7.09x` Smaller Peak WAL)**: Added composite indexes `idx_imports_source_line` and `idx_calls_source_line`, skipped redundant `DELETE` statements on brand-new files, introduced bounded batch commits (`_FILE_COMMIT_BATCH_SIZE = 500`, `_EDGE_COMMIT_BATCH_SIZE = 10000`), and added `PRAGMA wal_checkpoint(TRUNCATE)` on completion.
- **Safe `Ctrl+C` Cancellation & Resumable Indexing**: Cleanly rolls back only the interrupted batch, preserves previously committed file batches, records `resolution_dirty="1"`, and resumes on the next `codegraph index` run.
- **CLI Indexing Flags**: Added `--verbose` (`-v`), `--quiet` (`-q`), and `--json` to `codegraph index`.

## 2.1.6 (Production Installer & Agent Onboarding)

- **`codegraph install` / `uninstall` / `uninit` (`src/codegraph/installer.py`)**: Automatic detection and idempotent configuration for **Claude Code**, **Cursor**, **Antigravity**, **Codex CLI**, **Gemini CLI**, and **Cline** across local and global scopes.
- **Marker-Managed Agent Instructions**: Safe `<!-- CODEGRAPH:START -->` … `<!-- CODEGRAPH:END -->` block insertion and update for `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursor/rules/codegraph.mdc`, `.clinerules/codegraph.md`, and `.agents/skills/codegraph/SKILL.md` with backup, atomic write, and user-modification protection.

## 2.1.5 (Agent UX, Literal Search & 14-Tool Default Profile)

- **14-Tool Default `agent` MCP Profile**: High-signal default tool surface (`find_symbol`, `search_code`, `find_references`, `find_callers`, `find_callees`, `find_tests`, `find_routes`, `get_symbol`, `get_file`, `get_context`, `get_architecture`, `get_git_impact`, `trace_path`, `trace_flow`) with 56 tools in the `full` profile.
- **Literal & Regex Repository Search (`search_code`) & Bounded Reader (`get_file`)**: First-class text search across Python, HTML/Jinja, JS/TS, CSS, JSON/YAML, Markdown, and SQL, plus bounded line-slice file inspection.

## 2.1.4 (Database, Runtime & Security Intelligence)

- **Database Deep Intelligence (`src/codegraph/database/`)**: Schema, table, column, ORM model, migration, and `READS_TABLE` / `WRITES_TABLE` extraction across SQLAlchemy, Django ORM, SQLModel, Prisma, Alembic, Django migrations, and raw SQL (`11` database MCP tools).
- **Opt-In Runtime Trace Ingestion & Static Reconciliation (`src/codegraph/runtime/`)**: OpenTelemetry JSON, JSONL runtime event, and SQL query log ingestion with `reconcile_static_runtime` (`CONFIRMED_RUNTIME_PATH`, `NOT_OBSERVED_AT_RUNTIME`, `RUNTIME_ONLY_OBSERVED`, `STATIC_RUNTIME_CONFLICT`).
- **Security & Secret Redaction Layer (`src/codegraph/security/`)**: Sensitive file blocking (`.env`, private keys, credentials) and automatic secret/URI/SQL parameter redaction across indexing, search, file reads, database extraction, and runtime traces.

## 2.1.1 (Production Interrogation & Agent UX Hardening)

- **Unified MCP Response Contract & Ambiguity Guard**: Standardized response envelope and structured error recovery codes (`ErrorCode`).

## 2.1.0 (Task-Aware Retrieval Engine)

- **TargetResolver, RetrievalPolicy, QueryExpansion & ConstraintGuard**: Task-aware retrieval policies across 10 intents with hierarchical exclusion invariants.

## 2.0.0

- Production evaluation suite with 50 benchmark tasks across 10 categories, two-stage retrieval, token-budget optimizer, and resource governor.
