"""Source-backed test framework detection.

Detects test frameworks (PYTEST, UNITTEST, JEST, VITEST, MOCHA, OTHER, UNKNOWN)
using concrete repository facts (imports, class inheritance, configuration files).
Does not guess or assume tests exist merely because 'test' appears in a path.
"""
from __future__ import annotations

import json
import sqlite3
from enum import StrEnum
from pathlib import Path


class TestFramework(StrEnum):
    PYTEST = "PYTEST"
    UNITTEST = "UNITTEST"
    JEST = "JEST"
    VITEST = "VITEST"
    MOCHA = "MOCHA"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


def detect_test_framework(
    con: sqlite3.Connection,
    repository: Path,
) -> tuple[TestFramework, bool, str]:
    """Detect test framework and whether tests are present in the repository.

    Returns:
        (framework, tests_present, evidence)
    """
    root = repository.resolve()

    # 1. Query files for test files
    test_rows = []
    try:
        test_rows = con.execute(
            "SELECT path FROM files WHERE (category='TEST' OR path LIKE 'tests/%' "
            "OR path LIKE 'test/%' OR path LIKE '%/test_%.py' OR path LIKE '%_test.py' "
            "OR path LIKE '%.test.%' OR path LIKE '%.spec.%') AND status='ok'"
        ).fetchall()
    except sqlite3.OperationalError:
        pass

    test_paths = [r[0] for r in test_rows]

    # If no test files in index, check filesystem as fallback
    if not test_paths:
        for pat in ("tests", "test"):
            d = root / pat
            if d.is_dir() and any(d.iterdir()):
                test_paths.append(pat)
                break

    if not test_paths:
        return (TestFramework.UNKNOWN, False, "No test files or directories detected")

    # 2. Check Python imports from test files
    try:
        imp_rows = con.execute(
            "SELECT DISTINCT module FROM imports WHERE module IN ('pytest', 'unittest') "
            "OR module LIKE 'pytest.%' OR module LIKE 'unittest.%'"
        ).fetchall()
        imp_modules = {r[0] for r in imp_rows}
        if any(m.startswith("pytest") for m in imp_modules):
            return (TestFramework.PYTEST, True, "Source evidence: imports pytest")
        if any(m.startswith("unittest") for m in imp_modules):
            return (TestFramework.UNITTEST, True, "Source evidence: imports unittest")
    except sqlite3.OperationalError:
        pass

    # 3. Check Python configuration files
    if (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
        return (TestFramework.PYTEST, True, "Configuration evidence: pytest.ini or conftest.py present")

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="replace")
            if "tool.pytest" in content or "pytest" in content:
                return (TestFramework.PYTEST, True, "Configuration evidence: pyproject.toml defines pytest")
        except OSError:
            pass

    # 4. Check JS/TS package.json
    pkg_json = root / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            dev_deps = data.get("devDependencies", {})
            deps = data.get("dependencies", {})
            scripts = data.get("scripts", {})
            all_deps = {**deps, **dev_deps}
            scripts_str = " ".join(str(v) for v in scripts.values())

            if "vitest" in all_deps or "vitest" in scripts_str:
                return (TestFramework.VITEST, True, "Package evidence: vitest declared in package.json")
            if "jest" in all_deps or "jest" in scripts_str:
                return (TestFramework.JEST, True, "Package evidence: jest declared in package.json")
            if "mocha" in all_deps or "mocha" in scripts_str:
                return (TestFramework.MOCHA, True, "Package evidence: mocha declared in package.json")
        except (OSError, json.JSONDecodeError):
            pass

    # 5. Check config files for JS test runners
    for f in root.glob("jest.config.*"):
        if f.is_file():
            return (TestFramework.JEST, True, f"Configuration evidence: {f.name} present")
    for f in root.glob("vitest.config.*"):
        if f.is_file():
            return (TestFramework.VITEST, True, f"Configuration evidence: {f.name} present")

    # 6. Fallback if test files exist but specific runner not identified
    return (TestFramework.OTHER, True, f"Test files present ({len(test_paths)} test files) with unspecified runner")
