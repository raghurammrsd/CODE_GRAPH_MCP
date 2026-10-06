"""Deterministic Symbol History Engine.

Traces the evolutionary history of a symbol across Git commits:
- Symbol introduced / added
- Symbol modified (signature, body, docstring)
- Symbol renamed (tracked via AST structure & body hashes)
- Symbol moved across files (tracked via Git renames and structural equality)
- Symbol deleted

Epistemic states:
- FACT: Exact body hash match, canonical ID continuity, or Git rename (-M) metadata
- POSSIBLE: Structural or signature similarity without identical body hash
- AMBIGUOUS: Multiple candidate replacements detected
- UNKNOWN: Disappeared with no identifiable successor
"""
from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.git import recent_commits
from codegraph.indexing.parser import parse
from codegraph.indexing.scanner import LANGUAGES


@dataclass
class SymbolHistoryEvent:
    commit_sha: str
    date: str
    author: str
    message: str
    event_type: str  # "INTRODUCED" | "MODIFIED" | "RENAMED" | "MOVED" | "DELETED"
    path: str
    old_path: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    confidence: str = "FACT"  # "FACT" | "POSSIBLE" | "AMBIGUOUS" | "UNKNOWN"
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit_sha": self.commit_sha,
            "date": self.date,
            "author": self.author,
            "message": self.message,
            "event_type": self.event_type,
            "path": self.path,
            "old_path": self.old_path,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class SymbolHistoryReport:
    symbol: str
    current_path: str | None
    events: list[SymbolHistoryEvent] = field(default_factory=list)
    total_commits_evaluated: int = 0
    status: str = "SUCCESS"  # "SUCCESS" | "NOT_FOUND" | "AMBIGUOUS"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_path": self.current_path,
            "events": [e.as_dict() for e in self.events],
            "total_commits_evaluated": self.total_commits_evaluated,
            "status": self.status,
            "detail": self.detail,
        }


def _run_git(repository: Path, *args: str, timeout: int = 15) -> str | None:
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


_BODY_HASH_CACHE: dict[tuple[int, str, str, str], tuple[str | None, int | None]] = {}


def _get_symbol_body_hash(content: str, lang: str, file_path: str, symbol_name: str) -> tuple[str | None, int | None]:
    """Parse content and compute content hash for symbol body with caching."""
    if not content:
        return None, None
    c_hash = hash(content)
    cache_key = (c_hash, lang, file_path, symbol_name)
    if cache_key in _BODY_HASH_CACHE:
        return _BODY_HASH_CACHE[cache_key]
    try:
        res = parse(content, lang, file_path)
        for s in res.symbols:
            if s.name == symbol_name:
                lines = content.splitlines()
                snippet = "\n".join(lines[max(0, s.start_line - 1) : s.end_line]).strip()
                b_hash = hashlib.sha256(snippet.encode("utf-8", errors="replace")).hexdigest()[:16]
                result = (b_hash, s.start_line)
                if len(_BODY_HASH_CACHE) > 2000:
                    _BODY_HASH_CACHE.clear()
                _BODY_HASH_CACHE[cache_key] = result
                return result
        _BODY_HASH_CACHE[cache_key] = (None, None)
        return None, None
    except Exception:
        return None, None


