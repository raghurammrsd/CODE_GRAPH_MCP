"""v2.1 Diagnostic infrastructure regression tests."""
from __future__ import annotations

from benchmarks.diagnostics import (
    FalseNegativeClass,
    FalsePositiveClass,
    build_task_diagnostic,
    classify_false_negatives,
    classify_false_positives,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_packet(symbols: list[str], routes: list[str] | None = None) -> dict:
    return {
        "symbols": [
            {"symbol": s, "file": f"src/{s.lower()}.py", "score": 0.7, "reasons": []}
            for s in symbols
        ],
        "relationships": [],
        "entry_points": [
            {"route_path": r, "endpoint_id": r, "handler": r} for r in (routes or [])
        ],
        "tests": [],
        "task_spec": {"targets": [], "priority_targets": []},
        "budget": {"candidate_tokens": 1000, "selected_tokens": 500, "reduction_ratio": 0.5},
        "execution": {"candidate_count": 10, "selected_count": 5},
    }


# ---------------------------------------------------------------------------
# Tests: TaskDiagnosticReport fields
# ---------------------------------------------------------------------------

class TestTaskDiagnosticReportFields:
    def test_all_required_fields_present(self) -> None:
        packet = _minimal_packet(["AuthService", "login"])
        report = build_task_diagnostic(
            task_id="test_01",
            category="UNDERSTAND",
            intent="UNDERSTAND",
            prompt="How does auth work?",
            packet_dict=packet,
            expected_symbols=["AuthService", "login", "MissingService"],
            expected_relationships=["AuthService->login"],
            expected_routes=["/api/v1/auth/login"],
            expected_tests=["test_auth_login_success"],
            excluded_symbols=["AdminDashboardView"],
            excluded_files=["src/admin_panel/views.py"],
            latency_ms=25.0,
        )
        assert report.task_id == "test_01"
        assert report.category == "UNDERSTAND"
        assert report.intent == "UNDERSTAND"
        assert report.prompt == "How does auth work?"
        assert isinstance(report.expected_symbols, list)
        assert isinstance(report.retrieved_symbols, list)
        assert isinstance(report.true_positives, list)
        assert isinstance(report.false_positives, list)
        assert isinstance(report.false_negatives, list)
        assert isinstance(report.fn_classifications, list)
        assert isinstance(report.fp_classifications, list)
        assert isinstance(report.exclusion_violations, list)
        assert report.latency_ms == 25.0
        assert report.reduction_ratio == 0.5

    def test_true_positives_correct(self) -> None:
        packet = _minimal_packet(["AuthService", "login"])
        report = build_task_diagnostic(
            task_id="test_02", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test",
            packet_dict=packet,
            expected_symbols=["AuthService", "login"],
            expected_relationships=[],
            expected_routes=[],
            expected_tests=[],
            excluded_symbols=[],
            excluded_files=[],
            latency_ms=10.0,
        )
        assert set(report.true_positives) == {"AuthService", "login"}
        assert report.false_negatives == []
        assert report.false_positives == []

    def test_false_negatives_detected(self) -> None:
        packet = _minimal_packet(["AuthService"])  # only AuthService retrieved
        report = build_task_diagnostic(
            task_id="test_03", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test",
            packet_dict=packet,
            expected_symbols=["AuthService", "login", "find_user"],  # login and find_user missed
            expected_relationships=[],
            expected_routes=[],
            expected_tests=[],
            excluded_symbols=[],
            excluded_files=[],
            latency_ms=10.0,
        )
        assert "login" in report.false_negatives or "find_user" in report.false_negatives

    def test_false_positives_detected(self) -> None:
        packet = _minimal_packet(["AuthService", "UnrelatedService"])
        report = build_task_diagnostic(
            task_id="test_04", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test",
            packet_dict=packet,
            expected_symbols=["AuthService"],
            expected_relationships=[],
            expected_routes=[],
            expected_tests=[],
            excluded_symbols=[],
            excluded_files=[],
            latency_ms=10.0,
        )
        assert "UnrelatedService" in report.false_positives


# ---------------------------------------------------------------------------
# Tests: FN classification
# ---------------------------------------------------------------------------

class TestFalseNegativeClassification:
    def test_target_resolution_classification(self) -> None:
        """Symbol not in spec targets → TARGET_RESOLUTION."""
        classes = classify_false_negatives(
            expected=["MissingService"],
            retrieved=[],
            packet_dict=_minimal_packet([]),
            task_spec_dict={"targets": [], "priority_targets": []},
        )
        assert FalseNegativeClass.TARGET_RESOLUTION in classes

    def test_lexical_recall_classification(self) -> None:
        """Short name not retrieved at all → LEXICAL_RECALL."""
        classes = classify_false_negatives(
            expected=["find_user"],
            retrieved=["AuthService"],
            packet_dict=_minimal_packet(["AuthService"]),
            task_spec_dict={"targets": ["find_user"], "priority_targets": ["find_user"]},
        )
        assert len(classes) >= 1
        assert any(c in (
            FalseNegativeClass.LEXICAL_RECALL,
            FalseNegativeClass.GRAPH_TRAVERSAL,
        ) for c in classes)

    def test_exclusion_prevents_fn_classification(self) -> None:
        """Symbol that is explicitly excluded should NOT be classified as a FN."""
        classes = classify_false_negatives(
            expected=["AdminDashboardView"],
            retrieved=[],
            packet_dict=_minimal_packet([]),
            task_spec_dict={"targets": [], "priority_targets": []},
            excluded_symbols=["AdminDashboardView"],
        )
        # AdminDashboardView is excluded — should NOT generate a FN classification
        assert len(classes) == 0


# ---------------------------------------------------------------------------
# Tests: FP classification
# ---------------------------------------------------------------------------

class TestFalsePositiveClassification:
    def test_generic_name_classified_as_lexical_noise(self) -> None:
        """Symbol 'get' is generic → LEXICAL_NOISE."""
        classes = classify_false_positives(
            expected=["AuthService"],
            retrieved=["AuthService", "get"],
        )
        assert FalsePositiveClass.LEXICAL_NOISE in classes

    def test_test_noise_classification(self) -> None:
        """test_ function retrieved but not expected → TEST_NOISE."""
        classes = classify_false_positives(
            expected=["AuthService"],
            retrieved=["AuthService", "test_some_unrelated_thing"],
        )
        assert FalsePositiveClass.TEST_NOISE in classes

    def test_duplicate_symbol_classification(self) -> None:
        """Qualified form of expected short name → DUPLICATE_SYMBOL."""
        classes = classify_false_positives(
            expected=["login"],
            retrieved=["login", "auth.AuthService.login"],
        )
        assert FalsePositiveClass.DUPLICATE_SYMBOL in classes


# ---------------------------------------------------------------------------
# Tests: exclusion violations
# ---------------------------------------------------------------------------

class TestExclusionViolations:
    def test_exclusion_violation_detected(self) -> None:
        """If an excluded symbol appears in retrieved, it's an exclusion violation."""
        packet = _minimal_packet(["AuthService", "AdminDashboardView"])
        report = build_task_diagnostic(
            task_id="test_excl", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test",
            packet_dict=packet,
            expected_symbols=["AuthService"],
            expected_relationships=[],
            expected_routes=[],
            expected_tests=[],
            excluded_symbols=["AdminDashboardView"],
            excluded_files=[],
            latency_ms=5.0,
        )
        assert "AdminDashboardView" in report.exclusion_violations

    def test_no_violation_when_respected(self) -> None:
        packet = _minimal_packet(["AuthService"])
        report = build_task_diagnostic(
            task_id="test_no_excl", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test",
            packet_dict=packet,
            expected_symbols=["AuthService"],
            expected_relationships=[],
            expected_routes=[],
            expected_tests=[],
            excluded_symbols=["AdminDashboardView"],
            excluded_files=[],
            latency_ms=5.0,
        )
        assert report.exclusion_violations == []


# ---------------------------------------------------------------------------
# Tests: as_dict serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_as_dict_serializable(self) -> None:
        import json
        packet = _minimal_packet(["AuthService"])
        report = build_task_diagnostic(
            task_id="ser_test", category="UNDERSTAND", intent="UNDERSTAND",
            prompt="test", packet_dict=packet,
            expected_symbols=["AuthService"], expected_relationships=[],
            expected_routes=[], expected_tests=[],
            excluded_symbols=[], excluded_files=[], latency_ms=5.0,
        )
        d = report.as_dict()
        # Must be JSON-serializable
        json.dumps(d)
        assert d["task_id"] == "ser_test"
