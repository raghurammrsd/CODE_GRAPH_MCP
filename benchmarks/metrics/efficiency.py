"""Context Coverage, Redundancy, and Token Efficiency Metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EfficiencyMetrics:
    task_coverage: float
    redundancy_ratio: float
    candidate_tokens: int
    selected_tokens: int
    reduction_ratio: float
    coverage_per_1k_tokens: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_coverage": round(self.task_coverage, 4),
            "redundancy_ratio": round(self.redundancy_ratio, 4),
            "candidate_tokens": self.candidate_tokens,
            "selected_tokens": self.selected_tokens,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "coverage_per_1k_tokens": round(self.coverage_per_1k_tokens, 4),
        }


def calculate_structural_coverage(
    context_packet: dict[str, Any],
    required_layers: tuple[str, ...] = ("ENTRYPOINT", "SERVICE", "DATA", "TEST"),
) -> float:
    """Calculate structural coverage over required architectural layers."""
    if not required_layers:
        return 1.0

    present_layers: set[str] = set()

    # 1. Entrypoints present?
    if context_packet.get("entry_points"):
        present_layers.add("ENTRYPOINT")

    # 2. Tests present?
    if context_packet.get("tests"):
        present_layers.add("TEST")

    # 3. Check symbols / files / explain coverage
    exec_dict = context_packet.get("execution", {})
    if isinstance(exec_dict, dict):
        explain_dict = exec_dict.get("explain", {})
        if isinstance(explain_dict, dict):
            cov_map = explain_dict.get("coverage_layers", {})
            for layer, count in cov_map.items():
                if count > 0:
                    present_layers.add(str(layer).upper())

    # Check files as fallback
    files = context_packet.get("selected_files", [])
    for f in files:
        fl = str(f).lower()
        if "route" in fl or "api" in fl or "view" in fl:
            present_layers.add("ENTRYPOINT")
        if "service" in fl or "controller" in fl:
            present_layers.add("SERVICE")
        if "model" in fl or "db" in fl or "gateway" in fl or "schema" in fl:
            present_layers.add("DATA")
        if "test" in fl:
            present_layers.add("TEST")

    matched = sum(1 for req in required_layers if req.upper() in present_layers)
    return round(matched / len(required_layers), 4)


def calculate_redundancy_ratio(context_packet: dict[str, Any]) -> float:
    """Calculate redundancy ratio from duplicate symbols, file ranges, or identical snippets."""
    symbols = context_packet.get("symbols", [])
    files = context_packet.get("files", [])

    total_elements = len(symbols) + len(files)
    if total_elements <= 1:
        return 0.0

    seen_keys: set[str] = set()
    dup_count = 0

    for s in symbols:
        if isinstance(s, dict):
            sym = str(s.get("symbol", ""))
            f = str(s.get("file", ""))
            k = f"sym:{f}:{sym}"
            if k in seen_keys:
                dup_count += 1
            else:
                seen_keys.add(k)

    for f_item in files:
        if isinstance(f_item, dict):
            f_path = str(f_item.get("file", ""))
            k = f"file:{f_path}"
            if k in seen_keys:
                dup_count += 1
            else:
                seen_keys.add(k)

    return round(dup_count / total_elements, 4)


def calculate_efficiency_metrics(
    context_packet: dict[str, Any],
    required_layers: tuple[str, ...] = ("ENTRYPOINT", "SERVICE", "DATA", "TEST"),
) -> EfficiencyMetrics:
    coverage = calculate_structural_coverage(context_packet, required_layers)
    redundancy = calculate_redundancy_ratio(context_packet)

    budget_dict = context_packet.get("budget", {})
    if isinstance(budget_dict, dict) and "selected_tokens" in budget_dict:
        selected_tokens = int(str(budget_dict.get("selected_tokens", 0)))
        reduction_ratio = float(str(budget_dict.get("reduction_ratio", 0.0)))
        candidate_tokens = int(str(budget_dict.get("candidate_tokens", 0)))
    elif "context_reduction_pct" in context_packet:
        selected_tokens = int(str(context_packet.get("selected_token_estimate", 0)))
        pct = float(str(context_packet.get("context_reduction_pct", 0.0)))
        reduction_ratio = round(pct / 100.0, 4)
        candidate_tokens = int(context_packet.get("candidate_token_estimate", 0))
    else:
        candidate_tokens = int(context_packet.get("candidate_token_estimate", 0))
        selected_tokens = int(context_packet.get("selected_token_estimate", 0))
        if candidate_tokens > 0:
            reduction_ratio = round(1.0 - (selected_tokens / candidate_tokens), 4)
        else:
            reduction_ratio = 0.0

    # Coverage per 1000 tokens (normalized efficiency score)
    tokens_k = max(selected_tokens / 1000.0, 0.1)
    cov_per_1k = round(coverage / tokens_k, 4)

    return EfficiencyMetrics(
        task_coverage=coverage,
        redundancy_ratio=redundancy,
        candidate_tokens=candidate_tokens,
        selected_tokens=selected_tokens,
        reduction_ratio=reduction_ratio,
        coverage_per_1k_tokens=cov_per_1k,
    )
