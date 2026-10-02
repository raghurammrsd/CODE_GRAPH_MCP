"""Tests for global token budget optimizer and redundancy control."""

from codegraph.optimizer import (
    CandidateContextItem,
    ContextBudget,
    compute_item_utility,
    optimize_context_budget,
)


def _make_item(
    item_id: str,
    tokens: int,
    relevance: float,
    layer: str = "SERVICE",
    canonical_id: str | None = None,
    freshness: str = "FRESH",
    confidence: str = "HIGH",
    evidence_quality: float = 0.9,
) -> CandidateContextItem:
    return CandidateContextItem(
        item_id=item_id,
        file_path=f"src/{item_id}.py",
        start_line=1,
        end_line=20,
        canonical_id=canonical_id or f"src/{item_id}.py::{item_id}",
        estimated_tokens=tokens,
        relevance_score=relevance,
        evidence_quality=evidence_quality,
        freshness=freshness,
        coverage_layer=layer,
        source_type="symbol",
        snippet=f"# Snippet for {item_id}",
        confidence=confidence,
    )


def test_compute_item_utility_freshness_and_confidence() -> None:
    fresh_item = _make_item("fresh", tokens=100, relevance=0.8, freshness="FRESH", confidence="HIGH")
    stale_item = _make_item("stale", tokens=100, relevance=0.8, freshness="STALE", confidence="LOW")

    u_fresh = compute_item_utility(fresh_item, selected_layers=set(), selected_duplicate_keys=set())
    u_stale = compute_item_utility(stale_item, selected_layers=set(), selected_duplicate_keys=set())
    assert u_fresh > u_stale


def test_compute_item_utility_coverage_and_redundancy() -> None:
    item = _make_item("item1", tokens=100, relevance=0.8, layer="ENTRYPOINT")

    # Layer not yet selected -> gets coverage reward boost
    u_unselected = compute_item_utility(item, selected_layers=set(), selected_duplicate_keys=set())
    # Layer already selected
    u_selected = compute_item_utility(item, selected_layers={"ENTRYPOINT"}, selected_duplicate_keys=set())
    assert u_unselected > u_selected

    # Duplicate key penalty
    u_dup = compute_item_utility(item, selected_layers={"ENTRYPOINT"}, selected_duplicate_keys={item.duplicate_key})
    assert u_selected > u_dup


def test_optimize_budget_respects_token_limit() -> None:
    candidates = [
        _make_item(f"item_{i}", tokens=250, relevance=0.9 - (i * 0.05))
        for i in range(10)
    ]
    budget_limit = 600
    selected, budget = optimize_context_budget(candidates, token_budget=budget_limit)

    assert isinstance(budget, ContextBudget)
    assert budget.selected_tokens <= budget_limit
    assert sum(item.estimated_tokens for item in selected) == budget.selected_tokens
    assert budget.reduction_ratio > 0.0
    assert budget.candidate_tokens == 2500


def test_optimize_budget_layer_coverage_pass() -> None:
    # 4 items from 4 different layers
    ep = _make_item("route", tokens=100, relevance=0.7, layer="ENTRYPOINT")
    svc = _make_item("service", tokens=100, relevance=0.9, layer="SERVICE")
    tst = _make_item("test", tokens=100, relevance=0.6, layer="TEST")
    git = _make_item("diff", tokens=100, relevance=0.5, layer="GIT")

    # Budget fits 3 items
    selected, budget = optimize_context_budget([ep, svc, tst, git], token_budget=300)
    selected_layers = {item.coverage_layer for item in selected}
    # Pass 1 should ensure distinct layers are prioritized
    assert len(selected_layers) == 3
    assert budget.selected_tokens <= 300


def test_optimize_budget_empty_and_zero_tokens() -> None:
    selected_empty, budget_empty = optimize_context_budget([], token_budget=1000)
    assert selected_empty == []
    assert budget_empty.selected_tokens == 0

    candidates = [_make_item("item", tokens=100, relevance=0.9)]
    selected_zero, budget_zero = optimize_context_budget(candidates, token_budget=0)
    assert selected_zero == []
    assert budget_zero.selected_tokens == 0
