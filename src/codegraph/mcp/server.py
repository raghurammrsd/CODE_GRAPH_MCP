from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from codegraph.architecture import get_architecture as arch_get_architecture
from codegraph.config import Settings
from codegraph.context import get_context as compile_context
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
from codegraph.search import search
from codegraph.security import is_sensitive, safe_path
from codegraph.task import normalize_task_spec


def create_server(
    repository: Path,
    settings: Settings | None = None,
    profile: str = "full",
) -> Any:
    """Build an MCP FastMCP server lazily so normal CLI use needs no MCP dependency."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support requires: pip install 'codegraph-mcp[mcp]'") from exc

    indexer = Indexer(repository, settings)
    memory = MemoryStore(indexer.db_path)
    app = FastMCP("CodeGraph MCP")

    # -----------------------------------------------------------------------
    # Tool Handlers
    # -----------------------------------------------------------------------

    def search_code(query: str, top_k: int = 10) -> list[dict[str, object]]:
        """Find relevant code snippets and symbols across indexed files using lexical search. (Do NOT use for import or dependency questions; use get_imports or get_dependents instead)."""
        if not query.strip() or not 1 <= top_k <= 100:
            raise ValueError("query must be non-empty and top_k must be 1..100")
        with indexer.session() as con:
            return [item.as_dict() for item in search(con, query, top_k)]

    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> dict[str, object]:
        """Read a bounded, non-sensitive repository file by repository-relative path."""
        if start_line < 1 or end_line < start_line or end_line - start_line > 500:
            raise ValueError("line range must be 1..500 lines")
        resolved = safe_path(indexer.repository, path)
        relative = resolved.relative_to(indexer.repository)
        if is_sensitive(relative):
            raise SecurityError("sensitive files cannot be read")
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        return {
            "file": relative.as_posix(),
            "start_line": start_line,
            "end_line": min(end_line, len(lines)),
            "content": "\n".join(lines[start_line - 1 : end_line]),
        }

    def find_symbol(name: str) -> list[dict[str, object]]:
        """Find function, method, or class definitions by name."""
        if not name.strip():
            raise ValueError("symbol name must be non-empty")
        with indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name AS symbol,kind,path AS file,start_line,end_line "
                "FROM symbols WHERE name=? OR qualified_name=? ORDER BY path,start_line LIMIT 100",
                (name, name),
            )
            return [dict(row) for row in rows]

    def get_symbol(symbol: str) -> dict[str, object]:
        """Get authoritative details for a single symbol by name or canonical ID."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            sym = graph_get_symbol(con, symbol)
            if not sym:
                return {"error": f"Symbol not found: {symbol}"}
            return sym.as_dict()

    def find_references(name: str) -> list[dict[str, object]]:
        """Find textual references; results are explicitly not guaranteed semantic call edges."""
        if not name.strip():
            raise ValueError("reference name must be non-empty")
        with indexer.session() as con:
            return [
                dict(row)
                for row in con.execute(
                    "SELECT path AS file,symbol,start_line,end_line FROM chunks WHERE content LIKE ? ORDER BY path,start_line LIMIT 100",
                    (f"%{name}%",),
                )
            ]

    def find_callers(symbol: str, max_results: int = 20) -> list[dict[str, object]]:
        """Find functions and methods that call the specified symbol."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            return [dict(r) for r in graph_find_callers(con, symbol, max_results=max_results)]

    def find_callees(symbol: str, max_results: int = 20) -> list[dict[str, object]]:
        """Find functions and methods called by the specified symbol."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            return [dict(r) for r in graph_find_callees(con, symbol, max_results=max_results)]

    def get_call_graph(symbol: str, depth: int = 2, max_results: int = 100) -> list[dict[str, object]]:
        """Compute the call graph rooted at the given symbol."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            return [dict(e) for e in graph_get_call_graph(con, symbol=symbol, depth=depth, max_results=max_results)]

    def get_dependency_graph(file_path: str | None = None) -> list[dict[str, object]]:
        """List module import and dependency graph edges."""
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

    def find_related_tests(symbol: str, max_results: int = 10) -> list[dict[str, object]]:
        """Find test files and test functions related to a symbol."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            return [dict(r) for r in graph_find_related_tests(con, symbol, max_results=max_results)]

    def analyze_impact(symbol: str, max_depth: int = 3) -> dict[str, object]:
        """Analyze downstream impact and blast radius if a symbol is modified."""
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        with indexer.session() as con:
            return graph_analyze_impact(con, symbol, max_depth=max_depth)

    def compile_task(
        task: dict[str, Any] | str,
        max_tokens: int = 20_000,
        resource_mode: str = "BALANCED",
    ) -> dict[str, object]:
        """Normalize a task, ground targets against repository symbols, detect ambiguities, and build a RetrievalPlan."""
        with indexer.session() as con:
            spec, ambiguities = normalize_task_spec(task, con)
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
        task: dict[str, Any] | str,
        max_tokens: int = 20_000,
        resource_mode: str = "BALANCED",
    ) -> dict[str, object]:
        """Construct a deterministic RetrievalPlan for a task without executing retrieval."""
        with indexer.session() as con:
            spec, ambiguities = normalize_task_spec(task, con)
            plan = build_retrieval_plan(
                spec,
                ambiguities,
                con,
                token_budget=max_tokens,
                resource_mode=resource_mode,
            )
            return plan.as_dict()

    def get_context(
        task: dict[str, Any] | str,
        intent: str | None = None,
        max_tokens: int = 20000,
        top_k: int = 15,
        plan: dict[str, Any] | None = None,
        mode: str = "BALANCED",
        explain: bool = False,
        resource_mode: str | None = None,
    ) -> dict[str, object]:
        """Compile a complete, ranked, verified context packet for an AI agent task."""
        if isinstance(task, str) and not task.strip():
            raise ValueError("task must be non-empty")
        effective_mode = resource_mode or mode
        with indexer.session() as con:
            packet = compile_context(
                con,
                indexer.repository,
                task=task,
                intent=intent,
                max_tokens=max_tokens,
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
        """Get repository indexing status, freshness, symbol counts, and health."""
        with indexer.session() as con:
            report = check_freshness(indexer.repository, con)
            file_count = con.execute("SELECT count(*) FROM files").fetchone()[0]
            symbol_count = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
            edge_count = con.execute("SELECT count(*) FROM graph_edges").fetchone()[0]
            route_count = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
            return {
                "repository": str(indexer.repository),
                "generation": report.index_generation,
                "freshness": report.status.value,
                "freshness_detail": report.detail,
                "files_indexed": file_count,
                "symbols_indexed": symbol_count,
                "graph_edges": edge_count,
                "framework_routes": route_count,
                "modified_files": report.modified_files,
                "deleted_files": report.deleted_files,
                "parse_failed_files": report.parse_failed_files,
            }

    def trace_call(
        symbol: str,
        depth: int = 2,
        callers: bool = True,
        callees: bool = False,
        both: bool = False,
    ) -> list[dict[str, object]]:
        """Trace known definition, callers, and callees with explicit confidence and relationship labels."""
        with indexer.session() as con:
            return graph_trace_call(con, symbol, max_depth=depth, callers=callers, callees=callees, both=both)

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
                    row["end_line"],
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

    def resolve_symbol(name: str) -> dict[str, Any]:
        """Determine whether an exact/canonical symbol exists and return its location and identity."""
        with indexer.session() as con:
            return interrogation_resolve_symbol(con, indexer.repository, name)

    def search_symbols(query: str, top_k: int = 20) -> dict[str, Any]:
        """Search indexed repository symbols using an explicit search term. (Do NOT use for discovering module imports or dependencies; use get_imports or get_dependents instead)."""
        with indexer.session() as con:
            return interrogation_search_symbols(con, indexer.repository, query, top_k=top_k)

    def get_symbol_interrogation_wrapper(canonical_id: str = "", symbol: str = "") -> dict[str, Any]:
        """Return complete structured information for a known canonical symbol."""
        sym_id = canonical_id or symbol
        with indexer.session() as con:
            return interrogation_get_symbol(con, indexer.repository, sym_id)

    def get_file(path: str, include_content: bool = False) -> dict[str, Any]:
        """Return the structural AST representation of an indexed file."""
        with indexer.session() as con:
            return interrogation_get_file(con, indexer.repository, path, include_content=include_content)

    def get_references(canonical_id: str) -> dict[str, Any]:
        """Return all known references to a canonical symbol with evidence."""
        with indexer.session() as con:
            return interrogation_get_references(con, indexer.repository, canonical_id)

    def get_callers(canonical_id: str) -> dict[str, Any]:
        """Return symbols that call the specified symbol with explicit evidence."""
        with indexer.session() as con:
            return interrogation_get_callers(con, indexer.repository, canonical_id)

    def get_callees(canonical_id: str) -> dict[str, Any]:
        """Return symbols called by the specified symbol with call-type classification."""
        with indexer.session() as con:
            return interrogation_get_callees(con, indexer.repository, canonical_id)

    def trace_path(
        from_symbol: str = "",
        to_symbol: str = "",
        start_symbol: str = "",
        target_symbol: str = "",
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """Find a deterministic relationship path between two known symbols."""
        src = from_symbol or start_symbol
        tgt = to_symbol or target_symbol
        with indexer.session() as con:
            return interrogation_trace_path(con, indexer.repository, src, tgt, max_depth=max_depth)

    def get_imports(file: str | None = None, canonical_id: str | None = None) -> dict[str, Any]:
        """What this file/module imports: return parser-extracted imports and imported symbols for a file or canonical symbol."""
        with indexer.session() as con:
            return interrogation_get_imports(con, indexer.repository, file=file, canonical_id=canonical_id)

    def get_dependents(canonical_id: str | None = None, file: str | None = None) -> dict[str, Any]:
        """What imports or depends on this file/module: reverse dependency query returning files and symbols that import or depend on the target."""
        with indexer.session() as con:
            return interrogation_get_dependents(con, indexer.repository, canonical_id=canonical_id, file=file)

    def list_routes(
        framework: str | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Expose application routes discovered from the repository."""
        with indexer.session() as con:
            return interrogation_list_routes(con, indexer.repository, framework=framework, method=method, path=path)

    def get_architecture() -> dict[str, Any]:
        """Return a structural overview of the repository."""
        with indexer.session() as con:
            return interrogation_get_architecture(con, indexer.repository)

    def get_git_impact(base: str = "HEAD~1", head: str = "HEAD") -> dict[str, Any]:
        """Determine code affected by Git changes between base and head."""
        with indexer.session() as con:
            return interrogation_get_git_impact(con, indexer.repository, base=base, head=head)

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
        "analyze_impact": analyze_impact,
        "compile_task": compile_task,
        "plan_retrieval": plan_retrieval,
        "get_context": get_context,
        "get_recent_changes": get_recent_changes,
        "get_file_history": get_file_history,
        "analyze_change_impact": analyze_change_impact,
        "get_repository_status": get_repository_status,
        "trace_call": trace_call,
        "get_project_structure": get_project_structure,
        "get_dependencies": get_dependencies,
        "get_file_symbols": get_file_symbols,
        "get_graph": get_graph,
        "search_memory": search_memory,
        "get_evidence": get_evidence,
        "verify_evidence": verify_evidence,
        "get_resource_status": get_resource_status,
    }

    core_names = set(core_tools.keys())
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

    if profile == "core":
        selected_names = core_names
    elif profile == "minimal":
        selected_names = minimal_names
    elif profile == "developer":
        selected_names = developer_names
    else:
        selected_names = set(all_tools.keys())

    for tool_name in sorted(selected_names):
        target_fn: Any = all_tools[tool_name]

        def _make_guarded(fn: Any) -> Any:
            @functools.wraps(fn)
            def _guarded(*args: Any, **kwargs: Any) -> Any:
                with indexer.governor.task_scope(TaskPriority.INTERACTIVE_HIGH):
                    return fn(*args, **kwargs)

            return _guarded

        app.tool(name=tool_name)(_make_guarded(target_fn))

    # -----------------------------------------------------------------------
    # MCP Resources
    # -----------------------------------------------------------------------

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

    return app
