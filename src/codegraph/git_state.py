"""Git state tracking and freshness engine.

Tracks:
- current branch
- current HEAD commit SHA
- indexed HEAD commit SHA
- working-tree state (modified, staged, untracked relevant files, deleted)
- explicit freshness states: CLEAN, DIRTY, STALE, REINDEXING, ERROR

Enforces:
- sub-50ms quick freshness checks
- incremental synchronization of affected graph state without full re-indexing
- deterministic evidence-backed status reporting
"""
from __future__ import annotations

import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from codegraph.errors import SecurityError
from codegraph.security import safe_path


class GitFreshnessState(StrEnum):
    CLEAN = "CLEAN"           # Current HEAD == indexed HEAD, working tree clean
    DIRTY = "DIRTY"           # Current HEAD == indexed HEAD, but uncommitted working tree changes
    STALE = "STALE"           # Current HEAD != indexed HEAD (commits advanced or branch switched)
    REINDEXING = "REINDEXING" # Index lock active / reindexing underway
    ERROR = "ERROR"           # Not a git repo, git binary missing, or fatal error


@dataclass
class WorkingTreeStatus:
    is_dirty: bool
    modified_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    renamed_files: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_dirty": self.is_dirty,
            "modified_files": self.modified_files,
            "staged_files": self.staged_files,
            "untracked_files": self.untracked_files,
            "deleted_files": self.deleted_files,
            "renamed_files": self.renamed_files,
        }


@dataclass
class GitStateReport:
    is_git: bool
    branch: str | None
    current_head: str | None
    indexed_head: str | None
    freshness: GitFreshnessState
    working_tree: WorkingTreeStatus
    reindex_required: bool
    detail: str = ""
    last_indexed_at: int | None = None
    affected_files_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_git": self.is_git,
            "branch": self.branch,
            "current_head": self.current_head,
            "indexed_head": self.indexed_head,
            "freshness": self.freshness.value,
            "working_tree": self.working_tree.as_dict(),
            "reindex_required": self.reindex_required,
            "detail": self.detail,
            "last_indexed_at": self.last_indexed_at,
            "affected_files_count": self.affected_files_count,
        }


def _run_git_cmd(repository: Path, *args: str, timeout: int = 10) -> str | None:
    """Execute an allowlisted git command safely within repository boundary."""
    for arg in args:
        if any(c in arg for c in (";", "|", "&", "`", "$", "\n", "\r")):
            return None
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.stdout if res.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def get_indexed_commit(con: sqlite3.Connection | None) -> str | None:
    """Read indexed commit SHA from metadata table if available."""
    if con is None:
        return None
    for table in ("metadata", "codegraph_meta"):
        try:
            row = con.execute(f"SELECT value FROM {table} WHERE key='indexed_commit'").fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            continue
    return None


def get_last_indexed_timestamp(con: sqlite3.Connection | None) -> int | None:
    """Read index_timestamp from metadata table if available."""
    if con is None:
        return None
    for table in ("metadata", "codegraph_meta"):
        try:
            row = con.execute(f"SELECT value FROM {table} WHERE key='index_timestamp'").fetchone()
            if row and row[0]:
                return int(row[0])
        except (sqlite3.OperationalError, sqlite3.DatabaseError, ValueError):
            continue
    return None


def is_reindexing_active(repository: Path) -> bool:
    """Check if index lock or reindexing marker is currently active."""
    lock_file = repository / ".codegraph" / "indexing.lock"
    legacy_lock = repository / ".codegraph.lock"
    return lock_file.exists() or legacy_lock.exists()


# Recognized source extensions for tracking relevant untracked files
RELEVANT_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx", ".sql", ".prisma", ".json", ".toml", ".yaml", ".yml"}


