"""Comprehensive Test Suite for Production Evaluation & Real-Agent Validation Framework."""
from pathlib import Path

from benchmarks.baselines import check_for_regressions
from benchmarks.metrics import (
    calculate_efficiency_metrics,
    calculate_path_accuracy,
    calculate_retrieval_scores,
    calculate_trust_metrics,
)
from benchmarks.reports import (
    analyze_wrong_context,
    format_cli_summary,
    format_markdown_report,
    format_trust_report_markdown,
    generate_trust_report,
    validate_selection_explanations,
)
from benchmarks.repositories import generate_full_corpus_repo
from benchmarks.runners import (
    evaluate_agent_workflow,
    run_benchmark_tasks,
    run_budget_curve_benchmark,
    run_cache_correctness_benchmark,
    run_latency_modes_benchmark,
    run_sustained_workload_simulation,
)
from benchmarks.scenarios import (
    run_ambiguity_benchmark,
    run_dynamic_dispatch_benchmark,
    run_stale_evidence_benchmark,
)
from benchmarks.tasks import BenchmarkCategory, BenchmarkTask, get_standard_benchmark_catalog


def test_benchmark_task_catalog_composition() -> None:
    catalog = get_standard_benchmark_catalog()
    assert len(catalog) == 50

    categories = {t.category for t in catalog}
    assert len(categories) == 10

    # Ensure each category has at least 5 tasks
    for cat in BenchmarkCategory:
        cat_tasks = [t for t in catalog if t.category == cat.value]
        assert len(cat_tasks) >= 5, f"Category {cat.value} has fewer than 5 tasks"


def test_metrics_calculation_unit() -> None:
    # 1. Retrieval scores
    ranked = ["AuthService", "login", "OtherService"]
    scores = calculate_retrieval_scores(ranked, {"AuthService", "login"})
    assert scores.precision == round(2 / 3, 4)
    assert scores.recall == 1.0
    assert scores.f1 > 0.0
    assert scores.mrr == 1.0  # first item is in ground truth
    assert scores.ndcg > 0.0

    # 2. Path accuracy
    path_res = calculate_path_accuracy(
        retrieved_nodes=["login_route", "AuthService", "User"],
        expected_path_nodes=("login_route", "AuthService", "DatabaseSession", "User"),
    )
    assert path_res.path_recall == 0.75
    assert path_res.path_precision == 1.0
    assert "DatabaseSession" in path_res.missing_nodes

    # 3. Trust metrics
    fake_packet = {
        "symbols": [{"symbol": "AuthService"}],
        "relationships": [{"source": "AuthService", "target": "login", "relationship": "CALLS", "evidence": "AST call", "status": "FACT"}],
        "evidence": [{"evidence_status": "current"}],
        "freshness": "FRESH",
        "unknowns": ["getattr"],
    }
    trust = calculate_trust_metrics(
        context_packet=fake_packet,
        expected_unknowns=("getattr",),
        expected_ambiguities=(),
        excluded_symbols=("ForbiddenSym",),
        expected_relationships=(("AuthService", "login", "CALLS"),),
    )
    assert trust.unsupported_claim_rate == 0.0
    assert trust.evidence_accuracy == 1.0
    assert trust.unknown_accuracy == 1.0
    assert trust.freshness_accuracy == 1.0

    # 4. Efficiency metrics
    efficiency = calculate_efficiency_metrics(
        context_packet={
            "entry_points": [{"endpoint_id": "POST /login"}],
            "symbols": [{"symbol": "AuthService", "file": "auth.py"}],
            "files": [{"file": "src/services/auth_service.py"}],
            "candidate_token_estimate": 1000,
            "selected_token_estimate": 250,
        }
    )
    assert efficiency.task_coverage > 0.0
    assert efficiency.reduction_ratio == 0.75


