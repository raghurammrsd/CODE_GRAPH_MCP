"""Regression Detection Engine comparing candidate runs against recorded baselines."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RegressionThresholds:
    max_latency_regression_pct: float = 25.0
    max_memory_regression_pct: float = 25.0
    max_cpu_regression_pct: float = 30.0
    max_recall_drop_pct: float = 5.0
    max_coverage_drop_pct: float = 5.0
    max_unsupported_claim_increase_pct: float = 2.0


@dataclass(frozen=True)
class RegressionCheckResult:
    passed: bool
    violations: tuple[str, ...]
    candidate_metrics: dict[str, Any]
    baseline_metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "candidate_metrics": self.candidate_metrics,
            "baseline_metrics": self.baseline_metrics,
        }


def check_for_regressions(
    candidate_summary: dict[str, Any],
    baseline_path: Path,
    thresholds: RegressionThresholds | None = None,
) -> RegressionCheckResult:
    """Compare candidate summary against recorded baseline and detect regressions."""
    if thresholds is None:
        thresholds = RegressionThresholds()

    if not baseline_path.exists():
        # No baseline yet; candidate becomes the de-facto baseline
        return RegressionCheckResult(
            passed=True,
            violations=(),
            candidate_metrics=candidate_summary,
            baseline_metrics={},
        )

    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_summary = baseline_data.get("results", baseline_data)

    violations: list[str] = []

    # 1. Latency regression
    cand_lat = float(candidate_summary.get("avg_latency_ms", 0.0))
    base_lat = float(baseline_summary.get("avg_latency_ms", 0.0))
    if base_lat > 0 and cand_lat > base_lat:
        pct_increase = ((cand_lat - base_lat) / base_lat) * 100.0
        if pct_increase > thresholds.max_latency_regression_pct:
            violations.append(
                f"Latency regressed by {pct_increase:.1f}% ({base_lat}ms -> {cand_lat}ms, threshold: {thresholds.max_latency_regression_pct}%)"
            )

    # 2. Recall drop
    cand_rec = float(candidate_summary.get("symbol_recall", candidate_summary.get("avg_symbol_recall", 1.0)))
    base_rec = float(baseline_summary.get("symbol_recall", baseline_summary.get("avg_symbol_recall", 1.0)))
    if base_rec > 0 and cand_rec < base_rec:
        pct_drop = ((base_rec - cand_rec) / base_rec) * 100.0
        if pct_drop > thresholds.max_recall_drop_pct:
            violations.append(
                f"Symbol recall dropped by {pct_drop:.1f}% ({base_rec} -> {cand_rec}, threshold: {thresholds.max_recall_drop_pct}%)"
            )

    # 3. Coverage drop
    cand_cov = float(candidate_summary.get("task_coverage", 1.0))
    base_cov = float(baseline_summary.get("task_coverage", 1.0))
    if base_cov > 0 and cand_cov < base_cov:
        pct_drop = ((base_cov - cand_cov) / base_cov) * 100.0
        if pct_drop > thresholds.max_coverage_drop_pct:
            violations.append(
                f"Task coverage dropped by {pct_drop:.1f}% ({base_cov} -> {cand_cov}, threshold: {thresholds.max_coverage_drop_pct}%)"
            )

    # 4. Unsupported claim increase
    cand_unsupp = float(candidate_summary.get("unsupported_claim_rate", 0.0))
    base_unsupp = float(baseline_summary.get("unsupported_claim_rate", 0.0))
    if cand_unsupp > (base_unsupp + (thresholds.max_unsupported_claim_increase_pct / 100.0)):
        violations.append(
            f"Unsupported claim rate increased from {base_unsupp:.3f} to {cand_unsupp:.3f}"
        )

    return RegressionCheckResult(
        passed=len(violations) == 0,
        violations=tuple(violations),
        candidate_metrics=candidate_summary,
        baseline_metrics=baseline_summary,
    )
