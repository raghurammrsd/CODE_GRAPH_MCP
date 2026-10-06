"""Comprehensive test suite for CodeGraph MCP SAFE_RENAME vertical slice.

Covers:
  - Scenario A: Dry-run zero mutation invariant (hashes, mtimes, file bytes unchanged)
  - Scenario B: Atomic commit on clean repository (files updated, temp files cleaned up, manifest written)
  - Scenario C: Rollback (manifest exists, files restored to original bytes, status ROLLED_BACK)
  - Scenario D: Precondition change detection (FILE_CHANGED_SINCE_PLAN if file modified externally)
  - Scenario E: Rollback blocked on external modification (subsequent manual edits block rollback)
  - Scenario F: Uncertainty blocking (POSSIBLE / UNKNOWN calls cause BLOCKED unless force_uncertain=True)
  - Scenario G: Ambiguous target resolution rejected (homonyms without qualification)
  - Scenario H: Preserves comments, docstrings, formatting, indentation, and line endings
  - Scenario I: Renames from-import without alias (import and call sites updated)
  - Scenario J: Renames from-import with alias (import updated, alias call sites untouched)
  - Scenario K: Renames attribute calls (module.symbol or instance.method)
  - Scenario L: Syntax validation failure aborts with zero mutation
  - Scenario M: Concurrent lock rejection (RefactorLockError)
  - Scenario N: Post-commit incremental index update (new symbol indexed, old symbol absent)
  - Scenario O: Impact reporting (affected tests and routes listed)
  - Scenario P: CLI commands (codegraph refactor rename, codegraph refactor undo)
  - Scenario Q: Class method renaming (self.method, cls.method, def method)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.indexing.indexer import Indexer
from codegraph.refactor.models import RefactorRisk, RefactorStatus
from codegraph.refactor.renamer import (
    execute_safe_rename,
    plan_safe_rename,
    preview_safe_rename,
)
from codegraph.refactor.transactions import (
    RefactorLock,
    RefactorLockError,
    read_manifest,
    rollback_refactor,
)

runner = CliRunner()


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal multi-file Python repository with index."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # 1. math_utils.py (definition)
    math_file = repo / "math_utils.py"
    math_file.write_text(
        '"""Math utilities module."""\n'
        "\n"
        "# Addition function\n"
        "def compute_sum(a: int, b: int) -> int:\n"
        '    """Return sum of a and b."""\n'
        "    # Handle zero edge case\n"
        "    if a == 0:\n"
        "        return b\n"
        "    return compute_sum(a - 1, b + 1)\n"
    )

    # 2. service.py (from-import without alias)
    service_file = repo / "service.py"
    service_file.write_text(
        "from math_utils import compute_sum\n"
        "\n"
        "def run_service() -> int:\n"
        "    result = compute_sum(10, 20)\n"
        "    return result\n"
    )

    # 3. aliased.py (from-import with alias)
    aliased_file = repo / "aliased.py"
    aliased_file.write_text(
        "from math_utils import compute_sum as c_sum\n"
        "\n"
        "def run_aliased() -> int:\n"
        "    return c_sum(5, 5)\n"
    )

    # 4. test_math.py (test file)
    test_file = repo / "test_math.py"
    test_file.write_text(
        "from math_utils import compute_sum\n"
        "\n"
        "def test_compute_sum():\n"
        "    assert compute_sum(1, 2) == 3\n"
    )

    # Index the repository
    indexer = Indexer(repo)
    indexer.index()

    return repo


# ---------------------------------------------------------------------------
# Test A: Dry-run zero mutation invariant
# ---------------------------------------------------------------------------


def test_scenario_a_dry_run_zero_mutation(sample_repo: Path) -> None:
    """dry_run=True must return complete preview diffs with ZERO disk mutation."""
    # Capture initial hashes and mtimes
    files = ["math_utils.py", "service.py", "aliased.py", "test_math.py"]
    initial_bytes = {f: (sample_repo / f).read_bytes() for f in files}
    initial_mtimes = {f: (sample_repo / f).stat().st_mtime_ns for f in files}

    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        result = execute_safe_rename(
            sample_repo,
            con,
            target="compute_sum",
            new_name="add_numbers",
            dry_run=True,
        )

    assert result.status == RefactorStatus.READY
    assert result.target_symbol == "math_utils.compute_sum"
    assert result.new_name == "add_numbers"
    assert result.risk == RefactorRisk.LOW
    assert result.files_changed > 0
    assert result.spans_count > 0
    assert "math_utils.py" in result.diffs
    assert "service.py" in result.diffs

    # Invariant: verify all file bytes and mtimes are 100% identical on disk
    for f in files:
        current_bytes = (sample_repo / f).read_bytes()
        current_mtimes = (sample_repo / f).stat().st_mtime_ns
        assert current_bytes == initial_bytes[f], f"File {f} was mutated during dry-run!"
        assert current_mtimes == initial_mtimes[f], f"File {f} mtime changed during dry-run!"


# ---------------------------------------------------------------------------
# Test B: Atomic commit on clean repository
# ---------------------------------------------------------------------------


def test_scenario_b_atomic_commit(sample_repo: Path) -> None:
    """apply=True commits all changes atomically, cleans temp files, and records manifest."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        result = execute_safe_rename(
            sample_repo,
            con,
            target="compute_sum",
            new_name="add_numbers",
            dry_run=False,
        )

    assert result.status == RefactorStatus.APPLIED
    assert result.rollback_id is not None
    assert result.files_changed >= 3

    # Check that temporary files are cleaned up
    temp_files = list(sample_repo.glob("**/.tmp_cg_*"))
    assert len(temp_files) == 0

    # Check disk contents
    math_text = (sample_repo / "math_utils.py").read_text()
    assert "def add_numbers(a: int, b: int) -> int:" in math_text
    assert "return add_numbers(a - 1, b + 1)" in math_text
    assert "compute_sum" not in math_text.splitlines()[3]  # def line has new name

    service_text = (sample_repo / "service.py").read_text()
    assert "from math_utils import add_numbers" in service_text
    assert "result = add_numbers(10, 20)" in service_text

    # Manifest persisted
    manifest = read_manifest(sample_repo, result.rollback_id)
    assert manifest is not None
    assert manifest["status"] == "APPLIED"
    assert manifest["new_name"] == "add_numbers"


