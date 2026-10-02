"""Read-only Git intelligence.

All Git operations use an explicit allowlist of commands and validated
arguments.  No arbitrary shell execution.  No network access.
"""
from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommitInfo:
    sha: str
    author: str
    date: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"sha": self.sha, "author": self.author, "date": self.date, "message": self.message}


@dataclass
class FileDiff:
    path: str
    status: str   # M=modified, A=added, D=deleted, R=renamed
    diff_snippet: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "status": self.status, "diff_snippet": self.diff_snippet}


def _git(repository: Path, *args: str, timeout: int = 15) -> str | None:
    """Run a git subprocess with validated arguments only."""
    # Validate: no shell metacharacters, no absolute paths from user input
    for arg in args:
        if any(c in arg for c in (";", "|", "&", "`", "$", "\n", "\r")):
            return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def is_git_repository(repository: Path) -> bool:
    return _git(repository, "rev-parse", "--git-dir") is not None


def current_commit(repository: Path) -> str | None:
    """Return the current HEAD commit SHA, or None if not a git repository."""
    raw = _git(repository, "rev-parse", "HEAD")
    return raw.strip() if raw else None


def recent_commits(
    repository: Path,
    n: int = 10,
    path: str | None = None,
) -> list[CommitInfo]:
    """Return the last N commits, optionally scoped to a file path."""
    if not 1 <= n <= 100:
        n = 10
    args = ["log", f"-{n}", "--format=%H\x1f%an\x1f%ai\x1f%s"]
    if path:
        # Sanitize: path must not be absolute or contain traversal
        if ".." in path or path.startswith("/"):
            return []
        args += ["--", path]
    raw = _git(repository, *args)
    if not raw:
        return []
    commits = []
    for line in raw.strip().splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) == 4:
            commits.append(CommitInfo(*parts))
    return commits


def changed_files(
    repository: Path,
    since: str = "HEAD~10",
    until: str = "HEAD",
) -> list[FileDiff]:
    """Return files changed between two commits."""
    # Validate refs — allow only hex SHAs, HEAD, HEAD~N, branch names (alphanumeric + /-_.)
    import re
    _REF = re.compile(r"^[A-Za-z0-9_.~^/-]{1,100}$")
    if not _REF.match(since) or not _REF.match(until):
        return []
    raw = _git(repository, "diff", "--name-status", since, until)
    if not raw:
        return []
    diffs: list[FileDiff] = []
    for line in raw.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status, path = parts[0].strip()[0], parts[1].strip()
            diffs.append(FileDiff(path=path, status=status))
    return diffs


def file_diff(
    repository: Path,
    path: str,
    since: str = "HEAD~1",
    until: str = "HEAD",
    max_lines: int = 50,
) -> str:
    """Return a bounded unified diff for a single file."""
    import re
    _REF = re.compile(r"^[A-Za-z0-9_.~^/-]{1,100}$")
    if not _REF.match(since) or not _REF.match(until):
        return ""
    if ".." in path or path.startswith("/"):
        return ""
    raw = _git(repository, "diff", since, until, "--", path)
    if not raw:
        return ""
    lines = raw.splitlines()[:max_lines]
    return "\n".join(lines)


def blame_line(
    repository: Path,
    path: str,
    line: int,
) -> dict[str, str] | None:
    """Return blame info for a single line."""
    if ".." in path or path.startswith("/"):
        return None
    if not 1 <= line <= 100_000:
        return None
    raw = _git(
        repository, "blame", f"-L{line},{line}", "--porcelain", "--", path
    )
    if not raw:
        return None
    info: dict[str, str] = {}
    lines = raw.splitlines()
    if lines:
        info["sha"] = lines[0].split()[0] if lines else ""
    for bl in lines[1:]:
        if bl.startswith("author "):
            info["author"] = bl[7:]
        elif bl.startswith("author-time "):
            info["timestamp"] = bl[12:]
        elif bl.startswith("summary "):
            info["summary"] = bl[8:]
    return info or None


def changed_symbols_since(
    repository: Path,
    since: str,
    symbol_names: set[str],
) -> list[str]:
    """Return subset of symbol_names that appear in changed lines since `since`.

    This is a heuristic: it checks whether the symbol name appears in the
    diff text.  Results are LOW confidence.
    """
    import re
    _REF = re.compile(r"^[A-Za-z0-9_.~^/-]{1,100}$")
    if not _REF.match(since):
        return []
    raw = _git(repository, "diff", since, "HEAD")
    if not raw:
        return []
    found = []
    for name in symbol_names:
        # Only match if the name appears in added/removed diff lines
        if re.search(rf"^[+-].*\b{re.escape(name)}\b", raw, re.MULTILINE):
            found.append(name)
    return found


def get_file_history(
    repository: Path,
    path: str,
    n: int = 10,
) -> list[dict[str, str]]:
    """Return commit history for a single file path."""
    commits = recent_commits(repository, n=n, path=path)
    return [c.as_dict() for c in commits]


def get_symbol_history(
    repository: Path,
    path: str,
    symbol: str,
    n: int = 10,
) -> list[dict[str, str]]:
    """Return commits where a specific symbol name was modified in a file."""
    all_file_commits = recent_commits(repository, n=n * 2, path=path)
    matching: list[dict[str, str]] = []
    import re
    for c in all_file_commits:
        diff_text = file_diff(repository, path, since=f"{c.sha}~1", until=c.sha, max_lines=200)
        if re.search(rf"\b{re.escape(symbol)}\b", diff_text):
            matching.append(c.as_dict())
            if len(matching) >= n:
                break
    return matching


def get_change_context(
    repository: Path,
    since: str = "HEAD~1",
    until: str = "HEAD",
) -> dict[str, object]:
    """Return summary of changed files and bounded snippets."""
    diffs = changed_files(repository, since=since, until=until)
    file_summaries: list[dict[str, str]] = []
    for d in diffs[:20]:
        snippet = file_diff(repository, d.path, since=since, until=until, max_lines=30)
        file_summaries.append(
            {
                "path": d.path,
                "status": d.status,
                "diff_snippet": snippet,
            }
        )
    return {
        "since": since,
        "until": until,
        "total_changed": len(diffs),
        "files": file_summaries,
    }


def analyze_change_impact(
    con: sqlite3.Connection,
    repository: Path,
    since: str = "HEAD~1",
    until: str = "HEAD",
) -> dict[str, object]:
    """Analyze downstream callers and tests affected by changes between since and until."""
    diffs = changed_files(repository, since=since, until=until)
    changed_paths = [d.path for d in diffs]
    changed_symbols: list[str] = []
    affected_callers: list[dict[str, object]] = []
    affected_tests: list[dict[str, object]] = []

    from codegraph.graph.traversal import find_callers, find_related_tests

    for p in changed_paths:
        rows = con.execute("SELECT name, qualified_name FROM symbols WHERE path=?", (p,)).fetchall()
        sym_names = {r["name"] for r in rows}
        matched = changed_symbols_since(repository, since, sym_names)
        for s in matched:
            changed_symbols.append(s)
            callers = find_callers(con, s, max_results=5)
            for c in callers:
                affected_callers.append(dict(c))
            tests = find_related_tests(con, s, max_results=5)
            for t in tests:
                if "result" not in t:
                    affected_tests.append(dict(t))

    return {
        "since": since,
        "until": until,
        "changed_files": [d.as_dict() for d in diffs],
        "changed_symbols": changed_symbols,
        "affected_callers": affected_callers,
        "affected_tests": affected_tests,
    }

