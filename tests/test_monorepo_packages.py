"""Tests for Phase 9: Monorepo, Workspace & Package Boundary Intelligence.

Covers:
1. npm workspaces
2. pnpm workspace
3. Yarn workspaces
4. Python package with pyproject.toml
5. Multiple independent packages
6. Nested package roots
7. Package without explicit workspace metadata
8. Unknown package type
9. Package-to-package dependency
10. workspace:* dependency
11. Direct package import
12. Unresolved workspace dependency
13. Duplicate package names (collision-safety)
14. Package export resolution
15. Cross-package symbol resolution
26. Real-World Monorepo Fixture (company-platform)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.indexing.indexer import Indexer
from codegraph.monorepo import (
    PackageType,
    detect_workspace,
)

# ---------------------------------------------------------------------------
# Section 26: Real-World Monorepo Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def company_platform(tmp_path: Path) -> Path:
    """Fixture implementing Section 26: Real-World Monorepo Fixture."""
    root = tmp_path / "company-platform"
    root.mkdir()

    # Root package.json with npm workspaces
    (root / "package.json").write_text(
        json.dumps({
            "name": "company-platform",
            "private": True,
            "workspaces": ["apps/*", "packages/*", "services/*"],
        }, indent=2),
        encoding="utf-8",
    )

    # packages/shared
    p_shared = root / "packages" / "shared"
    (p_shared / "src").mkdir(parents=True)
    (p_shared / "package.json").write_text(
        json.dumps({
            "name": "@company/shared",
            "version": "1.0.0",
            "main": "./src/index.ts",
        }, indent=2),
        encoding="utf-8",
    )
    (p_shared / "src" / "index.ts").write_text(
        "export function formatCurrency(amount: number): string { return '$' + amount; }\n",
        encoding="utf-8",
    )

    # packages/database
    p_db = root / "packages" / "database"
    (p_db / "src").mkdir(parents=True)
    (p_db / "package.json").write_text(
        json.dumps({
            "name": "@company/database",
            "version": "1.0.0",
            "main": "./src/index.ts",
        }, indent=2),
        encoding="utf-8",
    )
    (p_db / "src" / "index.ts").write_text(
        "export class DatabaseClient {\n    query(sql: string) { return []; }\n}\n",
        encoding="utf-8",
    )

    # packages/auth (depends on database)
    p_auth = root / "packages" / "auth"
    (p_auth / "src").mkdir(parents=True)
    (p_auth / "package.json").write_text(
        json.dumps({
            "name": "@company/auth",
            "version": "1.0.0",
            "main": "./src/index.ts",
            "dependencies": {
                "@company/database": "workspace:*",
            },
        }, indent=2),
        encoding="utf-8",
    )
    (p_auth / "src" / "index.ts").write_text(
        "import { DatabaseClient } from '@company/database';\n\n"
        "export class AuthService {\n"
        "    constructor(private db: DatabaseClient) {}\n"
        "    authenticate(token: string): boolean { return token === 'secret'; }\n"
        "}\n",
        encoding="utf-8",
    )

    # apps/web (depends on auth, shared)
    a_web = root / "apps" / "web"
    (a_web / "src").mkdir(parents=True)
    (a_web / "package.json").write_text(
        json.dumps({
            "name": "@company/web",
            "version": "1.0.0",
            "dependencies": {
                "next": "^14.0.0",
                "@company/auth": "workspace:*",
                "@company/shared": "workspace:*",
            },
        }, indent=2),
        encoding="utf-8",
    )
    (a_web / "src" / "app.ts").write_text(
        "import { AuthService } from '@company/auth';\n"
        "import { formatCurrency } from '@company/shared';\n\n"
        "export function renderPage() {\n"
        "    return formatCurrency(100);\n"
        "}\n",
        encoding="utf-8",
    )

    # apps/api (depends on auth, database, shared)
    a_api = root / "apps" / "api"
    (a_api / "src").mkdir(parents=True)
    (a_api / "package.json").write_text(
        json.dumps({
            "name": "@company/api",
            "version": "1.0.0",
            "dependencies": {
                "express": "^4.18.0",
                "@company/auth": "workspace:*",
                "@company/database": "workspace:*",
                "@company/shared": "workspace:*",
            },
        }, indent=2),
        encoding="utf-8",
    )
    (a_api / "src" / "server.ts").write_text(
        "import express from 'express';\n"
        "import { AuthService } from '@company/auth';\n"
        "import { DatabaseClient } from '@company/database';\n\n"
        "const app = express();\n"
        "const db = new DatabaseClient();\n"
        "const auth = new AuthService(db);\n"
        "app.get('/login', (req, res) => {\n"
        "    return res.json({ ok: auth.authenticate('test') });\n"
        "});\n",
        encoding="utf-8",
    )

    # services/payments (depends on database)
    s_pay = root / "services" / "payments"
    (s_pay / "src").mkdir(parents=True)
    (s_pay / "package.json").write_text(
        json.dumps({
            "name": "@company/payments-service",
            "version": "1.0.0",
            "dependencies": {
                "@company/database": "workspace:*",
                "kafka": "^0.2.0",
            },
        }, indent=2),
        encoding="utf-8",
    )
    (s_pay / "src" / "worker.ts").write_text(
        "import { DatabaseClient } from '@company/database';\n"
        "export function startPaymentWorker() { return new DatabaseClient(); }\n",
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# Workspace Detection Tests (1-8)
# ---------------------------------------------------------------------------

def test_01_npm_workspaces(tmp_path: Path) -> None:
    """1. Detect npm workspaces declared via root package.json."""
    repo = tmp_path / "npm_repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "my-monorepo", "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    pkg_a = repo / "packages" / "pkg-a"
    pkg_a.mkdir(parents=True)
    (pkg_a / "package.json").write_text(
        json.dumps({"name": "pkg-a", "main": "index.js"}),
        encoding="utf-8",
    )
    (pkg_a / "index.js").write_text("module.exports = {};", encoding="utf-8")

    ws = detect_workspace(repo)
    assert ws.workspace_type == "npm"
    assert ws.workspace_id == "my-monorepo"
    assert "my-monorepo::packages/pkg-a" in ws.packages
    pkg = ws.packages["my-monorepo::packages/pkg-a"]
    assert pkg.name == "pkg-a"
    assert pkg.root_path == "packages/pkg-a"
    assert pkg.package_type == PackageType.LIBRARY


def test_02_pnpm_workspace(tmp_path: Path) -> None:
    """2. Detect pnpm workspace declared via pnpm-workspace.yaml."""
    repo = tmp_path / "pnpm_repo"
    repo.mkdir()
    (repo / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'libs/*'\n",
        encoding="utf-8",
    )
    lib = repo / "libs" / "core"
    lib.mkdir(parents=True)
    (lib / "package.json").write_text(
        json.dumps({"name": "@pnpm/core", "main": "index.ts"}),
        encoding="utf-8",
    )
    (lib / "index.ts").write_text("export const version = '1.0';", encoding="utf-8")

    ws = detect_workspace(repo)
    assert ws.workspace_type == "pnpm"
    assert any(p.name == "@pnpm/core" for p in ws.packages.values())


def test_03_yarn_workspaces(tmp_path: Path) -> None:
    """3. Detect Yarn workspaces object in package.json."""
    repo = tmp_path / "yarn_repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "yarn-mono", "workspaces": {"packages": ["modules/*"]}}),
        encoding="utf-8",
    )
    mod = repo / "modules" / "utils"
    mod.mkdir(parents=True)
    (mod / "package.json").write_text(
        json.dumps({"name": "utils", "main": "index.js"}),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    assert ws.workspace_type in ("npm", "yarn")
    assert any(p.name == "utils" for p in ws.packages.values())


def test_04_python_pyproject_toml(tmp_path: Path) -> None:
    """4. Detect Python packages configured via pyproject.toml."""
    repo = tmp_path / "py_repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'py-mono'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    pkg = repo / "packages" / "auth"
    pkg.mkdir(parents=True)
    (pkg / "pyproject.toml").write_text(
        "[project]\nname = 'py-auth'\nversion = '0.1.0'\ndependencies = ['fastapi>=0.100.0']\n",
        encoding="utf-8",
    )
    (pkg / "auth.py").write_text("def auth(): pass\n", encoding="utf-8")

    ws = detect_workspace(repo)
    assert any(p.name == "py-auth" for p in ws.packages.values())
    p_info = [p for p in ws.packages.values() if p.name == "py-auth"][0]
    assert p_info.package_type == PackageType.APPLICATION  # Evidence: fastapi dependency
    assert p_info.language == "python"


def test_05_multiple_independent_packages(tmp_path: Path) -> None:
    """5. Detect multiple independent packages without a root workspace manifest."""
    repo = tmp_path / "multi_repo"
    repo.mkdir()
    (repo / "service_a").mkdir()
    (repo / "service_a" / "package.json").write_text(
        json.dumps({"name": "service-a", "main": "index.js"}),
        encoding="utf-8",
    )
    (repo / "service_b").mkdir()
    (repo / "service_b" / "package.json").write_text(
        json.dumps({"name": "service-b", "main": "index.js"}),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    assert len(ws.packages) == 2
    names = {p.name for p in ws.packages.values()}
    assert names == {"service-a", "service-b"}


def test_06_nested_package_roots(tmp_path: Path) -> None:
    """6. Correctly identify deeply nested package roots."""
    repo = tmp_path / "nested_repo"
    repo.mkdir()
    deep = repo / "tools" / "internal" / "cli"
    deep.mkdir(parents=True)
    (deep / "package.json").write_text(
        json.dumps({"name": "internal-cli", "bin": "./bin/run.js"}),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    assert any(p.root_path == "tools/internal/cli" for p in ws.packages.values())


def test_07_package_without_explicit_workspace_metadata(tmp_path: Path) -> None:
    """7. Discovers package local metadata when not in root workspace patterns."""
    repo = tmp_path / "standalone_repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "my-app", "dependencies": {"express": "4.18.2"}}),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    assert len(ws.packages) == 1
    root_pkg = list(ws.packages.values())[0]
    assert root_pkg.name == "my-app"
    assert root_pkg.package_type == PackageType.APPLICATION


def test_08_unknown_package_type(tmp_path: Path) -> None:
    """8. Empty package without frameworks, entrypoints, or bins classifies as UNKNOWN."""
    repo = tmp_path / "unknown_repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "empty-pkg"}),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    pkg = list(ws.packages.values())[0]
    assert pkg.package_type == PackageType.UNKNOWN


# ---------------------------------------------------------------------------
# Dependency & Resolution Tests (9-15)
# ---------------------------------------------------------------------------

def test_09_package_to_package_dependency(company_platform: Path) -> None:
    """9. Prove package-to-package dependency from manifest evidence."""
    ws = detect_workspace(company_platform)
    assert len(ws.dependencies) > 0

    deps_by_src = {d.source_name: [] for d in ws.dependencies}
    for d in ws.dependencies:
        deps_by_src[d.source_name].append(d.target_name)

    assert "@company/database" in deps_by_src["@company/auth"]
    assert "@company/auth" in deps_by_src["@company/web"]
    assert "@company/shared" in deps_by_src["@company/web"]
    assert "@company/database" in deps_by_src["@company/payments-service"]


def test_10_workspace_star_dependency(company_platform: Path) -> None:
    """10. Correctly parses and marks workspace:* specifier in dependencies."""
    ws = detect_workspace(company_platform)
    ws_deps = [d for d in ws.dependencies if d.is_workspace]
    assert len(ws_deps) > 0
    assert any(d.specifier == "workspace:*" for d in ws_deps)


def test_11_direct_package_import(company_platform: Path) -> None:
    """11. Cross-package import resolves to entrypoint file."""
    ws = detect_workspace(company_platform)
    pkg, entrypoint = ws.resolve_package_import("@company/database")
    assert pkg is not None
    assert pkg.name == "@company/database"
    assert entrypoint == "packages/database/src/index.ts"


def test_12_unresolved_workspace_dependency(tmp_path: Path) -> None:
    """12. Unresolved workspace:* dependency is reported explicitly without fabricating a package."""
    repo = tmp_path / "unresolved_repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({
            "name": "root-app",
            "dependencies": {
                "@company/missing": "workspace:*",
            },
        }),
        encoding="utf-8",
    )

    ws = detect_workspace(repo)
    assert len(ws.dependencies) == 0
    assert len(ws.unresolved_dependencies) == 1
    unres = ws.unresolved_dependencies[0]
    assert unres["dependency_name"] == "@company/missing"
    assert unres["reason"] == "unresolved_workspace_dependency"


def test_13_duplicate_package_names(tmp_path: Path) -> None:
    """13. Duplicate package names in different directories have distinct, collision-safe identities."""
    repo = tmp_path / "dup_repo"
    repo.mkdir()
    # packages/auth
    p_auth = repo / "packages" / "auth"
    p_auth.mkdir(parents=True)
    (p_auth / "package.json").write_text(json.dumps({"name": "auth"}), encoding="utf-8")

    # apps/auth
    a_auth = repo / "apps" / "auth"
    a_auth.mkdir(parents=True)
    (a_auth / "package.json").write_text(json.dumps({"name": "auth"}), encoding="utf-8")

    ws = detect_workspace(repo)
    assert len(ws.packages) == 2
    pkg_ids = set(ws.packages.keys())
    assert any("packages/auth" in pid for pid in pkg_ids)
    assert any("apps/auth" in pid for pid in pkg_ids)


def test_14_package_export_resolution(tmp_path: Path) -> None:
    """14. Resolve subpath exports defined in package.json."""
    repo = tmp_path / "exports_repo"
    repo.mkdir()
    p = repo / "packages" / "ui"
    (p / "src").mkdir(parents=True)
    (p / "package.json").write_text(
        json.dumps({
            "name": "@my/ui",
            "exports": {
                ".": "./src/index.ts",
                "./button": "./src/button.ts",
            },
        }),
        encoding="utf-8",
    )
    (p / "src" / "index.ts").write_text("export * from './button';", encoding="utf-8")
    (p / "src" / "button.ts").write_text("export class Button {}", encoding="utf-8")

    ws = detect_workspace(repo)
    pkg, entrypoint = ws.resolve_package_import("@my/ui/button")
    assert pkg is not None
    assert entrypoint == "packages/ui/src/button.ts"


def test_15_cross_package_symbol_resolution(company_platform: Path) -> None:
    """15. Indexing the monorepo resolves cross-package imports and produces DEPENDS_ON_PACKAGE edges."""
    indexer = Indexer(company_platform)
    indexer.index()

    with indexer.session() as con:
        # Check DEPENDS_ON_PACKAGE graph edges
        dep_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges "
            "WHERE relationship='DEPENDS_ON_PACKAGE' ORDER BY source, target"
        ).fetchall()

        assert len(dep_edges) >= 4
        assert all(row[3] == "FRAMEWORK_VERIFIED" for row in dep_edges)

        # Check imports resolution in apps/api/src/server.ts
        api_imports = con.execute(
            "SELECT imported_module, resolved_path FROM imports "
            "WHERE source_path='apps/api/src/server.ts'"
        ).fetchall()

        auth_imp = [r for r in api_imports if r[0] == "@company/auth"]
        assert len(auth_imp) > 0
        assert auth_imp[0][1] == "packages/auth/src/index.ts"


# ---------------------------------------------------------------------------
# Section 26 Real-World Fixture Verification Test
# ---------------------------------------------------------------------------

def test_26_company_platform_full_verification(company_platform: Path) -> None:
    """26. Full verification of Section 26 Real-World Monorepo relationships."""
    ws = detect_workspace(company_platform)
    child_packages = [p for p in ws.packages.values() if p.root_path != ""]
    assert len(child_packages) == 6  # shared, database, auth, web, api, payments

    # Verify web dependencies
    web_pkg = [p for p in ws.packages.values() if p.name == "@company/web"][0]
    web_deps = [d.target_name for d in ws.dependencies if d.source_package_id == web_pkg.package_id]
    assert "@company/auth" in web_deps
    assert "@company/shared" in web_deps

    # Verify api dependencies
    api_pkg = [p for p in ws.packages.values() if p.name == "@company/api"][0]
    api_deps = [d.target_name for d in ws.dependencies if d.source_package_id == api_pkg.package_id]
    assert "@company/auth" in api_deps
    assert "@company/database" in api_deps
    assert "@company/shared" in api_deps

    # Verify payments dependencies
    pay_pkg = [p for p in ws.packages.values() if p.name == "@company/payments-service"][0]
    pay_deps = [d.target_name for d in ws.dependencies if d.source_package_id == pay_pkg.package_id]
    assert "@company/database" in pay_deps
