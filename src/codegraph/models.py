"""Unified domain models for the CodeGraph intelligence engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel

from codegraph.graph.models import GraphEdge
from codegraph.indexing.models import (
    CallRef,
    Chunk,
    ImportRef,
    InheritanceRef,
    Reference,
    Symbol,
    build_canonical_id,
    normalize_module,
)

Import = ImportRef
Call = CallRef

NodeType = Literal[
    "FILE",
    "MODULE",
    "CLASS",
    "FUNCTION",
    "METHOD",
    "API_ENDPOINT",
    "API",
    "TEST",
    "TYPE",
    "CONFIG",
    "EXTERNAL_SERVICE",
]

EdgeType = Literal[
    "DEFINES",
    "CONTAINS",
    "IMPORTS",
    "EXPORTS",
    "REEXPORTS",
    "CALLS",
    "CALLED_BY",
    "POSSIBLE_CALLS",
    "REFERENCES",
    "EXTENDS",
    "IMPLEMENTS",
    "USES",
    "ROUTES_TO",
    "TESTS",
    "DEPENDS_ON",
    "CONFIGURES",
]

ErrorCategory = Literal[
    "INVALID_INPUT",
    "NOT_FOUND",
    "SECURITY_DENIED",
    "STALE_INDEX",
    "INDEX_STALE",
    "INDEX_UNAVAILABLE",
    "PARSER_ERROR",
    "UNSUPPORTED_LANGUAGE",
    "STORAGE_ERROR",
    "INTERNAL_ERROR",
]


@dataclass(frozen=True)
class Repository:
    path: str
    name: str
    head_commit: str | None = None
    branch: str | None = None


@dataclass(frozen=True)
class File:
    path: str
    hash: str
    language: str
    indexed_at: int = 0
    status: str = "ok"  # ok | parse_failed
    parse_error: str | None = None


@dataclass(frozen=True)
class SymbolLocation:
    canonical_id: str
    path: str
    start_line: int
    end_line: int
    source_hash: str = ""


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    name: str
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    indexed_commit: str | None
    current_commit: str | None
    parser_version: str
    schema_version: int
    index_generation: int
    timestamp: int
    file_count: int
    symbol_count: int
    reference_count: int


@dataclass(frozen=True)
class FreshnessState:
    status: str  # FRESH | PARTIALLY_STALE | STALE | UNKNOWN
    indexed_commit: str | None
    current_commit: str | None
    modified_files: list[str]
    deleted_files: list[str]
    added_files: list[str]
    parse_failed_files: list[str]
    detail: str


@dataclass(frozen=True)
class ContextCandidate:
    file: str
    symbol: str | None
    canonical_id: str | None
    kind: str
    start_line: int
    end_line: int
    snippet: str
    confidence: str = "HIGH"
    freshness: str = "FRESH"
    relationship: str = ""
    distance: int = 0
    score: float = 0.0


class TestRelationship(BaseModel):
    schema_version: str = "1.0"
    file: str
    symbol: str | None = None
    target_symbol: str | None = None
    classification: str = "VERIFIED_TEST"  # VERIFIED_TEST | POSSIBLE_TEST
    relationship: str
    confidence: str
    start_line: int = 1
    evidence: str


class ImpactItem(BaseModel):
    symbol: str | None = None
    file: str
    impact_type: str  # direct | indirect | potential | test | api | config | doc
    relationship: str = "CALLS"
    confidence: str = "HIGH"
    label: str = "verified"  # verified | inferred | possible
    distance: int = 1
    line: int = 1
    evidence: str = ""


class ImpactResult(BaseModel):
    schema_version: str = "2.0"
    subject: str
    canonical_id: str | None = None
    direct_callers: list[dict[str, object]] = []
    transitive_callers: list[dict[str, object]] = []
    directly_affected: list[dict[str, object]] = []
    indirectly_affected: list[dict[str, object]] = []
    potential: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    dependent_modules: list[dict[str, object]] = []
    related_apis: list[dict[str, object]] = []
    related_tests: list[dict[str, object]] = []
    configuration: list[dict[str, object]] = []
    documentation: list[dict[str, object]] = []
    recent_modifications: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    label_legend: dict[str, str] = {}
    note: str = (
        "Static analysis cannot confirm runtime behavior. "
        "Do not assert failure solely from static dependency data."
    )

    def as_dict(self) -> dict[str, object]:
        return self.model_dump()


class ArchitectureNode(BaseModel):
    id: str
    name: str
    layer: str  # entry_point | route | controller | service | repository | model | config | test | external
    file: str
    line: int = 1
    confidence: str = "HIGH"


class ArchitectureEdge(BaseModel):
    source: str
    target: str
    relationship: str
    confidence: str = "HIGH"
    evidence: str = ""


class MCPError(BaseModel):
    schema_version: str = "1.0"
    error_code: ErrorCategory
    message: str
    details: dict[str, object] = {}

    def as_dict(self) -> dict[str, object]:
        return self.model_dump()


@dataclass
class ObservabilityMetrics:
    index_duration_ms: float = 0.0
    files_scanned: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    files_parse_failed: int = 0
    symbols_count: int = 0
    references_count: int = 0
    graph_edges_count: int = 0
    search_latency_ms: float = 0.0
    context_compile_latency_ms: float = 0.0
    database_size_bytes: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return round(self.cache_hits / total, 3) if total > 0 else 0.0

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["cache_hit_rate"] = self.cache_hit_rate
        return d


__all__ = [
    "ArchitectureEdge",
    "ArchitectureNode",
    "Call",
    "CallRef",
    "Chunk",
    "ContextCandidate",
    "EdgeType",
    "ErrorCategory",
    "File",
    "FreshnessState",
    "GraphEdge",
    "GraphNode",
    "ImpactItem",
    "ImpactResult",
    "Import",
    "ImportRef",
    "InheritanceRef",
    "MCPError",
    "NodeType",
    "ObservabilityMetrics",
    "Reference",
    "Repository",
    "RepositorySnapshot",
    "Symbol",
    "SymbolLocation",
    "TestRelationship",
    "build_canonical_id",
    "normalize_module",
]
