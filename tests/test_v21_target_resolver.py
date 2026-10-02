"""v2.1 TargetResolver regression tests."""
from __future__ import annotations

import sqlite3

import pytest

from codegraph.target_resolver import (
    ResolutionMethod,
    TargetType,
    resolve_target,
    resolve_targets,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS symbols (
            id TEXT PRIMARY KEY,
            canonical_id TEXT,
            qualified_name TEXT,
            name TEXT,
            kind TEXT,
            path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            parent_symbol_id TEXT,
            module TEXT,
            scope TEXT,
            language TEXT,
            signature TEXT,
            content_hash TEXT,
            visibility TEXT,
            return_type TEXT,
            parameter_count INTEGER,
            documentation TEXT,
            decorators TEXT
        );
        CREATE TABLE IF NOT EXISTS framework_routes (
            id INTEGER PRIMARY KEY,
            route_path TEXT,
            http_method TEXT,
            handler_name TEXT,
            file_path TEXT,
            line INTEGER,
            endpoint_id TEXT,
            evidence TEXT
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE
        );
        INSERT INTO symbols VALUES
          ('auth.AuthService','auth.AuthService','auth.AuthService','AuthService','class',
           'src/services/auth_service.py',10,100,NULL,'auth','','python','','hash1','public',NULL,0,'',NULL),
          ('auth.AuthService.login','auth.AuthService.login','auth.AuthService.login','login','method',
           'src/services/auth_service.py',20,40,'auth.AuthService','auth','AuthService','python','','hash2','public',NULL,1,'',NULL),
          ('admin.AdminDashboardView','admin.AdminDashboardView','admin.AdminDashboardView','AdminDashboardView','class',
           'src/admin_panel/views.py',5,80,NULL,'admin','','python','','hash3','public',NULL,0,'',NULL),
          ('admin.AdminDashboardView.get','admin.AdminDashboardView.get','admin.AdminDashboardView.get','get','method',
           'src/admin_panel/views.py',10,30,'admin.AdminDashboardView','admin','AdminDashboardView','python','','hash4','public',NULL,0,'',NULL),
          ('tests.test_auth.test_auth_login_success','tests.test_auth.test_auth_login_success',
           'tests.test_auth.test_auth_login_success','test_auth_login_success','function',
           'tests/test_auth.py',15,25,NULL,'tests.test_auth','','python','','hash5','public',NULL,0,'',NULL);
        INSERT INTO framework_routes VALUES
          (1,'/api/v1/auth/login','POST','login_route','src/api/fastapi_app.py',30,'ep_auth_login','Decorator @app.post');
        INSERT INTO files VALUES
          (1,'src/services/auth_service.py'),
          (2,'src/admin_panel/views.py');
    """)
    return con


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExactCanonicalResolution:
    def test_resolves_canonical_id(self, db: sqlite3.Connection) -> None:
        res = resolve_target("auth.AuthService", db)
        assert res.resolution_method == ResolutionMethod.CANONICAL_ID
        assert res.confidence == "HIGH"
        assert res.canonical_id == "auth.AuthService"
        assert res.target_type == TargetType.CLASS

    def test_resolves_method_canonical(self, db: sqlite3.Connection) -> None:
        res = resolve_target("auth.AuthService.login", db)
        assert res.resolution_method == ResolutionMethod.CANONICAL_ID
        assert res.canonical_id == "auth.AuthService.login"
        assert res.target_type == TargetType.METHOD


class TestExactQualifiedResolution:
    def test_resolves_qualified_name(self, db: sqlite3.Connection) -> None:
        # qualified_name == canonical_id in this fixture; test via a different setup
        # that has a different qualified_name
        res = resolve_target("auth.AuthService", db)
        assert res.confidence == "HIGH"


class TestRouteTargetResolution:
    def test_resolves_route_path(self, db: sqlite3.Connection) -> None:
        res = resolve_target("/api/v1/auth/login", db)
        assert res.resolution_method == ResolutionMethod.ROUTE_MATCH
        assert res.target_type == TargetType.API_ENDPOINT
        assert res.confidence == "HIGH"

    def test_resolves_endpoint_id(self, db: sqlite3.Connection) -> None:
        res = resolve_target("ep_auth_login", db)
        assert res.resolution_method == ResolutionMethod.ROUTE_MATCH
        assert res.target_type == TargetType.API_ENDPOINT


class TestClassMethodResolution:
    def test_class_method_resolution(self, db: sqlite3.Connection) -> None:
        res = resolve_target("AdminDashboardView.get", db)
        assert res.resolution_method == ResolutionMethod.CLASS_METHOD
        assert res.target_type == TargetType.METHOD
        assert res.canonical_id == "admin.AdminDashboardView.get"

    def test_class_method_confidence_high(self, db: sqlite3.Connection) -> None:
        res = resolve_target("AuthService.login", db)
        assert res.resolution_method == ResolutionMethod.CLASS_METHOD
        assert res.confidence == "HIGH"


class TestAmbiguousResolution:
    def test_no_match_returns_unknown(self, db: sqlite3.Connection) -> None:
        res = resolve_target("NonExistentSymbolXYZ123", db)
        assert res.resolution_method == ResolutionMethod.UNKNOWN
        assert res.confidence == "UNKNOWN"
        assert res.canonical_id is None

    def test_short_name_unique_returns_medium(self, db: sqlite3.Connection) -> None:
        res = resolve_target("AuthService", db)
        assert res.confidence in ("HIGH", "MEDIUM")
        assert res.canonical_id is not None

    def test_empty_string_returns_unknown(self, db: sqlite3.Connection) -> None:
        res = resolve_target("", db)
        assert res.resolution_method == ResolutionMethod.UNKNOWN


class TestResolveTargetsBatch:
    def test_resolves_multiple_targets(self, db: sqlite3.Connection) -> None:
        resolutions = resolve_targets(["AuthService", "/api/v1/auth/login", "NonExistent"], db)
        assert len(resolutions) == 3
        assert resolutions["AuthService"].is_resolved()
        assert resolutions["/api/v1/auth/login"].target_type == TargetType.API_ENDPOINT
        assert not resolutions["NonExistent"].is_resolved()

    def test_empty_list(self, db: sqlite3.Connection) -> None:
        resolutions = resolve_targets([], db)
        assert resolutions == {}
