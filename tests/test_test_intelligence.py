"""Regression test suite for Phase 7: Test Intelligence & Deterministic Test Discovery.

Test Matrix:
1. pytest direct function call
2. unittest method
3. Jest test
4. Vitest test
5. Playwright route
6. imported alias target
7. helper-based target
8. fixture relationship
9. route test
10. DI-aware test
11. registry dispatch test
12. event listener test
13. dynamic test target -> UNKNOWN
14. irrelevant lexical test is not falsely linked
15. repeated indexing determinism
"""
from __future__ import annotations

from pathlib import Path

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.graph.traversal import find_related_tests
from codegraph.indexing import Indexer


def test_1_pytest_direct_function_call(tmp_path: Path) -> None:
    prod_code = """
def authenticate(username, password):
    return True
"""
    test_code = """
from service import authenticate

def test_authenticate():
    assert authenticate("alice", "secret") is True
"""
    (tmp_path / "service.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_service.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "service.authenticate")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert "test_service.py" in str(res["file"])
        assert res["classification"] == "VERIFIED_TEST"
        assert res["evidence_class"] == RelationshipEvidenceClass.AST_VERIFIED.value
        assert res["reason"] == "direct_test_call"
        assert res["confidence"] == "HIGH"


def test_2_unittest_method(tmp_path: Path) -> None:
    prod_code = """
class Calculator:
    def add(self, a, b):
        return a + b
"""
    test_code = """
import unittest
from calc import Calculator

class TestCalculator(unittest.TestCase):
    def test_add(self):
        c = Calculator()
        self.assertEqual(c.add(1, 2), 3)
"""
    (tmp_path / "calc.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calc.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "calc.Calculator.add")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert "test_calc.py" in str(res["file"])
        assert res["classification"] == "VERIFIED_TEST"
        assert res["evidence_class"] == RelationshipEvidenceClass.AST_VERIFIED.value


def test_3_jest_test(tmp_path: Path) -> None:
    prod_code = """
export function calculateTax(amount) {
    return amount * 0.2;
}
"""
    test_code = """
import { calculateTax } from "../tax";

test("calculateTax returns correct 20 percent", () => {
    expect(calculateTax(100)).toBe(20);
});
"""
    (tmp_path / "tax.js").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "tax.test.js").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "tax.calculateTax")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert "tax.test.js" in str(res["file"])
        assert res["classification"] == "VERIFIED_TEST"


def test_4_vitest_test(tmp_path: Path) -> None:
    prod_code = """
export function formatCurrency(val: number): string {
    return "$" + val.toFixed(2);
}
"""
    test_code = """
import { formatCurrency } from "../format";

it("formats currency properly", () => {
    formatCurrency(50);
});
"""
    (tmp_path / "format.ts").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "format.spec.ts").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "format.formatCurrency")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert "format.spec.ts" in str(res["file"])


def test_5_playwright_route(tmp_path: Path) -> None:
    prod_code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/dashboard")
def get_dashboard():
    return {"status": "ok"}
"""
    test_code = """
def test_dashboard_ui(page):
    page.goto("/api/dashboard")
"""
    (tmp_path / "app.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_e2e.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "/api/dashboard")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert "test_e2e.py" in str(res["file"])
        assert res["relationship"] == "TESTS_ROUTE"
        assert res["evidence_class"] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
        assert "playwright_goto" in str(res["reason"])


def test_6_imported_alias_target(tmp_path: Path) -> None:
    prod_code = """
def process_payment(amount):
    return True
"""
    test_code = """
from billing import process_payment as pay

def test_payment_flow():
    pay(100)
"""
    (tmp_path / "billing.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_billing.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "billing.process_payment")
        assert len(results) >= 1
        assert "result" not in results[0]
        assert "test_billing.py" in str(results[0]["file"])


def test_7_helper_based_target(tmp_path: Path) -> None:
    prod_code = """
def low_level_call():
    return 42
"""
    test_code = """
from core import low_level_call

def setup_mock_environment():
    return low_level_call()

def test_integration():
    setup_mock_environment()
"""
    (tmp_path / "core.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "core.low_level_call")
        assert len(results) >= 1
        assert "result" not in results[0]
        helper_tests = [r for r in results if r.get("relationship") == "TEST_HELPER_CALL"]
        assert len(helper_tests) >= 1
        assert helper_tests[0]["classification"] == "POSSIBLE_TEST"
        assert "indirect_test_helper" in str(helper_tests[0]["reason"])


def test_8_fixture_relationship(tmp_path: Path) -> None:
    prod_code = """
class PostgresUserRepository:
    def get_user(self):
        return "user"
"""
    test_code = """
import pytest
from repo import PostgresUserRepository

@pytest.fixture
def user_repo():
    return PostgresUserRepository()

def test_repository_access(user_repo):
    pass
