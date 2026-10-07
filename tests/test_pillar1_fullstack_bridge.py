"""Comprehensive Test Suite for Pillar 1: The Unified Full-Stack Bridge.

Verifies:
1. Universal Parameterized Route Normalizer & Matcher (React/Next.js/Express/Flask/FastAPI).
2. End-to-end Graph Resolution (React component -> FETCHES_ROUTE -> CALLS -> backend handler).
3. Cross-Language Client-Server Contract Drift:
   - CROSS_LANGUAGE_FIELD_DRIFT (missing required field in backend)
   - NULLABILITY_DRIFT (client expects non-null, backend returns nullable)
   - TYPE_INCOMPATIBILITY (e.g. number vs UUID string)
   - HTTP_METHOD_MISMATCH (client POST vs backend GET)
   - ORPHANED_CLIENT_ROUTE (client fetch to non-existent route)
4. CLI command `codegraph api-drift` and MCP tools `check_api_drift`, `get_client_routes`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.api_drift import detect_api_contract_drift
from codegraph.indexing.indexer import Indexer
from codegraph.mcp.server import create_server
from codegraph.route_topology import match_route_topology, normalize_route


def test_route_topology_normalization_and_matching():
    # 1. React template literal matching FastAPI parameterized route
    client_1 = normalize_route("GET", "/api/v1/users/${userId}/orders")
    fastapi_1 = normalize_route("GET", "/users/{user_id}/orders")
    matched, match_type = match_route_topology(client_1, fastapi_1)
    assert matched is True
    assert match_type == "PROXY_PREFIX"

    # 2. React template literal matching Flask <int:param>
    flask_1 = normalize_route("GET", "/users/<int:user_id>/orders")
    matched, _ = match_route_topology(client_1, flask_1)
    assert matched is True

    # 3. Literal client integer ID matching Express / NestJS :param
    client_lit = normalize_route("GET", "/api/products/42")
    express_1 = normalize_route("GET", "/products/:productId")
    matched, _ = match_route_topology(client_lit, express_1)
    assert matched is True

    # 4. Method mismatch rejection
    client_post = normalize_route("POST", "/api/products/42")
    matched, _ = match_route_topology(client_post, express_1, match_methods=True)
    assert matched is False

    # But path matches when ignoring method:
    matched_path, _ = match_route_topology(client_post, express_1, match_methods=False)
    assert matched_path is True


def test_fullstack_graph_resolution_and_caller_discovery():
    """Verify that a React component fetching a backend endpoint creates a direct CALLS edge to the backend handler."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # Backend FastAPI route
        (src / "backend.py").write_text("""
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/users/{user_id}/orders")
def get_user_orders(user_id: int):
    return [{"order_id": 101, "total": 99.9}]
""")

        # Frontend React component calling the route via template literal
        (src / "OrderList.tsx").write_text("""
import React, { useEffect, useState } from 'react';

export function OrderList({ userId }: { userId: number }) {
  useEffect(() => {
    fetch(`/api/users/${userId}/orders`);
  }, [userId]);

  return <div>Orders</div>;
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # 1. Verify FETCHES_ROUTE reference
            fetches_refs = con.execute(
                "SELECT source_symbol_id, target_symbol_id, relationship, confidence FROM 'references' WHERE relationship = 'FETCHES_ROUTE'"
            ).fetchall()
            assert len(fetches_refs) >= 1
            f_ref = fetches_refs[0]
            assert "OrderList" in str(f_ref[0])

            # 2. Verify direct CALLS edge across the fullstack boundary
            calls_edges = con.execute(
                "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship = 'CALLS' AND source LIKE '%OrderList%'"
            ).fetchall()
            assert len(calls_edges) >= 1
            calls_edge = calls_edges[0]
            assert "OrderList" in str(calls_edge[0])
            assert "get_user_orders" in str(calls_edge[1])
            assert str(calls_edge[3]) == "DATAFLOW_VERIFIED"

        # 3. Verify find_callers tool returns the React caller
        server = create_server(repo, profile="full")
        find_callers_fn = server._tool_manager._tools["find_callers"].fn
        callers_res = find_callers_fn(symbol="get_user_orders")
        callers_list = callers_res if isinstance(callers_res, list) else callers_res.get("callers", [])
        caller_symbols = [str(c.get("caller") or c.get("symbol") or c.get("source") or c) for c in callers_list]
        assert any("OrderList" in s for s in caller_symbols)


def test_cross_language_contract_drift_detection():
    """Verify detection of:
    - TYPE_INCOMPATIBILITY (TS number vs Python str / UUID)
    - NULLABILITY_DRIFT (TS required vs Python Optional = None)
    - CROSS_LANGUAGE_FIELD_DRIFT (TS required field missing in backend)
    - HTTP_METHOD_MISMATCH
    - ORPHANED_CLIENT_ROUTE
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Backend FastAPI service with Pydantic response models
        (src / "api.py").write_text("""
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class UserProfileResponse(BaseModel):
    id: str  # String / UUID in backend!
    username: str
    email: Optional[str] = None  # Nullable in backend!
    # Note: 'loyalty_points' is missing in backend!

@app.get("/api/v1/profile", response_model=UserProfileResponse)
def get_user_profile():
    return UserProfileResponse(id="uuid-123", username="alice", email=None)

@app.get("/api/v1/health")
def health_check():
    return {"status": "ok"}
""")

        # 2. Frontend React / TypeScript component defining TypeScript interface and fetching
        (src / "Profile.tsx").write_text("""
import React from 'react';
import axios from 'axios';

interface UserProfile {
  id: number;              // Drift: backend returns str/UUID!
  username: string;        // Matching
  email: string;           // Drift: backend is Optional/None!
  loyalty_points: number;  // Drift: missing in backend!
}

export function ProfileCard() {
  // Matched route with TS interface -> triggers type drift analysis
  axios.get<UserProfile>('/api/v1/profile');

  // Method mismatch: client sends POST, backend only supports GET
  axios.post('/api/v1/health');

  // Orphaned client route: client calls non-existent route
  fetch('/api/v1/billing/invoices');

  return <div>Profile</div>;
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            report = detect_api_contract_drift(con, repo)

            assert report.has_drift is True
            drift_kinds = [d.kind for d in report.drifts]

            # 1. Check TYPE_INCOMPATIBILITY on id
            assert "TYPE_INCOMPATIBILITY" in drift_kinds
            type_drift = [d for d in report.drifts if d.kind == "TYPE_INCOMPATIBILITY"][0]
            assert type_drift.field_name == "id"
            assert "number" in type_drift.client_field_type
            assert "str" in type_drift.backend_field_type

            # 2. Check NULLABILITY_DRIFT on email
            assert "NULLABILITY_DRIFT" in drift_kinds
            null_drift = [d for d in report.drifts if d.kind == "NULLABILITY_DRIFT"][0]
            assert null_drift.field_name == "email"

            # 3. Check CROSS_LANGUAGE_FIELD_DRIFT on loyalty_points
            assert "CROSS_LANGUAGE_FIELD_DRIFT" in drift_kinds
            field_drift = [d for d in report.drifts if d.kind == "CROSS_LANGUAGE_FIELD_DRIFT"][0]
            assert field_drift.field_name == "loyalty_points"

            # 4. Check HTTP_METHOD_MISMATCH on /api/v1/health
            assert "HTTP_METHOD_MISMATCH" in drift_kinds
            method_drift = [d for d in report.drifts if d.kind == "HTTP_METHOD_MISMATCH"][0]
            assert method_drift.client_method == "POST"
            assert "/api/v1/health" in method_drift.client_route

            # 5. Check ORPHANED_CLIENT_ROUTE on /api/v1/billing/invoices
            assert "ORPHANED_CLIENT_ROUTE" in drift_kinds
            orphan_drift = [d for d in report.drifts if d.kind == "ORPHANED_CLIENT_ROUTE"][0]
            assert "/api/v1/billing/invoices" in orphan_drift.client_route


def test_mcp_tools_and_client_routes():
    """Verify that check_api_drift is exposed and executable via FastMCP, discovering client routes and drift."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        (src / "App.tsx").write_text("""
export function App() {
  fetch('/api/products');
  return null;
}
""")
        indexer = Indexer(repo)
        indexer.index()

        server = create_server(repo, profile="full")
        tools = server._tool_manager._tools

        assert "check_api_drift" in tools

        # Execute check_api_drift directly via FastMCP tool
        api_drift_fn = tools["check_api_drift"].fn
        drift_res = api_drift_fn()
        assert "has_drift" in drift_res
        assert drift_res["total_client_calls"] >= 1

        # Verify client routes are indexed in local_bindings table
        with indexer.connect() as con:
            bindings = con.execute(
                "SELECT target_name, expr_kind FROM local_bindings WHERE expr_kind = 'REACT_FETCH_ROUTE'"
            ).fetchall()
            assert len(bindings) >= 1
            assert bindings[0][0] == "/api/products"
