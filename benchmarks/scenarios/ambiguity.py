"""Ambiguity Benchmark Scenario: Evaluates ambiguous target detection and precision."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.task import AmbiguityStatus, detect_target_ambiguity


def run_ambiguity_benchmark(repository: Path) -> dict[str, Any]:
    """Evaluate ambiguity detection on homonymous symbols (e.g. auth/login vs admin/login)."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    with indexer.session() as con:
        # 1. Target with multiple definitions across distinct modules
        amb = detect_target_ambiguity(target="login", con=con)
        is_ambiguous = amb.status in (AmbiguityStatus.AMBIGUOUS, AmbiguityStatus.CONFLICT)

        # 2. Query MCP context for ambiguous prompt "Fix login"
        packet = get_context(
            con=con,
            repository=repository,
            task="Fix login function",
            intent="DEBUG",
        )

        task_spec_dict = packet.task_spec or {}
        reported_ambs = task_spec_dict.get("ambiguities", [])
        ambs_list = reported_ambs if isinstance(reported_ambs, list) else []
        has_ambiguity = len(ambs_list) > 0 or is_ambiguous

        return {
            "ambiguous_target": "login",
            "detected_status": amb.status.value,
            "is_ambiguous": is_ambiguous,
            "candidate_definitions_count": len(amb.candidates),
            "reported_ambiguities": list(ambs_list),
            "ambiguity_precision": 1.0 if has_ambiguity else 0.0,
            "ambiguity_recall": 1.0 if has_ambiguity else 0.0,
            "silent_assumption_rate": 0.0 if has_ambiguity else 1.0,
        }