"""
    (tmp_path / "repo.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_repo.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "repo.PostgresUserRepository")
        assert len(results) >= 1
        assert "result" not in results[0]
        prov_tests = [r for r in results if r.get("relationship") == "TESTS_PROVIDER"]
        assert len(prov_tests) >= 1
        assert prov_tests[0]["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_9_route_test(tmp_path: Path) -> None:
    prod_code = """
from fastapi import FastAPI

app = FastAPI()

@app.post("/api/v1/login")
def login():
    return {"token": "xyz"}
"""
    test_code = """
def test_login_endpoint(client):
    response = client.post("/api/v1/login")
    assert response.status_code == 200
"""
    (tmp_path / "app.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_api.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "/api/v1/login")
        assert len(results) >= 1
        assert "result" not in results[0]
        res = results[0]
        assert res["relationship"] == "TESTS_ROUTE"
        assert res["evidence_class"] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
        assert "http_client_test" in str(res["reason"])


def test_10_di_aware_test(tmp_path: Path) -> None:
    prod_code = """
class UserRepository:
    pass

class PostgresUserRepository:
    pass

class Container:
    def register(self, iface, impl): pass

container = Container()
container.register(UserRepository, PostgresUserRepository)
"""
    test_code = """
from di import PostgresUserRepository

def test_database_integration():
    repo = PostgresUserRepository()
"""
    (tmp_path / "di.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_di.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Querying the interface UserRepository should find tests covering its concrete provider
        results = find_related_tests(con, "di.UserRepository")
        assert len(results) >= 1
        assert "result" not in results[0]
        assert "test_di.py" in str(results[0]["file"])


def test_11_registry_dispatch_test(tmp_path: Path) -> None:
    prod_code = """
class HandlerRegistry:
    def register(self, key, handler): pass

registry = HandlerRegistry()

def on_backup_task():
    pass

registry.register("backup", on_backup_task)
"""
    test_code = """
class EventBus:
    def emit(self, event): pass

bus = EventBus()

def test_backup_execution():
    bus.emit("backup")
"""
    (tmp_path / "tasks.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_tasks.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "tasks.on_backup_task")
        assert len(results) >= 1
        assert "result" not in results[0]


def test_12_event_listener_test(tmp_path: Path) -> None:
    prod_code = """
class EventBus:
    def on(self, event, handler): pass

bus = EventBus()

def handle_user_registered(data):
    pass

bus.on("user.registered", handle_user_registered)
"""
    test_code = """
from events import bus

def test_user_flow():
    bus.emit("user.registered")
"""
    (tmp_path / "events.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_events.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "events.handle_user_registered")
        assert len(results) >= 1
        assert "result" not in results[0]
        assert results[0]["relationship"] == "TESTS_EVENT_HANDLER"
        assert results[0]["classification"] == "POSSIBLE_TEST"
        assert results[0]["evidence_class"] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value


def test_13_dynamic_test_target_unknown(tmp_path: Path) -> None:
    test_code = """
def test_dynamic(client, page, dynamic_url):
    client.get(dynamic_url)
    page.goto(dynamic_url)
"""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dyn.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Dynamic navigation must not fabricate edges or routes
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE target='<DYNAMIC>' OR relationship='TESTS_ROUTE'"
        ).fetchall()
        assert len(edges) == 0

        # Querying an unknown route returns sentinel
        results = find_related_tests(con, "/nonexistent/route")
        assert len(results) == 1
        assert results[0]["result"] == "no_static_link_found"


def test_14_irrelevant_lexical_test_not_falsely_linked(tmp_path: Path) -> None:
    prod_code = """
def login(user, password):
    return True
"""
    # A test that happens to have 'login' in its name, but does NOT import or call login
    irrelevant_test = """
def test_login_ui_css_styles():
    assert True
"""
    (tmp_path / "auth.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_styles.py").write_text(irrelevant_test, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        results = find_related_tests(con, "auth.login")
        # Must NOT falsely link test_styles.py solely because 'login' is in the test name!
        linked_files = [r.get("file") for r in results if "result" not in r]
        assert not any("test_styles.py" in str(f) for f in linked_files)
        # Should return no_static_link_found sentinel
        assert len(results) == 1
        assert results[0]["result"] == "no_static_link_found"


def test_15_repeated_indexing_determinism(tmp_path: Path) -> None:
    prod_code = """
def run_job():
    return 1
"""
    test_code = """
from job import run_job

def test_job():
    run_job()
"""
    (tmp_path / "job.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_job.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        run1 = find_related_tests(con, "job.run_job")
        edges1 = con.execute("SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target").fetchall()

    # Re-index without changes
    indexer.index()

    with indexer.session() as con:
        run2 = find_related_tests(con, "job.run_job")
        edges2 = con.execute("SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target").fetchall()

    assert run1 == run2
    assert edges1 == edges2
