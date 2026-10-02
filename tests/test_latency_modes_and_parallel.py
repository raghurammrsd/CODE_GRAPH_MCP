from __future__ import annotations

import sqlite3
from pathlib import Path

from codegraph.context import get_context
from codegraph.indexing import Indexer


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "latency_repo"
    repo.mkdir()
    (repo / "auth.py").write_text(
        "class AuthService:\n"
        "    def login(self, username: str) -> bool:\n"
        "        return True\n"
        "    def logout(self) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    (repo / "api.py").write_text(
        "from auth import AuthService\n"
        "auth = AuthService()\n"
        "def handle_login(req):\n"
        "    return auth.login('admin')\n",
        encoding="utf-8",
    )
    (repo / "test_auth.py").write_text(
        "from auth import AuthService\n"
        "def test_auth_login():\n"
        "    a = AuthService()\n"
        "    assert a.login('admin') is True\n",
        encoding="utf-8",
    )
    indexer = Indexer(repo)
    indexer.index()
    return repo


def test_latency_modes_and_execution_metadata(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    indexer = Indexer(repo)

    with indexer.session() as con:
        # 1. FAST Mode
        fast_packet = get_context(
            con,
            repo,
            task="Explain AuthService login",
            mode="FAST",
        )
        assert fast_packet.mode == "FAST"
        assert fast_packet.execution is not None
        assert fast_packet.execution["mode"] == "FAST"
        assert fast_packet.execution["cache_hit"] is False
        assert "timing" in fast_packet.execution
        timing = fast_packet.execution["timing"]
        assert "total_ms" in timing
        assert "planning_ms" in timing
        assert "search_ms" in timing
        assert "compilation_ms" in timing
        assert fast_packet.execution["latency_ms"] >= 0.0

        # 2. BALANCED Mode
        balanced_packet = get_context(
            con,
            repo,
            task="Explain AuthService login",
            mode="BALANCED",
        )
        assert balanced_packet.mode == "BALANCED"
        assert balanced_packet.execution is not None
        assert balanced_packet.execution["mode"] == "BALANCED"

        # 3. DEEP Mode
        deep_packet = get_context(
            con,
            repo,
            task="Explain AuthService login",
            mode="DEEP",
        )
        assert deep_packet.mode == "DEEP"
        assert deep_packet.execution is not None
        assert deep_packet.execution["mode"] == "DEEP"

        # 4. Cache Hit Verification
        cached_packet = get_context(
            con,
            repo,
            task="Explain AuthService login",
            mode="FAST",
        )
        assert cached_packet.mode == "FAST"
        assert cached_packet.execution is not None
        assert cached_packet.execution["cache_hit"] is True
        assert cached_packet.execution["latency_ms"] < 50.0


def test_parallel_retrieval_on_disk_db(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    db_file = repo / ".codegraph.sqlite3"
    assert db_file.exists()

    # Open connection to the disk DB
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    try:
        packet = get_context(
            con,
            repo,
            task="Analyze AuthService handle_login and test_auth_login",
            mode="BALANCED",
        )
        assert len(packet.symbols) > 0
        assert packet.execution is not None
        assert packet.execution["cache_hit"] is False
        assert packet.execution["latency_ms"] >= 0.0
    finally:
        con.close()