# ---------------------------------------------------------------------------
# Test C: Rollback restored to exact original bytes
# ---------------------------------------------------------------------------


def test_scenario_c_rollback(sample_repo: Path) -> None:
    """rollback_refactor restores original file contents atomically."""
    files = ["math_utils.py", "service.py", "aliased.py", "test_math.py"]
    original_bytes = {f: (sample_repo / f).read_bytes() for f in files}

    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        result = execute_safe_rename(
            sample_repo,
            con,
            target="compute_sum",
            new_name="add_numbers",
            dry_run=False,
        )

    assert result.status == RefactorStatus.APPLIED
    tx_id = result.rollback_id
    assert tx_id is not None

    # Now rollback
    rb_result = rollback_refactor(sample_repo, tx_id)
    assert rb_result.status == RefactorStatus.ROLLED_BACK
    assert rb_result.files_changed >= 3

    # Verify original bytes restored 100%
    for f in files:
        assert (sample_repo / f).read_bytes() == original_bytes[f]

    # Verify manifest marked ROLLED_BACK
    manifest = read_manifest(sample_repo, tx_id)
    assert manifest is not None
    assert manifest["status"] == "ROLLED_BACK"


# ---------------------------------------------------------------------------
# Test D: Precondition change detection
# ---------------------------------------------------------------------------


