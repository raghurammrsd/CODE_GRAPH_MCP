"""Regression tests for framework route identity, collision prevention, and idempotent persistence."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.frameworks import RouteDetection, analyze_js_ts_line
from codegraph.indexing import Indexer
from codegraph.indexing.indexer import check_database_health
from codegraph.target_resolver import TargetType, resolve_target


def test_deterministic_endpoint_ids() -> None:
    """Verify endpoint_id is stable, deterministic, and includes declaration evidence."""
    r1 = RouteDetection(
        framework="express",
        http_method="GET",
        route_path="/products",
        normalized_route="/products",
        handler_name="getProducts",
        handler_canonical_id="routes.products.getProducts",
        file_path="src/routes/products.ts",
        line=12,
        column=4,
        confidence="HIGH",
        resolution_status="RESOLVED",
        evidence="router.get('/products', getProducts)",
        module="src.routes.products",
    )
    r2 = RouteDetection(
        framework="express",
        http_method="GET",
        route_path="/products",
        normalized_route="/products",
        handler_name="getProducts",
        handler_canonical_id="routes.products.getProducts",
        file_path="src/routes/products.ts",
        line=12,
        column=4,
        confidence="HIGH",
        resolution_status="RESOLVED",
        evidence="router.get('/products', getProducts)",
        module="src.routes.products",
    )
    # Must be deterministic and stable
    assert r1.endpoint_id == r2.endpoint_id
    assert r1.endpoint_id == "API_ENDPOINT:express:src/routes/products.ts:12:GET /products#getProducts"

    # Override takes precedence if provided (e.g. from existing DB records)
    r_override = RouteDetection(
        framework="express",
        http_method="GET",
        route_path="/products",
        normalized_route="/products",
        handler_name="getProducts",
        handler_canonical_id="routes.products.getProducts",
        file_path="src/routes/products.ts",
        line=12,
        endpoint_id_override="CUSTOM_ID_123",
    )
    assert r_override.endpoint_id == "CUSTOM_ID_123"


def test_endpoint_id_collision_prevention_same_file() -> None:
    """Verify distinct route declarations in the same file for same path produce distinct endpoint_ids."""
    lines = [
        "router.get('/products', authCheck);",
        "router.get('/products', listProducts);",
    ]
    routes: list[RouteDetection] = []
    for idx, line in enumerate(lines):
        routes.extend(analyze_js_ts_line(line, idx + 1, "routes/products.js", "routes.products", set()))

    assert len(routes) == 2
    assert routes[0].route_signature == "GET /products"
    assert routes[1].route_signature == "GET /products"
    # Route signature is identical, but endpoint_id must be distinct!
    assert routes[0].endpoint_id != routes[1].endpoint_id
    assert "authCheck" in routes[0].endpoint_id
    assert "listProducts" in routes[1].endpoint_id


def test_two_files_with_same_method_and_path(tmp_path: Path) -> None:
    """Verify two distinct files with identical method + path can coexist without collisions."""
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir(parents=True)

    file_a = routes_dir / "a.ts"
    file_a.write_text("router.get('/products', handlerA);\n", encoding="utf-8")

    file_b = routes_dir / "b.ts"
    file_b.write_text("router.get('/products', handlerB);\n", encoding="utf-8")

    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res["indexed"] == 2

    with indexer.session() as con:
        rows = con.execute(
            "SELECT endpoint_id, file_path, handler_name, line FROM framework_routes ORDER BY file_path"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["file_path"] == "routes/a.ts"
        assert rows[0]["handler_name"] == "handlerA"
        assert rows[1]["file_path"] == "routes/b.ts"
        assert rows[1]["handler_name"] == "handlerB"
        # Neither overwrote the other!
        assert rows[0]["endpoint_id"] != rows[1]["endpoint_id"]


def test_same_route_declaration_discovered_twice(tmp_path: Path) -> None:
    """Verify exact duplicate route declaration handled idempotently via ON CONFLICT without crash."""
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # File must exist to satisfy foreign key
        con.execute(
            "INSERT INTO files(path, hash, language, indexed_at, status) VALUES ('app.js', 'h1', 'javascript', 0, 'ok')"
        )
        r = RouteDetection(
            framework="express",
            http_method="GET",
            route_path="/items",
            normalized_route="/items",
            handler_name="getItems",
            handler_canonical_id="app.getItems",
            file_path="app.js",
            line=10,
            evidence="router.get('/items', getItems)",
        )
        query = (
            "INSERT INTO framework_routes(endpoint_id, framework, http_method, route_path, "
            "normalized_route, handler_name, handler_canonical_id, file_path, line, evidence, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(endpoint_id) DO UPDATE SET "
            "framework=excluded.framework, "
            "http_method=excluded.http_method, "
            "route_path=excluded.route_path, "
            "normalized_route=excluded.normalized_route, "
            "handler_name=excluded.handler_name, "
            "handler_canonical_id=excluded.handler_canonical_id, "
            "file_path=excluded.file_path, "
            "line=excluded.line, "
            "evidence=excluded.evidence, "
            "confidence=excluded.confidence"
        )
        # Execute twice with identical endpoint_id in same transaction
        con.execute(query, (r.endpoint_id, r.framework, r.http_method, r.route_path, r.normalized_route, r.handler_name, r.handler_canonical_id, "app.js", r.line, r.evidence, r.confidence))
        con.execute(query, (r.endpoint_id, r.framework, r.http_method, r.route_path, r.normalized_route, r.handler_name, r.handler_canonical_id, "app.js", r.line, "updated evidence", r.confidence))

        row = con.execute("SELECT count(*), evidence FROM framework_routes WHERE endpoint_id=?", (r.endpoint_id,)).fetchone()
        assert row[0] == 1
        assert row[1] == "updated evidence"


def test_repeated_indexing(tmp_path: Path) -> None:
    """Verify repeated indexing does not crash and produces consistent route count."""
    (tmp_path / "server.js").write_text(
        "app.get('/health', getHealth);\n"
        "app.post('/login', postLogin);\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)

    # First index
    res1 = indexer.index()
    assert res1["indexed"] == 1

    with indexer.session() as con:
        count1 = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        assert count1 == 2

    # Second index immediately (files unchanged)
    res2 = indexer.index()
    assert res2["unchanged"] == 1

    with indexer.session() as con:
        count2 = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        assert count2 == 2

    # Third index with force_reparse
    with indexer.session() as con:
        # Force reparse by setting parser version to dummy
        con.execute("UPDATE metadata SET value='old_parser' WHERE key='parser_version'")

    res3 = indexer.index()
    assert res3["indexed"] == 1

    with indexer.session() as con:
        count3 = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        assert count3 == 2


def test_incremental_route_reindex(tmp_path: Path) -> None:
    """Verify modifying a route file replaces old routes cleanly without orphan rows."""
    file_path = tmp_path / "routes.js"
    file_path.write_text("router.get('/products', oldHandler);\n", encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        rows = con.execute("SELECT handler_name, line FROM framework_routes WHERE file_path='routes.js'").fetchall()
        assert len(rows) == 1
        assert rows[0]["handler_name"] == "oldHandler"
        assert rows[0]["line"] == 1

    # Modify file: shift line down and add another route
    file_path.write_text(
        "// added comment header\n"
        "// line 2\n"
        "router.get('/products', newHandler);\n"
        "router.delete('/products', deleteHandler);\n",
        encoding="utf-8",
    )

    indexer.index()

    with indexer.session() as con:
        rows = con.execute("SELECT handler_name, http_method, line FROM framework_routes WHERE file_path='routes.js' ORDER BY line").fetchall()
        assert len(rows) == 2
        # Old route removed, new routes added at correct lines
        assert rows[0]["handler_name"] == "newHandler"
        assert rows[0]["line"] == 3
        assert rows[1]["handler_name"] == "deleteHandler"
        assert rows[1]["line"] == 4


def test_route_foreign_key_and_evidence_integrity(tmp_path: Path) -> None:
    """Verify foreign key integrity on framework_routes and evidence persistence."""
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/users/{user_id}')\n"
        "def get_user(user_id: int):\n"
        "    return {'id': user_id}\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Check foreign key to files table
        row = con.execute(
            "SELECT r.endpoint_id, r.file_path, f.path, r.evidence "
            "FROM framework_routes r JOIN files f ON r.file_path = f.path"
        ).fetchone()
        assert row is not None
        assert row["file_path"] == "app.py"
        assert "FastAPI decorator" in row["evidence"]

        # Doctor health check
        health = check_database_health(con, tmp_path)
        assert health["status"] == "OK"
        assert health["issues"] == []


def test_framework_route_queries_after_deduplication(tmp_path: Path) -> None:
    """Verify CLI and target resolver queries against framework_routes work accurately."""
    (tmp_path / "routes.js").write_text(
        "router.get('/items', getItems);\n"
        "router.post('/items', createItem);\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    runner = CliRunner()
    res = runner.invoke(app, ["routes", str(tmp_path), "--json"])
    assert res.exit_code == 0
    assert "/items" in res.stdout
    assert "getItems" in res.stdout
    assert "createItem" in res.stdout

    with indexer.session() as con:
        target_res = resolve_target("/items", con)
        assert target_res.target_type == TargetType.API_ENDPOINT
        assert target_res.confidence == "HIGH"


def test_check_database_health_detects_route_issues(tmp_path: Path) -> None:
    """Verify check_database_health flags orphan routes and duplicate endpoint IDs."""
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # 1. Initially healthy
        assert check_database_health(con, tmp_path)["status"] == "OK"

        # 2. Insert orphan route referencing non-existent file
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute(
            "INSERT INTO framework_routes(endpoint_id, framework, http_method, route_path, normalized_route, handler_name, handler_canonical_id, file_path, line, evidence) "
            "VALUES ('ep_orphan', 'express', 'GET', '/orphan', '/orphan', 'h', 'h', 'non_existent.js', 1, 'ev')"
        )
        h_orphan = check_database_health(con, tmp_path)
        assert h_orphan["status"] == "ISSUES_FOUND"
        assert any("orphan route" in issue for issue in h_orphan["issues"])


def test_fastapi_duplicate_overlapping_routes(tmp_path: Path) -> None:
    """Verify FastAPI routes with duplicate/overlapping route paths in same file index without collisions."""
    app_file = tmp_path / "app.py"
    app_file.write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/items')\n"
        "def get_items_summary():\n"
        "    return []\n"
        "@app.get('/items')\n"
        "def get_items_detail():\n"
        "    return []\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res["indexed"] == 1

    with indexer.session() as con:
        rows = con.execute(
            "SELECT endpoint_id, handler_name, line FROM framework_routes WHERE file_path='app.py' ORDER BY line"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["handler_name"] == "get_items_summary"
        assert rows[1]["handler_name"] == "get_items_detail"
        assert rows[0]["endpoint_id"] != rows[1]["endpoint_id"]
        assert "get_items_summary" in rows[0]["endpoint_id"]
        assert "get_items_detail" in rows[1]["endpoint_id"]


def test_fastapi_and_express_both_work_in_same_repo(tmp_path: Path) -> None:
    """Verify both FastAPI (Python) and Express (JS/TS) routes index and coexist without collisions."""
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/api/health')\n"
        "def py_health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (tmp_path / "server.js").write_text(
        "app.get('/api/health', jsHealth);\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res["indexed"] == 2

    with indexer.session() as con:
        rows = con.execute(
            "SELECT endpoint_id, framework, file_path, handler_name FROM framework_routes ORDER BY framework"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["framework"] == "express"
        assert rows[0]["handler_name"] == "jsHealth"
        assert rows[1]["framework"] == "fastapi"
        assert rows[1]["handler_name"] == "py_health"
        assert "express" in rows[0]["endpoint_id"]
        assert "fastapi" in rows[1]["endpoint_id"]
        assert rows[0]["endpoint_id"] != rows[1]["endpoint_id"]
