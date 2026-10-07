---
name: codegraph
description: Deterministic repository relationship, route, dependency-injection, test-impact, package-boundary, literal text search, and bounded file inspection via CodeGraph MCP. Activate when a task involves multi-file code navigation, callers/callees, HTTP routes, DI providers, test discovery, change impact, or repository text/template discovery.
---

# CodeGraph Agent Skill

CodeGraph is a deterministic, local-first repository intelligence engine exposed via MCP (`codegraph mcp serve`).
Core operating principle:

    The AI Agent reasons.
    CodeGraph interrogates the repository.

End-to-end agent workflow:

    understand architecture (get_architecture / get_context)
        ↓
    find exact symbol or literal text (find_symbol / search_code / find_routes)
        ↓
    open targeted source lines (get_file)
        ↓
    reason with verified evidence (find_callers / find_callees / trace_path / find_tests)
        ↓
    edit the repository

---

## When to activate

Activate this skill whenever a developer task requires:
1. **Symbol & Definition Lookup (`SYMBOL_LOOKUP`)**: Locating canonical definitions of classes, functions, methods, or interfaces across a repository (`find_symbol`, `resolve_symbol`, `get_symbol`).
2. **Literal Text, UI, HTML/Jinja & Config Discovery (`search_code`)**: Locating button labels, HTML/Jinja template IDs, JS/TS snippets, CSS selectors, config keys, SQL fragments, or route strings across `.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, and `.md` files.
3. **Bounded Source File Inspection (`get_file`)**: Opening targeted line ranges (`start_line`, `end_line`, `max_lines`) or AST outlines of repository files without loading huge files into context.
4. **Caller / Callee & Reference Interrogation (`RELATIONSHIP`)**: Answering "Who calls X?" (`find_callers` / `get_callers`), "What does X call?" (`find_callees` / `get_callees`), or "Where is X referenced, imported, or registered?" (`find_references` / `get_references`).
5. **HTTP/RPC Route & Mount Composition (`ROUTE_DISCOVERY`)**: Locating FastAPI, Flask, Django, Express, or NestJS routes (`find_routes` / `list_routes`), especially when prefixes are composed via `MOUNTS` (`include_router`, `register_blueprint`, `app.use`).
6. **Multi-Hop Execution Tracing (`TRACE`)**: Proving how an entrypoint, route, CLI command, or background task reaches a downstream service or database query (`trace_path`, `trace_flow`).
7. **Dependency Injection & Configuration (`DEBUG` / DI)**: Tracing `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, and `DI_CYCLE` chains (`Depends(...)`, `Annotated[..., Depends(...)]`, container bindings).
8. **Registries, Dispatch, Events, Tasks & Commands**: Inspecting `REGISTERS`, `REGISTERED_HANDLER`, `DISPATCHES_TO`, `EVENT_LISTENER`, `TASK_HANDLER`, and `COMMAND_HANDLER` edges.
9. **Test Coverage Discovery (`TEST_DISCOVERY`)**: Finding tests statically linked to a symbol, route, provider, or event handler (`find_tests` / `find_related_tests` returning `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`).
10. **Blast Radius & Git Change Impact (`CHANGE_IMPACT`)**: Evaluating what callers, routes, workspace packages, and tests are impacted by modifying a symbol or commit range (`get_git_impact`, `analyze_impact`).
11. **Monorepo & Workspace Boundaries (`PACKAGE` / `ARCHITECTURE`)**: Inspecting manifest-backed workspace packages (`DEPENDS_ON_PACKAGE`, `CROSS_PACKAGE_IMPORT`, `PACKAGE_IMPORTS`, `CONTAINS_PACKAGE`) and system entrypoints (`get_architecture`).
12. **Multi-File Bug Investigation (`DEBUG` / `MULTI_FILE_INVESTIGATION`)**: Assembling a token-bounded, coverage-optimized `ContextPacket` via `get_context`.

---

## When NOT to activate

Do **NOT** call CodeGraph graph tools when:
1. **Trivial Single-File Local Edits (`LOCAL_EDIT`)**: Fixing a typo, editing a docstring or comment, adjusting formatting/indentation, or renaming a purely local variable inside a single already-known file and function. Use `get_file(path, start_line, end_line)` or `read_file` and standard editing tools directly.
2. **Canonical Evidence Is Already in Context**: If the current turn already resolved the symbol's `canonical_id`, callers, or `ContextPacket`, do not re-run the same CodeGraph tool.
3. **Sensitive Credential Files**: Never use CodeGraph, `get_file`, or `read_file` to inspect `.env`, `.pem`, `id_rsa`, or secret files (blocked by security policy).

