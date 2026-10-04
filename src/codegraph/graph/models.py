from __future__ import annotations

from dataclasses import asdict, dataclass

from codegraph.epistemic import RelationshipEvidenceClass, validate_relationship_invariants
from codegraph.evidence_contract import validate_graph_edge_contract


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relationship: str
    confidence: str
    file: str
    start_line: int
    end_line: int
    evidence: str
    evidence_class: str = RelationshipEvidenceClass.AST_VERIFIED.value
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_relationship_invariants(self.relationship, self.evidence_class, self.reason)
        rel, ev, conf = validate_graph_edge_contract(
            self.source, self.target, self.relationship, self.evidence_class, self.confidence
        )
        object.__setattr__(self, "relationship", rel)
        object.__setattr__(self, "evidence_class", ev)
        object.__setattr__(self, "confidence", conf)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GraphSeedPolicy:
    """Policy for selecting grounded roots for graph traversal."""

    source_type: str = "EXPLICIT_TARGET"  # EXPLICIT_TARGET | ROUTE_HANDLER | DIRECT_MATCH | USER_REQUESTED
    min_confidence: str = "HIGH"  # HIGH | MEDIUM | LOW
    max_seeds: int = 6
    max_depth: int = 3
    max_nodes_budget: int = 50
    allowed_edges: frozenset[str] = frozenset({
        "CALLS",
        "CALLED_BY",
        "HANDLED_BY",
        "ROUTES_TO",
        "MOUNTS",
        "DEPENDS_ON",
        "IMPORTS",
        "TESTS",
        "DEFINES",
        "CONTAINS",
    })

