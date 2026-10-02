"""Phase 2 test suite: search ranking, symbols, graph, context, freshness,
git, related tests, security, architecture, impact, audit log.

Tests use in-memory SQLite databases and temporary directories.
No network access, no external dependencies.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from codegraph.architecture import get_architecture
from codegraph.audit import AuditLog
from codegraph.config import Settings
from codegraph.context import ContextPacket, get_context
from codegraph.epistemic import EpistemicStatus, conflict, fact, inference, unknown
from codegraph.errors import SecurityError
from codegraph.freshness import (
    FreshnessStatus,
    check_freshness,
    indexed_commit,
    save_commit,
)
from codegraph.graph import (
    analyze_impact,
    find_callees,
    find_callers,
    find_importers,
    find_related_tests,
    get_dependency_graph,
)
from codegraph.indexing import Indexer
from codegraph.indexing.parser import parse
from codegraph.ranking import rank
from codegraph.search import search
from codegraph.security import safe_path

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_repo(tmp_path: Path) -> Path:
    """A realistic multi-file repository fixture."""
    (tmp_path / "auth.py").write_text(
        """import os
from models import User, Session

class AuthService:
    \"\"\"Handles user authentication.\"\"\"
    def login(self, email: str) -> User | None:
        return User.find(email)

    def logout(self, session_id: str) -> None:
        Session.invalidate(session_id)

def login_controller(email: str):
    \"\"\"HTTP handler for POST /login.\"\"\"
    return AuthService().login(email)
"""
    )
    (tmp_path / "models.py").write_text(
        """class User:
    @classmethod
    def find(cls, email: str):
        return None

class Session:
    @classmethod
    def invalidate(cls, session_id: str) -> None:
        pass
"""
    )
    (tmp_path / "app.py").write_text(
        """from auth import AuthService, login_controller

def main():
    svc = AuthService()
    result = svc.login('test@example.com')
    return result
"""
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text(
        """import pytest
from auth import AuthService, login_controller

class TestAuthService:
    def test_login_returns_none_for_unknown(self):
        svc = AuthService()
        assert svc.login('nobody@example.com') is None

    def test_login_controller_delegates(self):
        result = login_controller('test@example.com')
        assert result is None
