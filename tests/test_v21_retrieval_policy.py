"""v2.1 RetrievalPolicy regression tests."""
from __future__ import annotations

from codegraph.ranking import rank_candidates
from codegraph.retrieval_policy import get_retrieval_policy


class TestPolicies:
    def test_trace_policy_allows_handled_by(self) -> None:
        policy = get_retrieval_policy("TRACE")
        assert policy.allows("HANDLED_BY")
        assert policy.allows("CALLS")
        assert policy.allows("ROUTES_TO")
        assert policy.allows("TESTS")

    def test_trace_policy_includes_framework(self) -> None:
        policy = get_retrieval_policy("TRACE")
        assert policy.include_framework
        assert policy.include_tests
        assert policy.max_graph_depth == 4

    def test_understand_policy(self) -> None:
        policy = get_retrieval_policy("UNDERSTAND")
        assert policy.allows("DEFINES")
        assert policy.allows("CALLS")
        assert policy.allows("IMPORTS")
        assert policy.max_graph_depth == 2

    def test_architecture_policy(self) -> None:
        policy = get_retrieval_policy("ARCHITECTURE")
        assert policy.allows("IMPORTS")
        assert policy.allows("DEPENDS_ON")
        assert policy.include_architecture
        assert not policy.include_callers
        assert policy.max_graph_depth == 1

    def test_impact_policy_no_callees(self) -> None:
        policy = get_retrieval_policy("IMPACT")
        assert policy.include_callers
        assert not policy.include_callees

    def test_test_policy_boosts_tests(self) -> None:
        policy = get_retrieval_policy("TEST")
        assert policy.include_tests
        assert not policy.include_callers

    def test_review_includes_git(self) -> None:
        policy = get_retrieval_policy("REVIEW")
        assert policy.include_git

    def test_unknown_intent_falls_back_to_understand(self) -> None:
        policy = get_retrieval_policy("UNKNOWN_INTENT_XYZ")
        understand = get_retrieval_policy("UNDERSTAND")
        assert policy.intent == understand.intent

    def test_case_insensitive(self) -> None:
        assert get_retrieval_policy("trace") == get_retrieval_policy("TRACE")
        assert get_retrieval_policy("Debug") == get_retrieval_policy("DEBUG")


class TestPolicyRelationshipPenalty:
    def test_disallowed_relationship_gets_penalized(self) -> None:
        """Candidates with relationship not in allowlist get a RELATIONSHIP_NOT_ALLOWED penalty."""
        # ARCHITECTURE only allows IMPORTS, DEPENDS_ON, etc — not CALLS
        policy = get_retrieval_policy("ARCHITECTURE")
        candidate = {
            "file": "src/services/auth_service.py",
            "symbol": "AuthService",
            "canonical_id": "auth.AuthService",
            "start_line": 10,
            "end_line": 100,
            "score": 0.5,
            "snippet": "class AuthService:",
            "relationship": "CALLS",  # not in ARCHITECTURE policy
            "confidence": "HIGH",
            "freshness": "FRESH",
        }
        ranked = rank_candidates(
            [candidate],
            query="architecture overview",
            intent="architecture",
            allowed_relationships=policy.allowed_relationship_types,
        )
        assert len(ranked) == 1
        reason_codes = [r.code for r in ranked[0].reasons]
        assert "RELATIONSHIP_NOT_ALLOWED" in reason_codes

    def test_allowed_relationship_no_penalty(self) -> None:
        """Candidates with allowed relationship type must NOT get RELATIONSHIP_NOT_ALLOWED."""
        policy = get_retrieval_policy("TRACE")
        candidate = {
            "file": "src/api/fastapi_app.py",
            "symbol": "login_route",
            "canonical_id": "api.login_route",
            "start_line": 30,
            "end_line": 50,
            "score": 0.7,
            "snippet": "def login_route():",
            "relationship": "HANDLED_BY",  # allowed in TRACE
            "confidence": "HIGH",
            "freshness": "FRESH",
        }
        ranked = rank_candidates(
            [candidate],
            query="login authentication",
            intent="trace",
            allowed_relationships=policy.allowed_relationship_types,
        )
        assert len(ranked) == 1
        reason_codes = [r.code for r in ranked[0].reasons]
        assert "RELATIONSHIP_NOT_ALLOWED" not in reason_codes

    def test_no_allowlist_no_penalty(self) -> None:
        """When allowed_relationships is None, no penalty is applied."""
        candidate = {
            "file": "src/services/auth_service.py",
            "symbol": "AuthService",
            "canonical_id": "auth.AuthService",
            "start_line": 10,
            "end_line": 100,
            "score": 0.5,
            "snippet": "class AuthService:",
            "relationship": "CALLS",
            "confidence": "HIGH",
            "freshness": "FRESH",
        }
        ranked = rank_candidates(
            [candidate],
            query="auth",
            intent="trace",
            allowed_relationships=None,  # no policy filter
        )
        reason_codes = [r.code for r in ranked[0].reasons]
        assert "RELATIONSHIP_NOT_ALLOWED" not in reason_codes
