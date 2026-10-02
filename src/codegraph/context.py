"""Context Compiler — flag-ship orchestration engine for CodeGraph MCP.

Translates TaskSpec and RetrievalPlan into a verified, bounded, coverage-aware,
and deduplicated ContextPacket with full provenance and zero LLM API dependency.
"""
from __future__ import annotations

import concurrent.futures
import os
import sqlite3
import time
from dataclasses import field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from codegraph.architecture import get_architecture
from codegraph.cache import (
    compute_context_cache_key,
    get_cached_context_packet,
    store_cached_context_packet,
)
from codegraph.constraints import ConstraintGuard
from codegraph.freshness import (
    FreshnessStatus,
    check_freshness,
    index_generation,
)
from codegraph.git import changed_files, is_git_repository, recent_commits
from codegraph.graph import GraphSeedPolicy
from codegraph.graph.traversal import (
    find_callees,
    find_callers,
    find_parallel_implementations,
    find_related_tests,
)
from codegraph.observability import (
    ExecutionMetadata,
    ExecutionTiming,
    OperationMetric,
    Timer,
    create_request_id,
    get_global_metrics,
)
from codegraph.optimizer import (
    CandidateContextItem,
    optimize_context_budget,
)
from codegraph.planner import RetrievalPlan, build_retrieval_plan
from codegraph.query_expansion import QueryExpansion, expand_query_terms, get_search_queries
from codegraph.ranking import RankedItem, rank
from codegraph.resources import (
    TaskPriority,
    get_global_coalescer,
    get_global_governor,
    get_process_memory_mb,
)
from codegraph.retrieval_policy import RetrievalPolicy, get_retrieval_policy
from codegraph.search import search
from codegraph.target_resolver import TargetResolution, resolve_targets
from codegraph.task import (
    TaskSpec,
    canonicalize_intent,
    normalize_task_spec,
)

SCHEMA_VERSION = "2.0"

Intent = Literal[
    "explain", "debug", "modify", "review", "test", "trace", "impact", "architecture"
]


# ---------------------------------------------------------------------------
# ContextPacket Models
# ---------------------------------------------------------------------------


class RankingReasonModel(BaseModel):
    code: str
    label: str
    contribution: float


class SymbolRef(BaseModel):
    symbol: str
    file: str
    kind: str
    start_line: int
    end_line: int
    score: float
    reasons: list[RankingReasonModel] = []
    canonical_id: str | None = None


class Relationship(BaseModel):
    source: str
    target: str
    relationship: str
    confidence: str
    file: str | None = None
    start_line: int | None = None
    evidence: str = ""
    status: str = "FACT"  # FACT | ASSUMPTION | INFERENCE | UNKNOWN | CONFLICT


class TestRef(BaseModel):
    file: str
    symbol: str | None
    relationship: str
    confidence: str
    evidence: str


class FileRef(BaseModel):
    file: str
    score: float
    reasons: list[RankingReasonModel] = []
    snippet: str
    token_estimate: int


class EvidenceRef(BaseModel):
    file: str
    start_line: int
    end_line: int
    symbol: str | None
    snippet: str
    confidence: str
    source_hash: str | None = None
    evidence_status: str = "current"  # current | stale


class ContextPacket(BaseModel):
    schema_version: str = SCHEMA_VERSION
    task: str
    intent: str | None
    repository: str
    indexed_commit: str | None
    current_commit: str | None
    freshness: str  # FRESH | STALE | PARTIALLY_STALE | UNKNOWN
    freshness_detail: str

    # Production intelligence extensions
    repository_generation: int = 0
    task_spec: dict[str, object] | None = None
    task_fingerprint: str = ""
    budget: dict[str, object] | None = None
    execution: dict[str, object] | None = None
    mode: str = "BALANCED"  # FAST | BALANCED | DEEP
    entry_points: list[dict[str, object]] = []
    framework_facts: list[dict[str, object]] = []
    architecture: list[dict[str, object]] = []
    git_changes: list[dict[str, object]] = []
    git_facts: list[dict[str, object]] = []
    assumptions: list[str] = []
    unknowns: list[str] = []
    conflicts: list[str] = []

    # Knowledge
    facts: list[dict[str, object]] = field(default_factory=list)
    symbols: list[SymbolRef] = []
    relationships: list[Relationship] = []
    tests: list[TestRef] = []
    files: list[FileRef] = []
    evidence: list[EvidenceRef] = []
    uncertainties: list[str] = []

    # Token budget
    candidate_token_estimate: int = 0
    selected_token_estimate: int = 0
    context_reduction_pct: float = 0.0
    selected_files: list[str] = []
    discarded_files: list[str] = []

    model_config = {"arbitrary_types_allowed": True}

    def as_dict(self) -> dict[str, object]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Token estimation helper
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4


