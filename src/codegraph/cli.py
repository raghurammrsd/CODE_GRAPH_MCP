from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from codegraph import __version__
from codegraph.architecture import get_architecture
from codegraph.cli_output import cli_echo
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
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
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
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress and summary output")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show phase progress, timings, memory, and WAL stats")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON summary and phase telemetry")] = False,
) -> None:
    """Securely index supported source files, skipping unchanged content."""
    from codegraph.indexing.telemetry import IndexingTelemetry, format_progress_block

    repo = _resolve_repo(path, repository)
    idx_inst = _indexer(repo)

    _PHASE_LABELS = {
        "repository_scan": "Repository Scan",
        "ast_parsing": "AST Parsing & Extraction",
        "post_processing": "Post-Processing",
        "symbol_resolution": "Symbol Resolution",
        "relationship_resolution": "Relationship Resolution",
        "database_analysis": "Database Analysis",
        "final_commit_checkpoint": "Final Commit & Checkpoint",
    }

    def _on_progress(phase_key: str, current: int, total: int, tel: IndexingTelemetry) -> None:
        if not verbose or quiet or json_output:
            return
        label = _PHASE_LABELS.get(phase_key, phase_key)
        block = format_progress_block(
            label,
            current,
            total,
            tel.total_elapsed_seconds or (time.perf_counter() - tel.started_at),
            memory_mb=tel.peak_rss_mb,
        )
        typer.echo(block)

    import time

    result = idx_inst.index(progress_callback=_on_progress if verbose else None, catch_interrupt=True)
    tel = idx_inst.last_telemetry

    if json_output:
        payload: dict[str, object] = dict(result)
        if tel is not None:
            payload["telemetry"] = tel.as_dict()
        typer.echo(json.dumps(payload))
        if result.get("interrupted"):
            raise typer.Exit(code=130)
        return

    if quiet:
        if result.get("interrupted"):
            raise typer.Exit(code=130)
        return

    if verbose and tel is not None:
        typer.echo(
            f"Summary: elapsed={tel.total_elapsed_seconds:.3f}s "
            f"peak_rss={tel.peak_rss_mb:.1f}MB "
            f"max_wal={tel.max_wal_size_mb:.2f}MB "
            f"final_wal={tel.final_wal_size_mb:.2f}MB "
            f"commits={tel.batch_commits} checkpoints={tel.wal_checkpoints}"
        )
        for p_name, p_metrics in tel.phases.items():
            if p_metrics.elapsed_seconds > 0 or p_metrics.items_processed > 0 or p_metrics.files_processed > 0:
                typer.echo(
                    f"  [{p_name}] {p_metrics.elapsed_seconds * 1000:.1f}ms "
                    f"files={p_metrics.files_processed} items={p_metrics.items_processed} "
                    f"writes={p_metrics.db_writes}"
                )

    typer.echo(" ".join(f"{k}={v}" for k, v in result.items()))
    if result.get("interrupted"):
        raise typer.Exit(code=130)


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
        indexed_cnt = result.get("indexed", result.get("indexed_files", 0))
        typer.echo(f"Initialized CodeGraph repository at {target_repo.resolve()} (indexed {indexed_cnt} files)")


