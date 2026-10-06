"""Authoritative Evidence Contract for CodeGraph MCP (Phase 12).

Enforces a strict, explicit allowlist of relationship types, evidence classes,
and (relationship, evidence_class) pairs across every relationship-producing,
traversing, optimizing, and serializing path in CodeGraph.

Invariants:
- Unknown relationship types fail closed.
- Unknown evidence classes fail closed.
- Disallowed (relationship, evidence_class) combinations fail closed.
- Contradictory epistemic records (e.g. CALLS + POSSIBLE, CALLS + UNKNOWN,
  CALLS + FRAMEWORK_VERIFIED, status=FACT with POSSIBLE/UNKNOWN) fail closed.
- Raw dictionaries must be normalized and validated into `RelationshipRecord`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_PARSER_VERSION = "3.0"
PARSER_VERSION = DEFAULT_PARSER_VERSION

ALLOWED_EVIDENCE_CLASSES: frozenset[str] = frozenset({
    "AST_VERIFIED",
    "STATIC_VERIFIED",
    "FRAMEWORK_VERIFIED",
    "DATAFLOW_VERIFIED",
    "RUNTIME_OBSERVED",
    "RUNTIME_UNOBSERVED",
    "POSSIBLE",
    "UNKNOWN",
    "AMBIGUOUS",
})

ALLOWED_CONFIDENCE_LEVELS: frozenset[str] = frozenset({
    "HIGH",
    "MEDIUM",
    "LOW",
    "UNKNOWN",
})

ALLOWED_EPISTEMIC_STATUSES: frozenset[str] = frozenset({
    "FACT",
    "ASSUMPTION",
    "INFERENCE",
    "UNKNOWN",
    "CONFLICT",
    "POSSIBLE",
    "AMBIGUOUS",
    "RUNTIME_OBSERVED",
})

# Explicit ALLOWLIST mapping every canonical relationship type to its valid evidence classes.
ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX: dict[str, frozenset[str]] = {
    # Direct executable call edges — NEVER FRAMEWORK_VERIFIED, POSSIBLE, or UNKNOWN
    "CALLS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED"}),
    "CALLED_BY": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED"}),
    # Uncertain / candidate call edges — NEVER verified
    "POSSIBLE_CALLS": frozenset({"POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    # Framework routing & composition
    "MOUNTS": frozenset({"FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "ROUTE_HANDLER": frozenset({"FRAMEWORK_VERIFIED", "RUNTIME_OBSERVED", "POSSIBLE", "UNKNOWN"}),
    "HANDLED_BY": frozenset({"FRAMEWORK_VERIFIED", "RUNTIME_OBSERVED", "POSSIBLE", "UNKNOWN"}),
    "ROUTES_TO": frozenset({"FRAMEWORK_VERIFIED", "RUNTIME_OBSERVED", "POSSIBLE", "UNKNOWN"}),
    # Dependency Injection & Configuration
    "INJECTS": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "PROVIDES": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "RESOLVES_DEPENDENCY": frozenset({"DATAFLOW_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "CONFIGURES": frozenset({"DATAFLOW_VERIFIED", "FRAMEWORK_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "DI_CYCLE": frozenset({"DATAFLOW_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    # Registry, Dispatch, Events, Tasks, Commands
    "REGISTERS": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "REGISTERED_HANDLER": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "DISPATCHES_TO": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "POSSIBLE", "UNKNOWN"}),
    "EVENT_LISTENER": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TASK_HANDLER": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "COMMAND_HANDLER": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    # Monorepo / Package boundaries
    "DEPENDS_ON_PACKAGE": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "PACKAGE_IMPORTS": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "CROSS_PACKAGE_IMPORT": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "CONTAINS_PACKAGE": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED"}),
    # Test intelligence
    "TESTS": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TESTS_SYMBOL": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TESTS_ROUTE": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TESTS_PROVIDER": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TESTS_EVENT_HANDLER": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    # Structural & AST relationships
    "IMPORTS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "EXPORTS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED"}),
    "REEXPORTS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED"}),
    "EXTENDS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "IMPLEMENTS": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "DEFINES": frozenset({"AST_VERIFIED", "STATIC_VERIFIED"}),
    "CONTAINS": frozenset({"AST_VERIFIED", "STATIC_VERIFIED"}),
    "RESOLVES_TO": frozenset({"DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "BINDS_TO": frozenset({"DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "ALIASED_TO": frozenset({"DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "REFERENCES": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "USES": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "DEPENDS_ON": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "UNRESOLVED_REFERENCE": frozenset({"UNKNOWN", "POSSIBLE", "AMBIGUOUS"}),
    # Database & Persistence Intelligence (Phase 6)
    "MAPS_TO_TABLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "MAPS_TO_COLUMN": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "READS_TABLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "WRITES_TABLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "READS_COLUMN": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "WRITES_COLUMN": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "REFERENCES_TABLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "REFERENCES_COLUMN": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "FOREIGN_KEY_TO": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "HAS_PRIMARY_KEY": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED"}),
    "HAS_INDEX": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED"}),
    "HAS_UNIQUE_CONSTRAINT": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED"}),
    "HAS_CHECK_CONSTRAINT": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED"}),
    "MIGRATES_TABLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "QUERIES_DATABASE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "ORM_RELATION": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "POSSIBLE_TABLE": frozenset({"POSSIBLE", "AMBIGUOUS", "UNKNOWN"}),
    "UNKNOWN_TABLE": frozenset({"UNKNOWN", "AMBIGUOUS"}),
    # Environment variable dependency tracking (Phase 8 Security)
    "READS_ENV": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "DATAFLOW_VERIFIED"}),
    # Frontend, UI & Web Architecture (Pillar 4)
    "RENDERS": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "USES_HOOK": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "IMPORTS_STYLE": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "USES_STYLE_CLASS": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "FETCHES_ROUTE": frozenset({"AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "LOADS_SCRIPT": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "LOADS_STYLESHEET": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    # NoSQL Document Database & Collections (Mongoose / MongoDB)
    "MAPS_TO_COLLECTION": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "WRITES_COLLECTION": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "READS_COLLECTION": frozenset({"AST_VERIFIED", "STATIC_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "RUNTIME_OBSERVED", "RUNTIME_UNOBSERVED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    # Python Full-Stack (Celery, Django Signals, Templates)
    "DISPATCHES_TASK": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "TRIGGERS_SIGNAL": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "HANDLES_SIGNAL": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "RENDERS_TEMPLATE": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    # Python AI/ML Stack (PyTorch, LangChain, Ray, LlamaIndex)
    "DISPATCHES_FORWARD": frozenset({"AST_VERIFIED", "DATAFLOW_VERIFIED", "FRAMEWORK_VERIFIED", "POSSIBLE", "UNKNOWN", "AMBIGUOUS"}),
    "TOOL_HANDLER": frozenset({"FRAMEWORK_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
    "PIPELINE_STEP": frozenset({"FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "AST_VERIFIED", "POSSIBLE", "UNKNOWN"}),
}


def validate_relationship_type(relationship: str) -> str:
    """Validate that `relationship` is in the explicit allowlist. Fails closed."""
    if not isinstance(relationship, str) or not relationship.strip():
        raise ValueError("Invalid relationship type: must be a non-empty string.")
    norm = relationship.strip()
    if norm not in ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX:
        raise ValueError(
            f"Unknown or disallowed relationship type '{relationship}'. "
            f"Must be one of the canonical allowlist types."
        )
    return norm


def validate_evidence_class(evidence_class: str) -> str:
    """Validate that `evidence_class` is in the explicit allowlist. Fails closed."""
    if not isinstance(evidence_class, str) or not evidence_class.strip():
        raise ValueError("Invalid evidence_class: must be a non-empty string.")
    norm = evidence_class.strip()
    if norm not in ALLOWED_EVIDENCE_CLASSES:
        raise ValueError(
            f"Unknown or disallowed evidence_class '{evidence_class}'. "
            f"Allowed: {sorted(ALLOWED_EVIDENCE_CLASSES)}"
        )
    return norm


def validate_relationship_evidence_pair(
    relationship: str,
    evidence_class: str,
) -> tuple[str, str]:
    """Validate that `(relationship, evidence_class)` is explicitly allowed. Fails closed."""
    if not isinstance(relationship, str) or not relationship.strip():
        raise ValueError("Invalid relationship type: must be a non-empty string.")
    raw_rel = relationship.strip()
    ev = validate_evidence_class(evidence_class)
    if ev == "UNKNOWN" and raw_rel in ("CALLS", "CALLED_BY"):
        raise ValueError(
            "Epistemic invariant violation: UNKNOWN relationships cannot be exposed as authoritative 'CALLS'."
        )
    if ev == "POSSIBLE" and raw_rel in ("CALLS", "CALLED_BY"):
        raise ValueError(
            "Epistemic invariant violation: POSSIBLE relationships cannot be labeled as 'CALLS'; use 'POSSIBLE_CALLS'."
        )
    if ev == "AST_VERIFIED" and raw_rel.startswith("POSSIBLE"):
        raise ValueError(
            f"Epistemic invariant violation: POSSIBLE relationship '{raw_rel}' cannot be marked as AST_VERIFIED."
        )
    rel = validate_relationship_type(raw_rel)
    allowed_for_rel = ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX[rel]
    if ev not in allowed_for_rel:
        raise ValueError(
            f"Disallowed (relationship, evidence_class) pair: ('{rel}', '{ev}'). "
            f"Allowed evidence classes for '{rel}': {sorted(allowed_for_rel)}"
        )
    return rel, ev


@dataclass(frozen=True)
class RelationshipRecord:
    """Canonical validated relationship record preventing raw-dict contract bypass."""

    source: str
    target: str
    relationship: str
    evidence_class: str = "AST_VERIFIED"
    confidence: str = "HIGH"
    file: str = ""
    start_line: int = 1
    end_line: int = 1
    target_file: str | None = None
    target_line: int | None = None
    evidence: str = ""
    reason: str | None = None
    status: str = "FACT"
    parser_version: str = PARSER_VERSION
    index_generation: int = 0
    freshness: str = "FRESH"
    supporting_locations: tuple[str, ...] = field(default_factory=tuple)
    occurrence_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("RelationshipRecord.source must be a non-empty string.")
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("RelationshipRecord.target must be a non-empty string.")

        rel, ev = validate_relationship_evidence_pair(self.relationship, self.evidence_class)
        object.__setattr__(self, "relationship", rel)
        object.__setattr__(self, "evidence_class", ev)

        conf = str(self.confidence or "HIGH").strip().upper()
        if conf not in ALLOWED_CONFIDENCE_LEVELS:
            raise ValueError(f"Invalid confidence level '{self.confidence}'.")
        object.__setattr__(self, "confidence", conf)

        st = str(self.status or "FACT").strip().upper()
        if st not in ALLOWED_EPISTEMIC_STATUSES:
            raise ValueError(f"Invalid epistemic status '{self.status}'.")
        object.__setattr__(self, "status", st)

        # Reject contradictory epistemic combinations
        if ev == "UNKNOWN":
            if conf == "HIGH":
                raise ValueError(
                    "Contradictory RelationshipRecord: evidence_class='UNKNOWN' contradicts confidence='HIGH'."
                )
            if st == "FACT":
                raise ValueError(
                    "Contradictory RelationshipRecord: evidence_class='UNKNOWN' contradicts status='FACT'."
                )
        if ev == "POSSIBLE":
            if st == "FACT":
                raise ValueError(
                    "Contradictory RelationshipRecord: evidence_class='POSSIBLE' contradicts status='FACT'."
                )
            if conf == "HIGH":
                raise ValueError(
                    "Contradictory RelationshipRecord: evidence_class='POSSIBLE' contradicts confidence='HIGH'."
                )
        if rel == "POSSIBLE_CALLS" and conf == "HIGH":
            raise ValueError(
                "Contradictory RelationshipRecord: relationship='POSSIBLE_CALLS' contradicts confidence='HIGH'."
            )
        if rel in ("CALLS", "CALLED_BY") and ev in ("AST_VERIFIED", "DATAFLOW_VERIFIED") and conf in ("LOW", "UNKNOWN"):
            raise ValueError(
                f"Contradictory RelationshipRecord: verified '{rel}' with evidence_class='{ev}' contradicts confidence='{conf}'."
            )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "reason": self.reason,
            "status": self.status,
            "parser_version": self.parser_version,
            "index_generation": self.index_generation,
            "freshness": self.freshness,
            "supporting_locations": list(self.supporting_locations),
            "occurrence_count": self.occurrence_count,
        }
        if self.target_file is not None:
            out["target_file"] = self.target_file
        if self.target_line is not None:
            out["target_line"] = self.target_line
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


def validate_graph_edge_contract(
    source: str,
    target: str,
    relationship: str,
    evidence_class: str,
    confidence: str,
) -> tuple[str, str, str]:
    """Fast fail-closed validator for GraphEdge fields enforcing identical epistemic invariants."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("RelationshipRecord.source must be a non-empty string.")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("RelationshipRecord.target must be a non-empty string.")

    raw_ev_cls = evidence_class
    raw_conf = confidence
    if raw_ev_cls is None or str(raw_ev_cls).strip() == "":
        from codegraph.epistemic import classify_relationship_evidence

        inferred_ev, _ = classify_relationship_evidence(
            str(relationship or "").strip(), str(raw_conf or "HIGH").strip().upper()
        )
        ev_cls = inferred_ev.value
    else:
        ev_cls = str(raw_ev_cls).strip()

    rel, ev = validate_relationship_evidence_pair(relationship, ev_cls)

    if raw_conf is None or str(raw_conf).strip() == "":
        conf = "UNKNOWN" if ev == "UNKNOWN" else ("LOW" if ev == "POSSIBLE" else "HIGH")
    else:
        conf = str(raw_conf).strip().upper()

    if conf not in ALLOWED_CONFIDENCE_LEVELS:
        raise ValueError(f"Invalid confidence level '{confidence}'.")

    if ev == "UNKNOWN" and conf == "HIGH":
        raise ValueError(
            "Contradictory RelationshipRecord: evidence_class='UNKNOWN' contradicts confidence='HIGH'."
        )
    if ev == "POSSIBLE" and conf == "HIGH":
        raise ValueError(
            "Contradictory RelationshipRecord: evidence_class='POSSIBLE' contradicts confidence='HIGH'."
        )
    if rel == "POSSIBLE_CALLS" and conf == "HIGH":
        raise ValueError(
            "Contradictory RelationshipRecord: relationship='POSSIBLE_CALLS' contradicts confidence='HIGH'."
        )
    if rel in ("CALLS", "CALLED_BY") and ev in ("AST_VERIFIED", "DATAFLOW_VERIFIED") and conf in ("LOW", "UNKNOWN"):
        raise ValueError(
            f"Contradictory RelationshipRecord: verified '{rel}' with evidence_class='{ev}' contradicts confidence='{conf}'."
        )
    return rel, ev, conf


