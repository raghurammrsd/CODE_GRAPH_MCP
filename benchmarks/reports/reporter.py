"""Benchmark Report Generator producing JSON, Markdown, and CLI summaries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def format_cli_summary(results: dict[str, Any]) -> str:
    """Format a clean, informative CLI summary."""
    overall = results.get("overall", {})
    total_tasks = results.get("total_tasks", 0)

    sym_rec = overall.get("symbol_recall", 0.0) * 100.0
    rel_rec = overall.get("relationship_recall", 0.0) * 100.0
    task_cov = overall.get("task_coverage", 0.0) * 100.0
    unsupp = overall.get("unsupported_claim_rate", 0.0) * 100.0
    med_tok = overall.get("avg_selected_tokens", 0.0)
    med_red = overall.get("avg_reduction_ratio", 0.0) * 100.0
    avg_lat = overall.get("avg_latency_ms", 0.0)

    lines = [
        "==================================================",
        "CodeGraph MCP Production Benchmark Evaluation",
        "==================================================",
        f"Tasks Evaluated:       {total_tasks}",
        "",
        f"Symbol Recall:         {sym_rec:.1f}%",
        f"Relationship Recall:   {rel_rec:.1f}%",
        f"Task Coverage:         {task_cov:.1f}%",
        f"Unsupported Claims:    {unsupp:.1f}%",
        "",
        f"Average Context Size:  {med_tok:.0f} tokens",
        f"Token Reduction:       {med_red:.1f}%",
        f"Average Latency:       {avg_lat:.2f} ms",
        "==================================================",
    ]
    return "\n".join(lines)


def format_markdown_report(results: dict[str, Any]) -> str:
    """Produce detailed markdown report with category breakdown."""
    overall = results.get("overall", {})
    categories = results.get("categories", {})
    total_tasks = results.get("total_tasks", 0)

    md = [
        "# CodeGraph MCP Production Benchmark Report",
        "",
        f"**Total Tasks Evaluated**: {total_tasks}",
        "",
        "## Overall Summary",
        "",
        "| Metric | Score |",
        "| :--- | :--- |",
        f"| **Symbol Recall** | {overall.get('symbol_recall', 0.0) * 100:.1f}% |",
        f"| **Symbol Precision** | {overall.get('symbol_precision', 0.0) * 100:.1f}% |",
        f"| **Relationship Recall** | {overall.get('relationship_recall', 0.0) * 100:.1f}% |",
        f"| **Task Coverage** | {overall.get('task_coverage', 0.0) * 100:.1f}% |",
        f"| **Unsupported Claim Rate** | {overall.get('unsupported_claim_rate', 0.0) * 100:.1f}% |",
        f"| **Average Selected Tokens** | {overall.get('avg_selected_tokens', 0.0):.0f} |",
        f"| **Token Reduction** | {overall.get('avg_reduction_ratio', 0.0) * 100:.1f}% |",
        f"| **Average Latency** | {overall.get('avg_latency_ms', 0.0):.2f} ms |",
        "",
        "## Performance by Category",
        "",
        "| Category | Tasks | Recall | Coverage | Reduction | Latency (ms) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for cat_name, cat_stats in sorted(categories.items()):
        md.append(
            f"| `{cat_name}` | {cat_stats.get('count', 0)} | "
            f"{cat_stats.get('symbol_recall', 0.0) * 100:.1f}% | "
            f"{cat_stats.get('task_coverage', 0.0) * 100:.1f}% | "
            f"{cat_stats.get('avg_reduction_ratio', 0.0) * 100:.1f}% | "
            f"{cat_stats.get('avg_latency_ms', 0.0):.2f} |"
        )

    return "\n".join(md)


def save_benchmark_report(
    results: dict[str, Any],
    output_dir: Path,
    report_name: str = "benchmark_report",
) -> tuple[Path, Path]:
    """Save both JSON and Markdown reports to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report_name}.json"
    md_path = output_dir / f"{report_name}.md"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md_path.write_text(format_markdown_report(results), encoding="utf-8")

    return json_path, md_path