@app.command()
def watch(
    path: Annotated[Path | None, typer.Argument(help="Repository path to watch (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    debounce_ms: Annotated[int, typer.Option("--debounce", "--debounce-ms", help="Debounce delay in milliseconds")] = 250,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress real-time change logs")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show verbose reindex logs")] = False,
) -> None:
    """Watch repository for changes and update index in real-time (< 15ms per file)."""
    target_repo = _resolve_repo(path, repository)
    from codegraph.watcher import RepositoryWatcher

    def _on_batch_complete(res: dict[str, Any]) -> None:
        if quiet:
            return
        reindexed = res.get("reindexed", [])
        deleted = res.get("deleted", [])
        skipped = res.get("skipped", [])
        ms = res.get("elapsed_ms", 0.0)
        gen = res.get("generation")
        gen_str = f" [gen {gen}]" if gen is not None else ""

        parts: list[str] = []
        if reindexed:
            parts.append(f"reindexed {len(reindexed)} file(s): {', '.join(str(p) for p in reindexed[:3])}{'...' if len(reindexed) > 3 else ''}")
        if deleted:
            parts.append(f"removed {len(deleted)} file(s): {', '.join(str(p) for p in deleted[:3])}{'...' if len(deleted) > 3 else ''}")
        if verbose and skipped:
            parts.append(f"skipped {len(skipped)} unchanged file(s)")

        if parts:
            typer.echo(f"[WATCH] {'; '.join(parts)} in {ms:.1f}ms{gen_str}")
        elif verbose:
            typer.echo(f"[WATCH] Clean flush in {ms:.1f}ms{gen_str}")

    typer.echo(f"Watching {target_repo.resolve()} for changes (debounce {debounce_ms}ms)... Press Ctrl+C to stop.")
    watcher = RepositoryWatcher(
        target_repo,
        debounce_delay_sec=debounce_ms / 1000.0,
        on_batch_complete=_on_batch_complete,
    )
    watcher.run_forever()


@app.command()
def search(
    query: str,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    top_k: int = 10,
    ext: Annotated[str | None, typer.Option("--ext", "-e", help="Comma-separated file extensions (e.g. ts,tsx,jsx)")] = None,
    package: Annotated[str | None, typer.Option("--package", "-p", help="Monorepo package scope filter (e.g. dundoo-react)")] = None,
    path_prefix: Annotated[str | None, typer.Option("--path-prefix", help="Subdirectory path prefix filter")] = None,
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

    file_types = [e.strip().lstrip(".") for e in ext.split(",") if e.strip()] if ext else None
    effective_path_filter: str | None = path_prefix
    if package:
        from codegraph.monorepo import discover_workspace
        ws = discover_workspace(repo)
        pkg_info = ws.packages.get(package)
        if pkg_info:
            effective_path_filter = pkg_info.root_path
        else:
            effective_path_filter = package

    with _indexer(repo).session() as con:
        if file_types or effective_path_filter:
            from codegraph.search.hybrid import search_code as search_code_rich
            raw_hits = search_code_rich(
                con,
                query,
                repo_path=repo,
                path_filter=effective_path_filter,
                file_types=file_types,
                top_k=top_k,
            )
            result = [
                {
                    "file": str(h.get("path") or h.get("file") or ""),
                    "start_line": int(str(h.get("line") or h.get("start_line") or "1")),
                    "end_line": int(str(h.get("line") or h.get("end_line") or "1")),
                    "symbol": str(h.get("symbol") or ""),
                    "score": float(str(h.get("score") or "1.0")),
                    "snippet": str(h.get("snippet") or h.get("matched_text") or ""),
                }
                for h in raw_hits
            ]
        else:
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
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum number of routes to return")] = None,
    offset: Annotated[int, typer.Option("--offset", help="Number of routes to skip")] = 0,
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

        if limit is not None:
            safe_offset = max(0, offset)
            safe_limit = max(0, limit)
            route_list = route_list[safe_offset : safe_offset + safe_limit]

        if json_output:
            typer.echo(json.dumps(route_list, indent=2))
        else:
            if not route_list:
                typer.echo("No framework routes indexed or matching criteria.")
                return
            typer.echo(f"Found {len(route_list)} route(s):")
            for r in route_list:
                typer.echo(f"  [{r['http_method']}] {r['route_path']} -> {r['handler']} ({r['file']}:{r['line']}) [{r['framework']}]")


@app.command("schema-drift")
def schema_drift(
    route: Annotated[str | None, typer.Option("--route", help="Route path or endpoint to check for schema drift")] = None,
    handler: Annotated[str | None, typer.Option("--handler", "-h", help="Handler symbol to check for schema drift")] = None,
    table: Annotated[str | None, typer.Option("--table", "-t", help="Target table name (optional, inferred from mutation lineage)")] = None,
    schema: Annotated[str | None, typer.Option("--schema", "-s", help="Schema class name (optional, inferred from handler signature)")] = None,
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON array")] = False,
) -> None:
    """Detect Pydantic / Form validation drift against destination database table columns."""
    from codegraph.database.schema_drift import detect_schema_drift

    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        return
    target = route or handler or ""
    if not target:
        typer.echo("Error: Please specify --route or --handler to check for schema drift.")
        raise typer.Exit(code=1)
    with _indexer(repo).session() as con:
        res = detect_schema_drift(con, repo, route_or_handler=target, target_table=table, schema_name=schema)
    if json_output:
        typer.echo(json.dumps(res, indent=2))
    else:
        if res.get("status") == "error":
            typer.echo(f"Error: {res.get('error')}")
            raise typer.Exit(code=1)
        typer.echo(f"Schema Drift Report for {target} -> {res.get('target_table')} ({res.get('schema_name')}):")
        typer.echo(f"  Mode:         {res.get('schema_mode', 'STATIC_TYPED')}")
        recon = res.get("runtime_reconciliation", {})
        if recon.get("is_observed"):
            typer.echo(f"  Runtime SQL:  Observed ({recon.get('observation_count')} query executions)")
            if recon.get("last_sql_sample"):
                typer.echo(f"  Sample Query: {recon.get('last_sql_sample')}")
        else:
            typer.echo("  Runtime SQL:  NOT_OBSERVED_AT_RUNTIME (Run dev server or ingest traces to observe live queries)")
        typer.echo(f"  Total Issues: {res.get('drift_count')} (Critical: {res.get('critical_count')}, Warning: {res.get('warning_count')}, Info: {res.get('info_count')})")
        for iss in res.get("issues", []):
            typer.echo(f"  [{iss['severity']}] {iss['drift_type']} on '{iss['field_name']}': {iss['message']}")


@app.command("api-drift")
def api_drift_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Detect cross-language client-server API contract drift (404s, 405s, and TypeScript-to-Backend type drift)."""
    from codegraph.api_drift import detect_api_contract_drift

    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        return

    with _indexer(repo).session() as con:
        report = detect_api_contract_drift(con, repo)

    if json_output:
        typer.echo(json.dumps(report.as_dict(), indent=2))
    else:
        if not report.has_drift:
            typer.echo("No API contract drift detected.")
            typer.echo(f"Verified {report.total_client_calls} client data fetches against {report.total_backend_routes} backend routes ({report.matched_calls} matched).")
        else:
            typer.echo(f"API Contract Drift Detected ({len(report.drifts)} issues):")
            typer.echo(f"Client Calls: {report.total_client_calls} | Backend Routes: {report.total_backend_routes} | Matched: {report.matched_calls}\n")
            for d in report.drifts:
                typer.echo(f"  [{d.severity}] {d.kind}")
                typer.echo(f"    Client:  {d.client_method} {d.client_route} ({d.client_file}:{d.client_line})")
                if d.backend_route:
                    typer.echo(f"    Backend: {d.backend_route} -> {d.backend_handler} ({d.backend_file})")
                if d.field_name:
                    typer.echo(f"    Field:   {d.field_name} (Client: {d.client_field_type} vs Backend: {d.backend_field_type})")
                typer.echo(f"    Message: {d.message}\n")


@app.command("api_drift", hidden=True)
def api_drift_alias(
    path: Annotated[Path | None, typer.Argument(help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Alias for api-drift."""
    api_drift_cmd(path=path, repository=repository, json_output=json_output)


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


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_cmd(
    ctx: typer.Context,
    command: Annotated[list[str] | None, typer.Argument(help="Development command and arguments to execute")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    sample_rate: Annotated[float, typer.Option("--sample-rate", help="Sampling rate for trace capture (0.0..1.0)")] = 1.0,
) -> None:
    """Execute a development command or server with transparent runtime trace capture."""
    full_cmd = (command or []) + ctx.args
    if not full_cmd:
        cli_echo("Error: Command cannot be empty. Usage: codegraph run <command> [args...]")
        raise typer.Exit(code=1)

    repo = _resolve_repo(None, repository)
    from codegraph.runtime.runner import run_with_telemetry

    exit_code = run_with_telemetry(full_cmd, repository=repo, sample_rate=sample_rate)
    raise typer.Exit(code=exit_code)


@app.command("ingest")
def ingest_cli_cmd(
    source: Annotated[Path, typer.Argument(help="Path to OpenTelemetry JSON/JSONL, SQL query log, or trace file")],
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    format: Annotated[str, typer.Option("--format", "-f", help="Trace format: auto | otel | json | sql_log")] = "auto",
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Ingest runtime traces (OpenTelemetry, JSON, or SQL query logs) into repository index."""
    repo = _resolve_repo(None, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    if not source.exists():
        cli_echo(f"Error: Trace source file '{source}' does not exist.")
        raise typer.Exit(code=1)

    content = source.read_text(encoding="utf-8", errors="replace")
    indexer = _indexer(repo)
    with indexer.session() as con:
        from codegraph.runtime.ingestor import ingest_runtime_traces

        res = ingest_runtime_traces(con, content, repository=repo, format=format)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        cli_echo("Runtime Ingestion Complete:")
        cli_echo(f"  Events Ingested:  {res.get('events_ingested', 0)}")
        cli_echo(f"  Edges Upserted:   {res.get('edges_upserted', 0)}")
        cli_echo(f"  Generation:       {res.get('runtime_generation', 1)}")


def _run_server(
    path: Path | None,
    repository: Path | None,
    profile: str,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    repo = _resolve_repo(path, repository)
    from codegraph.mcp import create_server
    from codegraph.process_lifecycle import run_mcp_stdio_server

    if transport.lower() == "sse":
        server = create_server(repo, profile=profile, host=host, port=port)
        server.run(transport="sse")
    else:
        server = create_server(repo, profile=profile)
        run_mcp_stdio_server(server, repo, profile=profile)


@app.command()
def serve(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    profile: Annotated[str, typer.Option("--profile", help="Tool profile: core | minimal | developer | full")] = "full",
    transport: Annotated[str, typer.Option("--transport", "-t", help="MCP transport: stdio | sse")] = "stdio",
    host: Annotated[str, typer.Option("--host", help="Host for SSE server")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port for SSE server")] = 8765,
) -> None:
    """Run the CodeGraph MCP server via stdio or SSE transport."""
    _run_server(path, repository, profile, transport=transport, host=host, port=port)


mcp_app = typer.Typer(help="MCP server commands.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    profile: Annotated[str, typer.Option("--profile", help="Tool profile: core | graph | minimal | developer | full")] = "full",
    transport: Annotated[str, typer.Option("--transport", "-t", help="MCP transport: stdio | sse")] = "stdio",
    host: Annotated[str, typer.Option("--host", help="Host for SSE server")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port for SSE server")] = 8765,
) -> None:
    """Run the CodeGraph MCP server via stdio or SSE transport."""
    _run_server(path, repository, profile, transport=transport, host=host, port=port)


def _execute_stop(
    path: Path | None,
    repository: Path | None,
    all_processes: bool,
    timeout: float,
    json_output: bool,
) -> None:
    from codegraph.process_lifecycle import stop_codegraph_processes

    target_repo: Path | None = None
    if not all_processes:
        target_repo = _resolve_repo(path, repository)

    res = stop_codegraph_processes(
        repository=target_repo,
        stop_all=all_processes,
        timeout_sec=timeout,
    )
    if json_output:
        cli_echo(json.dumps(res.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(res.format_human())


@app.command("stop")
def stop_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    all_processes: Annotated[bool, typer.Option("--all", "-a", help="Stop all CodeGraph-owned MCP processes across all repositories")] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="Graceful shutdown timeout in seconds before force-kill")] = 3.0,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Safely stop running CodeGraph MCP background processes and release file locks."""
    _execute_stop(path, repository, all_processes, timeout, json_output)


@mcp_app.command("stop")
def mcp_stop_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    all_processes: Annotated[bool, typer.Option("--all", "-a", help="Stop all CodeGraph-owned MCP processes across all repositories")] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="Graceful shutdown timeout in seconds before force-kill")] = 3.0,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Safely stop running CodeGraph MCP background processes and release file locks."""
    _execute_stop(path, repository, all_processes, timeout, json_output)


@mcp_app.command("kill")
def mcp_kill_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    all_processes: Annotated[bool, typer.Option("--all", "-a", help="Stop all CodeGraph-owned MCP processes across all repositories")] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="Graceful shutdown timeout in seconds before force-kill")] = 1.0,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Alias for `codegraph stop` to terminate CodeGraph MCP processes and release locks."""
    _execute_stop(path, repository, all_processes, timeout, json_output)


@mcp_app.command("doctor")
def mcp_doctor(
    profile: Annotated[str, typer.Option("--profile", help="Tool profile to validate")] = "full",
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic JSON report")] = False,
) -> None:
    """Run end-to-end MCP server startup, handshake, tool discovery, and fixture query diagnostics."""
    from codegraph.mcp_diagnostics import run_mcp_doctor

    report = run_mcp_doctor(profile=profile)
    if json_output:
        cli_echo(json.dumps(report.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(report.format_human())
    if not report.healthy:
        raise typer.Exit(code=1)


@mcp_app.command("config-check")
def mcp_config_check(
    path: Annotated[Path | None, typer.Argument(help="Workspace path (default: current directory)")] = None,
    config_file: Annotated[Path | None, typer.Option("--config", "-c", help="Explicit MCP config JSON path")] = None,
    include_example: Annotated[bool, typer.Option("--include-example", help="Include .agents/mcp_config.json.example")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON report")] = True,
) -> None:
    """Validate MCP configuration read-only without mutating files or exposing secrets."""
    from codegraph.mcp_diagnostics import check_mcp_configuration

    ws = (path or Path.cwd()).resolve()
    rep = check_mcp_configuration(workspace_dir=ws, config_file=config_file, include_example=include_example)
    if json_output:
        cli_echo(json.dumps(rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"{rep.status.value}: {rep.message}")


@mcp_app.command("capabilities")
def mcp_capabilities() -> None:
    """Output the deterministic machine-readable CodeGraph capability manifest."""
    from codegraph.agent_capabilities import get_capability_manifest

    cli_echo(json.dumps(get_capability_manifest(), indent=2), json_mode=True)


@mcp_app.command("rules")
def mcp_rules(
    agent: Annotated[str, typer.Option("--agent", "-a", help="Target agent (antigravity, claude, cursor, gemini, codex, cline, agents)")] = "antigravity",
) -> None:
    """Render deterministic CodeGraph agent rules for the specified agent."""
    from codegraph.agent_rules import render_agent_rules

    cli_echo(render_agent_rules(agent=agent), nl=False)


@app.command()
def doctor(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    resources: Annotated[bool, typer.Option("--resources")] = False,
    database: Annotated[bool, typer.Option("--database", help="Run comprehensive database integrity and schema checks")] = False,
    processes: Annotated[bool, typer.Option("--processes", help="Inspect active CodeGraph processes, parent state, and stale PID files")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check repository and index readiness, database integrity, process lifecycle, and freshness."""
    if processes:
        from codegraph.process_lifecycle import discover_codegraph_processes

        discovery = discover_codegraph_processes(clean_stale=True)
        if json_output:
            cli_echo(json.dumps(discovery.as_dict(), indent=2), json_mode=True)
        else:
            cli_echo(discovery.format_human())
        return

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


@app.command()
def install(
    path: Annotated[Path | None, typer.Argument(help="Project path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Project path")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm installation without interactive prompt")] = False,
    target: Annotated[
        str,
        typer.Option("--target", "-t", help="Target agents: auto | all | claude,cursor,antigravity,codex,gemini,cline"),
    ] = "auto",
    location: Annotated[
        str,
        typer.Option("--location", "-l", help="Installation scope: local | global"),
    ] = "local",
    print_config: Annotated[
        str | None,
        typer.Option("--print-config", help="Print MCP configuration and rules for a specific agent without modifying files"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change without modifying any files")] = False,
    repair: Annotated[bool, typer.Option("--repair", help="Back up and repair malformed JSON configuration files")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Detect supported AI agents, configure CodeGraph MCP, install rules/skills, and verify health."""
    from codegraph.errors import CodeGraphError
    from codegraph.installer import (
        AGENT_ALIASES,
        format_marker_block,
        render_agent_mcp_config_snippet,
        run_install,
    )

    if print_config is not None:
        try:
            canon = AGENT_ALIASES.get(print_config.strip().lower(), print_config.strip().lower())
            snippet = render_agent_mcp_config_snippet(canon)
            from codegraph.agent_rules import render_agent_rules

            rules_txt = render_agent_rules(canon)
            if json_output:
                cli_echo(
                    json.dumps(
                        {
                            "status": "ok",
                            "agent": canon,
                            "mcp_config": snippet,
                            "instructions_block": format_marker_block(rules_txt),
                        },
                        indent=2,
                    ),
                    json_mode=True,
                )
            else:
                cli_echo(f"# MCP Configuration ({canon})\n")
                cli_echo(json.dumps(snippet, indent=2), json_mode=True)
                cli_echo(f"\n# Instructions Block ({canon})\n")
                cli_echo(format_marker_block(rules_txt), nl=False)
            return
        except CodeGraphError as exc:
            if json_output:
                cli_echo(json.dumps(exc.to_response(), indent=2), json_mode=True)
            else:
                cli_echo(f"Error [{exc.code}]: {exc.message}")
                if exc.next_action and exc.next_action.get("command"):
                    cli_echo(f"\nTry:\n  {exc.next_action['command']}")
            raise typer.Exit(code=1) from exc

    ws = _resolve_repo(path, repository)

    def _confirm(preview_rep: object) -> bool:
        from codegraph.installer import InstallerReport

        assert isinstance(preview_rep, InstallerReport)
        if not json_output:
            cli_echo(preview_rep.format_preview_human())
            cli_echo("")
            cli_echo("Continue? [y/N] ", nl=False)
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        if not json_output:
            cli_echo("")
        return ans in ("y", "yes")

    try:
        report = run_install(
            workspace=ws,
            target=target,
            location=location,
            dry_run=dry_run,
            allow_malformed_repair=repair,
            confirm_fn=None if (yes or dry_run) else _confirm,
        )
    except CodeGraphError as exc:
        if json_output:
            cli_echo(json.dumps(exc.to_response(), indent=2), json_mode=True)
        else:
            cli_echo(f"Error [{exc.code}]: {exc.message}")
            if exc.next_action and exc.next_action.get("reason"):
                cli_echo(f"\nExpected:\n  {exc.next_action['reason']}")
            if exc.next_action and exc.next_action.get("command"):
                cli_echo(f"\nTry:\n  {exc.next_action['command']}")
        raise typer.Exit(code=1) from exc

    if json_output:
        cli_echo(json.dumps(report.as_dict(), indent=2), json_mode=True)
    else:
        if yes and not dry_run:
            cli_echo(report.format_preview_human())
            cli_echo("")
        cli_echo(report.format_human())

    if report.status == "error":
        raise typer.Exit(code=1)


@app.command()
def uninstall(
    path: Annotated[Path | None, typer.Argument(help="Project path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Project path")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm uninstall without interactive prompt")] = False,
    target: Annotated[
        str,
        typer.Option("--target", "-t", help="Target agents: all | auto | claude,cursor,antigravity,codex,gemini,cline"),
    ] = "all",
    location: Annotated[
        str,
        typer.Option("--location", "-l", help="Installation scope: local | global"),
    ] = "local",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be removed without changing any files")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Remove CodeGraph-managed agent integrations while preserving user config and project index."""
    from codegraph.errors import CodeGraphError
    from codegraph.installer import InstallerReport, run_uninstall

    ws = _resolve_repo(path, repository)

    def _confirm_uninstall(preview_rep: InstallerReport) -> bool:
        if not json_output:
            cli_echo("CodeGraph Uninstaller\n")
            for c in preview_rep.changes:
                if c.action in ("remove", "modify"):
                    cli_echo(f"  - {c.display_path} ({c.action})")
            cli_echo("\nContinue? [y/N] ", nl=False)
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        if not json_output:
            cli_echo("")
        return ans in ("y", "yes")

    try:
        report = run_uninstall(
            workspace=ws,
            target=target,
            location=location,
            dry_run=dry_run,
            confirm_fn=None if (yes or dry_run) else _confirm_uninstall,
        )
    except CodeGraphError as exc:
        if json_output:
            cli_echo(json.dumps(exc.to_response(), indent=2), json_mode=True)
        else:
            cli_echo(f"Error [{exc.code}]: {exc.message}")
            if exc.next_action and exc.next_action.get("command"):
                cli_echo(f"\nTry:\n  {exc.next_action['command']}")
        raise typer.Exit(code=1) from exc

    if json_output:
        cli_echo(json.dumps(report.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(report.format_human())


@app.command()
def uninit(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm removal without interactive prompt")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview index files that would be removed")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output deterministic machine-readable JSON")] = False,
) -> None:
    """Remove the current project's CodeGraph index (.codegraph.sqlite3 and .codegraph/) without touching source or git."""
    from codegraph.errors import CodeGraphError
    from codegraph.installer import InstallerReport, run_uninit

    ws = _resolve_repo(path, repository)

    def _confirm_uninit(preview_rep: InstallerReport) -> bool:
        if not json_output:
            cli_echo("Remove CodeGraph project index files?\n")
            for c in preview_rep.changes:
                cli_echo(f"  - {c.display_path}")
            cli_echo("\nContinue? [y/N] ", nl=False)
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        if not json_output:
            cli_echo("")
        return ans in ("y", "yes")

    try:
        report = run_uninit(
            workspace=ws,
            dry_run=dry_run,
            confirm_fn=None if (yes or dry_run) else _confirm_uninit,
        )
    except CodeGraphError as exc:
        if json_output:
            cli_echo(json.dumps(exc.to_response(), indent=2), json_mode=True)
        else:
            cli_echo(f"Error [{exc.code}]: {exc.message}")
        raise typer.Exit(code=1) from exc

    if json_output:
        cli_echo(json.dumps(report.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(report.format_human())


@app.command("git-state")
def git_state_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    sync: Annotated[bool, typer.Option("--sync", help="Incrementally synchronize affected graph state if dirty/stale")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Track current Git branch, HEAD, indexed commit, working-tree modifications, and freshness states (CLEAN, DIRTY, STALE, REINDEXING, ERROR)."""
    from codegraph.git_state import get_git_state, incremental_git_sync

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    if sync:
        with indexer.session() as con:
            res = incremental_git_sync(repo, con=con)
            if json_output:
                cli_echo(json.dumps(res.as_dict(), indent=2), json_mode=True)
            else:
                cli_echo(f"Incremental Sync: {res.status.upper()} ({res.duration_ms:.1f}ms) - {res.detail}")
            return

    with indexer.session() as con:
        rep = get_git_state(repo, con=con)

    if json_output:
        cli_echo(json.dumps(rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Git Repository: {repo}")
        cli_echo(f"Branch:         {rep.branch or 'N/A'}")
        cli_echo(f"Current HEAD:   {rep.current_head[:8] if rep.current_head else 'N/A'}")
        cli_echo(f"Indexed HEAD:   {rep.indexed_head[:8] if rep.indexed_head else 'Not indexed'}")
        cli_echo(f"Freshness:      {rep.freshness.value}")
        cli_echo(f"Status Detail:  {rep.detail}")
        if rep.working_tree.is_dirty:
            cli_echo("\nWorking Tree Changes:")
            if rep.working_tree.modified_files:
                cli_echo(f"  Modified:   {len(rep.working_tree.modified_files)} files ({', '.join(rep.working_tree.modified_files[:3])}...)")
            if rep.working_tree.staged_files:
                cli_echo(f"  Staged:     {len(rep.working_tree.staged_files)} files ({', '.join(rep.working_tree.staged_files[:3])}...)")
            if rep.working_tree.untracked_files:
                cli_echo(f"  Untracked:  {len(rep.working_tree.untracked_files)} files ({', '.join(rep.working_tree.untracked_files[:3])}...)")
            if rep.working_tree.deleted_files:
                cli_echo(f"  Deleted:    {len(rep.working_tree.deleted_files)} files")


@app.command("git-diff")
def git_diff_cmd(
    base: Annotated[str, typer.Argument(help="Base Git ref or commit (default: HEAD~1)")] = "HEAD~1",
    head: Annotated[str, typer.Argument(help="Head Git ref, commit, or branch (default: HEAD)")] = "HEAD",
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    branch_comparison: Annotated[bool, typer.Option("--branch", "-b", help="Perform hierarchical branch architecture comparison")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Compute structural AST-level difference between Git revisions, commits, or branches."""
    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    if branch_comparison:
        from codegraph.branch_comparison import compare_branch_architecture
        with indexer.session() as con:
            b_rep = compare_branch_architecture(repo, base_branch=base, head_branch=head, con=con)
        if json_output:
            cli_echo(json.dumps(b_rep.as_dict(), indent=2), json_mode=True)
        else:
            cli_echo(f"Branch Architecture Comparison: {base} -> {head}")
            cli_echo(f"Packages: {b_rep.total_packages} | Symbols: {b_rep.total_symbols} (~{b_rep.estimated_tokens} tokens)")
            for pkg in b_rep.packages:
                cli_echo(f"\nPackage: {pkg.package_id}")
                for mod in pkg.modules:
                    cli_echo(f"  Module: {mod.module} ({mod.file_path})")
                    for s in mod.symbols:
                        cli_echo(f"    [{s.change_type}] {s.kind} {s.name}")
                        for rel in s.relationships:
                            cli_echo(f"      -> {rel}")
        return

    from codegraph.structural_diff import compare_revisions
    with indexer.session() as con:
        s_rep = compare_revisions(repo, base=base, head=head, con=con)

    if json_output:
        cli_echo(json.dumps(s_rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Structural Diff: {base} -> {head}")
        cli_echo(f"Files Changed:   {s_rep.total_file_changes} (Added: {len(s_rep.added_files)}, Modified: {len(s_rep.modified_files)}, Deleted: {len(s_rep.deleted_files)}, Renamed: {len(s_rep.renamed_files)})")
        cli_echo(f"Symbols Changed: {s_rep.total_symbol_changes} (Added: {len(s_rep.added_symbols)}, Modified: {len(s_rep.changed_symbols)}, Removed: {len(s_rep.removed_symbols)})")
        if s_rep.changed_routes:
            cli_echo(f"Changed Routes:  {len(s_rep.changed_routes)}")
            for r in s_rep.changed_routes:
                cli_echo(f"  [{r.change_type}] {r.method} {r.path} -> {r.handler}")
        if s_rep.affected_tests:
            cli_echo(f"Affected Tests:  {len(s_rep.affected_tests)} ({', '.join(s_rep.affected_tests[:5])})")


@app.command("impact")
def impact_cmd(
    base: Annotated[str, typer.Option("--base", "-b", help="Base Git ref (default: HEAD~1)")] = "HEAD~1",
    head: Annotated[str, typer.Option("--head", "-h", help="Head Git ref (default: HEAD)")] = "HEAD",
    symbol: Annotated[str | None, typer.Option("--symbol", "-s", help="Analyze blast radius for a specific symbol on-demand")] = None,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max caller traversal depth")] = 2,
    max_results: Annotated[int, typer.Option("--max-results", "-m", help="Max items per category")] = 30,
    tree: Annotated[bool, typer.Option("--tree", "-t", help="Display visual impact tree")] = False,
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Compute deep downstream change impact across callers, frontend UI, framework routes, tests, and DB."""
    from codegraph.change_impact import get_deep_change_impact

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    with indexer.session() as con:
        imp = get_deep_change_impact(
            repo, con, base=base, head=head, max_depth=depth, max_results=max_results, symbol=symbol
        )

    if json_output:
        cli_echo(json.dumps(imp.as_dict(), indent=2), json_mode=True)
    else:
        target_title = f"Symbol '{symbol}'" if symbol else f"Git Diff: {base} -> {head}"
        cli_echo(f"Semantic Change Impact Analysis: {target_title}")
        cli_echo(f"  PR Risk Level:        [{imp.risk_level}] (Score: {imp.blast_radius_score} / 100)")
        cli_echo(f"  Total Impacted Items: {imp.total_impacted_count}")
        cli_echo(f"  Direct Callers:       {len(imp.direct_callers)}")
        cli_echo(f"  Transitive Callers:   {len(imp.transitive_callers)}")
        if imp.affected_frontend_components:
            cli_echo(f"  Frontend UI Impact:   {len(imp.affected_frontend_components)} components")
        cli_echo(f"  Affected Routes:      {len(imp.affected_routes)}")
        cli_echo(f"  Covering Tests:       {len(imp.affected_tests)}")
        cli_echo(f"  DB Writers:           {len(imp.db_writers)}")
        cli_echo(f"  Monorepo Packages:    {len(imp.affected_packages)}")

        if imp.breaking_change_flags:
            cli_echo(f"\n  ⚠️  Breaking Risk Flags: {', '.join(imp.breaking_change_flags)}")

        if imp.recommended_test_command:
            cli_echo(f"\n  🎯 Recommended Test Run: {imp.recommended_test_command}")

        if tree or imp.total_impacted_count > 0:
            cli_echo("\nImpact Tree:")
            for s in imp.changed_symbols[:10]:
                cli_echo(f"  └── [{s.get('change_type', 'MODIFIED')}] {s.get('path', '')}::{s.get('name', '')}")
            for fe in imp.affected_frontend_components[:5]:
                cli_echo(f"      ├── UI: {fe.file}::{fe.name} (fetches route)")
            for c in imp.direct_callers[:8]:
                cli_echo(f"      ├── CALLER: {c.file}::{c.name} (depth 1)")
            for r in imp.affected_routes[:5]:
                cli_echo(f"      ├── ROUTE: {r.name} -> {r.file}")
            for t in imp.affected_tests[:5]:
                cli_echo(f"      ├── TEST: {t.file}::{t.name}")
            for db in imp.db_writers[:5]:
                cli_echo(f"      └── DB: {db.relationship} {db.name} in {db.file}")


@app.command("git-impact", hidden=True)
def git_impact_alias(
    base: Annotated[str, typer.Argument(help="Base Git ref (default: HEAD~1)")] = "HEAD~1",
    head: Annotated[str, typer.Argument(help="Head Git ref (default: HEAD)")] = "HEAD",
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max caller traversal depth")] = 2,
    max_results: Annotated[int, typer.Option("--max-results", "-m", help="Max items per category")] = 30,
    tree: Annotated[bool, typer.Option("--tree", "-t", help="Display visual impact tree")] = False,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Backward-compatible alias for codegraph impact."""
    impact_cmd(
        base=base,
        head=head,
        depth=depth,
        max_results=max_results,
        tree=tree,
        path=path,
        repository=repository,
        json_output=json_output,
    )


@app.command("git-conflicts")
def git_conflicts_cmd(
    base: Annotated[str, typer.Argument(help="Base Git branch (default: main)")] = "main",
    head: Annotated[str, typer.Argument(help="Head Git branch (default: HEAD)")] = "HEAD",
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Detect semantic and contract merge conflicts between branches (calling deleted symbols, broken call signatures, or missing route handlers)."""
    from codegraph.semantic_conflicts import detect_semantic_conflicts

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    with indexer.session() as con:
        rep = detect_semantic_conflicts(repo, base_branch=base, head_branch=head, con=con)

    if json_output:
        cli_echo(json.dumps(rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Semantic Conflict Analysis: {base} <-> {head}")
        cli_echo(f"Status:          {'[!] CONFLICTS DETECTED' if rep.has_conflicts else '[OK] CLEAN (0 conflicts)'}")
        cli_echo(f"Total Conflicts: {rep.total_conflicts}")
        cli_echo(f"Summary:         {rep.summary}")
        if rep.conflicts:
            cli_echo("\nDetected Semantic Conflicts:")
            for c in rep.conflicts:
                cli_echo(f"\n  [{c.severity.value}] {c.conflict_type.value}: {c.symbol}")
                cli_echo(f"    Description: {c.description}")
                cli_echo(f"    Base ({base}): {c.base_file} ({c.base_evidence})")
                cli_echo(f"    Head ({head}): {c.head_file} ({c.head_evidence})")


@app.command("check-freshness")
def check_freshness_cli_cmd(
    task: Annotated[str, typer.Argument(help="Task prompt to verify context freshness for")] = "",
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Validate whether compiled context remains VALID, PARTIALLY_STALE, or STALE against repository changes."""
    from codegraph.context import get_context
    from codegraph.context_freshness import check_context_freshness

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    with indexer.session() as con:
        # Generate baseline context if task provided
        ctx = get_context(con, repo, task or "general repository overview", mode="FAST")
        rep = check_context_freshness(ctx, repo, con=con)

    if json_output:
        cli_echo(json.dumps(rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Context Freshness Status: {rep.status.value}")
        cli_echo(f"Reason:                  {rep.reason}")
        cli_echo(f"Recommended Action:      {rep.recommended_action}")
        if rep.changed_relevant_files:
            cli_echo(f"Changed Relevant Files:  {', '.join(rep.changed_relevant_files)}")
        if rep.unrelated_changed_files:
            cli_echo(f"Unrelated Changed Files: {len(rep.unrelated_changed_files)} file(s)")


@app.command("symbol-history")
def symbol_history_cli_cmd(
    symbol: Annotated[str, typer.Argument(help="Symbol name to trace across Git history")],
    file_path: Annotated[str | None, typer.Option("--file", "-f", help="File path where symbol is located")] = None,
    max_commits: Annotated[int, typer.Option("--max-commits", "-m", help="Max commits to inspect")] = 15,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Trace deterministic symbol evolution across Git history: introduced, modified, moved, renamed, or deleted."""
    from codegraph.symbol_history import trace_symbol_history

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    with indexer.session() as con:
        rep = trace_symbol_history(repo, symbol=symbol, path=file_path, con=con, max_commits=max_commits)

    if json_output:
        cli_echo(json.dumps(rep.as_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Symbol History: {symbol}")
        cli_echo(f"Status:         {rep.status} ({rep.detail})")
        for ev in rep.events:
            cli_echo(f"\n  [{ev.event_type}] Commit {ev.commit_sha[:8]} on {ev.date} by {ev.author}")
            cli_echo(f"    Message:  {ev.message}")
            cli_echo(f"    Location: {ev.path}")
            cli_echo(f"    Evidence: {ev.evidence} (confidence: {ev.confidence})")


refactor_app = typer.Typer(no_args_is_help=True, help="Deterministic, syntax-validated AST refactoring and atomic rollback.")
app.add_typer(refactor_app, name="refactor")


@refactor_app.command("rename")
def refactor_rename_cli_cmd(
    target: Annotated[str, typer.Argument(help="Exact symbol name or qualified name to rename")],
    new_name: Annotated[str, typer.Argument(help="New valid Python identifier name")],
    apply: Annotated[bool, typer.Option("--apply", help="Apply changes atomically to disk (default is dry-run)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Force rename despite UNKNOWN/POSSIBLE uncertainty")] = False,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Perform deterministic, syntax-validated, transaction-safe AST rename."""
    from codegraph.refactor.renamer import execute_safe_rename

    repo = _resolve_repo(path, repository)
    indexer = _indexer(repo)

    with indexer.session() as con:
        result = execute_safe_rename(
            repository=repo,
            con=con,
            target=target,
            new_name=new_name,
            dry_run=not apply,
            force_uncertain=force,
        )

    if json_output:
        cli_echo(json.dumps(result.to_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Refactor Status:      {result.status}")
        cli_echo(f"Target:               {result.target_symbol} -> {result.new_name}")
        cli_echo(f"Risk:                 {result.risk}")
        cli_echo(f"Files Changed:        {result.files_changed}")
        cli_echo(f"Spans Count:          {result.spans_count}")
        if result.rollback_id:
            cli_echo(f"Rollback ID:          {result.rollback_id}")
        if result.uncertainty_reasons:
            cli_echo("\nUncertainty Reasons:")
            for reason in result.uncertainty_reasons:
                cli_echo(f"  - {reason}")
        if result.tests_affected:
            cli_echo(f"Affected Tests:       {', '.join(result.tests_affected)}")
        if result.routes_affected:
            cli_echo(f"Affected Routes:      {', '.join(result.routes_affected)}")
        if result.diffs:
            cli_echo("\nUnified Diffs:")
            for p, diff in result.diffs.items():
                cli_echo(f"--- {p} ---")
                cli_echo(diff)
        if result.errors:
            cli_echo("\nErrors:")
            for err in result.errors:
                cli_echo(f"  ! {err}")


@refactor_app.command("undo")
def refactor_undo_cli_cmd(
    transaction_id: Annotated[str, typer.Argument(help="Transaction ID to rollback")],
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON format")] = False,
) -> None:
    """Atomically rollback an applied refactoring transaction."""
    from codegraph.refactor.models import RefactorStatus
    from codegraph.refactor.transactions import rollback_refactor

    repo = _resolve_repo(path, repository)
    result = rollback_refactor(repo, transaction_id)
    if result.status == RefactorStatus.ROLLED_BACK:
        try:
            indexer = _indexer(repo)
            indexer.index()
        except Exception:
            pass

    if json_output:
        cli_echo(json.dumps(result.to_dict(), indent=2), json_mode=True)
    else:
        cli_echo(f"Rollback Status: {result.status}")
        cli_echo(f"Transaction ID:  {transaction_id}")
        cli_echo(f"Files Restored:  {result.files_changed}")
        if result.errors:
            cli_echo("\nErrors:")
            for err in result.errors:
                cli_echo(f"  ! {err}")


# ---------------------------------------------------------------------------
# Async Queue Subcommands
# ---------------------------------------------------------------------------
async_app = typer.Typer(
    no_args_is_help=True,
    help="Asynchronous message queues, distributed task linking, and cross-service traces.",
)
app.add_typer(async_app, name="async")


@async_app.command("queues")
def async_queues_cli_cmd(
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """List all detected asynchronous message queues, topics, and task channels."""
    from codegraph.async_queue.traversal import list_async_queues

    repo = _resolve_repo(None, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        queues = list_async_queues(con)

    if json_output:
        cli_echo(json.dumps(queues, indent=2), json_mode=True)
    else:
        if not queues:
            cli_echo("No asynchronous queues, topics, or task channels detected.")
            return

        cli_echo(f"Found {len(queues)} async queue(s):\n")
        for q in queues:
            cli_echo(
                f"  [{q['system'].upper()}] {q['destination']} "
                f"(producers: {q['producer_count']}, consumers: {q['consumer_count']}, links: {q['link_count']})"
            )


@async_app.command("trace")
def async_trace_cli_cmd(
    entrypoint: Annotated[str, typer.Argument(help="Entrypoint symbol, handler, or queue topic name")],
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max traversal depth")] = 5,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Trace cross-process asynchronous execution flow starting from an entrypoint."""
    from codegraph.async_queue.traversal import trace_async_flow

    repo = _resolve_repo(None, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        result = trace_async_flow(con, entrypoint, max_depth=depth)

    if json_output:
        cli_echo(json.dumps(result, indent=2), json_mode=True)
    else:
        if result.get("status") != "ok":
            cli_echo(f"No async flow found starting from '{entrypoint}'.")
            return

        cli_echo(f"Async Flow Trace for '{entrypoint}':\n")
        cli_echo(f"  Producers:      {result['producers_count']}")
        cli_echo(f"  Consumers:      {result['consumers_count']}")
        cli_echo(f"  Downstream DB:  {result['downstream_ops_count']}\n")
        cli_echo("Execution Steps:")
        for step in result.get("flow_steps", []):
            cli_echo(
                f"  [{step['step']}] {step['source']} --({step['relationship']})--> {step['target']} "
                f"[{step.get('evidence_class', 'AST_VERIFIED')}] ({step.get('file', '')}:{step.get('line', '')})"
            )


@async_app.command("ingest-traces")
def async_ingest_traces_cli_cmd(
    traces_file: Annotated[Path, typer.Argument(help="Path to JSON file containing OpenTelemetry spans (OTLP or flat JSON)")],
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Idempotently ingest OpenTelemetry traces and reconcile distributed links with the static graph."""
    from codegraph.async_queue.otel_parser import parse_otel_spans
    from codegraph.async_queue.reconciler import OTelTraceReconciler

    repo = _resolve_repo(None, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    if not traces_file.exists():
        cli_echo(f"Error: traces file '{traces_file}' not found.")
        raise typer.Exit(code=1)

    try:
        content = traces_file.read_text(encoding="utf-8")
        spans = parse_otel_spans(content)
    except Exception as exc:
        cli_echo(f"Failed to read/parse traces file: {exc}")
        raise typer.Exit(code=1) from exc

    indexer = _indexer(repo)
    with indexer.session() as con:
        reconciler = OTelTraceReconciler(con)
        res = reconciler.reconcile_spans(spans)

    if json_output:
        cli_echo(json.dumps(res.to_dict(), indent=2), json_mode=True)
    else:
        cli_echo("OpenTelemetry Trace Ingestion Summary:\n")
        cli_echo(f"  Spans Ingested:       {res.spans_ingested}")
        cli_echo(f"  Spans Deduplicated:   {res.spans_deduplicated}")
        cli_echo(f"  Links Upgraded:       {res.links_upgraded} (to OTEL_DISTRIBUTED_VERIFIED)")
        cli_echo(f"  Cross-Repo Observed:  {res.links_created_runtime_only} (RUNTIME_ONLY_OBSERVED)")
        if res.details:
            cli_echo("\nReconciliation Details:")
            for d in res.details:
                cli_echo(f"  * {d.get('action')}: {d.get('destination')} (p50={d.get('p50_ms')}ms, p95={d.get('p95_ms')}ms)")


# ---------------------------------------------------------------------------
# Database Intelligence Subcommands
# ---------------------------------------------------------------------------
db_app = typer.Typer(
    no_args_is_help=True,
    help="Database intelligence: tables, columns, ORM models, schema, and impact analysis.",
)
app.add_typer(db_app, name="db")


@db_app.command("tables")
def db_tables_cli_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path or table name filter")] = None,
    table: Annotated[str | None, typer.Option("--table", "-t", help="Filter by table name")] = None,
    dialect: Annotated[str | None, typer.Option("--dialect", "-d", help="Filter by SQL dialect")] = None,
    schema: Annotated[str | None, typer.Option("--schema", "-s", help="Filter by schema name")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Discover database tables and views in the repository."""
    from codegraph.database.interrogation import find_db_tables

    target_table = table
    repo_path = path
    if path is not None and not path.exists() and not table:
        target_table = str(path)
        repo_path = None
    repo = _resolve_repo(repo_path, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        res = find_db_tables(con, repo, name=target_table, dialect=dialect, schema=schema)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        tables = res.get("tables", [])
        if not tables:
            cli_echo("No database tables found.")
            return
        cli_echo(f"Found {len(tables)} database table(s):")
        for t in tables:
            models = f" -> ORM: {', '.join(t['orm_models'])}" if t.get("orm_models") else ""
            schema_prefix = f"{t['schema_name']}." if t.get("schema_name") else ""
            cli_echo(f"  • {schema_prefix}{t['table_name']} ({t.get('dialect', 'sql')}) [{t.get('framework', 'db')}]{models} at {t.get('file')}:{t.get('start_line')}")


@db_app.command("columns")
def db_columns_cli_cmd(
    target: Annotated[str | None, typer.Argument(help="Table name, column name, or repository path")] = None,
    table: Annotated[str | None, typer.Option("--table", "-t", help="Filter by table name")] = None,
    column: Annotated[str | None, typer.Option("--column", "-c", help="Filter by column name")] = None,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Discover database columns, data types, nullability, PK/FK flags, and ORM field mappings."""
    from codegraph.database.interrogation import find_db_columns

    target_table = table
    target_column = column
    repo_path = path
    if target is not None:
        p = Path(target)
        if p.exists() and p.is_dir() and repo_path is None:
            repo_path = p
        elif not target_table:
            if "." in target:
                parts = target.split(".", 1)
                target_table = parts[0]
                target_column = parts[1]
            else:
                target_table = target

    repo = _resolve_repo(repo_path, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        res = find_db_columns(con, repo, table=target_table, column=target_column)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        cols = res.get("columns", [])
        if not cols:
            cli_echo("No database columns found.")
            return
        cli_echo(f"Found {len(cols)} database column(s):")
        for c in cols:
            pk = " [PK]" if c.get("is_primary_key") else ""
            fk = f" [FK -> {c.get('target_table')}.{c.get('target_column')}]" if c.get("is_foreign_key") else ""
            nullable = " NULL" if c.get("nullable") else " NOT NULL"
            cli_echo(f"  • {c.get('table_name')}.{c.get('column_name')}: {c.get('data_type')}{nullable}{pk}{fk} ({c.get('file')}:{c.get('start_line')})")


@db_app.command("models")
def db_models_cli_cmd(
    path: Annotated[Path | None, typer.Argument(help="Repository path or model filter")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Filter by model name")] = None,
    framework: Annotated[str | None, typer.Option("--framework", "-f", help="Filter by ORM framework")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Discover ORM models and classes mapped to database tables."""
    from codegraph.database.interrogation import find_db_models

    target_model = model
    repo_path = path
    if path is not None and not path.exists() and not model:
        target_model = str(path)
        repo_path = None
    repo = _resolve_repo(repo_path, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        res = find_db_models(con, repo, model=target_model, framework=framework)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        models_list = res.get("models", [])
        if not models_list:
            cli_echo("No ORM models found.")
            return
        cli_echo(f"Found {len(models_list)} ORM model(s):")
        for m in models_list:
            tbl = f" -> Table: {m.get('table_name')}" if m.get("table_name") else ""
            cli_echo(f"  • {m.get('name')} [{m.get('framework')}]{tbl} ({m.get('file')}:{m.get('start_line')})")


@db_app.command("schema")
def db_schema_cli_cmd(
    target: Annotated[str | None, typer.Argument(help="Table name to inspect, or repository path")] = None,
    table: Annotated[str | None, typer.Option("--table", "-t", help="Inspect single table in detail")] = None,
    dialect: Annotated[str | None, typer.Option("--dialect", "-d", help="Filter by SQL dialect")] = None,
    schema_name: Annotated[str | None, typer.Option("--schema", "-s", help="Filter by schema name")] = None,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Inspect full database schema overview or deep table metadata."""
    from codegraph.database.interrogation import get_db_schema, get_db_table

    target_table = table
    repo_path = path
    if target is not None:
        p = Path(target)
        if p.exists() and p.is_dir() and repo_path is None:
            repo_path = p
        elif not target_table:
            target_table = target

    repo = _resolve_repo(repo_path, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        if target_table:
            res = get_db_table(con, repo, table=target_table)
        else:
            res = get_db_schema(con, repo, dialect=dialect, schema=schema_name)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        if target_table:
            tbl_info = res.get("table") or {}
            cols = res.get("columns", [])
            cli_echo(f"Table: {target_table} ({tbl_info.get('dialect', 'sql')}) [{tbl_info.get('framework', 'db')}]")
            cli_echo(f"Location: {tbl_info.get('file')}:{tbl_info.get('start_line')}")
            if res.get("models"):
                cli_echo(f"ORM Models: {', '.join(m['name'] for m in res['models'])}")
            cli_echo(f"\nColumns ({len(cols)}):")
            for c in cols:
                pk = " [PK]" if c.get("is_primary_key") else ""
                fk = f" [FK -> {c.get('target_table')}.{c.get('target_column')}]" if c.get("is_foreign_key") else ""
                cli_echo(f"  • {c.get('column_name')}: {c.get('data_type')}{pk}{fk}")
            if res.get("readers"):
                cli_echo(f"\nReaders ({len(res['readers'])}):")
                for r in res["readers"][:5]:
                    cli_echo(f"  • {r.get('symbol')} ({r.get('file')}:{r.get('line')})")
            if res.get("writers"):
                cli_echo(f"\nWriters ({len(res['writers'])}):")
                for w in res["writers"][:5]:
                    cli_echo(f"  • {w.get('symbol')} ({w.get('file')}:{w.get('line')})")
        else:
            cli_echo("Database Schema Overview:")
            cli_echo(f"  Tables:        {len(res.get('tables', []))}")
            cli_echo(f"  Columns:       {len(res.get('columns', []))}")
            cli_echo(f"  ORM Models:    {len(res.get('models', []))}")
            cli_echo(f"  Relationships: {len(res.get('relationships', []))}")
            cli_echo(f"  Migrations:    {len(res.get('migrations', []))}")
            if res.get("tables"):
                cli_echo("\nTables:")
                for t in res["tables"][:15]:
                    cli_echo(f"  • {t.get('table_name')} ({t.get('dialect', 'sql')})")
                if len(res["tables"]) > 15:
                    cli_echo(f"  ... and {len(res['tables']) - 15} more tables")


@db_app.command("impact")
def db_impact_cli_cmd(
    target: Annotated[str, typer.Argument(help="Table name or Table.column to analyze downstream impact for")],
    column: Annotated[str | None, typer.Option("--column", "-c", help="Column name if target is a table")] = None,
    path: Annotated[Path | None, typer.Option("--path", "-p", help="Repository path")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Analyze bidirectional downstream impact of table/column modifications on code, routes, and tests."""
    from codegraph.database.interrogation import get_db_impact

    target_table = target
    target_column = column
    if "." in target and not target_column:
        parts = target.split(".", 1)
        target_table = parts[0]
        target_column = parts[1]

    repo = _resolve_repo(path, repository)
    if not _ensure_indexed(repo):
        raise typer.Exit(code=1)

    indexer = _indexer(repo)
    with indexer.session() as con:
        res = get_db_impact(con, repo, table=target_table, column=target_column)

    if json_output:
        cli_echo(json.dumps(res, indent=2), json_mode=True)
    else:
        cli_echo(f"Database Impact Analysis for {target}:")
        cli_echo(f"  Direct Readers:    {len(res.get('readers', []))}")
        cli_echo(f"  Direct Writers:    {len(res.get('writers', []))}")
        cli_echo(f"  Reachable Routes:  {len(res.get('routes', []))}")
        cli_echo(f"  Impacted Tests:    {len(res.get('tests', []))}")
        if res.get("routes"):
            cli_echo("\nReachable Routes:")
            for r in res["routes"]:
                cli_echo(f"  • [{r.get('http_method')}] {r.get('route_path')} -> {r.get('handler')}")
        if res.get("tests"):
            cli_echo("\nImpacted Tests:")
            for t in res["tests"]:
                cli_echo(f"  • {t.get('test_symbol')} ({t.get('file')}:{t.get('line')})")


@db_app.command("drift")
def db_drift_cli_cmd(
    route: Annotated[str | None, typer.Option("--route", help="Route path or endpoint to check for schema drift")] = None,
    handler: Annotated[str | None, typer.Option("--handler", "-h", help="Handler symbol to check for schema drift")] = None,
    table: Annotated[str | None, typer.Option("--table", "-t", help="Target table name (optional, inferred from mutation lineage)")] = None,
    schema: Annotated[str | None, typer.Option("--schema", "-s", help="Schema class name (optional, inferred from handler signature)")] = None,
    path: Annotated[Path | None, typer.Argument(help="Repository path (default: current directory)")] = None,
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON array")] = False,
) -> None:
    """Detect Pydantic / Form validation drift against destination database table columns."""
    schema_drift(route=route, handler=handler, table=table, schema=schema, path=path, repository=repository, json_output=json_output)


@db_app.command("ingest")
def db_ingest_cli_cmd(
    source: Annotated[Path, typer.Argument(help="Path to OpenTelemetry JSON/JSONL, SQL query log, or trace file")],
    repository: Annotated[Path | None, typer.Option("--repository", "-r", "--repo", help="Repository path")] = None,
    format: Annotated[str, typer.Option("--format", "-f", help="Trace format: auto | otel | json | sql_log")] = "auto",
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON result")] = False,
) -> None:
    """Ingest runtime database query logs or OpenTelemetry traces into repository index."""
    ingest_cli_cmd(source=source, repository=repository, format=format, json_output=json_output)



if __name__ == "__main__":
    app()

