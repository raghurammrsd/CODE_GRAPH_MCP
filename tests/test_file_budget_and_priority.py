"""Tests for increased file budget (25 files default, 40 hard cap) and task-critical candidate prioritization."""
from __future__ import annotations

from pathlib import Path

from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.optimizer import (
    HARD_MAX_FILES,
    CandidateContextItem,
    ContextBudgetSpec,
    optimize_context_budget,
)


def _make_candidate(
    item_id: str,
    file_path: str,
    tokens: int = 50,
    relevance: float = 0.80,
    dimension: str = "TARGET",
    layer: str = "SERVICE",
) -> CandidateContextItem:
    return CandidateContextItem(
        item_id=item_id,
        file_path=file_path,
        start_line=1,
        end_line=10,
        canonical_id=f"{file_path}::{item_id}",
        estimated_tokens=tokens,
        relevance_score=relevance,
        evidence_quality=0.90,
        freshness="FRESH",
        coverage_layer=layer,
        source_type="symbol",
        snippet="def fn(): pass\n",
        task_dimension=dimension,
        data={"symbol": item_id, "reasons": []},
    )


def test_default_file_budget_is_25() -> None:
    spec = ContextBudgetSpec()
    assert spec.max_files == 25
    assert HARD_MAX_FILES == 40


def test_task_critical_candidates_prioritized_over_tangential_files() -> None:
    """When candidate files exceed budget, task-critical files (TARGET, ROUTE, CALLER)
    must be admitted before tangential files (TEST, GIT, GENERAL).
    """
    candidates: list[CandidateContextItem] = []

    # 10 critical target & route files
    for i in range(10):
        candidates.append(
            _make_candidate(f"target_{i}", f"src/target_{i}.py", relevance=0.85, dimension="TARGET")
        )
    for i in range(5):
        candidates.append(
            _make_candidate(f"route_{i}", f"src/routes/api_{i}.py", relevance=0.80, dimension="ROUTE", layer="ENTRYPOINT")
        )

    # 15 tangential test and git files with moderate relevance
    for i in range(10):
        candidates.append(
            _make_candidate(f"test_{i}", f"tests/test_misc_{i}.py", relevance=0.45, dimension="TEST", layer="TEST")
        )
    for i in range(5):
        candidates.append(
            _make_candidate(f"git_change_{i}", f"docs/change_{i}.md", relevance=0.35, dimension="GIT", layer="GIT")
        )

    # File budget capped at 12
    spec = ContextBudgetSpec(max_tokens=10_000, max_files=12)
    selected, budget = optimize_context_budget(candidates, token_budget=10_000, budget_spec=spec)

    selected_files = {s.file_path for s in selected}
    assert len(selected_files) <= 12

    # All admitted files should be from the critical set (TARGET / ROUTE), none from tangential GIT docs
    target_and_route_count = sum(1 for s in selected if s.infer_dimension() in ("TARGET", "ROUTE"))
    assert target_and_route_count >= 11
    assert not any(s.file_path.startswith("docs/") for s in selected)


def test_end_to_end_context_with_more_than_15_files(tmp_path: Path) -> None:
    """End-to-end test verifying get_context can accommodate > 15 files under the new default budget."""
    repo = tmp_path / "multi_file_repo"
    src = repo / "src"
    src.mkdir(parents=True)

    # Create 20 service files
    for i in range(20):
        (src / f"service_{i:02d}.py").write_text(
            f"def do_work_{i:02d}():\n    return {i}\n",
            encoding="utf-8",
        )

    Indexer(repo).index()

    with Indexer(repo).session() as con:
        pkt = get_context(
            con,
            repo,
            query="do_work",
            intent="UNDERSTAND",
            max_tokens=10_000,
        )
        # Should include more than 15 files since default is now 25
        assert len(pkt.selected_files) > 15
        assert len(pkt.selected_files) <= 25