---

## STEP 1 — Classify task

Classify the developer request into one of the 13 canonical categories (`AgentTaskCategory`) or explicit routing keys (`ROUTING_MANIFEST`):
- `LOCAL_EDIT`
- `SYMBOL_LOOKUP` (`symbol_discovery` -> `find_symbol` / `resolve_symbol`)
- `RELATIONSHIP` (`caller_discovery` -> `find_callers`, `callee_discovery` -> `find_callees`, `reference_discovery` -> `find_references`)
- `TRACE` (`relationship_trace` -> `trace_path` / `trace_flow`)
- `DEBUG` (`context_synthesis` -> `get_context`)
- `CHANGE_IMPACT` (`change_impact` -> `get_git_impact`)
- `TEST_DISCOVERY` (`test_discovery` -> `find_tests`)
- `ROUTE_DISCOVERY` (`route_discovery` -> `find_routes`)
- `DIAGNOSTIC` (`get_repository_status`)
- `ARCHITECTURE` (`architecture_analysis` -> `get_architecture`)
- `PACKAGE` (`get_architecture` / `get_context`)
- `MULTI_FILE_INVESTIGATION` (`literal_search` -> `search_code`, `source_inspection` -> `get_file`, or `get_context`)
- `EXPLANATION` (`context_synthesis` -> `get_context`)

---

## STEP 2 — Decide whether repository relationships or text search matter

- If the task is `LOCAL_EDIT` on a single known file: **stop here and use `get_file(path, start_line, end_line)` or `read_file` directly**.
- If searching for literal UI text, HTML/Jinja button IDs, CSS selectors, or config keys: call `search_code(query="...")` then open the matched lines with `get_file(path=..., start_line=..., end_line=...)`.
- If the task involves symbol definitions across files, callers/callees, routes, DI, registries, events, tasks, tests, packages, or impact: proceed to Step 3.

---

## STEP 3 — Ground the target

Before querying relationships, ground bare names into canonical repository identities:
- **Known symbol name**: Call `find_symbol(symbol="<symbol>")` or `resolve_symbol(symbol="<symbol>")` to obtain `canonical_id`, `file`, `start_line`, `end_line`, and `ambiguity_state`.
- **Partial or uncertain symbol name**: Call `search_symbols(query="<keyword>", top_k=10)` to discover candidate symbols, then select or resolve the canonical target.
- **Literal text / HTML template / UI label**: Call `search_code(query="<literal>", top_k=10)` to find exact `path`, `line`, and `matched_text`.
- **HTTP route path**: Call `find_routes(method="...", path="...")` or `list_routes(method="...", path="...")` to resolve composed mount prefixes (`MOUNTS`) and identify the handler's `canonical_id`.
- **Rule**: Never call `resolve_symbol` more than once for the same symbol in a session.

---

## STEP 4 — Choose the smallest sufficient tool

Select the smallest targeted tool that answers the question without over-fetching (all symbol-oriented tools accept `symbol=...` as canonical input and `canonical_id=...` as an explicit alias):
- **Symbol definition lookup**: `find_symbol(symbol=...)` or `resolve_symbol(symbol=...)`
- **Literal text / HTML / template / config search**: `search_code(query=..., top_k=10)`
- **Bounded file opening & AST outline**: `get_file(path=..., start_line=..., end_line=..., max_lines=200)`
- **Definition signature & decorators**: `get_symbol(symbol=...)`
- **Direct callers**: `find_callers(symbol=...)` or `get_callers(symbol=...)`
- **Direct callees**: `find_callees(symbol=...)` or `get_callees(symbol=...)`
- **All references / registrations / DI bindings**: `find_references(symbol=...)` or `get_references(symbol=...)`
- **Path between two known symbols**: `trace_path(from_symbol=..., to_symbol=..., max_depth=5)`
- **Bidirectional call flow around one symbol**: `trace_flow(symbol=..., depth=2)`
- **Forward module imports**: `get_imports(file=...)`
- **Reverse module/symbol dependents**: `get_dependents(symbol=...)`
- **Related test functions**: `find_tests(symbol=...)` or `find_related_tests(symbol=...)`
- **HTTP/RPC routes**: `find_routes(method=..., path=...)` or `list_routes(method=..., path=...)`
- **Symbol modification blast radius**: `analyze_impact(symbol=..., max_depth=3)`
- **Git commit diff impact**: `get_git_impact(base="HEAD~1", head="HEAD")`
- **Architecture & workspace packages**: `get_architecture()`
- **Multi-file debugging / DI / comprehensive task context**: `get_context(query=..., intent="DEBUG" | "TRACE" | "UNDERSTAND" | "IMPACT" | "ARCHITECTURE", max_tokens=4000, max_files=25, max_lines=500)` (`task=...` is also supported as an alias)

