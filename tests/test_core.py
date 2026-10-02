from pathlib import Path

import pytest

from codegraph.config import Settings
from codegraph.errors import SecurityError
from codegraph.graph import trace_call
from codegraph.indexing import Indexer
from codegraph.search import search
from codegraph.security import is_sensitive, safe_path


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    (tmp_path / "auth.py").write_text("""from models import User

class AuthService:
    def login(self, email: str):
        return User.find(email)

def login_controller(email):
    return AuthService().login(email)
""")
    (tmp_path / "models.py").write_text("""class User:
    @classmethod
    def find(cls, email):
        return None
""")
    (tmp_path / "routes.ts").write_text("export async function loginRoute() { return login_controller('a') }\n")
    (tmp_path / ".env").write_text("TOKEN=do-not-index")
    return tmp_path


def test_index_search_and_incremental(repository: Path) -> None:
    indexer = Indexer(repository, Settings(max_file_size=100_000))
    assert indexer.index() == {"scanned": 3, "indexed": 3, "unchanged": 0, "removed": 0}
    assert indexer.index()["unchanged"] == 3
    with indexer.session() as con:
        results = search(con, "authentication login")
        assert results and results[0].file == "auth.py"
        assert "do-not-index" not in str(con.execute("SELECT content FROM chunks").fetchall())
        assert any(item["confidence"] == "HIGH" for item in trace_call(con, "login"))


def test_safe_path_blocks_escape_and_sensitive(repository: Path) -> None:
    assert safe_path(repository, "auth.py") == repository / "auth.py"
    with pytest.raises(SecurityError):
        safe_path(repository, "../outside")
    assert is_sensitive(Path(".env"))
    assert is_sensitive(Path("keys/private.pem"))


def test_removed_file_is_pruned(repository: Path) -> None:
    indexer = Indexer(repository)
    indexer.index()
    (repository / "routes.ts").unlink()
    assert indexer.index()["removed"] == 1
    with indexer.session() as con:
        assert con.execute("SELECT count(*) FROM files WHERE path='routes.ts'").fetchone()[0] == 0
