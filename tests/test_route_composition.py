"""Comprehensive regression test suite for Phase 2: Hierarchical Route Composition.

Covers:
- FastAPI: include_router, nested prefixes, APIRouter aliases
- Flask: register_blueprint, url_prefix composition
- Django: include(...), multi-file urlpatterns composition
- Express: app.use, router.use, nested router mounts
- Same router mounted at multiple prefixes
- Deterministic, collision-safe endpoint_ids
- Repeated indexing (idempotence)
- Incremental route changes without re-parsing children
- Stale route cleanup
- MOUNTS is FRAMEWORK_VERIFIED and never CALLS
"""
from __future__ import annotations

from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.interrogation import list_routes


def test_fastapi_nested_mounts_and_prefix_composition(tmp_path: Path) -> None:
    """Verify FastAPI hierarchical router mounts compose multi-level prefixes deterministically."""
    # Child router in routers/users.py with router-level base prefix
    routers_dir = tmp_path / "routers"
    routers_dir.mkdir(parents=True)
    (routers_dir / "users.py").write_text("""
from fastapi import APIRouter

router = APIRouter(prefix="/users")

@router.get("/{user_id}")
def get_user(user_id: int):
    return {"id": user_id}
""")

    # Intermediate router in api.py
    (tmp_path / "api.py").write_text("""
from fastapi import APIRouter
from routers.users import router as user_router

api_router = APIRouter()
api_router.include_router(user_router, prefix="/v1")
""")

    # Main root app in main.py
    (tmp_path / "main.py").write_text("""
from fastapi import FastAPI
from api import api_router

app = FastAPI()
app.include_router(api_router, prefix="/api")
""")

    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res["indexed"] == 3

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="fastapi")
        assert routes_res["status"] == "ok"
        routes = routes_res["routes"]
        assert len(routes) == 1
        rt = routes[0]

        # Composed prefix: /api + /v1 + /users + /{user_id} -> /api/v1/users/{user_id}
        assert rt["path"] == "/api/v1/users/{user_id}"
        assert rt["method"] == "GET"
        assert rt["file"] == "routers/users.py"
        assert "get_user" in rt["handler"]

        # Verify evidence chain
        ev_list = rt["evidence"]
        assert len(ev_list) >= 1
        raw_ev = con.execute("SELECT evidence, endpoint_id FROM framework_routes").fetchone()
        assert "mounted via" in raw_ev["evidence"]
        assert "include_router" in raw_ev["evidence"]
        assert "API_ENDPOINT:fastapi:routers/users.py" in raw_ev["endpoint_id"]
        assert "/api/v1/users/{user_id}" in raw_ev["endpoint_id"]

        # Verify graph_edges
        edge = con.execute("SELECT relationship, evidence_class FROM graph_edges WHERE relationship='ROUTES_TO'").fetchone()
        assert edge is not None
        assert edge["relationship"] == "ROUTES_TO"
        assert edge["evidence_class"] == "FRAMEWORK_VERIFIED"


def test_flask_blueprint_composition_and_url_prefix(tmp_path: Path) -> None:
    """Verify Flask blueprint registration with url_prefix composition."""
    (tmp_path / "auth.py").write_text("""
from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/login", methods=["POST"])
def auth_login():
    return "ok"
""")

    (tmp_path / "app.py").write_text("""
from flask import Flask
from auth import auth_bp

app = Flask(__name__)
app.register_blueprint(auth_bp, url_prefix="/api/v1")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="flask")
        routes = routes_res["routes"]
        assert len(routes) == 1
        rt = routes[0]
        # /api/v1 + /auth + /login -> /api/v1/auth/login
        assert rt["path"] == "/api/v1/auth/login"
        assert rt["method"] == "POST"
        assert rt["file"] == "auth.py"
        assert "auth_login" in rt["handler"]


def test_django_multi_file_urlpatterns_composition(tmp_path: Path) -> None:
    """Verify Django path(..., include(...)) composition across multi-file urlpatterns."""
    myapp = tmp_path / "myapp"
    myapp.mkdir(parents=True)

    (myapp / "users_urls.py").write_text("""
from django.urls import path
from . import views

urlpatterns = [
    path("list/", views.user_list),
]
""")

    (myapp / "urls.py").write_text("""
from django.urls import path, include

urlpatterns = [
    path("users/", include("myapp.users_urls")),
]
""")

    (tmp_path / "root_urls.py").write_text("""
from django.urls import path, include

urlpatterns = [
    path("api/v1/", include("myapp.urls")),
]
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="django")
        routes = routes_res["routes"]
        assert len(routes) == 1
        rt = routes[0]
        # "api/v1/" + "users/" + "list/" -> /api/v1/users/list
        assert rt["path"] == "/api/v1/users/list"
        assert rt["file"] == "myapp/users_urls.py"
        assert "user_list" in rt["handler"]


