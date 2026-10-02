"""Tests for Git intelligence enrichment and change analysis."""
import sqlite3
import subprocess
from pathlib import Path

import pytest

from codegraph.git import (
    analyze_change_impact,
    changed_files,
    current_commit,
    file_diff,
    get_change_context,
    get_file_history,
    is_git_repository,
    recent_commits,
)
from codegraph.indexing.indexer import SCHEMA


def test_non_git_repo(tmp_path: Path) -> None:
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()

    assert is_git_repository(non_git) is False
    assert current_commit(non_git) is None
    assert recent_commits(non_git) == []
    assert changed_files(non_git) == []
    assert get_file_history(non_git, "foo.py") == []

    ctx = get_change_context(non_git)
    assert ctx["total_changed"] == 0
    assert ctx["files"] == []


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "test_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        )

    run_git("init")
    run_git("config", "user.email", "test@codegraph.dev")
    run_git("config", "user.name", "CodeGraph Tester")

    f1 = repo / "auth.py"
    f1.write_text("def authenticate():\n    return True\n")
    run_git("add", "auth.py")
    run_git("commit", "-m", "Initial commit: add auth")

    f1.write_text("def authenticate(token=None):\n    # updated\n    return False\n")
    run_git("add", "auth.py")
    run_git("commit", "-m", "Update authenticate function")

    return repo


def test_git_repo_basic_operations(git_repo: Path) -> None:
    assert is_git_repository(git_repo) is True
    sha = current_commit(git_repo)
    assert sha is not None
    assert len(sha) == 40

    commits = recent_commits(git_repo, n=5)
    assert len(commits) == 2
    assert commits[0].message == "Update authenticate function"
    assert commits[1].message == "Initial commit: add auth"


def test_git_repo_history_and_diff(git_repo: Path) -> None:
    history = get_file_history(git_repo, "auth.py")
    assert len(history) == 2
    assert history[0]["message"] == "Update authenticate function"

    diffs = changed_files(git_repo, since="HEAD~1", until="HEAD")
    assert len(diffs) == 1
    assert diffs[0].path == "auth.py"
    assert diffs[0].status in ("M", "A")

    diff_text = file_diff(git_repo, "auth.py", since="HEAD~1", until="HEAD")
    assert "updated" in diff_text


def test_get_change_context(git_repo: Path) -> None:
    ctx = get_change_context(git_repo, since="HEAD~1", until="HEAD")
    assert ctx["total_changed"] == 1
    assert len(ctx["files"]) == 1
    assert ctx["files"][0]["path"] == "auth.py"


def test_analyze_change_impact(git_repo: Path) -> None:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    con.execute("INSERT INTO files (path, hash, language) VALUES (?, ?, ?)",
                ("auth.py", "h1", "python"))
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("auth.py::authenticate", "authenticate", "authenticate", "auth.py", 1, 3, "function", "python"),
    )
    con.commit()

    impact = analyze_change_impact(con, git_repo, since="HEAD~1", until="HEAD")
    assert "changed_files" in impact
    assert "changed_symbols" in impact
    assert "affected_callers" in impact
    assert "affected_tests" in impact
    assert "authenticate" in impact["changed_symbols"]
