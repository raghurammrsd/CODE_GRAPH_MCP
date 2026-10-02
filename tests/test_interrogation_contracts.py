"""Comprehensive MCP contract and deterministic interrogation tests.

Covers:
- All 13 core interrogation capabilities:
  1. resolve_symbol
  2. search_symbols
  3. get_symbol
  4. get_file
  5. get_references
  6. get_callers
  7. get_callees
  8. trace_path
  9. get_imports
  10. get_dependents
  11. list_routes
  12. get_architecture
  13. get_git_impact
- FastMCP interface execution
- Deterministic ordering
- Freshness and index metadata
- Evidence generation
- Ambiguity and error handling
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from codegraph.indexing import Indexer
from codegraph.interrogation import (
    get_architecture,
    get_callees,
    get_callers,
    get_dependents,
    get_file,
    get_git_impact,
    get_imports,
    get_references,
    get_symbol,
    list_routes,
    resolve_symbol,
    search_symbols,
    trace_path,
)
from codegraph.mcp import create_server


# ---------------------------------------------------------------------------
# Test Fixture: Multi-module repository with cross-calls and routes
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "auth").mkdir()
    (repo / "src" / "api").mkdir()
    (repo / "src" / "admin").mkdir()

    # 1. Auth service
    (repo / "src" / "auth" / "service.py").write_text(
        "class AuthService:\n"
        "    def create_session(self, user_id: str) -> str:\n"
        "        return 'session_' + user_id\n"
        "\n"
        "def verify_otp(otp_code: str) -> bool:\n"
        "    return otp_code == '123456'\n",
        encoding="utf-8",
    )

    # 2. Auth views (calls auth service)
    (repo / "src" / "auth" / "views.py").write_text(
        "from src.auth.service import AuthService, verify_otp\n"
        "\n"
        "def verify_otp_view(otp_code: str) -> dict:\n"
        "    if verify_otp(otp_code):\n"
        "        svc = AuthService()\n"
        "        token = svc.create_session('u1')\n"
        "        return {'token': token}\n"
        "    return {'error': 'invalid'}\n"
        "\n"
        "def duplicate_helper():\n"
        "    return 'auth'\n",
        encoding="utf-8",
    )

    # 3. Admin views (has a duplicate name 'duplicate_helper')
    (repo / "src" / "admin" / "views.py").write_text(
        "def duplicate_helper():\n"
        "    return 'admin'\n",
        encoding="utf-8",
    )

    # 4. API routes (FastAPI)
    (repo / "src" / "api" / "routes.py").write_text(
        "from fastapi import FastAPI\n"
        "from src.auth.views import verify_otp_view\n"
        "\n"
        "app = FastAPI()\n"
        "\n"
        "@app.post('/auth/verify')\n"
        "def login_endpoint(otp: str):\n"
        "    return verify_otp_view(otp)\n",
        encoding="utf-8",
    )

    # 5. Sensitive file
    (repo / ".env").write_text("DATABASE_PASSWORD=secret", encoding="utf-8")

    # Initialize Git repository for git impact testing
    try:
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)
    except Exception:
        pass

    Indexer(repo).index()
    return repo


# ---------------------------------------------------------------------------
# 1. resolve_symbol tests
# ---------------------------------------------------------------------------
def test_resolve_symbol_exact(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = resolve_symbol(con, sample_repo, "verify_otp_view")
        assert res["status"] == "ok"
        assert res["symbol"]["name"] == "verify_otp_view"
        assert "views.py" in res["location"]["file"]
        assert res["index"]["freshness"] == "FRESH"
        assert "generation" in res["index"]


def test_resolve_symbol_method(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = resolve_symbol(con, sample_repo, "create_session")
        assert res["status"] == "ok"
        assert res["symbol"]["name"] == "create_session"
        assert res["symbol"]["kind"] in ("method", "function")


def test_resolve_symbol_not_found(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = resolve_symbol(con, sample_repo, "non_existent_symbol_123")
        assert res["status"] == "not_found"
        assert res["query"] == "non_existent_symbol_123"
        assert res["matches"] == []


def test_resolve_symbol_ambiguous_no_guessing(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = resolve_symbol(con, sample_repo, "duplicate_helper")
        assert res["status"] == "ambiguous"
        assert len(res["matches"]) >= 2
        # CodeGraph MUST NOT choose the intended candidate
        files = {m["file"] for m in res["matches"]}
        assert "src/auth/views.py" in files
        assert "src/admin/views.py" in files


# ---------------------------------------------------------------------------
# 2. search_symbols tests
# ---------------------------------------------------------------------------
def test_search_symbols_ranking_and_determinism(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = search_symbols(con, sample_repo, "verify", top_k=10)
        assert res["status"] == "ok"
        assert res["count"] > 0
        symbols = [s["name"] for s in res["symbols"]]
        assert "verify_otp" in symbols
        assert "verify_otp_view" in symbols
        # Stable sort check
        cids = [s["canonical_id"] for s in res["symbols"]]
        assert len(cids) == len(set(cids))


# ---------------------------------------------------------------------------
# 3. get_symbol tests
# ---------------------------------------------------------------------------
def test_get_symbol_structure(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_symbol(con, sample_repo, "AuthService")
        assert res["status"] == "ok"
        sym = res["symbol"]
        assert sym["name"] == "AuthService"
        assert sym["kind"] == "class"
        assert "src/auth/service.py" in sym["file"]
        assert sym["start_line"] >= 1
        assert "relationships" in sym


# ---------------------------------------------------------------------------
# 4. get_file tests
# ---------------------------------------------------------------------------
def test_get_file_structure(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_file(con, sample_repo, "src/auth/views.py")
        assert res["status"] == "ok"
        assert res["file"] == "src/auth/views.py"
        assert "hash" in res
        assert len(res["imports"]) >= 1
        assert any(s["name"] == "verify_otp_view" for s in res["functions"])


def test_get_file_sensitive_blocked(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_file(con, sample_repo, ".env")
        assert res["status"] == "invalid_request"
        assert res["error_code"] == "SENSITIVE_FILE_ACCESS_DENIED"


# ---------------------------------------------------------------------------
# 5. get_references tests
# ---------------------------------------------------------------------------
def test_get_references(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_references(con, sample_repo, "verify_otp")
        assert res["status"] == "ok"
        assert res["count"] >= 1
        assert all("evidence" in r for r in res["references"])


# ---------------------------------------------------------------------------
# 6. get_callers tests
# ---------------------------------------------------------------------------
def test_get_callers(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        # verify_otp is called by verify_otp_view
        res = get_callers(con, sample_repo, "verify_otp")
        assert res["status"] == "ok"
        caller_names = [c["caller"] for c in res["callers"]]
        assert any("verify_otp_view" in c for c in caller_names)
        assert all(c["evidence"]["type"] == "call" for c in res["callers"])


# ---------------------------------------------------------------------------
# 7. get_callees tests
# ---------------------------------------------------------------------------
def test_get_callees(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        # verify_otp_view calls verify_otp and AuthService.create_session
        res = get_callees(con, sample_repo, "verify_otp_view")
        assert res["status"] == "ok"
        callee_names = [c["callee"] for c in res["callees"]]
        assert any("verify_otp" in c for c in callee_names)
        assert all(c["call_type"] in ("resolved_call", "unresolved_call", "external_call") for c in res["callees"])


# ---------------------------------------------------------------------------
# 8. trace_path tests
# ---------------------------------------------------------------------------
def test_trace_path_success(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        # login_endpoint -> verify_otp_view -> verify_otp
        res = trace_path(con, sample_repo, "login_endpoint", "verify_otp")
        assert res["status"] == "ok"
        assert res["path_length"] >= 1
        for step in res["path"]:
            assert "source" in step
            assert "target" in step
            assert step["relationship"] == "CALLS"
            assert "evidence" in step


def test_trace_path_not_found(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        # duplicate_helper has no path to login_endpoint
        res = trace_path(con, sample_repo, "duplicate_helper", "login_endpoint")
        assert res["status"] == "not_found"
        assert res["path"] == []


# ---------------------------------------------------------------------------
# 9. get_imports tests
# ---------------------------------------------------------------------------
def test_get_imports(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_imports(con, sample_repo, file="src/auth/views.py")
        assert res["status"] == "ok"
        assert res["count"] >= 1
        targets = [i["target"] for i in res["imports"]]
        assert any("service" in t for t in targets)


# ---------------------------------------------------------------------------
# 10. get_dependents tests
# ---------------------------------------------------------------------------
def test_get_dependents(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_dependents(con, sample_repo, canonical_id="src/auth/service.py")
        assert res["status"] == "ok"
        assert res["count"] >= 1
        dep_files = [d["file"] for d in res["dependents"]]
        assert any("views.py" in f for f in dep_files)


# ---------------------------------------------------------------------------
# 11. list_routes tests
# ---------------------------------------------------------------------------
def test_list_routes(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = list_routes(con, sample_repo)
        assert res["status"] == "ok"
        assert res["count"] >= 1
        assert res["routes"][0]["path"] == "/auth/verify"
        assert res["routes"][0]["method"] == "POST"
        assert res["routes"][0]["evidence"]["type"] == "route"


def test_list_routes_filtered(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = list_routes(con, sample_repo, method="GET")
        assert res["status"] == "ok"
        assert res["count"] == 0


# ---------------------------------------------------------------------------
# 12. get_architecture tests
# ---------------------------------------------------------------------------
def test_get_architecture(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_architecture(con, sample_repo)
        assert res["status"] == "ok"
        assert "languages" in res
        assert "routes" in res
        assert "modules" in res


# ---------------------------------------------------------------------------
# 13. get_git_impact tests
# ---------------------------------------------------------------------------
def test_get_git_impact(sample_repo: Path) -> None:
    # Make a small code change to create a diff
    (sample_repo / "src" / "auth" / "service.py").write_text(
        "class AuthService:\n"
        "    def create_session(self, user_id: str) -> str:\n"
        "        return 'modified_' + user_id\n"
        "\n"
        "def verify_otp(otp_code: str) -> bool:\n"
        "    return otp_code == '123456'\n",
        encoding="utf-8",
    )
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = get_git_impact(con, sample_repo, base="HEAD")
        assert res["status"] == "ok"
        assert "summary" in res
        assert "changed_files" in res


# ---------------------------------------------------------------------------
# 14. Determinism & FastMCP Integration Tests (All 13 Core Tools)
# ---------------------------------------------------------------------------
def test_determinism_repeated_invocations(sample_repo: Path) -> None:
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res1 = json.dumps(search_symbols(con, sample_repo, "verify"), sort_keys=True)
        res2 = json.dumps(search_symbols(con, sample_repo, "verify"), sort_keys=True)
        assert res1 == res2

        trace1 = json.dumps(trace_path(con, sample_repo, "login_endpoint", "verify_otp"), sort_keys=True)
        trace2 = json.dumps(trace_path(con, sample_repo, "login_endpoint", "verify_otp"), sort_keys=True)
        assert trace1 == trace2


def test_mcp_fastmcp_all_13_tools_registered(sample_repo: Path) -> None:
    server = create_server(sample_repo, profile="core")

    async def _check_tools() -> None:
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        expected_13 = {
            "resolve_symbol",
            "search_symbols",
            "get_symbol",
            "get_file",
            "get_references",
            "get_callers",
            "get_callees",
            "trace_path",
            "get_imports",
            "get_dependents",
            "list_routes",
            "get_architecture",
            "get_git_impact",
        }
        assert expected_13 == tool_names

        # Call resolve_symbol through FastMCP
        _, meta = await server.call_tool("resolve_symbol", {"name": "verify_otp_view"})
        res = meta.get("result") or meta
        assert res["status"] == "ok"
        assert res["symbol"]["name"] == "verify_otp_view"

        # Call search_symbols through FastMCP
        _, meta = await server.call_tool("search_symbols", {"query": "verify", "top_k": 5})
        res = meta.get("result") or meta
        assert res["status"] == "ok"
        assert res["count"] > 0

        # Call get_file through FastMCP
        _, meta = await server.call_tool("get_file", {"path": "src/auth/views.py"})
        res = meta.get("result") or meta
        assert res["status"] == "ok"
        assert res["file"] == "src/auth/views.py"

        # Call list_routes through FastMCP
        _, meta = await server.call_tool("list_routes", {})
        res = meta.get("result") or meta
        assert res["status"] == "ok"
        assert res["count"] >= 1

    asyncio.run(_check_tools())
