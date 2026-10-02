# Changelog

## 2.1.1 (Production Interrogation & Agent UX Hardening)

### Core Interrogation Architecture
- **13-Tool MCP Interrogation Engine**: Unified orthogonal tool suite (`resolve_symbol`, `search_symbols`, `get_symbol`, `get_file`, `get_references`, `get_callers`, `get_callees`, `trace_path`, `get_imports`, `get_dependents`, `list_routes`, `get_architecture`, `get_git_impact`) delivering deterministic AST facts, call and import graphs, and verified line citations.
- **Unified MCP Response Contract**: Standardized response envelope (`status`, `symbol`/`file`/`callers`, `evidence`, `index`, `repository`) across all interrogation tools.
- **Ambiguity Guard**: When symbol queries match multiple entities, returns `status: "ambiguous"` with sorted candidates (`canonical_id`, `symbol`, `file`, `line`) rather than guessing developer intent.

### Agent UX & CLI Hardening
- **Structured Error Contract**: Replaced raw tracebacks on expected operational failures with machine-readable JSON envelopes containing stable error codes and deterministic `next_action` recovery guidance.
- **Centralized Error Codes**: Introduced `ErrorCode` enum (`INDEX_NOT_FOUND`, `INDEX_STALE`, `REPOSITORY_NOT_INITIALIZED`, `INVALID_PATH`, `PATH_OUTSIDE_REPOSITORY`, `SYMBOL_NOT_FOUND`, `SYMBOL_AMBIGUOUS`, `INVALID_ARGUMENT`, `INVALID_DEPTH`, `SENSITIVE_FILE_ACCESS_DENIED`, etc.).
- **CLI Path Consistency**: All repository inspection commands (`index`, `init`, `status`, `doctor`, `architecture`, `routes`, `privacy`, `serve`, `benchmark`) accept optional positional `[PATH]` defaulting to `.` as well as `-r` / `--repo`.
- **Explicit Symbol Commands**: Added `codegraph get-symbol <symbol>` and `codegraph resolve-symbol <query>`.
- **Schema Self-Healing**: Bumped SQLite schema version to 6 with automatic migration for file categories and index attributes.
- **MCP Stdio Hygiene**: Enforced stdout protocol purity for stdio MCP clients, directing logging and diagnostics strictly to stderr.

## 2.1.0 (Task-Aware Retrieval Engine)

### Core Retrieval & Architecture
- **TargetResolver**: First-class target resolution supporting exact canonical symbol IDs, exact qualified names, framework route endpoints, module-symbol hierarchies, class-method resolution, exact filenames, and ambiguity-aware lexical matching.
- **RetrievalPolicy**: Intent-driven retrieval contracts (`TRACE`, `UNDERSTAND`, `DEBUG`, `IMPACT`, `REVIEW`, `ARCHITECTURE`, `CHANGE`, `REFACTOR`, `TEST`, `EXPLAIN`) with explicit allowed relationship sets, search depth bounds, and coverage flow priority. Disallowed relationships are hard-filtered before reaching downstream ranking or serialization.
- **QueryExpansion**: Unified canonical query expansion replacing bare generic verbs (`get`, `post`, `run`, `login`) with fully-qualified symbols (`AdminDashboardView.get`, `AuthService.login`) and route handlers.
- **ConstraintGuard**: Hierarchical and path-component constraint enforcement. `AuthService` excludes `AuthService.login` and its methods while permitting `AuthServiceHelper`. Path matching respects repository boundaries and avoids partial-suffix collisions (`src/auth.py` does not match `src/auth.py.backup`).
- **Grounded Graph Seed Selection**: Graph traversal expands only grounded target roots and route handlers rather than ungrounded lexical matches, with deterministic seed ordering and traversal bounds.
- **Epistemic Relationship Distinction**: Preserves clean separation between verified facts (`CALLS`) and inferred relationships (`POSSIBLE_CALLS`).

### Production Hardening & Diagnostics
- **Diagnostic Engine**: Granular causal classification of false negatives (`TARGET_RESOLUTION`, `LEXICAL_RECALL`, `QUALIFIED_NAME_RESOLUTION`, `GRAPH_TRAVERSAL`, `REFERENCE_RESOLUTION`, `FRAMEWORK_DETECTION`, `TEST_LINKING`, `RANKING`, `BUDGET_PRUNING`, `OVER_FILTERING`) and false positives (`LEXICAL_NOISE`, `GRAPH_POLLUTION`, `WRONG_TARGET`, `WRONG_RELATIONSHIP`, `FRAMEWORK_NOISE`, `TEST_NOISE`, `IMPORT_NOISE`, `DUPLICATE_SYMBOL`, `PARENT_SCOPE_NOISE`, `RANKING_ERROR`).
- **Doctor Command**: Added `codegraph doctor --database` for deep SQLite integrity checks, schema validation, foreign key enforcement, orphan detection, and FTS consistency verification.
- **CLI & MCP Stability**: Added `--version` eager option callback, deterministic output sorting, and backward-compatible parameter signatures.
- **Deterministic Testing**: Validated 100% deterministic repeatable execution across repeated benchmark runs and soak simulations.

## 2.0.0

- Production evaluation suite with 50 benchmark tasks across 10 categories.
- Two-stage retrieval, token-budget optimizer, coverage compiler, resource governor, and active-coding protection.

## 0.1.0

- Initial release: secure local indexing, evidence, lexical retrieval, static symbols/imports/call hints, CLI, and optional MCP server.