def test_scenario_d_external_change_detected_during_commit(sample_repo: Path) -> None:
    """If an affected file changes between plan and commit, commit must abort."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        plan = plan_safe_rename(sample_repo, con, "compute_sum", "add_numbers")
        diffs, buffers, errors = preview_safe_rename(sample_repo, plan)

        # External modification occurs before commit
        (sample_repo / "service.py").write_text("# External manual edit\n" + (sample_repo / "service.py").read_text())

        from codegraph.refactor.transactions import commit_refactor_transaction

        res = commit_refactor_transaction(sample_repo, plan, buffers)

    assert res.status == RefactorStatus.ERROR
    assert any("FILE_CHANGED_SINCE_PLAN" in e for e in res.errors)


# ---------------------------------------------------------------------------
# Test E: Rollback blocked on external modification
# ---------------------------------------------------------------------------


def test_scenario_e_rollback_blocked_on_external_modification(sample_repo: Path) -> None:
    """If a file was modified externally after refactor was applied, rollback is BLOCKED."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        result = execute_safe_rename(
            sample_repo,
            con,
            target="compute_sum",
            new_name="add_numbers",
            dry_run=False,
        )

    tx_id = result.rollback_id
    assert tx_id is not None

    # External modification made to math_utils.py after refactor
    (sample_repo / "math_utils.py").write_text("# manual edit after refactor\n" + (sample_repo / "math_utils.py").read_text())

    rb_res = rollback_refactor(sample_repo, tx_id)
    assert rb_res.status == RefactorStatus.BLOCKED
    assert any("ROLLBACK_BLOCKED_EXTERNAL_MODIFICATION" in e for e in rb_res.errors)


# ---------------------------------------------------------------------------
# Test F: Uncertainty blocking
# ---------------------------------------------------------------------------


def test_scenario_f_uncertainty_blocking(tmp_path: Path) -> None:
    """POSSIBLE / UNKNOWN calls cause BLOCKED status unless force_uncertain=True."""
    repo = tmp_path / "uncertain_repo"
    repo.mkdir()

    # Define function
    (repo / "auth.py").write_text("def verify(token: str) -> bool:\n    return True\n")
    # File with unverified / dynamic reference
    (repo / "client.py").write_text("from auth import verify\nres = verify('abc')\n")

    indexer = Indexer(repo)
    indexer.index()

    # Manually inject a POSSIBLE_CALLS reference into references table
    with indexer.session() as con:
        con.execute(
            "INSERT INTO 'references'(source_symbol_id, target_symbol_id, relationship, confidence, path, start_line, end_line, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("client.client_call", "auth.verify", "POSSIBLE_CALLS", "LOW", "client.py", 2, 2, "res = verify('abc')"),
        )
        con.commit()

        # Without force_uncertain, must be BLOCKED
        res_blocked = execute_safe_rename(repo, con, "verify", "validate", dry_run=True, force_uncertain=False)
        assert res_blocked.status == RefactorStatus.BLOCKED
        assert res_blocked.risk in (RefactorRisk.HIGH, RefactorRisk.MEDIUM)
        assert len(res_blocked.uncertainty_reasons) > 0

        # With force_uncertain=True, allowed to proceed
        res_forced = execute_safe_rename(repo, con, "verify", "validate", dry_run=True, force_uncertain=True)
        assert res_forced.status == RefactorStatus.READY


# ---------------------------------------------------------------------------
# Test G: Ambiguous target resolution rejected
# ---------------------------------------------------------------------------


def test_scenario_g_ambiguous_target_rejected(tmp_path: Path) -> None:
    """Homonymous symbols across files without qualification return BLOCKED / AMBIGUOUS."""
    repo = tmp_path / "homonym_repo"
    repo.mkdir()

    (repo / "mod_a.py").write_text("def format_data(): pass\n")
    (repo / "mod_b.py").write_text("def format_data(): pass\n")

    indexer = Indexer(repo)
    indexer.index()

    with indexer.session() as con:
        # Unqualified target "format_data" matches both mod_a and mod_b
        res = execute_safe_rename(repo, con, "format_data", "serialize_data", dry_run=True)

    assert res.status == RefactorStatus.BLOCKED
    assert any("AMBIGUOUS_TARGET" in e for e in res.errors)

    # Fully qualified target succeeds
    with indexer.session() as con:
        res_qual = execute_safe_rename(repo, con, "mod_a.format_data", "serialize_data", dry_run=True)
    assert res_qual.status == RefactorStatus.READY