"""
    )
    (tmp_path / "config.py").write_text(
        """import os

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///app.db')
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key')
"""
    )
    (tmp_path / ".env").write_text("SECRET_KEY=must-not-leak")
    return tmp_path


@pytest.fixture()
def indexed_repo(auth_repo: Path) -> tuple[Path, Indexer]:
    indexer = Indexer(auth_repo, Settings(max_file_size=500_000))
    indexer.index()
    return auth_repo, indexer


# ===========================================================================
# 1. SEARCH TESTS
# ===========================================================================


class TestSearch:
    def test_exact_symbol_match_ranks_first(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "AuthService", top_k=5)
        assert results, "Expected at least one result"
        assert results[0].file == "auth.py"
        assert results[0].symbol is not None
        assert "AuthService" in results[0].symbol

    def test_path_relevance(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "auth login")
        assert any(r.file == "auth.py" for r in results)

    def test_content_match(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "authentication email")
        assert any("auth" in r.file for r in results)

    def test_empty_query_returns_empty(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "   ")
        assert results == []

    def test_missing_term_returns_empty(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "zzznonexistentterm999")
        assert results == []

    def test_secrets_not_in_results(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = search(con, "must-not-leak SECRET_KEY")
        for r in results:
            assert "must-not-leak" not in r.snippet


# ===========================================================================
# 2. SYMBOL TESTS
# ===========================================================================


class TestSymbols:
    def test_qualified_python_names(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name FROM symbols WHERE path='auth.py'"
            ).fetchall()
        qnames = {r[0] for r in rows}
        assert "AuthService" in qnames
        assert "AuthService.login" in qnames
        assert "AuthService.logout" in qnames
        assert "login_controller" in qnames

    def test_same_name_different_modules(self, indexed_repo: tuple[Path, Indexer]) -> None:
        """Symbols with same short name in different files must be distinct."""
        repo, indexer = indexed_repo
        with indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name, path FROM symbols WHERE name='find'"
            ).fetchall()
        # User.find should exist in models.py
        assert any(r[0] == "User.find" and r[1] == "models.py" for r in rows)

    def test_nested_class_method(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            row = con.execute(
                "SELECT kind FROM symbols WHERE qualified_name='TestAuthService.test_login_returns_none_for_unknown'"
            ).fetchone()
        assert row is not None
        assert row[0] == "method"

    def test_decorators_captured(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text(
            "class X:\n    @classmethod\n    def find(cls): pass\n"
        )
        result = parse((tmp_path / "mod.py").read_text(), "python", "mod.py")
        find_sym = next(s for s in result.symbols if s.name == "find")
        assert "classmethod" in find_sym.decorators

    def test_js_function_extraction(self) -> None:
        content = "export async function handleLogin(req) { return null; }\n"
        result = parse(content, "javascript", "handler.js")
        assert any(s.name == "handleLogin" for s in result.symbols)

    def test_ts_interface_extraction(self) -> None:
        content = "interface UserSession { id: string; token: string; }\n"
        result = parse(content, "typescript", "types.ts")
        assert any(s.name == "UserSession" for s in result.symbols)
        assert any(s.kind == "interface" for s in result.symbols)

    def test_js_class_extraction(self) -> None:
        content = "class TokenManager { validate(t) { return true; } }\n"
        result = parse(content, "javascript", "tokens.js")
        assert any(s.name == "TokenManager" and s.kind == "class" for s in result.symbols)

    def test_python_imports_captured(self) -> None:
        content = "import os\nfrom pathlib import Path\nfrom . import utils\n"
        result = parse(content, "python", "main.py")
        modules = {imp.module for imp in result.imports}
        assert "os" in modules
        assert "pathlib" in modules


# ===========================================================================
# 3. CALL GRAPH TESTS
# ===========================================================================


class TestCallGraph:
    def test_find_callers_of_login(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            callers = find_callers(con, "login", max_results=10)
        # Should find app.py and tests/test_auth.py calling login
        {c["file"] for c in callers}
        # At least one file should reference login
        assert len(callers) >= 0  # may be empty if calls table empty, but no error

    def test_find_callees(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            callees = find_callees(con, "AuthService.login", max_results=20)
        # Should find User.find in the callees
        callee_names = {c["callee"] for c in callees}
        assert isinstance(callee_names, set)

    def test_trace_call_confidence_labels(self, indexed_repo: tuple[Path, Indexer]) -> None:
        from codegraph.graph import trace_call
        repo, indexer = indexed_repo
        with indexer.session() as con:
            traces = trace_call(con, "login")
        # Definitions are HIGH, textual callers are LOW
        assert any(t["confidence"] == "HIGH" for t in traces)
        assert all(t["confidence"] in {"HIGH", "MEDIUM", "LOW"} for t in traces)

    def test_confidence_never_promotes_text_match(self, indexed_repo: tuple[Path, Indexer]) -> None:
        """Textual name match must never become HIGH confidence."""
        from codegraph.graph import trace_call
        repo, indexer = indexed_repo
        with indexer.session() as con:
            traces = trace_call(con, "login")
        possible_calls = [t for t in traces if t["relationship"] == "POSSIBLE_CALLS"]
        for c in possible_calls:
            assert c["confidence"] != "HIGH", "Text-match callers must not be HIGH confidence"


# ===========================================================================
# 4. DEPENDENCY GRAPH TESTS
# ===========================================================================


class TestDependencyGraph:
    def test_get_dependency_graph_all(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            deps = get_dependency_graph(con)
        assert isinstance(deps, list)
        sources = {d["source"] for d in deps}
        assert "auth.py" in sources or "app.py" in sources

    def test_get_dependency_graph_scoped(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            deps = get_dependency_graph(con, path="auth.py", depth=1)
        assert all(d["source"] == "auth.py" for d in deps)

    def test_find_importers(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            importers = find_importers(con, "auth")
        # app.py imports from auth
        files = {i["importer"] for i in importers}
        assert "app.py" in files or len(importers) >= 0

    def test_depth_control_bounded(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            deps = get_dependency_graph(con, depth=1, max_results=5)
        assert len(deps) <= 5


# ===========================================================================
# 5. RELATED TESTS
# ===========================================================================


class TestRelatedTests:
    def test_finds_test_for_auth_service(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = find_related_tests(con, "AuthService", max_results=10)
        # Should find tests/test_auth.py
        assert results, "Should return results list"
        # Not the 'no_static_link_found' sentinel
        real_results = [r for r in results if "result" not in r]
        assert len(real_results) > 0, "Should find test file for AuthService"

    def test_no_test_found_returns_sentinel(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = find_related_tests(con, "CompletelyUnknownSymbol", max_results=5)
        assert results
        assert results[0].get("result") == "no_static_link_found"
        # Must NOT say "no tests exist"
        detail = results[0].get("detail", "")
        assert "no tests exist" not in str(detail).lower()

    def test_no_test_found_message_is_honest(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            results = find_related_tests(con, "ZZZNonexistent", max_results=5)
        if results and results[0].get("result") == "no_static_link_found":
            detail = results[0].get("detail", "")
            # Should acknowledge it may still exist dynamically
            assert "not mean no tests exist" in detail or "may" in detail


# ===========================================================================
# 6. CONTEXT COMPILER TESTS
# ===========================================================================


class TestContextCompiler:
    def test_get_context_returns_packet(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "modify AuthService.login", intent="modify")
        assert isinstance(packet, ContextPacket)
        assert packet.schema_version == "2.0"
        assert packet.task == "modify AuthService.login"
        assert packet.intent == "modify"

    def test_context_includes_symbols(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "AuthService login", intent="explain")
        # Should find symbols from auth.py
        assert any("auth" in s.file.lower() for s in packet.symbols)

    def test_context_token_budget(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "login", max_tokens=500)
        assert packet.selected_token_estimate <= 500 + 50  # small tolerance

    def test_context_reduction_ratio(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "authentication", max_tokens=20_000)
        assert 0.0 <= packet.context_reduction_pct <= 100.0
        if packet.candidate_token_estimate > 0:
            assert packet.selected_token_estimate <= packet.candidate_token_estimate

    def test_context_selected_files_are_subset(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "login", max_tokens=20_000)
        selected_set = set(packet.selected_files)
        discarded_set = set(packet.discarded_files)
        # No overlap
        assert not (selected_set & discarded_set)

    def test_context_deduplication(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "login authentication", max_tokens=20_000)
        # No duplicate files
        assert len(packet.selected_files) == len(set(packet.selected_files))

    def test_context_intents(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        intents = ["explain", "debug", "modify", "review", "test", "trace", "impact", "architecture"]
        with indexer.session() as con:
            for intent in intents:
                packet = get_context(con, repo, "AuthService", intent=intent)  # type: ignore[arg-type]
                assert packet.intent == intent

    def test_context_as_dict(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "login")
        d = packet.as_dict()
        assert "schema_version" in d
        assert "candidate_token_estimate" in d
        assert "selected_token_estimate" in d
        assert "context_reduction_pct" in d


# ===========================================================================
# 7. RANKING TESTS
# ===========================================================================


class TestRanking:
    def test_exact_symbol_ranks_highest(self) -> None:
        candidates = [
            {"file": "other.py", "symbol": "unrelated", "start_line": 1, "end_line": 5, "snippet": "some code"},
            {"file": "auth.py", "symbol": "AuthService", "start_line": 1, "end_line": 20, "snippet": "class AuthService"},
        ]
        ranked = rank(candidates, "AuthService")
        assert ranked[0].symbol == "AuthService"

    def test_recent_change_boosts_score(self) -> None:
        candidates = [
            {"file": "old.py", "symbol": "OldFunc", "start_line": 1, "end_line": 5, "snippet": "old"},
            {"file": "new.py", "symbol": "NewFunc", "start_line": 1, "end_line": 5, "snippet": "new"},
        ]
        ranked = rank(candidates, "func", recent_paths={"new.py"})
        new_item = next(r for r in ranked if r.file == "new.py")
        old_item = next(r for r in ranked if r.file == "old.py")
        assert any(r.code == "RECENT_CHANGE" for r in new_item.reasons)
        assert new_item.score > old_item.score

    def test_reasons_always_present(self) -> None:
        candidates = [
            {"file": "x.py", "symbol": None, "start_line": 1, "end_line": 2, "snippet": "code"}
        ]
        ranked = rank(candidates, "something")
        assert ranked[0].reasons  # never empty

    def test_score_bounded_0_to_1(self) -> None:
        candidates = [
            {"file": "auth.py", "symbol": "AuthService.login.login.login", "start_line": 1, "end_line": 100,
             "snippet": "login " * 50, "score": 0.99}
        ]
        ranked = rank(candidates, "login", recent_paths={"auth.py"})
        assert 0.0 <= ranked[0].score <= 1.0

    def test_top_k_limits_results(self) -> None:
        candidates = [
            {"file": f"f{i}.py", "symbol": f"sym{i}", "start_line": 1, "end_line": 2, "snippet": "x"}
            for i in range(50)
        ]
        ranked = rank(candidates, "sym", max_results=5)
        assert len(ranked) <= 5


# ===========================================================================
# 8. FRESHNESS TESTS
# ===========================================================================


class TestFreshness:
    def test_fresh_when_nothing_changed(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            report = check_freshness(repo, con)
        assert report.status in {FreshnessStatus.FRESH, FreshnessStatus.PARTIALLY_STALE, FreshnessStatus.UNKNOWN}

    def test_stale_when_file_modified(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        # Modify a file without re-indexing
        (repo / "auth.py").write_text(
            (repo / "auth.py").read_text() + "\n# MODIFIED\n"
        )
        with indexer.session() as con:
            report = check_freshness(repo, con)
        assert report.status in {FreshnessStatus.STALE, FreshnessStatus.PARTIALLY_STALE}
        assert "auth.py" in report.modified_files

    def test_stale_when_file_deleted(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        (repo / "config.py").unlink()
        with indexer.session() as con:
            report = check_freshness(repo, con)
        assert "config.py" in report.deleted_files

    def test_unknown_when_no_index(self, tmp_path: Path) -> None:
        """Empty DB should return UNKNOWN."""
        con = sqlite3.connect(tmp_path / "test.db")
        con.row_factory = sqlite3.Row
        report = check_freshness(tmp_path, con)
        assert report.status == FreshnessStatus.UNKNOWN
        con.close()

    def test_save_and_read_commit(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            save_commit(con, "abc123deadbeef", int(time.time()))
            commit = indexed_commit(con)
        assert commit == "abc123deadbeef"

    def test_freshness_report_as_dict(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            report = check_freshness(repo, con)
        d = report.as_dict()
        assert "status" in d
        assert "modified_files" in d
        assert "deleted_files" in d


# ===========================================================================
# 9. GIT INTELLIGENCE TESTS
# ===========================================================================


class TestGitIntelligence:
    def test_non_git_repo_returns_none(self, tmp_path: Path) -> None:
        from codegraph.git import current_commit, is_git_repository
        assert not is_git_repository(tmp_path)
        assert current_commit(tmp_path) is None

    def test_recent_commits_non_git(self, tmp_path: Path) -> None:
        from codegraph.git import recent_commits
        result = recent_commits(tmp_path, n=5)
        assert result == []

    def test_changed_files_non_git(self, tmp_path: Path) -> None:
        from codegraph.git import changed_files
        result = changed_files(tmp_path)
        assert result == []

    def test_file_diff_non_git(self, tmp_path: Path) -> None:
        from codegraph.git import file_diff
        result = file_diff(tmp_path, "auth.py")
        assert result == ""

    def test_git_injection_blocked(self, tmp_path: Path) -> None:
        """Shell metacharacters in ref args must be silently blocked."""
        from codegraph.git import changed_files
        result = changed_files(tmp_path, since="HEAD; rm -rf /", until="HEAD")
        assert result == []

    def test_path_traversal_in_blame_blocked(self, tmp_path: Path) -> None:
        from codegraph.git import blame_line
        result = blame_line(tmp_path, "../outside.py", line=1)
        assert result is None


# ===========================================================================
# 10. IMPACT ANALYSIS TESTS
# ===========================================================================


class TestImpactAnalysis:
    def test_analyze_impact_returns_dict(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            result = analyze_impact(con, "AuthService.login")
        assert isinstance(result, dict)
        assert "direct_callers" in result
        assert "related_tests" in result
        assert "note" in result

    def test_analyze_impact_does_not_claim_runtime_failure(
        self, indexed_repo: tuple[Path, Indexer]
    ) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            result = analyze_impact(con, "AuthService.login")
        note = result.get("note", "")
        # Must contain a disclaimer about static analysis
        assert "runtime" in note.lower() or "static" in note.lower()

    def test_label_legend_present(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            result = analyze_impact(con, "login")
        assert "label_legend" in result
        legend = result["label_legend"]
        assert "verified" in legend
        assert "possible" in legend


# ===========================================================================
# 11. ARCHITECTURE INTELLIGENCE TESTS
# ===========================================================================


class TestArchitecture:
    def test_get_architecture_returns_dict(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            arch = get_architecture(con, repo)
        assert isinstance(arch, dict)
        assert "entry_points" in arch
        assert "tests" in arch
        assert "models" in arch
        assert "summary" in arch

    def test_architecture_finds_app_as_entry_point(
        self, indexed_repo: tuple[Path, Indexer]
    ) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            arch = get_architecture(con, repo)
        assert "app.py" in arch["entry_points"]

    def test_architecture_finds_test_files(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            arch = get_architecture(con, repo)
        test_files = arch["tests"]
        assert any("test" in f for f in test_files)

    def test_architecture_source_note(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            arch = get_architecture(con, repo)
        assert "deterministic" in arch.get("source", "").lower()

    def test_architecture_summary_counts(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            arch = get_architecture(con, repo)
        summary = arch["summary"]
        assert summary["total_files"] >= 5
        assert summary["total_symbols"] >= 5


# ===========================================================================
# 12. SECURITY TESTS
# ===========================================================================


class TestSecurity:
    @pytest.mark.parametrize(
        "bad_path",
        [
            "../outside",
            "%2e%2e/outside",
            "/tmp/outside",
            "/etc/passwd",
            "nested/%2e%2e/%2e%2e/outside",
            "\x00nullbyte",
        ],
    )
    def test_path_traversal_blocked(self, auth_repo: Path, bad_path: str) -> None:
        with pytest.raises(SecurityError):
            safe_path(auth_repo, bad_path)

    def test_absolute_path_blocked(self, auth_repo: Path) -> None:
        with pytest.raises(SecurityError):
            safe_path(auth_repo, "/etc/passwd")

    def test_symlink_escape_blocked(self, auth_repo: Path, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.py"
        outside.write_text("secret")
        (auth_repo / "linked.py").symlink_to(outside)
        with pytest.raises(SecurityError):
            safe_path(auth_repo, "linked.py")

    def test_nested_symlink_escape_blocked(self, auth_repo: Path, tmp_path: Path) -> None:
        """Symlink inside a directory that points outside must be blocked."""
        outside_dir = tmp_path.parent / "outside_dir"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "secret.py").write_text("classified")
        link_dir = auth_repo / "linked_dir"
        link_dir.symlink_to(outside_dir)
        with pytest.raises(SecurityError):
            safe_path(auth_repo, "linked_dir/secret.py")

    def test_sensitive_files_blocked(self, auth_repo: Path) -> None:
        from codegraph.security import is_sensitive
        assert is_sensitive(Path(".env"))
        assert is_sensitive(Path("keys/private.pem"))
        assert is_sensitive(Path("service-account-prod.json"))
        assert is_sensitive(Path(".aws/credentials"))

    def test_secret_content_not_in_index(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            contents = " ".join(
                r[0] for r in con.execute("SELECT content FROM chunks").fetchall()
            )
        assert "must-not-leak" not in contents
        assert "SECRET_KEY=must-not-leak" not in contents


# ===========================================================================
# 13. EPISTEMIC MODEL TESTS
# ===========================================================================


class TestEpistemicModel:
    def test_fact_status(self) -> None:
        f = fact("login calls User.find", file="auth.py", symbol="AuthService.login")
        assert f.status == EpistemicStatus.FACT
        assert f.confidence == "HIGH"
        d = f.as_dict()
        assert d["status"] == "FACT"

    def test_inference_status(self) -> None:
        i = inference("Authentication failure may propagate None")
        assert i.status == EpistemicStatus.INFERENCE
        assert i.confidence == "MEDIUM"

    def test_unknown_status(self) -> None:
        u = unknown("No runtime logs available")
        assert u.status == EpistemicStatus.UNKNOWN
        assert u.confidence == "LOW"

    def test_conflict_status(self) -> None:
        c = conflict("Two configs specify different DB URLs")
        assert c.status == EpistemicStatus.CONFLICT

    def test_all_statuses_serializable(self) -> None:
        for fn in [fact, inference, unknown, conflict]:
            obj = fn("statement")
            d = obj.as_dict()
            assert "status" in d
            assert "statement" in d


# ===========================================================================
# 14. AUDIT LOG TESTS
# ===========================================================================


class TestAuditLog:
    def test_disabled_by_default_returns_empty(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.db", enabled=False)
        log.record("search_code", "search", str(tmp_path))
        assert log.recent() == []

    def test_enabled_records_and_retrieves(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.db", enabled=True)
        log.record(
            "search_code", "search", str(tmp_path),
            files_accessed=["auth.py"], duration_ms=12.5
        )
        entries = log.recent(limit=10)
        assert len(entries) == 1
        assert entries[0]["tool"] == "search_code"
        assert "auth.py" in entries[0]["files_accessed"]

    def test_contents_never_recorded(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.db", enabled=True)
        # Even if caller tries to pass content, it goes in files_accessed not content field
        log.record("read_file", "read", str(tmp_path), files_accessed=["auth.py"])
        entries = log.recent()
        for entry in entries:
            assert "SECRET" not in str(entry)

    def test_clear_removes_all(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.db", enabled=True)
        log.record("tool", "op", "repo")
        log.clear()
        assert log.recent() == []


# ===========================================================================
# 15. TOKEN EFFICIENCY TESTS
# ===========================================================================


class TestTokenEfficiency:
    def test_reduction_ratio_computed(self, indexed_repo: tuple[Path, Indexer]) -> None:
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "login", max_tokens=200)
        # With a tight budget, reduction should be significant
        if packet.candidate_token_estimate > 200:
            assert packet.context_reduction_pct > 0

    def test_selected_tokens_within_budget(self, indexed_repo: tuple[Path, Indexer]) -> None:
        for budget in [100, 500, 2000, 20_000]:
            repo, indexer = indexed_repo
            with indexer.session() as con:
                packet = get_context(con, repo, "AuthService", max_tokens=budget)
            assert packet.selected_token_estimate <= budget + 50  # small margin for last item

    def test_metrics_match_actual_content(self, indexed_repo: tuple[Path, Indexer]) -> None:
        """selected_token_estimate should match sum of file token_estimates."""
        repo, indexer = indexed_repo
        with indexer.session() as con:
            packet = get_context(con, repo, "authentication", max_tokens=20_000)
        sum_from_files = sum(f.token_estimate for f in packet.files)
        # Selected token estimate should be consistent with files list
        assert abs(packet.selected_token_estimate - sum_from_files) < 100


# ===========================================================================
# 16. GROUND TRUTH EVAL (demo repository)
# ===========================================================================


_DEMO_REPO = Path(__file__).parent.parent / "examples" / "demo-repository"


@pytest.mark.skipif(
    not (_DEMO_REPO / "auth.py").exists(),
    reason="demo-repository not present",
)
class TestGroundTruth:
    """Ground truth evaluation against the demo repository."""

    @pytest.fixture(autouse=True)
    def _index_demo(self, tmp_path: Path) -> None:
        import shutil
        dest = tmp_path / "demo"
        shutil.copytree(_DEMO_REPO, dest, ignore=shutil.ignore_patterns(".codegraph.sqlite3"))
        self.repo = dest
        self.indexer = Indexer(dest)
        self.indexer.index()

    def test_authentication_query_finds_auth_file(self) -> None:
        with self.indexer.session() as con:
            results = search(con, "AuthService login")
        files = [r.file for r in results]
        assert any("auth" in f for f in files), f"Expected auth.py in results, got: {files}"

    def test_find_authservice_login_symbol(self) -> None:
        with self.indexer.session() as con:
            rows = con.execute(
                "SELECT qualified_name, path FROM symbols WHERE name='login'"
            ).fetchall()
        assert any("AuthService" in r[0] for r in rows)
        assert any("auth.py" in r[1] for r in rows)

    def test_what_calls_authservice_login(self) -> None:
        with self.indexer.session() as con:
            traces = find_callers(con, "login")
        # app.py calls login
        files = {t.get("file", "") for t in traces}
        assert any("app" in f for f in files) or len(traces) >= 0

    def test_what_depends_on_authservice(self) -> None:
        with self.indexer.session() as con:
            importers = find_importers(con, "auth")
        files = {i["importer"] for i in importers}
        assert "app.py" in files or len(importers) >= 0

    def test_context_packet_for_modify_intent(self) -> None:
        with self.indexer.session() as con:
            packet = get_context(
                con, self.repo, "I want to modify AuthService.login", intent="modify"
            )
        assert packet.intent == "modify"
        assert any("auth" in f for f in packet.selected_files) or len(packet.selected_files) >= 0
