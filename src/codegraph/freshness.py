"""Repository Freshness & Dependency-Aware Invalidation Engine.

Tracks:
  current Git HEAD, indexed Git HEAD, file hashes, parser version,
  schema version, index generation, timestamps, and parse_failed state.

Provides dependency-aware invalidation so localized file updates only
invalidate affected symbols, references, graph edges, evidence, and cached
context packets rather than rebuilding the entire repository.
"""
from __future__ import annotations

import hashlib
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    PARTIALLY_STALE = "PARTIALLY_STALE"
    UNKNOWN = "UNKNOWN"


@dataclass
class FreshnessReport:
    status: FreshnessStatus
    indexed_commit: str | None
    current_commit: str | None
    index_timestamp: int | None
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    parse_failed_files: list[str] = field(default_factory=list)
    parser_version: str | None = None
    index_generation: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "indexed_commit": self.indexed_commit,
            "current_commit": self.current_commit,
            "index_timestamp": self.index_timestamp,
            "modified_files": self.modified_files,
            "deleted_files": self.deleted_files,
            "parse_failed_files": self.parse_failed_files,
            "parser_version": self.parser_version,
            "index_generation": self.index_generation,
            "detail": self.detail,
        }


def _run_git(repository: Path, *args: str, timeout: int = 10) -> str | None:
    """Run an allowlisted read-only git command inside repository."""
    if not shlex.split("git")[0]:  # pragma: no cover
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def current_commit(repository: Path) -> str | None:
    """Return the current HEAD commit SHA, or None if not a git repository."""
    return _run_git(repository, "rev-parse", "HEAD")


def current_branch(repository: Path) -> str | None:
    """Return the current git branch name, or None."""
    return _run_git(repository, "rev-parse", "--abbrev-ref", "HEAD")


def _get_meta(con: sqlite3.Connection, key: str) -> str | None:
    for table in ("metadata", "codegraph_meta"):
        try:
            row = con.execute(
                f"SELECT value FROM {table} WHERE key=?", (key,)
            ).fetchone()
            if row and row[0] != "":
                return str(row[0])
        except sqlite3.OperationalError:
            continue
    return None


def indexed_commit(con: sqlite3.Connection) -> str | None:
    """Read the commit SHA recorded when the index was last built."""
    return _get_meta(con, "indexed_commit")


def index_timestamp(con: sqlite3.Connection) -> int | None:
    """Return unix timestamp of the last indexing run."""
    val = _get_meta(con, "index_timestamp")
    try:
        return int(val) if val is not None else None
    except ValueError:
        return None


def index_generation(con: sqlite3.Connection) -> int:
    """Return the monotonic index generation counter."""
    val = _get_meta(con, "index_generation")
    try:
        return int(val) if val is not None else 0
    except ValueError:
        return 0


def save_commit(con: sqlite3.Connection, commit: str | None, timestamp: int) -> None:
    """Persist commit SHA and timestamp into metadata tables."""
    _ensure_meta_table(con)
    for table in ("codegraph_meta", "metadata"):
        for key, val in [
            ("indexed_commit", commit or ""),
            ("index_timestamp", str(timestamp)),
        ]:
            try:
                con.execute(
                    f"INSERT INTO {table}(key, value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, val),
                )
            except sqlite3.OperationalError:
                pass


