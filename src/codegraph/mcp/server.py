from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from codegraph.architecture import get_architecture as arch_get_architecture
from codegraph.config import Settings
from codegraph.context import _resolve_task_or_query_input
from codegraph.context import get_context as compile_context
from codegraph.database import (
    find_db_callers as db_find_db_callers,
)
from codegraph.database import (
    find_db_columns as db_find_db_columns,
)
from codegraph.database import (
    find_db_models as db_find_db_models,
)
from codegraph.database import (
    find_db_queries as db_find_db_queries,
)
from codegraph.database import (
    find_db_readers as db_find_db_readers,
)
from codegraph.database import (
    find_db_relationships as db_find_db_relationships,
)
from codegraph.database import (
    find_db_tables as db_find_db_tables,
)
from codegraph.database import (
    find_db_writers as db_find_db_writers,
)
from codegraph.database import (
    get_db_impact as db_get_db_impact,
)
from codegraph.database import (
    get_db_schema as db_get_db_schema,
)
from codegraph.database import (
    get_db_table as db_get_db_table,
)
from codegraph.errors import SecurityError
from codegraph.evidence import Evidence
from codegraph.evidence import verify_evidence as verify_evidence_fn
from codegraph.freshness import check_freshness
from codegraph.git import (
    analyze_change_impact as git_analyze_change_impact,
)
from codegraph.git import (
    changed_files,
)
from codegraph.git import (
    get_file_history as git_get_file_history,
)
from codegraph.graph import (
    analyze_impact as graph_analyze_impact,
)
from codegraph.graph import (
    definition_edges,
    import_edges,
)
from codegraph.graph import (
    find_callees as graph_find_callees,
)
from codegraph.graph import (
    find_callers as graph_find_callers,
)
from codegraph.graph import (
    find_related_tests as graph_find_related_tests,
)
from codegraph.graph import (
    get_call_graph as graph_get_call_graph,
)
from codegraph.graph import (
    get_symbol as graph_get_symbol,
)
from codegraph.graph import (
    trace_call as graph_trace_call,
)
from codegraph.indexing import Indexer
from codegraph.indexing.indexer import check_database_health
from codegraph.interrogation import (
    get_architecture as interrogation_get_architecture,
)
from codegraph.interrogation import (
    get_callees as interrogation_get_callees,
)
from codegraph.interrogation import (
    get_callers as interrogation_get_callers,
)
from codegraph.interrogation import (
    get_dependents as interrogation_get_dependents,
)
from codegraph.interrogation import (
    get_file as interrogation_get_file,
)
from codegraph.interrogation import (
    get_git_impact as interrogation_get_git_impact,
)
from codegraph.interrogation import (
    get_imports as interrogation_get_imports,
)
from codegraph.interrogation import (
    get_references as interrogation_get_references,
)
from codegraph.interrogation import (
    get_symbol as interrogation_get_symbol,
)
from codegraph.interrogation import (
    list_routes as interrogation_list_routes,
)
from codegraph.interrogation import (
    resolve_symbol as interrogation_resolve_symbol,
)
from codegraph.interrogation import (
    search_symbols as interrogation_search_symbols,
)
from codegraph.interrogation import (
    trace_path as interrogation_trace_path,
)
from codegraph.memory import MemoryStore
from codegraph.planner import build_retrieval_plan
from codegraph.resources import TaskPriority
from codegraph.runtime import (
    get_runtime_trace as runtime_get_runtime_trace,
)
from codegraph.runtime import (
    ingest_runtime_traces as runtime_ingest_runtime_traces,
)
from codegraph.runtime import (
    reconcile_static_runtime as runtime_reconcile_static_runtime,
)
from codegraph.search import search_code as search_code_repo
from codegraph.security import is_sensitive, safe_path, safe_read_text
from codegraph.task import normalize_task_spec


def _resolve_symbol_arg(
    symbol: str = "",
    canonical_id: str = "",
    name: str = "",
    tool_name: str = "tool",
) -> str:
    """Resolve canonical `symbol` parameter with backward-compatible `canonical_id`/`name` aliases."""
    provided: list[tuple[str, str]] = []
    if symbol and symbol.strip():
        provided.append(("symbol", symbol.strip()))
    if canonical_id and canonical_id.strip():
        provided.append(("canonical_id", canonical_id.strip()))
    if name and name.strip():
        provided.append(("name", name.strip()))

    if not provided:
        raise ValueError(
            f"{tool_name} requires a non-empty 'symbol' (or 'canonical_id' alias) argument."
        )

    distinct_values = {val for _, val in provided}
    if len(distinct_values) > 1:
        details = ", ".join(f"{k}={v!r}" for k, v in provided)
        raise ValueError(
            f"Conflicting symbol arguments passed to {tool_name} ({details}); "
            "provide 'symbol' or identical alias values."
        )

    return provided[0][1]


