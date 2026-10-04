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
    HARD_MAX_LINES,
    CandidateContextItem,
    ContextBudgetSpec,
    compress_relationships,
    optimize_context_budget,
    select_bounded_snippet,
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
    reason_code: str = ""
    package_id: str | None = None


class Relationship(BaseModel):
    source: str
    target: str
    relationship: str
    confidence: str
    file: str | None = None
    start_line: int | None = None
    evidence: str = ""
    status: str = ""  # FACT | ASSUMPTION | INFERENCE | UNKNOWN | CONFLICT
    evidence_class: str = ""
    supporting_locations: list[str] = []
    occurrence_count: int = 1

    def model_post_init(self, __context: Any) -> None:
        from codegraph.evidence_contract import validate_relationship_record

        validated = validate_relationship_record(self)
        object.__setattr__(self, "relationship", validated.relationship)
        object.__setattr__(self, "evidence_class", validated.evidence_class)
        object.__setattr__(self, "confidence", validated.confidence)
        object.__setattr__(self, "status", validated.status)


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

    # Phase 10 & Phase 14 structured ContextPacket sections
    metadata: dict[str, object] = {}
    target: dict[str, object] = {}
    routes: list[dict[str, object]] = []
    packages: list[dict[str, object]] = []
    git_impact: dict[str, object] = {}
    findings: list[dict[str, object]] = []
    coverage: dict[str, object] = {}
    database: list[dict[str, object]] = []
    runtime: list[dict[str, object]] = []
    reconciliation: list[dict[str, object]] = []

    # Knowledge
    facts: list[dict[str, object]] = field(default_factory=list)
    symbols: list[SymbolRef] = []
    relationships: list[Relationship] = []
    tests: list[TestRef] = []
    files: list[FileRef] = []
    evidence: list[EvidenceRef] = []
    uncertainties: list[str] = []

    # Token budget & explicit boundary metadata
    candidate_tokens: int = 0
    selected_tokens: int = 0
    selected_lines: int = 0
    coverage_score: float = 0.0
    truncated: bool = False
    candidate_token_estimate: int = 0
    selected_token_estimate: int = 0
    context_reduction_pct: float = 0.0
    selected_files: list[str] = []
    discarded_files: list[str] = []

    model_config = {"arbitrary_types_allowed": True}

    def as_dict(self) -> dict[str, object]:
        return self.model_dump()

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Token estimation helper
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4


