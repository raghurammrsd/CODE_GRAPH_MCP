"""Benchmark Reports Package."""
from __future__ import annotations

from benchmarks.reports.reporter import (
    format_cli_summary,
    format_markdown_report,
    save_benchmark_report,
)
from benchmarks.reports.trust_report import (
    format_trust_report_markdown,
    generate_trust_report,
)
from benchmarks.reports.why_validation import validate_selection_explanations
from benchmarks.reports.wrong_context import (
    WrongContextItem,
    analyze_wrong_context,
)

__all__ = [
    "format_cli_summary",
    "format_markdown_report",
    "save_benchmark_report",
    "generate_trust_report",
    "format_trust_report_markdown",
    "WrongContextItem",
    "analyze_wrong_context",
    "validate_selection_explanations",
]
