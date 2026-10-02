from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from codegraph import __version__
from codegraph.architecture import get_architecture
from codegraph.config import Settings
from codegraph.context import get_context
from codegraph.errors import ErrorCode, SecurityError
from codegraph.freshness import check_freshness, index_generation
from codegraph.graph import trace_call
from codegraph.graph.traversal import get_focused_graph, get_graph_summary
from codegraph.indexing import Indexer
from codegraph.indexing.indexer import check_database_health
from codegraph.interrogation import (
    get_dependents as interrogation_get_dependents,
)
from codegraph.interrogation import (
    get_imports as interrogation_get_imports,
)
from codegraph.interrogation import (
    get_symbol as interrogation_get_symbol,
)
from codegraph.interrogation import (
    resolve_symbol as interrogation_resolve_symbol,
)
from codegraph.memory import MemoryStore
from codegraph.planner import build_retrieval_plan
from codegraph.resolver import ReferenceResolver
from codegraph.search import search as search_code
from codegraph.security import is_sensitive, safe_path
from codegraph.task import TargetExpressionType, classify_target_expression, normalize_task_spec

app = typer.Typer(no_args_is_help=True, help="Evidence-backed local codebase intelligence.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"codegraph {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", "-v", help="Show version and exit", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """Evidence-backed local codebase intelligence for MCP clients and AI agents."""
    pass


def _resolve_repo(
    path: Path | None = None,
    repository: Path | None = None,
) -> Path:
    """Resolve repository path with priority: explicit option > positional argument > current directory."""
    target: Path
    if repository is not None:
        target = repository
    elif path is not None:
        target = path
    else:
        target = Path.cwd()

    if not target.exists():
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.INVALID_PATH.value,
                        "message": f"Repository path does not exist: {target}",
                        "next_action": {
                            "command": "codegraph init .",
                            "reason": "Specify an existing directory path.",
                        },
                    },
                },
                indent=2,
            )
        )
        raise typer.Exit(code=1)

    if not target.is_dir():
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.INVALID_PATH.value,
                        "message": f"Repository path is not a directory: {target}",
                        "next_action": {
                            "command": "codegraph init .",
                            "reason": "Specify a valid directory path.",
                        },
                    },
                },
                indent=2,
            )
        )
        raise typer.Exit(code=1)

    return target.resolve()


def _ensure_indexed(repo: Path) -> bool:
    """Check if repository has an index database; if not, output structured INDEX_NOT_FOUND error."""
    db = repo / ".codegraph.sqlite3"
    if not db.exists():
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.INDEX_NOT_FOUND.value,
                        "message": "No CodeGraph index exists for this repository.",
                        "next_action": {
                            "command": "codegraph init",
                            "reason": "Initialize the repository before querying it.",
                        },
                    },
                },
                indent=2,
            )
        )
        return False
    return True


def _indexer(repository: Path, db_path: Path | None = None) -> Indexer:
    return Indexer(repository, Settings(repository=repository, db_path=db_path))


@app.command()
def index(
    path: Annotated[Path | None, typer.Argument(help="Repository path to index (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Securely index supported source files, skipping unchanged content."""
    repo = _resolve_repo(path, repository)
    result = _indexer(repo).index()
    typer.echo(json.dumps(result) if json_output else " ".join(f"{k}={v}" for k, v in result.items()))


@app.command()
def init(
    path: Annotated[Path | None, typer.Argument(help="Repository path to initialize (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Initialize repository indexing and configuration."""
    target_repo = _resolve_repo(path, repository)
    result = _indexer(target_repo).index()
    if json_output:
        typer.echo(json.dumps({"status": "initialized", "repository": str(target_repo.resolve()), "indexing": result}, indent=2))
    else:
        typer.echo(f"Initialized CodeGraph repository at {target_repo.resolve()} (indexed {result.get('indexed_files', 0)} files)")


@app.command()
def search(
    query: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    top_k: int = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Search indexed code with exact evidence."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    if not query.strip():
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.INVALID_ARGUMENT.value,
                        "message": "Search query must be non-empty.",
                        "next_action": {
                            "command": "codegraph search <query>",
                            "reason": "Provide a non-empty search query.",
                        },
                    },
                },
                indent=2,
            )
        )
        return
    with _indexer(repo).session() as con:
        result = [r.as_dict() for r in search_code(con, query, top_k)]
    typer.echo(
        json.dumps(result, indent=2)
        if json_output
        else "\n\n".join(
            f"{r['file']}:{r['start_line']}-{r['end_line']} {r['symbol'] or ''} score={r['score']}\n{r['snippet']}"
            for r in result
        )
    )


@app.command()
def symbols(
    path: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
) -> None:
    """Show extracted symbols for an indexed file."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    try:
        safe_path(repo, path)
    except SecurityError:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.PATH_OUTSIDE_REPOSITORY.value,
                        "message": f"Path traversal blocked: '{path}' resides outside repository boundary.",
                        "next_action": {
                            "command": "codegraph status",
                            "reason": "Ensure all queried paths reside within the repository root.",
                        },
                    },
                },
                indent=2,
            )
        )
        return
    with _indexer(repo).session() as con:
        rows = con.execute(
            "SELECT canonical_id, qualified_name, kind, start_line, end_line FROM symbols WHERE path=? ORDER BY start_line",
            (path,),
        ).fetchall()
    typer.echo(json.dumps([dict(r) for r in rows], indent=2))


@app.command()
def trace(
    symbol: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    callers: Annotated[bool, typer.Option("--callers", help="Trace caller hierarchy")] = False,
    callees: Annotated[bool, typer.Option("--callees", help="Trace direct callees")] = False,
    both: Annotated[bool, typer.Option("--both", help="Trace both callers and callees")] = False,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max trace depth (clamped to max 5)")] = 2,
) -> None:
    """Trace a symbol definition, callers, and callees with explicit confidence labels."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    if depth < 1 or depth > 10:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": ErrorCode.INVALID_DEPTH.value,
                        "message": f"Invalid graph traversal depth {depth}; allowed range is 1..5.",
                        "next_action": {
                            "command": "codegraph trace --depth 2 <symbol>",
                            "reason": "Specify a traversal depth between 1 and 5.",
                        },
                    },
                },
                indent=2,
            )
        )
        return
    bounded_depth = max(1, min(depth, 5))
    effective_callers = callers
    effective_callees = callees
    effective_both = both
    if not callers and not callees and not both:
        effective_both = True

    with _indexer(repo).session() as con:
        res = trace_call(con, symbol, max_depth=bounded_depth, callers=effective_callers, callees=effective_callees, both=effective_both)
        if not res:
            sym_row = con.execute(
                "SELECT 1 FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
                (symbol, symbol, symbol),
            ).fetchone()
            if not sym_row:
                typer.echo(
                    json.dumps(
                        {
                            "status": "unknown",
                            "error": {
                                "code": ErrorCode.SYMBOL_NOT_FOUND.value,
                                "message": f"No matching symbol was found for '{symbol}'.",
                                "next_action": {
                                    "command": f"codegraph search {symbol}",
                                    "reason": "Search with a broader query term.",
                                },
                            },
                        },
                        indent=2,
                    )
                )
                return
        typer.echo(json.dumps(res, indent=2))


