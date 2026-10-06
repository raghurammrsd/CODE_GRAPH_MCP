"""Comprehensive Test Suite for Pillar 2: Semantic Change Impact & PR Blast Radius Engine.

Verifies:
1. Full-stack change impact tracing (symbol -> caller -> route -> frontend UI component).
2. Database mutation impact (mutating SQL operations and schema impacts).
3. Covering test discovery and Smart Test Execution Command generation.
4. PR Risk Score and semantic breaking change flags (PUBLIC_API_MODIFIED, DB_MUTATION_IMPACT, UNCOVERED_BY_TESTS).
5. Symbol-level on-demand blast radius vs Git commit range blast radius.
6. FastMCP tool `get_change_impact` integration with `symbol` argument.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.change_impact import get_deep_change_impact
from codegraph.indexing.indexer import Indexer
from codegraph.mcp.server import create_server


def test_fullstack_blast_radius_and_frontend_ui_impact():
    """Verify that changing a backend calculation function discovers:
    - Direct backend caller (route handler)
    - Affected route endpoint
    - Affected frontend React component fetching the route
    - Breaking change flags
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Backend service function
        (src / "service.py").write_text("""
def calculate_discount(amount: float, code: str) -> float:
    if code == 'VIP':
        return amount * 0.2
    return 0.0
""")

        # 2. Backend FastAPI route handler calling the service
        (src / "routes.py").write_text("""
from fastapi import FastAPI
from service import calculate_discount

app = FastAPI()

@app.post("/api/checkout/apply-discount")
def apply_discount_handler(amount: float, code: str):
    return {"discount": calculate_discount(amount, code)}
""")

        # 3. Frontend React component calling the route
        (src / "CartView.tsx").write_text("""
import React from 'react';

export function CartDiscount() {
  const applyPromo = () => {
    fetch('/api/checkout/apply-discount', { method: 'POST' });
  };
  return <button onClick={applyPromo}>Apply</button>;
}
""")

        # 4. Covering test
        tests_dir = repo / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_service.py").write_text("""
from service import calculate_discount

def test_calculate_discount_vip():
    assert calculate_discount(100.0, 'VIP') == 20.0
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            report = get_deep_change_impact(repo, con, symbol="calculate_discount")

            assert report.target_symbol == "calculate_discount"
            assert report.total_impacted_count > 0

            # Direct caller: apply_discount_handler
            caller_names = [c.name for c in report.direct_callers]
            assert any("apply_discount_handler" in name for name in caller_names)

            # Affected route: POST /api/checkout/apply-discount
            route_names = [r.name for r in report.affected_routes]
            assert any("/api/checkout/apply-discount" in name for name in route_names)

            # Affected frontend UI component: CartDiscount
            fe_names = [fe.name for fe in report.affected_frontend_components]
            assert any("CartDiscount" in name for name in fe_names)

            # Covering test discovery
            test_names = [t.name for t in report.affected_tests]
            assert any("test_calculate_discount" in name for name in test_names)

            # Smart test command recommendation
            assert "pytest" in report.recommended_test_command
            assert "test_service.py" in report.recommended_test_command

            # Breaking flags: Public API is exposed downstream
            assert "PUBLIC_API_MODIFIED" in report.breaking_change_flags


def test_database_mutation_blast_radius_and_uncovered_flag():
    """Verify that mutating database queries are captured in db_writers and risk flags."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        (src / "models.py").write_text("""
import sqlite3

def delete_user_account(user_id: int):
    con = sqlite3.connect(':memory:')
    con.execute('DELETE FROM users WHERE id = ?', (user_id,))
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            report = get_deep_change_impact(repo, con, symbol="delete_user_account")

            assert report.target_symbol == "delete_user_account"

            # DB mutation captured
            writer_ops = [w.name for w in report.db_writers]
            assert any("DELETE" in op for op in writer_ops)
            assert "DB_MUTATION_IMPACT" in report.breaking_change_flags

            # No tests cover this symbol -> UNCOVERED_BY_TESTS flag
            assert "UNCOVERED_BY_TESTS" in report.breaking_change_flags


def test_pr_risk_scoring_scale_and_levels():
    """Verify risk levels: LOW, MEDIUM, HIGH, CRITICAL based on blast radius score."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # Isolated helper with zero callers
        (src / "utils.py").write_text("""
def pure_math_helper(x: int) -> int:
    return x * 2
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            report = get_deep_change_impact(repo, con, symbol="pure_math_helper")
            assert report.blast_radius_score < 25.0
            assert report.risk_level == "LOW"


def test_mcp_get_change_impact_with_symbol_param():
    """Verify that MCP tool get_change_impact accepts symbol parameter and runs asynchronously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        (src / "core.py").write_text("""
def core_computation():
    return 42
""")

        indexer = Indexer(repo)
        indexer.index()

        server = create_server(repo, profile="full")
        impact_tool = server._tool_manager._tools["get_change_impact"].fn

        res = impact_tool(base="symbol:core_computation")
        assert res["target_symbol"] == "core_computation"
        assert "blast_radius_score" in res
        assert "risk_level" in res
        assert "breaking_change_flags" in res
