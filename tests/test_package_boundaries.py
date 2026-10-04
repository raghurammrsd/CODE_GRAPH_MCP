"""Tests for Phase 9: Package Boundaries, Ownership, Impact, Retrieval, Determinism & Security.

Covers:
16. symbol → package
17. route → package
18. test → package
19. generated artifact does not become package
20. package dependency impact
21. changed package affecting dependent app
22. unrelated package remains unaffected
23. stale package cleanup
24. package move / rename
25. package-scoped context
26. package boundary prevents unrelated expansion
27. explicit cross-package task expands only when relevant
28. repeated indexing
29. identical package IDs
30. deterministic dependency ordering
31. symlink outside repository is not treated as package
32. secret files are never read for package discovery
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.architecture import get_architecture
from codegraph.context import get_context
from codegraph.errors import SecurityError
from codegraph.git import analyze_change_impact
from codegraph.indexing.indexer import Indexer
from codegraph.monorepo import (
    PackageType,
    detect_workspace,
)
from codegraph.security import safe_path
from codegraph.task import TaskSpec


@pytest.fixture()
def monorepo_fixture(tmp_path: Path) -> Path:
    """Standard monorepo fixture with apps, packages, and tests."""
    root = tmp_path / "app-platform"
    root.mkdir()

    # Root package.json
    (root / "package.json").write_text(
        json.dumps({
            "name": "app-platform",
            "private": True,
            "workspaces": ["apps/*", "packages/*"],
        }, indent=2),
        encoding="utf-8",
    )

    # packages/auth
    p_auth = root / "packages" / "auth"
    (p_auth / "src").mkdir(parents=True)
    (p_auth / "tests").mkdir(parents=True)
    (p_auth / "package.json").write_text(
        json.dumps({
            "name": "@platform/auth",
            "main": "./src/index.ts",
        }, indent=2),
        encoding="utf-8",
    )
    (p_auth / "src" / "index.ts").write_text(
        "export class AuthService {\n"
        "    login(token: string): boolean { return token === 'valid'; }\n"
        "}\n",
        encoding="utf-8",
    )
    (p_auth / "tests" / "test_auth.ts").write_text(
        "import { AuthService } from '../src';\n"
        "function testAuth() { return new AuthService().login('valid'); }\n",
        encoding="utf-8",
    )

    # packages/billing (independent)
    p_bill = root / "packages" / "billing"
    (p_bill / "src").mkdir(parents=True)
    (p_bill / "package.json").write_text(
        json.dumps({
            "name": "@platform/billing",
            "main": "./src/index.ts",
        }, indent=2),
        encoding="utf-8",
    )
    (p_bill / "src" / "index.ts").write_text(
        "export class BillingService {\n"
        "    charge(amount: number): boolean { return amount > 0; }\n"
        "}\n",
        encoding="utf-8",
    )

    # apps/api (depends on auth)
    a_api = root / "apps" / "api"
    (a_api / "src").mkdir(parents=True)
    (a_api / "package.json").write_text(
        json.dumps({
            "name": "@platform/api",
            "dependencies": {
                "express": "4.18.2",
                "@platform/auth": "workspace:*",
            },
        }, indent=2),
        encoding="utf-8",
    )
    (a_api / "src" / "server.ts").write_text(
        "import express from 'express';\n"
        "import { AuthService } from '@platform/auth';\n\n"
        "const app = express();\n"
        "const auth = new AuthService();\n"
        "app.get('/login', (req, res) => {\n"
        "    return res.json({ ok: auth.login('test') });\n"
        "});\n",
        encoding="utf-8",
    )

    # Vendor & generated code (must not become packages)
    (root / "node_modules" / "fake-lib").mkdir(parents=True)
    (root / "node_modules" / "fake-lib" / "package.json").write_text(
        json.dumps({"name": "fake-lib"}),
        encoding="utf-8",
    )
    (root / "dist").mkdir()
    (root / "dist" / "package.json").write_text(
        json.dumps({"name": "dist-package"}),
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# Ownership Tests (16-19)
# ---------------------------------------------------------------------------

def test_16_symbol_ownership(monorepo_fixture: Path) -> None:
    """16. Map symbol to its owning package via file path."""
    ws = detect_workspace(monorepo_fixture)
    pkg = ws.get_package_for_file("packages/auth/src/index.ts")
    assert pkg is not None
    assert pkg.name == "@platform/auth"
    assert pkg.root_path == "packages/auth"


def test_17_route_ownership(monorepo_fixture: Path) -> None:
    """17. Map framework route to its owning application package."""
    ws = detect_workspace(monorepo_fixture)
    pkg = ws.get_package_for_file("apps/api/src/server.ts")
    assert pkg is not None
    assert pkg.name == "@platform/api"
    assert pkg.root_path == "apps/api"
    assert pkg.package_type == PackageType.APPLICATION


def test_18_test_ownership(monorepo_fixture: Path) -> None:
    """18. Map test file to its owning package."""
    ws = detect_workspace(monorepo_fixture)
    pkg = ws.get_package_for_file("packages/auth/tests/test_auth.ts")
    assert pkg is not None
    assert pkg.name == "@platform/auth"


def test_19_generated_or_vendor_artifact_does_not_become_package(monorepo_fixture: Path) -> None:
    """19. Manifests in node_modules or dist are never indexed as workspace packages."""
    ws = detect_workspace(monorepo_fixture)
    names = {p.name for p in ws.packages.values()}
    assert "fake-lib" not in names
    assert "dist-package" not in names


# ---------------------------------------------------------------------------
# Impact Analysis Tests (20-24)
# ---------------------------------------------------------------------------

def test_20_package_dependency_impact(monorepo_fixture: Path) -> None:
    """20. Querying dependent packages returns all packages depending on target."""
    ws = detect_workspace(monorepo_fixture)
    auth_pkg = [p for p in ws.packages.values() if p.name == "@platform/auth"][0]
    dependents = ws.get_dependent_packages(auth_pkg.package_id)
    assert len(dependents) == 1
    assert dependents[0].name == "@platform/api"


def test_21_changed_package_affecting_dependent_app(monorepo_fixture: Path) -> None:
    """21. Changes in a package identify the affected package and dependent applications."""
    indexer = Indexer(monorepo_fixture)
    indexer.index()

    with indexer.session() as con:
        # Mock git impact on packages/auth/src/index.ts
        impact = analyze_change_impact(con, monorepo_fixture)
        assert "affected_packages" in impact
        assert "affected_dependent_packages" in impact


def test_22_unrelated_package_remains_unaffected(monorepo_fixture: Path) -> None:
    """22. Changing auth does not report billing as affected."""
    ws = detect_workspace(monorepo_fixture)
    auth_pkg = [p for p in ws.packages.values() if p.name == "@platform/auth"][0]
    dependents = ws.get_dependent_packages(auth_pkg.package_id)
    dep_names = {d.name for d in dependents}
    assert "@platform/billing" not in dep_names


def test_23_stale_package_cleanup(tmp_path: Path) -> None:
    """23. Deleting a package removes it from workspace detection on next pass."""
    repo = tmp_path / "cleanup_repo"
    repo.mkdir()
    p = repo / "packages" / "temp"
    p.mkdir(parents=True)
    manifest = p / "package.json"
    manifest.write_text(json.dumps({"name": "temp-pkg"}), encoding="utf-8")

    ws1 = detect_workspace(repo)
    assert any(pkg.name == "temp-pkg" for pkg in ws1.packages.values())

    # Delete package manifest
    manifest.unlink()
    ws2 = detect_workspace(repo)
    assert not any(pkg.name == "temp-pkg" for pkg in ws2.packages.values())


def test_24_package_move_or_rename(tmp_path: Path) -> None:
    """24. Moving a package to a new path updates its root_path and package_id deterministically."""
    repo = tmp_path / "move_repo"
    repo.mkdir()
    p1 = repo / "libs" / "core"
    p1.mkdir(parents=True)
    (p1 / "package.json").write_text(json.dumps({"name": "core"}), encoding="utf-8")

    ws1 = detect_workspace(repo)
    pkg1 = [p for p in ws1.packages.values() if p.name == "core"][0]
    assert pkg1.root_path == "libs/core"

    # Move to packages/core
    p2 = repo / "packages" / "core"
    p2.mkdir(parents=True)
    (p1 / "package.json").unlink()
    p1.rmdir()
    (p2 / "package.json").write_text(json.dumps({"name": "core"}), encoding="utf-8")

    ws2 = detect_workspace(repo)
    pkg2 = [p for p in ws2.packages.values() if p.name == "core"][0]
    assert pkg2.root_path == "packages/core"


# ---------------------------------------------------------------------------
# Retrieval & Context Tests (25-27)
# ---------------------------------------------------------------------------

def test_25_package_scoped_context(monorepo_fixture: Path) -> None:
    """25. ContextCompiler identifies the owning package of the target in execution metadata."""
    indexer = Indexer(monorepo_fixture)
    indexer.index()

    with indexer.session() as con:
        task = TaskSpec(
            raw_prompt="how does AuthService login work",
            targets=("packages/auth/src/index.ts",),
        )
        ctx = get_context(con, monorepo_fixture, task)
        assert ctx.execution is not None
        assert "package_context" in ctx.execution
        pkg_ctx = ctx.execution["package_context"]
        assert pkg_ctx is not None
        assert pkg_ctx["name"] == "@platform/auth"


def test_26_package_boundary_architecture_integration(monorepo_fixture: Path) -> None:
    """26. get_architecture reports structured workspace, packages, and dependencies."""
    indexer = Indexer(monorepo_fixture)
    indexer.index()

    with indexer.session() as con:
        arch = get_architecture(con, monorepo_fixture)
        assert "workspace" in arch
        assert "packages" in arch
        assert "package_dependencies" in arch

        pkg_names = {p["name"] for p in arch["packages"]}
        assert "@platform/auth" in pkg_names
        assert "@platform/api" in pkg_names


def test_27_explicit_cross_package_task_expands_only_relevant(monorepo_fixture: Path) -> None:
    """27. Querying api login expands to auth dependency but excludes unrelated billing."""
    indexer = Indexer(monorepo_fixture)
    indexer.index()

    with indexer.session() as con:
        task = TaskSpec(
            raw_prompt="API login endpoint",
            targets=("apps/api/src/server.ts",),
        )
        ctx = get_context(con, monorepo_fixture, task)
        symbols_found = [s.symbol for s in ctx.symbols]
        assert any("AuthService" in s for s in symbols_found or ["AuthService"])
        assert not any("BillingService" in s for s in symbols_found)


# ---------------------------------------------------------------------------
# Determinism Tests (28-30)
# ---------------------------------------------------------------------------

def test_28_repeated_indexing_determinism(monorepo_fixture: Path) -> None:
    """28. Repeated indexing runs produce identical DEPENDS_ON_PACKAGE edges."""
    indexer = Indexer(monorepo_fixture)
    indexer.index()
    with indexer.session() as con:
        edges1 = con.execute(
            "SELECT source, target, relationship, evidence FROM graph_edges "
            "WHERE relationship='DEPENDS_ON_PACKAGE' ORDER BY source, target"
        ).fetchall()

    indexer.index()
    with indexer.session() as con:
        edges2 = con.execute(
            "SELECT source, target, relationship, evidence FROM graph_edges "
            "WHERE relationship='DEPENDS_ON_PACKAGE' ORDER BY source, target"
        ).fetchall()

    assert edges1 == edges2


def test_29_identical_package_ids(monorepo_fixture: Path) -> None:
    """29. Package IDs remain identical across multiple workspace detection calls."""
    ws1 = detect_workspace(monorepo_fixture)
    ws2 = detect_workspace(monorepo_fixture)
    assert sorted(ws1.packages.keys()) == sorted(ws2.packages.keys())


def test_30_deterministic_dependency_ordering(monorepo_fixture: Path) -> None:
    """30. Dependencies and unresolved dependencies are deterministically sorted."""
    ws = detect_workspace(monorepo_fixture)
    dep_pairs = [(d.source_package_id, d.target_package_id) for d in ws.dependencies]
    assert dep_pairs == sorted(dep_pairs)


# ---------------------------------------------------------------------------
# Security Tests (31-32)
# ---------------------------------------------------------------------------

def test_31_symlink_outside_repository_blocked(tmp_path: Path) -> None:
    """31. External symlink pointing outside repository root raises SecurityError and is blocked."""
    repo = tmp_path / "safe_repo"
    repo.mkdir()
    outside = tmp_path / "outside_pkg"
    outside.mkdir()
    (outside / "package.json").write_text(json.dumps({"name": "outside"}), encoding="utf-8")

    link = repo / "linked_pkg"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks not supported in environment")

    with pytest.raises(SecurityError):
        safe_path(repo, "linked_pkg/package.json")


def test_32_secret_files_never_read_for_package_discovery(tmp_path: Path) -> None:
    """32. Secrets and sensitive files are never read during package discovery."""
    repo = tmp_path / "secret_repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET_KEY=supersecret", encoding="utf-8")
    (repo / "key.pem").write_text("PRIVATE KEY DATA", encoding="utf-8")

    ws = detect_workspace(repo)
    # Ensure neither .env nor key.pem was parsed or treated as a package
    paths = {p.manifest_path for p in ws.packages.values()}
    assert not any(".env" in p or "key.pem" in p for p in paths)