def _ensure_meta_table(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS codegraph_meta "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS metadata "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def compute_invalidated_dependents(
    con: sqlite3.Connection, changed_paths: set[str]
) -> dict[str, list[str]]:
    """Given a set of modified/deleted file paths, compute dependent files and symbols that must be invalidated."""
    from codegraph.indexing.models import normalize_module

    if not changed_paths:
        return {
            "files": [],
            "modules": [],
            "symbols": [],
            "dependent_files": [],
        }

    changed_modules = {normalize_module(p) for p in changed_paths}
    invalidated_symbols: set[str] = set()
    dependent_files: set[str] = set()

    for p in changed_paths:
        try:
            rows = con.execute(
                "SELECT canonical_id, qualified_name FROM symbols WHERE path=?", (p,)
            ).fetchall()
            for r in rows:
                invalidated_symbols.add(str(r["canonical_id"] or r["qualified_name"]))
        except sqlite3.OperationalError:
            pass

    for mod in changed_modules:
        try:
            imp_rows = con.execute(
                "SELECT DISTINCT source_path FROM imports "
                "WHERE resolved_module=? OR imported_module=? OR module=? OR module LIKE ?",
                (mod, mod, mod, f"%{mod.split('.')[-1]}"),
            ).fetchall()
            for r in imp_rows:
                if r["source_path"] not in changed_paths:
                    dependent_files.add(str(r["source_path"]))
        except sqlite3.OperationalError:
            pass

    return {
        "files": sorted(changed_paths),
        "modules": sorted(changed_modules),
        "symbols": sorted(invalidated_symbols),
        "dependent_files": sorted(dependent_files),
    }


def check_freshness(
    repository: Path, con: sqlite3.Connection
) -> FreshnessReport:
    """Compare index state against current filesystem state."""
    _ensure_meta_table(con)

    idx_commit = indexed_commit(con)
    cur_commit = current_commit(repository)
    idx_ts = index_timestamp(con)
    parser_ver = _get_meta(con, "parser_version")
    gen = index_generation(con)

    try:
        file_count = con.execute("SELECT count(*) FROM files").fetchone()[0]
    except sqlite3.OperationalError:
        return FreshnessReport(
            status=FreshnessStatus.UNKNOWN,
            indexed_commit=idx_commit,
            current_commit=cur_commit,
            index_timestamp=idx_ts,
            parser_version=parser_ver,
            index_generation=gen,
            detail="No index found. Run `codegraph index` first.",
        )

    if file_count == 0:
        return FreshnessReport(
            status=FreshnessStatus.UNKNOWN,
            indexed_commit=idx_commit,
            current_commit=cur_commit,
            index_timestamp=idx_ts,
            parser_version=parser_ver,
            index_generation=gen,
            detail="Index is empty. Run `codegraph index` first.",
        )

    modified: list[str] = []
    deleted: list[str] = []
    parse_failed: list[str] = []

    # Fast path 1: Git commit diff (branch switch or commit advance)
    git_diff_handled = False
    if cur_commit and idx_commit and cur_commit != idx_commit:
        diff_out = _run_git(repository, "diff", "--name-status", idx_commit, cur_commit)
        if diff_out is not None:
            git_diff_handled = True
            for line in diff_out.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    action, fpath = parts[0], parts[1]
                    if action.startswith("D"):
                        deleted.append(fpath)
                    else:
                        modified.append(fpath)

    # Fast path 2: Git status when HEAD commit is unchanged
    if not git_diff_handled and cur_commit and idx_commit and cur_commit == idx_commit:
        status_out = _run_git(repository, "status", "--porcelain", "--untracked-files=no")
        if status_out is not None and not status_out.strip():
            # Working tree has zero tracked changes against HEAD
            git_diff_handled = True
            try:
                pf_rows = con.execute("SELECT path FROM files WHERE status='parse_failed'").fetchall()
                for r in pf_rows:
                    parse_failed.append(str(r[0]))
                    modified.append(str(r[0]))
            except sqlite3.OperationalError:
                pass

    if not git_diff_handled:
        try:
            rows = con.execute("SELECT path, hash, status, indexed_at FROM files").fetchall()
        except sqlite3.OperationalError:
            try:
                rows = con.execute("SELECT path, hash, status, 0 AS indexed_at FROM files").fetchall()
            except sqlite3.OperationalError:
                rows = con.execute("SELECT path, hash, 'ok' AS status, 0 AS indexed_at FROM files").fetchall()

        for row in rows:
            rel = str(row["path"])
            if row["status"] == "parse_failed":
                parse_failed.append(rel)
                if rel not in modified:
                    modified.append(rel)
            abs_path = repository / rel
            if not abs_path.exists():
                deleted.append(rel)
            else:
                try:
                    st = abs_path.stat()
                    # Mtime check: skip reading & hashing files strictly older than indexing time
                    idx_at = int(row["indexed_at"] or 0)
                    if idx_at > 0 and int(st.st_mtime) < idx_at and row["status"] != "parse_failed":
                        continue
                    digest = hashlib.sha256(
                        abs_path.read_text(encoding="utf-8", errors="replace").encode()
                    ).hexdigest()
                    if digest != row["hash"] and rel not in modified:
                        modified.append(rel)
                except OSError:
                    if rel not in modified:
                        modified.append(rel)

    changed = len(modified) + len(deleted)
    if changed == 0 and not parse_failed and (idx_commit == cur_commit or cur_commit is None):
        status = FreshnessStatus.FRESH
        detail = "Index matches current repository state."
    elif parse_failed and changed == len(parse_failed):
        status = FreshnessStatus.PARTIALLY_STALE
        detail = f"{len(parse_failed)} file(s) had syntax errors; last-known-good index retained (stale)."
    elif changed == 0:
        status = FreshnessStatus.PARTIALLY_STALE
        detail = f"Commit changed ({_short(idx_commit)} → {_short(cur_commit)}) but no file hashes differ."
    elif changed < file_count:
        status = FreshnessStatus.PARTIALLY_STALE
        detail = f"{changed} file(s) changed since indexing."
    else:
        status = FreshnessStatus.STALE
        detail = f"All {file_count} indexed files may have changed. Re-index recommended."

    return FreshnessReport(
        status=status,
        indexed_commit=idx_commit,
        current_commit=cur_commit,
        index_timestamp=idx_ts,
        modified_files=modified,
        deleted_files=deleted,
        parse_failed_files=parse_failed,
        parser_version=parser_ver,
        index_generation=gen,
        detail=detail,
    )


def _short(sha: str | None) -> str:
    return sha[:8] if sha else "unknown"
