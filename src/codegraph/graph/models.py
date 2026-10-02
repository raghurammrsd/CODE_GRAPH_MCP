from __future__ import annotations

from dataclasses import asdict, dataclass


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
        "DEPENDS_ON",
        "IMPORTS",
        "TESTS",
        "DEFINES",
        "CONTAINS",
    })

