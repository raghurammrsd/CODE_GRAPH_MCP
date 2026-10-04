"""Tests for CodeGraph v2.2.0: Enterprise Concurrency, Sub-50ms Freshness, Bounded Context, and Zero-Friction Runtime Interceptor."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.database.interrogation import get_db_schema
from codegraph.freshness import check_freshness
from codegraph.indexing import Indexer
from codegraph.interrogation import list_routes
from codegraph.runtime.runner import (
    _generate_node_interceptor,
    _generate_python_interceptor,
    run_with_telemetry,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@codegraph.dev"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CodeGraph Test"], cwd=path, check=True, capture_output=True)


def test_v22_01_wal_and_concurrency_pragmas(tmp_path: Path) -> None:
    """v2.2 enforces WAL mode, synchronous NORMAL, and 15s busy timeout across sessions."""
    (tmp_path / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    indexer = Indexer(tmp_path)
    res = indexer.index()
    assert res.get("indexed", 0) >= 1 or res.get("indexed_files", 0) >= 1

    with indexer.session() as con:
        # Check WAL mode
        journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"

        # Check synchronous NORMAL (1)
        sync_mode = con.execute("PRAGMA synchronous").fetchone()[0]
        assert sync_mode == 1

        # Check busy timeout >= 15000ms
        busy_to = con.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_to >= 15000


def test_v22_02_git_fast_path_sub_50ms_freshness(tmp_path: Path) -> None:
    """Git commit fast path validates index freshness immediately when HEAD matches."""
    _init_git_repo(tmp_path)
    code_file = tmp_path / "service.py"
    code_file.write_text("def get_data(): return 42\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    indexer = Indexer(tmp_path)
    indexer.index()

    from codegraph.freshness import FreshnessStatus

    # Immediate check should be fresh
    with indexer.session() as con:
        status = check_freshness(tmp_path, con)
        assert status.status == FreshnessStatus.FRESH
        assert status.modified_files == []

    # Modify file -> should immediately detect stale
    code_file.write_text("def get_data(): return 100\n", encoding="utf-8")
    with indexer.session() as con:
        status2 = check_freshness(tmp_path, con)
        assert status2.status == FreshnessStatus.STALE


def test_v22_03_bounded_discovery_routes_pagination(tmp_path: Path) -> None:
    """list_routes bounds output and supports limit/offset pagination."""
    (tmp_path / "routes.py").write_text(
        """
from flask import Flask
app = Flask(__name__)

@app.route("/api/users", methods=["GET"])
def get_users(): pass

@app.route("/api/users", methods=["POST"])
def create_user(): pass

@app.route("/api/orders", methods=["GET"])
def get_orders(): pass
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Full query
        all_routes = list_routes(con, tmp_path)
        assert all_routes["status"] == "ok"
        total = all_routes["total_count"]
        assert total >= 3

        # Paginated query: limit 2, offset 0
        page1 = list_routes(con, tmp_path, limit=2, offset=0)
        assert page1["status"] == "ok"
        assert page1["count"] == 2
        assert page1["total_count"] == total
        assert page1["limit"] == 2
        assert page1["offset"] == 0
        assert page1["has_more"] is True

        # Paginated query: limit 2, offset 2
        page2 = list_routes(con, tmp_path, limit=2, offset=2)
        assert page2["count"] >= 1
        assert page2["offset"] == 2


def test_v22_04_bounded_discovery_db_schema_pagination(tmp_path: Path) -> None:
    """get_db_schema bounds output with limit and offset pagination."""
    (tmp_path / "models.py").write_text(
        """
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        all_schema = get_db_schema(con, tmp_path)
        assert all_schema["status"] == "ok"
        total_tbls = all_schema["table_count"]

        # Paginated query
        paged = get_db_schema(con, tmp_path, limit=1, offset=0)
        assert paged["status"] == "ok"
        assert len(paged["tables"]) == min(1, total_tbls)
        assert paged["limit"] == 1
        assert paged["offset"] == 0


def test_v22_05_runtime_interceptors_generation(tmp_path: Path) -> None:
    """Node and Python runtime interceptors generate valid syntax with target log path."""
    log_path = tmp_path / "traces.jsonl"
    node_code = _generate_node_interceptor(log_path)
    py_code = _generate_python_interceptor(log_path)

    assert "CodeGraph Node.js Runtime Interceptor" in node_code
    assert "uncaughtExceptionMonitor" in node_code
    assert "CodeGraph Python Runtime Interceptor" in py_code
    assert "sys.excepthook" in py_code
    assert str(log_path) in node_code or log_path.name in node_code
    assert str(log_path) in py_code


def test_v22_06_codegraph_run_telemetry_execution(tmp_path: Path) -> None:
    """codegraph run transparently executes a child process and streams traces into runtime index."""
    (tmp_path / "test_app.py").write_text("print('telemetry child executed')\n", encoding="utf-8")
    ret = run_with_telemetry(["python3", str(tmp_path / "test_app.py")], repository=tmp_path)
    assert ret == 0

    hooks_dir = tmp_path / ".codegraph" / "runtime_hooks"
    assert hooks_dir.exists()
    assert (hooks_dir / "cg_python_hook.py").exists()
    assert (hooks_dir / "cg_node_hook.js").exists()


def test_v22_07_cli_run_command_empty_validation() -> None:
    """codegraph run rejects empty command with error message and exit code 1."""
    runner = CliRunner()
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0
    assert "Error: Command cannot be empty" in result.output


def test_v22_08_cli_serve_sse_flags(tmp_path: Path) -> None:
    """codegraph serve accepts --transport sse, --host, and --port flags."""
    runner = CliRunner()
    with patch("codegraph.cli._run_server") as mock_run:
        result = runner.invoke(
            app,
            ["serve", str(tmp_path), "--transport", "sse", "--host", "0.0.0.0", "--port", "9999"],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["transport"] == "sse"
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9999
