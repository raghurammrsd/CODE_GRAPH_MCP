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


def test_git_state_clean_dirty_stale(tmp_path: Path) -> None:
    from codegraph.freshness import save_commit
    from codegraph.git_state import GitFreshnessState, get_git_state

    repo = tmp_path / "fresh_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    f = repo / "core.py"
    f.write_text("def run(): pass\n")
    run_git("add", "core.py")
    run_git("commit", "-m", "Initial")

    head_rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # 1. CLEAN: indexed_commit matches HEAD, working tree clean
    save_commit(con, head_rev, 1000)
    st = get_git_state(repo, con)
    assert st.freshness == GitFreshnessState.CLEAN
    assert st.branch == "main"
    assert st.current_head == head_rev
    assert not st.working_tree.is_dirty

    # 2. DIRTY: modify file in working tree
    f.write_text("def run(): return 42\n")
    st_dirty = get_git_state(repo, con)
    assert st_dirty.freshness == GitFreshnessState.DIRTY
    assert st_dirty.working_tree.is_dirty
    assert "core.py" in st_dirty.working_tree.modified_files

    # 3. STALE: commit new change, indexed_commit is now older than HEAD
    run_git("add", "core.py")
    run_git("commit", "-m", "Second commit")
    st_stale = get_git_state(repo, con)
    assert st_stale.freshness == GitFreshnessState.STALE
    assert st_stale.current_head != st_stale.indexed_head


def test_structural_diff_and_rename(tmp_path: Path) -> None:
    from codegraph.structural_diff import compare_revisions

    repo = tmp_path / "diff_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "old_name.py").write_text("def stable(): return 1\n")
    (repo / "calc.py").write_text("def calculate():\n    return 10\n")
    run_git("add", ".")
    run_git("commit", "-m", "c1")

    # Rename old_name.py -> new_name.py, modify calc.py, add new_file.py
    run_git("mv", "old_name.py", "new_name.py")
    (repo / "calc.py").write_text("def calculate():\n    return 99\ndef helper():\n    return 0\n")
    (repo / "new_file.py").write_text("def newly_added(): pass\n")
    run_git("add", ".")
    run_git("commit", "-m", "c2")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    diff = compare_revisions(repo, "HEAD~1", "HEAD", con)
    assert "new_file.py" in diff.added_files
    assert "calc.py" in diff.modified_files

    # Check renamed files
    assert any(r.old_path == "old_name.py" and r.new_path == "new_name.py" for r in diff.renamed_files)

    # Check AST symbol level diff
    changed_names = {s.name for s in diff.changed_symbols}
    added_names = {s.name for s in diff.added_symbols}

    assert "calculate" in changed_names
    assert "helper" in added_names
    assert "newly_added" in added_names


def test_deep_change_impact(tmp_path: Path) -> None:
    from codegraph.change_impact import get_deep_change_impact

    repo = tmp_path / "impact_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "service.py").write_text("def pay(amount):\n    return amount\n")
    run_git("add", ".")
    run_git("commit", "-m", "c1")

    (repo / "service.py").write_text("def pay(amount, currency='USD'):\n    return amount\n")
    run_git("add", ".")
    run_git("commit", "-m", "c2")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # Populate symbol and callers in DB
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("service.py::pay", "pay", "pay", "service.py", 1, 2, "function", "python"),
    )
    con.execute(
        "INSERT INTO calls (source_path, callee, line, confidence, source_symbol_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("api.py", "pay", 15, "HIGH", "api.py::checkout"),
    )
    con.execute(
        "INSERT INTO 'references' (source_symbol_id, target_symbol_id, relationship, confidence, path, start_line, end_line, evidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("test_service.py::test_pay", "service.py::pay", "TESTS", "HIGH", "test_service.py", 5, 8, "tests pay"),
    )
    con.commit()

    report = get_deep_change_impact(repo, con, "HEAD~1", "HEAD", max_depth=2)
    assert report.total_impacted_count > 0
    assert any("checkout" in c.name for c in report.direct_callers)
    assert any(t.name == "test_pay" or "test_service.py" in t.file for t in report.affected_tests)
    assert report.blast_radius_score > 0.0


