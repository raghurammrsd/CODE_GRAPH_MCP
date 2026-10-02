"""Tests for symbol grounding and target ambiguity detection."""
import sqlite3

import pytest

from codegraph.indexing.indexer import SCHEMA
from codegraph.task import (
    AmbiguityStatus,
    detect_target_ambiguity,
    normalize_task_spec,
)


@pytest.fixture
def test_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    # Populate dummy files
    con.execute("INSERT INTO files (path, hash, language) VALUES (?, ?, ?)",
                ("src/auth.py", "h1", "python"))
    con.execute("INSERT INTO files (path, hash, language) VALUES (?, ?, ?)",
                ("src/api.py", "h2", "python"))
    con.execute("INSERT INTO files (path, hash, language) VALUES (?, ?, ?)",
                ("tests/test_auth.py", "h3", "python"))

    # Unique symbol
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/auth.py::TokenValidator", "TokenValidator", "TokenValidator", "src/auth.py", 10, 50, "class", "python"),
    )

    # Ambiguous symbols across src/auth.py and src/api.py
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/auth.py::authenticate", "authenticate", "authenticate", "src/auth.py", 60, 80, "function", "python"),
    )
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/api.py::authenticate", "authenticate", "authenticate", "src/api.py", 10, 30, "function", "python"),
    )

    # Symbol with test counterpart -> triggers ASSUMED
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/auth.py::create_session", "create_session", "create_session", "src/auth.py", 90, 110, "function", "python"),
    )
    con.execute(
        "INSERT INTO symbols (canonical_id, name, qualified_name, path, start_line, end_line, kind, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("tests/test_auth.py::create_session", "create_session", "create_session", "tests/test_auth.py", 20, 40, "function", "python"),
    )

    # Framework route
    con.execute(
        "INSERT INTO framework_routes (endpoint_id, framework, http_method, route_path, normalized_route, handler_name, handler_canonical_id, file_path, line, evidence, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("POST /api/v1/login", "fastapi", "POST", "/api/v1/login", "/api/v1/login", "login_endpoint", "src/api.py::login_endpoint", "src/api.py", 40, "route decorator", "HIGH"),
    )

    con.commit()
    return con


def test_ambiguity_exact_canonical_id(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("src/auth.py::TokenValidator", test_db)
    assert res.status == AmbiguityStatus.CLEAR
    assert len(res.candidates) == 1
    assert res.candidates[0].canonical_id == "src/auth.py::TokenValidator"


def test_ambiguity_unique_symbol_name(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("TokenValidator", test_db)
    assert res.status == AmbiguityStatus.CLEAR
    assert len(res.candidates) == 1
    assert res.candidates[0].name == "TokenValidator"


def test_ambiguity_ambiguous_across_source_files(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("authenticate", test_db)
    assert res.status == AmbiguityStatus.AMBIGUOUS
    assert len(res.candidates) == 2
    paths = {c.path for c in res.candidates}
    assert paths == {"src/auth.py", "src/api.py"}


def test_ambiguity_assumed_for_source_vs_test(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("create_session", test_db)
    assert res.status == AmbiguityStatus.ASSUMED
    assert res.assumption is not None
    assert "src/auth.py" in res.assumption


def test_ambiguity_framework_route(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("POST /api/v1/login", test_db)
    assert res.status == AmbiguityStatus.CLEAR
    assert len(res.candidates) == 1
    assert res.candidates[0].kind == "endpoint"


def test_ambiguity_file_path(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("src/auth.py", test_db)
    assert res.status == AmbiguityStatus.CLEAR
    assert res.candidates[0].kind == "file"


def test_ambiguity_unknown(test_db: sqlite3.Connection) -> None:
    res = detect_target_ambiguity("NonExistentHelper", test_db)
    assert res.status == AmbiguityStatus.UNKNOWN
    assert len(res.candidates) == 0


def test_normalize_task_spec_with_grounding(test_db: sqlite3.Connection) -> None:
    spec, ambiguities = normalize_task_spec(
        "Fix bug in authenticate and TokenValidator",
        con=test_db,
    )
    assert len(ambiguities) >= 2
    # One of them should be AMBIGUOUS because 'authenticate' has 2 candidates
    assert any(a.status == AmbiguityStatus.AMBIGUOUS for a in ambiguities)
    assert len(spec.ambiguities) > 0