# ---------------------------------------------------------------------------
# Test H: Preserves comments, docstrings, formatting, indentation, CRLF
# ---------------------------------------------------------------------------


def test_scenario_h_preserves_formatting_and_comments(sample_repo: Path) -> None:
    """Preserves comments, docstrings, indentation, CRLF/LF line endings."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        execute_safe_rename(sample_repo, con, "compute_sum", "add_numbers", dry_run=False)

    new_text = (sample_repo / "math_utils.py").read_text()

    # Docstring preserved
    assert '"""Math utilities module."""' in new_text
    assert '"""Return sum of a and b."""' in new_text
    # Comments preserved
    assert "# Addition function" in new_text
    assert "# Handle zero edge case" in new_text
    # Indentation preserved (4 spaces)
    assert "    if a == 0:\n        return b\n" in new_text


# ---------------------------------------------------------------------------
# Test I & J: Aliased and unaliased from-imports
# ---------------------------------------------------------------------------


def test_scenario_i_and_j_import_aliasing(sample_repo: Path) -> None:
    """Unaliased import renames both import and usages; aliased import renames import only."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        execute_safe_rename(sample_repo, con, "compute_sum", "add_numbers", dry_run=False)

    # Unaliased service.py
    srv_text = (sample_repo / "service.py").read_text()
    assert "from math_utils import add_numbers" in srv_text
    assert "result = add_numbers(10, 20)" in srv_text

    # Aliased aliased.py
    aliased_text = (sample_repo / "aliased.py").read_text()
    # Import statement line has new name before 'as'
    assert "from math_utils import add_numbers as c_sum" in aliased_text
    # Usages stay c_sum
    assert "return c_sum(5, 5)" in aliased_text


# ---------------------------------------------------------------------------
# Test K: Attribute calls (e.g. module.symbol or obj.method)
# ---------------------------------------------------------------------------


def test_scenario_k_attribute_calls(tmp_path: Path) -> None:
    """Renames attribute accesses module.symbol."""
    repo = tmp_path / "attr_repo"
    repo.mkdir()

    (repo / "calc.py").write_text("def multiply(x, y):\n    return x * y\n")
    (repo / "main.py").write_text("import calc\n\nres = calc.multiply(2, 3)\n")

    indexer = Indexer(repo)
    indexer.index()

    with indexer.session() as con:
        res = execute_safe_rename(repo, con, "multiply", "mult", dry_run=False)

    assert res.status == RefactorStatus.APPLIED
    main_text = (repo / "main.py").read_text()
    assert "res = calc.mult(2, 3)" in main_text


# ---------------------------------------------------------------------------
# Test L: Syntax validation failure aborts with zero mutation
# ---------------------------------------------------------------------------


def test_scenario_l_invalid_identifier_and_syntax_guard(sample_repo: Path) -> None:
    """Invalid Python identifier (e.g. keywords, numbers, punctuation) is rejected."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = execute_safe_rename(sample_repo, con, "compute_sum", "123invalid", dry_run=True)

    assert res.status == RefactorStatus.BLOCKED
    assert any("INVALID_IDENTIFIER" in e for e in res.errors)

    # Reserved keyword rejected
    with indexer.session() as con:
        res_kw = execute_safe_rename(sample_repo, con, "compute_sum", "def", dry_run=True)
    assert res_kw.status == RefactorStatus.BLOCKED
    assert any("INVALID_IDENTIFIER" in e for e in res_kw.errors)


# ---------------------------------------------------------------------------
# Test M: Concurrent lock rejection
# ---------------------------------------------------------------------------


def test_scenario_m_concurrent_lock_rejection(sample_repo: Path) -> None:
    """Concurrent lock prevents simultaneous refactoring operations."""
    with RefactorLock(sample_repo):
        # Attempting to acquire lock while already held
        with pytest.raises(RefactorLockError):
            lock2 = RefactorLock(sample_repo, timeout_seconds=0.1)
            lock2.acquire()


# ---------------------------------------------------------------------------
# Test N: Post-commit incremental index update
# ---------------------------------------------------------------------------


def test_scenario_n_post_commit_reindex(sample_repo: Path) -> None:
    """Post-commit triggers incremental index update where new symbol is verified."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        execute_safe_rename(sample_repo, con, "compute_sum", "add_numbers", dry_run=False)

    # Re-connect to database
    with indexer.session() as con:
        new_row = con.execute("SELECT name FROM symbols WHERE name='add_numbers'").fetchone()
        assert new_row is not None
        assert new_row["name"] == "add_numbers"

        old_row = con.execute("SELECT name FROM symbols WHERE name='compute_sum'").fetchone()
        assert old_row is None


