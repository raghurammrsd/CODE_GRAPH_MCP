"""Benchmark Baselines and Regression Detection Package."""
from __future__ import annotations

from benchmarks.baselines.regression import (
    RegressionCheckResult,
    RegressionThresholds,
    check_for_regressions,
)

__all__ = [
    "RegressionThresholds",
    "RegressionCheckResult",
    "check_for_regressions",
]
