"""Main CLI Execution Driver for CodeGraph MCP Production Evaluation Suite."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path for direct CLI execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchmarks.baselines import check_for_regressions  # noqa: E402
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
    run_latency_modes_benchmark,
)
from benchmarks.scenarios import (  # noqa: E402
    run_ambiguity_benchmark,
    run_dynamic_dispatch_benchmark,
    run_stale_evidence_benchmark,
)
from benchmarks.tasks import get_standard_benchmark_catalog  # noqa: E402


def run_full_evaluation(
    output_dir: Path | None = None,
    check_baseline: bool = True,
    quick: bool = False,
) -> int:
    """Run full production evaluation and return exit code (0 for success)."""
    with tempfile.TemporaryDirectory() as td:
        repo_dir = Path(td)
        print("Provisioning multi-framework repository corpus...")
        generate_full_corpus_repo(repo_dir, init_git=True)

        catalog = get_standard_benchmark_catalog()
        if quick:
            # Pick 1 task per category for rapid smoke testing
            selected_tasks = []
            seen_cats = set()
            for t in catalog:
                if t.category not in seen_cats:
                    seen_cats.add(t.category)
                    selected_tasks.append(t)
            tasks_to_run = selected_tasks
        else:
            tasks_to_run = catalog

        print(f"Executing {len(tasks_to_run)} benchmark tasks across 10 categories...")
        task_results = run_benchmark_tasks(repo_dir, tasks_to_run, max_tokens=20000)

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

        full_evaluation_payload = {
            "task_benchmarks": task_results,
            "trust_report": trust_report,
            "scenarios": {
                "ambiguity": amb_res,
                "dynamic_dispatch": dyn_res,
                "stale_evidence": stale_res,
            },
            "cache": cache_res,
            "modes": mode_res,
        }

        # Print CLI Summary
        print("\n" + format_cli_summary(task_results))
        print("\n" + format_trust_report_markdown(trust_report))

        if output_dir:
            json_file, md_file = save_benchmark_report(
                full_evaluation_payload,
                output_dir,
                report_name="production_eval_report",
            )
            print(f"\nSaved JSON report: {json_file}")
            print(f"Saved Markdown report: {md_file}")

        # Baseline Regression Check
        if check_baseline:
            baseline_file = Path(__file__).parent / "baselines" / "task_baseline.json"
            reg_check = check_for_regressions(task_results.get("overall", {}), baseline_file)
            if not reg_check.passed:
                print("\n[REGRESSION DETECTED]")
                for v in reg_check.violations:
                    print(f" - {v}")
                return 1
            else:
                print("\nRegression gate: PASSED (no regressions detected against baseline)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeGraph MCP Production Evaluation Suite")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/reports"), help="Output directory for reports")
    parser.add_argument("--no-baseline", action="store_true", help="Skip baseline regression check")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (10 tasks instead of 50)")
    args = parser.parse_args()

    code = run_full_evaluation(
        output_dir=args.output_dir,
        check_baseline=not args.no_baseline,
        quick=args.quick,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
