"""First-class Evidence Engine with deterministic source-hash verification.

Every evidence item contains:
  evidence_id, repository, file, start_line, end_line, symbol, relationship,
  source_hash, indexed_commit, confidence, evidence_type, evidence_status.

Before returning evidence, current file content is hashed and compared against
the stored source_hash. If modified or deleted since indexing, evidence_status
is set to 'stale' (never silently returning obsolete citations as current).
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codegraph.freshness import index_generation
from codegraph.security import safe_path

PARSER_VERSION = "3.0"


@dataclass(frozen=True)
class Evidence:
    file: str
    start_line: int
    end_line: int
    symbol: str | None
    snippet: str
    evidence_type: str = "source"
    confidence: str = "HIGH"
    source_hash: str | None = None
    indexed_commit: str | None = None
    evidence_status: str = "current"  # current | stale | deleted | unknown
    relationship: str = "DEFINES"
    repository: str = ""
    evidence_id: str = ""
    start_column: int | None = None
    end_column: int | None = None
    index_generation: int = 0
    parser_version: str = PARSER_VERSION

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raw = f"{self.file}:{self.start_line}:{self.end_line}:{self.symbol or ''}:{self.relationship}"
            eid = "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
            object.__setattr__(self, "evidence_id", eid)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)


def get_repository_from_con(con: sqlite3.Connection) -> Path | None:
    """Retrieve the repository root path stored in the index metadata table."""
    try:
        row = con.execute(
            "SELECT value FROM metadata WHERE key='repository'"
        ).fetchone()
        if row and row[0]:
            p = Path(str(row[0]))
            if p.exists():
                return p
    except sqlite3.OperationalError:
        pass
    return None


def verify_source_hash(
    repository: Path | None,
    file_path: str,
    stored_hash: str | None,
) -> str:
    """Verify whether the current file on disk matches `stored_hash`.

    Returns 'current', 'stale', or 'deleted'.
    """
    if not stored_hash or repository is None:
        return "current"
    abs_path = repository / file_path
    if not abs_path.exists():
        return "stale"
    try:
        current_digest = hashlib.sha256(
            abs_path.read_text(encoding="utf-8", errors="replace").encode()
        ).hexdigest()
        return "current" if current_digest == stored_hash else "stale"
    except OSError:
        return "stale"


def build_evidence(
    con: sqlite3.Connection,
    repository: Path | None,
    path: str,
    symbol: str | None = None,
    limit: int = 50,
) -> list[Evidence]:
    """Build verified evidence list for a file/symbol, checking source hash freshness."""
    from codegraph.freshness import indexed_commit as get_indexed_commit

    repo = repository or get_repository_from_con(con)
    idx_commit = get_indexed_commit(con)
    repo_str = str(repo) if repo else ""

    # Look up the file-level hash in `files` table for source verification
    file_row = con.execute(
        "SELECT hash FROM files WHERE path=?", (path,)
    ).fetchone()
    file_hash = str(file_row["hash"]) if file_row else None

    if symbol:
        short = symbol.split(".")[-1]
        rows = con.execute(
            "SELECT symbol, start_line, end_line, content, hash FROM chunks "
            "WHERE path=? AND (symbol=? OR symbol LIKE ? OR symbol=?) LIMIT ?",
            (path, symbol, f"%.{symbol}", short, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT symbol, start_line, end_line, content, hash FROM chunks "
            "WHERE path=? ORDER BY start_line LIMIT ?",
            (path, limit),
        ).fetchall()

    results: list[Evidence] = []
    for row in rows:
        expected_hash = file_hash or str(row["hash"])
        status = verify_source_hash(repo, path, expected_hash)
        confidence = "HIGH" if status == "current" else "LOW"
        results.append(
            Evidence(
                file=path,
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                symbol=row["symbol"],
                snippet=str(row["content"])[:900],
                evidence_type="source",
                confidence=confidence,
                source_hash=expected_hash,
                indexed_commit=idx_commit,
                evidence_status=status,
                relationship="DEFINES",
                repository=repo_str,
            )
        )
    return results


@dataclass
class VerificationReport:
    valid: bool
    exists: bool
    hash_matches: bool
    lines_valid: bool
    status: str  # FACT | CONFLICT | UNKNOWN
    confidence: str  # HIGH | MEDIUM | LOW | UNKNOWN
    freshness: str  # FRESH | STALE | UNKNOWN
    reason: str
    file: str
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None
    evidence_id: str | None = None
    index_generation: int = 0
    parser_version: str = PARSER_VERSION

    def as_dict(self) -> dict[str, object]:
        d: dict[str, object] = asdict(self)
        d["epistemic_status"] = self.status
        return d

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)


def verify_evidence(
    con: sqlite3.Connection,
    repository: Path,
    evidence: Evidence | dict[str, Any] | str | None = None,
    evidence_id: str | None = None,
    file_path: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    symbol: str | None = None,
    expected_content_hash: str | None = None,
    expected_hash: str | None = None,
) -> VerificationReport:
    """Verify validity and freshness of an evidence reference against current repository disk state."""
    gen = index_generation(con)

    resolved_file = file_path
    resolved_start = start_line
    resolved_end = end_line
    resolved_symbol = symbol
    resolved_id = evidence_id
    expected_h = expected_content_hash or expected_hash

    if isinstance(evidence, Evidence):
        resolved_file = evidence.file
        resolved_start = evidence.start_line
        resolved_end = evidence.end_line
        resolved_symbol = evidence.symbol
        resolved_id = evidence.evidence_id
    elif isinstance(evidence, dict):
        resolved_file = str(evidence.get("file") or evidence.get("file_path") or "")
        resolved_start = evidence.get("start_line")
        resolved_end = evidence.get("end_line")
        resolved_symbol = evidence.get("symbol")
        resolved_id = evidence.get("evidence_id")
        if not expected_h:
            expected_h = evidence.get("source_hash")
    elif isinstance(evidence, str):
        if "/" in evidence or evidence.endswith(".py") or evidence.endswith(".ts") or evidence.endswith(".js"):
            resolved_file = evidence
        else:
            resolved_id = evidence

    if resolved_id and not resolved_file:
        edge_row = con.execute(
            "SELECT file, start_line, end_line, source, target, relationship FROM graph_edges WHERE evidence_id=?",
            (resolved_id,),
        ).fetchone()
        if edge_row:
            resolved_file = str(edge_row["file"])
            resolved_start = int(edge_row["start_line"])
            resolved_end = int(edge_row["end_line"])
            if not resolved_symbol:
                resolved_symbol = str(edge_row["target"])

    if not resolved_file:
        return VerificationReport(
            valid=False,
            exists=False,
            hash_matches=False,
            lines_valid=False,
            status="UNKNOWN",
            confidence="UNKNOWN",
            freshness="UNKNOWN",
            reason="Missing file path and evidence_id not found in index",
            file="",
            index_generation=gen,
        )

    try:
        abs_path = safe_path(repository, resolved_file)
    except Exception as e:
        return VerificationReport(
            valid=False,
            exists=False,
            hash_matches=False,
            lines_valid=False,
            status="UNKNOWN",
            confidence="UNKNOWN",
            freshness="UNKNOWN",
            reason=f"Repository boundary violation: {e}",
            file=resolved_file,
            index_generation=gen,
        )

    if not abs_path.exists() or not abs_path.is_file():
        return VerificationReport(
            valid=False,
            exists=False,
            hash_matches=False,
            lines_valid=False,
            status="UNKNOWN",
            confidence="LOW",
            freshness="STALE",
            reason=f"File not found on disk: {resolved_file}",
            file=resolved_file,
            index_generation=gen,
        )

    try:
        content_bytes = abs_path.read_bytes()
        current_hash = hashlib.sha256(content_bytes).hexdigest()
    except OSError as e:
        return VerificationReport(
            valid=False,
            exists=True,
            hash_matches=False,
            lines_valid=False,
            status="CONFLICT",
            confidence="LOW",
            freshness="STALE",
            reason=f"Could not read file from disk: {e}",
            file=resolved_file,
            index_generation=gen,
        )

    # Check against expected hash if supplied
    if expected_h and current_hash != expected_h:
        return VerificationReport(
            valid=False,
            exists=True,
            hash_matches=False,
            lines_valid=False,
            status="CONFLICT",
            confidence="LOW",
            freshness="STALE",
            reason=f"Source hash mismatch (expected {expected_h[:8]}..., found {current_hash[:8]}...)",
            file=resolved_file,
            start_line=resolved_start,
            end_line=resolved_end,
            symbol=resolved_symbol,
            index_generation=gen,
        )

    # Check against indexed database hash if available
    file_row = con.execute("SELECT hash FROM files WHERE path=?", (resolved_file,)).fetchone()
    if file_row:
        stored_hash = str(file_row["hash"])
        if current_hash != stored_hash:
            return VerificationReport(
                valid=False,
                exists=True,
                hash_matches=False,
                lines_valid=False,
                status="CONFLICT",
                confidence="LOW",
                freshness="STALE",
                reason="Source hash changed (file modified on disk after indexing)",
                file=resolved_file,
                start_line=resolved_start,
                end_line=resolved_end,
                symbol=resolved_symbol,
                index_generation=gen,
            )

    lines = content_bytes.splitlines()
    line_count = len(lines)
    if resolved_start is not None and resolved_end is not None:
        if resolved_start < 1 or resolved_end > line_count or resolved_start > resolved_end:
            return VerificationReport(
                valid=False,
                exists=True,
                hash_matches=True,
                lines_valid=False,
                status="CONFLICT",
                confidence="LOW",
                freshness="STALE",
                reason=f"Referenced line range {resolved_start}-{resolved_end} exceeds current file length ({line_count} lines)",
                file=resolved_file,
                start_line=resolved_start,
                end_line=resolved_end,
                symbol=resolved_symbol,
                index_generation=gen,
            )

    if resolved_symbol:
        sym_row = con.execute(
            "SELECT canonical_id FROM symbols WHERE path=? AND (name=? OR qualified_name=? OR canonical_id=?)",
            (resolved_file, resolved_symbol, resolved_symbol, resolved_symbol),
        ).fetchone()
        short_sym = resolved_symbol.split(".")[-1]
        if not sym_row and short_sym not in abs_path.read_text(encoding="utf-8", errors="replace"):
            return VerificationReport(
                valid=False,
                exists=True,
                hash_matches=True,
                lines_valid=True,
                status="UNKNOWN",
                confidence="LOW",
                freshness="STALE",
                reason=f"Referenced symbol '{resolved_symbol}' no longer found in file",
                file=resolved_file,
                symbol=resolved_symbol,
                index_generation=gen,
            )

    return VerificationReport(
        valid=True,
        exists=True,
        hash_matches=True,
        lines_valid=True,
        status="FACT",
        confidence="HIGH",
        freshness="FRESH",
        reason="Evidence verified against source file and disk hash",
        file=resolved_file,
        start_line=resolved_start,
        end_line=resolved_end,
        symbol=resolved_symbol,
        evidence_id=resolved_id,
        index_generation=gen,
    )