---

## STEP 5 — Retrieve structured evidence

Invoke the selected tool with exact schema arguments. Inspect the structured payload fields:
- `canonical_id`, `qualified_name`, `file` / `path`, `start_line`, `end_line`
- `relationship` (e.g., `CALLS`, `HANDLED_BY`, `MOUNTS`, `INJECTS`, `PROVIDES`, `REGISTERS`, `DISPATCHES_TO`, `DEPENDS_ON_PACKAGE`, `TESTS_SYMBOL`)
- `evidence_class` (`AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`)
- `confidence` (`HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`)
- `freshness` (`FRESH` vs `STALE`)

---

## STEP 6 — Interpret evidence

Respect CodeGraph's semantic and epistemic contract:
- **`AST_VERIFIED` / `FRAMEWORK_VERIFIED` / `DATAFLOW_VERIFIED`**: Proven static, framework, or conservative dataflow facts. Cite them directly with `file:start_line`.
- **Text Search != Semantic Graph**: `search_code` finds literal text matches across code, templates, and configs; it never proves semantic `CALLS`, `IMPORTS`, or `HANDLED_BY` edges.
- **`REGISTERS` != `CALLS`**: Registration into a dict or decorator registry proves `REGISTERS` / `REGISTERED_HANDLER`, not direct invocation. Invocation happens at `DISPATCHES_TO`.
- **DI != `CALLS`**: `INJECTS`, `PROVIDES`, and `RESOLVES_DEPENDENCY` express dependency injection wiring, not direct helper calls.
- **`MOUNTS` != `CALLS`**: Router prefix mounting is `MOUNTS`, connected to endpoints via `HANDLED_BY` / `ROUTE_HANDLER`.
- **Artifact Priority**: Prefer authored `SOURCE` and `TEST` files over `GENERATED`, `BUNDLE`, `MINIFIED`, or `VENDOR` artifacts.

---

## STEP 7 — Expand only when necessary

- If the first targeted tool (`find_callers`/`get_callers`, `find_routes`/`list_routes`, `find_tests`/`find_related_tests`, `trace_path`, `search_code`) already answers the developer's question with verified evidence, **STOP graph interrogation**.
- Expand with `get_context` or a follow-up relationship tool only if intermediate hops, DI providers, or package boundaries are still missing.

---

## STEP 8 — Targeted source read

CodeGraph tells you **WHERE** and **HOW** symbols or text relate; `get_file(path, start_line, end_line)` (or `read_file`) tells you **EXACTLY** what implementation statements exist.
- Call `get_file(path="<file>", start_line=<start>, end_line=<end>, max_lines=200)` on the exact line span returned by CodeGraph when:
  - You are about to edit a Python, HTML, Jinja, JS, TS, CSS, or config file.
  - You need to inspect conditional branch logic, HTML form fields, exception types, or literal values inside the file.
  - An edge is marked `POSSIBLE` or `UNKNOWN` and requires call-site verification.

---

## STEP 9 — Validate uncertainty

Never hide or launder epistemic uncertainty:
1. **`UNKNOWN` Workflow**:
    - `UNKNOWN` means static analysis could not establish the target (e.g., `getattr(obj, dynamic_attr)()`, `eval`, runtime config).
    - **Never** claim "no relationship exists" or "nothing calls X" from `UNKNOWN`.
    - Perform a targeted `get_file` / `read_file` on the cited call site; if still runtime-dependent, report it as statically `UNKNOWN`.
2. **`POSSIBLE` Workflow**:
    - Treat `POSSIBLE` / `POSSIBLE_CALLS` as a static lead (e.g., conditional registration or interface candidate).
    - Read the cited lines with `get_file` / `read_file` to confirm or reject before stating as fact.
3. **`AMBIGUOUS` Workflow**:
    - When `ambiguity_state == "AMBIGUOUS"`, inspect `alternatives`, compare `canonical_id`, owning package, and file path, and disambiguate using task context. Never blindly pick `alternatives[0]`.