def test_full_corpus_e2e_runners(tmp_path: Path) -> None:
    repo = generate_full_corpus_repo(tmp_path / "repo", init_git=True)

    # Pick 2 sample tasks
    tasks = [
        BenchmarkTask(
            task_id="t1",
            repository_id="c1",
            intent="UNDERSTAND",
            prompt="Explain AuthService login",
            expected_symbols=("AuthService", "login"),
            expected_relationships=(("login_route", "AuthService", "CALLS"),),
            allowed_files=("src/services/auth_service.py",),
            excluded_symbols=("ForbiddenSymbol",),
        ),
        BenchmarkTask(
            task_id="t2",
            repository_id="c1",
            intent="TRACE",
            prompt="Trace POST /api/v1/auth/login",
            expected_entry_points=("/api/v1/auth/login",),
            expected_symbols=("login_route", "AuthService"),
        ),
    ]

    # Task runner
    task_res = run_benchmark_tasks(repo, tasks, max_tokens=5000)
    assert task_res["total_tasks"] == 2
    assert "overall" in task_res
    assert task_res["overall"]["unsupported_claim_rate"] == 0.0

    # Budget curve runner
    budget_res = run_budget_curve_benchmark(repo, tasks, budgets=(500, 2000))
    assert "500" in budget_res["curve"]
    assert "2000" in budget_res["curve"]
    assert budget_res["curve"]["500"]["avg_selected_tokens"] <= 500

    # Latency modes runner
    mode_res = run_latency_modes_benchmark(repo, iterations=1)
    assert "FAST" in mode_res
    assert "BALANCED" in mode_res
    assert "DEEP" in mode_res

    # Cache runner
    cache_res = run_cache_correctness_benchmark(repo)
    assert cache_res["speedup_factor"] >= 1.0
    assert cache_res["warm_cache_hit"] is True

    # Sustained simulator (3 cycles for quick testing)
    sim_res = run_sustained_workload_simulation(repo, cycles=3)
    assert sim_res["cycles_completed"] == 3
    assert sim_res["memory_bounded"] is True


def test_specialized_scenarios(tmp_path: Path) -> None:
    repo = generate_full_corpus_repo(tmp_path / "repo_scenarios", init_git=True)

    # 1. Ambiguity scenario
    amb_res = run_ambiguity_benchmark(repo)
    assert amb_res["is_ambiguous"] is True
    assert amb_res["candidate_definitions_count"] >= 2

    # 2. Dynamic dispatch scenario
    dyn_res = run_dynamic_dispatch_benchmark(repo)
    assert dyn_res["unknown_correctness"] is True
    assert dyn_res["false_resolved_relationships_count"] == 0

    # 3. Stale evidence lifecycle
    stale_res = run_stale_evidence_benchmark(repo)
    assert stale_res["lifecycle_passed"] is True
    assert stale_res["stale_detected"] is True
    assert stale_res["recovered_freshness"] == "FRESH"


def test_agent_evaluation_harness(tmp_path: Path) -> None:
    repo = generate_full_corpus_repo(tmp_path / "repo_agent", init_git=True)

    def dummy_agent_simulator(prompt: str, mcp_context: dict[str, object] | None) -> dict[str, object]:
        if mcp_context is None:
            # Baseline: slow, touches extra files, misses tests
            return {
                "tokens_consumed": 18000,
                "files_changed": ["src/services/auth_service.py", "unrelated.py"],
                "tests_passed": False,
                "task_completed": False,
                "unsupported_assumptions": ["Assumed legacy endpoint exists"],
            }
        # With MCP: fast, compact, correct files, tests pass
        return {
            "tokens_consumed": mcp_context.get("selected_token_estimate", 1200),
            "files_changed": ["src/services/auth_service.py"],
            "tests_passed": True,
            "task_completed": True,
            "unsupported_assumptions": [],
        }

    comparison = evaluate_agent_workflow(
        repository=repo,
        task_id="agent_task_1",
        task_prompt="Fix AuthService login issue",
        expected_files=("src/services/auth_service.py",),
        agent_simulator=dummy_agent_simulator,
    )

    assert comparison.token_savings_pct > 50.0
    assert comparison.completion_improvement is True
    assert comparison.experiment.tests_passed is True
    assert comparison.baseline.tests_passed is False
    assert len(comparison.baseline.irrelevant_files_touched) == 1
    assert len(comparison.experiment.irrelevant_files_touched) == 0


