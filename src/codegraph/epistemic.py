"""Epistemic classification for CodeGraph findings.

Every relationship or claim is classified as:
  FACT        — parser-confirmed, source-backed.
  INFERENCE   — statically plausible but not directly confirmed.
  UNKNOWN     — not determinable from static analysis.
  CONFLICT    — two sources contradict each other.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class EpistemicStatus(StrEnum):
    FACT = "FACT"
    ASSUMPTION = "ASSUMPTION"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class RelationshipEvidenceClass(StrEnum):
    """Rigorous epistemic classification for code graph relationships.

    Invariants:
    1. AST_VERIFIED: directly proven by static AST inspection (direct calls, containment, imports, inheritance).
    2. FRAMEWORK_VERIFIED: proven by deterministic framework route or registration analysis (FastAPI, Flask, Express, Django).
    3. DATAFLOW_VERIFIED: proven by deterministic local data-flow, alias resolution, or assignment binding.
    4. POSSIBLE: plausible semantic candidate that cannot be proven statically (must never be upgraded to AST_VERIFIED).
    5. UNKNOWN: dynamically dispatched, reflected, or statically unverifiable relationship (must never be labeled as CALLS).
    """
    AST_VERIFIED = "AST_VERIFIED"
    STATIC_VERIFIED = "STATIC_VERIFIED"
    FRAMEWORK_VERIFIED = "FRAMEWORK_VERIFIED"
    DATAFLOW_VERIFIED = "DATAFLOW_VERIFIED"
    RUNTIME_OBSERVED = "RUNTIME_OBSERVED"
    RUNTIME_UNOBSERVED = "RUNTIME_UNOBSERVED"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


def validate_relationship_invariants(
    relationship: str,
    evidence_class: RelationshipEvidenceClass | str,
    reason: str | None = None,
) -> None:
    """Enforce non-negotiable epistemic invariants across CodeGraph via authoritative evidence_contract:

    1. Unknown relationship types and unknown evidence classes fail closed.
    2. Disallowed (relationship, evidence_class) pairs fail closed.
    3. UNKNOWN relationships must never be exposed as authoritative CALLS.
    4. POSSIBLE relationships must never be marked as AST_VERIFIED.
    5. CALLS relationships must be AST_VERIFIED or DATAFLOW_VERIFIED (never FRAMEWORK_VERIFIED, UNKNOWN, or POSSIBLE).
    """
    del reason
    from codegraph.evidence_contract import validate_relationship_evidence_pair

    e_class = (
        evidence_class.value
        if isinstance(evidence_class, RelationshipEvidenceClass)
        else str(evidence_class)
    )
    validate_relationship_evidence_pair(str(relationship), e_class)


def classify_relationship_evidence(
    relationship: str,
    confidence: str = "HIGH",
    reason: str | None = None,
) -> tuple[RelationshipEvidenceClass, str | None]:
    """Deterministically map a relationship and confidence to its epistemic evidence class."""
    from codegraph.evidence_contract import validate_relationship_type

    rel = validate_relationship_type(relationship.strip().upper())
    conf = confidence.upper()

    if conf == "UNKNOWN" or rel.startswith("UNKNOWN") or rel == "UNRESOLVED_REFERENCE":
        return RelationshipEvidenceClass.UNKNOWN, reason or "static_resolution_unavailable"

    if conf == "LOW" or rel.startswith("POSSIBLE"):
        return RelationshipEvidenceClass.POSSIBLE, reason or "unresolved_dynamic_candidate"

    if rel in (
        "HANDLED_BY",
        "ROUTE_HANDLER",
        "ROUTES_TO",
        "REGISTERS",
        "REGISTERED_HANDLER",
        "MOUNTS",
        "EVENT_LISTENER",
        "TASK_HANDLER",
        "COMMAND_HANDLER",
        "INJECTS",
        "DEPENDS_ON_PACKAGE",
        "TESTS_ROUTE",
        "TESTS_EVENT_HANDLER",
    ):
        return RelationshipEvidenceClass.FRAMEWORK_VERIFIED, reason

    if rel in (
        "RESOLVES_TO",
        "BINDS_TO",
        "ALIASED_TO",
        "DISPATCHES_TO",
        "PROVIDES",
        "RESOLVES_DEPENDENCY",
        "CONFIGURES",
        "DI_CYCLE",
        "TESTS_PROVIDER",
    ):
        return RelationshipEvidenceClass.DATAFLOW_VERIFIED, reason

    return RelationshipEvidenceClass.AST_VERIFIED, reason


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FreshnessLevel(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass
class Finding:
    status: EpistemicStatus
    statement: str
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None
    evidence: str = ""
    confidence: str = "HIGH"   # HIGH | MEDIUM | LOW | UNKNOWN
    freshness: str = "FRESH"    # FRESH | STALE | UNKNOWN

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def fact(
    statement: str,
    file: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    symbol: str | None = None,
    evidence: str = "",
    confidence: str = "HIGH",
) -> Finding:
    return Finding(EpistemicStatus.FACT, statement, file, start_line, end_line, symbol, evidence, confidence)


def inference(
    statement: str,
    file: str | None = None,
    symbol: str | None = None,
    evidence: str = "",
) -> Finding:
    return Finding(EpistemicStatus.INFERENCE, statement, file, symbol=symbol, evidence=evidence, confidence="MEDIUM")


def unknown(statement: str, evidence: str = "") -> Finding:
    return Finding(EpistemicStatus.UNKNOWN, statement, evidence=evidence, confidence="LOW")


def assumption(
    statement: str,
    file: str | None = None,
    symbol: str | None = None,
    evidence: str = "",
    confidence: str = "MEDIUM",
) -> Finding:
    return Finding(EpistemicStatus.ASSUMPTION, statement, file, symbol=symbol, evidence=evidence, confidence=confidence)


def conflict(statement: str, evidence: str = "") -> Finding:
    return Finding(EpistemicStatus.CONFLICT, statement, evidence=evidence, confidence="LOW")