def _token_estimate(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Main Context Compiler
# ---------------------------------------------------------------------------


def get_context(
    con: sqlite3.Connection,
    repository: Path,
    task: str | TaskSpec | dict[str, Any],
    intent: Intent | str | None = None,
    max_tokens: int = 20_000,
    top_k: int = 15,
    plan: RetrievalPlan | dict[str, Any] | None = None,
    mode: str = "BALANCED",  # FAST | BALANCED | DEEP
    explain: bool = False,
) -> ContextPacket:
    """Compile a deterministic, verified ContextPacket for the given task and intent."""
    governor = get_global_governor()
    coalescer = get_global_coalescer()
    flight_key = f"{repository}:{task}:{intent}:{max_tokens}:{top_k}:{mode}:{explain}"

    def _execute() -> ContextPacket:
        with governor.task_scope(TaskPriority.INTERACTIVE_HIGH):
            return _get_context_impl(
                con=con,
                repository=repository,
                task=task,
                intent=intent,
                max_tokens=max_tokens,
                top_k=top_k,
                plan=plan,
                mode=mode,
                explain=explain,
                governor=governor,
            )

    return coalescer.coalesce(flight_key, _execute)


def _get_context_impl(
    con: sqlite3.Connection,
    repository: Path,
    task: str | TaskSpec | dict[str, Any],
    intent: Intent | str | None = None,
    max_tokens: int = 20_000,
    top_k: int = 15,
    plan: RetrievalPlan | dict[str, Any] | None = None,
    mode: str = "BALANCED",  # FAST | BALANCED | DEEP
    explain: bool = False,
    governor: Any = None,
) -> ContextPacket:
    if governor is None:
        governor = get_global_governor()
    req_id = create_request_id()
    timing = ExecutionTiming()
    with Timer() as timer:
        # 0. Latency Mode configuration
        mode_upper = (mode or "BALANCED").upper()
        if mode_upper not in ("FAST", "BALANCED", "DEEP"):
            mode_upper = "BALANCED"

        if mode_upper == "FAST":
            effective_top_k = min(top_k, 5)
            max_graph_syms = 2
            max_graph_results = 5
            max_test_syms = 2
            max_test_results = 3
            git_commits_n = 2
        elif mode_upper == "DEEP":
            effective_top_k = max(top_k, 25)
            max_graph_syms = 10
            max_graph_results = 15
            max_test_syms = 8
            max_test_results = 8
            git_commits_n = 10
        else:  # BALANCED
            effective_top_k = top_k
            max_graph_syms = 6
            max_graph_results = 10
            max_test_syms = 4
            max_test_results = 5
            git_commits_n = 5

        # 1. Planning stage
        t_plan_start = time.perf_counter()
        task_spec, ambiguities = normalize_task_spec(task, con)

        caller_raw_intent = intent
        if caller_raw_intent:
            canonical_intent = canonicalize_intent(str(caller_raw_intent))
            task_spec = TaskSpec(
                schema_version=task_spec.schema_version,
                raw_prompt=task_spec.raw_prompt,
                intent=canonical_intent.value,
                goal=task_spec.goal,
                targets=task_spec.targets,
                entities=task_spec.entities,
                operations=task_spec.operations,
                constraints=task_spec.constraints,
                exclusions=task_spec.exclusions,
                scope_paths=task_spec.scope_paths,
                scope_modules=task_spec.scope_modules,
                frameworks=task_spec.frameworks,
                time_scope=task_spec.time_scope,
                priority_targets=task_spec.priority_targets,
                ambiguities=task_spec.ambiguities,
                assumptions=task_spec.assumptions,
                unknowns=task_spec.unknowns,
                confidence=task_spec.confidence,
            )

        task_display_str = (
            task if isinstance(task, str) else (task_spec.raw_prompt or task_spec.goal or "task")
        )

        gen = index_generation(con)
        cache_key = compute_context_cache_key(
            task_spec=task_spec,
            repository_generation=gen,
            max_tokens=max_tokens,
            extra_config=f"{caller_raw_intent or ''}:{mode_upper}",
        )

        # 2. Check Cache
        cached_data = get_cached_context_packet(con, cache_key)
        if cached_data is not None:
            try:
                packet = ContextPacket.model_validate(cached_data)
                timing.total_ms = timer.elapsed_ms
                exec_meta = ExecutionMetadata(
                    latency_ms=timer.elapsed_ms,
                    cache_hit=True,
                    index_generation=gen,
                    candidate_count=packet.candidate_token_estimate,
                    selected_count=packet.selected_token_estimate,
                    mode=mode_upper,
                    timing=timing,
                )
                packet.execution = exec_meta.as_dict()
                packet.execution["resource"] = {
                    "profile": governor.policy.profile.value,
                    "pressure": governor.get_pressure().value,
                    "activity": governor.get_activity_mode().value,
                    "estimated_memory_mb": get_process_memory_mb(),
                }
                packet.mode = mode_upper
                get_global_metrics().record(
                    OperationMetric(
                        request_id=req_id,
                        tool_or_op="get_context",
                        latency_ms=timer.elapsed_ms,
                        index_generation=gen,
                        cache_hit=True,
                        candidate_count=packet.candidate_token_estimate,
                        selected_count=packet.selected_token_estimate,
                        estimated_tokens=packet.selected_token_estimate,
                        task_intent=task_spec.intent,
                        freshness=packet.freshness,
                    )
                )
                return packet
            except Exception:
                pass

        if plan is None:
            retrieval_plan = build_retrieval_plan(
                task_spec=task_spec,
                ambiguities=ambiguities,
                con=con,
                token_budget=max_tokens,
            )
        elif isinstance(plan, dict):
            retrieval_plan = build_retrieval_plan(
                task_spec=task_spec,
                ambiguities=ambiguities,
                con=con,
                token_budget=int(plan.get("token_budget", max_tokens)),
            )
        else:
            retrieval_plan = plan
        timing.planning_ms = (time.perf_counter() - t_plan_start) * 1000

        # ── v2.1: First-class target resolution + qualified query expansion ──
        # Resolve every target in the spec against the indexed repository before
        # any retrieval work. This drives qualified, precise search queries and
        # prevents generic method names from polluting search results.
        _raw_targets = list(task_spec.priority_targets or task_spec.targets)
        _target_resolutions: dict[str, TargetResolution] = {}
        _retrieval_policy: RetrievalPolicy = get_retrieval_policy(task_spec.intent)
        if _raw_targets and con:
            _target_resolutions = resolve_targets(_raw_targets, con)
        _expanded_queries_obj: list[QueryExpansion] = expand_query_terms(
            _raw_targets,
            con,
            target_resolutions=_target_resolutions,
            max_expansions=10,
        )
        _v21_queries: list[str] = get_search_queries(_expanded_queries_obj)
        # Merge v2.1 qualified queries with planner queries (prefer qualified)
        _planner_queries: list[str] = [
            q for group in retrieval_plan.query_groups for q in group.queries
        ]
        # Deduplicated, qualified-first merge
        _merged_queries: list[str] = []
        _seen_q: set[str] = set()
        for q in _v21_queries + _planner_queries:
            if q and q not in _seen_q:
                _seen_q.add(q)
                _merged_queries.append(q)
        # ────────────────────────────────────────────────────────────────────

        # 3. Freshness check
        freshness_report = check_freshness(repository, con)
        stale_paths = set(freshness_report.modified_files + freshness_report.deleted_files)

        # 4. Check whether database is file-backed for multi-threaded parallel read
        db_file_path: str | None = None
        try:
            for r in con.execute("PRAGMA database_list").fetchall():
                if r[1] == "main" and r[2]:
                    db_file_path = str(r[2])
                    break
        except Exception:
            pass
        is_disk_db = db_file_path is not None and Path(db_file_path).is_file()

        queries_to_run: list[str] = _merged_queries if _merged_queries else [
            q for group in retrieval_plan.query_groups for q in group.queries
        ]

        candidate_dicts: list[dict[str, object]] = []
        target_symbols: set[str] = set()
        for t in task_spec.targets:
            target_symbols.add(t)
            target_symbols.add(t.split(".")[-1])
        # Also add canonical IDs from target resolutions as target symbols
        for res in _target_resolutions.values():
            if res.canonical_id:
                target_symbols.add(res.canonical_id)
                target_symbols.add(res.canonical_id.split(".")[-1])
            if res.qualified_name:
                target_symbols.add(res.qualified_name)

        # Parallel / Sequential retrieval worker helpers
        def _exec_search(path: str | None, queries: list[str]) -> list[dict[str, object]]:
            items: list[dict[str, object]] = []
            if path:
                c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                c.row_factory = sqlite3.Row
                try:
                    for query in queries:
                        for item in search(c, query, top_k=effective_top_k):
                            items.append(item.as_dict())
                finally:
                    c.close()
            else:
                for query in queries:
                    for item in search(con, query, top_k=effective_top_k):
                        items.append(item.as_dict())
            return items

        def _exec_routes(path: str | None) -> list[Any]:
            try:
                if path:
                    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    c.row_factory = sqlite3.Row
                    try:
                        return c.execute(
                            "SELECT route_path, http_method, handler_name, file_path, line, endpoint_id FROM framework_routes"
                        ).fetchall()
                    finally:
                        c.close()
                else:
                    return con.execute(
                        "SELECT route_path, http_method, handler_name, file_path, line, endpoint_id FROM framework_routes"
                    ).fetchall()
            except Exception:
                return []

        def _exec_git(repo: Path, include_git: bool, commit_limit: int) -> tuple[list[dict[str, Any]], set[str]]:
            changes: list[dict[str, Any]] = []
            recent: set[str] = set()
            try:
                if is_git_repository(repo):
                    diffs = changed_files(repo, since="HEAD~10", until="HEAD")
                    for d in diffs:
                        recent.add(d.path)
                        changes.append(d.as_dict())
                    if include_git:
                        for commit in recent_commits(repo, n=commit_limit):
                            changes.append(commit.as_dict())
            except Exception:
                pass
            return changes, recent

        include_arch = retrieval_plan.include_architecture or (mode_upper == "DEEP")
        def _exec_arch(path: str | None, repo: Path) -> list[dict[str, object]]:
            archs: list[dict[str, object]] = []
            try:
                if path:
                    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    c.row_factory = sqlite3.Row
                    try:
                        archs.append(get_architecture(c, repo))
                    finally:
                        c.close()
                else:
                    archs.append(get_architecture(con, repo))
            except Exception:
                pass
            return archs

        # Execute searches, framework routes, git, and architecture
        t_stage2_start = time.perf_counter()
        if is_disk_db:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as executor:
                f_search = executor.submit(_exec_search, db_file_path, queries_to_run)
                f_routes = executor.submit(_exec_routes, db_file_path)
                f_git = executor.submit(_exec_git, repository, retrieval_plan.include_git, git_commits_n)
                f_arch = executor.submit(_exec_arch, db_file_path, repository) if include_arch else None

                search_res = f_search.result()
                routes_res = f_routes.result()
                git_changes_out, recent_paths = f_git.result()
                architecture_out = f_arch.result() if f_arch else []
        else:
            search_res = _exec_search(None, queries_to_run)
            routes_res = _exec_routes(None)
            git_changes_out, recent_paths = _exec_git(repository, retrieval_plan.include_git, git_commits_n)
            architecture_out = _exec_arch(None, repository) if include_arch else []

        stage2_duration = (time.perf_counter() - t_stage2_start) * 1000
        timing.search_ms = stage2_duration * 0.4
        timing.framework_ms = stage2_duration * 0.2
        timing.git_ms = stage2_duration * 0.4

        for r_dict in search_res:
            candidate_dicts.append(r_dict)
            sym = r_dict.get("symbol")
            if sym and isinstance(sym, str):
                target_symbols.add(sym)
                target_symbols.add(sym.split(".")[-1])

        stage1_candidate_count = len(candidate_dicts)

        # Process framework routes
        route_relationships: list[Relationship] = []
        entry_points_out: list[dict[str, object]] = []
        framework_facts_out: list[dict[str, object]] = []

        for r in routes_res:
            r_path = r["route_path"]
            r_method = r["http_method"]
            ep_id = r["endpoint_id"] or f"{r_method} {r_path}"
            matches_task = (
                r_path in task_display_str
                or ep_id.lower() in task_display_str.lower()
                or (r_method in task_display_str.upper() and r_path in task_display_str)
                or any(
                    (len(tgt) >= 3 and (tgt.lower() == r["handler_name"].lower() or tgt.lower() in r_path.lower()))
                    for tgt in task_spec.targets
                )
            )
            if matches_task:
                target_symbols.add(r["handler_name"])
                r_line = r["line"] or 1
                candidate_dicts.append(
                    {
                        "file": r["file_path"],
                        "symbol": r["handler_name"],
                        "start_line": r_line,
                        "end_line": r_line,
                        "score": 0.95,
                        "snippet": f"Endpoint: {ep_id} handled by {r['handler_name']}",
                    }
                )
                route_rel = Relationship(
                    source=ep_id,
                    target=r["handler_name"],
                    relationship="HANDLED_BY",
                    confidence="HIGH",
                    file=r["file_path"],
                    start_line=r_line,
                    evidence=f"Route definition for {ep_id}",
                    status="FACT",
                )
                route_relationships.append(route_rel)
                entry_points_out.append(
                    {
                        "endpoint_id": ep_id,
                        "route_path": r_path,
                        "http_method": r_method,
                        "handler": r["handler_name"],
                        "file": r["file_path"],
                        "line": r_line,
                    }
                )
                framework_facts_out.append(
                    {
                        "construct": "ROUTE",
                        "endpoint_id": ep_id,
                        "handler": r["handler_name"],
                        "file": r["file_path"],
                        "line": r_line,
                    }
                )
                try:
                    dec_rows = con.execute(
                        "SELECT decorators, canonical_id, qualified_name, start_line FROM symbols "
                        "WHERE (name=? OR qualified_name=? OR canonical_id=?) AND path=?",
                        (r["handler_name"], r["handler_name"], r["handler_name"], r["file_path"]),
                    ).fetchall()
                    for d_row in dec_rows:
                        if d_row["decorators"]:
                            for dec in str(d_row["decorators"]).split(","):
                                clean_dec = dec.strip()
                                if clean_dec:
                                    fmt_dec = f"@{clean_dec}" if not clean_dec.startswith("@") else clean_dec
                                    framework_facts_out.append(
                                        {
                                            "framework": str(r["framework"] if "framework" in r.keys() else "framework"),
                                            "decorator": fmt_dec,
                                            "route": r_path,
                                            "handler": r["handler_name"],
                                            "canonical_id": str(d_row["canonical_id"]),
                                            "file": r["file_path"],
                                            "line": int(d_row["start_line"]),
                                            "confidence": "HIGH",
                                            "evidence": f"Decorator {fmt_dec} on {d_row['qualified_name']}",
                                        }
                                    )
                except Exception:
                    pass

        # Instantiate ConstraintGuard for hard safety invariants
        _guard = ConstraintGuard.from_task_spec(task_spec)

        # 5. Graph exploration (callers/callees) & Tests with deterministic seeds
        t_graph_start = time.perf_counter()

        # Build grounded, deterministic graph roots in priority order:
        # 1. canonical targets from TargetResolver
        # 2. exact qualified targets
        # 3. route handlers
        # 4. priority targets / task targets
        ordered_seeds: list[str] = []
        _seen_seeds: set[str] = set()

        for res in _target_resolutions.values():
            if res.canonical_id and _guard.allows_canonical_id(res.canonical_id) and res.canonical_id not in _seen_seeds:
                _seen_seeds.add(res.canonical_id)
                ordered_seeds.append(res.canonical_id)
            if res.qualified_name and _guard.allows_symbol(res.qualified_name) and res.qualified_name not in _seen_seeds:
                _seen_seeds.add(res.qualified_name)
                ordered_seeds.append(res.qualified_name)

        for ep in entry_points_out:
            h = str(ep.get("handler", ""))
            if h and _guard.allows_symbol(h) and h not in _seen_seeds:
                _seen_seeds.add(h)
                ordered_seeds.append(h)

        for sym in list(task_spec.priority_targets or task_spec.targets):
            if sym and _guard.allows_symbol(sym) and sym not in _seen_seeds:
                _seen_seeds.add(sym)
                ordered_seeds.append(sym)

        # Include top search results as seeds when grounded symbols are found
        for s_item in search_res[:3]:
            s_sym = str(s_item.get("symbol") or "")
            if s_sym and _guard.allows_symbol(s_sym) and s_sym not in _seen_seeds:
                _seen_seeds.add(s_sym)
                ordered_seeds.append(s_sym)

        # Bounded seed policy
        graph_seed_policy = GraphSeedPolicy(
            source_type="EXPLICIT_TARGET",
            min_confidence="HIGH",
            max_seeds=max_graph_syms,
            max_depth=_retrieval_policy.max_graph_depth,
            allowed_edges=_retrieval_policy.allowed_relationship_types,
        )

        for sym in ordered_seeds[:graph_seed_policy.max_seeds]:
            short = sym.split(".")[-1]
            if _retrieval_policy.include_callers and (
                retrieval_plan.entry_point_strategy in ("TRACE_FROM_ENDPOINT", "TRACE_HIERARCHY")
                or task_spec.intent in ("DEBUG", "TRACE", "IMPACT", "CHANGE", "REVIEW")
            ):
                callers = find_callers(con, short, max_results=max_graph_results)
                for c in callers:
                    caller_sym = c.get("symbol")
                    rel = str(c.get("relationship", "CALLS"))
                    if not _retrieval_policy.allows(rel):
                        continue
                    if not _guard.allows_symbol(str(caller_sym) if caller_sym else None):
                        continue
                    if not _guard.allows_file(str(c.get("file", ""))):
                        continue
                    candidate_dicts.append(
                        {
                            "file": c.get("file"),
                            "symbol": caller_sym,
                            "start_line": c.get("start_line", 1),
                            "end_line": c.get("end_line", 1),
                            "score": 0.45,
                            "snippet": "",
                            "relationship": rel,
                        }
                    )

            if _retrieval_policy.include_callees and task_spec.intent in ("EXPLAIN", "UNDERSTAND", "TRACE", "CHANGE", "REFACTOR", "DEBUG"):
                callees = find_callees(con, short, max_results=max_graph_results)
                for c in callees:
                    callee_sym = c.get("callee")
                    rel = str(c.get("relationship", "CALLS"))
                    if not _retrieval_policy.allows(rel):
                        continue
                    if not _guard.allows_symbol(str(callee_sym) if callee_sym else None):
                        continue
                    if not _guard.allows_file(str(c.get("file", ""))):
                        continue
                    candidate_dicts.append(
                        {
                            "file": c.get("file", ""),
                            "symbol": callee_sym,
                            "start_line": c.get("line", 1),
                            "end_line": c.get("line", 1),
                            "score": 0.50,
                            "snippet": "",
                            "relationship": rel,
                        }
                    )
                    # Depth 2 callee and parallel discovery
                    if _retrieval_policy.max_graph_depth >= 2 and callee_sym:
                        c2_list = find_callees(con, str(callee_sym), max_results=max_graph_results)
                        for c2 in c2_list:
                            c2_sym = c2.get("callee")
                            c2_rel = str(c2.get("relationship", "CALLS"))
                            if not _retrieval_policy.allows(c2_rel):
                                continue
                            if not _guard.allows_symbol(str(c2_sym) if c2_sym else None):
                                continue
                            if not _guard.allows_file(str(c2.get("file", ""))):
                                continue
                            candidate_dicts.append(
                                {
                                    "file": c2.get("file", ""),
                                    "symbol": c2_sym,
                                    "start_line": c2.get("line", 1),
                                    "end_line": c2.get("line", 1),
                                    "score": 0.45,
                                    "snippet": "",
                                    "relationship": c2_rel,
                                }
                            )
                        if _retrieval_policy.allows("PARALLEL_IMPLEMENTATION"):
                            p2_list = find_parallel_implementations(con, str(callee_sym), max_results=2)
                            for p2 in p2_list:
                                p2_sym = p2.get("symbol")
                                if not _guard.allows_symbol(str(p2_sym) if p2_sym else None):
                                    continue
                                if not _guard.allows_file(str(p2.get("file", ""))):
                                    continue
                                candidate_dicts.append(
                                    {
                                        "file": p2.get("file", ""),
                                        "symbol": p2_sym,
                                        "canonical_id": p2.get("canonical_id"),
                                        "start_line": p2.get("start_line", 1),
                                        "end_line": p2.get("end_line", 1),
                                        "score": 0.55,
                                        "snippet": "",
                                        "relationship": "PARALLEL_IMPLEMENTATION",
                                    }
                                )

            if _retrieval_policy.allows("PARALLEL_IMPLEMENTATION"):
                parallels = find_parallel_implementations(con, short, max_results=3)
                for p in parallels:
                    p_sym = p.get("symbol")
                    if not _guard.allows_symbol(str(p_sym) if p_sym else None):
                        continue
                    if not _guard.allows_file(str(p.get("file", ""))):
                        continue
                    candidate_dicts.append(
                        {
                            "file": p.get("file", ""),
                            "symbol": p_sym,
                            "canonical_id": p.get("canonical_id"),
                            "start_line": p.get("start_line", 1),
                            "end_line": p.get("end_line", 1),
                            "score": 0.65,
                            "snippet": "",
                            "relationship": "PARALLEL_IMPLEMENTATION",
                        }
                    )

        # Also discover parallel implementations for top search results
        if _retrieval_policy.allows("PARALLEL_IMPLEMENTATION"):
            for s_item in search_res[:4]:
                s_sym = str(s_item.get("symbol") or "")
                if s_sym and s_sym not in _seen_seeds:
                    parallels = find_parallel_implementations(con, s_sym, max_results=2)
                    for p in parallels:
                        p_sym = p.get("symbol")
                        if not _guard.allows_symbol(str(p_sym) if p_sym else None):
                            continue
                        if not _guard.allows_file(str(p.get("file", ""))):
                            continue
                        candidate_dicts.append(
                            {
                                "file": p.get("file", ""),
                                "symbol": p_sym,
                                "canonical_id": p.get("canonical_id"),
                                "start_line": p.get("start_line", 1),
                                "end_line": p.get("end_line", 1),
                                "score": 0.60,
                                "snippet": "",
                                "relationship": "PARALLEL_IMPLEMENTATION",
                            }
                        )

        timing.graph_ms = (time.perf_counter() - t_graph_start) * 1000

        # Related tests
        t_tests_start = time.perf_counter()
        tests_out: list[TestRef] = []
        if retrieval_plan.include_tests:
            test_sym_targets = list(task_spec.priority_targets or task_spec.targets)
            if not test_sym_targets:
                test_sym_targets = list(target_symbols)
            for sym in test_sym_targets[:max_test_syms]:
                test_results = find_related_tests(con, sym, max_results=max_test_results)
                for test_item in test_results:
                    if "result" in test_item:
                        continue
                    candidate_dicts.append(
                        {
                            "file": test_item.get("file"),
                            "symbol": test_item.get("symbol"),
                            "start_line": test_item.get("start_line", 1),
                            "end_line": test_item.get("start_line", 1),
                            "score": 0.55,
                            "snippet": "",
                        }
                    )
                    tests_out.append(
                        TestRef(
                            file=str(test_item.get("file", "")),
                            symbol=str(test_item["symbol"]) if test_item.get("symbol") is not None else None,
                            relationship=str(test_item.get("relationship", "")),
                            confidence=str(test_item.get("confidence", "LOW")),
                            evidence=str(test_item.get("evidence", "")),
                        )
                    )
        timing.tests_ms = (time.perf_counter() - t_tests_start) * 1000

        # 6. Rank candidates
        t_rank_start = time.perf_counter()
        legacy_intent_str = str(caller_raw_intent or task_spec.intent.lower())
        ranked: list[RankedItem] = rank(
            candidate_dicts,
            query=task_display_str,
            intent=legacy_intent_str,
            target_symbols=target_symbols,
            recent_paths=recent_paths,
            max_results=effective_top_k * 4,
            allowed_relationships=_retrieval_policy.allowed_relationship_types,
        )
        timing.ranking_ms = (time.perf_counter() - t_rank_start) * 1000

        # 7. Snippets and Evidence
        t_evidence_start = time.perf_counter()
        for item in ranked:
            if not item.snippet and item.symbol:
                row = con.execute(
                    "SELECT content FROM chunks WHERE symbol=? LIMIT 1", (item.symbol,)
                ).fetchone()
                if row:
                    snip = row["content"][:800]
                    object.__setattr__(item, "snippet", snip)
                    object.__setattr__(item, "token_estimate", _token_estimate(snip))
        timing.evidence_ms = (time.perf_counter() - t_evidence_start) * 1000

        # 8. Token Budget Optimization
        t_compile_start = time.perf_counter()
        candidate_items: list[CandidateContextItem] = []
        for idx, item in enumerate(ranked):
            layer = "GENERAL"
            if any(ep["file"] == item.file for ep in entry_points_out):
                layer = "ENTRYPOINT"
            elif "test" in item.file.lower():
                layer = "TEST"
            elif item.file in recent_paths:
                layer = "GIT"
            elif "service" in item.file.lower() or "controller" in item.file.lower():
                layer = "SERVICE"
            elif "model" in item.file.lower() or "db" in item.file.lower() or "schema" in item.file.lower():
                layer = "DATA"

            canon = None
            if item.symbol:
                srow = con.execute(
                    "SELECT canonical_id FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
                    (item.symbol, item.symbol, item.symbol),
                ).fetchone()
                if srow:
                    canon = srow["canonical_id"]

            candidate_items.append(
                CandidateContextItem(
                    item_id=f"c_{idx}_{item.file}_{item.start_line}",
                    file_path=item.file,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    canonical_id=canon,
                    estimated_tokens=item.token_estimate,
                    relevance_score=item.score,
                    evidence_quality=0.9 if item.file not in stale_paths else 0.4,
                    freshness="STALE" if item.file in stale_paths else "FRESH",
                    coverage_layer=layer,
                    source_type="symbol" if item.symbol else "chunk",
                    snippet=item.snippet,
                    confidence="HIGH" if item.file not in stale_paths else "LOW",
                    relationship_value=0.8 if layer in ("ENTRYPOINT", "SERVICE", "TEST") else 0.4,
                    epistemic_status="FACT" if item.file not in stale_paths else "UNKNOWN",
                    data={"reasons": item.reasons, "symbol": item.symbol},
                )
            )

        selected_items, budget = optimize_context_budget(
            candidates=candidate_items,
            token_budget=max_tokens,
            task_spec=task_spec,
        )
        timing.compilation_ms = (time.perf_counter() - t_compile_start) * 1000

        # 9. Assembly & Serialization
        t_serial_start = time.perf_counter()
        selected_paths = {item.file_path for item in selected_items}
        discarded_paths = {item.file_path for item in candidate_items if item.file_path not in selected_paths}

        symbols_out: list[SymbolRef] = []
        seen_sym_keys: set[tuple[str, str]] = set()
        for it in selected_items:
            sym_name = it.data.get("symbol")
            if sym_name:
                sym_key = (sym_name, it.file_path)
                if sym_key in seen_sym_keys:
                    continue
                seen_sym_keys.add(sym_key)
                known_cid = it.canonical_id or it.data.get("canonical_id")
                if known_cid:
                    row = con.execute(
                        "SELECT canonical_id, kind FROM symbols WHERE canonical_id=? LIMIT 1",
                        (known_cid,),
                    ).fetchone()
                else:
                    row = con.execute(
                        "SELECT canonical_id, kind FROM symbols WHERE (qualified_name=? OR name=?) AND path=? LIMIT 1",
                        (sym_name, sym_name, it.file_path),
                    ).fetchone()
                    if not row:
                        row = con.execute(
                            "SELECT canonical_id, kind FROM symbols WHERE qualified_name=? OR name=? LIMIT 1",
                            (sym_name, sym_name),
                        ).fetchone()
                cid = known_cid or (row["canonical_id"] if row and "canonical_id" in row.keys() else None)
                kind = row["kind"] if row else "unknown"
                reasons = it.data.get("reasons", [])
                symbols_out.append(
                    SymbolRef(
                        symbol=sym_name,
                        file=it.file_path,
                        kind=kind,
                        start_line=it.start_line,
                        end_line=it.end_line,
                        score=it.relevance_score,
                        reasons=[
                            RankingReasonModel(code=rs.code, label=rs.label, contribution=rs.contribution)
                            for rs in reasons
                        ],
                        canonical_id=cid or it.canonical_id,
                    )
                )

        # ── Relationships extraction ────────────────────────────────────────
        relationships_raw: list[Relationship] = list(route_relationships)
        seen_rel: set[tuple[str, str, str]] = {
            (r.source, r.target, r.relationship) for r in route_relationships
        }

        try:
            all_syms = list(target_symbols) + [s.split(".")[-1] for s in target_symbols]
            if all_syms:
                placeholders = ",".join("?" for _ in all_syms)
                edge_rows = con.execute(
                    f"""
                    SELECT source, target, relationship, confidence, file, start_line, evidence
                    FROM graph_edges
                    WHERE source IN ({placeholders}) OR target IN ({placeholders})
                    LIMIT 50
                    """,
                    all_syms + all_syms,
                ).fetchall()
                for er in edge_rows:
                    key = (er["source"], er["target"], er["relationship"])
                    if key not in seen_rel:
                        seen_rel.add(key)
                        relationships_raw.append(
                            Relationship(
                                source=er["source"],
                                target=er["target"],
                                relationship=er["relationship"],
                                confidence=er["confidence"] or "HIGH",
                                file=er["file"],
                                start_line=er["start_line"],
                                evidence=er["evidence"] or "",
                                status="FACT" if (er["confidence"] or "HIGH").upper() == "HIGH" else "INFERENCE",
                            )
                        )
        except Exception:
            pass

        # Backfill callers
        for sym in list(target_symbols)[:5]:
            short = sym.split(".")[-1]
            callers = find_callers(con, short, max_results=10)
            for c in callers:
                c_file = str(c.get("file", ""))
                if c_file in selected_paths:
                    key = (c_file, sym, "POSSIBLE_CALLS")
                    if key not in seen_rel:
                        seen_rel.add(key)
                        relationships_raw.append(
                            Relationship(
                                source=c_file,
                                target=sym,
                                relationship="POSSIBLE_CALLS",
                                confidence=str(c.get("confidence", "LOW")),
                                file=c_file,
                                evidence=str(c.get("evidence", "")),
                                status="INFERENCE",
                            )
                        )

        # ── v2.1 HARD SAFETY & INTEGRITY INVARIANT ──────────────────────────
        # Every channel must strictly conform to ConstraintGuard and RetrievalPolicy:
        # 1. Symbols
        symbols_out = [
            s for s in symbols_out
            if _guard.allows_symbol(s.symbol) and _guard.allows_canonical_id(s.canonical_id) and _guard.allows_file(s.file)
        ]

        # 2. Relationships
        relationships_out: list[Relationship] = [
            r for r in relationships_raw
            if _guard.allows_relationship(r.source, r.relationship, r.target)
            and (_guard.allows_file(r.file) if r.file else True)
            and _retrieval_policy.allows(r.relationship)
        ]

        # 3. Tests
        tests_out = [
            t for t in tests_out
            if _guard.allows_test(t.file, t.symbol)
        ]

        # 4. Entry points & framework facts
        entry_points_out = [
            ep for ep in entry_points_out
            if _guard.allows_endpoint(
                str(ep.get("route_path")),
                str(ep.get("handler")),
                str(ep.get("file")),
            )
        ]
        framework_facts_out = [
            ff for ff in framework_facts_out
            if _guard.allows_symbol(str(ff.get("handler"))) and _guard.allows_file(str(ff.get("file")))
        ]

        # 5. Evidence
        evidence_out: list[EvidenceRef] = []
        for it in selected_items[:12]:
            if it.snippet:
                if not _guard.allows_file(it.file_path) or not _guard.allows_symbol(it.data.get("symbol")):
                    continue
                src_hash: str | None = None
                try:
                    row = con.execute("SELECT content_hash FROM files WHERE path=?", (it.file_path,)).fetchone()
                    if row:
                        src_hash = row["content_hash"]
                except Exception:
                    pass
                is_stale = it.file_path in stale_paths
                evidence_out.append(
                    EvidenceRef(
                        file=it.file_path,
                        start_line=it.start_line,
                        end_line=it.end_line,
                        symbol=it.data.get("symbol"),
                        snippet=it.snippet[:600],
                        confidence="LOW" if is_stale else "HIGH",
                        source_hash=src_hash,
                        evidence_status="stale" if is_stale else "current",
                    )
                )

        # 6. Files
        files_out: list[FileRef] = []
        seen_files: set[str] = set()
        for it in selected_items:
            if not _guard.allows_file(it.file_path):
                continue
            if it.file_path in seen_files:
                continue
            seen_files.add(it.file_path)
            reasons = it.data.get("reasons", [])
            files_out.append(
                FileRef(
                    file=it.file_path,
                    score=it.relevance_score,
                    reasons=[
                        RankingReasonModel(code=rs.code, label=rs.label, contribution=rs.contribution)
                        for rs in reasons
                    ],
                    snippet=it.snippet[:400],
                    token_estimate=it.estimated_tokens,
                )
            )

        uncertainties: list[str] = []
        if freshness_report.status != FreshnessStatus.FRESH:
            uncertainties.append(f"Index is {freshness_report.status.value}: {freshness_report.detail}")
        if stale_paths & selected_paths:
            uncertainties.append(f"Evidence from {len(stale_paths & selected_paths)} file(s) may be stale.")
        if not candidate_dicts:
            uncertainties.append("No lexical or graph matches found. Results may be incomplete.")

        assumptions_out = list(task_spec.assumptions)
        unknowns_out = list(task_spec.unknowns)

        timing.serialization_ms = (time.perf_counter() - t_serial_start) * 1000
        timing.total_ms = timer.elapsed_ms

        exec_meta = ExecutionMetadata(
            latency_ms=timer.elapsed_ms,
            cache_hit=False,
            index_generation=gen,
            candidate_count=budget.candidate_tokens,
            selected_count=budget.selected_tokens,
            mode=mode_upper,
            timing=timing,
        )
        exec_dict = exec_meta.as_dict()
        exec_dict["resource"] = {
            "profile": governor.policy.profile.value,
            "pressure": governor.get_pressure().value,
            "activity": governor.get_activity_mode().value,
            "estimated_memory_mb": get_process_memory_mb(),
        }
        if explain:
            exec_dict["rejections"] = list(budget.rejections)
            exec_dict["retrieval_plan"] = retrieval_plan.as_dict()
            exec_dict["explain"] = {
                "task_spec": task_spec.as_dict(),
                "retrieval_plan": retrieval_plan.as_dict(),
                "stage1_candidate_count": stage1_candidate_count,
                "stage2_candidate_count": len(candidate_dicts),
                "coverage_layers": {
                    layer: sum(1 for it in selected_items if it.coverage_layer == layer)
                    for layer in set(it.coverage_layer for it in selected_items)
                },
                "why_selected": {
                    it.item_id: it.why_selected for it in selected_items
                },
                "rejections": list(budget.rejections),
            }

        packet = ContextPacket(
            schema_version=SCHEMA_VERSION,
            task=task_display_str,
            intent=str(caller_raw_intent) if caller_raw_intent else task_spec.intent.lower(),
            repository=str(repository),
            indexed_commit=freshness_report.indexed_commit,
            current_commit=freshness_report.current_commit,
            freshness=freshness_report.status.value,
            freshness_detail=freshness_report.detail,
            repository_generation=gen,
            task_spec=task_spec.as_dict(),
            task_fingerprint=getattr(retrieval_plan, "task_fingerprint", "") or task_spec.fingerprint(),
            budget=budget.as_dict(),
            execution=exec_dict,
            mode=mode_upper,
            entry_points=entry_points_out,
            framework_facts=framework_facts_out,
            architecture=architecture_out,
            git_changes=git_changes_out,
            git_facts=git_changes_out,
            assumptions=assumptions_out,
            unknowns=unknowns_out,
            conflicts=list(task_spec.conflicts) if hasattr(task_spec, "conflicts") else [],
            symbols=symbols_out,
            relationships=relationships_out,
            tests=tests_out,
            files=files_out,
            evidence=evidence_out,
            uncertainties=uncertainties,
            candidate_token_estimate=budget.candidate_tokens,
            selected_token_estimate=budget.selected_tokens,
            context_reduction_pct=round(budget.reduction_ratio * 100, 1),
            selected_files=sorted(selected_paths),
            discarded_files=sorted(discarded_paths),
        )

        store_cached_context_packet(con, cache_key, packet.as_dict())

        get_global_metrics().record(
            OperationMetric(
                request_id=req_id,
                tool_or_op="get_context",
                latency_ms=timer.elapsed_ms,
                index_generation=gen,
                cache_hit=False,
                candidate_count=budget.candidate_tokens,
                selected_count=budget.selected_tokens,
                estimated_tokens=budget.selected_tokens,
                task_intent=task_spec.intent,
                freshness=freshness_report.status.value,
            )
        )

        return packet
