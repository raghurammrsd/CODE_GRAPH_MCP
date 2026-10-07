"""Secure, deterministic repository scanner.

Architectural Invariants:
1. Low-level primitive `safe_path()` is strict and fail-closed (raises SecurityError on escape).
2. Repository scanner catches SecurityError on individual unsafe symlink/traversal entries,
   records the security skip, and continues scanning without aborting the entire repository.
3. Unsafe/escaped paths are NEVER indexed or exposed.
4. Scan statistics are tracked explicitly.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from codegraph.errors import SecurityError
from codegraph.indexing.classifier import (
    FileCategory,
    classify_file,
    is_ignored_by_codegraphignore,
    load_codegraphignore,
)
from codegraph.security import is_sensitive, safe_path

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sql": "sql",
    ".prisma": "prisma",
    ".html": "html",
    ".htm": "html",
    ".jinja": "html",
    ".jinja2": "html",
    ".njk": "html",
    ".ejs": "html",
    ".lua": "luau",
    ".luau": "luau",
}


@dataclass(frozen=True)
class ScanResult:
    path: Path
    relative_path: Path
    language: str
    category: FileCategory = FileCategory.SOURCE


@dataclass
class ScanStats:
    scanned: int = 0
    accepted: int = 0
    skipped: int = 0
    skipped_security: int = 0
    skipped_binary: int = 0
    skipped_secret: int = 0
    skipped_large: int = 0
    skipped_ignored: int = 0
    skipped_details: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "accepted": self.accepted,
            "skipped": self.skipped,
            "skipped_security": self.skipped_security,
            "skipped_binary": self.skipped_binary,
            "skipped_secret": self.skipped_secret,
            "skipped_large": self.skipped_large,
            "skipped_ignored": self.skipped_ignored,
        }


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def scan_with_stats(
    repository: Path,
    max_file_size: int,
    exclusions: tuple[str, ...] = (),
) -> tuple[list[ScanResult], ScanStats]:
    """Scan repository for supported source files, catching unsafe symlinks and collecting stats."""
    root = repository.resolve(strict=True)
    gitignore = _gitignore_patterns(root)
    codegraphignore = load_codegraphignore(root)
    results: list[ScanResult] = []
    stats = ScanStats()

    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for filename in files:
            stats.scanned += 1
            absolute = Path(directory) / filename
            try:
                rel_unresolved = absolute.relative_to(root)
            except ValueError:
                stats.skipped += 1
                stats.skipped_security += 1
                continue

            try:
                # safe_path raises SecurityError if symlink resolves outside root or uses traversal escapes
                resolved = safe_path(root, rel_unresolved)
            except SecurityError:
                stats.skipped += 1
                stats.skipped_security += 1
                stats.skipped_details.append(f"Security blocked: {rel_unresolved}")
                continue

            relative = resolved.relative_to(root)

            try:
                if not resolved.is_file():
                    stats.skipped += 1
                    continue
                if resolved.stat().st_size > max_file_size:
                    stats.skipped += 1
                    stats.skipped_large += 1
                    continue
                if is_sensitive(relative):
                    stats.skipped += 1
                    stats.skipped_secret += 1
                    continue
                if (
                    _ignored_by_gitignore(relative, gitignore)
                    or is_ignored_by_codegraphignore(relative, codegraphignore)
                    or any(relative.match(p) for p in exclusions)
                ):
                    stats.skipped += 1
                    stats.skipped_ignored += 1
                    continue
                if is_binary(resolved):
                    stats.skipped += 1
                    stats.skipped_binary += 1
                    continue

                category = classify_file(relative)
                if category in (FileCategory.BUILD_ARTIFACT, FileCategory.VENDOR, FileCategory.BINARY):
                    stats.skipped += 1
                    if category == FileCategory.BINARY:
                        stats.skipped_binary += 1
                    else:
                        stats.skipped_ignored += 1
                    continue
            except OSError:
                stats.skipped += 1
                continue

            language = LANGUAGES.get(relative.suffix.lower())
            if language:
                stats.accepted += 1
                results.append(ScanResult(resolved, relative, language, category=category))
            else:
                stats.skipped += 1

    results.sort(key=lambda item: item.relative_path.as_posix())
    return results, stats


def scan(
    repository: Path,
    max_file_size: int,
    exclusions: tuple[str, ...] = (),
) -> list[ScanResult]:
    """Securely scan repository for supported source files."""
    results, _ = scan_with_stats(repository, max_file_size, exclusions)
    return results


def _gitignore_patterns(root: Path) -> list[str]:
    path = root / ".gitignore"
    try:
        return [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#") and not line.startswith("!")
        ]
    except OSError:
        return []


def _ignored_by_gitignore(relative: Path, patterns: list[str]) -> bool:
    """Small, deterministic subset: ordinary glob and directory patterns; negation is unsupported."""
    value = relative.as_posix()
    return any(
        fnmatch.fnmatch(value, pattern.rstrip("/"))
        or (pattern.endswith("/") and value.startswith(pattern))
        or fnmatch.fnmatch(relative.name, pattern)
        for pattern in patterns
    )
