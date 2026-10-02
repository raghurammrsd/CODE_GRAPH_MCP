from __future__ import annotations

from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.resolver import ReferenceResolver, resolve_module_to_path


def test_resolve_module_to_path_resolution() -> None:
    """Verify deterministic module-to-file path resolution without guessing outside repo."""
    known = {
        "src/auth/service.py",
        "src/auth/__init__.py",
        "src/utils/helpers.ts",
        "src/utils/index.ts",
        "core/database.py",
    }

    # Relative resolution from src/api.py
    assert resolve_module_to_path("./auth/service", "src/api.py", known) == "src/auth/service.py"
    assert resolve_module_to_path("./utils", "src/api.py", known) == "src/utils/index.ts"

    # Dotted absolute-style resolution from repo root
    assert resolve_module_to_path("core.database", "src/api.py", known) == "core/database.py"

    # External package (not in known files) -> None
    assert resolve_module_to_path("requests", "src/api.py", known) is None
    assert resolve_module_to_path("react", "src/components.tsx", known) is None


def test_alias_and_call_resolution_through_indexer(tmp_path: Path) -> None:
    """Verify import aliases (e.g. import auth as auth_service; auth_service.login_user()) are resolved to canonical symbols."""
    auth_file = tmp_path / "auth.py"
    auth_file.write_text("""
def login_user(username):
    return f"logged in {username}"
""")

    client_file = tmp_path / "client.py"
    client_file.write_text("""
import auth as auth_service

def run():
    return auth_service.login_user("alice")
""")

    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res["indexed"] == 2

    with indexer.session() as con:
        # Check graph edges for CALLS
        calls = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        assert len(calls) >= 1
        call_targets = {c["target"] for c in calls}
        assert any("login_user" in t for t in call_targets)


def test_reexport_chain_resolution(tmp_path: Path) -> None:
    """Verify multi-hop re-export chains: C imports from B, B re-exports from A."""
    (tmp_path / "backend").mkdir()

    (tmp_path / "backend" / "base.py").write_text("""
def core_calculator(x, y):
    return x + y
""")

    (tmp_path / "backend" / "facade.py").write_text("""
from .base import core_calculator
""")

    (tmp_path / "main.py").write_text("""
from backend.facade import core_calculator

def main():
    return core_calculator(2, 3)
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Verify diagnostic lookup finds the definition
        diag = ReferenceResolver.resolve_symbol_diagnostic(con, "core_calculator")
        assert diag["input"] == "core_calculator"
        assert diag["resolved_symbol"] == "core_calculator"
        assert "core_calculator" in diag["canonical_id"]


def test_inheritance_relationship_resolution(tmp_path: Path) -> None:
    """Verify class inheritance emits EXTENDS edges in the graph."""
    (tmp_path / "models.py").write_text("""
class BaseModel:
    def save(self):
        pass

class User(BaseModel):
    def update_name(self, name):
        self.save()
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        extends_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='EXTENDS'"
        ).fetchall()
        assert len(extends_edges) >= 1
        edge = extends_edges[0]
        assert "User" in edge["source"]
        assert "BaseModel" in edge["target"]
