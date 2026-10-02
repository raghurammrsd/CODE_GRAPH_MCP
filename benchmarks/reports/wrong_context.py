"""Qualitative Wrong-Context Analysis and Debug Diagnostic Reporter."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WrongContextItem:
    task_id: str
    expected_entity: str
    returned_entity: str
    error_type: str  # WRONG_FILE | WRONG_SYMBOL | WRONG_RELATIONSHIP | IRRELEVANT_FRAMEWORK | STALE_CONTEXT
    diagnostic_reason: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def analyze_wrong_context(
    task_id: str,
    context_packet: dict[str, Any],
    allowed_files: tuple[str, ...],
    excluded_files: tuple[str, ...],
    expected_symbols: tuple[str, ...],
    excluded_symbols: tuple[str, ...],
) -> list[WrongContextItem]:
    """Diagnose specific instances of wrong, irrelevant, or stale context returned."""
    findings: list[WrongContextItem] = []

    # 1. Check excluded or irrelevant files returned
    selected_files = context_packet.get("selected_files", [])
    for f in selected_files:
        if f in excluded_files:
            findings.append(
                WrongContextItem(
                    task_id=task_id,
                    expected_entity="Excluded File",
                    returned_entity=str(f),
                    error_type="WRONG_FILE",
                    diagnostic_reason=f"File {f} is explicitly marked as excluded or irrelevant for this task.",
                )
            )

    # 2. Check excluded symbols returned
    raw_symbols = context_packet.get("symbols", [])
    retrieved_symbols = {
        str(s.get("symbol", "")) for s in raw_symbols if isinstance(s, dict)
    }
    for excl in excluded_symbols:
        if excl in retrieved_symbols:
            findings.append(
                WrongContextItem(
                    task_id=task_id,
                    expected_entity="Excluded Symbol",
                    returned_entity=excl,
                    error_type="WRONG_SYMBOL",
                    diagnostic_reason=f"Symbol {excl} was returned despite being irrelevant or excluded.",
                )
            )

    # 3. Check for stale evidence in fresh repository queries
    evidence = context_packet.get("evidence", [])
    for ev in evidence:
        if isinstance(ev, dict) and ev.get("evidence_status") == "stale":
            findings.append(
                WrongContextItem(
                    task_id=task_id,
                    expected_entity="Current Evidence",
                    returned_entity=str(ev.get("file", "")),
                    error_type="STALE_CONTEXT",
                    diagnostic_reason="Returned evidence is stale relative to disk source hash.",
                )
            )

    return findings