def _fast_read_git_head_and_branch(repository: Path) -> tuple[str | None, str | None]:
    """Pure-Python zero-subprocess resolution of HEAD commit SHA and current branch.

    Resolves in <0.2ms on standard repositories, falling back to None if non-standard or missing.
    """
    git_dir = repository / ".git"
    if git_dir.is_file():
        # Git worktree or submodule pointing to another gitdir
        try:
            content = git_dir.read_text(encoding="utf-8", errors="replace").strip()
            if content.startswith("gitdir:"):
                target = Path(content.split(":", 1)[1].strip())
                git_dir = target if target.is_absolute() else (repository / target).resolve()
        except OSError:
            return None, None
    if not git_dir.exists() or not git_dir.is_dir():
        return None, None

    head_file = git_dir / "HEAD"
    if not head_file.exists():
        return None, None

    try:
        head_text = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if head_text.startswith("ref:"):
            ref_path = head_text.split(":", 1)[1].strip()
            branch = ref_path.replace("refs/heads/", "")
            # Check loose ref
            ref_file = git_dir / ref_path
            if ref_file.exists():
                return ref_file.read_text(encoding="utf-8", errors="replace").strip(), branch
            # Check packed-refs
            packed_file = git_dir / "packed-refs"
            if packed_file.exists():
                for line in packed_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("#") or line.startswith("^"):
                        continue
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[1] == ref_path:
                        return parts[0], branch
            return None, branch
        elif len(head_text) == 40 and all(c in "0123456789abcdefABCDEF" for c in head_text):
            return head_text, f"detached:{head_text[:8]}"
    except OSError:
        pass

    return None, None


_WORKING_TREE_CACHE: dict[str, tuple[float, WorkingTreeStatus]] = {}


def clear_working_tree_cache() -> None:
    """Clear cached working tree statuses."""
    _WORKING_TREE_CACHE.clear()


def get_working_tree_status(repository: Path, max_age_ms: float = 0.0) -> WorkingTreeStatus:
    """Inspect working tree status using git status porcelain v1 with optional sub-millisecond caching."""
    repo_key = str(repository.resolve())
    now = time.monotonic()
    if max_age_ms > 0.0 and repo_key in _WORKING_TREE_CACHE:
        cached_time, cached_val = _WORKING_TREE_CACHE[repo_key]
        if (now - cached_time) * 1000.0 < max_age_ms:
            return cached_val

    raw = _run_git_cmd(repository, "status", "--porcelain=v1", "-uall")
    if raw is None:
        return WorkingTreeStatus(is_dirty=False)

    modified: list[str] = []
    staged: list[str] = []
    untracked: list[str] = []
    deleted: list[str] = []
    renamed: list[dict[str, str]] = []

    for line in raw.splitlines():
        if len(line) < 4:
            continue
        index_status = line[0]
        work_status = line[1]
        path_part = line[3:].strip()

        # Handle renamed format: "R  old -> new"
        if " -> " in path_part:
            old_p, new_p = path_part.split(" -> ", 1)
            old_p = old_p.strip().strip('"')
            new_p = new_p.strip().strip('"')
            renamed.append({"old_path": old_p, "new_path": new_p})
            staged.append(new_p)
            continue

        clean_path = path_part.strip('"')

        # Staged changes (index)
        if index_status in ("M", "A", "R"):
            if clean_path not in staged:
                staged.append(clean_path)
        elif index_status == "D":
            if clean_path not in deleted:
                deleted.append(clean_path)

        # Working tree changes
        if work_status == "M":
            if clean_path not in modified:
                modified.append(clean_path)
        elif work_status == "D":
            if clean_path not in deleted:
                deleted.append(clean_path)
        elif work_status == "?":
            # Only include untracked if relevant source file
            ext = Path(clean_path).suffix.lower()
            if ext in RELEVANT_EXTENSIONS:
                untracked.append(clean_path)

    is_dirty = bool(modified or staged or untracked or deleted or renamed)
    res = WorkingTreeStatus(
        is_dirty=is_dirty,
        modified_files=sorted(modified),
        staged_files=sorted(staged),
        untracked_files=sorted(untracked),
        deleted_files=sorted(deleted),
        renamed_files=renamed,
    )
    _WORKING_TREE_CACHE[repo_key] = (now, res)
    return res


_DIFF_COUNT_CACHE: dict[tuple[str, str, str], int] = {}


def _get_cached_diff_count(repository: Path, base: str, head: str) -> int:
    """Cache diff counts between immutable commit SHAs to avoid redundant subprocess invocations."""
    cache_key = (str(repository), base, head)
    if cache_key in _DIFF_COUNT_CACHE:
        return _DIFF_COUNT_CACHE[cache_key]
    diff_out = _run_git_cmd(repository, "diff", "--name-only", base, head)
    count = len(diff_out.splitlines()) if diff_out else 0
    if len(_DIFF_COUNT_CACHE) > 500:
        _DIFF_COUNT_CACHE.clear()
    _DIFF_COUNT_CACHE[cache_key] = count
    return count