4. **`STALE` Index Workflow**:
    - If `freshness == "STALE"`, one or more files in `modified_files` changed on disk since indexing. Verify modified files directly with `get_file` / `read_file` or run `codegraph index`.

---

## STEP 10 — Answer/edit

Synthesize the final answer or apply the code edit:
- Cite verified symbol names, relationship types, and `file:start_line` coordinates.
- Clearly distinguish verified facts (`AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`) from `POSSIBLE` leads or `UNKNOWN` dynamic boundaries.

---

## Tool selection matrix

| Task Category / Routing Intent | Primary Tool | Follow-Up Tool(s) | When to Use Targeted `get_file` / `read_file` |
| :--- | :--- | :--- | :--- |
| `LOCAL_EDIT` | `get_file` / `read_file` (Bypass Graph) | None | Immediately on the target file/lines |
| `SYMBOL_LOOKUP` (`symbol_discovery`) | `find_symbol` / `resolve_symbol` | `get_symbol` | Only if full implementation body beyond snippet is needed |
| `LITERAL_SEARCH` (`literal_search`) | `search_code` | `get_file(path, start_line, end_line)` | Immediately to inspect surrounding HTML/JS/Python lines |
| `RELATIONSHIP` (`caller_discovery`) | `find_callers` / `get_callers` | `get_file` | Only to inspect call-site argument expressions |
| `RELATIONSHIP` (`callee_discovery`) | `find_callees` / `get_callees` | `get_file` | Only to inspect branch conditions around calls |
| `RELATIONSHIP` (`reference_discovery`) | `find_references` / `get_references` | `get_file` | When checking conditional `REGISTERS` or `DISPATCHES_TO` sites |
| `ROUTE_DISCOVERY` (`route_discovery`) | `find_routes` / `list_routes` | `resolve_symbol` / `trace_path` | Only to inspect handler body statements |
| `TRACE` (`relationship_trace`) | `trace_path` / `trace_flow` | `get_context(intent="TRACE")` | When a hop is `POSSIBLE`/`UNKNOWN` or branch logic matters |
| `DEBUG` (`context_synthesis`) | `get_context(intent="DEBUG")` | `get_file` | On the exact fault or provider line span |
| `TEST_DISCOVERY` (`test_discovery`) | `find_tests` / `find_related_tests` | `get_file` | Only if test assertion details need inspection |
| `CHANGE_IMPACT` (`change_impact`) | `get_git_impact` / `analyze_impact` | `find_tests` | On direct callers that require signature updates |
| `PACKAGE` | `get_architecture` | `get_context(intent="ARCHITECTURE")` / `get_dependents` | Only if manifest version constraints need inspection |
| `ARCHITECTURE` (`architecture_analysis`) | `get_architecture` | `get_context(intent="ARCHITECTURE")` | Rarely needed for macro overview |
| `DATABASE` (`db_tables`, `db_writers`, `db_impact`) | `find_db_tables` / `get_db_table` | `find_db_writers` / `find_db_callers` / `get_db_impact` | On ORM model, SQL query, or migration file lines |
| `RUNTIME` (`runtime_trace`, `runtime_reconcile`) | `get_runtime_trace` / `reconcile_static_runtime` | `ingest_runtime_traces` / `get_file` | On `runtime_only_observed` or `static_runtime_conflicts` call sites |
| `DIAGNOSTIC` | `get_repository_status` | `get_resource_status` / `verify_evidence` | On `modified_files` if `freshness == "STALE"` |

---

## Evidence matrix