def _token_estimate(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _resolve_task_or_query_input(
    task: str | TaskSpec | dict[str, Any] | None = "",
    query: str | TaskSpec | dict[str, Any] | None = "",
) -> str | TaskSpec | dict[str, Any]:
    """Resolve canonical `query` / `task` inputs with strict conflict validation."""
    def _is_nonempty(val: Any) -> bool:
        if val is None:
            return False
        if isinstance(val, str):
            return bool(val.strip())
        if isinstance(val, dict):
            return bool(val)
        return True

    has_task = _is_nonempty(task)
    has_query = _is_nonempty(query)

    if not has_task and not has_query:
        raise ValueError("Either 'query' or 'task' must be provided to get_context (non-empty string or TaskSpec).")

    if has_task and has_query:
        if isinstance(task, str) and isinstance(query, str):
            if task.strip() != query.strip():
                raise ValueError(
                    f"Conflicting 'query' ({query.strip()!r}) and 'task' ({task.strip()!r}) provided; "
                    "pass one or identical values."
                )
            return query.strip()
        if isinstance(task, dict) and isinstance(query, str):
            dict_prompt = str(task.get("raw_prompt") or task.get("goal") or task.get("task") or task.get("query") or "").strip()
            if dict_prompt and dict_prompt != query.strip():
                raise ValueError(
                    f"Conflicting 'query' ({query.strip()!r}) and 'task' prompt ({dict_prompt!r}) provided."
                )
            if not dict_prompt:
                merged = dict(task)
                merged["raw_prompt"] = query.strip()
                return merged
            return task
        if isinstance(query, dict) and isinstance(task, str):
            dict_prompt = str(query.get("raw_prompt") or query.get("goal") or query.get("task") or query.get("query") or "").strip()
            if dict_prompt and dict_prompt != task.strip():
                raise ValueError(
                    f"Conflicting 'query' prompt ({dict_prompt!r}) and 'task' ({task.strip()!r}) provided."
                )
            if not dict_prompt:
                merged = dict(query)
                merged["raw_prompt"] = task.strip()
                return merged
            return query
        if task != query:
            raise ValueError("Conflicting 'query' and 'task' arguments provided to get_context.")
        return task  # type: ignore[return-value]

    resolved = query if has_query else task
    if isinstance(resolved, str):
        return resolved.strip()
    assert resolved is not None
    return resolved


# ---------------------------------------------------------------------------
# Main Context Compiler
# ---------------------------------------------------------------------------


def get_context(
    con: sqlite3.Connection,
    repository: Path,
    task: str | TaskSpec | dict[str, Any] = "",
    intent: Intent | str | None = None,
    max_tokens: int = 20_000,
    top_k: int = 15,
    plan: RetrievalPlan | dict[str, Any] | None = None,
    mode: str = "BALANCED",  # FAST | BALANCED | DEEP
    explain: bool = False,
    include_generated: bool = False,
    include_vendor: bool = False,
    include_bundles: bool = False,
    include_build_artifacts: bool = False,
    max_symbols: int = 25,
    max_relationships: int = 30,
    max_files: int = 15,
    max_lines: int = 500,
    max_depth: int | None = None,
    max_package_depth: int | None = None,
    query: str | TaskSpec | dict[str, Any] = "",
) -> ContextPacket:
    """Compile a deterministic, verified ContextPacket for the given query/task and intent."""
    effective_task = _resolve_task_or_query_input(task=task, query=query)
    if max_tokens <= 0 or max_files <= 0 or max_lines <= 0:
        raise ValueError("max_tokens, max_files, and max_lines must be positive integers (> 0).")
    governor = get_global_governor()
    coalescer = get_global_coalescer()
    flight_key = (
        f"{repository}:{effective_task}:{intent}:{max_tokens}:{top_k}:{mode}:{explain}:"
        f"{include_generated}:{include_vendor}:{include_bundles}:{include_build_artifacts}:"
        f"{max_symbols}:{max_relationships}:{max_files}:{max_lines}:{max_depth}:{max_package_depth}"
    )

    def _execute() -> ContextPacket:
        with governor.task_scope(TaskPriority.INTERACTIVE_HIGH):
            return _get_context_impl(
                con=con,
                repository=repository,
                task=effective_task,
                intent=intent,
                max_tokens=max_tokens,
                top_k=top_k,
                plan=plan,
                mode=mode,
                explain=explain,
                governor=governor,
                include_generated=include_generated,
                include_vendor=include_vendor,
                include_bundles=include_bundles,
                include_build_artifacts=include_build_artifacts,
                max_symbols=max_symbols,
                max_relationships=max_relationships,
                max_files=max_files,
                max_lines=max_lines,
                max_depth=max_depth,
                max_package_depth=max_package_depth,
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
    include_generated: bool = False,
    include_vendor: bool = False,
    include_bundles: bool = False,
    include_build_artifacts: bool = False,
    max_symbols: int = 25,
    max_relationships: int = 30,
    max_files: int = 15,
    max_lines: int = 500,
    max_depth: int | None = None,
    max_package_depth: int | None = None,
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
        runtime_edge_count = 0
        try:
            row_rt = con.execute("SELECT count(*), COALESCE(MAX(runtime_generation), 0) FROM runtime_edges").fetchone()
            if row_rt:
                runtime_edge_count = int(row_rt[0] or 0) + int(row_rt[1] or 0) * 1000
        except Exception:
            pass
        cache_key = compute_context_cache_key(
            task_spec=task_spec,
            repository_generation=gen,
            max_tokens=max_tokens,
            extra_config=(
                f"{caller_raw_intent or ''}:{mode_upper}:{top_k}:"
                f"{include_generated}:{include_vendor}:{include_bundles}:{include_build_artifacts}:"
                f"{max_symbols}:{max_relationships}:{max_files}:{max_lines}:{max_depth}:{max_package_depth}:{runtime_edge_count}"
            ),
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
                old_exec = cached_data.get("execution", {}) if isinstance(cached_data, dict) else {}
                packet.execution = exec_meta.as_dict()
                packet.execution["excluded_count"] = old_exec.get("excluded_count", 0)
                packet.execution["excluded_artifact_classes"] = old_exec.get("excluded_artifact_classes", [])
                packet.execution["artifact_inclusions"] = old_exec.get("artifact_inclusions", [])
                packet.execution["package_context"] = old_exec.get("package_context")
                packet.execution["tool_efficiency"] = old_exec.get("tool_efficiency", {"tool_calls": 1, "cache_hit": True})
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
                        for item in search(
                            c,
                            query,
                            top_k=effective_top_k,
                            include_generated=include_generated,
                            include_vendor=include_vendor,
                            include_bundles=include_bundles,
                            include_build_artifacts=include_build_artifacts,
                            include_text_files=False,
                        ):
                            items.append(item.as_dict())
                finally:
                    c.close()
            else:
                for query in queries:
                    for item in search(
                        con,
                        query,
                        top_k=effective_top_k,
                        include_generated=include_generated,
                        include_vendor=include_vendor,
                        include_bundles=include_bundles,
                        include_build_artifacts=include_build_artifacts,
                        include_text_files=False,
                    ):
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
                        "relationship": "HANDLED_BY",
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
                    evidence_class="FRAMEWORK_VERIFIED",
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

        effective_max_depth = max_depth if max_depth is not None else _retrieval_policy.max_graph_depth
        effective_pkg_depth = max_package_depth if max_package_depth is not None else _retrieval_policy.max_package_depth

        # Bounded seed policy
        graph_seed_policy = GraphSeedPolicy(
            source_type="EXPLICIT_TARGET",
            min_confidence="HIGH",
            max_seeds=max_graph_syms,
            max_depth=effective_max_depth,
            allowed_edges=_retrieval_policy.allowed_relationship_types,
        )

        # Monorepo / Package boundary detection early for package-aware limiting
        from codegraph.monorepo import detect_workspace
        ws_info = detect_workspace(repository, con=con)
        target_pkg = None
        for t in task_spec.targets:
            pkg = ws_info.get_package_for_file(t)
            if pkg and pkg.root_path != "":
                target_pkg = pkg
                break
        if not target_pkg:
            for t in task_spec.targets:
                pkg = ws_info.get_package_for_file(t)
                if pkg:
                    target_pkg = pkg
                    break
        if not target_pkg and ordered_seeds:
            for s in ordered_seeds:
                s_row = con.execute(
                    "SELECT path FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
                    (s, s, s),
                ).fetchone()
                if s_row:
                    pkg = ws_info.get_package_for_file(str(s_row[0]))
                    if pkg:
                        target_pkg = pkg
                        break

        # Compute bounded package distance map (0=target, 1=direct dep/dependent, ..d=transitive, 99=unrelated)
        pkg_distances: dict[str, int] = {}
        if target_pkg:
            pkg_distances[target_pkg.package_id] = 0
            frontier = [target_pkg.package_id]
            for dist in range(1, max(1, effective_pkg_depth) + 1):
                next_frontier: list[str] = []
                for curr_pid in frontier:
                    curr_pkg = ws_info.packages.get(curr_pid)
                    if not curr_pkg:
                        continue
                    for dep_pid in curr_pkg.dependency_package_ids:
                        if dep_pid in ws_info.packages and dep_pid not in pkg_distances:
                            pkg_distances[dep_pid] = dist
                            next_frontier.append(dep_pid)
                    for dep_pkg in ws_info.get_dependent_packages(curr_pkg.package_id):
                        if dep_pkg.package_id not in pkg_distances:
                            pkg_distances[dep_pkg.package_id] = dist
                            next_frontier.append(dep_pkg.package_id)
                frontier = next_frontier
            for pid in ws_info.packages:
                if pid not in pkg_distances:
                    pkg_distances[pid] = 99

        # Artifact-aware seed policy:
        # SOURCE: full participation
        # TEST: participation for test-aware tasks
        # GENERATED: deprioritized (placed after handwritten source)
        # BUILD_ARTIFACT, MINIFIED, BUNDLE, BINARY: suppressed from normal seeds
        # VENDOR: suppressed from normal seeds unless explicit opt-in
        filtered_seeds: list[str] = []
        deprioritized_seeds: list[str] = []
        excluded_artifacts_count = 0
        excluded_artifact_classes: set[str] = set()
        artifact_inclusions: list[dict[str, object]] = []

        explicit_targets = set(task_spec.targets) | set(task_spec.priority_targets or ())

        for s_candidate in ordered_seeds:
            if s_candidate in explicit_targets:
                filtered_seeds.append(s_candidate)
                continue
            cat_row = con.execute(
                "SELECT f.category FROM symbols s JOIN files f ON s.path = f.path "
                "WHERE s.canonical_id = ? OR s.qualified_name = ? OR s.name = ? LIMIT 1",
                (s_candidate, s_candidate, s_candidate),
            ).fetchone()
            if cat_row:
                s_cat = str(cat_row[0])
                if s_cat in ("MINIFIED", "BUNDLE") and not include_bundles:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(s_cat)
                    continue
                if s_cat in ("BUILD_ARTIFACT", "BINARY") and not include_build_artifacts:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(s_cat)
                    continue
                if s_cat == "VENDOR" and not include_vendor:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(s_cat)
                    continue
                if s_cat == "TEST" and task_spec.intent not in ("TEST", "DEBUG", "REVIEW"):
                    continue
                if s_cat == "GENERATED" and not include_generated:
                    deprioritized_seeds.append(s_candidate)
                    continue
            filtered_seeds.append(s_candidate)

        active_seeds = filtered_seeds + deprioritized_seeds
        findings_out: list[dict[str, object]] = []

        for sym in active_seeds[:graph_seed_policy.max_seeds]:
            short = sym.split(".")[-1]
            if _retrieval_policy.include_callers and (
                retrieval_plan.entry_point_strategy in ("TRACE_FROM_ENDPOINT", "TRACE_HIERARCHY")
                or task_spec.intent in ("DEBUG", "TRACE", "IMPACT", "CHANGE", "REVIEW", "UNDERSTAND")
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
                    if effective_max_depth >= 2 and callee_sym:
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

            # Phase 10: Semantic edge candidate discovery (DI providers, registrations, events, routes, tests)
            # Ensures coverage-aware optimization discovers high-value semantic neighbors even when lexically distinct
            try:
                sem_rows = con.execute(
                    """
                    SELECT source, target, relationship, confidence, evidence_class, file, start_line, evidence
                    FROM graph_edges
                    WHERE source = ? OR target = ? OR source LIKE ? OR target LIKE ?
                    LIMIT 30
                    """,
                    (sym, sym, f"%::{short}", f"%::{short}"),
                ).fetchall()
                for srow in sem_rows:
                    s_rel = str(srow["relationship"] or "")
                    s_conf = str(srow["confidence"] or "HIGH").upper()
                    s_ev_cls = str(srow["evidence_class"] or "AST_VERIFIED").upper()
                    if s_ev_cls in ("UNKNOWN", "POSSIBLE") or s_conf == "LOW":
                        findings_out.append({
                            "type": "EPISTEMIC_EDGE",
                            "source": srow["source"],
                            "target": srow["target"],
                            "relationship": s_rel,
                            "evidence_class": s_ev_cls,
                            "confidence": s_conf,
                            "file": srow["file"],
                            "line": srow["start_line"],
                            "evidence": srow["evidence"] or "",
                            "status": "UNKNOWN" if s_ev_cls == "UNKNOWN" else "INFERENCE",
                        })
                    if not _retrieval_policy.allows(s_rel):
                        continue
                    other_id = str(srow["target"]) if str(srow["source"]).endswith(short) or str(srow["source"]) == sym else str(srow["source"])
                    target_symbols.add(other_id)
                    sym_lookup = con.execute(
                        "SELECT canonical_id, qualified_name, name, path, start_line, end_line FROM symbols "
                        "WHERE canonical_id = ? OR qualified_name = ? OR name = ? LIMIT 1",
                        (other_id, other_id, other_id.split("::")[-1].split(".")[-1]),
                    ).fetchone()
                    if sym_lookup:
                        o_file = str(sym_lookup["path"])
                        o_sym = str(sym_lookup["qualified_name"] or sym_lookup["name"])
                        if _guard.allows_symbol(o_sym) and _guard.allows_file(o_file):
                            candidate_dicts.append({
                                "file": o_file,
                                "symbol": o_sym,
                                "canonical_id": str(sym_lookup["canonical_id"]),
                                "start_line": int(sym_lookup["start_line"] or 1),
                                "end_line": int(sym_lookup["end_line"] or 1),
                                "score": 0.65,
                                "snippet": "",
                                "relationship": s_rel,
                                "confidence": s_conf,
                            })
            except Exception:
                pass

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
        seen_test_keys: set[tuple[str, str | None, str]] = set()
        if retrieval_plan.include_tests or _retrieval_policy.include_tests:
            test_sym_targets = list(task_spec.priority_targets or task_spec.targets)
            if not test_sym_targets:
                test_sym_targets = list(target_symbols)
            for sym in test_sym_targets[:max_test_syms]:
                test_results = find_related_tests(con, sym, max_results=max_test_results)
                for test_item in test_results:
                    if "result" in test_item:
                        continue
                    t_file = str(test_item.get("file", ""))
                    t_sym = str(test_item["symbol"]) if test_item.get("symbol") is not None else None
                    t_rel = str(test_item.get("relationship", "TESTS"))
                    t_key = (t_file, t_sym, t_rel)
                    if t_key in seen_test_keys:
                        continue
                    seen_test_keys.add(t_key)
                    candidate_dicts.append(
                        {
                            "file": t_file,
                            "symbol": t_sym,
                            "start_line": test_item.get("start_line", 1),
                            "end_line": test_item.get("start_line", 1),
                            "score": 0.60,
                            "snippet": "",
                            "relationship": t_rel,
                        }
                    )
                    tests_out.append(
                        TestRef(
                            file=t_file,
                            symbol=t_sym,
                            relationship=t_rel,
                            confidence=str(test_item.get("confidence", "LOW")),
                            evidence=str(test_item.get("evidence", "")),
                        )
                    )
        timing.tests_ms = (time.perf_counter() - t_tests_start) * 1000

        # Pre-ranking artifact & package annotation on candidate_dicts
        from codegraph.indexing.classifier import classify_file
        from codegraph.security import is_sensitive_path
        filtered_candidate_dicts: list[dict[str, object]] = []
        for cd in candidate_dicts:
            c_file = str(cd.get("file") or "")
            if c_file and is_sensitive_path(c_file):
                continue
            c_sym = str(cd.get("symbol") or "")
            c_cat = str(cd.get("category") or "")
            if not c_cat and c_file:
                frow = con.execute("SELECT category FROM files WHERE path=? LIMIT 1", (c_file,)).fetchone()
                c_cat = str(frow[0]) if frow and frow[0] else str(classify_file(c_file).value)
            cd["category"] = c_cat

            is_explicit = c_file in explicit_targets or c_sym in explicit_targets
            if not is_explicit:
                if c_cat in ("MINIFIED", "BUNDLE") and not include_bundles:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(c_cat)
                    continue
                if c_cat in ("BUILD_ARTIFACT", "BINARY") and not include_build_artifacts:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(c_cat)
                    continue
                if c_cat == "VENDOR" and not include_vendor:
                    excluded_artifacts_count += 1
                    excluded_artifact_classes.add(c_cat)
                    continue
            else:
                if c_cat in ("MINIFIED", "BUNDLE", "BUILD_ARTIFACT", "VENDOR", "GENERATED"):
                    artifact_inclusions.append({
                        "file": c_file,
                        "artifact_class": c_cat,
                        "reason": "Explicitly targeted by task",
                    })

            if c_cat in ("MINIFIED", "BUNDLE") and include_bundles:
                artifact_inclusions.append({"file": c_file, "artifact_class": c_cat, "reason": "Explicit opt-in: include_bundles=True"})
            elif c_cat in ("BUILD_ARTIFACT", "BINARY") and include_build_artifacts:
                artifact_inclusions.append({"file": c_file, "artifact_class": c_cat, "reason": "Explicit opt-in: include_build_artifacts=True"})
            elif c_cat == "VENDOR" and include_vendor:
                artifact_inclusions.append({"file": c_file, "artifact_class": c_cat, "reason": "Explicit opt-in: include_vendor=True"})
            elif c_cat == "GENERATED" and include_generated:
                artifact_inclusions.append({"file": c_file, "artifact_class": c_cat, "reason": "Explicit opt-in: include_generated=True"})

            if target_pkg and c_file:
                c_pkg = ws_info.get_package_for_file(c_file)
                if c_pkg:
                    cd["package_id"] = c_pkg.package_id
                    cd["package_distance"] = pkg_distances.get(c_pkg.package_id, 99)

            filtered_candidate_dicts.append(cd)

        candidate_dicts = filtered_candidate_dicts

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

        # 7. Bounded Snippets and Evidence
        from codegraph.security import redact_secrets
        t_evidence_start = time.perf_counter()
        per_snippet_max_lines = max(1, min(35, min(max_lines, HARD_MAX_LINES)))
        for item in ranked:
            if not item.snippet and item.symbol:
                row = con.execute(
                    "SELECT content FROM chunks WHERE symbol=? LIMIT 1", (item.symbol,)
                ).fetchone()
                if row:
                    snip, _, _ = select_bounded_snippet(
                        redact_secrets(str(row["content"])),
                        start_line=item.start_line,
                        end_line=item.end_line,
                        max_lines=per_snippet_max_lines,
                        max_chars=800,
                    )
                    snip = redact_secrets(snip)
                    object.__setattr__(item, "snippet", snip)
                    object.__setattr__(item, "token_estimate", _token_estimate(snip))
            elif item.snippet:
                snip, _, _ = select_bounded_snippet(
                    redact_secrets(item.snippet),
                    start_line=item.start_line,
                    end_line=item.end_line,
                    max_lines=per_snippet_max_lines,
                    max_chars=800,
                )
                snip = redact_secrets(snip)
                object.__setattr__(item, "snippet", snip)
                object.__setattr__(item, "token_estimate", _token_estimate(snip))
        timing.evidence_ms = (time.perf_counter() - t_evidence_start) * 1000

        # 8. Token Budget & Coverage-Aware Optimization
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

            canon = item.canonical_id
            if not canon and item.symbol:
                srow = con.execute(
                    "SELECT canonical_id FROM symbols WHERE (canonical_id=? OR qualified_name=? OR name=?) AND path=? LIMIT 1",
                    (item.symbol, item.symbol, item.symbol, item.file),
                ).fetchone()
                if not srow:
                    srow = con.execute(
                        "SELECT canonical_id FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
                        (item.symbol, item.symbol, item.symbol),
                    ).fetchone()
                if srow:
                    canon = srow["canonical_id"]

            item_pkg = ws_info.get_package_for_file(item.file) if item.file else None
            item_pkg_id = item_pkg.package_id if item_pkg else None
            item_pkg_dist = pkg_distances.get(item_pkg_id, 0) if (target_pkg and item_pkg_id) else 0

            frow = con.execute("SELECT category FROM files WHERE path=? LIMIT 1", (item.file,)).fetchone() if item.file else None
            item_art_cls = str(frow[0]) if frow and frow[0] else str(classify_file(item.file).value)

            # Determine relationship tag from reasons if present
            rel_tag = ""
            for rs in item.reasons:
                if rs.code == "DI_PROVIDER":
                    rel_tag = "PROVIDES"
                elif rs.code == "SEMANTIC_DISPATCH":
                    rel_tag = "REGISTERS"
                elif rs.code == "ENDPOINT_HANDLER":
                    rel_tag = "HANDLED_BY"
                elif rs.code in ("DIRECT_CALLER", "POSSIBLE_CALLER"):
                    rel_tag = "CALLED_BY"
                elif rs.code == "DIRECT_CALLEE":
                    rel_tag = "CALLS"
                elif rs.code == "TEST_RELATION":
                    rel_tag = "TESTS"
                elif rs.code == "PACKAGE_DEPENDENCY":
                    rel_tag = "DEPENDS_ON_PACKAGE"

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
                    relationship_value=0.8 if layer in ("ENTRYPOINT", "SERVICE", "TEST") or rel_tag else 0.4,
                    epistemic_status="FACT" if item.file not in stale_paths else "UNKNOWN",
                    data={"reasons": item.reasons, "symbol": item.symbol, "relationship": rel_tag},
                    package_id=item_pkg_id,
                    package_distance=item_pkg_dist,
                    artifact_class=item_art_cls,
                )
            )

        budget_spec = ContextBudgetSpec(
            max_tokens=max_tokens,
            max_symbols=max_symbols,
            max_relationships=max_relationships,
            max_files=max_files,
            max_lines=max_lines,
            max_depth=effective_max_depth,
        )

        selected_items, budget = optimize_context_budget(
            candidates=candidate_items,
            token_budget=max_tokens,
            task_spec=task_spec,
            budget_spec=budget_spec,
            required_dimensions=_retrieval_policy.required_dimensions,
            verified_claims_count=len(route_relationships) + len(tests_out),
            tool_calls=1,
        )
        timing.compilation_ms = (time.perf_counter() - t_compile_start) * 1000

        # 9. Assembly, Deduplication & Evidence Compression
        t_serial_start = time.perf_counter()
        selected_paths = {item.file_path for item in selected_items if item.file_path}
        discarded_paths = {item.file_path for item in candidate_items if item.file_path and item.file_path not in selected_paths}

        symbols_out: list[SymbolRef] = []
        seen_canonical_syms: set[str] = set()
        for it in selected_items:
            sym_name = it.data.get("symbol")
            if sym_name:
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
                dedup_id = str(cid) if cid else f"{it.file_path}::{sym_name}"
                if dedup_id in seen_canonical_syms:
                    continue
                seen_canonical_syms.add(dedup_id)
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
                        reason_code=it.reason_code,
                        package_id=it.package_id,
                    )
                )

        # ── Relationships extraction & compression ──────────────────────────
        relationships_raw: list[Relationship] = list(route_relationships)

        try:
            all_syms = (
                list(target_symbols)
                + [s.split(".")[-1] for s in target_symbols]
                + [s.canonical_id for s in symbols_out if s.canonical_id]
                + [s.symbol for s in symbols_out if s.symbol]
            )
            if target_pkg:
                all_syms.append(target_pkg.package_id)
                all_syms.append(target_pkg.name)
            all_syms = list(dict.fromkeys(all_syms))
            if all_syms:
                placeholders = ",".join("?" for _ in all_syms)
                edge_rows = con.execute(
                    f"""
                    SELECT source, target, relationship, confidence, evidence_class, file, start_line, evidence
                    FROM graph_edges
                    WHERE source IN ({placeholders}) OR target IN ({placeholders})
                    LIMIT 100
                    """,
                    all_syms + all_syms,
                ).fetchall()
                for er in edge_rows:
                    ev_cls = str(er["evidence_class"] if "evidence_class" in er.keys() and er["evidence_class"] else "AST_VERIFIED")
                    conf_val = str(er["confidence"] or "HIGH").upper()
                    status_val = "FACT" if conf_val == "HIGH" and ev_cls not in ("POSSIBLE", "UNKNOWN") else (
                        "UNKNOWN" if ev_cls == "UNKNOWN" else "INFERENCE"
                    )
                    relationships_raw.append(
                        Relationship(
                            source=er["source"],
                            target=er["target"],
                            relationship=er["relationship"],
                            confidence=conf_val,
                            file=er["file"],
                            start_line=er["start_line"],
                            evidence=er["evidence"] or "",
                            status=status_val,
                            evidence_class=ev_cls,
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
                    raw_c_conf = str(c.get("confidence", "LOW")).upper()
                    c_conf = "MEDIUM" if raw_c_conf == "HIGH" else raw_c_conf
                    relationships_raw.append(
                        Relationship(
                            source=c_file,
                            target=sym,
                            relationship="POSSIBLE_CALLS",
                            confidence=c_conf,
                            file=c_file,
                            evidence=str(c.get("evidence", "")),
                            status="INFERENCE",
                            evidence_class="POSSIBLE",
                        )
                    )

        # ── v2.1 & Phase 10 HARD SAFETY & INTEGRITY INVARIANT ───────────────
        # 1. Symbols
        symbols_out = [
            s for s in symbols_out
            if _guard.allows_symbol(s.symbol) and _guard.allows_canonical_id(s.canonical_id) and _guard.allows_file(s.file)
        ][: budget.max_symbols]

        # 2. Relationships (filtered + deterministically compressed)
        filtered_rels: list[Relationship] = [
            r for r in relationships_raw
            if _guard.allows_relationship(r.source, r.relationship, r.target)
            and (_guard.allows_file(r.file) if r.file else True)
            and _retrieval_policy.allows(r.relationship)
        ]
        relationships_out, compression_stats = compress_relationships(
            filtered_rels, max_relationships=budget.max_relationships
        )

        # 3. Tests (deduplicated)
        tests_out = [
            t for t in tests_out
            if _guard.allows_test(t.file, t.symbol)
        ]

        # 4. Entry points & framework facts (deduplicated by endpoint_id)
        seen_ep_ids: set[str] = set()
        dedup_entry_points: list[dict[str, object]] = []
        for ep in entry_points_out:
            if not _guard.allows_endpoint(
                str(ep.get("route_path")),
                str(ep.get("handler")),
                str(ep.get("file")),
            ):
                continue
            eid = str(ep.get("endpoint_id") or "")
            if eid and eid in seen_ep_ids:
                continue
            if eid:
                seen_ep_ids.add(eid)
            dedup_entry_points.append(ep)
        entry_points_out = dedup_entry_points

        framework_facts_out = [
            ff for ff in framework_facts_out
            if _guard.allows_symbol(str(ff.get("handler"))) and _guard.allows_file(str(ff.get("file")))
        ]

        # 5. Evidence (bounded & deduplicated by canonical location)
        evidence_out: list[EvidenceRef] = []
        seen_ev_keys: set[tuple[str, int, str | None]] = set()
        for it in selected_items[:12]:
            if it.snippet:
                if not _guard.allows_file(it.file_path) or not _guard.allows_symbol(it.data.get("symbol")):
                    continue
                ev_key = (it.file_path, it.start_line, it.data.get("symbol"))
                if ev_key in seen_ev_keys:
                    continue
                seen_ev_keys.add(ev_key)
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

        # 6. Files (bounded by budget.max_files, aggregating token_estimate across selected items in each file)
        files_out: list[FileRef] = []
        file_index_map: dict[str, int] = {}
        for it in selected_items:
            if not it.file_path or not _guard.allows_file(it.file_path):
                continue
            if it.file_path in file_index_map:
                existing_idx = file_index_map[it.file_path]
                existing_ref = files_out[existing_idx]
                existing_ref.token_estimate += it.estimated_tokens
                continue
            if len(files_out) >= budget.max_files:
                continue
            file_index_map[it.file_path] = len(files_out)
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

        # 7. Package-aware bounded packages list & unresolved package dependency preservation
        packages_out: list[dict[str, object]] = []
        seen_pkg_ids: set[str] = set()
        for pid in sorted(ws_info.packages.keys()):
            p_info = ws_info.packages[pid]
            if p_info.root_path == "" and len(ws_info.packages) > 1:
                continue
            p_dist = pkg_distances.get(pid, 0)
            if target_pkg and p_dist > effective_pkg_depth and task_spec.intent != "ARCHITECTURE":
                continue
            if pid not in seen_pkg_ids:
                seen_pkg_ids.add(pid)
                p_dict = p_info.as_dict()
                p_dict["distance"] = p_dist
                packages_out.append(p_dict)

        for unres in ws_info.unresolved_dependencies:
            src_pid = str(unres.get("source_package_id") or "")
            if not target_pkg or src_pid == target_pkg.package_id:
                findings_out.append({
                    "type": "UNRESOLVED_PACKAGE_DEPENDENCY",
                    "source": src_pid,
                    "target": str(unres.get("target_name") or ""),
                    "specifier": str(unres.get("specifier") or ""),
                    "status": "UNKNOWN",
                    "reason": f"Dependency '{unres.get('target_name')}' is external or unresolved in workspace",
                })

        # Check unresolved target resolutions and preserve as UNKNOWN findings
        assumptions_out = list(task_spec.assumptions)
        unknowns_out = list(task_spec.unknowns)
        conflicts_out = list(task_spec.conflicts) if hasattr(task_spec, "conflicts") else []

        for raw_t, t_res in _target_resolutions.items():
            if t_res.ambiguity_state == "AMBIGUOUS":
                findings_out.append({
                    "type": "AMBIGUOUS_TARGET",
                    "target": raw_t,
                    "status": "CONFLICT",
                    "alternatives": list(t_res.alternatives),
                })
                msg = f"Target '{raw_t}' is ambiguous across multiple candidates."
                if msg not in conflicts_out:
                    conflicts_out.append(msg)
            elif t_res.target_type.value == "UNKNOWN":
                findings_out.append({
                    "type": "UNRESOLVED_TARGET",
                    "target": raw_t,
                    "status": "UNKNOWN",
                    "reason": f"Target '{raw_t}' could not be statically resolved in repository.",
                })
                msg = f"Target '{raw_t}' could not be statically resolved."
                if msg not in unknowns_out:
                    unknowns_out.append(msg)

        # 8. Phase 14: Database, Runtime & Reconciliation Context Assembly
        database_out: list[dict[str, object]] = []
        runtime_out: list[dict[str, object]] = []
        reconciliation_out: list[dict[str, object]] = []

        try:
            relevant_names: set[str] = set()
            for t in task_spec.targets:
                if t:
                    relevant_names.add(t.lower())
                    relevant_names.add(t.split(".")[-1].lower())
            for s_ref in symbols_out:
                relevant_names.add(s_ref.symbol.lower())
                relevant_names.add(s_ref.symbol.split(".")[-1].lower())
                if s_ref.canonical_id:
                    relevant_names.add(s_ref.canonical_id.lower())
            for word in task_display_str.lower().replace(",", " ").replace("(", " ").replace(")", " ").split():
                if len(word) >= 3:
                    relevant_names.add(word)

            db_ent_rows = con.execute(
                "SELECT canonical_id, entity_type, name, dialect, schema_name, table_name, data_type, "
                "nullable, primary_key, foreign_key_target, path, start_line, end_line, confidence, evidence_class "
                "FROM db_entities ORDER BY table_name ASC, entity_type ASC, name ASC LIMIT 80"
            ).fetchall()
            for drow in db_ent_rows:
                t_name = str(drow["table_name"] or drow["name"] or "").lower()
                e_name = str(drow["name"] or "").lower()
                d_path = str(drow["path"] or "")
                if (
                    not _guard.allows_file(d_path)
                    or not _guard.allows_symbol(str(drow["name"] or ""))
                ):
                    continue
                if (
                    t_name in relevant_names
                    or e_name in relevant_names
                    or d_path in selected_paths
                    or any(rn and (rn in t_name or t_name in rn) for rn in relevant_names if len(rn) >= 4)
                ):
                    database_out.append({
                        "record_type": "entity",
                        "canonical_id": str(drow["canonical_id"]),
                        "entity_type": str(drow["entity_type"]),
                        "name": str(drow["name"]),
                        "dialect": str(drow["dialect"]),
                        "schema": str(drow["schema_name"]),
                        "table": str(drow["table_name"] or ""),
                        "data_type": drow["data_type"],
                        "primary_key": bool(drow["primary_key"]),
                        "foreign_key_target": drow["foreign_key_target"],
                        "file": d_path,
                        "start_line": int(drow["start_line"] or 1),
                        "end_line": int(drow["end_line"] or 1),
                        "confidence": str(drow["confidence"]),
                        "evidence_class": str(drow["evidence_class"]),
                    })
                    if len(database_out) >= 20:
                        break

            db_q_rows = con.execute(
                "SELECT source_symbol, target_table, operation, relationship, path, start_line, end_line, "
                "confidence, evidence_class, snippet, framework FROM db_queries "
                "ORDER BY path ASC, start_line ASC LIMIT 50"
            ).fetchall()
            for qrow in db_q_rows:
                q_path = str(qrow["path"] or "")
                q_sym = str(qrow["source_symbol"] or "")
                q_tbl = str(qrow["target_table"] or "").lower()
                if not _guard.allows_file(q_path) or not _guard.allows_symbol(q_sym):
                    continue
                if (
                    q_path in selected_paths
                    or q_tbl in relevant_names
                    or q_sym.lower() in relevant_names
                    or q_sym.split("::")[-1].split(".")[-1].lower() in relevant_names
                ):
                    database_out.append({
                        "record_type": "query",
                        "source_symbol": q_sym,
                        "target_table": str(qrow["target_table"]),
                        "operation": str(qrow["operation"]),
                        "relationship": str(qrow["relationship"]),
                        "framework": str(qrow["framework"] or ""),
                        "file": q_path,
                        "start_line": int(qrow["start_line"] or 1),
                        "end_line": int(qrow["end_line"] or 1),
                        "confidence": str(qrow["confidence"]),
                        "evidence_class": str(qrow["evidence_class"]),
                        "snippet": redact_secrets(str(qrow["snippet"] or "")[:240]),
                    })
                    if len(database_out) >= 30:
                        break
        except Exception:
            pass

        try:
            rt_rows = con.execute(
                "SELECT source, target, relationship, observation_count, first_seen, last_seen, "
                "runtime_generation, confidence, evidence_class, sample_trace_id "
                "FROM runtime_edges ORDER BY observation_count DESC, source ASC, target ASC LIMIT 25"
            ).fetchall()
            for rrow in rt_rows:
                runtime_out.append({
                    "source": str(rrow["source"]),
                    "target": str(rrow["target"]),
                    "relationship": str(rrow["relationship"]),
                    "observation_count": int(rrow["observation_count"] or 1),
                    "first_seen": str(rrow["first_seen"] or ""),
                    "last_seen": str(rrow["last_seen"] or ""),
                    "runtime_generation": int(rrow["runtime_generation"] or 1),
                    "confidence": str(rrow["confidence"] or "HIGH"),
                    "evidence_class": "RUNTIME_OBSERVED",
                    "sample_trace_id": str(rrow["sample_trace_id"] or ""),
                })
            if runtime_out:
                from codegraph.runtime.reconciliation import reconcile_static_runtime
                rec_res = reconcile_static_runtime(con, repository)
                for item_rec in rec_res.get("items", [])[:20]:
                    reconciliation_out.append(dict(item_rec))
        except Exception:
            pass

        uncertainties: list[str] = []
        if freshness_report.status != FreshnessStatus.FRESH:
            uncertainties.append(f"Index is {freshness_report.status.value}: {freshness_report.detail}")
        if stale_paths & selected_paths:
            uncertainties.append(f"Evidence from {len(stale_paths & selected_paths)} file(s) may be stale.")
        if not candidate_dicts:
            uncertainties.append("No lexical or graph matches found. Results may be incomplete.")

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
        exec_dict["excluded_count"] = excluded_artifacts_count
        exec_dict["excluded_artifact_classes"] = sorted(excluded_artifact_classes)
        exec_dict["artifact_inclusions"] = artifact_inclusions
        exec_dict["package_context"] = target_pkg.as_dict() if target_pkg else None
        exec_dict["evidence_compression"] = compression_stats
        exec_dict["tool_efficiency"] = {
            "tool_calls": 1,
            "internal_queries_executed": len(queries_to_run),
            "consolidated_operations": [
                "target_resolution",
                "hybrid_search",
                "graph_traversal",
                "route_matching",
                "database_intelligence",
                "runtime_reconciliation",
                "test_discovery",
                "package_boundary_filtering",
                "budget_optimization",
            ],
        }
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

        coverage_dict: dict[str, object] = {
            "coverage_score": round(budget.coverage_score, 4),
            "required_dimensions": list(_retrieval_policy.required_dimensions),
            "covered_dimensions": list(budget.covered_dimensions),
            "missing_dimensions": list(budget.missing_dimensions),
            "reason_codes": {
                it.canonical_id or str(it.data.get("symbol") or it.file_path): it.reason_code
                for it in selected_items
            },
        }

        metadata_dict: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "repository": str(repository),
            "repository_generation": gen,
            "freshness": freshness_report.status.value,
            "mode": mode_upper,
            "intent": str(caller_raw_intent) if caller_raw_intent else task_spec.intent.lower(),
            "selected_tokens": budget.selected_tokens,
            "candidate_tokens": budget.candidate_tokens,
            "selected_files": len(files_out),
            "selected_lines": budget.selected_lines,
            "coverage_score": round(budget.coverage_score, 4),
            "truncated": budget.truncated,
        }

        target_dict: dict[str, object] = {
            "raw_targets": list(task_spec.targets),
            "resolutions": {
                k: {
                    "target_type": v.target_type.value,
                    "canonical_id": v.canonical_id,
                    "qualified_name": v.qualified_name,
                    "file_path": v.file_path,
                    "confidence": v.confidence,
                    "ambiguity_state": v.ambiguity_state,
                }
                for k, v in _target_resolutions.items()
            },
            "package": target_pkg.as_dict() if target_pkg else None,
        }

        git_impact_dict: dict[str, object] = {
            "recent_changes": git_changes_out,
            "modified_files_count": len(recent_paths),
            "affected_package": target_pkg.package_id if target_pkg else None,
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
            conflicts=conflicts_out,
            metadata=metadata_dict,
            target=target_dict,
            routes=entry_points_out,
            packages=packages_out,
            git_impact=git_impact_dict,
            findings=findings_out,
            coverage=coverage_dict,
            database=database_out,
            runtime=runtime_out,
            reconciliation=reconciliation_out,
            symbols=symbols_out,
            relationships=relationships_out,
            tests=tests_out,
            files=files_out,
            evidence=evidence_out,
            uncertainties=uncertainties,
            candidate_tokens=budget.candidate_tokens,
            selected_tokens=budget.selected_tokens,
            selected_lines=budget.selected_lines,
            coverage_score=round(budget.coverage_score, 4),
            truncated=budget.truncated,
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
