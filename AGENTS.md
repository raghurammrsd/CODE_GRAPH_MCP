<!-- CODEGRAPH:START -->
# CodeGraph MCP Rules (AGENTS.md)

Target environment: `agents`. CodeGraph MCP (`codegraph mcp serve`) provides deterministic, local-first repository intelligence.

## CodeGraph Mental Model

- **Division of Labor**: The AI coding agent reasons, plans, and edits source code; CodeGraph interrogates the repository for AST-, framework-, and dataflow-verified facts.
- **Core Strength**: CodeGraph is preferred for relationship-heavy and multi-file repository questions (callers/callees, HTTP routes and router mounts, dependency injection, registries/dispatch, events/tasks/commands, test coverage, monorepo package boundaries, and change impact).

## Always-On Principles

1. **When to Use CodeGraph**: Use CodeGraph when repository relationships, multi-file reasoning, or literal text discovery make it materially useful—specifically for callers/callees, route-to-handler chains, dependency injection (`Depends`, providers, containers), task/command/event decorators, test coverage discovery, monorepo package boundaries, change-impact analysis, and literal text/template search (`search_code`).
2. **When Direct File Reading Is Sufficient (`LOCAL_EDIT`)**: Bypass CodeGraph graph queries for trivial single-file edits (typos, formatting, docstrings, or local variable changes inside an already-identified function). Use `get_file(path, start_line, end_line)` or `read_file` directly.
3. **Smallest-Sufficient-Tool Principle (`find_*`, `get_*`, `trace_*`)**: Pick the smallest tool that answers the question (`find_symbol`/`resolve_symbol` -> `find_callers`/`get_callers`, `find_routes`/`list_routes` -> `trace_path`, `search_code` -> `get_file`, or `get_context`). Stop as soon as verified evidence answers the question.
4. **Preserve Semantic Distinctions**: Never invent relationships and never collapse `REGISTERS`, `DISPATCHES_TO`, `MOUNTS`, `INJECTS`, `PROVIDES`, or `RESOLVES_DEPENDENCY` into generic `CALLS`. `search_code` returns literal text hits only and never creates semantic graph edges.
5. **Targeted Source Reads After Discovery (`get_file` / `read_file`)**: Once `search_code`, `find_symbol`, `find_routes`, or `get_context` identifies the target file and line range, call `get_file(path, start_line=..., end_line=..., max_lines=200)` (or `read_file`) to open only the needed lines.
6. **Anti-Loop Discipline**: Never call `resolve_symbol` or `find_symbol` repeatedly for the same symbol or spam redundant CodeGraph tools once a `canonical_id` or `ContextPacket` is obtained.

## Task-Specific Tool Selection

| Developer Question / Task Type | Recommended CodeGraph Tool Sequence |
| :--- | :--- |
| **Single-file local edit** (`LOCAL_EDIT`) | Bypass graph tools -> `get_file(path, start_line, end_line)` or `read_file` directly |
| **Where is symbol X defined?** (`SYMBOL_LOOKUP`) | `find_symbol(symbol=...)` or `resolve_symbol(symbol=...)` (or `search_symbols` if partial) -> `get_symbol` |
| **Where is literal text / HTML / UI string / config key?** | `search_code(query=...)` -> `get_file(path=..., start_line=..., end_line=...)` |
| **Who calls X / What does X call?** (`RELATIONSHIP`) | `find_callers(symbol=...)` / `get_callers(symbol=...)` or `find_callees(symbol=...)` / `get_callees(symbol=...)` |
| **Where is X referenced / registered / dispatched?** (`RELATIONSHIP`) | `find_references(symbol=...)` or `get_references(symbol=...)` |
| **Which HTTP route reaches handler Y?** (`ROUTE_DISCOVERY` / `TRACE`) | `find_routes` / `list_routes` -> `resolve_symbol` -> `trace_path` |
| **How does this bug / DI chain work?** (`DEBUG`) | `resolve_symbol` -> `get_context(query=..., intent="DEBUG")` |
| **What tests cover symbol X?** (`TEST_DISCOVERY`) | `find_tests(symbol=...)` or `find_related_tests(symbol=...)` |
| **What breaks if X or git diff changes?** (`CHANGE_IMPACT`) | `get_change_impact` or `get_git_impact` -> `find_tests` |
| **What changed structurally between commits / branches?** (`GIT_DIFF`) | `compare_git(base=..., head=..., branch_comparison=...)` -> `get_change_impact` |
| **Is repository index up to date with Git?** (`GIT_FRESHNESS`) | `get_git_state()` |
| **Is my compiled context still valid?** (`CONTEXT_FRESHNESS`) | `check_context_freshness(task=... or context_packet=...)` |
| **When was symbol X renamed / moved / introduced?** (`SYMBOL_HISTORY`) | `trace_symbol_history(symbol=..., path=...)` |
| **How are packages / modules structured?** (`ARCHITECTURE` / `PACKAGE`) | `get_architecture()` -> `get_context(query=..., intent="ARCHITECTURE")` |
| **Which database tables / columns / writers exist?** (`DATABASE`) | `find_db_tables` / `get_db_table` / `find_db_writers` / `get_db_impact` |
| **What happened at runtime vs static analysis?** (`RUNTIME`) | `get_runtime_trace` -> `reconcile_static_runtime` |
| **Where is feature Z implemented?** (`MULTI_FILE_INVESTIGATION`) | `search_symbols` / `search_code` -> `resolve_symbol` -> `get_context` |

## Epistemic & Fallback Rules (`UNKNOWN` / `POSSIBLE` / `AMBIGUOUS` / `RUNTIME_OBSERVED`)

- **Verified Evidence (`AST_VERIFIED`, `STATIC_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`)**: Rely on these relationships as proven static/framework/dataflow facts.
- **Runtime Evidence (`RUNTIME_OBSERVED` vs `RUNTIME_UNOBSERVED`)**: `RUNTIME_OBSERVED` records ingested trace edges; never convert it into static `AST_VERIFIED` proof, and never treat `NOT_OBSERVED_AT_RUNTIME` (`RUNTIME_UNOBSERVED`) as proof a path cannot execute.
- **How to Interpret `UNKNOWN`**: `UNKNOWN` means *static analysis could not establish the relationship* (e.g., dynamic `getattr`, `eval`, or runtime config). `UNKNOWN` **NEVER** means "there is no relationship." Inspect the cited call site with `get_file` or `read_file`.
- **How to Interpret `POSSIBLE`**: `POSSIBLE` indicates a plausible static candidate (such as conditional registration or interface implementation) that is not statically guaranteed. Verify the cited source lines with `get_file` or `read_file` before claiming as fact.
- **How to Handle `AMBIGUOUS`**: When `resolve_symbol` or `get_context` reports `AMBIGUOUS` with multiple candidates, inspect `alternatives` and disambiguate by module/package path—never pick `matches[0]` blindly.
- **Safe Fallback (`STALE` / `DISCONNECTED`)**: If CodeGraph MCP is disconnected, unavailable, or reports `freshness="STALE"`, fall back to targeted `get_file` / `read_file` / search and state the static limitation clearly.
<!-- CODEGRAPH:END -->