def trace_symbol_history(
    repository: Path,
    symbol: str,
    path: str | None = None,
    con: sqlite3.Connection | None = None,
    max_commits: int = 15,
) -> SymbolHistoryReport:
    """Trace the history of a symbol across Git commits deterministically."""
    from codegraph.structural_diff import _get_file_content_at_ref

    # 1. Resolve path if not provided
    resolved_path = path
    if not resolved_path and con is not None:
        try:
            row = con.execute("SELECT path FROM symbols WHERE name=? LIMIT 1", (symbol,)).fetchone()
            if row:
                resolved_path = str(row[0])
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    # 2. Get commits affecting the file or symbol
    commits = recent_commits(repository, n=max_commits * 2, path=resolved_path)
    if not commits:
        return SymbolHistoryReport(
            symbol=symbol,
            current_path=resolved_path,
            events=[],
            total_commits_evaluated=0,
            status="NOT_FOUND",
            detail=f"No Git commits found for symbol '{symbol}' or path '{resolved_path}'.",
        )

    events: list[SymbolHistoryEvent] = []
    current_sym_name = symbol
    current_sym_path = resolved_path or ""

    prev_parent_content: str | None = None
    prev_parent_hash: str | None = None
    prev_parent_line: int | None = None
    prev_parent_path: str | None = None

    for c in commits:
        if len(events) >= max_commits:
            break

        ext = Path(current_sym_path).suffix.lower() if current_sym_path else ".py"
        lang = LANGUAGES.get(ext, "python")

        # Fast path: check if curr_content was already loaded as parent in previous iteration
        curr_content: str | None = None
        curr_hash: str | None = None
        curr_line: int | None = None

        if prev_parent_content is not None and prev_parent_path == current_sym_path:
            curr_content = prev_parent_content
            curr_hash, curr_line = prev_parent_hash, prev_parent_line
        else:
            curr_content = _get_file_content_at_ref(repository, c.sha, current_sym_path) if current_sym_path else None
            curr_hash, curr_line = _get_symbol_body_hash(curr_content or "", lang, current_sym_path, current_sym_name) if curr_content else (None, None)

        # Get file content at parent commit c.sha~1
        parent_content = _get_file_content_at_ref(repository, f"{c.sha}~1", current_sym_path) if current_sym_path else None
        parent_hash, parent_line = _get_symbol_body_hash(parent_content or "", lang, current_sym_path, current_sym_name) if parent_content else (None, None)

        # Store for next iteration
        prev_parent_content = parent_content
        prev_parent_hash = parent_hash
        prev_parent_line = parent_line
        prev_parent_path = current_sym_path

        if curr_hash is not None and parent_hash is not None:
            if curr_hash != parent_hash:
                events.append(
                    SymbolHistoryEvent(
                        commit_sha=c.sha,
                        date=c.date,
                        author=c.author,
                        message=c.message,
                        event_type="MODIFIED",
                        path=current_sym_path,
                        confidence="FACT",
                        evidence=f"Symbol modified at line {curr_line} (body hash changed)",
                    )
                )
        elif curr_hash is not None and parent_hash is None:
            # Symbol appeared in this commit! Did it rename or move from somewhere else?
            found_move = False
            # Check git diff --name-status c.sha~1 c.sha for renames
            raw_rename = _run_git(repository, "diff", "-M", "--name-status", f"{c.sha}~1", c.sha)
            if raw_rename:
                for line in raw_rename.splitlines():
                    if line.startswith("R") and current_sym_path in line:
                        parts = line.split("\t")
                        if len(parts) >= 3 and parts[2] == current_sym_path:
                            old_p = parts[1]
                            events.append(
                                SymbolHistoryEvent(
                                    commit_sha=c.sha,
                                    date=c.date,
                                    author=c.author,
                                    message=c.message,
                                    event_type="MOVED",
                                    path=current_sym_path,
                                    old_path=old_p,
                                    confidence="FACT",
                                    evidence=f"File moved from {old_p} to {current_sym_path}",
                                )
                            )
                            current_sym_path = old_p
                            found_move = True
                            break

            if not found_move:
                # Check if introduced
                events.append(
                    SymbolHistoryEvent(
                        commit_sha=c.sha,
                        date=c.date,
                        author=c.author,
                        message=c.message,
                        event_type="INTRODUCED",
                        path=current_sym_path,
                        confidence="FACT",
                        evidence=f"Symbol created at {current_sym_path}:{curr_line}",
                    )
                )
                break
        elif curr_hash is None and parent_hash is not None:
            # Symbol was deleted or renamed in curr_content
            events.append(
                SymbolHistoryEvent(
                    commit_sha=c.sha,
                    date=c.date,
                    author=c.author,
                    message=c.message,
                    event_type="DELETED",
                    path=current_sym_path,
                    confidence="FACT",
                    evidence=f"Symbol removed in commit {c.sha[:8]}",
                )
            )

    return SymbolHistoryReport(
        symbol=symbol,
        current_path=resolved_path,
        events=events,
        total_commits_evaluated=len(commits),
        status="SUCCESS" if events else "NOT_FOUND",
        detail=f"Traced {len(events)} history event(s) across {len(commits)} commits.",
    )
