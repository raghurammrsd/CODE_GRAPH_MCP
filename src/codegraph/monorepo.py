"""Monorepo, Workspace, and Package Boundary Intelligence for CodeGraph MCP.

Core Principle:
    The AI reasons.
    CodeGraph interrogates the repository.

Invariants:
1. Never infer a package boundary solely from directory names (apps/, packages/, services/).
2. A package boundary must be supported by concrete evidence (manifests, workspace configs).
3. Collision-safe, machine-independent package identities (workspace_id::root_path).
4. No arbitrary command execution — static AST/JSON/TOML/YAML parsing only.
5. Reuse Phase 8 artifact classification: vendor/build/generated directories are never workspace packages.
"""
from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import sqlite3
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.errors import SecurityError
from codegraph.indexing.classifier import FileCategory, classify_file
from codegraph.security import is_sensitive, safe_path

try:
    import yaml  # type: ignore[import-untyped]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


class PackageType(StrEnum):
    APPLICATION = "APPLICATION"
    LIBRARY = "LIBRARY"
    SERVICE = "SERVICE"
    UNKNOWN = "UNKNOWN"


_APP_FRAMEWORKS = {
    "express",
    "next",
    "nextjs",
    "react",
    "vue",
    "svelte",
    "fastapi",
    "flask",
    "django",
    "tornado",
    "aiohttp",
    "starlette",
    "nestjs",
    "koa",
    "remix",
}

_BACKEND_SERVER_FRAMEWORKS = {
    "express",
    "fastapi",
    "flask",
    "django",
    "tornado",
    "aiohttp",
    "starlette",
    "nestjs",
    "koa",
}

_SERVICE_INDICATORS = {
    "microservice",
    "daemon",
    "worker",
    "grpc",
    "kafka",
    "rabbitmq",
    "celery",
    "pika",
    "bullmq",
    "dramatiq",
    "rq",
}

_PRUNED_WALK_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    "vendor",
    "third_party",
    "__pycache__",
    ".next",
    ".nuxt",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
})


@dataclass(frozen=True)
class PackageDependency:
    source_package_id: str
    target_package_id: str
    source_name: str
    target_name: str
    specifier: str = ""
    evidence: str = ""
    is_workspace: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "source_package_id": self.source_package_id,
            "target_package_id": self.target_package_id,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "relationship": "DEPENDS_ON_PACKAGE",
            "specifier": self.specifier,
            "evidence": self.evidence,
            "is_workspace": self.is_workspace,
        }


@dataclass
class PackageInfo:
    package_id: str
    name: str
    root_path: str
    manifest_path: str
    language: str
    package_manager: str
    workspace_id: str
    package_type: PackageType
    entrypoints: list[str] = field(default_factory=list)
    exports: dict[str, str] = field(default_factory=dict)
    dependency_names: list[str] = field(default_factory=list)
    dependency_package_ids: list[str] = field(default_factory=list)
    source_directories: list[str] = field(default_factory=list)
    test_directories: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "name": self.name,
            "root_path": self.root_path,
            "manifest_path": self.manifest_path,
            "language": self.language,
            "package_manager": self.package_manager,
            "workspace_id": self.workspace_id,
            "package_type": self.package_type.value,
            "entrypoints": self.entrypoints,
            "exports": self.exports,
            "dependency_names": self.dependency_names,
            "dependency_package_ids": self.dependency_package_ids,
            "source_directories": self.source_directories,
            "test_directories": self.test_directories,
        }


