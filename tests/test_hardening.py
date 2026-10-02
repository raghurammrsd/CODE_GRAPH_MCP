from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.agent import answer_question
from codegraph.cli import app
from codegraph.config import Settings
from codegraph.errors import SecurityError
from codegraph.evidence import Evidence
from codegraph.graph import import_edges, trace_call
from codegraph.indexing import Indexer
from codegraph.indexing.parser import parse_symbols
from codegraph.indexing.scanner import scan
from codegraph.llm import LLMProvider, ProviderError
from codegraph.llm.context import assemble_context
from codegraph.memory import MemoryStore
from codegraph.search import search, status
from codegraph.security import safe_path


@pytest.fixture()
def realistic_repo(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("ignored.py\ngenerated/\n*.generated.ts\n")
    (tmp_path / "auth.py").write_text(
        """import os
from models import User

class AuthService:
    def login(self, email: str) -> User | None:
        return User.find(email)

def login_controller(email: str):
    return AuthService().login(email)
"""
    )
    (tmp_path / "models.py").write_text("class User:\n    @classmethod\n    def find(cls, email): return None\n")
    (tmp_path / "ui.js").write_text("import { login } from './auth'; export function render() { return login() }\nclass Panel {}\n")
    (tmp_path / "routes.ts").write_text("import { render } from './ui'; export async function loginRoute() { return render() }\ninterface Session { id: string }\n")
    (tmp_path / "ignored.py").write_text("def hidden(): pass\n")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "build.py").write_text("def hidden_build(): pass\n")
    (tmp_path / "secret.env.local").write_text("TOKEN=must-not-leak")
    (tmp_path / "credentials.json").write_text('{"token":"must-not-leak"}')
    (tmp_path / "key.pem").write_text("PRIVATE KEY")
    (tmp_path / "blob.py").write_bytes(b"\0not source")
    (tmp_path / "large.py").write_text("x" * 2048)
    return tmp_path


def test_scanner_gitignore_size_binary_and_secrets(realistic_repo: Path) -> None:
    items = scan(realistic_repo, max_file_size=1000)
    assert [item.relative_path.as_posix() for item in items] == ["auth.py", "models.py", "routes.ts", "ui.js"]


@pytest.mark.parametrize("candidate", ["../outside", "%2e%2e/outside", "/tmp/outside", "nested/%2e%2e/%2e%2e/outside"])
def test_path_security_rejects_escapes(realistic_repo: Path, candidate: str) -> None:
    with pytest.raises(SecurityError):
        safe_path(realistic_repo, candidate)


def test_path_security_rejects_symlink_escape(realistic_repo: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret")
    (realistic_repo / "linked.py").symlink_to(outside)
    with pytest.raises(SecurityError):
        safe_path(realistic_repo, "linked.py")


def test_parsers_cover_languages(realistic_repo: Path) -> None:
    py_symbols, py_imports = parse_symbols((realistic_repo / "auth.py").read_text(), "python", "auth.py")
    js_symbols, js_imports = parse_symbols((realistic_repo / "ui.js").read_text(), "javascript", "ui.js")
    ts_symbols, ts_imports = parse_symbols((realistic_repo / "routes.ts").read_text(), "typescript", "routes.ts")
    assert {item.qualified_name for item in py_symbols} >= {"AuthService", "AuthService.login", "login_controller"}
    assert py_imports == ["os", "models"]
    assert {item.name for item in js_symbols} >= {"render", "Panel"}
    assert js_imports == ["./auth"]
    assert "loginRoute" in {item.name for item in ts_symbols}
    assert "Session" in {item.name for item in ts_symbols}  # Phase 2: TypeScript interfaces now extracted
    assert ts_imports == ["./ui"]


def test_incremental_persistence_updates_and_removes(realistic_repo: Path) -> None:
    indexer = Indexer(realistic_repo, Settings(max_file_size=1000))
    assert indexer.index()["indexed"] == 4
    assert indexer.index()["unchanged"] == 4
    auth = realistic_repo / "auth.py"
    auth.write_text(auth.read_text() + "\ndef logout(): return True\n")
    result = indexer.index()
    assert result["indexed"] == 1 and result["unchanged"] == 3
    with indexer.session() as con:
        assert search(con, "logout")[0].symbol == "logout"
    (realistic_repo / "ui.js").unlink()
    assert indexer.index()["removed"] == 1
    con = sqlite3.connect(indexer.db_path)
    try:
        assert con.execute("SELECT count(*) FROM files WHERE path='ui.js'").fetchone()[0] == 0
    finally:
        con.close()


def test_search_evidence_graph_and_semantic_fallback(realistic_repo: Path) -> None:
    indexer = Indexer(realistic_repo, Settings(max_file_size=1000))
    indexer.index()
    with indexer.session() as con:
        result = search(con, "authentication login", 5)
        assert result and result[0].file == "auth.py"
        assert result[0].start_line <= result[0].end_line
        assert "must-not-leak" not in str(result)
        traces = trace_call(con, "login")
        assert all(item["confidence"] in {"HIGH", "LOW"} for item in traces)
        edge = import_edges(con)[0]
        assert edge.relationship == "IMPORTS" and edge.confidence == "HIGH"
    assert not status(None).available
    evidence = Evidence("auth.py", 4, 6, "AuthService.login", "def login")
    assert evidence.as_dict()["start_line"] == 4


class BrokenProvider(LLMProvider):
    async def complete(self, prompt: str, context: str) -> str:
        raise ProviderError("provider unavailable")


def test_agent_no_provider_context_limit_and_failure(realistic_repo: Path) -> None:
    indexer = Indexer(realistic_repo, Settings(max_file_size=1000))
    indexer.index()
    with indexer.session() as con:
        answer = asyncio.run(answer_question(con, "login", None, 300, 2))
        assert not answer.generated and answer.evidence
        context = assemble_context(search(con, "login"), 10)
        assert len(context) <= 10
        with pytest.raises(ProviderError):
            asyncio.run(answer_question(con, "login", BrokenProvider(), 300, 2))


def test_memory_is_local_searchable_and_clearable(realistic_repo: Path) -> None:
    memory = MemoryStore(realistic_repo / ".codegraph.sqlite3")
    with memory.session() as con:
        con.execute("INSERT INTO memory(key, value) VALUES (?, ?)", ("architecture", "Auth service"))
    assert memory.search("Auth") == [("architecture", "Auth service")]
    memory.clear()
    assert memory.list() == []


def test_cli_success_and_failure(realistic_repo: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["index", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["search", "login", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["symbols", "auth.py", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["trace", "login", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["graph", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["debug", "login fails", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["doctor", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["memory", "list", "-r", str(realistic_repo)]).exit_code == 0
    assert runner.invoke(app, ["version"]).exit_code == 0
    assert runner.invoke(app, ["index", str(realistic_repo / "missing")]).exit_code != 0
