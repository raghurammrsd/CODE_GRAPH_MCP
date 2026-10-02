"""Tests for Adaptive Task Intelligence, Multi-Clause Decomposition, and Retrieval Planner 2.0."""
import sqlite3
from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.planner import QueryPurpose, build_retrieval_plan
from codegraph.task import (
    AmbiguityStatus,
    TaskSpec,
    decompose_prompt,
    detect_target_ambiguity,
    expand_terms_with_repository,
)


def _setup_test_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    repo = tmp_path / "repo_adaptive"
    repo.mkdir()
    (repo / "auth.py").write_text("""class AuthService:
    def login(self, email: str, password: str) -> bool:
        return True

    def logout(self, token: str) -> None:
        pass

def handle_login_request(email: str, password: str):
    service = AuthService()
    return service.login(email, password)
""")
    (repo / "routes.py").write_text("""from auth import handle_login_request

# @app.route('/api/v1/auth/login')
def login_route():
    return handle_login_request('user@example.com', 'pwd')
""")
    indexer = Indexer(repo)
    indexer.index()
    con = sqlite3.connect(indexer.db_path)
    con.row_factory = sqlite3.Row
    return repo, con


def test_adaptive_depth_and_resource_modes(tmp_path: Path) -> None:
    _, con = _setup_test_db(tmp_path)
    try:
        spec = TaskSpec(
            schema_version="2.0",
            raw_prompt="Explain AuthService login flow",
            intent="explain",
            goal="Explain AuthService login flow",
            targets=("AuthService",),
            entities=("AuthService",),
            operations=(),
            constraints=(),
            exclusions=(),
            scope_paths=(),
            scope_modules=(),
            frameworks=(),
            time_scope="all",
            priority_targets=("AuthService",),
            ambiguities=(),
            assumptions=(),
            unknowns=(),
            confidence="HIGH",
        )

        plan_fast = build_retrieval_plan(spec, ambiguities=[], con=con, resource_mode="FAST")
        assert plan_fast.max_depth <= 2
        assert plan_fast.max_nodes <= 150
        assert plan_fast.max_edges <= 500

        plan_balanced = build_retrieval_plan(spec, ambiguities=[], con=con, resource_mode="BALANCED")
        assert plan_balanced.max_depth == 3
        assert plan_balanced.max_nodes == 300
        assert plan_balanced.max_edges == 1200

        plan_deep = build_retrieval_plan(spec, ambiguities=[], con=con, resource_mode="DEEP")
        assert plan_deep.max_depth >= 5
        assert plan_deep.max_nodes >= 600
        assert plan_deep.max_edges >= 2400

        # Plan dictionary includes task_fingerprint, intent, and budgets
        plan_dict = plan_deep.as_dict()
        assert "task_fingerprint" in plan_dict
        assert "max_nodes" in plan_dict
        assert "max_edges" in plan_dict
        assert plan_dict["intent"] == "EXPLAIN"
    finally:
        con.close()


def test_decompose_prompt_multi_clause() -> None:
    prompt = "Refactor AuthService login method, update database schema for OAuth tokens, and fix related unit tests"
    clauses = decompose_prompt(prompt)
    assert len(clauses) >= 2
    # Ensure technical terms are extracted
    found_tokens = [c for c in clauses if "AuthService" in c or "OAuth" in c or "login" in c]
    assert len(found_tokens) > 0


def test_repository_backed_query_expansion(tmp_path: Path) -> None:
    _, con = _setup_test_db(tmp_path)
    try:
        expanded = expand_terms_with_repository(["AuthService", "login"], con, max_expansions=5)
        assert "AuthService" in expanded
        # Should ground against existing symbols without hallucinating random ones
        for item in expanded:
            row = con.execute(
                "SELECT 1 FROM symbols WHERE name=? OR qualified_name=? OR canonical_id LIKE ?",
                (item, item, f"%{item}%"),
            ).fetchone()
            assert row is not None
    finally:
        con.close()


def test_conflict_detection(tmp_path: Path) -> None:
    repo = tmp_path / "repo_conflict"
    repo.mkdir()
    # Create two different files with same class name
    (repo / "service_a.py").write_text("class PaymentProcessor:\n    def process(self): pass\n")
    (repo / "service_b.py").write_text("class PaymentProcessor:\n    def execute(self): pass\n")
    indexer = Indexer(repo)
    indexer.index()
    con = sqlite3.connect(indexer.db_path)
    con.row_factory = sqlite3.Row

    try:
        # 1. Conflict between targets and exclusions
        amb_conflict_target = detect_target_ambiguity(
            target="PaymentProcessor",
            con=con,
            exclusions=("PaymentProcessor",),
        )
        assert amb_conflict_target is not None
        assert amb_conflict_target.status == AmbiguityStatus.CONFLICT

        # 2. Conflicting identical definitions across distinct non-test modules
        amb_multiple = detect_target_ambiguity(
            target="PaymentProcessor",
            con=con,
            exclusions=(),
        )
        assert amb_multiple is not None
        assert amb_multiple.status in (AmbiguityStatus.CONFLICT, AmbiguityStatus.AMBIGUOUS)
    finally:
        con.close()


def test_query_purpose_enum_extensions() -> None:
    assert QueryPurpose.IMPLEMENTATIONS == "IMPLEMENTATIONS"
    assert QueryPurpose.ENTRY_POINT == "ENTRY_POINT"