def create_server(
    repository: Path,
    settings: Settings | None = None,
    profile: str = "full",
) -> Any:
    """Build an MCP FastMCP server lazily so normal CLI use needs no MCP dependency."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support requires: pip install 'codegraph-engine[mcp]'") from exc

    from codegraph.agent_rules import render_agent_rules

    indexer = Indexer(repository, settings)
    memory = MemoryStore(indexer.db_path)
    app = FastMCP("CodeGraph MCP", instructions=render_agent_rules("antigravity"))
    max_read_bytes = indexer.settings.max_read_bytes

    # -----------------------------------------------------------------------
    # Tool Handlers
    # -----------------------------------------------------------------------

    def search_code(
        query: str,
        top_k: int = 10,
        path_filter: str | None = None,
        file_types: list[str] | None = None,
        include_tests: bool = True,
        include_configs: bool = True,
        max_results: int = 20,
    ) -> list[dict[str, object]]:
        """Search literal text, strings, UI labels, HTML/Jinja templates, JS/TS/CSS/Python files, config keys, SQL fragments, and error messages across the repository. USE THIS when the target is NOT a known code symbol (e.g., 'Add Manual Entry', 'scanBtn', 'GROQ_API_KEY'). DO NOT use this for callers, callees, imports, or symbol definitions—use find_callers, find_callees, get_imports, or find_symbol instead. Returns deterministic text hits (`path`, `line`, `matched_text`, `snippet`, `file_category`); never fabricates semantic graph relationships."""
        effective_limit = top_k if (top_k != 10 and max_results == 20) else (
            max_results if max_results != 20 else top_k
        )
        if not query.strip() or not 1 <= effective_limit <= 100:
            raise ValueError("query must be non-empty and top_k must be 1..100")
        with indexer.session() as con:
            return search_code_repo(
                con,
                query,
                repo_path=indexer.repository,
                path_filter=path_filter,
                file_types=file_types,
                include_tests=include_tests,
                include_configs=include_configs,
                max_results=effective_limit,
            )

    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> dict[str, object]:
        """Read a bounded line range (1..500 lines) of a non-sensitive repository file. Use AFTER CodeGraph tools identify the exact file and line span, or directly for trivial single-file edits. Blocks path traversal, sensitive credential files, binary files, and files exceeding max_read_bytes. Does not compute cross-file callers, DI bindings, or test links."""
        if start_line < 1 or end_line < start_line or end_line - start_line > 500:
            raise ValueError("line range must be 1..500 lines")
        _, rel_posix, text = safe_read_text(
            indexer.repository,
            path,
            max_read_bytes=max_read_bytes,
        )
        lines = text.splitlines()
        return {
            "file": rel_posix,
            "path": rel_posix,
            "start_line": start_line,
            "end_line": min(end_line, len(lines)),
            "content": "\n".join(lines[start_line - 1 : end_line]),
            "truncated": end_line < len(lines) or start_line > 1,
        }

    def find_symbol(
        symbol: str = "",
        name: str = "",
        canonical_id: str = "",
    ) -> list[dict[str, object]]:
        """Find function, method, or class definitions by `symbol` (or `name` / `canonical_id` alias). USE THIS INSTEAD OF grep/search_code when asking 'where is symbol X defined?'. DO NOT use search_code for symbol definition lookup. Returns AST-verified symbol definitions (`symbol`, `kind`, `file`, `start_line`, `end_line`). Does not return callers or dependency relationships."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="find_symbol"
        )
        with indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name AS symbol,kind,path AS file,start_line,end_line "
                "FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? ORDER BY path,start_line LIMIT 100",
                (target, target, target),
            )
            return [dict(row) for row in rows]

    def get_symbol(
        symbol: str = "",
        canonical_id: str = "",
        name: str = "",
    ) -> dict[str, object]:
        """Get authoritative details for a single symbol by `symbol` (or `canonical_id` alias). Use to inspect symbol declaration metadata. Does not traverse multi-hop call graphs."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="get_symbol"
        )
        with indexer.session() as con:
            sym = graph_get_symbol(con, target)
            if not sym:
                return {"error": f"Symbol not found: {target}"}
            return sym.as_dict()

    def find_references(
        symbol: str = "",
        name: str = "",
        canonical_id: str = "",
    ) -> list[dict[str, object]]:
        """Find textual references across indexed chunks by `symbol` (or `name` / `canonical_id` alias); use get_references for canonical evidence-backed symbol references. USE THIS when checking where a symbol identifier is mentioned across files. Results are explicitly not guaranteed semantic call edges."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="find_references"
        )
        short = target.split(":")[-1].split(".")[-1]
        with indexer.session() as con:
            return [
                dict(row)
                for row in con.execute(
                    "SELECT path AS file,symbol,start_line,end_line FROM chunks WHERE content LIKE ? ORDER BY path,start_line LIMIT 100",
                    (f"%{short}%",),
                )
            ]

    def find_callers(
        symbol: str = "",
        canonical_id: str = "",
        max_results: int = 20,
    ) -> list[dict[str, object]]:
        """Find functions and methods that call the specified `symbol` (accepts symbol name, qualified name, or `canonical_id` alias). USE THIS INSTEAD OF grep/search_code when asking 'who calls X?'. DO NOT use search_code for caller discovery. Returns verified `CALLS` and candidate `POSSIBLE_CALLS` with `confidence` and `evidence_class` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`). Does not prove runtime execution of conditional branches."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="find_callers"
        )
        with indexer.session() as con:
            return [dict(r) for r in graph_find_callers(con, target, max_results=max_results)]

    def find_callees(
        symbol: str = "",
        canonical_id: str = "",
        max_results: int = 20,
    ) -> list[dict[str, object]]:
        """Find functions and methods called by the specified `symbol` (accepts symbol name, qualified name, or `canonical_id` alias). USE THIS INSTEAD OF reading multiple files manually when asking 'what does X call?'. DO NOT use search_code for callee discovery. Returns verified `CALLS` and candidate `POSSIBLE_CALLS` with `confidence` and `evidence_class` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`). Does not resolve dynamic string-based callbacks."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="find_callees"
        )
        with indexer.session() as con:
            return [dict(r) for r in graph_find_callees(con, target, max_results=max_results)]

    def get_call_graph(
        symbol: str = "",
        canonical_id: str = "",
        depth: int = 2,
        max_results: int = 100,
    ) -> list[dict[str, object]]:
        """Compute the multi-hop call graph rooted at `symbol` (or `canonical_id` alias) up to `depth`. Use when visualizing neighborhood call structure. Does not prove runtime reachability."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="get_call_graph"
        )
        with indexer.session() as con:
            return [dict(e) for e in graph_get_call_graph(con, symbol=target, depth=depth, max_results=max_results)]

    def get_dependency_graph(file_path: str | None = None) -> list[dict[str, object]]:
        """List module import and dependency graph edges. Use for inspecting module-to-module import structure. Does not prove symbol-level call invocation."""
        with indexer.session() as con:
            if file_path:
                rows = con.execute(
                    "SELECT source, target, relationship, confidence, evidence FROM graph_edges WHERE relationship='IMPORTS' AND (source=? OR file=?) ORDER BY source",
                    (file_path, file_path),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT source, target, relationship, confidence, evidence FROM graph_edges WHERE relationship='IMPORTS' ORDER BY source LIMIT 500"
                ).fetchall()
            return [dict(r) for r in rows]

    def find_related_tests(
        symbol: str = "",
        canonical_id: str = "",
        max_results: int = 10,
    ) -> list[dict[str, object]]:
        """Return test files and test functions statically linked to `symbol` (or `canonical_id` alias) via direct calls, imports, fixtures, or route invocation. USE THIS INSTEAD OF grep/search_code when asking 'what tests cover symbol X?' before or after a code change. Never fabricates coverage from lexical similarity alone."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="find_related_tests"
        )
        with indexer.session() as con:
            return [dict(r) for r in graph_find_related_tests(con, target, max_results=max_results)]

    def find_tests(
        symbol: str = "",
        canonical_id: str = "",
        max_results: int = 10,
    ) -> list[dict[str, object]]:
        """Find test files and test functions statically linked to `symbol` (or `canonical_id` alias) via direct calls, imports, fixtures, or route invocation. USE THIS INSTEAD OF grep/search_code when asking 'what tests cover X?'. DO NOT guess test coverage from filename similarity alone. Returns verified test links (`TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`) with `confidence` and `evidence_class`."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="find_tests"
        )
        with indexer.session() as con:
            return [dict(r) for r in graph_find_related_tests(con, target, max_results=max_results)]

    def analyze_impact(
        symbol: str = "",
        canonical_id: str = "",
        max_depth: int = 3,
    ) -> dict[str, object]:
        """Compute downstream callers, dependents, affected routes, and related tests if `symbol` (or `canonical_id` alias) is modified. Use before refactoring or changing a function/class signature. Does not prove runtime failure without inspecting call sites."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="analyze_impact"
        )
        with indexer.session() as con:
            return graph_analyze_impact(con, target, max_depth=max_depth)

    def compile_task(
        query: str = "",
        task: dict[str, Any] | str = "",
        max_tokens: int = 20_000,
        resource_mode: str = "BALANCED",
    ) -> dict[str, object]:
        """Normalize a `query` (or `task` alias), ground targets against repository symbols, detect ambiguities, and build a RetrievalPlan. Use before get_context when explicit ambiguity pre-checking is desired. Does not execute source retrieval."""
        effective_task = _resolve_task_or_query_input(task=task, query=query)
        with indexer.session() as con:
            spec, ambiguities = normalize_task_spec(effective_task, con)
            plan = build_retrieval_plan(
                spec,
                ambiguities,
                con,
                token_budget=max_tokens,
                resource_mode=resource_mode,
            )
            entry_points: list[str] = []
            for t in spec.priority_targets or spec.targets:
                r_rows = con.execute(
                    "SELECT endpoint_id, handler_name FROM framework_routes WHERE route_path LIKE ? OR endpoint_id LIKE ?",
                    (f"%{t}%", f"%{t}%"),
                ).fetchall()
                for r in r_rows:
                    entry_points.append(r["endpoint_id"] or r["handler_name"])
            amb_list = [a.as_dict() for a in ambiguities]
            return {
                "task_spec": spec.as_dict(),
                "ambiguity": amb_list[0] if amb_list else None,
                "ambiguities": amb_list,
                "entry_points": entry_points,
                "candidate_entry_points": entry_points,
                "retrieval_plan": plan.as_dict(),
                "recommended_next_step": "get_context",
            }

    def plan_retrieval(
        query: str = "",
        task: dict[str, Any] | str = "",
        max_tokens: int = 20_000,
        resource_mode: str = "BALANCED",
    ) -> dict[str, object]:
        """Construct a deterministic RetrievalPlan for a `query` (or `task` alias) without executing retrieval. Use to preview planned search and graph steps. Does not return code snippets."""
        effective_task = _resolve_task_or_query_input(task=task, query=query)
        with indexer.session() as con:
            spec, ambiguities = normalize_task_spec(effective_task, con)
            plan = build_retrieval_plan(
                spec,
                ambiguities,
                con,
                token_budget=max_tokens,
                resource_mode=resource_mode,
            )
            return plan.as_dict()

    def get_context(
        query: str = "",
        task: dict[str, Any] | str = "",
        intent: str | None = None,
        max_tokens: int = 4000,
        max_files: int = 15,
        max_lines: int = 500,
        top_k: int = 15,
        plan: dict[str, Any] | None = None,
        mode: str = "BALANCED",
        explain: bool = False,
        resource_mode: str | None = None,
    ) -> dict[str, object]:
        """Compile a token-bounded, coverage-optimized ContextPacket for a `query` (or `task` alias: natural-language question, symbol/route target, or structured TaskSpec). Enforces strict pre-serialization boundaries (`max_tokens`, `max_files`, `max_lines`) and returns explicit budget metadata (`selected_tokens`, `candidate_tokens`, `selected_files`, `selected_lines`, `coverage_score`, `truncated`). Example: `get_context(query="Trace InventoryService.place_order callers and tests", intent="TRACE", max_tokens=4000, max_files=10, max_lines=300)`."""
        effective_task = _resolve_task_or_query_input(task=task, query=query)
        effective_mode = resource_mode or mode
        with indexer.session() as con:
            packet = compile_context(
                con,
                indexer.repository,
                task=effective_task,
                intent=intent,
                max_tokens=max_tokens,
                max_files=max_files,
                max_lines=max_lines,
                top_k=top_k,
                plan=plan,
                mode=effective_mode,
                explain=explain,
            )
            return packet.as_dict()

    def get_recent_changes(
        since: str = "HEAD~10",
        until: str = "HEAD",
    ) -> list[dict[str, str]]:
        """Return files changed between two commits or refs (read-only, sandboxed)."""
        diffs = changed_files(indexer.repository, since=since, until=until)
        return [d.as_dict() for d in diffs]

    def get_file_history(
        path: str,
        n: int = 10,
    ) -> list[dict[str, str]]:
        """Return recent commits touching the specified repository file."""
        return git_get_file_history(indexer.repository, path, n=n)

    def analyze_change_impact(
        since: str = "HEAD~1",
        until: str = "HEAD",
    ) -> dict[str, object]:
        """Analyze downstream callers and tests affected by changes between since and until."""
        with indexer.session() as con:
            return git_analyze_change_impact(con, indexer.repository, since=since, until=until)

    def get_repository_status() -> dict[str, object]:
        """Get repository indexing status, freshness, symbol counts, and health (automatically hot-reloads in-memory caches when `.codegraph.sqlite3` is created or updated by `codegraph init` / `codegraph index`)."""
        from codegraph.resources.cache import get_graph_cache, get_parse_cache

        get_graph_cache().clear()
        get_parse_cache().clear()
        if not indexer.db_path.exists():
            return {
                "status": "error",
                "repository": str(indexer.repository),
                "generation": 0,
                "freshness": "NOT_INDEXED",
                "freshness_detail": "No CodeGraph index exists for this repository.",
                "files": 0,
                "files_indexed": 0,
                "symbols": 0,
                "symbols_indexed": 0,
                "graph_edges": 0,
                "framework_routes": 0,
                "reloaded": True,
                "error": {
                    "code": "INDEX_NOT_FOUND",
                    "message": "No CodeGraph index exists for this repository.",
                    "next_action": {
                        "command": "codegraph init",
                        "reason": "Initialize the repository before querying it.",
                    },
                },
            }
        with indexer.session() as con:
            report = check_freshness(indexer.repository, con)
            file_count = int(con.execute("SELECT count(*) FROM files").fetchone()[0])
            symbol_count = int(con.execute("SELECT count(*) FROM symbols").fetchone()[0])
            edge_count = int(con.execute("SELECT count(*) FROM graph_edges").fetchone()[0])
            route_count = int(con.execute("SELECT count(*) FROM framework_routes").fetchone()[0])
            if file_count == 0:
                return {
                    "status": "error",
                    "repository": str(indexer.repository),
                    "generation": report.index_generation,
                    "freshness": "NOT_INDEXED",
                    "freshness_detail": "No files are indexed in this repository.",
                    "files": 0,
                    "files_indexed": 0,
                    "symbols": 0,
                    "symbols_indexed": 0,
                    "graph_edges": 0,
                    "framework_routes": 0,
                    "reloaded": True,
                    "error": {
                        "code": "INDEX_NOT_FOUND",
                        "message": "No CodeGraph index exists for this repository.",
                        "next_action": {
                            "command": "codegraph init",
                            "reason": "Initialize the repository before querying it.",
                        },
                    },
                }
            return {
                "status": "ok",
                "repository": str(indexer.repository),
                "generation": report.index_generation,
                "freshness": report.status.value,
                "freshness_detail": report.detail,
                "files": file_count,
                "files_indexed": file_count,
                "symbols": symbol_count,
                "symbols_indexed": symbol_count,
                "graph_edges": edge_count,
                "framework_routes": route_count,
                "modified_files": report.modified_files,
                "deleted_files": report.deleted_files,
                "parse_failed_files": report.parse_failed_files,
                "reloaded": True,
            }

    def trace_call(
        symbol: str = "",
        canonical_id: str = "",
        depth: int = 2,
        callers: bool = True,
        callees: bool = False,
        both: bool = False,
    ) -> list[dict[str, object]]:
        """Trace known definition, callers, and callees for `symbol` (or `canonical_id` alias) with explicit confidence and relationship labels. USE THIS when exploring the call neighborhood around a single symbol. Does not prove runtime execution of conditional branches."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="trace_call"
        )
        with indexer.session() as con:
            return graph_trace_call(con, target, max_depth=depth, callers=callers, callees=callees, both=both)

    def trace_flow(
        symbol: str = "",
        canonical_id: str = "",
        depth: int = 2,
        callers: bool = True,
        callees: bool = False,
        both: bool = False,
    ) -> list[dict[str, object]]:
        """Trace multi-hop upstream callers and downstream callees for `symbol` (or `canonical_id` alias) up to `depth`. USE THIS when exploring the bidirectional call flow around a single symbol. Returns verified and candidate call hops with explicit `confidence` and `evidence_class`. Does not prove runtime execution of conditional branches."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="trace_flow"
        )
        with indexer.session() as con:
            return graph_trace_call(con, target, max_depth=depth, callers=callers, callees=callees, both=both)

    def get_project_structure() -> list[str]:
        """List indexed source paths only."""
        with indexer.session() as con:
            return [r[0] for r in con.execute("SELECT path FROM files ORDER BY path LIMIT 500")]

    def get_dependencies() -> list[dict[str, str]]:
        """List source imports as static evidence, without resolving external packages."""
        with indexer.session() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT source_path,imported FROM imports ORDER BY source_path,imported LIMIT 500"
                )
            ]

    def get_file_symbols(path: str) -> list[dict[str, object]]:
        """List extracted symbols in one repository-relative file."""
        resolved = safe_path(indexer.repository, path)
        relative = resolved.relative_to(indexer.repository).as_posix()
        with indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name AS symbol,kind,start_line,end_line FROM symbols "
                "WHERE path=? ORDER BY start_line LIMIT 200",
                (relative,),
            )
            return [dict(row) for row in rows]

    def get_graph(limit: int = 200) -> list[dict[str, object]]:
        """Return bounded parser-confirmed file/symbol/import graph edges with evidence metadata."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        with indexer.session() as con:
            edges = definition_edges(con, limit) + import_edges(con)
        return [edge.as_dict() for edge in edges[:limit]]

    def search_memory(query: str, limit: int = 20) -> list[dict[str, str]]:
        """Search local repository memory. Memory never overrides current source evidence."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        return [{"key": key, "value": value} for key, value in memory.search(query, limit)]

    def get_evidence(path: str, symbol: str | None = None) -> list[dict[str, object]]:
        """Return source-derived evidence for a safe indexed file, optionally narrowed to one symbol."""
        resolved = safe_path(indexer.repository, path)
        relative = resolved.relative_to(indexer.repository)
        if is_sensitive(relative):
            raise SecurityError("sensitive files cannot be used as evidence")
        with indexer.session() as con:
            if symbol:
                rows = con.execute(
                    "SELECT symbol,start_line,end_line,content FROM chunks WHERE path=? AND symbol=? LIMIT 20",
                    (relative.as_posix(), symbol),
                )
            else:
                rows = con.execute(
                    "SELECT symbol,start_line,end_line,content FROM chunks WHERE path=? ORDER BY start_line LIMIT 50",
                    (relative.as_posix(),),
                )
            return [
                Evidence(
                    relative.as_posix(),
                    row["start_line"],
                    row["start_line"] if row["end_line"] is None else row["end_line"],
                    row["symbol"],
                    row["content"][:900],
                ).as_dict()
                for row in rows
            ]

    def verify_evidence(
        file_path: str,
        start_line: int,
        end_line: int,
        expected_hash: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, object]:
        """Verify that a cited piece of evidence or code snippet actually exists, matches disk hash, and remains valid."""
        ev = Evidence(
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            symbol=symbol,
            snippet="",
        )
        with indexer.session() as con:
            res = verify_evidence_fn(con, indexer.repository, ev, expected_content_hash=expected_hash)
            return res.as_dict()

    def get_resource_status() -> dict[str, object]:
        """Inspect current resource governor state, memory usage, pressure, and activity mode."""
        return indexer.governor.get_state().as_dict()

    # -----------------------------------------------------------------------
    # Core Deterministic Interrogation Tools (13 Core Capabilities)
    # -----------------------------------------------------------------------

    def resolve_symbol(
        symbol: str = "",
        canonical_id: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        """Resolve a `symbol` (or `canonical_id` / `name` alias) into its canonical repository identity and file/line location. Use as the first step before relationship queries when exact symbol identity is unknown or potentially ambiguous. Returns canonical_id, ambiguity_state, and candidate alternatives. Does not prove runtime execution or dynamic monkey-patching."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="resolve_symbol"
        )
        with indexer.session() as con:
            return interrogation_resolve_symbol(con, indexer.repository, symbol=target)

    def search_symbols(query: str, top_k: int = 20) -> dict[str, Any]:
        """Search indexed repository symbols by partial name or keyword with ranked relevance. Use when exact symbol spelling is unknown and you need candidate symbol definitions. Returns ranked symbol definitions with file paths and line spans. Does not return module import graphs or call relationships (use get_imports or get_dependents instead)."""
        with indexer.session() as con:
            return interrogation_search_symbols(con, indexer.repository, query, top_k=top_k)

    def get_symbol_interrogation_wrapper(
        symbol: str = "",
        canonical_id: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        """Return authoritative signature, kind, parent scope, decorators, and bounded source snippet for `symbol` (or `canonical_id` alias). Use when you have a symbol name, qualified name, or canonical_id and need its declaration metadata. Does not traverse multi-hop call graphs."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="get_symbol"
        )
        with indexer.session() as con:
            return interrogation_get_symbol(con, indexer.repository, symbol=target)

    def get_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        max_lines: int = 200,
        include_content: bool = False,
    ) -> dict[str, Any]:
        """Read bounded source lines (`start_line`, `end_line`, `max_lines`) and structural AST outline of a repository file (`.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, `.md`). USE THIS after search_code, find_symbol, or find_routes identifies a target file and line range. DO NOT read entire huge files blindly when a targeted line range is known. Returns `path`, `start_line`, `end_line`, `content`, `truncated`, and AST symbols while blocking sensitive files and path traversal."""
        with indexer.session() as con:
            return interrogation_get_file(
                con,
                indexer.repository,
                path,
                include_content=include_content,
                max_read_bytes=max_read_bytes,
                start_line=start_line,
                end_line=end_line,
                max_lines=max_lines,
            )

    def get_references(
        symbol: str = "",
        canonical_id: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        """Return verified and candidate references to `symbol` (or `canonical_id` alias) across the repository with evidence_class labels. Use for cross-file reference, registration, dispatch, or DI binding lookup. Does not guarantee dynamic reflection targets when evidence_class is UNKNOWN or POSSIBLE."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, name=name, tool_name="get_references"
        )
        with indexer.session() as con:
            return interrogation_get_references(con, indexer.repository, symbol=target)

    def get_callers(
        symbol: str = "",
        canonical_id: str = "",
    ) -> dict[str, Any]:
        """Return statically verified and candidate callers of `symbol` (accepts symbol name, qualified name, or `canonical_id` alias) with confidence and evidence_class. USE THIS INSTEAD OF grep/search_code for multi-file call-relationship and upstream impact questions. Does not prove runtime dispatch unless evidence_class indicates framework/dataflow verification."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="get_callers"
        )
        with indexer.session() as con:
            return interrogation_get_callers(con, indexer.repository, symbol=target)

    def get_callees(
        symbol: str = "",
        canonical_id: str = "",
    ) -> dict[str, Any]:
        """Return symbols called or invoked by `symbol` (accepts symbol name, qualified name, or `canonical_id` alias) with evidence_class classification. USE THIS INSTEAD OF reading multiple files manually to inspect downstream dependencies invoked by a function or handler. Does not resolve dynamic callbacks passed as opaque runtime arguments."""
        target = _resolve_symbol_arg(
            symbol=symbol, canonical_id=canonical_id, tool_name="get_callees"
        )
        with indexer.session() as con:
            return interrogation_get_callees(con, indexer.repository, symbol=target)

    def trace_path(
        from_symbol: str = "",
        to_symbol: str = "",
        start_symbol: str = "",
        target_symbol: str = "",
        source_symbol: str = "",
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """Compute deterministic multi-hop relationship paths between two symbols (`from_symbol` -> `to_symbol`). USE THIS INSTEAD OF manual file-by-file hopping when tracing how an entrypoint, route, or caller reaches a downstream service or database function. Returns ordered hop edges with relationship types and `evidence_class` (`AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`). Does not prove runtime branch conditions along the path."""
        src = _resolve_symbol_arg(
            symbol=from_symbol,
            canonical_id=start_symbol,
            name=source_symbol,
            tool_name="trace_path(from_symbol)",
        )
        tgt = _resolve_symbol_arg(
            symbol=to_symbol,
            canonical_id=target_symbol,
            tool_name="trace_path(to_symbol)",
        )
        with indexer.session() as con:
            return interrogation_trace_path(con, indexer.repository, src, tgt, max_depth=max_depth)

    def get_imports(
        symbol: str | None = None,
        file: str | None = None,
        canonical_id: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Return parser-extracted module and symbol imports for `file` (or `path` alias) or `symbol` (or `canonical_id` alias). Use for forward dependency and package boundary questions. Does not return reverse importers (use get_dependents for reverse dependencies)."""
        if symbol and canonical_id and symbol.strip() and canonical_id.strip() and symbol.strip() != canonical_id.strip():
            raise ValueError(f"Conflicting symbol arguments passed to get_imports: symbol={symbol!r}, canonical_id={canonical_id!r}")
        if file and path and file.strip() and path.strip() and file.strip() != path.strip():
            raise ValueError(f"Conflicting file arguments passed to get_imports: file={file!r}, path={path!r}")
        eff_sym = (symbol or canonical_id or "").strip() or None
        eff_file = (file or path or "").strip() or None
        if not eff_sym and not eff_file:
            raise ValueError("get_imports requires at least one of 'symbol' ('canonical_id') or 'file' ('path').")
        with indexer.session() as con:
            return interrogation_get_imports(con, indexer.repository, file=eff_file, canonical_id=eff_sym, symbol=eff_sym, path=eff_file)

    def get_dependents(
        symbol: str | None = None,
        file: str | None = None,
        canonical_id: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Return files, symbols, and packages that import or depend on `symbol` (or `canonical_id` alias) or `file` (or `path` alias). Use for blast-radius, change-impact, and package boundary analysis. Does not prove runtime failure without checking test and caller evidence."""
        if symbol and canonical_id and symbol.strip() and canonical_id.strip() and symbol.strip() != canonical_id.strip():
            raise ValueError(f"Conflicting symbol arguments passed to get_dependents: symbol={symbol!r}, canonical_id={canonical_id!r}")
        if file and path and file.strip() and path.strip() and file.strip() != path.strip():
            raise ValueError(f"Conflicting file arguments passed to get_dependents: file={file!r}, path={path!r}")
        eff_sym = (symbol or canonical_id or "").strip() or None
        eff_file = (file or path or "").strip() or None
        if not eff_sym and not eff_file:
            raise ValueError("get_dependents requires at least one of 'symbol' ('canonical_id') or 'file' ('path').")
        with indexer.session() as con:
            return interrogation_get_dependents(con, indexer.repository, canonical_id=eff_sym, file=eff_file, symbol=eff_sym, path=eff_file)

    def list_routes(
        framework: str | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Return HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols. USE THIS INSTEAD OF grep/search_code when locating API endpoints, route handlers, or mounted sub-applications. Does not prove runtime middleware authentication unless traced via get_context or trace_path."""
        with indexer.session() as con:
            return interrogation_list_routes(con, indexer.repository, framework=framework, method=method, path=path)

    def find_routes(
        framework: str | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Find HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols. USE THIS INSTEAD OF grep/search_code when asking 'which route handles /path?' or listing API endpoints. DO NOT grep for split router prefix strings. Returns `route_path`, `http_method`, `handler_name`, `canonical_id`, `file`, `line`, and `evidence_class` (`FRAMEWORK_VERIFIED`). Does not prove runtime middleware state."""
        with indexer.session() as con:
            return interrogation_list_routes(con, indexer.repository, framework=framework, method=method, path=path)

    def get_architecture() -> dict[str, Any]:
        """Return structural repository overview including modules, workspace packages (`DEPENDS_ON_PACKAGE`), entrypoints, and layer relationships. Use for high-level architecture, monorepo package boundary, and onboarding questions. Does not replace symbol-level evidence for specific bug fixes."""
        with indexer.session() as con:
            return interrogation_get_architecture(con, indexer.repository)

    def get_git_impact(base: str = "HEAD~1", head: str = "HEAD") -> dict[str, Any]:
        """Compute deterministic change impact between Git refs (`base`..`head`), including modified symbols, downstream callers, affected packages, and covering tests. Use for PR review, regression analysis, and pre-commit blast-radius checks. Does not execute tests; reports static test-to-symbol coverage edges."""
        with indexer.session() as con:
            return interrogation_get_git_impact(con, indexer.repository, base=base, head=head)

    # -----------------------------------------------------------------------
    # Database Deep Intelligence Tools (11 Tools)
    # -----------------------------------------------------------------------

    def find_db_tables(table: str = "", dialect: str = "", schema: str = "") -> dict[str, Any]:
        """Find database tables discovered across ORM models, raw SQL queries, and migrations. Use instead of grep when asking 'which database tables exist in this repository?'. Returns canonical IDs (`db.<dialect>.<schema>.<table>`), columns, ORM models, and evidence classes (`FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`, `POSSIBLE`, `UNKNOWN`). Does not connect to live databases or execute SQL."""
        with indexer.session() as con:
            return db_find_db_tables(con, indexer.repository, table=table, dialect=dialect, schema=schema)

    def find_db_columns(table: str = "", column: str = "") -> dict[str, Any]:
        """Find database columns, data types, nullability, primary keys, and foreign keys across tables and ORM models. Use instead of grep when locating where a table column is defined or mapped (`MAPS_TO_COLUMN`, `HAS_PRIMARY_KEY`, `FOREIGN_KEY_TO`). Does not inspect live database catalogs."""
        with indexer.session() as con:
            return db_find_db_columns(con, indexer.repository, table=table, column=column)

    def find_db_models(model: str = "", table: str = "") -> dict[str, Any]:
        """Find ORM models (SQLAlchemy, Flask-SQLAlchemy, Django ORM, SQLModel, Prisma) and their `MAPS_TO_TABLE` mappings. Use when asking which model class maps to a database table or vice versa. Returns model name, table, canonical ID, and `FRAMEWORK_VERIFIED` evidence. Does not import or execute application model modules."""
        with indexer.session() as con:
            return db_find_db_models(con, indexer.repository, model=model, table=table)

    def find_db_queries(table: str = "", symbol: str = "", operation: str = "") -> dict[str, Any]:
        """Find database queries (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) across ORM calls, query builders, and raw SQL strings. Use when asking which queries touch a table or what SQL a function executes. Returns `READS_TABLE`, `WRITES_TABLE`, `POSSIBLE_TABLE`, or `UNKNOWN_TABLE` with redacted snippets. Never exposes SQL literal secret parameters."""
        with indexer.session() as con:
            return db_find_db_queries(con, indexer.repository, table=table, symbol=symbol, operation=operation)

    def find_db_callers(table: str) -> dict[str, Any]:
        """Find all functions, methods, and upstream HTTP routes (`HANDLED_BY`) that read from or write to a database table. Use instead of grep when asking 'which code or route reaches table X?'. Returns direct accessors, upstream routes, relationships (`READS_TABLE`, `WRITES_TABLE`), and evidence classes. Does not prove runtime query frequency."""
        with indexer.session() as con:
            return db_find_db_callers(con, indexer.repository, table=table)

    def find_db_writers(table: str = "", column: str = "") -> dict[str, Any]:
        """Find all symbols and queries that write (`INSERT`, `UPDATE`, `DELETE`) to a database table or column (`WRITES_TABLE`, `WRITES_COLUMN`). Use when investigating data mutations, state changes, or write blast radius. Returns writer symbols, operations, file:line citations, and redacted snippets. Does not execute database transactions."""
        with indexer.session() as con:
            return db_find_db_writers(con, indexer.repository, table=table, column=column)

    def find_db_readers(table: str = "", column: str = "") -> dict[str, Any]:
        """Find all symbols and queries that read (`SELECT`, `.query()`, `.objects.filter()`, `.findMany()`) from a database table or column (`READS_TABLE`, `READS_COLUMN`). Use when tracing where table data is consumed across services and views. Returns reader symbols, operations, and evidence classes. Does not prove runtime cache hits."""
        with indexer.session() as con:
            return db_find_db_readers(con, indexer.repository, table=table, column=column)

    def find_db_relationships(table: str = "") -> dict[str, Any]:
        """Find database schema and ORM relationships (`FOREIGN_KEY_TO`, `ORM_RELATION`, `MAPS_TO_TABLE`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `MIGRATES_TABLE`). Use when inspecting foreign keys, table joins, or model associations. Preserves explicit database relationship types and never collapses them into generic `DEPENDS_ON`."""
        with indexer.session() as con:
            return db_find_db_relationships(con, indexer.repository, table=table)

    def get_db_table(table: str) -> dict[str, Any]:
        """Return complete structural details for a database table including columns, primary keys, foreign keys, indexes, constraints, ORM models, readers, writers, migrations, and upstream routes. Use when inspecting a specific table's schema and code usage in one call. Does not query live database servers."""
        with indexer.session() as con:
            return db_get_db_table(con, indexer.repository, table=table)

    def get_db_schema(dialect: str = "", schema: str = "") -> dict[str, Any]:
        """Return a repository-wide database schema summary including all discovered tables, columns, ORM models, foreign keys, and migrations. Use for database architecture overviews or schema audits. Preserves `UNKNOWN` dialect/schema when not statically provable and never guesses database names."""
        with indexer.session() as con:
            return db_get_db_schema(con, indexer.repository, dialect=dialect, schema=schema)

    def get_db_impact(table: str = "", column: str = "") -> dict[str, Any]:
        """Compute bidirectional Code <-> Database change impact for a table or column, returning affected ORM models, readers, writers, upstream HTTP routes, migrations, and statically linked tests. Use before renaming or altering a database table or column. Does not execute database migrations or tests."""
        with indexer.session() as con:
            return db_get_db_impact(con, indexer.repository, table=table, column=column)

    # -----------------------------------------------------------------------
    # Runtime Observation & Reconciliation Tools (3 Tools)
    # -----------------------------------------------------------------------

    def ingest_runtime_traces(
        source_path: str = "",
        format: str = "auto",
        payload: str = "",
        max_events: int = 5000,
        sample_rate: float = 1.0,
    ) -> dict[str, Any]:
        """Ingest optional runtime observation traces (OpenTelemetry JSON, structured JSON/JSONL events, or SQL query logs) into CodeGraph's `RUNTIME_OBSERVED` layer. Use when grounding static analysis with recorded runtime traces. Automatically strips headers/cookies/bodies, redacts SQL bind parameters and secrets, and never converts runtime observations into static `AST_VERIFIED` proof."""
        with indexer.session() as con:
            return runtime_ingest_runtime_traces(
                con,
                indexer.repository,
                source_path=source_path,
                format=format,
                payload=payload,
                max_events=max_events,
                sample_rate=sample_rate,
            )

    def get_runtime_trace(route: str = "", symbol: str = "", table: str = "") -> dict[str, Any]:
        """Retrieve aggregated runtime execution edges (`RUNTIME_OBSERVED`) and reverse maps (`table -> runtime writers/readers`, `route -> runtime tables`) with `observation_count`, `first_seen`, `last_seen`, and `runtime_generation`. Use when asking what actually happened at runtime. Does not treat unobserved paths as impossible."""
        with indexer.session() as con:
            return runtime_get_runtime_trace(con, indexer.repository, route=route, symbol=symbol, table=table)

    def reconcile_static_runtime(symbol: str = "", route: str = "", table: str = "") -> dict[str, Any]:
        """Reconcile static repository edges against ingested runtime observations, classifying edges into `CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`, `NOT_OBSERVED_AT_RUNTIME`, and `RUNTIME_ONLY_OBSERVED`. Use when comparing static code analysis with runtime behavior. Never treats `NOT_OBSERVED_AT_RUNTIME` as proof that a path cannot execute."""
        with indexer.session() as con:
            return runtime_reconcile_static_runtime(con, indexer.repository, symbol=symbol, route=route, table=table)

    core_tools: dict[str, Any] = {
        "resolve_symbol": resolve_symbol,
        "search_symbols": search_symbols,
        "get_symbol": get_symbol_interrogation_wrapper,
        "get_file": get_file,
        "get_references": get_references,
        "get_callers": get_callers,
        "get_callees": get_callees,
        "trace_path": trace_path,
        "get_imports": get_imports,
        "get_dependents": get_dependents,
        "list_routes": list_routes,
        "get_architecture": get_architecture,
        "get_git_impact": get_git_impact,
    }

    # Map of all available tools
    all_tools: dict[str, Any] = {
        **core_tools,
        "search_code": search_code,
        "read_file": read_file,
        "find_symbol": find_symbol,
        "find_references": find_references,
        "find_callers": find_callers,
        "find_callees": find_callees,
        "get_call_graph": get_call_graph,
        "get_dependency_graph": get_dependency_graph,
        "find_related_tests": find_related_tests,
        "find_tests": find_tests,
        "find_routes": find_routes,
        "analyze_impact": analyze_impact,
        "compile_task": compile_task,
        "plan_retrieval": plan_retrieval,
        "get_context": get_context,
        "get_recent_changes": get_recent_changes,
        "get_file_history": get_file_history,
        "analyze_change_impact": analyze_change_impact,
        "get_repository_status": get_repository_status,
        "trace_call": trace_call,
        "trace_flow": trace_flow,
        "get_project_structure": get_project_structure,
        "get_dependencies": get_dependencies,
        "get_file_symbols": get_file_symbols,
        "get_graph": get_graph,
        "search_memory": search_memory,
        "get_evidence": get_evidence,
        "verify_evidence": verify_evidence,
        "get_resource_status": get_resource_status,
        "find_db_tables": find_db_tables,
        "find_db_columns": find_db_columns,
        "find_db_models": find_db_models,
        "find_db_queries": find_db_queries,
        "find_db_callers": find_db_callers,
        "find_db_writers": find_db_writers,
        "find_db_readers": find_db_readers,
        "find_db_relationships": find_db_relationships,
        "get_db_table": get_db_table,
        "get_db_schema": get_db_schema,
        "get_db_impact": get_db_impact,
        "ingest_runtime_traces": ingest_runtime_traces,
        "get_runtime_trace": get_runtime_trace,
        "reconcile_static_runtime": reconcile_static_runtime,
    }

    agent_names = {
        # DISCOVERY
        "find_symbol",
        "search_code",
        "find_references",
        "find_callers",
        "find_callees",
        "find_tests",
        "find_routes",
        # DETAILS
        "get_symbol",
        "get_file",
        "get_context",
        "get_architecture",
        "get_git_impact",
        # GRAPH
        "trace_path",
        "trace_flow",
    }
    core_names = set(core_tools.keys())
    graph_names = core_names | {
        "get_context",
        "get_call_graph",
        "find_related_tests",
        "analyze_impact",
    }
    minimal_names = core_names | {
        "search_code",
        "read_file",
        "find_symbol",
        "compile_task",
        "get_context",
        "get_repository_status",
        "verify_evidence",
        "get_resource_status",
    }
    developer_names = minimal_names | {
        "find_references",
        "find_callers",
        "find_callees",
        "get_call_graph",
        "find_related_tests",
        "analyze_impact",
        "get_evidence",
        "trace_call",
        "get_graph",
        "plan_retrieval",
        "get_recent_changes",
        "get_file_history",
        "analyze_change_impact",
    }

    if profile in ("agent", "default"):
        selected_names = agent_names
    elif profile == "core":
        selected_names = core_names
    elif profile == "graph":
        selected_names = graph_names
    elif profile == "minimal":
        selected_names = minimal_names
    elif profile == "developer":
        selected_names = developer_names
    else:
        selected_names = set(all_tools.keys())

    _last_db_sig: list[tuple[int, int, int, int] | None] = [None]

    def _compute_db_sig() -> tuple[int, int, int, int] | None:
        db_file = indexer.db_path
        if not db_file.exists():
            return None
        try:
            st = db_file.stat()
            wal_file = Path(f"{db_file}-wal")
            wal_mtime = wal_file.stat().st_mtime_ns if wal_file.exists() else 0
            return (st.st_ino, st.st_mtime_ns, st.st_size, wal_mtime)
        except OSError:
            return None

    _last_db_sig[0] = _compute_db_sig()

    def _ensure_hot_reloaded() -> bool:
        """Detect if `.codegraph.sqlite3` was created, replaced, or updated on disk (e.g. via `codegraph init`)."""
        cur_sig = _compute_db_sig()
        if cur_sig != _last_db_sig[0]:
            _last_db_sig[0] = cur_sig
            from codegraph.resources.cache import get_graph_cache, get_parse_cache

            get_graph_cache().clear()
            get_parse_cache().clear()
            return True
        return False

    for tool_name in sorted(selected_names):
        target_fn: Any = all_tools[tool_name]

        def _make_guarded(fn: Any) -> Any:
            @functools.wraps(fn)
            def _guarded(*args: Any, **kwargs: Any) -> Any:
                _ensure_hot_reloaded()
                with indexer.governor.task_scope(TaskPriority.INTERACTIVE_HIGH):
                    return fn(*args, **kwargs)

            return _guarded

        app.tool(name=tool_name)(_make_guarded(target_fn))

    # -----------------------------------------------------------------------
    # MCP Resources
    # -----------------------------------------------------------------------

    @app.resource("codebase://capabilities")
    def resource_capabilities() -> str:
        """Machine-readable CodeGraph capability manifest, tool selection rules, and evidence semantics."""
        from codegraph.agent_capabilities import get_capability_manifest

        return json.dumps(get_capability_manifest(), indent=2)

    @app.resource("codebase://status")
    def resource_status() -> str:
        """Repository index status, generation, and file counts."""
        with indexer.session() as con:
            report = check_freshness(indexer.repository, con)
            return json.dumps(
                {
                    "repository": str(indexer.repository),
                    "generation": report.index_generation,
                    "freshness": report.status.value,
                    "files": con.execute("SELECT count(*) FROM files").fetchone()[0],
                    "symbols": con.execute("SELECT count(*) FROM symbols").fetchone()[0],
                },
                indent=2,
            )

    @app.resource("codebase://architecture")
    def resource_architecture() -> str:
        """High-level architectural overview."""
        with indexer.session() as con:
            arch = arch_get_architecture(con, indexer.repository)
            return json.dumps(arch, indent=2)

    @app.resource("codebase://modules")
    def resource_modules() -> str:
        """List of indexed repository module paths."""
        with indexer.session() as con:
            rows = con.execute("SELECT path FROM files ORDER BY path LIMIT 500").fetchall()
            return "\n".join(r[0] for r in rows)

    @app.resource("codebase://health")
    def resource_health() -> str:
        """Database health and integrity report."""
        with indexer.session() as con:
            health = check_database_health(con)
            return json.dumps(health, indent=2)

    @app.resource("codebase://resources")
    def resource_resources() -> str:
        """Resource governor state, memory bounds, pressure, and activity mode."""
        return json.dumps(indexer.governor.get_state().as_dict(), indent=2)

    # -----------------------------------------------------------------------
    # MCP Prompts
    # -----------------------------------------------------------------------

    @app.prompt()
    def understand_repository() -> str:
        """Guide the AI coding agent to understand repository structure and components."""
        return (
            "1. Read `codebase://status` and `get_architecture()` to inspect the macro system layout.\n"
            "2. Identify primary entry points, endpoints, and data models.\n"
            "3. Compile a TaskSpec with intent='UNDERSTAND' and pass to `get_context()`."
        )

    @app.prompt()
    def trace_request(endpoint: str = "") -> str:
        """Guide the AI coding agent to trace an HTTP route or entrypoint."""
        return (
            f"Trace route or endpoint: {endpoint}\n"
            "1. Call `compile_task` with intent='TRACE' and target set to the endpoint.\n"
            "2. Call `get_context` to receive the full call-path from route to data layer.\n"
            "3. Inspect callers, callees, and verified evidence."
        )

    @app.prompt()
    def debug_issue(symptom: str = "") -> str:
        """Guide the AI coding agent to debug an issue using verified facts and recent changes."""
        return (
            f"Investigate symptom: {symptom}\n"
            "1. Call `compile_task` with intent='DEBUG' and relevant targets.\n"
            "2. Call `get_context` with token budget to retrieve entry points, recent git diffs, and related tests.\n"
            "3. Formulate hypotheses strictly based on cited source evidence."
        )

    @app.prompt()
    def prepare_change(target: str = "") -> str:
        """Guide the AI coding agent to evaluate blast radius before changing code."""
        return (
            f"Target symbol or file: {target}\n"
            "1. Call `analyze_impact` to compute callers and affected modules.\n"
            "2. Call `find_related_tests` to identify regression verification targets.\n"
            "3. Call `get_context` with intent='CHANGE'."
        )

    @app.prompt()
    def analyze_impact_prompt(target: str = "") -> str:
        """Guide the AI coding agent to compute reverse dependency blast radius."""
        return (
            f"Target: {target}\n"
            "1. Call `analyze_impact` for reverse references, callers, and dependents.\n"
            "2. Verify related tests and routes."
        )

    @app.prompt()
    def review_change(since: str = "HEAD~1") -> str:
        """Guide the AI coding agent to review recent changes against affected tests."""
        return (
            f"Diff range: {since}..HEAD\n"
            "1. Call `analyze_change_impact` to identify changed symbols and callers.\n"
            "2. Run `get_context` with intent='REVIEW'."
        )

    app._codegraph_indexer = indexer  # type: ignore[attr-defined]
    return app
