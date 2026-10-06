from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.indexing import Indexer

runner = CliRunner()


def _create_sample_db_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_db_repo"
    repo.mkdir()
    (repo / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String\n"
        "from sqlalchemy.orm import declarative_base\n"
        "Base = declarative_base()\n\n"
        "class User(Base):\n"
        "    __tablename__ = 'users'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    email = Column(String, nullable=False)\n",
        encoding="utf-8",
    )
    indexer = Indexer(repo)
    indexer.index()
    return repo


def test_cli_db_tables(tmp_path: Path) -> None:
    repo = _create_sample_db_repo(tmp_path)
    res = runner.invoke(app, ["db", "tables", str(repo), "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    assert any(t["table_name"] == "users" for t in data["tables"])

    # Human readable output
    res_human = runner.invoke(app, ["db", "tables", str(repo)])
    assert res_human.exit_code == 0
    assert "users" in res_human.stdout


def test_cli_db_columns(tmp_path: Path) -> None:
    repo = _create_sample_db_repo(tmp_path)
    res = runner.invoke(app, ["db", "columns", "users", "--path", str(repo), "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    col_names = [c["column_name"] for c in data["columns"]]
    assert "id" in col_names
    assert "email" in col_names


def test_cli_db_models(tmp_path: Path) -> None:
    repo = _create_sample_db_repo(tmp_path)
    res = runner.invoke(app, ["db", "models", str(repo), "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    assert any(m["name"] == "User" for m in data["models"])


def test_cli_db_schema_and_impact(tmp_path: Path) -> None:
    repo = _create_sample_db_repo(tmp_path)
    res_schema = runner.invoke(app, ["db", "schema", str(repo), "--json"])
    assert res_schema.exit_code == 0
    schema_data = json.loads(res_schema.stdout)
    assert schema_data["status"] == "ok"

    res_impact = runner.invoke(app, ["db", "impact", "users", "--path", str(repo), "--json"])
    assert res_impact.exit_code == 0
    impact_data = json.loads(res_impact.stdout)
    assert impact_data["status"] == "ok"


def test_cli_ingest_traces(tmp_path: Path) -> None:
    repo = _create_sample_db_repo(tmp_path)
    trace_file = tmp_path / "traces.json"
    trace_file.write_text(
        json.dumps([
            {
                "trace_id": "tr_1",
                "span_id": "sp_1",
                "operation": "INSERT",
                "table": "users",
                "sql": "INSERT INTO users (email) VALUES ('test@example.com')",
            }
        ]),
        encoding="utf-8",
    )

    # Test top-level codegraph ingest
    res_ingest = runner.invoke(app, ["ingest", str(trace_file), "--repository", str(repo), "--json"])
    assert res_ingest.exit_code == 0
    data = json.loads(res_ingest.stdout)
    assert data["status"] == "ok"
    assert data["events_ingested"] >= 1

    # Test codegraph db ingest
    res_db_ingest = runner.invoke(app, ["db", "ingest", str(trace_file), "--repository", str(repo)])
    assert res_db_ingest.exit_code == 0
    assert "Runtime Ingestion Complete" in res_db_ingest.stdout

