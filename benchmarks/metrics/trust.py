"""Trust and Provenance Metrics for CodeGraph MCP evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustMetrics:
    unsupported_claim_rate: float
    false_positive_relationship_rate: float
    false_negative_relationship_rate: float
    evidence_accuracy: float
    freshness_accuracy: float
    ambiguity_accuracy: float
    unknown_accuracy: float

    def as_dict(self) -> dict[str, float]:
        return {
            "unsupported_claim_rate": round(self.unsupported_claim_rate, 4),
            "false_positive_relationship_rate": round(self.false_positive_relationship_rate, 4),
            "false_negative_relationship_rate": round(self.false_negative_relationship_rate, 4),
            "evidence_accuracy": round(self.evidence_accuracy, 4),
            "freshness_accuracy": round(self.freshness_accuracy, 4),
            "ambiguity_accuracy": round(self.ambiguity_accuracy, 4),
            "unknown_accuracy": round(self.unknown_accuracy, 4),
        }


def calculate_trust_metrics(
    context_packet: dict[str, Any],
    expected_unknowns: tuple[str, ...],
    expected_ambiguities: tuple[str, ...],
    excluded_symbols: tuple[str, ...],
    expected_relationships: tuple[tuple[str, str, str], ...],
    is_fresh_expected: bool = True,
) -> TrustMetrics:
    """Evaluate trust dimensions: hallucination, unsupported claims, ambiguity, and freshness."""
    # 1. Unsupported claims (e.g. excluded or unverified symbols claimed as facts)
    raw_symbols = context_packet.get("symbols", [])
    retrieved_symbols: set[str] = set()
    for s in raw_symbols:
        if isinstance(s, dict):
            name = str(s.get("symbol", ""))
            canon = str(s.get("canonical_id", ""))
            if name:
                retrieved_symbols.add(name)
                retrieved_symbols.add(name.split(".")[-1])
            if canon:
                retrieved_symbols.add(canon)

    unsupported_count = sum(1 for excl in excluded_symbols if excl in retrieved_symbols)
    unsupported_rate = (
        round(unsupported_count / len(excluded_symbols), 4) if excluded_symbols else 0.0
    )

    # 2. Relationship false positive / false negative
    raw_rels = context_packet.get("relationships", [])
    retrieved_rel_tuples: set[tuple[str, str, str]] = set()
    for r in raw_rels:
        if isinstance(r, dict):
            src = str(r.get("source", ""))
            tgt = str(r.get("target", ""))
            rel = str(r.get("relationship", ""))
            retrieved_rel_tuples.add((src, tgt, rel))

    expected_rel_set = set(expected_relationships)
    if expected_rel_set:
        fn_count = len(expected_rel_set - retrieved_rel_tuples)
        fn_rate = round(fn_count / len(expected_rel_set), 4)
    else:
        fn_rate = 0.0

    if retrieved_rel_tuples:
        # False positives: relationships reported that are neither in expected nor have valid evidence
        fp_count = 0
        for r in raw_rels:
            if isinstance(r, dict):
                src = str(r.get("source", ""))
                tgt = str(r.get("target", ""))
                rel = str(r.get("relationship", ""))
                if (src, tgt, rel) not in expected_rel_set:
                    # Check if relationship has valid source-backed evidence
                    ev = str(r.get("evidence", ""))
                    if not ev or r.get("status") == "UNKNOWN":
                        fp_count += 1
        fp_rate = round(fp_count / len(retrieved_rel_tuples), 4)
    else:
        fp_rate = 0.0

    # 3. Evidence accuracy: proportion of evidence refs with valid non-stale status
    raw_evidence = context_packet.get("evidence", [])
    if raw_evidence:
        valid_ev = sum(
            1 for ev in raw_evidence
            if isinstance(ev, dict) and ev.get("evidence_status") in ("current", "fresh")
        )
        ev_accuracy = round(valid_ev / len(raw_evidence), 4)
    else:
        ev_accuracy = 1.0

    # 4. Freshness accuracy: packet freshness matches reality
    actual_freshness = str(context_packet.get("freshness", "UNKNOWN"))
    if is_fresh_expected:
        fresh_acc = 1.0 if actual_freshness == "FRESH" else 0.0
    else:
        fresh_acc = 1.0 if actual_freshness in ("STALE", "PARTIALLY_STALE") else 0.0

    # 5. Ambiguity accuracy
    task_spec = context_packet.get("task_spec", {})
    reported_ambiguities = set(task_spec.get("ambiguities", [])) if isinstance(task_spec, dict) else set()
    conflicts = set(context_packet.get("conflicts", []))

    if expected_ambiguities:
        matched_amb = sum(
            1 for ea in expected_ambiguities
            if any(ea.lower() in ra.lower() for ra in reported_ambiguities)
            or any(ea.lower() in c.lower() for c in conflicts)
        )
        amb_accuracy = round(matched_amb / len(expected_ambiguities), 4)
    else:
        amb_accuracy = 1.0 if not reported_ambiguities else 0.8

    # 6. Unknown accuracy: proportion of expected unknowns identified
    reported_unknowns = set(context_packet.get("unknowns", []))
    if expected_unknowns:
        matched_unk = sum(
            1 for eu in expected_unknowns
            if any(eu.lower() in ru.lower() for ru in reported_unknowns)
        )
        unk_accuracy = round(matched_unk / len(expected_unknowns), 4)
    else:
        unk_accuracy = 1.0

    return TrustMetrics(
        unsupported_claim_rate=unsupported_rate,
        false_positive_relationship_rate=fp_rate,
        false_negative_relationship_rate=fn_rate,
        evidence_accuracy=ev_accuracy,
        freshness_accuracy=fresh_acc,
        ambiguity_accuracy=amb_accuracy,
        unknown_accuracy=unk_accuracy,
    )