def test_context_freshness_unrelated_file_invariant(tmp_path: Path) -> None:
    """CRITICAL TEST:
    generate context at HEAD A -> modify unrelated file -> verify context remains valid.
    modify target symbol/file -> verify context becomes STALE.
    """
    from codegraph.context_freshness import check_context_freshness

    repo = tmp_path / "freshness_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "auth.py").write_text("def verify_token(t): return True\n")
    (repo / "unrelated_notes.py").write_text("# Just documentation\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit A")

    head_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip()

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # 1. Compile context targeting auth.py
    context_packet = {
        "metadata": {
            "indexed_commit": head_a,
            "target": "verify_token",
            "files": ["auth.py"],
        },
        "symbols": [
            {"name": "verify_token", "file": "auth.py", "canonical_id": "auth.py::verify_token"}
        ],
        "files": ["auth.py"],
    }

    # Context is VALID initially
    freshness_res = check_context_freshness(context_packet, repo, con)
    assert freshness_res.status.value == "VALID"
    assert freshness_res.is_valid is True

    # 2. Modify UNRELATED file (unrelated_notes.py) and commit
    (repo / "unrelated_notes.py").write_text("# Updated documentation\n")
    run_git("add", "unrelated_notes.py")
    run_git("commit", "-m", "Commit B: Update unrelated file")

    # Critical invariant: context must STILL be VALID!
    freshness_after_unrelated = check_context_freshness(context_packet, repo, con)
    assert freshness_after_unrelated.status.value == "VALID"
    assert freshness_after_unrelated.is_valid is True
    assert freshness_after_unrelated.unrelated_changed_files == ["unrelated_notes.py"]

    # 3. Now modify the TARGET file (auth.py)
    (repo / "auth.py").write_text("def verify_token(t): return False\n")
    run_git("add", "auth.py")
    run_git("commit", "-m", "Commit C: Modify target auth.py")

    # Context must now be STALE
    freshness_after_target_change = check_context_freshness(context_packet, repo, con)
    assert freshness_after_target_change.status.value == "STALE"
    assert freshness_after_target_change.is_valid is False
    assert "auth.py" in freshness_after_target_change.changed_relevant_files


def test_symbol_history_tracing(tmp_path: Path) -> None:
    from codegraph.symbol_history import trace_symbol_history

    repo = tmp_path / "history_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    calc_file = repo / "calculator.py"
    calc_file.write_text("def add(a, b):\n    return a + b\n")
    run_git("add", ".")
    run_git("commit", "-m", "Initial add function")

    calc_file.write_text("def add(a, b):\n    # log\n    return int(a) + int(b)\n")
    run_git("add", ".")
    run_git("commit", "-m", "Cast add args to int")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    history = trace_symbol_history(repo, "add", "calculator.py", con, max_commits=10)
    assert history.symbol == "add"
    assert len(history.events) >= 1
    assert any(e.event_type in ("MODIFIED", "INTRODUCED") for e in history.events)


def test_branch_architecture_comparison(tmp_path: Path) -> None:
    from codegraph.branch_comparison import compare_branch_architecture

    repo = tmp_path / "branch_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "base.py").write_text("def base(): pass\n")
    run_git("add", ".")
    run_git("commit", "-m", "Base commit")

    # Switch to feature branch
    run_git("checkout", "-b", "feature/billing")
    pkg_dir = repo / "billing"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "processor.py").write_text("def process_invoice(): pass\n")
    run_git("add", ".")
    run_git("commit", "-m", "Add billing module")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    report = compare_branch_architecture(repo, "main", "feature/billing", con, limit=50)
    assert report.total_symbols >= 1
    assert len(report.packages) >= 1
    pkg = report.packages[0]
    assert any("processor" in m.module for m in pkg.modules)


def test_incremental_git_sync(tmp_path: Path) -> None:
    from codegraph.git_state import incremental_git_sync

    repo = tmp_path / "sync_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "math_ops.py").write_text("def add(a, b): return a + b\n")
    run_git("add", ".")
    run_git("commit", "-m", "Initial math")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # Initial sync
    sync_res = incremental_git_sync(repo, con)
    assert sync_res.status in ("synced", "clean")

    # Modify file
    (repo / "math_ops.py").write_text("def add(a, b): return a + b\ndef sub(a, b): return a - b\n")
    sync_dirty = incremental_git_sync(repo, con)
    assert "math_ops.py" in sync_dirty.reindexed_files
    assert sync_dirty.status == "synced"


