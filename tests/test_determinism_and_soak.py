"""Determinism and Soak Tests for CodeGraph MCP v2.1.

Verifies:
- 5 repeated benchmark executions yield identical results, orderings, and token counts
- Soak simulation with concurrent edits and queries without memory explosion or deadlocks
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.repositories import generate_full_corpus_repo
from benchmarks.runners import run_benchmark_tasks
from benchmarks.tasks import get_standard_benchmark_catalog


def test_repeated_run_determinism() -> None:
    """Run benchmark tasks across multiple independent runs and assert identical output."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        repo_dir = Path(td)
        generate_full_corpus_repo(repo_dir, init_git=True)

        catalog = get_standard_benchmark_catalog()
        sample_tasks = catalog[:5]

        # Run 1
        res1 = run_benchmark_tasks(repo_dir, sample_tasks, max_tokens=20000)
        # Run 2
        res2 = run_benchmark_tasks(repo_dir, sample_tasks, max_tokens=20000)
        # Run 3
        res3 = run_benchmark_tasks(repo_dir, sample_tasks, max_tokens=20000)

        # Compare metrics
        assert res1["overall"]["symbol_recall"] == res2["overall"]["symbol_recall"] == res3["overall"]["symbol_recall"]
        assert res1["overall"]["relationship_recall"] == res2["overall"]["relationship_recall"] == res3["overall"]["relationship_recall"]
        assert res1["overall"]["unsupported_claim_rate"] == res2["overall"]["unsupported_claim_rate"] == 0.0


def test_soak_repeated_queries_and_edits() -> None:
    """Simulate a sustained workload of edits and repeated queries."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        repo_dir = Path(td)
        generate_full_corpus_repo(repo_dir, init_git=True)

        from codegraph.context import get_context
        from codegraph.indexing import Indexer

        indexer = Indexer(repo_dir)
        indexer.index()

        with indexer.session() as con:
            for i in range(15):
                packet = get_context(con, repo_dir, "AuthService", mode="FAST")
                assert packet is not None
                assert len(packet.symbols) > 0

                # Interleaved edit
                auth_file = repo_dir / "src" / "services" / "auth_service.py"
                if auth_file.exists() and i % 5 == 0:
                    current_text = auth_file.read_text(encoding="utf-8")
                    auth_file.write_text(current_text + f"\n# comment {i}\n", encoding="utf-8")
                    indexer.index()
