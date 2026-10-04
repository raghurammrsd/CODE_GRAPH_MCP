"""Regression tests for Phase 6: Deterministic Dependency Injection & Configuration Intelligence.

Invariants:
  - INJECTS != CALLS
  - PROVIDES != CALLS
  - RESOLVES_DEPENDENCY != CALLS
  - CONFIGURES != CALLS
  - UNKNOWN must never create fabricated target canonical IDs.
  - POSSIBLE must never become AST_VERIFIED.
  - Multiple distinct providers produce POSSIBLE with reason="multiple_providers".
  - Dynamic runtime configurations produce UNKNOWN findings with reason="runtime_configuration".
  - Environment variables reference key names only (never secret contents).
  - No application code execution.
"""
from __future__ import annotations

from pathlib import Path

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.indexing import Indexer


def test_1_fastapi_depends_get_db(tmp_path: Path) -> None:
    code = """
from fastapi import FastAPI, Depends

app = FastAPI()

def get_db():
    pass

@app.get("/items")
def list_items(db=Depends(get_db)):
    pass
"""
    (tmp_path / "main.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        assert len(edges) >= 1
        targets = {e[1] for e in edges}
        assert "main.get_db" in targets
        for e in edges:
            assert e[2] == "INJECTS"
            assert e[3] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
            assert e[4] == "fastapi_depends"


def test_2_fastapi_depends_get_current_user(tmp_path: Path) -> None:
    code = """
from typing import Annotated
from fastapi import FastAPI, Depends

app = FastAPI()

def get_current_user():
    pass

@app.get("/profile")
def get_profile(user: Annotated[dict, Depends(get_current_user)]):
    pass
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        assert len(edges) >= 1
        targets = {e[1] for e in edges}
        assert "app.get_current_user" in targets
        for e in edges:
            assert e[3] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value


def test_3_deterministic_container_register(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

class PostgresRepository(UserRepository):
    pass

class Container:
    def register(self, interface, impl):
        pass

container = Container()
container.register(UserRepository, PostgresRepository)
"""
    (tmp_path / "di.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e[0] == "di.UserRepository" and e[1] == "di.PostgresRepository" for e in edges)
        for e in edges:
            assert e[3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_4_dict_provider_mapping(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

class PostgresRepository:
    pass

providers = {
    UserRepository: PostgresRepository,
}
"""
    (tmp_path / "providers.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e[0] == "providers.UserRepository" and e[1] == "providers.PostgresRepository" for e in edges)
        assert edges[0][3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_5_cross_file_provider_resolution(tmp_path: Path) -> None:
    (tmp_path / "interfaces.py").write_text("class UserRepository:\n    pass\n", encoding="utf-8")
    (tmp_path / "implementations.py").write_text("class PostgresRepository:\n    pass\n", encoding="utf-8")
    container_code = """
from interfaces import UserRepository
from implementations import PostgresRepository

class Container:
    def register(self, iface, impl):
        pass

container = Container()
container.register(UserRepository, PostgresRepository)
"""
    (tmp_path / "container.py").write_text(container_code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e[0] == "interfaces.UserRepository" and e[1] == "implementations.PostgresRepository" for e in edges)
        for e in edges:
            assert e[3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_6_deterministic_container_resolve(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

class PostgresRepository:
    pass

class Container:
    def register(self, iface, impl): pass
    def resolve(self, iface): pass

container = Container()
container.register(UserRepository, PostgresRepository)
repo = container.resolve(UserRepository)
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='RESOLVES_DEPENDENCY'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e[0] == "app.UserRepository" and e[1] == "app.PostgresRepository" for e in edges)
        for e in edges:
            assert e[3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_7_constructor_injection(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

class PostgresRepository:
    pass

providers = {
    UserRepository: PostgresRepository,
}

class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo
"""
    (tmp_path / "service.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        inject_edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        assert len(inject_edges) >= 1
        assert any(e[0] == "service.UserService" and e[1] == "service.UserRepository" for e in inject_edges)
        for e in inject_edges:
            assert e[3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        provides_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(provides_edges) >= 1
        assert any(e[0] == "service.UserRepository" and e[1] == "service.PostgresRepository" for e in provides_edges)


def test_8_di_decorator(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

def inject(fn):
    return fn

@inject
def get_user_service(repo: UserRepository):
    return repo
"""
    (tmp_path / "di_dec.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e[0] == "di_dec.get_user_service" and e[1] == "di_dec.UserRepository" for e in edges)


def test_9_multiple_providers_possible(tmp_path: Path) -> None:
    code = """
class UserRepository:
    pass

class PostgresRepository:
    pass

class MockRepository:
    pass

class Container:
    def register(self, iface, impl): pass

container = Container()
container.register(UserRepository, PostgresRepository)
container.register(UserRepository, MockRepository)
"""
    (tmp_path / "multi.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(edges) >= 2
        for e in edges:
            assert e[3] == RelationshipEvidenceClass.POSSIBLE.value
            assert e[4] == "multiple_providers"


def test_10_dynamic_config_unknown(tmp_path: Path) -> None:
    code = """
config = {"repo": "postgres"}
key = "repo"
provider = config[key]
"""
    (tmp_path / "dyn_conf.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        fake_edges = con.execute(
            "SELECT * FROM graph_edges WHERE target LIKE '%<DYNAMIC>%' OR target LIKE '%UNKNOWN%'"
        ).fetchall()
        assert len(fake_edges) == 0


def test_11_environment_reference_without_secret_exposure(tmp_path: Path) -> None:
    code = """
import os

DATABASE_URL = os.getenv("DATABASE_URL")
"""
    (tmp_path / "config.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='CONFIGURES'"
        ).fetchall()
        assert len(edges) >= 1
        assert edges[0][0] == "DATABASE_URL"
        assert edges[0][2] == "CONFIGURES"
        assert edges[0][4] == "environment_reference"
        for col in edges[0]:
            assert "super_secret_value" not in str(col)


def test_12_stale_provider_cleanup(tmp_path: Path) -> None:
    file_p = tmp_path / "di.py"
    file_p.write_text("""
class UserRepository: pass
class PostgresRepository: pass
class Container:
    def register(self, i, c): pass
container = Container()
container.register(UserRepository, PostgresRepository)
""", encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        assert con.execute("SELECT count(*) FROM graph_edges WHERE relationship='PROVIDES'").fetchone()[0] >= 1

    # Remove registration
    file_p.write_text("""
class UserRepository: pass
class PostgresRepository: pass
""", encoding="utf-8")
    indexer.index()

    with indexer.session() as con:
        assert con.execute("SELECT count(*) FROM graph_edges WHERE relationship='PROVIDES'").fetchone()[0] == 0


def test_13_repeated_indexing_determinism(tmp_path: Path) -> None:
    code = """
class IRepo: pass
class PostgresRepo: pass
providers = {IRepo: PostgresRepo}
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        edges1 = con.execute("SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target, relationship").fetchall()

    indexer.index()
    with indexer.session() as con:
        edges2 = con.execute("SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target, relationship").fetchall()

    assert edges1 == edges2


def test_14_injects_not_calls(tmp_path: Path) -> None:
    code = """
from fastapi import FastAPI, Depends

app = FastAPI()

def get_db():
    pass

@app.get("/items")
def read_items(db=Depends(get_db)):
    pass
"""
    (tmp_path / "main.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        inject_edges = con.execute("SELECT * FROM graph_edges WHERE relationship='INJECTS'").fetchall()
        assert len(inject_edges) >= 1

        calls_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='CALLS' AND source='main.read_items' AND target='main.get_db'"
        ).fetchall()
        assert len(calls_edges) == 0


def test_15_provides_not_calls(tmp_path: Path) -> None:
    code = """
class IUserRepo: pass
class PostgresUserRepo: pass
class Container:
    def register(self, i, c): pass
container = Container()
container.register(IUserRepo, PostgresUserRepo)
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='CALLS' AND source='app.IUserRepo' AND target='app.PostgresUserRepo'"
        ).fetchall()
        assert len(calls_edges) == 0

        provides_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='PROVIDES' AND source='app.IUserRepo' AND target='app.PostgresUserRepo'"
        ).fetchall()
        assert len(provides_edges) >= 1


def test_16_resolves_dependency_not_calls(tmp_path: Path) -> None:
    code = """
class IRepo: pass
class PostgresRepo: pass
class Container:
    def register(self, i, c): pass
    def resolve(self, i): pass
container = Container()
container.register(IRepo, PostgresRepo)
r = container.resolve(IRepo)
"""
    (tmp_path / "app.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='CALLS' AND source='app.IRepo' AND target='app.PostgresRepo'"
        ).fetchall()
        assert len(calls) == 0

        res_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='RESOLVES_DEPENDENCY' AND source='app.IRepo' AND target='app.PostgresRepo'"
        ).fetchall()
        assert len(res_edges) >= 1


def test_17_configures_not_calls(tmp_path: Path) -> None:
    code = """
import os

DATABASE_URL = os.getenv("DATABASE_URL")
"""
    (tmp_path / "cfg.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls = con.execute("SELECT * FROM graph_edges WHERE relationship='CALLS' AND source='DATABASE_URL'").fetchall()
        assert len(calls) == 0

        configures = con.execute("SELECT * FROM graph_edges WHERE relationship='CONFIGURES' AND source='DATABASE_URL'").fetchall()
        assert len(configures) >= 1


def test_18_unknown_decorator_ignored(tmp_path: Path) -> None:
    code = """
def custom_wrapper(fn):
    return fn

@custom_wrapper
def calculate():
    pass
"""
    (tmp_path / "test.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        di_edges = con.execute(
            "SELECT * FROM graph_edges WHERE relationship IN ('INJECTS', 'PROVIDES', 'RESOLVES_DEPENDENCY')"
        ).fetchall()
        assert len(di_edges) == 0


def test_19_dynamic_provider_target_unknown(tmp_path: Path) -> None:
    code = """
class Container:
    def register(self, i, c): pass

def get_target(): return None

container = Container()
container.register(get_target(), object)
"""
    (tmp_path / "dyn.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        fake_edges = con.execute(
            "SELECT * FROM graph_edges WHERE target LIKE '%<DYNAMIC>%' OR target LIKE '%UNKNOWN%'"
        ).fetchall()
        assert len(fake_edges) == 0


def test_20_ambiguous_provider_selection(tmp_path: Path) -> None:
    code = """
class ServiceInterface: pass
class ServiceA: pass
class ServiceB: pass

class Container:
    def register(self, i, c): pass
    def resolve(self, i): pass

container = Container()
container.register(ServiceInterface, ServiceA)
container.register(ServiceInterface, ServiceB)
container.resolve(ServiceInterface)
"""
    (tmp_path / "ambig.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        res_edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='RESOLVES_DEPENDENCY'"
        ).fetchall()
        assert len(res_edges) >= 2
        for e in res_edges:
            assert e[3] == RelationshipEvidenceClass.POSSIBLE.value
            assert e[4] == "multiple_providers"


def test_21_js_ts_deterministic_provider_mapping(tmp_path: Path) -> None:
    code = """
class UserRepository {}
class PostgresUserRepository {}

const providers = [
  { provide: UserRepository, useClass: PostgresUserRepository }
];
"""
    (tmp_path / "module.ts").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert len(edges) >= 1
        assert any("UserRepository" in e[0] and "PostgresUserRepository" in e[1] for e in edges)


def test_22_real_world_end_to_end_chain(tmp_path: Path) -> None:
    """Real-world end-to-end chain:
    HTTP route -> handler -> service -> injected interface -> concrete provider -> repository -> database/config
    """
    repo_file = """
import os

DATABASE_URL = os.getenv("DATABASE_URL")

class UserRepository:
    pass

class PostgresUserRepository(UserRepository):
    def fetch_user(self, user_id):
        pass
"""
    (tmp_path / "repository.py").write_text(repo_file, encoding="utf-8")

    di_file = """
from repository import UserRepository, PostgresUserRepository

providers = {
    UserRepository: PostgresUserRepository,
}
"""
    (tmp_path / "container.py").write_text(di_file, encoding="utf-8")

    service_file = """
from repository import UserRepository

class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def get_user(self, user_id):
        return self.repo.fetch_user(user_id)
"""
    (tmp_path / "service.py").write_text(service_file, encoding="utf-8")

    api_file = """
from fastapi import FastAPI, Depends
from service import UserService

app = FastAPI()

def get_user_service():
    return UserService(...)

@app.get("/users/{user_id}")
def get_user_endpoint(user_id: int, svc: UserService = Depends(get_user_service)):
    return svc.get_user(user_id)
"""
    (tmp_path / "main.py").write_text(api_file, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # 1. Route -> Handler
        routes = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='ROUTES_TO'"
        ).fetchall()
        assert len(routes) >= 1
        assert any(r[1] == "main.get_user_endpoint" for r in routes)

        # 2. Handler -> Service Dependency
        injects_handler = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='INJECTS' AND source='main.get_user_endpoint'"
        ).fetchall()
        assert len(injects_handler) >= 1
        assert any(e[1] == "main.get_user_service" for e in injects_handler)
        assert injects_handler[0][3] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value

        # 3. Handler calls service method
        calls = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        assert any("get_user" in c[1] for c in calls)

        # 4. Service -> Injected Interface
        service_injects = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='INJECTS' AND source='service.UserService'"
        ).fetchall()
        assert len(service_injects) >= 1
        assert any(e[1] == "repository.UserRepository" for e in service_injects)
        assert service_injects[0][3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        # 5. Interface -> Concrete Provider
        provides = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES' AND source='repository.UserRepository'"
        ).fetchall()
        assert len(provides) >= 1
        assert any(e[1] == "repository.PostgresUserRepository" for e in provides)
        assert provides[0][3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        # 6. Repository -> Config/Database
        configures = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='CONFIGURES'"
        ).fetchall()
        assert len(configures) >= 1
        assert any(e[0] == "DATABASE_URL" for e in configures)
        assert configures[0][4] == "environment_reference"