| Evidence Class | Meaning | Allowed Claim Strength | Required Agent Action |
| :--- | :--- | :--- | :--- |
| `AST_VERIFIED` | Directly proven by syntax tree (`DEFINES`, `CALLS`, `IMPORTS`, `EXTENDS`) | Verified Fact (`FACT`) | Cite directly; no extra verification required unless editing body. |
| `STATIC_VERIFIED` | Directly proven by static SQL DDL/DML or migration parsing (`CREATE TABLE`, `INSERT INTO`, `MIGRATES_TABLE`) | Verified Fact (`FACT`) | Cite with SQL/migration file and line coordinates. |
| `FRAMEWORK_VERIFIED` | Proven by deterministic framework rules (`HANDLED_BY`, `MOUNTS`, `INJECTS`, `PROVIDES`, `MAPS_TO_TABLE`, `TASK_HANDLER`, `EVENT_LISTENER`) | Verified Fact (`FACT`) | Cite with framework relationship type; never collapse into `CALLS`. |
| `DATAFLOW_VERIFIED` | Proven by conservative local/attribute/registry binding (`BINDS_TO`, `RESOLVES_DEPENDENCY`, `REGISTERS`, `DISPATCHES_TO`) | Verified Fact (`FACT`) | Cite with resolved target and binding location. |
| `ROJO_VERIFIED` | Proven by deterministic Rojo `default.project.json` DataModel-to-filesystem mapping (`REQUIRES_MODULE`) | Verified Fact (`FACT`) | Cite with virtual DataModel path and resolved physical file. |
| `RUNTIME_OBSERVED` | Observed in an ingested runtime trace (`observation_count`, `first_seen`, `last_seen`, `runtime_generation`) | Observed Runtime Fact | Cite as runtime observation; never promote into static `AST_VERIFIED` proof. |
| `RUNTIME_UNOBSERVED` | Static edge not observed in the ingested runtime trace sample (`NOT_OBSERVED_AT_RUNTIME`) | Unobserved in Sample | Never claim the path is dead code or impossible at runtime. |
| `POSSIBLE` | Plausible static candidate (`POSSIBLE_CALLS`, `POSSIBLE_TABLE`, conditional registration, multiple providers) | Candidate Lead (`POSSIBLE`) | Inspect cited lines via `get_file` / `read_file` before making a definitive claim. |
| `UNKNOWN` | Static analysis could not resolve target (`getattr`, `eval`, `UNKNOWN_TABLE`, dynamic dispatch) | Unresolved (`UNKNOWN`) | **Never** claim "no relationship exists"; read call site and report dynamic boundary. |
| `AMBIGUOUS` | Multiple candidate symbols or tables match the target name | Ambiguous (`AMBIGUOUS`) | Inspect `alternatives` and disambiguate by module/package/schema; never pick `alternatives[0]` blindly. |

---

## Relationship matrix