def get_git_state(
    repository: Path,
    con: sqlite3.Connection | None = None,
    cache_ttl_ms: float = 0.0,
) -> GitStateReport:
    """Compute comprehensive Git state and freshness assessment."""
    if is_reindexing_active(repository):
        return GitStateReport(
            is_git=True,
            branch=None,
            current_head=None,
            indexed_head=get_indexed_commit(con),
            freshness=GitFreshnessState.REINDEXING,
            working_tree=WorkingTreeStatus(is_dirty=False),
            reindex_required=False,
            detail="Repository reindexing lock is currently active.",
            last_indexed_at=get_last_indexed_timestamp(con),
        )

    # 1. Fast zero-subprocess check for Git directory, HEAD, and branch
    current_head, branch = _fast_read_git_head_and_branch(repository)
    is_git_confirmed = bool(current_head or branch or (repository / ".git").exists())

    if not is_git_confirmed:
        # Fallback check for non-standard GIT_DIR env or worktree
        git_dir = _run_git_cmd(repository, "rev-parse", "--git-dir")
        if git_dir is None:
            return GitStateReport(
                is_git=False,
                branch=None,
                current_head=None,
                indexed_head=get_indexed_commit(con),
                freshness=GitFreshnessState.ERROR,
                working_tree=WorkingTreeStatus(is_dirty=False),
                reindex_required=False,
                detail="Repository is not a Git repository.",
                last_indexed_at=get_last_indexed_timestamp(con),
            )

    # 2. If HEAD or branch was not resolved by fast-path, query Git CLI
    if not current_head:
        head_raw = _run_git_cmd(repository, "rev-parse", "HEAD")
        current_head = head_raw.strip() if head_raw else None

    if not branch:
        branch_raw = _run_git_cmd(repository, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_raw.strip() if branch_raw else None
        if branch == "HEAD":
            branch = f"detached:{current_head[:8]}" if current_head else "detached"

    indexed_head = get_indexed_commit(con)
    last_indexed_at = get_last_indexed_timestamp(con)
    wt_status = get_working_tree_status(repository, max_age_ms=cache_ttl_ms)

    # 3. Determine freshness state
    if indexed_head is None:
        # Never indexed
        freshness = GitFreshnessState.STALE
        detail = "Repository has not been indexed yet."
        reindex_required = True
        affected_count = len(wt_status.modified_files) + len(wt_status.staged_files)
    elif current_head != indexed_head:
        # Commit advanced or branch switched
        freshness = GitFreshnessState.STALE
        detail = f"Indexed commit ({indexed_head[:8]}) does not match current HEAD ({current_head[:8] if current_head else 'none'})."
        reindex_required = True
        # Calculate diff files between indexed_head and current_head with caching
        diff_count = _get_cached_diff_count(repository, indexed_head, current_head or "HEAD")
        affected_count = diff_count + len(wt_status.modified_files) + len(wt_status.staged_files)
    elif wt_status.is_dirty:
        freshness = GitFreshnessState.DIRTY
        detail = "Working tree has uncommitted modifications, staged changes, or relevant untracked files."
        reindex_required = True
        affected_count = len(wt_status.modified_files) + len(wt_status.staged_files) + len(wt_status.untracked_files) + len(wt_status.deleted_files)
    else:
        freshness = GitFreshnessState.CLEAN
        detail = f"Index is fresh at HEAD ({current_head[:8] if current_head else 'clean'}) with clean working tree."
        reindex_required = False
        affected_count = 0

    return GitStateReport(
        is_git=True,
        branch=branch,
        current_head=current_head,
        indexed_head=indexed_head,
        freshness=freshness,
        working_tree=wt_status,
        reindex_required=reindex_required,
        detail=detail,
        last_indexed_at=last_indexed_at,
        affected_files_count=affected_count,
    )


@dataclass
class IncrementalSyncResult:
    status: str
    reindexed_files: list[str]
    deleted_files: list[str]
    new_commit: str | None
    duration_ms: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reindexed_files": self.reindexed_files,
            "deleted_files": self.deleted_files,
            "new_commit": self.new_commit,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }


