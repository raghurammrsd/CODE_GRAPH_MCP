"""v2.1 Query Expansion regression tests."""
from __future__ import annotations

import sqlite3

import pytest

from codegraph.query_expansion import QueryExpansion, expand_query_terms, get_search_queries


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
          ('admin.AdminDashboardView.get','admin.AdminDashboardView.get',
           'admin.AdminDashboardView.get','get','method',
           'src/admin_panel/views.py',10,30,'admin.AdminDashboardView','admin','AdminDashboardView',
           'python','','hash','public',NULL,0,'',NULL),
          ('auth.AuthService','auth.AuthService','auth.AuthService','AuthService','class',
           'src/services/auth_service.py',10,100,NULL,'auth','','python','','hash2','public',NULL,0,'',NULL),
          ('auth.AuthService.login','auth.AuthService.login','auth.AuthService.login','login','method',
           'src/services/auth_service.py',20,40,'auth.AuthService','auth','AuthService','python','','hash3',
           'public',NULL,1,'',NULL);
        INSERT INTO framework_routes VALUES
          (1,'/api/v1/auth/login','POST','login_route','src/api/fastapi_app.py',30,'ep_auth_login','Decorator');
    """)
    return con


class TestGenericMethodQualification:
    def test_generic_get_qualified(self, db: sqlite3.Connection) -> None:
        """'get' is generic — must be expanded to qualified form AdminDashboardView.get."""
        expansions = expand_query_terms(["get"], db)
        expanded_terms = [e.expanded_term for e in expansions]
        # Must NOT emit bare 'get' as a search query
        assert "get" not in expanded_terms
        # Must emit the qualified form (found in DB)
        assert any("AdminDashboardView.get" in t or "admin.AdminDashboardView.get" in t
                   for t in expanded_terms)

    def test_generic_post_suppressed(self, db: sqlite3.Connection) -> None:
        """'post' is generic and not in DB — must not be emitted."""
        expansions = expand_query_terms(["post"], db)
        expanded_terms = [e.expanded_term for e in expansions]
        assert "post" not in expanded_terms

    def test_generic_login_qualified_via_route(self, db: sqlite3.Connection) -> None:
        """'login' is generic — if route exists, expand to handler."""
        # login itself is in DB as a method
        expansions = expand_query_terms(["login"], db)
        [e.expanded_term for e in expansions]
        # 'login' is generic — should be suppressed or qualified
        # The bare 'login' should not be the only result
        assert len(expansions) == 0 or all(
            e.qualification_level in ("CANONICAL", "QUALIFIED", "ROUTE") for e in expansions
        )


class TestExactCanonicalExpansion:
    def test_auth_service_expands_to_canonical(self, db: sqlite3.Connection) -> None:
        expansions = expand_query_terms(["AuthService"], db)
        assert len(expansions) >= 1
        assert any(e.qualification_level in ("CANONICAL", "QUALIFIED", "SHORT", "LEXICAL")
                   for e in expansions)
        # canonical_id should be in expanded terms
        terms = [e.expanded_term for e in expansions]
        assert any("AuthService" in t for t in terms)

    def test_qualified_name_expansion(self, db: sqlite3.Connection) -> None:
        expansions = expand_query_terms(["auth.AuthService.login"], db)
        terms = [e.expanded_term for e in expansions]
        assert any("auth.AuthService.login" in t for t in terms)


class TestRouteExpansion:
    def test_route_expands_to_handler(self, db: sqlite3.Connection) -> None:
        expansions = expand_query_terms(["/api/v1/auth/login"], db)
        terms = [e.expanded_term for e in expansions]
        # Route expansion should include the handler name
        assert any("login_route" in t or "/api/v1/auth/login" in t for t in terms)

    def test_route_level_is_route(self, db: sqlite3.Connection) -> None:
        expansions = expand_query_terms(["/api/v1/auth/login"], db)
        route_expansions = [e for e in expansions if e.qualification_level == "ROUTE"]
        assert len(route_expansions) >= 1


class TestNonGenericPassthrough:
    def test_auth_service_not_generic(self, db: sqlite3.Connection) -> None:
        """AuthService is not a generic name — should be passed through."""
        expansions = expand_query_terms(["AuthService"], db)
        terms = [e.expanded_term for e in expansions]
        # Should have at least one result referencing AuthService
        assert any("AuthService" in t for t in terms)

    def test_payment_service_passthrough(self, db: sqlite3.Connection) -> None:
        """PaymentService not in DB — should still expand as LEXICAL."""
        expansions = expand_query_terms(["PaymentService"], db)
        terms = [e.expanded_term for e in expansions]
        assert "PaymentService" in terms


class TestGetSearchQueries:
    def test_deduplicates_queries(self, db: sqlite3.Connection) -> None:
        expansions = [
            QueryExpansion("a", "x.Y", "reason1", "x.Y", "CANONICAL", "HIGH"),
            QueryExpansion("a", "x.Y", "reason2", "x.Y", "QUALIFIED", "HIGH"),
            QueryExpansion("b", "x.Z", "reason3", "x.Z", "CANONICAL", "HIGH"),
        ]
        queries = get_search_queries(expansions)
        assert len(queries) == 2
        assert queries == ["x.Y", "x.Z"]
