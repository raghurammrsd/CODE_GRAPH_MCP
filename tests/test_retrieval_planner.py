"""Tests for RetrievalPlan and intent-specific strategy mapper."""
import sqlite3

import pytest

from codegraph.indexing.indexer import SCHEMA
from codegraph.planner import (
    PLAN_SCHEMA_VERSION,
    RetrievalPlan,
    build_retrieval_plan,
    compute_task_spec_hash,
)
from codegraph.task import (
    TaskIntent,
    TaskSpec,
)


@pytest.fixture
def test_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    con.execute("INSERT INTO files (path, hash, language) VALUES (?, ?, ?)",
                ("src/auth.py", "h1", "python"))
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/auth.py::TokenValidator", "TokenValidator", "TokenValidator", "src/auth.py", 10, 50, "class", "python"),
    )
    con.commit()
    return con


def test_build_plan_understand() -> None:
    spec = TaskSpec(
        goal="Understand auth token validation",
        intent=TaskIntent.UNDERSTAND.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec)
    assert isinstance(plan, RetrievalPlan)
    assert plan.schema_version == PLAN_SCHEMA_VERSION
    assert plan.task_spec_hash == compute_task_spec_hash(spec)
    assert plan.include_architecture is True
    assert plan.include_git is False
    purposes = {qg.purpose for qg in plan.query_groups}
    assert "PRIMARY_TARGET" in purposes
    assert "ARCHITECTURE" in purposes


def test_build_plan_debug() -> None:
    spec = TaskSpec(
        goal="Debug authentication failure in TokenValidator",
        intent=TaskIntent.DEBUG.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec)
    assert plan.include_tests is True
    assert plan.include_git is True
    purposes = {qg.purpose for qg in plan.query_groups}
    assert "PRIMARY_TARGET" in purposes
    assert "CALLERS" in purposes
    assert "TESTS" in purposes
    assert "GIT" in purposes


def test_build_plan_trace() -> None:
    spec = TaskSpec(
        goal="Trace token validation request flow",
        intent=TaskIntent.TRACE.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec)
    assert plan.entry_point_strategy in ("TRACE_HIERARCHY", "TRACE_FROM_ENDPOINT")
    assert plan.max_depth >= 4
    purposes = {qg.purpose for qg in plan.query_groups}
    assert "PRIMARY_TARGET" in purposes
    assert "CALLEES" in purposes
    assert "FRAMEWORK" in purposes


def test_build_plan_impact() -> None:
    spec = TaskSpec(
        goal="Analyze impact of changing TokenValidator",
        intent=TaskIntent.IMPACT.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec)
    assert plan.include_tests is True
    assert plan.max_depth >= 4
    purposes = {qg.purpose for qg in plan.query_groups}
    assert "CALLERS" in purposes
    assert "DEPENDENCIES" in purposes


def test_build_plan_review() -> None:
    spec = TaskSpec(
        goal="Review recent commits on authentication",
        intent=TaskIntent.REVIEW.value,
    )
    plan = build_retrieval_plan(spec)
    assert plan.include_git is True
    assert plan.entry_point_strategy == "GIT_DIFF_ENTRY"


def test_retrieval_plan_as_dict() -> None:
    spec = TaskSpec(
        goal="Test coverage for TokenValidator",
        intent=TaskIntent.TEST.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec)
    d = plan.as_dict()
    assert d["schema_version"] == PLAN_SCHEMA_VERSION
    assert d["task_spec_hash"] == plan.task_spec_hash
    assert isinstance(d["query_groups"], list)
    assert len(d["query_groups"]) > 0
    assert d["include_tests"] is True


def test_plan_with_grounded_database(test_db: sqlite3.Connection) -> None:
    spec = TaskSpec(
        goal="Explain TokenValidator",
        intent=TaskIntent.UNDERSTAND.value,
        targets=("TokenValidator",),
    )
    plan = build_retrieval_plan(spec, con=test_db)
    # Target should be matched in the queries
    all_queries = [q for qg in plan.query_groups for q in qg.queries]
    assert "TokenValidator" in all_queries
