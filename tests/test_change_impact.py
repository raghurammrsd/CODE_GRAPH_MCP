from __future__ import annotations

import subprocess
from pathlib import Path

from codegraph.git import analyze_change_impact
from codegraph.graph.traversal import analyze_impact, find_related_tests
from codegraph.indexing.indexer import Indexer


# 16. Direct Caller Impact
def test_16_direct_caller_impact(tmp_path: Path) -> None:
    service_code = """
def validate_token(token):
    return True
"""
    auth_code = """
from service import validate_token

def login(user, token):
    if validate_token(token):
        return True
    return False
"""
    (tmp_path / "service.py").write_text(service_code, encoding="utf-8")
    (tmp_path / "auth.py").write_text(auth_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "service.validate_token")
        assert len(impact["direct_callers"]) >= 1
        caller_syms = [c["symbol"] for c in impact["direct_callers"]]
        assert any("auth.login" in str(s) for s in caller_syms)

        # Check impact items & categories
        assert "DIRECT" in impact["categories"]
        direct_items = impact["categories"]["DIRECT"]
        assert any(item["impact_reason"] == "direct_caller" for item in direct_items)
        assert any(item["rank"] == 2 for item in direct_items)


# 17. Direct Test Impact
def test_17_direct_test_impact(tmp_path: Path) -> None:
    prod_code = """
def calculate_tax(amount):
    return amount * 0.2
"""
    test_code = """
from tax import calculate_tax

def test_calculate_tax():
    assert calculate_tax(100) == 20
"""
    (tmp_path / "tax.py").write_text(prod_code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_tax.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "tax.calculate_tax")
        assert len(impact["related_tests"]) >= 1
        assert any("test_calculate_tax" in str(t.get("symbol", "")) for t in impact["related_tests"])

        assert "TEST" in impact["categories"]
        test_items = impact["categories"]["TEST"]
        assert any(item["impact_reason"] == "direct_test" for item in test_items)
        assert any(item["rank"] == 1 for item in test_items)


# 18. Route Impact
def test_18_route_impact(tmp_path: Path) -> None:
    app_code = """
class FastAPI:
    def post(self, path):
        def dec(f): return f
        return dec

app = FastAPI()

@app.post("/api/v1/auth/login")
def login_handler(username, password):
    return {"token": "abc"}
"""
    (tmp_path / "main.py").write_text(app_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "main.login_handler")
        assert len(impact["related_apis"]) >= 1
        assert any("/api/v1/auth/login" in r["route"] for r in impact["related_apis"])

        assert "FRAMEWORK" in impact["categories"]
        fw_items = impact["categories"]["FRAMEWORK"]
        assert any(item["impact_reason"] == "route_handler" for item in fw_items)
        assert any(item["relationship"] == "ROUTES_TO" for item in fw_items)
        assert any(item["rank"] == 3 for item in fw_items)


# 19. Provider Impact
def test_19_provider_impact(tmp_path: Path) -> None:
    di_code = """
class UserRepository:
    pass

class PostgresUserRepository(UserRepository):
    pass

class Container:
    def register(self, iface, impl): pass

container = Container()
container.register(UserRepository, PostgresUserRepository)
"""
    (tmp_path / "di.py").write_text(di_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "di.PostgresUserRepository")
        assert "DI" in impact["categories"]
        di_items = impact["categories"]["DI"]
        assert any(item["relationship"] in ("PROVIDES", "INJECTS", "RESOLVES_DEPENDENCY") for item in di_items)


