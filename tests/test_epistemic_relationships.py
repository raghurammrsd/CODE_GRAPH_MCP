"""Regression tests for Phase 1: RelationshipEvidenceClass, GraphEdge epistemic foundation,
and non-negotiable relationship invariants.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codegraph.epistemic import (
    RelationshipEvidenceClass,
    classify_relationship_evidence,
    validate_relationship_invariants,
)
from codegraph.graph.models import GraphEdge
from codegraph.indexing import Indexer
from codegraph.indexing.indexer import check_database_health
from codegraph.interrogation import get_symbol


def test_relationship_evidence_class_enum() -> None:
    """Verify all required evidence classes are defined with deterministic string values."""
    assert RelationshipEvidenceClass.AST_VERIFIED.value == "AST_VERIFIED"
    assert RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value == "FRAMEWORK_VERIFIED"
    assert RelationshipEvidenceClass.DATAFLOW_VERIFIED.value == "DATAFLOW_VERIFIED"
    assert RelationshipEvidenceClass.POSSIBLE.value == "POSSIBLE"
    assert RelationshipEvidenceClass.UNKNOWN.value == "UNKNOWN"


def test_graph_edge_defaults_and_serialization() -> None:
    """Verify GraphEdge defaults to AST_VERIFIED and serializes cleanly."""
    edge = GraphEdge(
        source="src/auth.py::login",
        target="src/crypto.py::verify_password",
        relationship="CALLS",
        confidence="HIGH",
        file="src/auth.py",
        start_line=10,
        end_line=12,
        evidence="Direct call site verify_password()",
    )
    assert edge.evidence_class == "AST_VERIFIED"
    assert edge.reason is None

    d = edge.as_dict()
    assert d["source"] == "src/auth.py::login"
    assert d["target"] == "src/crypto.py::verify_password"
    assert d["relationship"] == "CALLS"
    assert d["confidence"] == "HIGH"
    assert d["evidence_class"] == "AST_VERIFIED"
    assert d["reason"] is None


def test_invariant_possible_never_becomes_ast_verified() -> None:
    """POSSIBLE relationships must NEVER be marked as AST_VERIFIED."""
    with pytest.raises(ValueError, match="cannot be marked as AST_VERIFIED"):
        validate_relationship_invariants("POSSIBLE_CALLS", RelationshipEvidenceClass.AST_VERIFIED)

    with pytest.raises(ValueError, match="cannot be marked as AST_VERIFIED"):
        GraphEdge(
            source="caller",
            target="target",
            relationship="POSSIBLE_DISPATCH",
            confidence="LOW",
            file="service.py",
            start_line=5,
            end_line=5,
            evidence="dynamic call",
            evidence_class=RelationshipEvidenceClass.AST_VERIFIED.value,
        )


def test_invariant_unknown_never_becomes_calls() -> None:
    """UNKNOWN relationships must NEVER be exposed as authoritative CALLS."""
    with pytest.raises(ValueError, match="UNKNOWN relationships cannot be exposed as authoritative 'CALLS'"):
        validate_relationship_invariants("CALLS", RelationshipEvidenceClass.UNKNOWN)

    with pytest.raises(ValueError, match="UNKNOWN relationships cannot be exposed as authoritative 'CALLS'"):
        GraphEdge(
            source="caller",
            target="target",
            relationship="CALLS",
            confidence="UNKNOWN",
            file="service.py",
            start_line=5,
            end_line=5,
            evidence="unresolved dynamic target",
            evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
        )


def test_invariant_possible_never_becomes_calls() -> None:
    """POSSIBLE relationships must NEVER be labeled as authoritative CALLS."""
    with pytest.raises(ValueError, match="POSSIBLE relationships cannot be labeled as 'CALLS'"):
        validate_relationship_invariants("CALLS", RelationshipEvidenceClass.POSSIBLE)

    with pytest.raises(ValueError, match="POSSIBLE relationships cannot be labeled as 'CALLS'"):
        GraphEdge(
            source="caller",
            target="target",
            relationship="CALLS",
            confidence="LOW",
            file="service.py",
            start_line=5,
            end_line=5,
            evidence="potential candidate",
            evidence_class=RelationshipEvidenceClass.POSSIBLE.value,
        )


def test_classify_relationship_evidence_helper() -> None:
    """Test deterministic mapping of relationships and confidence levels."""
    ev_calls, _ = classify_relationship_evidence("CALLS", "HIGH")
    assert ev_calls == RelationshipEvidenceClass.AST_VERIFIED

    ev_fw, _ = classify_relationship_evidence("ROUTES_TO", "HIGH")
    assert ev_fw == RelationshipEvidenceClass.FRAMEWORK_VERIFIED

    ev_df, _ = classify_relationship_evidence("RESOLVES_TO", "HIGH")
    assert ev_df == RelationshipEvidenceClass.DATAFLOW_VERIFIED

    ev_pos, r_pos = classify_relationship_evidence("POSSIBLE_CALLS", "LOW")
    assert ev_pos == RelationshipEvidenceClass.POSSIBLE
    assert r_pos == "unresolved_dynamic_candidate"

    ev_unk, r_unk = classify_relationship_evidence("UNRESOLVED_REFERENCE", "UNKNOWN")
    assert ev_unk == RelationshipEvidenceClass.UNKNOWN
    assert r_unk == "static_resolution_unavailable"


def test_existing_verified_calls_remain_ast_verified_in_indexed_repo(tmp_path: Path) -> None:
    """Verify that end-to-end repository indexing marks real CALLS edges as AST_VERIFIED."""
    app_code = tmp_path / "app.py"
    app_code.write_text("""
