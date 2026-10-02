"""Stale Evidence and Freshness Lifecycle Benchmark Scenario."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.freshness import check_freshness
from codegraph.indexing import Indexer


def run_stale_evidence_benchmark(repository: Path) -> dict[str, Any]:
    """Test full stale lifecycle: index -> direct file edit -> query (STALE) -> re-index -> query (FRESH)."""
    indexer = Indexer(repository)
    indexer.index()

    target_file = repository / "src" / "services" / "auth_service.py"
    if not target_file.exists():
        target_file = next(repository.glob("src/**/*.py"))

    original_text = target_file.read_text(encoding="utf-8")

    try:
        # Step 1: Initial query on fresh index
        with indexer.session() as con:
            fresh_report_1 = check_freshness(repository, con)
            pkt_fresh_1 = get_context(
                con=con,
                repository=repository,
                task="Explain AuthService.login",
                max_tokens=4000,
            )
            assert pkt_fresh_1.freshness == "FRESH"

        # Step 2: Modify source file directly on disk without re-indexing
        target_file.write_text(original_text + "\n# mutated on disk\n", encoding="utf-8")

        # Step 3: Query existing index and verify detection of modified file
        with indexer.session() as con:
            stale_report = check_freshness(repository, con)
            assert str(target_file.relative_to(repository)) in stale_report.modified_files
            stale_detected = stale_report.status.value in ("STALE", "PARTIALLY_STALE")

            get_context(
                con=con,
                repository=repository,
                task="Explain AuthService.login",
                max_tokens=4000,
            )

        # Step 4: Re-index
        indexer.index()

        # Step 5: Verify index is fresh again
        with indexer.session() as con:
            fresh_report_2 = check_freshness(repository, con)
            pkt_fresh_2 = get_context(
                con=con,
                repository=repository,
                task="Explain AuthService.login",
                max_tokens=4000,
            )
            assert pkt_fresh_2.freshness == "FRESH"

        return {
            "initial_freshness": fresh_report_1.status.value,
            "stale_detected": stale_detected,
            "stale_status": stale_report.status.value,
            "modified_files": stale_report.modified_files,
            "recovered_freshness": fresh_report_2.status.value,
            "lifecycle_passed": stale_detected and fresh_report_2.status.value == "FRESH",
        }
    finally:
        # Cleanup
        target_file.write_text(original_text, encoding="utf-8")
        indexer.index()