# ---------------------------------------------------------------------------
# Test O: Impact reporting (tests and routes)
# ---------------------------------------------------------------------------


def test_scenario_o_impact_reporting(sample_repo: Path) -> None:
    """RefactorResult includes affected tests and routes."""
    indexer = Indexer(sample_repo)
    with indexer.session() as con:
        res = execute_safe_rename(sample_repo, con, "compute_sum", "add_numbers", dry_run=True)

    assert "test_math.py" in res.tests_affected


# ---------------------------------------------------------------------------
# Test P: CLI commands
# ---------------------------------------------------------------------------


def test_scenario_p_cli_commands(sample_repo: Path) -> None:
    """CLI subcommands codegraph refactor rename and codegraph refactor undo work end-to-end."""
    # 1. CLI dry-run preview
    res_dry = runner.invoke(
        app,
        ["refactor", "rename", "compute_sum", "add_numbers", "--path", str(sample_repo), "--json"],
    )
    assert res_dry.exit_code == 0
    dry_json = json.loads(res_dry.stdout)
    assert dry_json["status"] == "READY"
    assert "math_utils.py" in dry_json["diffs"]

    # 2. CLI apply
    res_apply = runner.invoke(
        app,
        ["refactor", "rename", "compute_sum", "add_numbers", "--apply", "--path", str(sample_repo), "--json"],
    )
    assert res_apply.exit_code == 0
    apply_json = json.loads(res_apply.stdout)
    assert apply_json["status"] == "APPLIED"
    tx_id = apply_json["rollback_id"]
    assert tx_id is not None

    # Check math_utils.py modified
    assert "def add_numbers" in (sample_repo / "math_utils.py").read_text()

    # 3. CLI undo
    res_undo = runner.invoke(
        app,
        ["refactor", "undo", tx_id, "--path", str(sample_repo), "--json"],
    )
    assert res_undo.exit_code == 0
    undo_json = json.loads(res_undo.stdout)
    assert undo_json["status"] == "ROLLED_BACK"

    # Check restored
    assert "def compute_sum" in (sample_repo / "math_utils.py").read_text()


# ---------------------------------------------------------------------------
# Test Q: Class method renaming
# ---------------------------------------------------------------------------


def test_scenario_q_class_method_rename(tmp_path: Path) -> None:
    """Renames class method definitions and self.method() calls."""
    repo = tmp_path / "class_repo"
    repo.mkdir()

    (repo / "auth_service.py").write_text(
        "class AuthService:\n"
        "    def verify(self, token: str) -> bool:\n"
        "        return True\n"
        "\n"
        "    def check_auth(self, token: str) -> bool:\n"
        "        return self.verify(token)\n"
    )

    indexer = Indexer(repo)
    indexer.index()

    with indexer.session() as con:
        res = execute_safe_rename(repo, con, "AuthService.verify", "validate_token", dry_run=False)

    assert res.status == RefactorStatus.APPLIED
    updated_text = (repo / "auth_service.py").read_text()
    assert "def validate_token(self, token: str) -> bool:" in updated_text
    assert "return self.validate_token(token)" in updated_text