def helper_compute(x: int) -> int:
    return x * 2

def main_process():
    val = helper_compute(10)
    return val
""")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        rows = con.execute(
            "SELECT source, target, relationship, confidence, evidence_class, reason "
            "FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        assert len(rows) >= 1
        for r in rows:
            assert r["relationship"] == "CALLS"
            assert r["confidence"] in ("HIGH", "MEDIUM")
            assert r["evidence_class"] == "AST_VERIFIED"
            assert r["reason"] is None


def test_framework_routes_remain_framework_verified_in_indexed_repo(tmp_path: Path) -> None:
    """Verify that framework route edges are marked as FRAMEWORK_VERIFIED."""
    app_code = tmp_path / "routes.py"
    app_code.write_text("""
from fastapi import FastAPI

app = FastAPI()

@app.get("/items")
def list_items():
    return [{"id": 1}]
""")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        rows = con.execute(
            "SELECT source, target, relationship, evidence_class "
            "FROM graph_edges WHERE relationship='ROUTES_TO'"
        ).fetchall()
        assert len(rows) >= 1
        for r in rows:
            assert r["relationship"] == "ROUTES_TO"
            assert r["evidence_class"] == "FRAMEWORK_VERIFIED"


def test_schema_migration_v6_to_v7_preserves_data(tmp_path: Path) -> None:
    """Verify non-destructive migration of existing database from schema v6 to v7."""
    db_file = tmp_path / ".codegraph.sqlite3"

    # Initialize a v6-like database table manually
    con = sqlite3.connect(str(db_file))
    con.execute("PRAGMA user_version = 6")
    con.execute("""
    CREATE TABLE files (
        path TEXT PRIMARY KEY,
        hash TEXT NOT NULL,
        language TEXT NOT NULL,
        indexed_at INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ok',
        category TEXT NOT NULL DEFAULT 'SOURCE'
    )
    """)
    con.execute("""
    CREATE TABLE graph_edges (
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        relationship TEXT NOT NULL,
        confidence TEXT NOT NULL,
        file TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        evidence TEXT NOT NULL DEFAULT '',
        evidence_id TEXT NOT NULL DEFAULT '',
        source_hash TEXT NOT NULL DEFAULT '',
        indexed_commit TEXT
    )
    """)
    con.execute("INSERT INTO files(path, hash, language) VALUES ('test.py', 'hash123', 'python')")
    con.execute(
        "INSERT INTO graph_edges(source, target, relationship, confidence, file, start_line, end_line) "
        "VALUES ('symA', 'symB', 'CALLS', 'HIGH', 'test.py', 1, 5)"
    )
    con.commit()
    con.close()

    # Now open with Indexer which triggers _migrate_schema
    indexer = Indexer(tmp_path)
    with indexer.session() as con:
        ver = con.execute("PRAGMA user_version").fetchone()[0]
        assert ver >= 7

        # Verify columns exist
        cols = {r[1] for r in con.execute("PRAGMA table_info(graph_edges)").fetchall()}
        assert "evidence_class" in cols
        assert "reason" in cols

        # Verify existing row migrated with default AST_VERIFIED
        row = con.execute("SELECT source, target, relationship, evidence_class, reason FROM graph_edges").fetchone()
        assert row["source"] == "symA"
        assert row["target"] == "symB"
        assert row["relationship"] == "CALLS"
        assert row["evidence_class"] == "AST_VERIFIED"
        assert row["reason"] is None

        # Verify database health check passes
        health = check_database_health(con)
        assert health["status"] == "OK"
        assert health["database_version"] >= 7


def test_mcp_response_backward_compatibility(tmp_path: Path) -> None:
    """Verify that get_symbol returns all legacy fields plus additive epistemic fields."""
    src = tmp_path / "calc.py"
    src.write_text("""
def add(a: int, b: int) -> int:
    return a + b

def compute():
    return add(1, 2)
""")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        row = con.execute("SELECT canonical_id FROM symbols WHERE name='compute'").fetchone()
        assert row is not None
        res = get_symbol(con, tmp_path, row["canonical_id"])
        assert res["status"] == "ok"
        rels = res.get("symbol", {}).get("relationships", [])
        assert len(rels) >= 1
        rel = rels[0]

        # Legacy required fields must be present and identical
        assert "target" in rel
        assert "relationship" in rel
        assert "confidence" in rel
        assert "file" in rel
        assert "start_line" in rel
        assert "end_line" in rel

        # Additive Phase 1 fields must also be present
        assert "evidence_class" in rel
        assert rel["evidence_class"] == "AST_VERIFIED"
        assert "reason" in rel