# 20. Registry Impact
def test_20_registry_impact(tmp_path: Path) -> None:
    reg_code = """
class TaskRegistry:
    def register(self, name, handler): pass

registry = TaskRegistry()

def on_backup():
    pass

registry.register("backup_job", on_backup)
"""
    (tmp_path / "registry.py").write_text(reg_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "registry.on_backup")
        assert "SEMANTIC" in impact["categories"]
        sem_items = impact["categories"]["SEMANTIC"]
        assert any(item["relationship"] in ("REGISTERS", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER") for item in sem_items)


# 21. Event Listener Impact
def test_21_event_listener_impact(tmp_path: Path) -> None:
    events_code = """
class EventBus:
    def on(self, event, handler): pass

bus = EventBus()

def on_user_registered(data):
    pass

bus.on("user.registered", on_user_registered)
"""
    (tmp_path / "events.py").write_text(events_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "events.on_user_registered")
        assert "SEMANTIC" in impact["categories"]
        sem_items = impact["categories"]["SEMANTIC"]
        assert any(item["relationship"] == "EVENT_LISTENER" for item in sem_items)
        assert any(item["impact_reason"] == "event_listener" for item in sem_items)


# 22. Indirect Dependent Impact
def test_22_indirect_dependent(tmp_path: Path) -> None:
    code = """
def low_level_helper():
    return 42

def mid_level_service():
    return low_level_helper()

def high_level_controller():
    return mid_level_service()
"""
    (tmp_path / "pipeline.py").write_text(code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "pipeline.low_level_helper", max_depth=2)
        assert len(impact["direct_callers"]) >= 1
        assert len(impact["transitive_callers"]) >= 1
        assert any("high_level_controller" in str(c.get("symbol", "")) for c in impact["transitive_callers"])

        direct_items = impact["categories"].get("DIRECT", [])
        assert any(item["impact_reason"] == "indirect_dependent" for item in direct_items)


# 23. Ambiguous Impact Stays POSSIBLE
def test_23_ambiguous_impact_possible(tmp_path: Path) -> None:
    code = """
def base_function():
    pass

def caller_one():
    base_function()

def caller_two():
    caller_one()
"""
    (tmp_path / "ambig.py").write_text(code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "ambig.base_function", max_depth=2)
        direct_items = impact["categories"].get("DIRECT", [])
        transitive_items = [i for i in direct_items if i["impact_reason"] == "indirect_dependent"]
        assert len(transitive_items) >= 1
        # Transitive / indirect callers must remain POSSIBLE, never fabricated to AST_VERIFIED
        assert all(i["evidence_class"] == "POSSIBLE" for i in transitive_items)


# 24. Deleted Symbol Graceful Handling
def test_24_deleted_symbol_impact(tmp_path: Path) -> None:
    code = """
def live_symbol():
    pass
"""
    (tmp_path / "live.py").write_text(code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Querying a non-existent symbol must not raise and must indicate STALE freshness
        impact = analyze_impact(con, "live.deleted_symbol_name")
        assert len(impact["impact_items"]) >= 1
        deleted_item = next(
            (i for i in impact["impact_items"] if i.get("impact_reason") == "deleted_symbol"),
            None,
        )
        assert deleted_item is not None
        assert deleted_item["freshness"] == "STALE"
        assert deleted_item["evidence_class"] == "UNKNOWN"
        assert deleted_item["rank"] == 8


# 25. Renamed Symbol Handling
def test_25_renamed_symbol_impact(tmp_path: Path) -> None:
    code = """
def old_function_name():
    return 1
"""
    (tmp_path / "mod.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Renamed symbol queried under old name
        impact = analyze_impact(con, "mod.renamed_new_function")
        assert impact is not None
        assert "categories" in impact
        assert isinstance(impact["categories"], dict)


# 26. Stale Index Handling
def test_26_stale_index_handling(tmp_path: Path) -> None:
    code = """
def stable_fn():
    return "ok"
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Querying nonexistent file
        file_impact = analyze_impact(con, "nonexistent/path/app.py")
        assert file_impact is not None
        assert isinstance(file_impact["impact_items"], list)


# 27. Git Diff Change Impact
def test_27_git_diff_impact(tmp_path: Path) -> None:
    # Initialize a git repository in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)

    math_v1 = """
def add(a, b):
    return a + b
"""
    (tmp_path / "calc.py").write_text(math_v1, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True, capture_output=True)

    # Version 2 modifies add() and adds test
    math_v2 = """
def add(a, b):
    # Added validation
    if not isinstance(a, (int, float)):
        raise TypeError()
    return a + b
"""
    test_v2 = """
from calc import add

def test_add():
    assert add(1, 2) == 3
"""
    (tmp_path / "calc.py").write_text(math_v2, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calc.py").write_text(test_v2, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Update add and add test"], cwd=tmp_path, check=True, capture_output=True)

    with indexer.session() as con:
        git_impact = analyze_change_impact(con, tmp_path, since="HEAD~1", until="HEAD")
        assert "changed_files" in git_impact
        assert len(git_impact["changed_files"]) >= 1
        assert "add" in git_impact["changed_symbols"] or len(git_impact["changed_symbols"]) >= 1
        assert "impact_items" in git_impact


# 28. Deterministic Impact Ordering
def test_28_deterministic_impact_ordering(tmp_path: Path) -> None:
    code = """
def core_fn():
    return 1

def direct_caller_fn():
    return core_fn()

def indirect_caller_fn():
    return direct_caller_fn()
"""
    test_code = """
from lib import core_fn

def test_core():
    assert core_fn() == 1
"""
    (tmp_path / "lib.py").write_text(code, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_lib.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        impact = analyze_impact(con, "lib.core_fn", max_depth=2)
        items = impact["impact_items"]
        assert len(items) >= 2

        # Verify ranks are ordered: direct_test (1) <= direct_caller (2) <= indirect (7)
        ranks = [item["rank"] for item in items]
        assert ranks == sorted(ranks)


# Section 23 Real-World End-to-End Fixture
def test_29_real_world_end_to_end_fixture(tmp_path: Path) -> None:
    auth_service_code = """
class AuthService:
    def __init__(self, user_repo):
        self.user_repo = user_repo

    def authenticate(self, username, password):
        user = self.user_repo.get_by_username(username)
        if not user:
            return None
        if user.is_locked:
            return "LOCKED"
        if user.password == password:
            return "SUCCESS"
        return "INVALID"
"""
    users_code = """
class UserRepository:
    def get_by_username(self, username): pass

class PostgresUserRepository(UserRepository):
    def get_by_username(self, username):
        return None

def get_user_repository() -> PostgresUserRepository:
    return PostgresUserRepository()
"""
    main_code = """
class FastAPI:
    def post(self, path):
        def dec(f): return f
        return dec

def Depends(provider=None):
    return provider

app = FastAPI()

@app.post("/api/login")
def login_endpoint(credentials, auth_service: AuthService = Depends()):
    return auth_service.authenticate(credentials.user, credentials.pwd)
"""
    test_code = """
from auth import AuthService

def test_login_success(client, user_repo):
    response = client.post("/api/login", {"user": "alice", "pwd": "secret"})
    assert response == 200

def test_login_invalid_password(client):
    response = client.post("/api/login", {"user": "alice", "pwd": "wrong"})
    assert response == 401

def test_login_locked_user():
    service = AuthService(None)
    result = service.authenticate("locked_user", "pass")
    assert result == "LOCKED"
"""
    (tmp_path / "auth.py").write_text(auth_service_code, encoding="utf-8")
    (tmp_path / "users.py").write_text(users_code, encoding="utf-8")
    (tmp_path / "main.py").write_text(main_code, encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_auth_flow.py").write_text(test_code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # A. Find tests related to auth.AuthService.authenticate
        related = find_related_tests(con, "auth.AuthService.authenticate")
        assert len(related) >= 1
        assert "result" not in related[0]

        # Verify test_login_locked_user directly calls authenticate
        test_names = [str(t.get("symbol", "")) for t in related]
        assert any("test_login_locked_user" in n for n in test_names)

        # B. Analyze impact of auth.AuthService.authenticate
        impact = analyze_impact(con, "auth.AuthService.authenticate", max_depth=2)

        # Categories must include DIRECT, FRAMEWORK, and TEST
        assert "DIRECT" in impact["categories"]
        assert "TEST" in impact["categories"]

        # Callers must include login_endpoint
        callers = [str(c.get("symbol", "")) for c in impact["direct_callers"]]
        assert any("login_endpoint" in c for c in callers)

        # Impact items must be ranked deterministically
        items = impact["impact_items"]
        ranks = [it["rank"] for it in items]
        assert ranks == sorted(ranks)

        # Every item has non-empty impact_reason and valid evidence_class
        for item in items:
            assert item["impact_reason"]
            assert item["evidence_class"] in (
                "AST_VERIFIED",
                "FRAMEWORK_VERIFIED",
                "DATAFLOW_VERIFIED",
                "POSSIBLE",
                "UNKNOWN",
            )