def test_express_nested_router_mounts(tmp_path: Path) -> None:
    """Verify Express app.use and router.use compose nested prefixes."""
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir(parents=True)

    (routes_dir / "users.js").write_text("""
const express = require('express');
const router = express.Router();

router.get('/profile', getUserProfile);
module.exports = router;
""")

    (routes_dir / "api.js").write_text("""
const express = require('express');
const router = express.Router();
const users = require('./users');

router.use('/users', users);
module.exports = router;
""")

    (tmp_path / "app.js").write_text("""
const express = require('express');
const app = express();
const api = require('./routes/api');

app.use('/api/v1', api);
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="express")
        routes = routes_res["routes"]
        assert len(routes) == 1
        rt = routes[0]
        # /api/v1 + /users + /profile -> /api/v1/users/profile
        assert rt["path"] == "/api/v1/users/profile"
        assert rt["method"] == "GET"
        assert rt["file"] == "routes/users.js"
        assert "getUserProfile" in rt["handler"]


def test_fastapi_router_aliases(tmp_path: Path) -> None:
    """Verify APIRouter imported with an alias is resolved and composed cleanly."""
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True)

    (pkg / "auth_routes.py").write_text("""
from fastapi import APIRouter

router = APIRouter()

@router.post("/token")
def issue_token():
    return {"token": "xyz"}
""")

    (tmp_path / "main.py").write_text("""
from fastapi import FastAPI
from pkg.auth_routes import router as authentication_router

app = FastAPI()
app.include_router(authentication_router, prefix="/security")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="fastapi")
        routes = routes_res["routes"]
        assert len(routes) == 1
        rt = routes[0]
        assert rt["path"] == "/security/token"
        assert rt["method"] == "POST"
        assert rt["file"] == "pkg/auth_routes.py"
        assert "issue_token" in rt["handler"]


