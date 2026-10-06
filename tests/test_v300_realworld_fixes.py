import tempfile
from pathlib import Path

from codegraph.graph.traversal import find_callees
from codegraph.indexing.indexer import Indexer
from codegraph.indexing.parser import _parse_python, _repair_python_syntax


def test_python_syntax_repair():
    broken = """
try:
    x = 1
except ValueError, TypeError:
    pass
"""
    repaired = _repair_python_syntax(broken)
    assert "except (ValueError, TypeError):" in repaired

    # Check parse succeeds
    res = _parse_python(broken, "sample.py")
    assert not res.parse_failed


def test_fastapi_annotated_di_and_scoping():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        app_dir = root / "app"
        app_dir.mkdir()

        deps_code = """
from typing import Annotated
from fastapi import Depends

def get_db():
    return "db_session"

def get_current_user():
    return "user"

SessionDep = Annotated[str, Depends(get_db)]
CurrentUser = Annotated[str, Depends(get_current_user)]
"""
        (app_dir / "deps.py").write_text(deps_code)

        users_code = """
from fastapi import APIRouter
from app.deps import SessionDep, CurrentUser

router = APIRouter()

@router.post("/users/")
def create_user(session: SessionDep, current_user: CurrentUser):
    return {"status": "ok"}
"""
        (app_dir / "users.py").write_text(users_code)

        private_code = """
from fastapi import APIRouter
from app.deps import SessionDep

router = APIRouter()

@router.post("/private/users")
def create_user(session: SessionDep):
    return {"private": True}
"""
        (app_dir / "private.py").write_text(private_code)

        indexer = Indexer(root)
        indexer.index()

        with indexer.session() as con:
            # 1. Verify get_db is injected into both create_user endpoints
            edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'INJECTS'"
            ).fetchall()
            edge_pairs = [(e["source"], e["target"]) for e in edges]

            # CurrentUser should inject into app.users.create_user, but NOT app.private.create_user
            users_cur_user = any("app.users.create_user" in src and "get_current_user" in tgt for src, tgt in edge_pairs)
            assert users_cur_user, "app.users.create_user should inject get_current_user"

            private_cur_user = any("app.private.create_user" in src and "get_current_user" in tgt for src, tgt in edge_pairs)
            assert not private_cur_user, "app.private.create_user MUST NOT inject get_current_user (no cross-file collision)"

            # Both should inject get_db
            users_db = any("app.users.create_user" in src and "get_db" in tgt for src, tgt in edge_pairs)
            private_db = any("app.private.create_user" in src and "get_db" in tgt for src, tgt in edge_pairs)
            assert users_db
            assert private_db


def test_primitive_tensor_noise_filtered_in_callees():
    # If a call references noisy primitives like .size() or .shape or torch.stack,
    # find_callees should skip them
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_file = root / "model.py"
        src_file.write_text("""
def forward(x):
    s = x.size()
    b = x.shape
    return helper(s)

def helper(v):
    return v
""")
        indexer = Indexer(root)
        indexer.index()

        with indexer.session() as con:
            callees = find_callees(con, "model.forward")
            callee_symbols = [c.callee for c in callees]
            assert "helper" in callee_symbols
            assert "size" not in callee_symbols
            assert "shape" not in callee_symbols
