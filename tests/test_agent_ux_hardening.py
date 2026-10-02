"""Regression test suite for CodeGraph MCP P0 Agent UX Hardening.

Validates:
1. CLI path consistency ([PATH] defaulting to . and -r/--repo)
2. Machine-readable structured error contract (no raw tracebacks)
3. Stable centralized error codes and recovery guidance (next_action)
4. Unified MCP response envelope across all 13 core interrogation tools
5. Explicit symbol semantics without symbol/path ambiguity
6. Deterministic response ordering and identity
7. Path traversal and security boundaries
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.errors import (
    CodeGraphError,
    ErrorCode,
    IndexStaleError,
    InvalidArgumentError,
    InvalidDepthError,
    InvalidModuleError,
    InvalidPathError,
    NotIndexedError,
    ParseFailureError,
    RepositoryNotInitializedError,
    SecurityError,
    SymbolAmbiguousError,
    SymbolNotFoundError,
    UnsupportedLanguageError,
)
from codegraph.indexing import Indexer
from codegraph.interrogation import (
    get_architecture,
    get_callees,
    get_callers,
    get_dependents,
    get_file,
    get_git_impact,
    get_imports,
    get_references,
    get_symbol,
    list_routes,
    resolve_symbol,
    search_symbols,
    trace_path,
)

runner = CliRunner()


@pytest.fixture()
def sample_indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "auth").mkdir()
    (repo / "src" / "admin").mkdir()

    (repo / "src" / "auth" / "service.py").write_text(
        "class AuthService:\n"
        "    def authenticate(self, token: str) -> bool:\n"
        "        return token == 'valid'\n"
        "\n"
        "def check_session(s: str) -> bool:\n"
        "    return len(s) > 0\n",
        encoding="utf-8",
    )

    (repo / "src" / "auth" / "views.py").write_text(
        "from src.auth.service import AuthService\n"
        "\n"
        "def login_handler(token: str) -> dict:\n"
        "    svc = AuthService()\n"
        "    return {'ok': svc.authenticate(token)}\n"
        "\n"
        "def duplicate_action():\n"
        "    return 'auth'\n",
        encoding="utf-8",
    )

    (repo / "src" / "admin" / "views.py").write_text(
        "def duplicate_action():\n"
        "    return 'admin'\n",
        encoding="utf-8",
    )

    (repo / ".env").write_text("API_SECRET=supersecret\n", encoding="utf-8")

    Indexer(repo).index()
    return repo


@pytest.fixture()
def empty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    return repo


# ---------------------------------------------------------------------------
# 1. CLI Path Consistency Tests
# ---------------------------------------------------------------------------
def test_cli_path_consistency_status(sample_indexed_repo: Path) -> None:
    # 1. codegraph status (default to current directory)
    res_default = runner.invoke(app, ["status"], catch_exceptions=False)
    # 2. codegraph status .
    res_dot = runner.invoke(app, ["status", "."], catch_exceptions=False)
    # 3. codegraph status <path>
    res_path = runner.invoke(app, ["status", str(sample_indexed_repo)], catch_exceptions=False)
    # 4. codegraph status -r <path>
    res_opt = runner.invoke(app, ["status", "-r", str(sample_indexed_repo)], catch_exceptions=False)
    # 5. codegraph status --repo <path>
    res_long = runner.invoke(app, ["status", "--repo", str(sample_indexed_repo)], catch_exceptions=False)

    assert res_default.exit_code == 0
    assert res_dot.exit_code == 0
    assert json.loads(res_default.stdout)["repository"] == json.loads(res_dot.stdout)["repository"]
    assert res_path.exit_code == 0
    assert res_opt.exit_code == 0
    assert res_long.exit_code == 0

    data_path = json.loads(res_path.stdout)
    data_opt = json.loads(res_opt.stdout)
    data_long = json.loads(res_long.stdout)

    # All targeting sample_indexed_repo must produce identical repository resolution
    assert data_path["repository"] == str(sample_indexed_repo.resolve())
    assert data_opt["repository"] == str(sample_indexed_repo.resolve())
    assert data_long["repository"] == str(sample_indexed_repo.resolve())
    assert data_path["files"] == data_opt["files"] == data_long["files"]


def test_cli_path_consistency_index(tmp_path: Path) -> None:
    repo = tmp_path / "index_consistency_repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")

    # codegraph index <path>
    res_path = runner.invoke(app, ["index", str(repo)], catch_exceptions=False)
    assert res_path.exit_code == 0

    # codegraph index -r <path>
    res_opt = runner.invoke(app, ["index", "-r", str(repo)], catch_exceptions=False)
    assert res_opt.exit_code == 0


def test_cli_path_consistency_doctor_routes_architecture(sample_indexed_repo: Path) -> None:
    # doctor
    res_doc1 = runner.invoke(app, ["doctor", str(sample_indexed_repo)])
    res_doc2 = runner.invoke(app, ["doctor", "-r", str(sample_indexed_repo)])
    assert res_doc1.exit_code == res_doc2.exit_code == 0
    d1 = json.loads(res_doc1.stdout)
    d2 = json.loads(res_doc2.stdout)
    assert d1["repository"] == d2["repository"] == str(sample_indexed_repo.resolve())

    # routes
    res_r1 = runner.invoke(app, ["routes", str(sample_indexed_repo), "--json"])
    res_r2 = runner.invoke(app, ["routes", "-r", str(sample_indexed_repo), "--json"])
    assert res_r1.exit_code == res_r2.exit_code == 0

    # architecture
    res_a1 = runner.invoke(app, ["architecture", str(sample_indexed_repo)])
    res_a2 = runner.invoke(app, ["architecture", "-r", str(sample_indexed_repo)])
    assert res_a1.exit_code == res_a2.exit_code == 0
    assert json.loads(res_a1.stdout)["repository"] == json.loads(res_a2.stdout)["repository"]


# ---------------------------------------------------------------------------
# 2. Explicit Symbol Semantics CLI Commands
# ---------------------------------------------------------------------------
def test_cli_get_symbol_command(sample_indexed_repo: Path) -> None:
    res = runner.invoke(app, ["get-symbol", "AuthService", "-r", str(sample_indexed_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    assert data["symbol"]["name"] == "AuthService"
    assert data["symbol"]["kind"] == "class"


def test_cli_resolve_symbol_command(sample_indexed_repo: Path) -> None:
    # Ambiguous symbol: duplicate_action
    res = runner.invoke(app, ["resolve-symbol", "duplicate_action", "-r", str(sample_indexed_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ambiguous"
    assert data["error"]["code"] == ErrorCode.SYMBOL_AMBIGUOUS.value
    assert len(data["candidates"]) == 2
    # Verify deterministic ordering
    cids = [c["canonical_id"] for c in data["candidates"]]
    assert cids == sorted(cids)


# ---------------------------------------------------------------------------
# 3. Machine-Readable Structured Error Contract Tests
# ---------------------------------------------------------------------------
def test_error_index_not_found(empty_repo: Path) -> None:
    # Querying unindexed repository produces structured error without traceback
    res = runner.invoke(app, ["status", str(empty_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "error"
    assert data["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value
    assert "No CodeGraph index exists" in data["error"]["message"]
    assert data["error"]["next_action"]["command"] == "codegraph init"

    # Search on unindexed repository
    res_search = runner.invoke(app, ["search", "authenticate", "-r", str(empty_repo)])
    assert res_search.exit_code == 0
    data_search = json.loads(res_search.stdout)
    assert data_search["status"] == "error"
    assert data_search["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value


def test_error_symbol_not_found(sample_indexed_repo: Path) -> None:
    res = runner.invoke(app, ["get-symbol", "NonExistentClass", "-r", str(sample_indexed_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "not_found"
    assert data["error"]["code"] == ErrorCode.SYMBOL_NOT_FOUND.value
    assert "NonExistentClass" in data["error"]["message"]
    assert "next_action" in data["error"]


def test_error_path_outside_repository(sample_indexed_repo: Path) -> None:
    res = runner.invoke(app, ["symbols", "../../etc/passwd", "-r", str(sample_indexed_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "error"
    assert data["error"]["code"] == ErrorCode.PATH_OUTSIDE_REPOSITORY.value
    assert "outside repository" in data["error"]["message"]


def test_error_invalid_path(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist_dir"
    res = runner.invoke(app, ["status", str(non_existent)])
    data = json.loads(res.stdout)
    assert data["status"] == "error"
    assert data["error"]["code"] == ErrorCode.INVALID_PATH.value


def test_error_invalid_depth(sample_indexed_repo: Path) -> None:
    res = runner.invoke(app, ["trace", "AuthService", "--depth", "99", "-r", str(sample_indexed_repo)])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["status"] == "error"
    assert data["error"]["code"] == ErrorCode.INVALID_DEPTH.value


# ---------------------------------------------------------------------------
# 4. Error Model and Recovery Guidance Unit Tests
# ---------------------------------------------------------------------------
def test_error_model_classes() -> None:
    # 1. Base error
    e = CodeGraphError("General failure", code=ErrorCode.INTERNAL_ERROR, next_action={"command": "codegraph doctor"})
    d = e.to_dict()
    assert d["code"] == "INTERNAL_ERROR"
    assert d["message"] == "General failure"
    assert d["next_action"]["command"] == "codegraph doctor"

    # 2. NotIndexedError
    nie = NotIndexedError()
    assert nie.code == ErrorCode.INDEX_NOT_FOUND.value
    assert nie.next_action is not None
    assert nie.next_action["command"] == "codegraph init"

    # 3. IndexStaleError
    ise = IndexStaleError()
    assert ise.code == ErrorCode.INDEX_STALE.value
    assert ise.next_action is not None
    assert ise.next_action["command"] == "codegraph index"

    # 4. SecurityError
    se = SecurityError()
    assert se.code == ErrorCode.PATH_OUTSIDE_REPOSITORY.value
    assert se.next_action is not None
    assert se.next_action["command"] == "codegraph status"

    # 5. SymbolAmbiguousError
    sae = SymbolAmbiguousError("my_func", [{"canonical_id": "a::my_func"}, {"canonical_id": "b::my_func"}])
    assert sae.code == ErrorCode.SYMBOL_AMBIGUOUS.value
    assert len(sae.candidates) == 2

    # 6. ParseFailureError
    pfe = ParseFailureError("syntax_error.py")
    assert pfe.code == ErrorCode.PARSE_FAILURE.value

    # 7. UnsupportedLanguageError
    ule = UnsupportedLanguageError(".rb")
    assert ule.code == ErrorCode.UNSUPPORTED_LANGUAGE.value

    # 8. InvalidModuleError
    ime = InvalidModuleError("unknown_mod")
    assert ime.code == ErrorCode.INVALID_MODULE.value

    # 9. RepositoryNotInitializedError
    rnie = RepositoryNotInitializedError()
    assert rnie.code == ErrorCode.REPOSITORY_NOT_INITIALIZED.value

    # 10. InvalidArgumentError
    iae = InvalidArgumentError("bad_arg")
    assert iae.code == ErrorCode.INVALID_ARGUMENT.value

    # 11. InvalidDepthError
    ide = InvalidDepthError(99)
    assert ide.code == ErrorCode.INVALID_DEPTH.value

    # 12. InvalidPathError
    ipe = InvalidPathError("/bad/path")
    assert ipe.code == ErrorCode.INVALID_PATH.value

    # 13. SymbolNotFoundError
    snfe = SymbolNotFoundError("missing_sym")
    assert snfe.code == ErrorCode.SYMBOL_NOT_FOUND.value


# ---------------------------------------------------------------------------
# 5. All 13 Core MCP Interrogation Tools Contracts
# ---------------------------------------------------------------------------
def test_all_13_tools_unindexed_error_contract(empty_repo: Path) -> None:
    indexer = Indexer(empty_repo)
    with indexer.session() as con:
        # All 13 tools must return status: "error" with code: "INDEX_NOT_FOUND" on unindexed repo
        res1 = resolve_symbol(con, empty_repo, "foo")
        assert res1["status"] == "error"
        assert res1["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res2 = search_symbols(con, empty_repo, "foo")
        assert res2["status"] == "error"
        assert res2["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res3 = get_symbol(con, empty_repo, "foo")
        assert res3["status"] == "error"
        assert res3["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res4 = get_file(con, empty_repo, "foo.py")
        assert res4["status"] == "error"
        assert res4["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res5 = get_references(con, empty_repo, "foo")
        assert res5["status"] == "error"
        assert res5["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res6 = get_callers(con, empty_repo, "foo")
        assert res6["status"] == "error"
        assert res6["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res7 = get_callees(con, empty_repo, "foo")
        assert res7["status"] == "error"
        assert res7["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res8 = trace_path(con, empty_repo, "foo", "bar")
        assert res8["status"] == "error"
        assert res8["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res9 = get_imports(con, empty_repo, file="foo.py")
        assert res9["status"] == "error"
        assert res9["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res10 = get_dependents(con, empty_repo, canonical_id="foo")
        assert res10["status"] == "error"
        assert res10["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res11 = list_routes(con, empty_repo)
        assert res11["status"] == "error"
        assert res11["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res12 = get_architecture(con, empty_repo)
        assert res12["status"] == "error"
        assert res12["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value

        res13 = get_git_impact(con, empty_repo)
        assert res13["status"] == "error"
        assert res13["error"]["code"] == ErrorCode.INDEX_NOT_FOUND.value


def test_all_13_tools_invalid_request_handling(sample_indexed_repo: Path) -> None:
    indexer = Indexer(sample_indexed_repo)
    with indexer.session() as con:
        # 1. resolve_symbol empty
        r1 = resolve_symbol(con, sample_indexed_repo, "   ")
        assert r1["status"] == "invalid_request"
        assert r1["error"]["code"] == ErrorCode.EMPTY_SYMBOL_NAME.value

        # 2. search_symbols empty
        r2 = search_symbols(con, sample_indexed_repo, "")
        assert r2["status"] == "error"
        assert r2["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 3. get_symbol empty
        r3 = get_symbol(con, sample_indexed_repo, "")
        assert r3["status"] == "error"
        assert r3["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 4. get_file path traversal
        r4 = get_file(con, sample_indexed_repo, "../../etc/shadow")
        assert r4["status"] == "error"
        assert r4["error"]["code"] == ErrorCode.PATH_OUTSIDE_REPOSITORY.value

        # 5. get_references empty
        r5 = get_references(con, sample_indexed_repo, "")
        assert r5["status"] == "error"
        assert r5["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 6. get_callers empty
        r6 = get_callers(con, sample_indexed_repo, "")
        assert r6["status"] == "error"
        assert r6["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 7. get_callees empty
        r7 = get_callees(con, sample_indexed_repo, "")
        assert r7["status"] == "error"
        assert r7["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 8. trace_path invalid depth
        r8 = trace_path(con, sample_indexed_repo, "a", "b", max_depth=99)
        assert r8["status"] == "error"
        assert r8["error"]["code"] == ErrorCode.INVALID_DEPTH.value

        # 9. get_imports empty
        r9 = get_imports(con, sample_indexed_repo, file=None, canonical_id=None)
        assert r9["status"] == "invalid_request"
        assert r9["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value

        # 10. get_dependents empty
        r10 = get_dependents(con, sample_indexed_repo, canonical_id=None, file=None)
        assert r10["status"] == "invalid_request"
        assert r10["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value


# ---------------------------------------------------------------------------
# 6. Determinism Invariant Test
# ---------------------------------------------------------------------------
def test_interrogation_determinism_invariant(sample_indexed_repo: Path) -> None:
    """Invariant: same repository + same index generation + same request = identical result."""
    indexer = Indexer(sample_indexed_repo)
    with indexer.session() as con:
        # Run search_symbols 5 times
        runs = [search_symbols(con, sample_indexed_repo, "auth", top_k=10) for _ in range(5)]
        first_json = json.dumps(runs[0], sort_keys=True)
        for r in runs[1:]:
            assert json.dumps(r, sort_keys=True) == first_json

        # Run resolve_symbol on ambiguous target 5 times
        runs_amb = [resolve_symbol(con, sample_indexed_repo, "duplicate_action") for _ in range(5)]
        first_amb_json = json.dumps(runs_amb[0], sort_keys=True)
        for r in runs_amb[1:]:
            assert json.dumps(r, sort_keys=True) == first_amb_json
            # Verify candidate list ordering is identical
            assert [c["canonical_id"] for c in r["candidates"]] == [
                c["canonical_id"] for c in runs_amb[0]["candidates"]
            ]
