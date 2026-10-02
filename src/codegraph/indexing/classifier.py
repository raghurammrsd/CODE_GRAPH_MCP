"""Generalized file and repository artifact classifier.

Classifies files into distinct categories:
- SOURCE: normal application source code
- TEST: test suites, mocks, and fixtures
- GENERATED: minified assets, bundles, generated stubs, source maps
- BUILD_ARTIFACT: build output directories (dist, build, target)
- VENDOR: external dependencies (node_modules, vendor, venv)
- CONFIG: project and build configuration files
- BINARY: compiled objects, images, archives
"""
from __future__ import annotations

import fnmatch
from enum import StrEnum
from pathlib import Path

_BINARY_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dylib",
    ".dll",
    ".wasm",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
}

_BUILD_ARTIFACT_DIRS = {
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".turbo",
    "eggs",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

_VENDOR_DIRS = {
    "node_modules",
    "vendor",
    "third_party",
    "bower_components",
    ".venv",
    "venv",
    "env",
}

_CONFIG_FILENAMES = {
    "package.json",
    "tsconfig.json",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "cargo.toml",
    "go.mod",
    "makefile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "cmakelists.txt",
    ".editorconfig",
    ".gitignore",
    ".codegraphignore",
    "requirements.txt",
    "gemfile",
}

_CONFIG_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".env",
}

_TEST_DIRS = {
    "tests",
    "test",
    "__tests__",
    "spec",
    "specs",
}

_GENERATED_PATTERNS = [
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "*.bundle.css",
    "*.map",
    "*.generated.*",
    "*_generated.py",
    "*_pb2.py",
    "*.pb.go",
    "*.gen.ts",
    "*.d.ts",
]

_GENERATED_DIR_SUBSTRINGS = {
    "react_assets",
    "generated",
    "gen",
    "bundles",
    "bundle",
    "build_assets",
    "static_bundles",
}


class FileCategory(StrEnum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    GENERATED = "GENERATED"
    BUILD_ARTIFACT = "BUILD_ARTIFACT"
    VENDOR = "VENDOR"
    CONFIG = "CONFIG"
    BINARY = "BINARY"


def load_codegraphignore(root: Path) -> list[str]:
    """Parse .codegraphignore from repository root.

    Format:
    - one glob pattern per line
    - blank lines ignored
    - lines beginning with # are comments
    - directory patterns end with /
    - negation rules beginning with ! are NOT supported in v2.1.1
    """
    path = root / ".codegraphignore"
    if not path.is_file():
        return []
    try:
        patterns: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            patterns.append(stripped)
        return patterns
    except OSError:
        return []


def is_ignored_by_codegraphignore(relative: Path, patterns: list[str]) -> bool:
    """Check if relative path matches any .codegraphignore pattern deterministically."""
    if not patterns:
        return False
    posix_path = relative.as_posix()
    name = relative.name
    for pat in patterns:
        clean_pat = pat.rstrip("/")
        # Directory pattern (ends with /)
        if pat.endswith("/"):
            if posix_path.startswith(pat) or f"/{pat}" in f"/{posix_path}/":
                return True
            if any(part == clean_pat or fnmatch.fnmatch(part, clean_pat) for part in relative.parts):
                return True
        # Exact or glob match on full relative path or filename
        if fnmatch.fnmatch(posix_path, clean_pat) or fnmatch.fnmatch(name, clean_pat):
            return True
        # Match within path segments
        if any(fnmatch.fnmatch(part, clean_pat) for part in relative.parts):
            return True
    return False


def classify_file(
    relative_path: Path | str,
    content: str | bytes | None = None,
) -> FileCategory:
    """Classify a repository file into its canonical category."""
    p = Path(relative_path)
    suffix = p.suffix.lower()
    name = p.name.lower()
    parts_lower = [part.lower() for part in p.parts]

    # 1. Binary check
    if suffix in _BINARY_EXTENSIONS:
        return FileCategory.BINARY
    if isinstance(content, bytes) and b"\x00" in content[:8192]:
        return FileCategory.BINARY

    # 2. Build artifact check
    for part in parts_lower:
        if part in _BUILD_ARTIFACT_DIRS or part.endswith(".egg-info"):
            return FileCategory.BUILD_ARTIFACT

    # 3. Vendor check
    for part in parts_lower:
        if part in _VENDOR_DIRS:
            return FileCategory.VENDOR

    # 4. Test check
    if any(part in _TEST_DIRS for part in parts_lower):
        return FileCategory.TEST
    if (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith(".test.jsx")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.jsx")
        or name.endswith(".spec.tsx")
    ):
        return FileCategory.TEST

    # 5. Generated artifact check (pattern / path / content heuristics)
    for pat in _GENERATED_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return FileCategory.GENERATED

    for part in parts_lower:
        if part in _GENERATED_DIR_SUBSTRINGS:
            return FileCategory.GENERATED

    if isinstance(content, str) and content:
        # Check source map directive
        if "//# sourceMappingURL=" in content or "/*# sourceMappingURL=" in content:
            return FileCategory.GENERATED
        # Check minified characteristics: single line > 1000 characters or very few lines for large size
        lines = content.splitlines()
        if lines:
            max_line_len = max(len(ln) for ln in lines[:20])
            if max_line_len > 1000:
                return FileCategory.GENERATED
            if len(content) > 5000 and len(lines) < 10 and max_line_len > 500:
                return FileCategory.GENERATED
            # Minified JS runtime boilerplate signatures
            first_line = lines[0].strip()
            if (
                first_line.startswith("!function(")
                or first_line.startswith("(window.webpackJsonp")
                or first_line.startswith("\"use strict\";var ")
                or first_line.startswith("(()=>{var ")
            ) and len(content) > 3000:
                return FileCategory.GENERATED

    # 6. Configuration check
    if name in _CONFIG_FILENAMES or suffix in _CONFIG_EXTENSIONS:
        return FileCategory.CONFIG

    # 7. Default to SOURCE for all other files
    return FileCategory.SOURCE
