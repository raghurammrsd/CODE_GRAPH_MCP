from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.indexing import Indexer

runner = CliRunner()


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "cli_repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def main():\n"
        "    print('hello world')\n",
        encoding="utf-8",
    )
    indexer = Indexer(repo)
    indexer.index()
    return repo


def test_cli_doctor_indexed(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    res = runner.invoke(app, ["doctor", "--repository", str(repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["index_exists"] is True
    assert data["status"] in ("healthy", "warning")
    assert "health" in data
    assert "freshness" in data
    assert "counts" in data
    assert data["counts"]["files"] >= 1


def test_cli_doctor_not_indexed(tmp_path: Path) -> None:
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    res = runner.invoke(app, ["doctor", "--repository", str(empty_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["index_exists"] is False
    assert data["status"] == "not_indexed"


def test_cli_privacy(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    res = runner.invoke(app, ["privacy", "--repository", str(repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["boundary_enforced"] is True
    assert data["clean"] is True
    assert "source_upload" in data
    assert "telemetry" in data
    assert "network_access" in data
    assert "prompt_injection_boundary" in data
    assert data["model_api_required"] is False


def test_cli_explain_context(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    res = runner.invoke(app, ["explain-context", "Explain main", "--repository", str(repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert "execution" in data
    assert "task" in data
    assert data["execution"] is not None
    assert "mode" in data["execution"]
    assert "retrieval_plan" in data["execution"]
