# CodeGraph MCP — Tool Capabilities Summary (v2.1.8)

> Compact task-to-tool routing table derived from `src/codegraph/agent_capabilities.py` (`ROUTING_MANIFEST`) and `src/codegraph/evidence_contract.py`.

## Task Routing & Evidence Expectations

| Task / Domain | Preferred First Tool | Common Follow-Up Tool(s) | Evidence Expectations & Relationship Types |
| :--- | :--- | :--- | :--- |
| **`LOCAL_EDIT`** (Single-file typo / local variable) | `get_file` / `read_file` (Bypass CodeGraph) | Apply edit directly | Direct on-disk source lines; 0 graph calls needed. |
| **`SYMBOL_LOOKUP`** (Where is X defined?) | `find_symbol` / `resolve_symbol` | `get_symbol` -> `get_file` | `DEFINES`, `CONTAINS`, `RESOLVES_TO` (`AST_VERIFIED`) + explicit `AMBIGUOUS` alternatives. |
| **`TEXT / TEMPLATE SEARCH`** (Literal text, HTML id, UI label) | `search_code` | `get_file(path, start_line, end_line)` | Deterministic text match across `.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, `.md` (never emits semantic edges). |
| **`FILE_INSPECTION`** (Show lines N..M of a file) | `get_file(path, start_line, end_line)` | `find_symbol` / `find_callers` | Bounded source lines (`content`, `truncated`, `category`) + AST symbol outline. |
| **`CALLERS / CALLEES`** (Who calls X / What does X call?) | `find_callers` / `find_callees` | `get_callers` / `get_callees` | `CALLS` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`) vs `POSSIBLE_CALLS` (`POSSIBLE`, `UNKNOWN`). |
| **`TRACE`** (End-to-end execution path) | `find_routes` / `find_symbol` | `trace_path` -> `get_context(intent="TRACE")` | Ordered hop chain (`HANDLED_BY`, `MOUNTS`, `INJECTS`, `PROVIDES`, `DISPATCHES_TO`, `CALLS`) + uncertainty preservation. |
| **`ROUTE_DISCOVERY`** (HTTP/RPC endpoints & mounts) | `find_routes` / `list_routes` | `find_symbol` -> `trace_path` | Composed route paths via `MOUNTS`, `HANDLED_BY`, `ROUTE_HANDLER`, `ROUTES_TO` (`FRAMEWORK_VERIFIED`). |
| **`DI`** (Dependency Injection & Providers) | `find_symbol` / `resolve_symbol` | `get_context(intent="DEBUG")` / `get_references` | `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, `DI_CYCLE` (never collapsed into `CALLS`). |
| **`REGISTRY / DISPATCH`** (Plugin & handler maps) | `find_symbol` / `resolve_symbol` | `get_references` / `get_context` | `REGISTERS`, `REGISTERED_HANDLER`, `DISPATCHES_TO` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`). |
| **`EVENTS / TASKS / COMMANDS`** | `find_symbol` / `resolve_symbol` | `get_references` / `trace_path` | `EVENT_LISTENER`, `TASK_HANDLER`, `COMMAND_HANDLER` (`FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`). |
| **`TEST_DISCOVERY`** (What tests cover X?) | `find_tests` / `find_related_tests` | `get_file(path, start_line, end_line)` | `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER` (never fabricated from lexical similarity). |
| **`CHANGE_IMPACT`** (Blast radius & Git diff impact) | `get_git_impact` / `analyze_impact` | `find_tests` -> `get_file` | Modified symbols, downstream `CALLS`/`IMPORTS`, affected `DEPENDS_ON_PACKAGE`, and covering `TESTS`. |
| **`PACKAGE`** (Monorepo & workspace boundaries) | `get_architecture` | `get_context(intent="ARCHITECTURE")` / `get_dependents` | Manifest-backed `DEPENDS_ON_PACKAGE`, `PACKAGE_IMPORTS`, `CROSS_PACKAGE_IMPORT`, `CONTAINS_PACKAGE`. |
| **`ARCHITECTURE`** (System & module overview) | `get_architecture` | `get_context(intent="ARCHITECTURE")` | Modules, workspace packages, entrypoints, and routes. |
| **`DATABASE`** (Tables, columns, ORM models, queries, impact) | `find_db_tables` / `get_db_table` | `find_db_callers` / `find_db_writers` / `get_db_impact` | `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `READS_TABLE`, `WRITES_TABLE`, `FOREIGN_KEY_TO`, `MIGRATES_TABLE`, `POSSIBLE_TABLE`, `UNKNOWN_TABLE`. |
| **`RUNTIME`** (Traces & static-vs-runtime reconciliation) | `get_runtime_trace` / `reconcile_static_runtime` | `ingest_runtime_traces` -> `get_file` | `RUNTIME_OBSERVED` vs `RUNTIME_UNOBSERVED` (`CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`, `NOT_OBSERVED_AT_RUNTIME`, `RUNTIME_ONLY_OBSERVED`). |
| **`DEBUG`** (Bug & exception investigation) | `get_context(intent="DEBUG")` | `get_file(path, start_line, end_line)` | Bounded `ContextPacket` (target + callers + callees + DI + database + runtime + tests) followed by targeted `get_file`. |
| **`DIAGNOSTIC`** (Index freshness & health) | `get_repository_status` | `get_resource_status` / `verify_evidence` | Index `generation`, `freshness` (`FRESH` vs `STALE`), `modified_files`, and SHA-256 evidence verification. |

## Epistemic Status Quick Reference

| Evidence / State | Meaning | Required Agent Behavior |
| :--- | :--- | :--- |
| **`AST_VERIFIED`** | Proven directly by syntax tree | Rely on relationship as verified static fact. |
| **`STATIC_VERIFIED`** | Proven by static SQL DDL/DML or migration parsing | Rely on table/column/query/migration relationship as verified static fact. |
| **`FRAMEWORK_VERIFIED`** | Proven by deterministic framework rules | Rely on route/ORM/DI/task/event relationship as verified framework fact. |
| **`DATAFLOW_VERIFIED`** | Proven by conservative local/container binding | Rely on resolved target as verified dataflow fact. |
| **`RUNTIME_OBSERVED`** | Observed in an ingested runtime trace (`observation_count >= 1`) | Treat as verified runtime execution fact; never promote to static `AST_VERIFIED` proof. |
| **`RUNTIME_UNOBSERVED`** | Not observed in the ingested runtime trace sample | Never claim the static path is dead code or impossible at runtime. |
| **`POSSIBLE`** | Plausible candidate, not statically guaranteed | Treat as lead; verify with targeted `get_file` / `read_file` before claiming as fact. |
| **`UNKNOWN`** | Static analysis could not prove target | **Never** claim "no relationship exists"; inspect call site with `get_file` / `read_file`. |
| **`AMBIGUOUS`** | Multiple symbols or tables match the target name | Inspect `alternatives` and disambiguate by module/package/schema; never pick `matches[0]` blindly. |
| **`STALE`** | Disk files changed since index generation | Verify `modified_files` with `get_file` / `read_file` or re-index (`codegraph index`). |