def test_same_router_mounted_at_multiple_prefixes(tmp_path: Path) -> None:
    """Verify a router mounted at multiple prefixes produces distinct, non-colliding routes."""
    (tmp_path / "health.py").write_text("""
from fastapi import APIRouter

health_router = APIRouter()

@health_router.get("/ping")
def ping():
    return "pong"
""")

    (tmp_path / "app.py").write_text("""
from fastapi import FastAPI
from health import health_router

app = FastAPI()
app.include_router(health_router, prefix="/health")
app.include_router(health_router, prefix="/api/v1/health")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        routes_res = list_routes(con, tmp_path, framework="fastapi")
        routes = routes_res["routes"]
        assert len(routes) == 2

        paths = {r["path"] for r in routes}
        assert paths == {"/health/ping", "/api/v1/health/ping"}

        # Verify distinct, non-colliding endpoint_ids
        ep_rows = con.execute("SELECT endpoint_id, route_path FROM framework_routes ORDER BY route_path ASC").fetchall()
        assert len(ep_rows) == 2
        assert ep_rows[0]["endpoint_id"] != ep_rows[1]["endpoint_id"]
        assert "/api/v1/health/ping" in ep_rows[0]["endpoint_id"]
        assert "/health/ping" in ep_rows[1]["endpoint_id"]


def test_repeated_indexing_is_idempotent(tmp_path: Path) -> None:
    """Verify running indexing multiple times preserves deterministic state and row counts."""
    (tmp_path / "routes.py").write_text("""
from fastapi import APIRouter
router = APIRouter()
@router.get("/items")
def list_items(): return []
""")
    (tmp_path / "app.py").write_text("""
from fastapi import FastAPI
from routes import router
app = FastAPI()
app.include_router(router, prefix="/api")
""")

    indexer = Indexer(tmp_path)
    res1 = indexer.index()
    assert res1["indexed"] == 2

    with indexer.session() as con:
        count1 = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        edges1 = con.execute("SELECT count(*) FROM graph_edges").fetchone()[0]

    # Run indexing again on unchanged repo
    res2 = indexer.index()
    assert res2["unchanged"] == 2
    assert res2["indexed"] == 0

    with indexer.session() as con:
        count2 = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
        edges2 = con.execute("SELECT count(*) FROM graph_edges").fetchone()[0]
        assert count1 == count2 == 1
        assert edges1 == edges2


def test_incremental_route_changes(tmp_path: Path) -> None:
    """Verify changing a mount prefix in app.py updates child routes without modifying child file."""
    (tmp_path / "items.py").write_text("""
from fastapi import APIRouter
router = APIRouter()
@router.get("/all")
def get_all(): return []
""")
    app_file = tmp_path / "app.py"
    app_file.write_text("""
from fastapi import FastAPI
from items import router
app = FastAPI()
app.include_router(router, prefix="/v1")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        r = con.execute("SELECT route_path FROM framework_routes").fetchone()
        assert r["route_path"] == "/v1/all"

    # Now update app.py prefix to /v2 (items.py remains unchanged)
    app_file.write_text("""
from fastapi import FastAPI
from items import router
app = FastAPI()
app.include_router(router, prefix="/v2")
""")
    res = indexer.index()
    assert res["indexed"] == 1  # Only app.py re-indexed!
    assert res["unchanged"] == 1  # items.py unchanged!

    with indexer.session() as con:
        routes = con.execute("SELECT route_path FROM framework_routes").fetchall()
        assert len(routes) == 1
        assert routes[0]["route_path"] == "/v2/all"


def test_stale_route_cleanup(tmp_path: Path) -> None:
    """Verify deleting a child router file or its mount completely eliminates stale routes."""
    items_file = tmp_path / "items.py"
    items_file.write_text("""
from fastapi import APIRouter
router = APIRouter()
@router.get("/all")
def get_all(): return []
""")
    (tmp_path / "app.py").write_text("""
from fastapi import FastAPI
from items import router
app = FastAPI()
app.include_router(router, prefix="/api")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        assert con.execute("SELECT count(*) FROM framework_routes").fetchone()[0] == 1

    # Remove items.py and update app.py
    items_file.unlink()
    (tmp_path / "app.py").write_text("""
from fastapi import FastAPI
app = FastAPI()
@app.get("/root")
def root(): return {}
""")

    indexer.index()

    with indexer.session() as con:
        routes = con.execute("SELECT route_path FROM framework_routes").fetchall()
        assert len(routes) == 1
        assert routes[0]["route_path"] == "/root"


def test_router_mount_never_represented_as_calls(tmp_path: Path) -> None:
    """Verify router mounting relationships are marked as MOUNTS (FRAMEWORK_VERIFIED), never CALLS."""
    (tmp_path / "users.py").write_text("""
from fastapi import APIRouter
router = APIRouter()
@router.get("/me")
def me(): return {}
""")
    (tmp_path / "main.py").write_text("""
from fastapi import FastAPI
from users import router
app = FastAPI()
app.include_router(router, prefix="/api")
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Check mount edges in graph_edges
        mount_edges = con.execute("SELECT * FROM graph_edges WHERE relationship='MOUNTS'").fetchall()
        assert len(mount_edges) >= 1
        for me in mount_edges:
            assert me["relationship"] == "MOUNTS"
            assert me["evidence_class"] == "FRAMEWORK_VERIFIED"
            assert me["reason"] == "router_mount"

        # Assert no router mounting statement was converted into a CALLS edge
        calls_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='CALLS' AND (source LIKE '%main.py%app%' OR target LIKE '%users.py%router%')"
        ).fetchall()
        assert len(calls_edges) == 0