@dataclass
class WorkspaceInfo:
    workspace_id: str
    root_path: str
    workspace_type: str  # "npm" | "pnpm" | "yarn" | "python" | "standalone"
    packages: dict[str, PackageInfo] = field(default_factory=dict)
    package_by_name: dict[str, list[PackageInfo]] = field(default_factory=dict)
    package_by_path: dict[str, PackageInfo] = field(default_factory=dict)
    dependencies: list[PackageDependency] = field(default_factory=list)
    unresolved_dependencies: list[dict[str, str]] = field(default_factory=list)
    ambiguous_packages: dict[str, list[str]] = field(default_factory=dict)

    def get_package_for_file(self, file_path: str) -> PackageInfo | None:
        """Find the package that owns file_path based on longest matching root_path."""
        clean = file_path.replace("\\", "/").lstrip("./")
        best_pkg: PackageInfo | None = None
        best_len = -1

        for pkg in self.packages.values():
            pkg_root = pkg.root_path
            if pkg_root == "" or pkg_root == ".":
                if best_len < 0:
                    best_pkg = pkg
                    best_len = 0
            elif clean == pkg_root or clean.startswith(f"{pkg_root}/"):
                if len(pkg_root) > best_len:
                    best_pkg = pkg
                    best_len = len(pkg_root)
        return best_pkg

    def get_dependent_packages(self, package_id: str) -> list[PackageInfo]:
        """Return all packages in the workspace that depend on package_id."""
        dependents: list[PackageInfo] = []
        for dep in self.dependencies:
            if dep.target_package_id == package_id:
                source_pkg = self.packages.get(dep.source_package_id)
                if source_pkg and source_pkg not in dependents:
                    dependents.append(source_pkg)
        return dependents

    def resolve_package_import_detailed(
        self,
        import_specifier: str,
        source_file: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a package import specifier with explicit AMBIGUOUS reporting when duplicate
        package names exist in the workspace. Never silently guesses `candidates[0]`.
        """
        del source_file
        if not import_specifier:
            return {"status": "UNRESOLVED", "package": None, "entrypoint": None, "candidates": []}

        # 1. Exact match on package name
        candidates = self.package_by_name.get(import_specifier)
        if candidates:
            if len(candidates) > 1:
                return {
                    "status": "AMBIGUOUS",
                    "package": None,
                    "entrypoint": None,
                    "candidates": sorted(c.package_id for c in candidates),
                    "reason": "duplicate_package_name",
                }
            pkg = candidates[0]
            target_file = pkg.exports.get(".") or (pkg.entrypoints[0] if pkg.entrypoints else None)
            return {
                "status": "RESOLVED",
                "package": pkg,
                "entrypoint": target_file,
                "candidates": [pkg.package_id],
            }

        # 2. Subpath import (e.g. '@company/auth/service' or 'shared/utils')
        for name, pkg_list in self.package_by_name.items():
            if import_specifier.startswith(f"{name}/"):
                if len(pkg_list) > 1:
                    return {
                        "status": "AMBIGUOUS",
                        "package": None,
                        "entrypoint": None,
                        "candidates": sorted(c.package_id for c in pkg_list),
                        "reason": "duplicate_package_name",
                    }
                subpath = "." + import_specifier[len(name):]
                pkg = pkg_list[0]
                if subpath in pkg.exports:
                    return {
                        "status": "RESOLVED",
                        "package": pkg,
                        "entrypoint": pkg.exports[subpath],
                        "candidates": [pkg.package_id],
                    }
                rel_candidate = posixpath.normpath(posixpath.join(pkg.root_path, subpath.lstrip("./")))
                return {
                    "status": "RESOLVED",
                    "package": pkg,
                    "entrypoint": rel_candidate,
                    "candidates": [pkg.package_id],
                }

        return {"status": "UNRESOLVED", "package": None, "entrypoint": None, "candidates": []}

    def resolve_package_import(
        self,
        import_specifier: str,
        source_file: str | None = None,
    ) -> tuple[PackageInfo | None, str | None]:
        """Resolve a package import specifier to `(PackageInfo, entrypoint_file)`.

        If multiple workspace packages share `import_specifier`, returns `(None, None)`
        rather than guessing `candidates[0]`. Use `resolve_package_import_detailed` to
        inspect `AMBIGUOUS` candidate lists.
        """
        detail = self.resolve_package_import_detailed(import_specifier, source_file=source_file)
        if detail["status"] == "RESOLVED":
            return detail["package"], detail["entrypoint"]
        return None, None

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "workspace_id": self.workspace_id,
            "root_path": self.root_path,
            "workspace_type": self.workspace_type,
            "package_count": len(self.packages),
            "packages": [p.as_dict() for p in self.packages.values()],
            "package_dependencies": [d.as_dict() for d in self.dependencies],
            "unresolved_dependencies": self.unresolved_dependencies,
        }
        if self.ambiguous_packages:
            out["ambiguous_packages"] = self.ambiguous_packages
        return out


def _parse_yaml_packages(content: str) -> list[str]:
    """Parse packages list from pnpm-workspace.yaml safely."""
    if _HAS_YAML:
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                pkgs = data.get("packages")
                if isinstance(pkgs, list):
                    return [str(p) for p in pkgs if isinstance(p, (str, int))]
        except Exception:
            pass

    # Simple line-based fallback parser
    patterns: list[str] = []
    in_packages = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("packages:"):
            in_packages = True
            continue
        if in_packages:
            if stripped.startswith("-"):
                pat = stripped.lstrip("-").strip().strip("'\"")
                if pat:
                    patterns.append(pat)
            elif not line.startswith(" ") and not line.startswith("\t"):
                break
    return patterns


def _scan_manifests(
    repository: Path,
    con: sqlite3.Connection | None = None,
    max_depth: int = 5,
) -> list[Path]:
    """Discover manifest files safely with bounded recursion (`max_depth`),
    skipping vendor/build/generated artifacts and sensitive paths.
    """
    root = repository.resolve(strict=True)
    manifest_paths: list[Path] = []
    target_names = {"package.json", "pyproject.toml", "setup.cfg"}

    # Priority: if database connection is available, use indexed files table
    if con is not None:
        try:
            rows = con.execute(
                "SELECT path, category FROM files WHERE "
                "path LIKE '%package.json' OR path LIKE '%pyproject.toml' "
                "OR path LIKE '%setup.py' OR path LIKE '%setup.cfg'"
            ).fetchall()
            for r in rows:
                p_str = str(r[0])
                cat = str(r[1])
                if cat in ("VENDOR", "BUILD_ARTIFACT", "BINARY"):
                    continue
                if p_str.count("/") > max_depth:
                    continue
                try:
                    p = safe_path(root, p_str)
                    if p.is_file():
                        manifest_paths.append(p)
                except SecurityError:
                    continue
            if manifest_paths:
                return sorted(set(manifest_paths))
        except Exception:
            pass

    # Bounded recursive filesystem walk (never descends beyond max_depth or into vendor/build dirs)
    def _walk(current_dir: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(current_dir.iterdir(), key=lambda e: e.name)
        except OSError:
            return

        for entry in entries:
            try:
                if entry.is_symlink():
                    # Verify symlink stays inside repository root
                    resolved_entry = entry.resolve(strict=False)
                    resolved_entry.relative_to(root)
                rel = entry.relative_to(root)
            except (ValueError, OSError, SecurityError):
                continue

            if is_sensitive(rel):
                continue

            if entry.is_dir():
                if entry.name in _PRUNED_WALK_DIRS or (entry.name.startswith(".") and entry.name != "."):
                    continue
                cat_dir = classify_file(rel)
                if cat_dir in (FileCategory.VENDOR, FileCategory.BUILD_ARTIFACT, FileCategory.BINARY):
                    continue
                _walk(entry, depth + 1)
            elif entry.is_file() and entry.name in target_names:
                cat_file = classify_file(rel)
                if cat_file in (FileCategory.VENDOR, FileCategory.BUILD_ARTIFACT, FileCategory.BINARY):
                    continue
                manifest_paths.append(entry)

    _walk(root, 0)
    return sorted(set(manifest_paths))


def _resolve_entrypoints_js(
    root_rel: str,
    pkg_data: dict[str, Any],
    manifest_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    """Extract entrypoints and exports map from package.json."""
    entrypoints: list[str] = []
    exports_map: dict[str, str] = {}

    def _add_entry(cand: str, key: str = ".") -> None:
        cand_clean = cand.replace("\\", "/").lstrip("./")
        full_rel = posixpath.normpath(posixpath.join(root_rel, cand_clean)) if root_rel else cand_clean
        if full_rel not in entrypoints:
            entrypoints.append(full_rel)
        if key not in exports_map:
            exports_map[key] = full_rel

    # 1. package.json "main"
    main_field = pkg_data.get("main")
    if isinstance(main_field, str) and main_field.strip():
        _add_entry(main_field, ".")

    # 2. package.json "module"
    module_field = pkg_data.get("module")
    if isinstance(module_field, str) and module_field.strip():
        _add_entry(module_field, ".")

    # 3. package.json "bin"
    bin_field = pkg_data.get("bin")
    if isinstance(bin_field, str):
        _add_entry(bin_field, "./bin")
    elif isinstance(bin_field, dict):
        for b_name, b_path in bin_field.items():
            if isinstance(b_path, str):
                _add_entry(b_path, f"./bin/{b_name}")

    # 4. package.json "exports"
    exports_field = pkg_data.get("exports")
    if isinstance(exports_field, str):
        _add_entry(exports_field, ".")
    elif isinstance(exports_field, dict):
        for exp_key, exp_val in exports_field.items():
            if isinstance(exp_val, str):
                _add_entry(exp_val, exp_key)
            elif isinstance(exp_val, dict):
                # Conditional exports (import, require, default)
                for cond in ("import", "require", "default", "types"):
                    c_val = exp_val.get(cond)
                    if isinstance(c_val, str):
                        _add_entry(c_val, exp_key)
                        break

    # 5. Common conventions if no explicit entrypoint
    if not entrypoints:
        for standard in (
            "src/index.ts",
            "src/index.js",
            "src/index.tsx",
            "src/main.ts",
            "src/main.js",
            "index.ts",
            "index.js",
        ):
            if (manifest_dir / standard).is_file():
                _add_entry(standard, ".")
                break

    return entrypoints, exports_map


def _resolve_entrypoints_py(
    root_rel: str,
    py_data: dict[str, Any],
    manifest_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    """Extract entrypoints and scripts from pyproject.toml."""
    entrypoints: list[str] = []
    exports_map: dict[str, str] = {}

    def _add_entry(cand: str, key: str = ".") -> None:
        cand_clean = cand.replace("\\", "/").lstrip("./")
        full_rel = posixpath.normpath(posixpath.join(root_rel, cand_clean)) if root_rel else cand_clean
        if full_rel not in entrypoints:
            entrypoints.append(full_rel)
        if key not in exports_map:
            exports_map[key] = full_rel

    # Check project.scripts
    proj = py_data.get("project", {}) if isinstance(py_data, dict) else {}
    scripts = proj.get("scripts", {}) if isinstance(proj, dict) else {}
    if isinstance(scripts, dict):
        for s_name, s_spec in scripts.items():
            if isinstance(s_spec, str) and ":" in s_spec:
                mod = s_spec.split(":")[0].replace(".", "/")
                _add_entry(f"{mod}.py", f"./bin/{s_name}")

    # Check poetry.scripts
    tool = py_data.get("tool", {}) if isinstance(py_data, dict) else {}
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    p_scripts = poetry.get("scripts", {}) if isinstance(poetry, dict) else {}
    if isinstance(p_scripts, dict):
        for s_name, s_spec in p_scripts.items():
            if isinstance(s_spec, str) and ":" in s_spec:
                mod = s_spec.split(":")[0].replace(".", "/")
                _add_entry(f"{mod}.py", f"./bin/{s_name}")

    # Look for package module / __init__.py
    pkg_name = proj.get("name") or poetry.get("name")
    if isinstance(pkg_name, str) and pkg_name:
        clean_pkg = pkg_name.replace("-", "_")
        for cand in (
            f"src/{clean_pkg}/__init__.py",
            f"{clean_pkg}/__init__.py",
            f"src/{clean_pkg}.py",
            f"{clean_pkg}.py",
        ):
            if (manifest_dir / cand).is_file():
                _add_entry(cand, ".")
                break

    if not entrypoints:
        for cand in ("src/__init__.py", "app.py", "main.py"):
            if (manifest_dir / cand).is_file():
                _add_entry(cand, ".")
                break

    return entrypoints, exports_map


def _matches_ws_pattern(rel_path: str, pat: str) -> bool:
    """Match a package relative path against a workspace glob pattern."""
    clean_pat = pat.strip().rstrip("/")
    if not clean_pat:
        return False
    return (
        fnmatch.fnmatch(rel_path, clean_pat)
        or fnmatch.fnmatch(rel_path, pat.rstrip("/*"))
        or (clean_pat.endswith("/*") and rel_path.startswith(clean_pat[:-2] + "/"))
        or (clean_pat.endswith("/**") and (rel_path == clean_pat[:-3] or rel_path.startswith(clean_pat[:-3] + "/")))
    )


def _has_typescript_files_bounded(manifest_dir: Path, entrypoints: list[str]) -> bool:
    """Check whether a JS/TS package uses TypeScript without unbounded globbing."""
    if (manifest_dir / "tsconfig.json").is_file():
        return True
    if any(ep.endswith((".ts", ".tsx")) for ep in entrypoints):
        return True
    try:
        for child in manifest_dir.iterdir():
            if child.is_file() and child.suffix in (".ts", ".tsx"):
                return True
            if child.is_dir() and child.name not in _PRUNED_WALK_DIRS and not child.name.startswith("."):
                for sub in child.iterdir():
                    if sub.is_file() and sub.suffix in (".ts", ".tsx"):
                        return True
    except OSError:
        pass
    return False


def _classify_package_type(
    name: str,
    root_rel: str,
    dependencies: list[str],
    entrypoints: list[str],
    has_bin: bool,
    con: sqlite3.Connection | None,
) -> PackageType:
    """Statically determine PackageType based on verified evidence without guessing from directory names.

    Precedence:
    1. Explicit service indicators (celery, kafka, grpc, worker, daemon, etc.) -> SERVICE
    2. Backend server frameworks (FastAPI, Flask, Django, Express, etc.) paired with service
       evidence (ASGI/WSGI runners, service entrypoints, or service package identity) -> SERVICE
    3. Application frameworks (Next, React, Vue, standalone web apps) -> APPLICATION
    4. Indexed framework routes under package root -> APPLICATION
    5. CLI binary without application server -> APPLICATION
    6. Library entrypoints without binary -> LIBRARY
    7. Otherwise -> UNKNOWN
    """
    all_deps_lower = {d.lower() for d in dependencies}
    name_lower = name.lower()

    # Evidence 1: Service markers in dependencies (checked BEFORE generic app frameworks)
    if any(ind in all_deps_lower for ind in _SERVICE_INDICATORS):
        return PackageType.SERVICE

    # Evidence 2: Backend server framework acting as a service (service runner / service entrypoint / service identity)
    has_backend_server = any(fw in all_deps_lower for fw in _BACKEND_SERVER_FRAMEWORKS)
    has_service_runner = any(srv in all_deps_lower for srv in ("uvicorn", "gunicorn", "hypercorn", "daphne"))
    has_service_entrypoint = any(
        ep.endswith(("service.py", "service.ts", "service.js", "worker.py", "worker.ts", "daemon.py"))
        for ep in entrypoints
    )
    has_service_identity = (
        name_lower.endswith(("-service", "_service", "-svc", "_svc", "-worker", "_worker", "-daemon"))
        or root_rel.startswith("services/")
    )
    if has_backend_server and (has_service_runner or has_service_entrypoint or has_service_identity):
        return PackageType.SERVICE

    # Evidence 3: Application frameworks
    if any(fw in all_deps_lower for fw in _APP_FRAMEWORKS):
        return PackageType.APPLICATION

    # Evidence 4: Database routes registered under this package root
    if con is not None:
        try:
            count = con.execute(
                "SELECT count(*) FROM framework_routes WHERE file_path LIKE ?",
                (f"{root_rel}/%" if root_rel else "%",),
            ).fetchone()[0]
            if count > 0:
                return PackageType.APPLICATION
        except Exception:
            pass

    # Evidence 5: CLI binary without application server
    if has_bin and not any(fw in all_deps_lower for fw in _APP_FRAMEWORKS):
        return PackageType.APPLICATION

    # Evidence 6: Library characteristics (entrypoints exist, no app frameworks)
    if entrypoints and not has_bin:
        return PackageType.LIBRARY

    return PackageType.UNKNOWN


def detect_workspace(
    repository: Path,
    con: sqlite3.Connection | None = None,
) -> WorkspaceInfo:
    """Deterministically analyze repository workspace structure, packages, and dependencies."""
    root = repository.resolve(strict=True)

    # 1. Detect root workspace type and declared package patterns
    workspace_type = "standalone"
    workspace_patterns: list[str] = []
    root_name = root.name

    # Check pnpm-workspace.yaml
    pnpm_ws = root / "pnpm-workspace.yaml"
    if pnpm_ws.is_file():
        workspace_type = "pnpm"
        try:
            text = pnpm_ws.read_text(encoding="utf-8", errors="replace")
            workspace_patterns.extend(_parse_yaml_packages(text))
        except OSError:
            pass

    # Check root package.json
    root_pkg_json = root / "package.json"
    if root_pkg_json.is_file():
        try:
            data = json.loads(root_pkg_json.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                r_name = data.get("name")
                if isinstance(r_name, str) and r_name:
                    root_name = r_name
                ws = data.get("workspaces")
                if ws:
                    if workspace_type == "standalone":
                        workspace_type = "npm"
                    if isinstance(ws, list):
                        workspace_patterns.extend([str(p) for p in ws if isinstance(p, str)])
                    elif isinstance(ws, dict):
                        pkgs = ws.get("packages")
                        if isinstance(pkgs, list):
                            workspace_patterns.extend([str(p) for p in pkgs if isinstance(p, str)])
        except Exception:
            pass

    # Check root pyproject.toml
    root_pyproj = root / "pyproject.toml"
    if root_pyproj.is_file() and workspace_type == "standalone":
        try:
            p_data = tomllib.loads(root_pyproj.read_text(encoding="utf-8", errors="replace"))
            if isinstance(p_data, dict):
                proj = p_data.get("project", {})
                if isinstance(proj, dict) and proj.get("name"):
                    root_name = str(proj["name"])
                tool = p_data.get("tool", {})
                if isinstance(tool, dict) and "poetry" in tool:
                    workspace_type = "python"
        except Exception:
            pass

    workspace_id = root_name

    pos_patterns = [p.strip() for p in workspace_patterns if p.strip() and not p.strip().startswith("!")]
    neg_patterns = [p.strip()[1:].strip() for p in workspace_patterns if p.strip().startswith("!") and p.strip()[1:].strip()]

    # 2. Discover candidate package manifests
    manifest_files = _scan_manifests(root, con=con)

    packages: dict[str, PackageInfo] = {}
    package_by_name: dict[str, list[PackageInfo]] = {}
    package_by_path: dict[str, PackageInfo] = {}

    for manifest_path in manifest_files:
        try:
            rel_manifest = manifest_path.relative_to(root).as_posix()
        except ValueError:
            continue

        manifest_dir = manifest_path.parent
        try:
            root_rel = manifest_dir.relative_to(root).as_posix()
            if root_rel == ".":
                root_rel = ""
        except ValueError:
            continue

        # Respect negated workspace globs (e.g. '!packages/legacy')
        if root_rel != "" and neg_patterns:
            if any(_matches_ws_pattern(root_rel, np) for np in neg_patterns):
                continue

        # If workspace patterns are defined (e.g. apps/*, packages/*), verify membership for child packages
        is_workspace_member = True
        if pos_patterns and root_rel != "":
            is_workspace_member = any(_matches_ws_pattern(root_rel, pat) for pat in pos_patterns)

        # Package identity is strictly deterministic and collision-safe
        package_id = f"{workspace_id}::{root_rel}" if root_rel else f"{workspace_id}::root"

        # Parse manifest data
        m_name = manifest_path.name
        pkg_name = root_rel if root_rel else workspace_id
        pkg_lang = "unknown"
        pkg_mgr = "unknown"
        dep_names: list[str] = []
        entrypoints: list[str] = []
        exports: dict[str, str] = {}
        has_bin = False
        raw_metadata: dict[str, Any] = {"is_workspace_member": is_workspace_member}

        if m_name == "package.json":
            pkg_mgr = workspace_type if workspace_type in ("npm", "pnpm", "yarn") else "npm"
            try:
                p_dict = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(p_dict, dict):
                    raw_metadata.update(p_dict)
                    if isinstance(p_dict.get("name"), str) and p_dict["name"].strip():
                        pkg_name = p_dict["name"].strip()
                    has_bin = bool(p_dict.get("bin"))
                    entrypoints, exports = _resolve_entrypoints_js(root_rel, p_dict, manifest_dir)

                    # Extract all dependencies
                    for dep_key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                        d_dict = p_dict.get(dep_key)
                        if isinstance(d_dict, dict):
                            for d_name, _d_spec in d_dict.items():
                                if d_name not in dep_names:
                                    dep_names.append(d_name)
            except Exception:
                continue
            pkg_lang = "typescript" if _has_typescript_files_bounded(manifest_dir, entrypoints) else "javascript"

        elif m_name in ("pyproject.toml", "setup.cfg", "setup.py"):
            pkg_lang = "python"
            pkg_mgr = "poetry" if workspace_type == "python" else "pip"
            if m_name == "pyproject.toml":
                try:
                    py_dict = tomllib.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(py_dict, dict):
                        raw_metadata = py_dict
                        proj = py_dict.get("project", {})
                        if isinstance(proj, dict) and proj.get("name"):
                            pkg_name = str(proj["name"])
                            deps = proj.get("dependencies", [])
                            if isinstance(deps, list):
                                for d in deps:
                                    if isinstance(d, str):
                                        dep_names.append(re.split(r"[><=~;!]", d)[0].strip())
                        tool = py_dict.get("tool", {})
                        if isinstance(tool, dict) and "poetry" in tool:
                            p_sec = tool["poetry"]
                            if isinstance(p_sec, dict) and p_sec.get("name"):
                                pkg_name = str(p_sec["name"])
                            p_deps = p_sec.get("dependencies", {})
                            if isinstance(p_deps, dict):
                                for d in p_deps.keys():
                                    if d != "python" and d not in dep_names:
                                        dep_names.append(d)
                        entrypoints, exports = _resolve_entrypoints_py(root_rel, py_dict, manifest_dir)
                except Exception:
                    continue

        pkg_type = _classify_package_type(
            name=pkg_name,
            root_rel=root_rel,
            dependencies=dep_names,
            entrypoints=entrypoints,
            has_bin=has_bin,
            con=con,
        )

        # Separate source and test directories under this package
        source_dirs: set[str] = set()
        test_dirs: set[str] = set()
        for sub in manifest_dir.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                sub_rel = sub.relative_to(root).as_posix()
                if sub.name in ("tests", "test", "__tests__", "spec", "specs"):
                    test_dirs.add(sub_rel)
                elif sub.name not in ("node_modules", "dist", "build", ".venv", "vendor"):
                    source_dirs.add(sub_rel)

        info = PackageInfo(
            package_id=package_id,
            name=pkg_name,
            root_path=root_rel,
            manifest_path=rel_manifest,
            language=pkg_lang,
            package_manager=pkg_mgr,
            workspace_id=workspace_id,
            package_type=pkg_type,
            entrypoints=sorted(entrypoints),
            exports=exports,
            dependency_names=sorted(dep_names),
            source_directories=sorted(source_dirs),
            test_directories=sorted(test_dirs),
            metadata=raw_metadata,
        )

        packages[package_id] = info
        package_by_path[root_rel] = info
        package_by_name.setdefault(pkg_name, []).append(info)

    ambiguous_packages: dict[str, list[str]] = {
        p_name: sorted(p.package_id for p in p_list)
        for p_name, p_list in sorted(package_by_name.items())
        if len(p_list) > 1
    }

    # 3. Resolve inter-package dependencies and detect unresolved or ambiguous dependencies
    dependencies: list[PackageDependency] = []
    unresolved_dependencies: list[dict[str, str]] = []

    for _pkg_id, pkg in packages.items():
        resolved_dep_ids: list[str] = []
        raw_deps: dict[str, Any] = {}
        if pkg.manifest_path.endswith("package.json") and isinstance(pkg.metadata, dict):
            for k in ("dependencies", "devDependencies", "peerDependencies"):
                d_sec = pkg.metadata.get(k)
                if isinstance(d_sec, dict):
                    raw_deps.update(d_sec)

        for dep_name in pkg.dependency_names:
            spec = str(raw_deps.get(dep_name, ""))
            is_ws_spec = "workspace:" in spec
            target_pkgs = [p for p in (package_by_name.get(dep_name) or []) if p.package_id != pkg.package_id]

            if len(target_pkgs) == 1:
                target_pkg = target_pkgs[0]
                dependencies.append(
                    PackageDependency(
                        source_package_id=pkg.package_id,
                        target_package_id=target_pkg.package_id,
                        source_name=pkg.name,
                        target_name=target_pkg.name,
                        specifier=spec,
                        evidence=f"{pkg.manifest_path}:dependencies['{dep_name}']",
                        is_workspace=is_ws_spec,
                    )
                )
                resolved_dep_ids.append(target_pkg.package_id)
            elif len(target_pkgs) > 1:
                # Duplicate package name in workspace: never guess target_pkgs[0]
                unresolved_dependencies.append({
                    "source_package_id": pkg.package_id,
                    "dependency_name": dep_name,
                    "specifier": spec,
                    "status": "AMBIGUOUS",
                    "reason": "ambiguous_duplicate_package_name",
                    "candidates": ",".join(sorted(p.package_id for p in target_pkgs)),
                    "evidence": f"{pkg.manifest_path}:dependencies['{dep_name}']",
                })
            elif is_ws_spec:
                # workspace:* dependency requested but package not found
                unresolved_dependencies.append({
                    "source_package_id": pkg.package_id,
                    "dependency_name": dep_name,
                    "specifier": spec,
                    "status": "UNRESOLVED",
                    "reason": "unresolved_workspace_dependency",
                    "evidence": f"{pkg.manifest_path}:dependencies['{dep_name}']={spec}",
                })

        pkg.dependency_package_ids = sorted(set(resolved_dep_ids))

    dependencies.sort(key=lambda d: (d.source_package_id, d.target_package_id))
    unresolved_dependencies.sort(key=lambda u: (u["source_package_id"], u["dependency_name"]))

    return WorkspaceInfo(
        workspace_id=workspace_id,
        root_path="",
        workspace_type=workspace_type,
        packages=packages,
        package_by_name=package_by_name,
        package_by_path=package_by_path,
        dependencies=dependencies,
        unresolved_dependencies=unresolved_dependencies,
        ambiguous_packages=ambiguous_packages,
    )
