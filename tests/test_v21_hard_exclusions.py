"""v2.1 Hard Exclusion Propagation regression tests."""
from __future__ import annotations

from typing import Any

from codegraph.optimizer import CandidateContextItem, _is_excluded
from codegraph.task import TaskSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_spec(exclusions: tuple[str, ...]) -> TaskSpec:
    return TaskSpec(raw_prompt="test", goal="test", exclusions=exclusions)


def _make_item(
    canonical_id: str | None = None,
    symbol: str | None = None,
    file_path: str = "src/services/auth_service.py",
) -> CandidateContextItem:
    data: dict[str, Any] = {}
    if symbol:
        data["symbol"] = symbol
    return CandidateContextItem(
        item_id=f"item_{canonical_id or symbol or 'unknown'}",
        file_path=file_path,
        start_line=1,
        end_line=10,
        canonical_id=canonical_id,
        estimated_tokens=100,
        relevance_score=0.8,
        evidence_quality=1.0,
        freshness="FRESH",
        coverage_layer="GENERAL",
        source_type="symbol",
        snippet="",
        confidence="HIGH",
        epistemic_status="FACT",
        data=data,
    )


# ---------------------------------------------------------------------------
# Tests: hierarchical class exclusion
# ---------------------------------------------------------------------------


class TestHierarchicalClassExclusion:
    def test_class_itself_excluded(self) -> None:
        spec = _make_spec(("AuthService",))
        item = _make_item(canonical_id="auth.AuthService")
        assert _is_excluded(item, spec)

    def test_class_method_excluded(self) -> None:
        """AuthService in exclusions → AuthService.login must also be excluded."""
        spec = _make_spec(("AuthService",))
        item = _make_item(canonical_id="AuthService.login")
        assert _is_excluded(item, spec)

    def test_class_method_with_module_excluded(self) -> None:
        spec = _make_spec(("AuthService",))
        item = _make_item(canonical_id="auth.services.AuthService.get_user_by_token")
        assert _is_excluded(item, spec)

    def test_unrelated_class_not_excluded(self) -> None:
        spec = _make_spec(("AuthService",))
        item = _make_item(canonical_id="PaymentService")
        assert not _is_excluded(item, spec)

    def test_admin_dashboard_hierarchy(self) -> None:
        spec = _make_spec(("AdminDashboardView",))
        assert _is_excluded(_make_item(canonical_id="AdminDashboardView"), spec)
        assert _is_excluded(_make_item(canonical_id="AdminDashboardView.get"), spec)
        assert _is_excluded(_make_item(canonical_id="AdminDashboardView.post"), spec)
        assert not _is_excluded(_make_item(canonical_id="AuthService"), spec)


# ---------------------------------------------------------------------------
# Tests: file path exclusion
# ---------------------------------------------------------------------------


class TestFilePathExclusion:
    def test_exact_file_excluded(self) -> None:
        spec = _make_spec(("src/admin_panel/views.py",))
        item = _make_item(file_path="src/admin_panel/views.py")
        assert _is_excluded(item, spec)

    def test_file_prefix_excluded(self) -> None:
        spec = _make_spec(("src/admin_panel",))
        item = _make_item(file_path="src/admin_panel/views.py")
        assert _is_excluded(item, spec)

    def test_unrelated_file_not_excluded(self) -> None:
        spec = _make_spec(("src/admin_panel",))
        item = _make_item(file_path="src/services/auth_service.py")
        assert not _is_excluded(item, spec)


# ---------------------------------------------------------------------------
# Tests: no exclusions
# ---------------------------------------------------------------------------


class TestNoExclusions:
    def test_no_spec_not_excluded(self) -> None:
        assert not _is_excluded(_make_item(canonical_id="anything"), None)

    def test_empty_exclusions_not_excluded(self) -> None:
        spec = _make_spec(())
        assert not _is_excluded(_make_item(canonical_id="anything"), spec)


# ---------------------------------------------------------------------------
# Tests: optimizer pass
# ---------------------------------------------------------------------------


class TestOptimizerExclusion:
    def test_optimizer_filters_excluded(self) -> None:
        from codegraph.optimizer import optimize_context_budget

        spec = _make_spec(("AuthService",))
        items = [
            _make_item(canonical_id="auth.AuthService", symbol="AuthService"),
            _make_item(canonical_id="auth.AuthService.login", symbol="AuthService.login"),
            _make_item(canonical_id="PaymentService", symbol="PaymentService"),
        ]
        selected, _ = optimize_context_budget(items, token_budget=50_000, task_spec=spec)
        selected_ids = {it.canonical_id for it in selected}
        assert "auth.AuthService" not in selected_ids
        assert "auth.AuthService.login" not in selected_ids
        assert "PaymentService" in selected_ids