def test_detached_head_and_edge_cases(tmp_path: Path) -> None:
    from codegraph.git_state import get_git_state
    from codegraph.structural_diff import compare_revisions

    repo = tmp_path / "edge_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "f1.py").write_text("x = 1\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit 1")

    (repo / "f2.py").write_text("y = 2\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit 2")

    # Detached HEAD
    run_git("checkout", "HEAD~1")
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    st = get_git_state(repo, con)
    assert st.is_git is True
    assert "detached" in str(st.branch).lower() or "detached" in str(st.detail).lower()

    # Diff with invalid ref safely handled
    diff = compare_revisions(repo, "nonexistent_ref_1", "nonexistent_ref_2", con)
    assert diff.total_file_changes == 0


def test_mcp_git_tools_registered_and_callable(tmp_path: Path) -> None:
    import asyncio

    from codegraph.indexing import Indexer
    from codegraph.mcp import create_server

    repo = tmp_path / "mcp_git_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "main.py").write_text("def run(): pass\n")
    run_git("add", ".")
    run_git("commit", "-m", "Initial commit")

    Indexer(repo).index()
    server = create_server(repo)

    async def _test() -> None:
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "get_git_state" in names
        assert "compare_git" in names
        assert "get_change_impact" in names
        assert "check_context_freshness" in names
        assert "trace_symbol_history" in names
        assert "detect_semantic_conflicts" in names

        # Call get_git_state
        res, structured = await server.call_tool("get_git_state", {})
        git_res = structured.get("result", structured)
        assert git_res["is_git"] is True
        assert git_res["freshness"] in ("CLEAN", "DIRTY", "STALE")

        # Call compare_git
        res, structured = await server.call_tool("compare_git", {"base": "HEAD", "head": "HEAD"})
        comp_res = structured.get("result", structured)
        assert comp_res["base_ref"] == "HEAD"

        # Call check_context_freshness
        res, structured = await server.call_tool("check_context_freshness", {"context_packet": {"files": ["main.py"]}})
        fresh_res = structured.get("result", structured)
        assert fresh_res["status"] in ("VALID", "STALE", "PARTIALLY_STALE", "UNKNOWN")

        # Call detect_semantic_conflicts
        res, structured = await server.call_tool("detect_semantic_conflicts", {"base_branch": "main", "head_branch": "main"})
        conf_res = structured.get("result", structured)
        assert conf_res["has_conflicts"] is False

    asyncio.run(_test())


def test_detect_semantic_conflicts_between_branches(tmp_path: Path) -> None:
    from codegraph.semantic_conflicts import detect_semantic_conflicts

    repo = tmp_path / "conflict_repo"
    repo.mkdir()

    def run_git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)

    run_git("init", "-b", "main")
    run_git("config", "user.email", "tester@codegraph.dev")
    run_git("config", "user.name", "Tester")

    (repo / "calc.py").write_text("def legacy_sum(a, b):\n    return a + b\n")
    run_git("add", ".")
    run_git("commit", "-m", "Initial commit with legacy_sum")

    # Create feature branch
    run_git("checkout", "-b", "feature/client")
    (repo / "client.py").write_text("from calc import legacy_sum\ndef run():\n    return legacy_sum(1, 2)\n")
    run_git("add", ".")
    run_git("commit", "-m", "Add client using legacy_sum")

    # Go back to main and delete legacy_sum
    run_git("checkout", "main")
    (repo / "calc.py").write_text("def modern_sum(a, b, extra=0):\n    return a + b + extra\n")
    run_git("add", ".")
    run_git("commit", "-m", "Replace legacy_sum with modern_sum")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # Detect conflicts between main and feature/client
    report = detect_semantic_conflicts(repo, base_branch="main", head_branch="feature/client", con=con)
    assert report.has_conflicts is True
    assert report.total_conflicts >= 1
    assert any("legacy_sum" in c.symbol for c in report.conflicts)

    # Identical branches check
    clean_report = detect_semantic_conflicts(repo, base_branch="main", head_branch="main", con=con)
    assert clean_report.has_conflicts is False
    assert clean_report.total_conflicts == 0