def validate_relationship_record(
    record: RelationshipRecord | dict[str, Any] | Any,
) -> RelationshipRecord:
    """Validate any relationship object or dictionary and return a canonical `RelationshipRecord`.

    Fails closed (`ValueError`) if required fields are missing or if the
    `(relationship, evidence_class, confidence, status)` combination is invalid or contradictory.
    """
    if isinstance(record, RelationshipRecord):
        validate_relationship_evidence_pair(record.relationship, record.evidence_class)
        return record

    if isinstance(record, dict):
        src = str(record.get("source") or record.get("source_symbol_id") or record.get("symbol") or "").strip()
        tgt = str(record.get("target") or record.get("target_symbol_id") or record.get("callee") or "").strip()
        rel = str(record.get("relationship") or "").strip()
        if not src or not tgt or not rel:
            raise ValueError(
                f"Invalid relationship dictionary: 'source', 'target', and 'relationship' are required (got {record!r})."
            )

        raw_ev_cls = record.get("evidence_class")
        raw_conf = record.get("confidence")
        if raw_ev_cls is None or str(raw_ev_cls).strip() == "":
            # Derive default evidence class only when not explicitly supplied, then validate strictly
            from codegraph.epistemic import classify_relationship_evidence

            inferred_ev, _ = classify_relationship_evidence(rel, str(raw_conf or "HIGH").strip().upper())
            ev_cls = inferred_ev.value
        else:
            ev_cls = str(raw_ev_cls).strip()

        if raw_conf is None or str(raw_conf).strip() == "":
            conf = "UNKNOWN" if ev_cls == "UNKNOWN" else ("LOW" if ev_cls == "POSSIBLE" else "HIGH")
        else:
            conf = str(raw_conf).strip().upper()

        raw_status = record.get("status")
        if raw_status is None or str(raw_status).strip() == "":
            if ev_cls == "UNKNOWN":
                status = "UNKNOWN"
            elif ev_cls == "POSSIBLE":
                status = "INFERENCE"
            else:
                status = "FACT"
        else:
            status = str(raw_status).strip().upper()

        f_path = str(record.get("file") or record.get("path") or "")
        s_line = int(record.get("start_line") or record.get("line") or 1)
        e_line = int(record.get("end_line") or s_line)
        supp = record.get("supporting_locations") or ()
        occ = int(record.get("occurrence_count") or 1)

        return RelationshipRecord(
            source=src,
            target=tgt,
            relationship=rel,
            evidence_class=ev_cls,
            confidence=conf,
            file=f_path,
            start_line=s_line,
            end_line=e_line,
            target_file=record.get("target_file"),
            target_line=record.get("target_line"),
            evidence=str(record.get("evidence") or ""),
            reason=record.get("reason"),
            status=status,
            parser_version=str(record.get("parser_version") or PARSER_VERSION),
            index_generation=int(record.get("index_generation") or 0),
            freshness=str(record.get("freshness") or "FRESH"),
            supporting_locations=tuple(str(x) for x in supp),
            occurrence_count=occ,
        )

    # Object with attributes (e.g., GraphEdge, Relationship Pydantic model)
    src = str(getattr(record, "source", "") or "").strip()
    tgt = str(getattr(record, "target", "") or "").strip()
    rel = str(getattr(record, "relationship", "") or "").strip()
    raw_ev_cls = getattr(record, "evidence_class", None)
    raw_conf = getattr(record, "confidence", None)
    if raw_ev_cls is None or str(raw_ev_cls).strip() == "":
        from codegraph.epistemic import classify_relationship_evidence

        inferred_ev, _ = classify_relationship_evidence(rel, str(raw_conf or "HIGH").strip().upper())
        ev_cls = inferred_ev.value
    else:
        ev_cls = str(raw_ev_cls).strip()

    if raw_conf is None or str(raw_conf).strip() == "":
        conf = "UNKNOWN" if ev_cls == "UNKNOWN" else ("LOW" if ev_cls == "POSSIBLE" else "HIGH")
    else:
        conf = str(raw_conf).strip().upper()

    raw_status = getattr(record, "status", None)
    if raw_status is None or str(raw_status).strip() == "":
        status = "UNKNOWN" if ev_cls == "UNKNOWN" else ("INFERENCE" if ev_cls == "POSSIBLE" else "FACT")
    else:
        status = str(raw_status).strip().upper()

    return RelationshipRecord(
        source=src,
        target=tgt,
        relationship=rel,
        evidence_class=ev_cls,
        confidence=conf,
        file=str(getattr(record, "file", "") or ""),
        start_line=int(getattr(record, "start_line", 1) or 1),
        end_line=int(getattr(record, "end_line", None) or getattr(record, "start_line", 1) or 1),
        target_file=getattr(record, "target_file", None),
        target_line=getattr(record, "target_line", None),
        evidence=str(getattr(record, "evidence", "") or ""),
        reason=getattr(record, "reason", None),
        status=status,
        supporting_locations=tuple(getattr(record, "supporting_locations", ()) or ()),
        occurrence_count=int(getattr(record, "occurrence_count", 1) or 1),
    )