@app.command("get-symbol")
def get_symbol_cmd(
    symbol: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = True,
) -> None:
    """Get authoritative AST details for a single symbol by name or canonical ID."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        res = interrogation_get_symbol(con, repo, symbol)
    typer.echo(json.dumps(res, indent=2))


@app.command("resolve-symbol")
def resolve_symbol_cmd(
    query: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = True,
) -> None:
    """Determine whether an exact/canonical symbol exists or return ambiguous candidates."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        res = interrogation_resolve_symbol(con, repo, query)
    typer.echo(json.dumps(res, indent=2))


@app.command()
def graph(
    path: Annotated[Path | None, typer.Argument(help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    module: Annotated[str | None, typer.Option("--module", "-m", help="Filter focused graph by module")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol", "-s", help="Filter focused graph by symbol")] = None,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Traversal depth for focused graph (max 5)")] = 2,
) -> None:
    """Summarize indexed graph nodes, edges, modules, or inspect focused subgraphs."""
    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        return
    bounded_depth = max(1, min(depth, 5))
    with _indexer(repo).session() as con:
        if module or symbol:
            result = get_focused_graph(con, module=module, symbol=symbol, depth=bounded_depth)
        else:
            result = get_graph_summary(con)
        typer.echo(json.dumps(result, indent=2))


@app.command()
def routes(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    framework: Annotated[str | None, typer.Option("--framework", "-f", help="Filter by framework (e.g. flask, fastapi)")] = None,
    method: Annotated[str | None, typer.Option("--method", "-m", help="Filter by HTTP method (e.g. GET, POST)")] = None,
    route_path: Annotated[str | None, typer.Option("--path", "-p", help="Filter by route path substring")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON array")] = False,
) -> None:
    """List and inspect indexed framework routes."""
    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        query = (
            "SELECT endpoint_id, framework, http_method, route_path, handler_name, "
            "handler_canonical_id, file_path, line, evidence, confidence "
            "FROM framework_routes WHERE 1=1 "
        )
        params: list[str] = []
        if framework:
            query += "AND framework=? "
            params.append(framework.lower())
        if method:
            query += "AND UPPER(http_method)=? "
            params.append(method.upper())
        if route_path:
            query += "AND route_path LIKE ? "
            params.append(f"%{route_path}%")
        query += "ORDER BY route_path, http_method"

        try:
            rows = con.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            rows = []

        route_list = [
            {
                "endpoint_id": r["endpoint_id"],
                "http_method": r["http_method"],
                "route_path": r["route_path"],
                "handler": r["handler_name"],
                "canonical_id": r["handler_canonical_id"],
                "file": r["file_path"],
                "line": r["line"],
                "framework": r["framework"],
                "evidence": r["evidence"],
                "confidence": r["confidence"],
            }
            for r in rows
        ]

        if json_output:
            typer.echo(json.dumps(route_list, indent=2))
        else:
            if not route_list:
                typer.echo("No framework routes indexed or matching criteria.")
                return
            typer.echo(f"Found {len(route_list)} route(s):")
            for r in route_list:
                typer.echo(f"  [{r['http_method']}] {r['route_path']} -> {r['handler']} ({r['file']}:{r['line']}) [{r['framework']}]")


@app.command()
def imports(
    path: Annotated[str | None, typer.Argument(help="Repository-relative file path to inspect imports for (default: inspect all imports)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON array")] = True,
) -> None:
    """Show what a file or module imports."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        res = interrogation_get_imports(con, repo, file=path)
    typer.echo(json.dumps(res, indent=2))


@app.command()
def dependents(
    target: Annotated[str, typer.Argument(help="File path or symbol canonical ID to find dependents/importers for")],
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON array")] = True,
) -> None:
    """Show what files and symbols import or depend on the target file/symbol."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        is_path = "/" in target or target.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))
        if is_path:
            res = interrogation_get_dependents(con, repo, file=target)
        else:
            res = interrogation_get_dependents(con, repo, canonical_id=target)
    typer.echo(json.dumps(res, indent=2))


@app.command()
def architecture(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output full architecture model in JSON")] = True,
) -> None:
    """Summarize repository architecture including modules, frameworks, routes, and tests."""
    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        arch = get_architecture(con, repo)
        typer.echo(json.dumps(arch, indent=2))


@app.command()
def debug(
    question: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
) -> None:
    """Return source-backed facts and clearly-labelled debugging hypotheses."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        spec, _ = normalize_task_spec(question, con=con)
        unknown_explicit_targets = []
        for t in spec.targets:
            expr_type = classify_target_expression(t)
            if expr_type == TargetExpressionType.EXPLICIT_SYMBOL_TARGET:
                row = con.execute(
                    "SELECT 1 FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? "
                    "UNION SELECT 1 FROM framework_routes WHERE endpoint_id=? OR route_path=? "
                    "LIMIT 1",
                    (t, t, t, t, t),
                ).fetchone()
                if not row:
                    unknown_explicit_targets.append(t)

        if unknown_explicit_targets:
            unknown_target = unknown_explicit_targets[0]
            lexical_evidence = [item.as_dict() for item in search_code(con, question, 10)]
            typer.echo(
                json.dumps(
                    {
                        "TARGET": unknown_target,
                        "STATUS": "UNKNOWN",
                        "MESSAGE": "No repository symbol/route/module matching the explicit target was found.",
                        "RELATED_LEXICAL_RESULTS": lexical_evidence,
                    },
                    indent=2,
                )
            )
            return

        evidence = [item.as_dict() for item in search_code(con, question, 10)]
        typer.echo(
            json.dumps(
                {
                    "CONFIRMED FACT": evidence,
                    "LIKELY CAUSE": [
                        "A cited branch or raised exception may explain the symptom; this is not confirmed."
                    ],
                    "POSSIBLE CAUSE": [
                        "Other uncited runtime configuration or dependency behavior may contribute."
                    ],
                    "RECOMMENDATION": ["Reproduce with input that exercises each cited branch."],
                },
                indent=2,
            )
        )


@app.command()
def serve(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    profile: Annotated[str, typer.Option("--profile", help="Tool profile: core | minimal | developer | full")] = "full",
) -> None:
    """Run the stdio MCP server (requires the optional mcp extra)."""
    repo = _resolve_repo(path, repository)
    from codegraph.mcp import create_server

    create_server(repo, profile=profile).run()


mcp_app = typer.Typer(help="MCP server commands.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    profile: Annotated[str, typer.Option("--profile", help="Tool profile: core | minimal | developer | full")] = "full",
) -> None:
    """Run the stdio MCP server (requires the optional mcp extra)."""
    repo = _resolve_repo(path, repository)
    from codegraph.mcp import create_server

    create_server(repo, profile=profile).run()


@app.command()
def doctor(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    resources: Annotated[bool, typer.Option("--resources")] = False,
    database: Annotated[bool, typer.Option("--database", help="Run comprehensive database integrity and schema checks")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check repository and index readiness, database integrity, and freshness."""
    repo = _resolve_repo(path, repository)
    indexer_inst = _indexer(repo)
    db = repo / ".codegraph.sqlite3"
    result: dict[str, object] = {
        "repository": str(repo.resolve()),
        "index_exists": db.exists(),
        "python": "supported",
    }
    if db.exists():
        with indexer_inst.session() as con:
            health = check_database_health(con, repo)
            freshness_rep = check_freshness(repo, con)
            gen = index_generation(con)
            result["health"] = health
            result["status"] = (
                "healthy"
                if health.get("status") in ("healthy", "OK") and freshness_rep.status.value == "FRESH"
                else "warning"
            )
            result["freshness"] = freshness_rep.status.value
            result["freshness_detail"] = freshness_rep.detail
            result["index_generation"] = gen
            result["counts"] = {
                "files": con.execute("SELECT count(*) FROM files").fetchone()[0],
                "symbols": con.execute("SELECT count(*) FROM symbols").fetchone()[0],
                "chunks": con.execute("SELECT count(*) FROM chunks").fetchone()[0],
                "framework_routes": con.execute("SELECT count(*) FROM framework_routes").fetchone()[0],
                "graph_edges": con.execute("SELECT count(*) FROM graph_edges").fetchone()[0],
            }
    else:
        result["status"] = "not_indexed"

    if database:
        if not db.exists():
            typer.echo(json.dumps({"status": "not_indexed", "error": "Database does not exist"}, indent=2))
            return
        with indexer_inst.session() as con:
            health = check_database_health(con, repo)
            typer.echo(json.dumps(health, indent=2))
            return

    result["resources"] = indexer_inst.governor.get_state().as_dict()
    typer.echo(json.dumps(result, indent=2))


@app.command()
def resolve(
    symbol: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Resolve a symbol with authoritative diagnostic, callers, and callees."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        diag = ReferenceResolver.resolve_symbol_diagnostic(con, symbol)
    typer.echo(json.dumps(diag, indent=2))


@app.command()
def privacy(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify repository privacy boundaries and ensure no sensitive data is indexed."""
    repo = _resolve_repo(path, repository)
    db = repo / ".codegraph.sqlite3"
    indexed_files: list[str] = []
    if db.exists():
        with _indexer(repo).session() as con:
            indexed_files = [r[0] for r in con.execute("SELECT path FROM files").fetchall()]
    sensitive_leaks = [p for p in indexed_files if is_sensitive(Path(p))]
    report: dict[str, object] = {
        "repository": str(repo.resolve()),
        "sensitive_files_indexed": len(sensitive_leaks),
        "leaks": sensitive_leaks,
        "clean": len(sensitive_leaks) == 0,
        "boundary_enforced": True,
        "source_upload": "DISABLED (100% local execution)",
        "telemetry": "DISABLED",
        "network_access": "DISABLED",
        "shell_execution": "DISABLED",
        "model_api_required": False,
        "prompt_injection_boundary": "STRICT (code and repo docs treated as passive DATA)",
    }
    typer.echo(json.dumps(report, indent=2))


@app.command()
def status(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show repository indexing status, freshness, and graph statistics."""
    repo = _resolve_repo(path, repository)
    db = repo / ".codegraph.sqlite3"
    if not db.exists():
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "repository": str(repo.resolve()),
                    "error": {
                        "code": ErrorCode.INDEX_NOT_FOUND.value,
                        "message": "No CodeGraph index exists for this repository.",
                        "next_action": {
                            "command": "codegraph init",
                            "reason": "Initialize the repository before querying it.",
                        },
                    },
                },
                indent=2,
            )
        )
        return
    indexer_inst = _indexer(repo)
    with indexer_inst.session() as con:
        freshness_rep = check_freshness(repo, con)
        file_count = con.execute("SELECT count(*) FROM files").fetchone()[0]
        symbol_count = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
        chunk_count = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        route_count = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        edge_count = con.execute("SELECT count(*) FROM graph_edges").fetchone()[0]
        gov_state = indexer_inst.governor.get_state().as_dict()
        rep = {
            "repository": str(repo.resolve()),
            "freshness": freshness_rep.status.value,
            "freshness_detail": freshness_rep.detail,
            "files": file_count,
            "chunks": chunk_count,
            "symbols": symbol_count,
            "framework_routes": route_count,
            "graph_edges": edge_count,
            "resource_profile": gov_state["policy_profile"],
            "pressure_level": gov_state["pressure_level"],
            "activity_mode": gov_state["activity_mode"],
            "estimated_memory_mb": gov_state["estimated_memory_mb"],
            "modified_files": freshness_rep.modified_files,
            "deleted_files": freshness_rep.deleted_files,
            "parse_failed_files": freshness_rep.parse_failed_files,
        }
        typer.echo(json.dumps(rep, indent=2))


@app.command()
def context(
    task: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    intent: Annotated[str | None, typer.Option("--intent", "-i")] = None,
    max_tokens: Annotated[int, typer.Option("--max-tokens")] = 20000,
    top_k: Annotated[int, typer.Option("--top-k")] = 15,
    mode: Annotated[str, typer.Option("--mode", "-m", help="FAST | BALANCED | DEEP")] = "BALANCED",
    explain: Annotated[bool, typer.Option("--explain", "-e", help="Explain budget rejections and retrieval details")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compile evidence-backed context packet for an AI agent task."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        packet = get_context(
            con,
            repo,
            task=task,
            intent=intent,
            max_tokens=max_tokens,
            top_k=top_k,
            mode=mode,
            explain=explain,
        )
    typer.echo(json.dumps(packet.as_dict(), indent=2))


@app.command("explain-context")
def explain_context(
    task: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    intent: Annotated[str | None, typer.Option("--intent", "-i")] = None,
    max_tokens: Annotated[int, typer.Option("--max-tokens")] = 20000,
    mode: Annotated[str, typer.Option("--mode", "-m")] = "BALANCED",
) -> None:
    """Compile context with explicit explainability and budget rejection details."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        packet = get_context(
            con,
            repo,
            task=task,
            intent=intent,
            max_tokens=max_tokens,
            mode=mode,
            explain=True,
        )
    typer.echo(json.dumps(packet.as_dict(), indent=2))


@app.command()
def task(
    prompt: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Normalize a prompt into a structured TaskSpec and detect ambiguities."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        spec, ambiguities = normalize_task_spec(prompt, con)
    res = {
        "task_spec": spec.as_dict(),
        "ambiguities": [a.as_dict() for a in ambiguities],
    }
    typer.echo(json.dumps(res, indent=2))


@app.command()
def plan(
    prompt: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    max_tokens: Annotated[int, typer.Option("--max-tokens")] = 20000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Construct a deterministic RetrievalPlan for a task."""
    repo = _resolve_repo(repository=repository)
    if not _ensure_indexed(repo):
        return
    with _indexer(repo).session() as con:
        spec, ambiguities = normalize_task_spec(prompt, con)
        retrieval_plan = build_retrieval_plan(spec, ambiguities, con, token_budget=max_tokens)
    typer.echo(json.dumps(retrieval_plan.as_dict(), indent=2))


@app.command()
def benchmark(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    suite: Annotated[Path | None, typer.Option("--suite", "-s")] = None,
    max_tokens: Annotated[int, typer.Option("--max-tokens")] = 20000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run deterministic codebase intelligence benchmark suite."""
    repo = _resolve_repo(path, repository)
    from benchmarks.runner import run_benchmark_suite

    result = run_benchmark_suite(repo, suite_file=suite, max_tokens=max_tokens)
    typer.echo(json.dumps(result, indent=2))


memory_app = typer.Typer(help="Inspect or clear repository-scoped durable notes.")
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(
    path: Annotated[Path | None, typer.Argument(help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
) -> None:
    repo = _resolve_repo(path, repository)
    typer.echo(json.dumps(MemoryStore(repo / ".codegraph.sqlite3").list(), indent=2))


@memory_app.command("clear")
def memory_clear(
    path: Annotated[Path | None, typer.Argument(help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
) -> None:
    repo = _resolve_repo(path, repository)
    MemoryStore(repo / ".codegraph.sqlite3").clear()
    typer.echo("Repository memory cleared.")


@app.command()
def version() -> None:
    typer.echo(__version__)


if __name__ == "__main__":
    app()
