"""Unified Benchmark Evaluation Metrics Suite."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from benchmarks.metrics.efficiency import (
    EfficiencyMetrics,
    calculate_efficiency_metrics,
    calculate_redundancy_ratio,
    calculate_structural_coverage,
)
from benchmarks.metrics.retrieval import (
    PathAccuracy,
    RetrievalScores,
    calculate_mrr,
    calculate_ndcg,
    calculate_path_accuracy,
    calculate_precision_recall,
    calculate_retrieval_scores,
)
from benchmarks.metrics.trust import (
    TrustMetrics,
    calculate_trust_metrics,
)


@dataclass
class BenchmarkTaskResult:
    task_id: str
    intent: str
    symbol_precision: float
    symbol_recall: float
    relationship_precision: float
    relationship_recall: float
    route_accuracy: float
    test_discovery_accuracy: float
    unsupported_claim_rate: float
    stale_context_rate: float
    selected_tokens: int
    reduction_ratio: float
    latency_ms: float

    # Extended intelligence metrics
    category: str = "UNDERSTAND"
    task_coverage: float = 1.0
    redundancy_ratio: float = 0.0
    mrr: float = 1.0
    ndcg: float = 1.0
    path_recall: float = 1.0
    path_precision: float = 1.0
    ambiguity_accuracy: float = 1.0
    unknown_accuracy: float = 1.0
    why_selected_valid: bool = True
    why_rejected_valid: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_task_output(
    task_id: str,
    intent: str,
    context_packet: dict[str, object],
    expected_entrypoints: list[str],
    expected_symbols: list[str],
    expected_relationships: list[str],
    expected_tests: list[str],
    excluded_symbols: list[str],
    latency_ms: float = 0.0,
    expected_path_nodes: list[str] | None = None,
    expected_unknowns: list[str] | None = None,
    expected_ambiguities: list[str] | None = None,
    category: str = "UNDERSTAND",
) -> BenchmarkTaskResult:
    """Evaluate a compiled ContextPacket against benchmark ground truth."""
    # 1. Extracted symbols
    raw_symbols = context_packet.get("symbols", [])
    retrieved_symbols: list[str] = []
    if isinstance(raw_symbols, list):
        for s in raw_symbols:
            if isinstance(s, dict):
                sym_name = str(s.get("symbol", ""))
                canon = str(s.get("canonical_id", ""))
                if sym_name:
                    retrieved_symbols.append(sym_name)
                if canon:
                    retrieved_symbols.append(canon)

    sym_scores = calculate_retrieval_scores(retrieved_symbols, set(expected_symbols))

    # 2. Extracted relationships
    raw_rels = context_packet.get("relationships", [])
    retrieved_rels: list[str] = []
    if isinstance(raw_rels, list):
        for r in raw_rels:
            if isinstance(r, dict):
                src = str(r.get("source", ""))
                tgt = str(r.get("target", ""))
                rel = str(r.get("relationship", ""))
                retrieved_rels.append(f"{src}->{tgt}")
                retrieved_rels.append(f"{rel}:{tgt}")

    rel_scores = calculate_retrieval_scores(retrieved_rels, set(expected_relationships))

    # 3. Route / Entrypoints accuracy
    raw_entries = context_packet.get("entry_points", [])
    retrieved_entries: set[str] = set()
    if isinstance(raw_entries, list):
        for ep in raw_entries:
            if isinstance(ep, dict):
                eid = str(ep.get("endpoint_id", ""))
                h = str(ep.get("handler", ""))
                if eid:
                    retrieved_entries.add(eid)
                if h:
                    retrieved_entries.add(h)

    _, route_acc = calculate_precision_recall(
        retrieved=retrieved_entries,
        expected=set(expected_entrypoints),
    )

    # 4. Test discovery accuracy
    raw_tests = context_packet.get("tests", [])
    retrieved_tests: set[str] = set()
    if isinstance(raw_tests, list):
        for t in raw_tests:
            if isinstance(t, dict):
                tf = str(t.get("file", ""))
                ts = str(t.get("symbol", ""))
                if tf:
                    retrieved_tests.add(tf)
                if ts:
                    retrieved_tests.add(ts)

    _, test_acc = calculate_precision_recall(
        retrieved=retrieved_tests,
        expected=set(expected_tests),
    )

    # 5. Trust metrics
    trust = calculate_trust_metrics(
        context_packet=context_packet,
        expected_unknowns=tuple(expected_unknowns or ()),
        expected_ambiguities=tuple(expected_ambiguities or ()),
        excluded_symbols=tuple(excluded_symbols or ()),
        expected_relationships=(),
        is_fresh_expected=True,
    )

    # 6. Efficiency metrics
    efficiency = calculate_efficiency_metrics(context_packet)

    # 7. Path accuracy (for TRACE tasks)
    path_acc = calculate_path_accuracy(
        retrieved_nodes=retrieved_symbols,
        expected_path_nodes=tuple(expected_path_nodes or ()),
    )

    # 8. Why-selected / Why-rejected validation
    exec_meta = context_packet.get("execution", {})
    why_selected_ok = True
    why_rejected_ok = True
    if isinstance(exec_meta, dict):
        explain = exec_meta.get("explain", {})
        if isinstance(explain, dict):
            why_sel = explain.get("why_selected", {})
            if why_sel and not any(isinstance(v, list) and len(v) > 0 for v in why_sel.values()):
                why_selected_ok = False
            rejections = explain.get("rejections", [])
            if rejections and not any("reason" in r for r in rejections if isinstance(r, dict)):
                why_rejected_ok = False

    return BenchmarkTaskResult(
        task_id=task_id,
        intent=intent,
        symbol_precision=sym_scores.precision,
        symbol_recall=sym_scores.recall,
        relationship_precision=rel_scores.precision,
        relationship_recall=rel_scores.recall,
        route_accuracy=route_acc,
        test_discovery_accuracy=test_acc,
        unsupported_claim_rate=trust.unsupported_claim_rate,
        stale_context_rate=round(1.0 - trust.evidence_accuracy, 4),
        selected_tokens=efficiency.selected_tokens,
        reduction_ratio=efficiency.reduction_ratio,
        latency_ms=round(latency_ms, 2),
        category=category,
        task_coverage=efficiency.task_coverage,
        redundancy_ratio=efficiency.redundancy_ratio,
        mrr=sym_scores.mrr,
        ndcg=sym_scores.ndcg,
        path_recall=path_acc.path_recall,
        path_precision=path_acc.path_precision,
        ambiguity_accuracy=trust.ambiguity_accuracy,
        unknown_accuracy=trust.unknown_accuracy,
        why_selected_valid=why_selected_ok,
        why_rejected_valid=why_rejected_ok,
    )


__all__ = [
    "BenchmarkTaskResult",
    "calculate_precision_recall",
    "calculate_mrr",
    "calculate_ndcg",
    "calculate_retrieval_scores",
    "calculate_path_accuracy",
    "evaluate_task_output",
    "TrustMetrics",
    "calculate_trust_metrics",
    "EfficiencyMetrics",
    "calculate_efficiency_metrics",
    "calculate_structural_coverage",
    "calculate_redundancy_ratio",
    "PathAccuracy",
    "RetrievalScores",
]
