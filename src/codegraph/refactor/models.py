"""Models and data structures for deterministic, syntax-validated, transaction-safe refactoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RefactorStatus(StrEnum):
    """Execution status of a refactoring plan or transaction."""

    READY = "READY"
    BLOCKED = "BLOCKED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    ERROR = "ERROR"


class RefactorRisk(StrEnum):
    """Assessed risk of an AST refactoring operation."""

    LOW = "LOW"        # All affected relationships are FACT / deterministically verified.
    MEDIUM = "MEDIUM"  # POSSIBLE relationships exist but scope is bounded.
    HIGH = "HIGH"      # UNKNOWN / AMBIGUOUS / CONFLICT relationships could make rename incomplete.


@dataclass(frozen=True)
class TokenReplacementSpan:
    """Exact byte/token coordinates for an AST-grounded replacement."""

    path: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    old_token: str
    new_token: str
    evidence: str
    symbol_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RefactorPlan:
    """Deterministic refactoring plan before in-memory preview or commit."""

    transaction_id: str
    target_symbol: str
    new_name: str
    files: list[str] = field(default_factory=list)
    spans: list[TokenReplacementSpan] = field(default_factory=list)
    risk: RefactorRisk = RefactorRisk.LOW
    uncertainty_reasons: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    affected_routes: list[str] = field(default_factory=list)
    affected_db_relationships: list[str] = field(default_factory=list)
    original_file_hashes: dict[str, str] = field(default_factory=dict)
    original_file_sizes: dict[str, int] = field(default_factory=dict)
    original_file_mtimes: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "target_symbol": self.target_symbol,
            "new_name": self.new_name,
            "files": sorted(self.files),
            "spans": [s.to_dict() for s in sorted(self.spans, key=lambda x: (x.path, x.start_line, x.start_col))],
            "risk": str(self.risk),
            "uncertainty_reasons": sorted(self.uncertainty_reasons),
            "affected_tests": sorted(self.affected_tests),
            "affected_routes": sorted(self.affected_routes),
            "affected_db_relationships": sorted(self.affected_db_relationships),
            "original_file_hashes": dict(sorted(self.original_file_hashes.items())),
        }


@dataclass
class RefactorResult:
    """Complete result of a refactor preview, apply, or rollback."""

    status: RefactorStatus
    target_symbol: str
    new_name: str
    risk: RefactorRisk
    uncertainty_reasons: list[str] = field(default_factory=list)
    files_changed: int = 0
    symbols_changed: int = 0
    spans_count: int = 0
    tests_affected: list[str] = field(default_factory=list)
    routes_affected: list[str] = field(default_factory=list)
    db_affected: list[str] = field(default_factory=list)
    rollback_id: str | None = None
    diffs: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "target_symbol": self.target_symbol,
            "new_name": self.new_name,
            "risk": str(self.risk),
            "uncertainty_reasons": sorted(self.uncertainty_reasons),
            "files_changed": self.files_changed,
            "symbols_changed": self.symbols_changed,
            "spans_count": self.spans_count,
            "tests_affected": sorted(self.tests_affected),
            "routes_affected": sorted(self.routes_affected),
            "db_affected": sorted(self.db_affected),
            "rollback_id": self.rollback_id,
            "diffs": dict(sorted(self.diffs.items())),
            "errors": sorted(self.errors),
        }