| Domain | Canonical Relationships | Key Rule |
| :--- | :--- | :--- |
| **Direct Calls** | `CALLS`, `CALLED_BY`, `POSSIBLE_CALLS` | `CALLS` is strictly `AST_VERIFIED`, `DATAFLOW_VERIFIED`, or `RUNTIME_OBSERVED`; uncertain static calls are `POSSIBLE_CALLS`. |
| **Routing & Mounts** | `MOUNTS`, `ROUTE_HANDLER`, `HANDLED_BY`, `ROUTES_TO` | Composes nested router prefixes (`include_router`, `app.use`); never collapsed into `CALLS`. |
| **Database & Persistence** | `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `READS_TABLE`, `WRITES_TABLE`, `READS_COLUMN`, `WRITES_COLUMN`, `REFERENCES_TABLE`, `REFERENCES_COLUMN`, `FOREIGN_KEY_TO`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `HAS_UNIQUE_CONSTRAINT`, `HAS_CHECK_CONSTRAINT`, `MIGRATES_TABLE`, `QUERIES_DATABASE`, `ORM_RELATION`, `POSSIBLE_TABLE`, `UNKNOWN_TABLE`, `READS_ENV` | Preserves explicit database schema, ORM, query, and migration semantics; never collapsed into generic `DEPENDS_ON`. |
| **Registries & Dispatch** | `REGISTERS`, `REGISTERED_HANDLER`, `DISPATCHES_TO` | `REGISTERS` records registration; `DISPATCHES_TO` records dispatcher-to-handler routing. |
| **Events, Tasks & Commands** | `EVENT_LISTENER`, `TASK_HANDLER`, `COMMAND_HANDLER` | Captures decorator/bus subscriptions for events, Celery/Dramatiq tasks, and CLI commands. |
| **Dependency Injection** | `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, `DI_CYCLE` | Traces consumer -> `INJECTS` -> provider -> `PROVIDES` -> implementation. |
| **Packages & Monorepo** | `DEPENDS_ON_PACKAGE`, `PACKAGE_IMPORTS`, `CROSS_PACKAGE_IMPORT`, `CONTAINS_PACKAGE` | Requires manifest proof (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`); never folder names alone. |
| **Test Coverage** | `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER` | Proven by static call, import, route client, or provider override; never lexical guessing. |
| **Structural & Binding** | `IMPORTS`, `EXPORTS`, `REEXPORTS`, `EXTENDS`, `IMPLEMENTS`, `DEFINES`, `CONTAINS`, `RESOLVES_TO`, `BINDS_TO`, `ALIASED_TO`, `REFERENCES`, `USES`, `DEPENDS_ON`, `UNRESOLVED_REFERENCE` | Structural AST containment, inheritance, exports, and conservative variable bindings. |

---

## Common workflows

1. **Trace HTTP Route to Database**:
   `find_routes(path="/api/v1/auth/login")` -> `find_symbol(symbol="login_endpoint")` -> `trace_path(from_symbol="login_endpoint", to_symbol="find_by_email")` -> `find_db_callers(table="users")` -> targeted `get_file` if branch details needed.
2. **Add UI + Backend Feature (HTML Template -> Route -> Service -> Tests)**:
   `get_architecture()` -> `search_code(query="Add Manual Entry")` -> `get_file(path="templates/dashboard.html", start_line=1, end_line=120)` -> `find_routes(path="/api/scan-bill")` -> `find_symbol(symbol="parse_bill")` -> `find_callers(symbol="parse_bill")` -> `find_tests(symbol="parse_bill")`.
3. **Database Schema, Writers & Bidirectional Impact Audit**:
   `find_db_tables()` -> `get_db_table(table="products")` -> `find_db_writers(table="products")` -> `get_db_impact(table="products", column="shop_id")`.
4. **Runtime Trace Ingestion & Static-vs-Runtime Reconciliation**:
   `ingest_runtime_traces(source_path="traces/otel.json")` -> `get_runtime_trace(route="/api/scan-bill")` -> `reconcile_static_runtime(route="/api/scan-bill")`.
5. **Inspect Dependency Injection Chain**:
   `resolve_symbol(symbol="get_current_user")` -> `get_context(query="DI chain for get_current_user", intent="DEBUG", max_tokens=4000)` -> inspect `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, and `DI_CYCLE`.
6. **Investigate Registry / Plugin Dispatch**:
   `resolve_symbol(symbol="command_registry")` -> `get_references(symbol="command_registry")` -> separate `REGISTERS` sites from `DISPATCHES_TO` sites.
7. **Pre-Refactor Impact & Test Selection**:
   `resolve_symbol(symbol="OrderRepository.save")` -> `analyze_impact(symbol="OrderRepository.save")` -> `find_tests(symbol="OrderRepository.save")` -> `get_file` on direct callers to update call sites.
8. **Monorepo Package Dependency Audit**:
   `get_architecture()` -> `get_context(query="package dependencies of @acme/orders", intent="ARCHITECTURE", max_tokens=4000)` -> inspect `DEPENDS_ON_PACKAGE` and `CROSS_PACKAGE_IMPORT`.

---

## Failure/fallback workflow

1. **MCP Server Disconnected or Unavailable**:
   - Fall back to workspace file search and targeted `read_file`. State clearly that static graph verification was unavailable.
2. **Index Freshness is `STALE`**:
   - Call `get_repository_status()` to see `modified_files`. Use `get_file` or `read_file` on any modified files before trusting cached graph edges, or run `codegraph index`.
3. **Target Resolution Returns `not_found`**:
   - Do not repeat `resolve_symbol` with the same string. Call `search_symbols(query="<stem>")`, `search_code(query="<literal>")`, or `find_routes()` to discover the actual identifier or file.
4. **Path Trace Returns Empty at Default Depth**:
   - Check if intermediate hops use DI (`INJECTS`/`PROVIDES`) or registry dispatch (`DISPATCHES_TO`) via `get_context(intent="TRACE")`, or inspect `unknowns` for dynamic dispatch boundaries.

---

## Stop conditions

Stop calling CodeGraph tools immediately when:
1. **Verified Answer Obtained**: The requested symbol definition, caller list, route handler, database table/writer, test list, literal text match, or trace path has been returned with `AST_VERIFIED`, `STATIC_VERIFIED`, `FRAMEWORK_VERIFIED`, or `DATAFLOW_VERIFIED` evidence.
2. **Single-File Local Scope Reached**: The remaining work is reading or editing specific lines inside an already-located file (`use get_file or read_file`).
3. **Dynamic Boundary Confirmed**: CodeGraph reported `UNKNOWN` (e.g., dynamic `getattr`/`eval` or `UNKNOWN_TABLE`) and you have read the call site with `get_file` / `read_file` to confirm the runtime-dependent expression.
4. **Maximum Sequence Bound**: Never exceed 3–4 CodeGraph tool calls for a single question without synthesizing findings.
