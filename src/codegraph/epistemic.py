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
