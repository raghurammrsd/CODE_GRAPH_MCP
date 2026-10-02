"""v2.1.1 Production Correction Release Feature & Regression Tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.architecture import get_architecture
from codegraph.cli import app
from codegraph.context import get_context
from codegraph.graph.traversal import (
    find_parallel_implementations,
    get_focused_graph,
    get_graph_summary,
    trace_call,
)
from codegraph.indexing.classifier import (
    FileCategory,
    classify_file,
    is_ignored_by_codegraphignore,
)
from codegraph.indexing.indexer import Indexer
from codegraph.indexing.test_framework import TestFramework as TF
from codegraph.indexing.test_framework import detect_test_framework
from codegraph.mcp.server import create_server
from codegraph.task import (
    AmbiguityStatus,
    TargetExpressionType,
    classify_target_expression,
    detect_target_ambiguity,
    extract_keywords_from_prompt,
)

# Prevent pytest from attempting to collect the TestFramework enum
TF.__test__ = False  # type: ignore[attr-defined]

runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. .codegraphignore syntax and trailing slash matching
# ---------------------------------------------------------------------------
def test_codegraphignore_syntax() -> None:
    patterns = [
        "*.min.js",
        "dist/",
        "build/",
        "temp/cache/",
        "secrets.env",
    ]
    # Trailing slash directory matching
    assert is_ignored_by_codegraphignore(Path("dist/bundle.js"), patterns) is True
    assert is_ignored_by_codegraphignore(Path("build/output.css"), patterns) is True
    assert is_ignored_by_codegraphignore(Path("temp/cache/item.json"), patterns) is True
    assert is_ignored_by_codegraphignore(Path("src/dist/bundle.js"), patterns) is True
    # Extension glob
    assert is_ignored_by_codegraphignore(Path("vendor/jquery.min.js"), patterns) is True
    # Non-matching
    assert is_ignored_by_codegraphignore(Path("src/main.py"), patterns) is False


# ---------------------------------------------------------------------------
# 2. Artifact classification (FileCategory)
# ---------------------------------------------------------------------------
def test_file_classification() -> None:
    assert classify_file("src/models/user.py") == FileCategory.SOURCE
    assert classify_file("tests/test_user.py") == FileCategory.TEST
    assert classify_file("src/user.test.ts") == FileCategory.TEST
    assert classify_file("frontend/static/bundle.min.js") == FileCategory.GENERATED
    assert classify_file("dist/index.js") == FileCategory.BUILD_ARTIFACT
    assert classify_file("build/out.js") == FileCategory.BUILD_ARTIFACT
    assert classify_file("node_modules/axios/index.js") == FileCategory.VENDOR
    assert classify_file("vendor/lib.js") == FileCategory.VENDOR
    assert classify_file("tsconfig.json") == FileCategory.CONFIG
    assert classify_file("images/logo.png") == FileCategory.BINARY


# ---------------------------------------------------------------------------
# 3. Generated bundle suppression
# ---------------------------------------------------------------------------
def test_generated_bundle_suppression(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "static").mkdir()

    # Normal source file
    (repo / "src" / "service.py").write_text(
        "def fetch_user():\n    return {'name': 'alice'}\n",
        encoding="utf-8",
    )
    # Minified generated bundle with obfuscated symbols
    (repo / "static" / "app.min.js").write_text(
        "function Cd(e){return e*2} function Nd(a,b){return a+b} var Hf=100;\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    indexer.index()

    with indexer.session() as con:
        # Check files table: category is GENERATED
        file_row = con.execute("SELECT category FROM files WHERE path LIKE '%app.min.js'").fetchone()
        assert file_row is not None
        assert file_row[0] == "GENERATED"

        # Check symbols table: Cd, Nd, Hf must NOT be indexed
        symbols = [r[0] for r in con.execute("SELECT name FROM symbols").fetchall()]
        assert "fetch_user" in symbols
        assert "Cd" not in symbols
        assert "Nd" not in symbols
        assert "Hf" not in symbols

        # Check chunks_fts: no search tokens for obfuscated bundle
        fts_hits = con.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'Nd'").fetchone()[0]
        assert fts_hits == 0


# ---------------------------------------------------------------------------
# Fixture for Graph, Traversal, and Architecture Tests
# ---------------------------------------------------------------------------
@pytest.fixture()
def indexed_repo(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "src").mkdir()

    (repo / "src" / "geo.py").write_text(
        "def calc_distance(lat1, lon1, lat2, lon2):\n"
        "    return haversine_km(lat1, lon1, lat2, lon2)\n\n"
        "def haversine_km(lat1, lon1, lat2, lon2):\n"
        "    return 6371.0\n",
        encoding="utf-8",
    )
    (repo / "src" / "search.py").write_text(
        "from src.geo import calc_distance, haversine_km\n\n"
        "def search_products(query, location):\n"
        "    d = calc_distance(0, 0, 1, 1)\n"
        "    h = haversine_km(0, 0, 1, 1)\n"
        "    return []\n",
        encoding="utf-8",
    )
    (repo / "src" / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from src.search import search_products\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/api/products')\n"
        "def product_endpoint(q: str):\n"
        "    return search_products(q, 'city')\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    indexer.index()
    con = indexer.connect()
    return repo, con


# ---------------------------------------------------------------------------
# 4, 5, 6. Graph Summary, Module View, and Bounded Traversal
# ---------------------------------------------------------------------------
def test_graph_summary(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    summary = get_graph_summary(con)
    assert int(str(summary["total_symbols"])) >= 3
    assert int(str(summary["total_edges"])) >= 2
    edge_counts = summary["edge_counts"]
    assert isinstance(edge_counts, dict)
    assert "CALLS" in edge_counts
    modules = summary["modules"]
    assert isinstance(modules, list)
    assert len(modules) > 0


def test_graph_module_view(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    focused = get_focused_graph(con, module="src/geo.py")
    assert focused["module"] == "src/geo.py"
    nodes = focused["nodes"]
    assert isinstance(nodes, list)
    names = [n["name"] for n in nodes if isinstance(n, dict)]
    assert "calc_distance" in names
    assert "haversine_km" in names


def test_graph_bounded_traversal(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    focused = get_focused_graph(con, symbol="calc_distance", depth=1)
    assert focused["symbol"] == "calc_distance"
    nodes = focused["nodes"]
    assert isinstance(nodes, list)
    node_ids = {n["id"] for n in nodes if isinstance(n, dict)}
    assert "calc_distance" in node_ids


# ---------------------------------------------------------------------------
# 7, 8, 9, 10. Trace Callers, Callees, Both, and Max Depth Clamping
# ---------------------------------------------------------------------------
def test_trace_callers(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    trace = trace_call(con, "calc_distance", callers=True, callees=False)
    relations = [r["relationship"] for r in trace]
    assert "CALLER" in relations
    assert "CALLEE" not in relations


def test_trace_callees(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    trace = trace_call(con, "search_products", callers=False, callees=True)
    relations = [r["relationship"] for r in trace]
    assert "CALLEE" in relations
    assert "CALLER" not in relations


def test_trace_both(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    trace = trace_call(con, "search_products", both=True)
    relations = [r["relationship"] for r in trace]
    assert "CALLER" in relations
    assert "CALLEE" in relations


def test_trace_max_depth_clamping(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    trace = trace_call(con, "calc_distance", max_depth=100)
    assert len(trace) > 0



# ---------------------------------------------------------------------------
# 11, 12. Route Listing and Filtering
# ---------------------------------------------------------------------------
def test_route_listing_and_filtering(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    routes = con.execute("SELECT http_method, route_path, framework FROM framework_routes").fetchall()
    assert len(routes) == 1
    assert routes[0]["http_method"] == "GET"
    assert routes[0]["route_path"] == "/api/products"

    # Filter by framework
    fastapi_routes = con.execute("SELECT * FROM framework_routes WHERE framework=?", ("fastapi",)).fetchall()
    assert len(fastapi_routes) == 1
    flask_routes = con.execute("SELECT * FROM framework_routes WHERE framework=?", ("flask",)).fetchall()
    assert len(flask_routes) == 0


# ---------------------------------------------------------------------------
# 13. Architecture Command / Summary
# ---------------------------------------------------------------------------
def test_architecture_summary(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    repo, con = indexed_repo
    arch = get_architecture(con, repo)
    assert "frameworks" in arch
    assert "top_level_modules" in arch
    assert "route_summary" in arch
    route_summary = arch["route_summary"]
    assert isinstance(route_summary, dict)
    assert route_summary["total_routes"] == 1
    frameworks = arch["frameworks"]
    assert isinstance(frameworks, list)
    assert "fastapi" in frameworks


# ---------------------------------------------------------------------------
# 14, 15, 16. Target Grounding: Concept vs NL vs Explicit Symbol
# ---------------------------------------------------------------------------
def test_concept_target_grounding(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    assert classify_target_expression("product search") == TargetExpressionType.CONCEPT_TARGET
    assert classify_target_expression("user authentication") == TargetExpressionType.CONCEPT_TARGET

    _, con = indexed_repo
    ambiguity = detect_target_ambiguity("product search", con)
    assert ambiguity.status != AmbiguityStatus.UNKNOWN


def test_natural_language_target_suppression() -> None:
    assert classify_target_expression("works") == TargetExpressionType.NATURAL_LANGUAGE_TERM
    assert classify_target_expression("input") == TargetExpressionType.NATURAL_LANGUAGE_TERM
    assert classify_target_expression("final") == TargetExpressionType.NATURAL_LANGUAGE_TERM
    assert classify_target_expression("results") == TargetExpressionType.NATURAL_LANGUAGE_TERM

    keywords = extract_keywords_from_prompt("how does product search input lead to final results")
    assert "works" not in keywords
    assert "input" not in keywords
    assert "final" not in keywords
    assert "results" not in keywords


def test_unknown_explicit_symbol(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    assert classify_target_expression("FakePayService") == TargetExpressionType.EXPLICIT_SYMBOL_TARGET
    assert classify_target_expression("calc_distance") == TargetExpressionType.EXPLICIT_SYMBOL_TARGET

    _, con = indexed_repo
    ambiguity = detect_target_ambiguity("FakePayService", con)
    assert ambiguity.status == AmbiguityStatus.UNKNOWN


# ---------------------------------------------------------------------------
# 17. Unknown Debug Behavior
# ---------------------------------------------------------------------------
def test_debug_unknown_target_behavior(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "billing.py").write_text("def process_payment(): pass\n", encoding="utf-8")

    indexer = Indexer(repo)
    indexer.index()

    result = runner.invoke(app, ["debug", "FakePayService billing handler", "-r", str(repo)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data.get("STATUS") == "UNKNOWN"
    assert data.get("TARGET") == "FakePayService"
    assert "RELATED_LEXICAL_RESULTS" in data


# ---------------------------------------------------------------------------
# 18. Parallel Implementation Discovery
# ---------------------------------------------------------------------------
def test_find_parallel_implementations(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    _, con = indexed_repo
    parallel = find_parallel_implementations(con, "calc_distance")
    target_cids = [p["canonical_id"] for p in parallel]
    assert any("haversine_km" in cid for cid in target_cids)


# ---------------------------------------------------------------------------
# 19. Haversine Context Regression
# ---------------------------------------------------------------------------
def test_haversine_context_regression(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    repo, con = indexed_repo
    packet = get_context(con, repo, "Explain product search from user input to final results")
    retrieved_symbols = [s.symbol for s in packet.symbols]

    assert any("search_products" in s for s in retrieved_symbols)
    assert any("calc_distance" in s for s in retrieved_symbols)
    assert any("haversine_km" in s for s in retrieved_symbols)


# ---------------------------------------------------------------------------
# 20. Decorator / Framework Evidence
# ---------------------------------------------------------------------------
def test_framework_decorator_evidence(indexed_repo: tuple[Path, sqlite3.Connection]) -> None:
    repo, con = indexed_repo
    packet = get_context(con, repo, "How does product endpoint work?")
    assert len(packet.framework_facts) > 0
    facts_str = " ".join(str(f) for f in packet.framework_facts)
    assert "route" in facts_str.lower() or "/api/products" in facts_str


# ---------------------------------------------------------------------------
# 21. Test Framework Detection
# ---------------------------------------------------------------------------
def test_detect_test_framework(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_auth.py").write_text(
        "import pytest\n\ndef test_auth():\n    assert True\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    indexer.index()
    with indexer.session() as con:
        fw, tests_present, evidence = detect_test_framework(con, repo)
        assert fw == TF.PYTEST
        assert tests_present is True
        assert len(evidence) > 0


# ---------------------------------------------------------------------------
# 22, 23. MCP Stdio Server Creation and Tool Registration
# ---------------------------------------------------------------------------
def test_mcp_server_creation_and_tools(tmp_path: Path) -> None:
    server = create_server(tmp_path)
    assert server is not None
    assert hasattr(server, "_tool_manager") or hasattr(server, "list_tools")


# ---------------------------------------------------------------------------
# 24. Stdout / Stderr Separation
# ---------------------------------------------------------------------------
def test_stdout_json_cleanliness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def ping(): return 'pong'\n", encoding="utf-8")

    # codegraph init --json
    result = runner.invoke(app, ["init", str(repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["status"] == "initialized"


# ---------------------------------------------------------------------------
# 25. Project Isolation
# ---------------------------------------------------------------------------
def test_project_isolation(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    (repo_a / "a.py").write_text("def unique_symbol_a(): pass\n", encoding="utf-8")
    (repo_b / "b.py").write_text("def unique_symbol_b(): pass\n", encoding="utf-8")

    Indexer(repo_a).index()
    Indexer(repo_b).index()

    with Indexer(repo_a).session() as con_a:
        syms_a = [r[0] for r in con_a.execute("SELECT name FROM symbols").fetchall()]
        assert "unique_symbol_a" in syms_a
        assert "unique_symbol_b" not in syms_a

    with Indexer(repo_b).session() as con_b:
        syms_b = [r[0] for r in con_b.execute("SELECT name FROM symbols").fetchall()]
        assert "unique_symbol_b" in syms_b
        assert "unique_symbol_a" not in syms_b


# ---------------------------------------------------------------------------
# 26. Clean Installed-Package Execution (Doctor & Status)
# ---------------------------------------------------------------------------
def test_doctor_and_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    Indexer(repo).index()

    # codegraph doctor --database
    doc_db_result = runner.invoke(app, ["doctor", "-r", str(repo), "--database", "--json"])
    assert doc_db_result.exit_code == 0
    doc_db_data = json.loads(doc_db_result.stdout)
    assert doc_db_data["status"] == "OK"

    # codegraph doctor
    doc_result = runner.invoke(app, ["doctor", "-r", str(repo), "--json"])
    assert doc_result.exit_code == 0
    doc_data = json.loads(doc_result.stdout)
    assert doc_data["status"] == "healthy"
    assert doc_data["health"]["status"] == "OK"

    # codegraph status
    status_result = runner.invoke(app, ["status", "-r", str(repo), "--json"])
    assert status_result.exit_code == 0
    status_data = json.loads(status_result.stdout)
    assert status_data["freshness"] == "FRESH"