def test_reports_and_diagnostics() -> None:
    sample_results = {
        "total_tasks": 2,
        "overall": {
            "symbol_recall": 0.95,
            "symbol_precision": 0.90,
            "relationship_recall": 0.92,
            "task_coverage": 0.94,
            "unsupported_claim_rate": 0.005,
            "avg_selected_tokens": 850.0,
            "avg_reduction_ratio": 0.65,
            "avg_latency_ms": 22.5,
        },
        "categories": {
            "UNDERSTAND": {
                "count": 2,
                "symbol_recall": 0.95,
                "task_coverage": 0.94,
                "avg_reduction_ratio": 0.65,
                "avg_latency_ms": 22.5,
            }
        },
        "tasks": [
            {
                "task_id": "sample_1",
                "unsupported_claim_rate": 0.0,
                "ambiguity_accuracy": 1.0,
                "unknown_accuracy": 1.0,
            }
        ],
    }

    cli_text = format_cli_summary(sample_results)
    assert "CodeGraph MCP Production Benchmark Evaluation" in cli_text
    assert "95.0%" in cli_text

    md_text = format_markdown_report(sample_results)
    assert "# CodeGraph MCP Production Benchmark Report" in md_text
    assert "| `UNDERSTAND` |" in md_text

    trust_rep = generate_trust_report(sample_results)
    assert trust_rep["meets_target"] is True
    assert trust_rep["trust_summary"]["unsupported_claim_rate_pct"] == 0.0

    trust_md = format_trust_report_markdown(trust_rep)
    assert "Dedicated Trust & Provenance Report" in trust_md

    # Wrong context diagnostic
    fake_packet = {
        "selected_files": ["src/forbidden.py"],
        "symbols": [{"symbol": "ForbiddenSymbol"}],
        "evidence": [{"file": "src/stale.py", "evidence_status": "stale"}],
    }
    findings = analyze_wrong_context(
        task_id="t1",
        context_packet=fake_packet,
        allowed_files=("src/allowed.py",),
        excluded_files=("src/forbidden.py",),
        expected_symbols=("AllowedSymbol",),
        excluded_symbols=("ForbiddenSymbol",),
    )
    assert len(findings) == 3
    error_types = {f.error_type for f in findings}
    assert "WRONG_FILE" in error_types
    assert "WRONG_SYMBOL" in error_types
    assert "STALE_CONTEXT" in error_types

    # Why validation
    explain_packet = {
        "execution": {
            "explain": {
                "why_selected": {"item1": ["Coverage layer guarantee: 'SERVICE'", "Relevance: 0.85"]},
                "rejections": [{"reason": "Duplicate of selected symbol/chunk in src/auth.py"}],
            }
        }
    }
    val = validate_selection_explanations(explain_packet)
    assert val["valid"] is True


def test_regression_detection(tmp_path: Path) -> None:
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(
        """{
        "avg_latency_ms": 20.0,
        "symbol_recall": 0.95,
        "task_coverage": 0.90,
        "unsupported_claim_rate": 0.01
    }""",
        encoding="utf-8",
    )

    # 1. Candidate within thresholds (passes)
    good_cand = {
        "avg_latency_ms": 21.0,
        "symbol_recall": 0.94,
        "task_coverage": 0.89,
        "unsupported_claim_rate": 0.01,
    }
    res_good = check_for_regressions(good_cand, baseline_file)
    assert res_good.passed is True
    assert len(res_good.violations) == 0

    # 2. Candidate with latency and recall regressions (fails)
    bad_cand = {
        "avg_latency_ms": 45.0,  # > 25% increase
        "symbol_recall": 0.80,   # > 5% drop
        "task_coverage": 0.80,   # > 5% drop
        "unsupported_claim_rate": 0.05, # > 2% increase
    }
    res_bad = check_for_regressions(bad_cand, baseline_file)
    assert res_bad.passed is False
    assert len(res_bad.violations) >= 3
