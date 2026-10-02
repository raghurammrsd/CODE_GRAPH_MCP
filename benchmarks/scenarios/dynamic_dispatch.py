"""Unknown and Dynamic Dispatch Benchmark Scenario."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer


def run_dynamic_dispatch_benchmark(repository: Path) -> dict[str, Any]:
    """Verify that dynamic reflections without static AST evidence are not falsely resolved."""
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    with indexer.session() as con:
        packet = get_context(
            con=con,
            repository=repository,
            task="Explain DynamicService execute_action and reflective dispatch",
            intent="EXPLAIN",
            max_tokens=5000,
        )

        relationships = packet.relationships
        # Ensure no hallucinated static CALLS edge was fabricated for getattr
        false_resolved_calls = [
            r for r in relationships
            if r.source == "execute_action" and r.relationship == "CALLS" and r.target == "fn"
        ]

        unknown_correctness = len(false_resolved_calls) == 0

        return {
            "false_resolved_relationships_count": len(false_resolved_calls),
            "unsupported_claim_rate": 0.0 if unknown_correctness else 1.0,
            "unknown_correctness": unknown_correctness,
            "symbols_found": [s.symbol for s in packet.symbols],
        }
