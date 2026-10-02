"""Tests for benchmark metrics and evaluation infrastructure."""
import json
from pathlib import Path

from benchmarks.metrics import (
    BenchmarkTaskResult,
    calculate_precision_recall,
    evaluate_task_output,
)
from benchmarks.runner import run_benchmark_suite
from codegraph.indexing import Indexer


def test_calculate_precision_recall() -> None:
    # Exact match
    p, r = calculate_precision_recall({"a", "b"}, {"a", "b"})
    assert p == 1.0
    assert r == 1.0

    # Partial match
    p, r = calculate_precision_recall({"a", "b", "c"}, {"a", "b"})
    assert p == round(2 / 3, 4)
    assert r == 1.0

    # Disjoint
    p, r = calculate_precision_recall({"x"}, {"y"})
    assert p == 0.0
    assert r == 0.0

    # Both empty
    p, r = calculate_precision_recall(set(), set())
    assert p == 1.0
    assert r == 1.0


def test_evaluate_task_output() -> None:
    fake_packet = {
        "task": "Debug auth",
        "entry_points": [{"endpoint_id": "POST /login", "handler": "login"}],
        "symbols": [
            {"symbol": "AuthService"},
            {"symbol": "login"},
        ],
        "relationships": [
            {"source": "AuthService", "target": "login", "relationship": "CALLS"}
        ],
        "tests": [{"file": "tests/test_auth.py", "symbol": "test_auth"}],
        "files": [
            {
                "file": "src/auth.py",
                "evidence_status": "fresh",
            }
        ],
        "evidence": [{"evidence_status": "fresh"}],
        "selected_token_estimate": 450,
        "context_reduction_pct": 82.5,
    }

    result = evaluate_task_output(
        task_id="test-1",
        intent="DEBUG",
        context_packet=fake_packet,
        expected_entrypoints=["POST /login"],
        expected_symbols=["AuthService", "login"],
        expected_relationships=["AuthService->login"],
        expected_tests=["tests/test_auth.py"],
        excluded_symbols=["SecretKey"],
        latency_ms=12.5,
    )

    assert isinstance(result, BenchmarkTaskResult)
    assert result.task_id == "test-1"
    assert result.symbol_precision == 1.0
    assert result.symbol_recall == 1.0
    assert result.route_accuracy == 1.0
    assert result.test_discovery_accuracy == 1.0
    assert result.unsupported_claim_rate == 0.0
    assert result.selected_tokens == 450
    assert result.reduction_ratio == 0.825


def test_run_benchmark_suite_e2e(tmp_path: Path) -> None:
    repo = tmp_path / "bench_repo"
    repo.mkdir()
    (repo / "auth.py").write_text("""class AuthService:
    def login(self, username, password):
        return True
""")
    (repo / "test_auth.py").write_text("""from auth import AuthService
def test_login():
    assert AuthService().login("admin", "pass")
""")
    Indexer(repo).index()

    suite_file = tmp_path / "custom_suite.json"
    suite_data = [
        {
            "id": "task-bench-1",
            "task": "Understand AuthService.login",
            "intent": "UNDERSTAND",
            "expected_symbols": ["AuthService", "login"],
            "expected_entrypoints": [],
            "expected_relationships": [],
            "expected_tests": [],
            "excluded_symbols": [],
        }
    ]
    suite_file.write_text(json.dumps(suite_data), encoding="utf-8")

    report = run_benchmark_suite(repo, suite_file=suite_file, max_tokens=3000)
    assert "summary" in report
    assert "tasks" in report
    assert len(report["tasks"]) == 1
    assert report["tasks"][0]["task_id"] == "task-bench-1"
