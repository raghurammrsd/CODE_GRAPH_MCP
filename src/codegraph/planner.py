"""Deterministic Retrieval Planner for CodeGraph MCP.

Translates a grounded TaskSpec into an intent-driven, deterministic RetrievalPlan.
Query groups distinguish between primary targets, callers, callees, dependencies,
tests, git changes, framework routes, and architecture slices without guessing.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from codegraph.task import AmbiguityStatus, TaskAmbiguity, TaskIntent, TaskSpec

PLAN_SCHEMA_VERSION = "1.0"


class QueryPurpose:
    PRIMARY_TARGET = "PRIMARY_TARGET"
    ENTRY_POINT = "ENTRY_POINT"
    RELATED_SYMBOLS = "RELATED_SYMBOLS"
    CALLERS = "CALLERS"
    CALLEES = "CALLEES"
    DEPENDENCIES = "DEPENDENCIES"
    IMPLEMENTATIONS = "IMPLEMENTATIONS"
    TESTS = "TESTS"
    FRAMEWORK = "FRAMEWORK"
    GIT = "GIT"
    ARCHITECTURE = "ARCHITECTURE"


@dataclass(frozen=True)
class QueryGroup:
    purpose: str
    queries: tuple[str, ...]
    weight: float = 1.0
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalPlan:
    schema_version: str = PLAN_SCHEMA_VERSION
    task_spec_hash: str = ""
    task_fingerprint: str = ""
    intent: str = ""

    query_groups: tuple[QueryGroup, ...] = ()

    required_relationships: tuple[str, ...] = ()
    optional_relationships: tuple[str, ...] = ()

    include_tests: bool = True
    include_git: bool = False
    include_framework: bool = True
    include_architecture: bool = False

    entry_point_strategy: str = "DIRECT"  # DIRECT | TRACE_FROM_ENDPOINT | TRACE_HIERARCHY | GIT_DIFF_ENTRY

    max_depth: int = 3
    max_nodes: int = 300
    max_edges: int = 1200
    token_budget: int = 20_000

    freshness_policy: str = "REQUIRE_FRESH"  # REQUIRE_FRESH | PERMIT_PARTIAL | BEST_EFFORT
    evidence_policy: str = "VERIFY_SOURCE_HASH"
    ambiguity_policy: str = "REPORT_OR_ASSUME"  # REPORT_OR_ASSUME | STRICT_FAIL | BEST_EFFORT

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_spec_hash": self.task_spec_hash or self.task_fingerprint,
            "task_fingerprint": self.task_fingerprint or self.task_spec_hash,
            "intent": self.intent,
            "query_groups": [q.as_dict() for q in self.query_groups],
            "required_relationships": list(self.required_relationships),
            "optional_relationships": list(self.optional_relationships),
            "include_tests": self.include_tests,
            "include_git": self.include_git,
            "include_framework": self.include_framework,
            "include_architecture": self.include_architecture,
            "entry_point_strategy": self.entry_point_strategy,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "token_budget": self.token_budget,
            "freshness_policy": self.freshness_policy,
            "evidence_policy": self.evidence_policy,
            "ambiguity_policy": self.ambiguity_policy,
        }


def compute_task_spec_hash(task_spec: TaskSpec) -> str:
    """Compute a deterministic SHA-256 hash of a TaskSpec."""
    canonical_payload = {
        "intent": task_spec.intent,
        "goal": task_spec.goal,
        "targets": sorted(task_spec.targets),
        "entities": sorted(task_spec.entities),
        "operations": sorted(task_spec.operations),
        "constraints": sorted(task_spec.constraints),
        "exclusions": sorted(task_spec.exclusions),
        "scope_paths": sorted(task_spec.scope_paths),
        "scope_modules": sorted(task_spec.scope_modules),
        "frameworks": sorted(task_spec.frameworks),
        "time_scope": task_spec.time_scope or "",
    }
    raw_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def build_retrieval_plan(
    task_spec: TaskSpec,
    ambiguities: tuple[TaskAmbiguity, ...] = (),
    con: sqlite3.Connection | None = None,
    token_budget: int = 20_000,
    resource_mode: str = "BALANCED",
) -> RetrievalPlan:
    """Construct an intent-specific, repository-aware RetrievalPlan for a TaskSpec."""
    spec_hash = compute_task_spec_hash(task_spec)
    intent = task_spec.intent.upper()

    # Base query items from targets
    primary_queries = tuple(task_spec.priority_targets or task_spec.targets or (task_spec.goal,))
    related_queries: list[str] = []

    if con and primary_queries:
        from codegraph.query_expansion import expand_query_terms, get_search_queries

        expansions = expand_query_terms(primary_queries[:5], con, max_expansions=8)
        expanded_terms = get_search_queries(expansions)
        for term in expanded_terms:
            if term not in primary_queries and term not in related_queries:
                related_queries.append(term)

    query_groups: list[QueryGroup] = []

    # Primary target group
    query_groups.append(
        QueryGroup(
            purpose=QueryPurpose.PRIMARY_TARGET,
            queries=primary_queries,
            weight=1.0,
            required=True,
        )
    )

    if related_queries:
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.RELATED_SYMBOLS,
                queries=tuple(related_queries[:8]),
                weight=0.75,
                required=False,
            )
        )

    # Strategy configuration based on intent
    include_tests = True
    include_git = False
    include_framework = True
    include_architecture = False
    entry_point_strategy = "DIRECT"
    max_depth = 3
    required_relationships: list[str] = []
    optional_relationships: list[str] = ["CALLS", "IMPORTS"]

    # Check explicit time_scope or operations in TaskSpec
    if task_spec.time_scope or "INSPECT_RECENT_CHANGES" in task_spec.operations:
        include_git = True

    # Adaptive depth calculation based on query complexity and resource mode
    goal_lower = (task_spec.goal or "").lower()
    is_shallow = any(pattern in goal_lower for pattern in ("where is", "where's", "find definition", "show definition", "locate"))
    mode_upper = (resource_mode or "BALANCED").upper()

    if is_shallow:
        max_depth = 1
    elif mode_upper == "FAST":
        max_depth = min(max_depth, 2)
    elif mode_upper == "DEEP":
        max_depth = max(max_depth, 5)

    if mode_upper == "FAST":
        max_nodes = 100
        max_edges = 400
    elif mode_upper == "DEEP":
        max_nodes = 600
        max_edges = 2400
    else:
        max_nodes = 300
        max_edges = 1200

    if intent in (TaskIntent.UNDERSTAND.value, TaskIntent.EXPLAIN.value):
        include_architecture = True
        required_relationships = ["HANDLED_BY", "CALLS"]
        optional_relationships = ["IMPORTS", "EXTENDS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.ARCHITECTURE,
                queries=primary_queries[:3],
                weight=0.6,
                required=False,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries[:3],
                weight=0.5,
                required=False,
            )
        )

    elif intent == TaskIntent.DEBUG.value:
        include_git = True
        entry_point_strategy = "TRACE_FROM_ENDPOINT"
        max_depth = 3
        required_relationships = ["HANDLED_BY", "CALLS"]
        optional_relationships = ["IMPORTS", "EXTENDS", "POSSIBLE_CALLS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.CALLERS,
                queries=primary_queries[:4],
                weight=0.85,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries[:3],
                weight=0.7,
                required=True,
            )
        )
        if include_git:
            query_groups.append(
                QueryGroup(
                    purpose=QueryPurpose.GIT,
                    queries=primary_queries[:3],
                    weight=0.8,
                    required=False,
                )
            )

    elif intent in (TaskIntent.CHANGE.value, TaskIntent.REFACTOR.value):
        entry_point_strategy = "DIRECT"
        max_depth = 2
        required_relationships = ["CALLS"]
        optional_relationships = ["EXTENDS", "IMPLEMENTS", "IMPORTS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.CALLERS,
                queries=primary_queries[:4],
                weight=0.9,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.CALLEES,
                queries=primary_queries[:4],
                weight=0.85,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries[:3],
                weight=0.75,
                required=True,
            )
        )

    elif intent == TaskIntent.TRACE.value:
        entry_point_strategy = "TRACE_HIERARCHY"
        max_depth = 4
        required_relationships = ["HANDLED_BY", "CALLS"]
        optional_relationships = ["IMPORTS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.FRAMEWORK,
                queries=primary_queries[:4],
                weight=0.95,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.CALLEES,
                queries=primary_queries[:4],
                weight=0.9,
                required=True,
            )
        )

    elif intent == TaskIntent.IMPACT.value:
        entry_point_strategy = "DIRECT"
        max_depth = 4
        include_architecture = True
        required_relationships = ["CALLS", "IMPORTS"]
        optional_relationships = ["HANDLED_BY", "EXTENDS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.CALLERS,
                queries=primary_queries[:5],
                weight=0.95,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.DEPENDENCIES,
                queries=primary_queries[:5],
                weight=0.8,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries[:3],
                weight=0.75,
                required=True,
            )
        )

    elif intent == TaskIntent.REVIEW.value:
        include_git = True
        entry_point_strategy = "GIT_DIFF_ENTRY"
        max_depth = 2
        required_relationships = ["CALLS"]
        optional_relationships = ["IMPORTS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.GIT,
                queries=primary_queries or ("HEAD~1..HEAD",),
                weight=1.0,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries[:3],
                weight=0.8,
                required=True,
            )
        )

    elif intent == TaskIntent.ARCHITECTURE.value:
        include_architecture = True
        include_tests = False
        max_depth = 2
        required_relationships = ["HANDLED_BY", "IMPORTS"]
        optional_relationships = ["CALLS", "EXTENDS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.ARCHITECTURE,
                queries=primary_queries,
                weight=1.0,
                required=True,
            )
        )
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.FRAMEWORK,
                queries=primary_queries,
                weight=0.85,
                required=False,
            )
        )

    elif intent == TaskIntent.TEST.value:
        include_tests = True
        max_depth = 2
        required_relationships = ["TESTED_BY", "CALLS"]
        optional_relationships = ["IMPORTS"]
        query_groups.append(
            QueryGroup(
                purpose=QueryPurpose.TESTS,
                queries=primary_queries,
                weight=1.0,
                required=True,
            )
        )

    # Ambiguity policy handling
    has_ambiguity = any(a.status == AmbiguityStatus.AMBIGUOUS for a in ambiguities)
    ambiguity_policy = "REPORT_OR_ASSUME" if has_ambiguity else "CLEAR"

    return RetrievalPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        task_spec_hash=spec_hash,
        task_fingerprint=spec_hash,
        intent=intent,
        query_groups=tuple(query_groups),
        required_relationships=tuple(dict.fromkeys(required_relationships)),
        optional_relationships=tuple(dict.fromkeys(optional_relationships)),
        include_tests=include_tests,
        include_git=include_git,
        include_framework=include_framework,
        include_architecture=include_architecture,
        entry_point_strategy=entry_point_strategy,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        token_budget=token_budget,
        freshness_policy="REQUIRE_FRESH",
        evidence_policy="VERIFY_SOURCE_HASH",
        ambiguity_policy=ambiguity_policy,
    )