def incremental_git_sync(
    repository: Path,
    con: sqlite3.Connection,
) -> IncrementalSyncResult:
    """Incrementally synchronize the affected graph state without a full repository rebuild.
    
    Identifies changed/added/deleted/renamed files and updates the index database
    selectively, updating indexed_commit when working tree is clean.
    """
    import time

    from codegraph.config import Settings
    from codegraph.indexing import Indexer

    start_time = time.perf_counter()
    state = get_git_state(repository, con=con)

    if not state.is_git:
        return IncrementalSyncResult(
            status="error",
            reindexed_files=[],
            deleted_files=[],
            new_commit=None,
            duration_ms=0.0,
            detail="Cannot incrementally sync non-git repository.",
        )

    if state.freshness == GitFreshnessState.CLEAN:
        return IncrementalSyncResult(
            status="clean",
            reindexed_files=[],
            deleted_files=[],
            new_commit=state.current_head,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            detail="Repository index is already fresh.",
        )

    affected_modified: set[str] = set()
    affected_deleted: set[str] = set()

    # 1. Collect files changed between indexed_head and current_head
    if state.indexed_head and state.current_head and state.indexed_head != state.current_head:
        diff_raw = _run_git_cmd(repository, "diff", "--name-status", state.indexed_head, state.current_head)
        if diff_raw:
            for line in diff_raw.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    action, path_str = parts[0], parts[1]
                    if action.startswith("D"):
                        affected_deleted.add(path_str)
                    else:
                        affected_modified.add(path_str)

    # 2. Add working tree changes
    wt = state.working_tree
    for p in wt.modified_files:
        affected_modified.add(p)
    for p in wt.staged_files:
        affected_modified.add(p)
    for p in wt.untracked_files:
        affected_modified.add(p)
    for p in wt.deleted_files:
        affected_deleted.add(p)
    for r in wt.renamed_files:
        affected_deleted.add(r["old_path"])
        affected_modified.add(r["new_path"])

    # Don't try to index files that were deleted
    affected_modified -= affected_deleted

    if not affected_modified and not affected_deleted:
        if not wt.is_dirty and state.current_head:
            from codegraph.freshness import save_commit
            save_commit(con, state.current_head, int(time.time()))
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return IncrementalSyncResult(
            status="clean",
            reindexed_files=[],
            deleted_files=[],
            new_commit=state.current_head,
            duration_ms=elapsed_ms,
            detail="Repository index is already fresh.",
        )

    # Query known hashes to skip unchanged files
    existing_hashes: dict[str, str] = {}
    try:
        cur = con.execute("SELECT path, hash FROM files")
        for row in cur.fetchall():
            existing_hashes[str(row[0])] = str(row[1])
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass

    from codegraph.indexing.scanner import LANGUAGES

    indexer = Indexer(repository, Settings(repository=repository))
    reindexed: list[str] = []
    removed: list[str] = []

    # 3. Clean up deleted files from graph
    for d_path in affected_deleted:
        indexer._delete_file(con, d_path)
        removed.append(d_path)

    # 4. Incrementally index modified / added files
    import hashlib
    for m_path in affected_modified:
        abs_p = repository / m_path
        if abs_p.exists() and abs_p.is_file():
            try:
                # safe_path check
                safe_path(repository, m_path)
                ext = abs_p.suffix.lower()
                lang = LANGUAGES.get(ext)
                if not lang:
                    continue
                content = abs_p.read_text(encoding="utf-8", errors="replace")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if existing_hashes.get(m_path) == digest:
                    # Content is unchanged from current index; skip reindexing
                    continue
                indexer._replace_file(con, m_path, lang, content, digest)
                reindexed.append(m_path)
            except (SecurityError, Exception):
                continue

    if reindexed or removed:
        con.commit()

    # 5. If working tree is clean, update indexed_commit
    if not wt.is_dirty and state.current_head:
        from codegraph.freshness import save_commit
        save_commit(con, state.current_head, int(time.time()))

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return IncrementalSyncResult(
        status="synced",
        reindexed_files=sorted(reindexed),
        deleted_files=sorted(removed),
        new_commit=state.current_head,
        duration_ms=elapsed_ms,
        detail=f"Incrementally updated {len(reindexed)} files and removed {len(removed)} deleted files in {elapsed_ms:.1f}ms.",
    )
