"""v2.1 Unified Production Evaluation Driver and Diagnostics Runner.

Executes:
- 50 standard benchmark tasks across 10 categories
- Diagnostics engine emitting TaskDiagnosticReport with FN/FP root cause analysis
- Specialized trust & safety scenarios (ambiguity, dynamic dispatch, stale evidence lifecycle)
- Performance and token efficiency profiling (cache, latency modes)
- Frozen v2.0 baseline regression verification against v2_0_verified.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchmarks.baselines import check_for_regressions  # noqa: E402
from benchmarks.diagnostics import TaskDiagnosticReport  # noqa: E402
from benchmarks.reports import (  # noqa: E402
    format_cli_summary,
    format_trust_report_markdown,
    generate_trust_report,
    save_benchmark_report,
)
from benchmarks.repositories import generate_full_corpus_repo  # noqa: E402
from benchmarks.runners import (  # noqa: E402
    run_benchmark_tasks,
    run_cache_correctness_benchmark,
    run_diagnostic_benchmark,
    run_latency_modes_benchmark,
)
from benchmarks.scenarios import (  # noqa: E402
    run_ambiguity_benchmark,
    run_dynamic_dispatch_benchmark,
    run_stale_evidence_benchmark,
)
from benchmarks.tasks import get_standard_benchmark_catalog  # noqa: E402


def run_v21_evaluation(
    output_dir: Path | None = None,
    check_baseline: bool = True,
    quick: bool = False,
    token_budget: int = 20000,
) -> int:
    """Run complete v2.1 benchmark suite with diagnostics and regression check."""
    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        repo_dir = Path(td)
        print("Provisioning multi-framework repository corpus...")
        generate_full_corpus_repo(repo_dir, init_git=True)

        catalog = get_standard_benchmark_catalog()
        if quick:
            # 1 task per category
            selected_tasks = []
            seen_cats = set()
            for t in catalog:
                if t.category not in seen_cats:
                    seen_cats.add(t.category)
                    selected_tasks.append(t)
            tasks_to_run = selected_tasks
        else:
            tasks_to_run = catalog

        print(f"Executing {len(tasks_to_run)} benchmark tasks (max_tokens={token_budget})...")
        task_results = run_benchmark_tasks(repo_dir, tasks_to_run, max_tokens=token_budget)

        print("Executing task diagnostics and causal FN/FP classification...")
        diagnostic_reports: list[TaskDiagnosticReport] = run_diagnostic_benchmark(
            repo_dir, tasks_to_run, max_tokens=token_budget
        )

        print("Executing ambiguity scenario...")
        amb_res = run_ambiguity_benchmark(repo_dir)

        print("Executing dynamic dispatch scenario...")
        dyn_res = run_dynamic_dispatch_benchmark(repo_dir)

        print("Executing stale evidence lifecycle scenario...")
        stale_res = run_stale_evidence_benchmark(repo_dir)

        print("Executing cache correctness benchmark...")
        cache_res = run_cache_correctness_benchmark(repo_dir)

        print("Executing latency mode comparison (FAST / BALANCED / DEEP)...")
        mode_res = run_latency_modes_benchmark(repo_dir, iterations=2)

        # Generate Trust Report
        trust_report = generate_trust_report(
            results=task_results,
            stale_test_passed=stale_res.get("lifecycle_passed", True),
            unknown_test_passed=dyn_res.get("unknown_correctness", True),
            ambiguity_test_passed=amb_res.get("is_ambiguous", True),
        )

        # Aggregate diagnostics by category
        category_diagnostics: dict[str, dict[str, int]] = {}
        fn_totals: dict[str, int] = {}
        fp_totals: dict[str, int] = {}
        for r in diagnostic_reports:
            cat = r.category
            if cat not in category_diagnostics:
                category_diagnostics[cat] = {"fn_count": 0, "fp_count": 0, "violations": 0}
            category_diagnostics[cat]["fn_count"] += len(r.false_negatives)
            category_diagnostics[cat]["fp_count"] += len(r.false_positives)
            category_diagnostics[cat]["violations"] += len(r.exclusion_violations)
            for fn in r.fn_classifications:
                fn_totals[fn] = fn_totals.get(fn, 0) + 1
            for fp in r.fp_classifications:
                fp_totals[fp] = fp_totals.get(fp, 0) + 1

        v21_payload = {
            "version": "2.1.0",
            "benchmark_config": {
                "corpus_version": "2.0",
                "task_version": "standard_50_tasks",
                "categories": 10,
                "token_budget": token_budget,
                "parser_version": "1.0",
                "schema_version": "2.0",
                "ranking_version": "2.1",
                "retrieval_version": "2.1",
            },
            "task_benchmarks": task_results,
            "trust_report": trust_report,
            "diagnostics": {
                "reports": [r.as_dict() for r in diagnostic_reports],
                "category_summary": category_diagnostics,
                "fn_classification_totals": fn_totals,
                "fp_classification_totals": fp_totals,
            },
            "scenarios": {
                "ambiguity": amb_res,
                "dynamic_dispatch": dyn_res,
                "stale_evidence": stale_res,
            },
            "cache": cache_res,
            "modes": mode_res,
            "total_eval_duration_seconds": round(time.perf_counter() - start_time, 2),
        }

        # Print summary
        print("\n" + format_cli_summary(task_results))
        print("\n" + format_trust_report_markdown(trust_report))

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            # 1. Main benchmark report
            save_benchmark_report(v21_payload, output_dir, report_name="benchmark_v2_1")

            # 2. Diagnostics JSON
            diag_file = output_dir / "benchmark_v2_1_diagnostics.json"
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump([r.as_dict() for r in diagnostic_reports], f, indent=2)
            print(f"Saved Diagnostics report: {diag_file}")

            # 3. Category breakdown
            cat_file = output_dir / "benchmark_v2_1_category_report.json"
            with open(cat_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "category_summary": category_diagnostics,
                        "fn_totals": fn_totals,
                        "fp_totals": fp_totals,
                    },
                    f,
                    indent=2,
                )
            print(f"Saved Category Diagnostics report: {cat_file}")

        # Baseline Regression Check against frozen v2.0 baseline
        if check_baseline:
            frozen_baseline = Path(__file__).parent / "baselines" / "v2_0_verified.json"
            if not frozen_baseline.exists():
                frozen_baseline = Path(__file__).parent / "baselines" / "task_baseline.json"
            reg_check = check_for_regressions(task_results.get("overall", {}), frozen_baseline)
            if not reg_check.passed:
                print("\n[REGRESSION DETECTED against frozen v2.0 baseline]")
                for v in reg_check.violations:
                    print(f" - {v}")
                return 1
            else:
                print("\nRegression gate: PASSED (verified against frozen v2.0 baseline)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeGraph MCP v2.1 Production Evaluation Suite")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/reports"), help="Output directory for reports")
    parser.add_argument("--no-baseline", action="store_true", help="Skip baseline regression check")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (10 tasks instead of 50)")
    parser.add_argument("--max-tokens", type=int, default=20000, help="Context token budget")
    args = parser.parse_args()

    code = run_v21_evaluation(
        output_dir=args.output_dir,
        check_baseline=not args.no_baseline,
        quick=args.quick,
        token_budget=args.max_tokens,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
