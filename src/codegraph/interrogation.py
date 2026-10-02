"""Core deterministic repository interrogation engine for CodeGraph MCP.

Principle:
    "The AI understands the developer. CodeGraph interrogates the repository."
    "The claim comes from the AI; the proof comes from CodeGraph."

Invariant:
    same repository + same index generation + same MCP request = same deterministic result.
"""
from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from codegraph.architecture import get_architecture as arch_get_architecture
from codegraph.errors import ErrorCode, SecurityError
from codegraph.freshness import check_freshness, index_generation
from codegraph.git import (
    changed_files,
    changed_symbols_since,
    current_commit,
)
from codegraph.security import is_sensitive, safe_path


def make_evidence(
    file: str,
    start_line: int,
    end_line: int,
    evidence_type: str,
    canonical_id: str | None = None,
) -> dict[str, Any]:
    """Create a standardized, evidence-backed citation record."""
    return {
        "file": file,
        "start_line": start_line,
        "end_line": end_line,
        "type": evidence_type,
        "canonical_id": canonical_id or "",
    }


def get_index_metadata(con: sqlite3.Connection, repository: Path) -> dict[str, Any]:
    """Return index generation, freshness, and repository commit identity."""
    gen = index_generation(con)
    freshness_rep = check_freshness(repository, con)
    commit = current_commit(repository)

    created_at = ""
    try:
        row = con.execute("SELECT value FROM metadata WHERE key='indexed_at'").fetchone()
        if row:
            created_at = str(row[0])
    except Exception:
        pass

    return {
        "index": {
            "generation": gen,
            "created_at": created_at,
            "freshness": freshness_rep.status.value,
        },
        "repository": {
            "commit": commit,
        },
    }


def check_index_available(con: sqlite3.Connection, repository: Path) -> dict[str, Any] | None:
    """Return an INDEX_NOT_FOUND error envelope if the repository has not been indexed."""
    try:
        count = con.execute("SELECT count(*) FROM files").fetchone()[0]
    except sqlite3.OperationalError:
        count = 0
    if count == 0:
        return {
            "status": "error",
            "error": {
                "code": ErrorCode.INDEX_NOT_FOUND.value,
                "message": "No CodeGraph index exists for this repository.",
                "next_action": {
                    "command": "codegraph init",
                    "reason": "Initialize the repository before querying it.",
                },
            },
        }
    return None


# ---------------------------------------------------------------------------
# 1. resolve_symbol
# ---------------------------------------------------------------------------
def resolve_symbol(
    con: sqlite3.Connection,
    repository: Path,
    name: str,
) -> dict[str, Any]:
    """Determine whether an exact/canonical symbol exists and return its location and identity.

    CodeGraph MUST NOT choose an intended candidate when ambiguous.
    """
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_name = name.strip()
    meta = get_index_metadata(con, repository)
    if not clean_name:
        return {
            "status": "invalid_request",
            "error_code": ErrorCode.EMPTY_SYMBOL_NAME.value,
            "error": {
                "code": ErrorCode.EMPTY_SYMBOL_NAME.value,
                "message": "Symbol name must be non-empty.",
                "next_action": {
                    "command": "codegraph resolve <symbol>",
                    "reason": "Provide a non-empty symbol name to resolve.",
                },
            },
            "query": name,
            **meta,
        }

    # Query matching symbols
    rows = con.execute(
        "SELECT canonical_id, name, qualified_name, kind, path, start_line, end_line "
        "FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=? "
        "ORDER BY canonical_id ASC",
        (clean_name, clean_name, clean_name),
    ).fetchall()

    if not rows:
        return {
            "status": "not_found",
            "query": clean_name,
            "error": {
                "code": ErrorCode.SYMBOL_NOT_FOUND.value,
                "message": f"No matching symbol was found for '{clean_name}'.",
                "next_action": {
                    "command": f"codegraph search {clean_name}",
                    "reason": "Search with a broader query term.",
                },
            },
            **meta,
            "matches": [],
            "candidates": [],
        }

    # Check for exact canonical_id match
    exact_canonical = [r for r in rows if r["canonical_id"] == clean_name]
    if len(exact_canonical) == 1:
        match = exact_canonical[0]
        ev = [
            make_evidence(
                file=match["path"],
                start_line=match["start_line"],
                end_line=match["end_line"],
                evidence_type="definition",
                canonical_id=match["canonical_id"],
            )
        ]
        return {
            "status": "ok",
            **meta,
            "symbol": {
                "name": match["name"],
                "canonical_id": match["canonical_id"],
                "kind": match["kind"],
            },
            "location": {
                "file": match["path"],
                "start_line": match["start_line"],
                "end_line": match["end_line"],
            },
            "evidence": ev,
        }

    # If only one match overall
    if len(rows) == 1:
        match = rows[0]
        ev = [
            make_evidence(
                file=match["path"],
                start_line=match["start_line"],
                end_line=match["end_line"],
                evidence_type="definition",
                canonical_id=match["canonical_id"],
            )
        ]
        return {
            "status": "ok",
            **meta,
            "symbol": {
                "name": match["name"],
                "canonical_id": match["canonical_id"],
                "kind": match["kind"],
            },
            "location": {
                "file": match["path"],
                "start_line": match["start_line"],
                "end_line": match["end_line"],
            },
            "evidence": ev,
        }

    # Multiple candidates exist -> ambiguous! CodeGraph MUST NOT choose!
    matches = [
        {
            "canonical_id": r["canonical_id"],
            "symbol": r["name"],
            "name": r["name"],
            "file": r["path"],
            "kind": r["kind"],
            "line": r["start_line"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
        }
        for r in rows
    ]
    matches.sort(key=lambda m: str(m["canonical_id"]))
    return {
        "status": "ambiguous",
        "query": clean_name,
        "error": {
            "code": ErrorCode.SYMBOL_AMBIGUOUS.value,
            "message": f"Multiple symbols match '{clean_name}'. Provide a qualified name or canonical ID.",
            "next_action": {
                "command": "codegraph resolve <canonical_id>",
                "reason": "Select an explicit canonical ID from candidates.",
            },
        },
        **meta,
        "matches": matches,
        "candidates": matches,
    }


# ---------------------------------------------------------------------------
# 2. search_symbols
# ---------------------------------------------------------------------------
def search_symbols(
    con: sqlite3.Connection,
    repository: Path,
    query: str,
    top_k: int = 20,
) -> dict[str, Any]:
    """Search indexed repository symbols using explicit search terms with deterministic ranking."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_query = query.strip()
    meta = get_index_metadata(con, repository)
    if not clean_query:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Search query must be non-empty.",
                "next_action": {
                    "command": "codegraph search <query>",
                    "reason": "Provide a non-empty query term.",
                },
            },
            "query": query,
            **meta,
            "count": 0,
            "symbols": [],
            "evidence": [],
        }

    bounded_k = max(1, min(top_k, 100))

    # Search symbols joined with files to exclude GENERATED files
    rows = con.execute(
        "SELECT s.canonical_id, s.name, s.qualified_name, s.kind, s.path, s.start_line, s.end_line, f.category "
        "FROM symbols s "
        "JOIN files f ON f.path = s.path "
        "WHERE (f.category != 'GENERATED' OR f.category IS NULL) "
        "AND (s.name LIKE ? OR s.qualified_name LIKE ? OR s.canonical_id LIKE ?) "
        "ORDER BY s.canonical_id ASC",
        (f"%{clean_query}%", f"%{clean_query}%", f"%{clean_query}%"),
    ).fetchall()

    # Deterministic scoring:
    # 1.0 = exact match on name or qualified_name
    # 0.85 = prefix match on name
    # 0.70 = substring match on name
    # 0.60 = match elsewhere
    scored_results: list[dict[str, Any]] = []
    q_lower = clean_query.lower()

    for r in rows:
        name = r["name"]
        qname = r["qualified_name"] or ""
        cid = r["canonical_id"] or ""
        name_lower = name.lower()

        if name_lower == q_lower or qname.lower() == q_lower:
            score = 1.00
        elif name_lower.startswith(q_lower):
            score = 0.85
        elif q_lower in name_lower:
            score = 0.70
        else:
            score = 0.60

        scored_results.append(
            {
                "name": name,
                "canonical_id": cid,
                "kind": r["kind"],
                "file": r["path"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "score": round(score, 2),
                "evidence": make_evidence(
                    file=r["path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    evidence_type="symbol_match",
                    canonical_id=cid,
                ),
            }
        )

    # Sort deterministically: highest score first, ties broken by canonical_id ASC
    scored_results.sort(key=lambda s: (-float(s["score"]), str(s["canonical_id"])))
    selected = scored_results[:bounded_k]

    evidence_list = [s["evidence"] for s in selected]

    return {
        "status": "ok",
        "query": clean_query,
        **meta,
        "count": len(selected),
        "symbols": selected,
        "evidence": evidence_list,
    }


# ---------------------------------------------------------------------------
# 3. get_symbol
# ---------------------------------------------------------------------------
def get_symbol(
    con: sqlite3.Connection,
    repository: Path,
    canonical_id: str,
) -> dict[str, Any]:
    """Return complete structured information for a known canonical symbol."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_id = canonical_id.strip()
    meta = get_index_metadata(con, repository)
    if not clean_id:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Canonical ID or symbol name must be non-empty.",
                "next_action": {
                    "command": "codegraph get-symbol <symbol>",
                    "reason": "Provide a non-empty canonical ID or symbol name.",
                },
            },
            "canonical_id": canonical_id,
            **meta,
        }

    row = con.execute(
        "SELECT id, canonical_id, qualified_name, name, kind, path, start_line, end_line, "
        "parent_symbol_id, module, scope, language, signature, content_hash, visibility, "
        "return_type, parameter_count, documentation, decorators "
        "FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=? "
        "ORDER BY canonical_id=? DESC "
        "LIMIT 1",
        (clean_id, clean_id, clean_id, clean_id),
    ).fetchone()

    if not row:
        return {
            "status": "not_found",
            "canonical_id": clean_id,
            "error": {
                "code": ErrorCode.SYMBOL_NOT_FOUND.value,
                "message": f"No symbol found with canonical ID or name: '{clean_id}'",
                "next_action": {
                    "command": f"codegraph search {clean_id}",
                    "reason": "Search for symbol candidates.",
                },
            },
            **meta,
        }

    # Query parent symbol
    parent_info: str | None = None
    if row["parent_symbol_id"]:
        p_row = con.execute(
            "SELECT canonical_id, qualified_name FROM symbols WHERE id=?",
            (row["parent_symbol_id"],),
        ).fetchone()
        if p_row:
            parent_info = p_row["canonical_id"] or p_row["qualified_name"]

    # Query children
    children_rows = con.execute(
        "SELECT canonical_id, name, kind, start_line, end_line FROM symbols "
        "WHERE parent_symbol_id=? ORDER BY start_line ASC, canonical_id ASC",
        (row["id"],),
    ).fetchall()
    children = [
        {
            "canonical_id": c["canonical_id"],
            "name": c["name"],
            "kind": c["kind"],
            "start_line": c["start_line"],
            "end_line": c["end_line"],
        }
        for c in children_rows
    ]

    # Parse decorators
    decors_raw = row["decorators"] or ""
    decorators: list[str] = []
    if decors_raw:
        decorators = [d.strip() for d in decors_raw.split(",") if d.strip()]

    # Query relationships from graph_edges
    cid = row["canonical_id"]
    rel_rows = con.execute(
        "SELECT target, relationship, confidence, file, start_line, end_line "
        "FROM graph_edges WHERE source=? ORDER BY relationship ASC, target ASC",
        (cid,),
    ).fetchall()
    relationships = [
        {
            "target": r["target"],
            "relationship": r["relationship"],
            "confidence": r["confidence"],
            "file": r["file"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
        }
        for r in rel_rows
    ]

    ev = [
        make_evidence(
            file=row["path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            evidence_type="definition",
            canonical_id=row["canonical_id"],
        )
    ]

    return {
        "status": "ok",
        **meta,
        "evidence": ev,
        "symbol": {
            "canonical_id": row["canonical_id"],
            "name": row["name"],
            "qualified_name": row["qualified_name"],
            "kind": row["kind"],
            "file": row["path"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "module": row["module"],
            "scope": row["scope"],
            "language": row["language"],
            "signature": row["signature"] or "",
            "parent": parent_info,
            "children": children,
            "decorators": decorators,
            "docstring": row["documentation"] or "",
            "visibility": row["visibility"] or "public",
            "relationships": relationships,
        },
    }


# ---------------------------------------------------------------------------
# 4. get_file
# ---------------------------------------------------------------------------
def get_file(
    con: sqlite3.Connection,
    repository: Path,
    path: str,
    include_content: bool = False,
) -> dict[str, Any]:
    """Return the structural AST representation of an indexed file."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    try:
        resolved = safe_path(repository, path)
        relative = resolved.relative_to(repository).as_posix()
    except SecurityError:
        return {
            "status": "error",
            "error_code": ErrorCode.PATH_OUTSIDE_REPOSITORY.value,
            "error": {
                "code": ErrorCode.PATH_OUTSIDE_REPOSITORY.value,
                "message": f"Path traversal blocked: '{path}' resides outside repository boundary.",
                "next_action": {
                    "command": "codegraph status",
                    "reason": "Ensure all queried paths reside within the repository root.",
                },
            },
            "path": path,
            **meta,
        }
    except Exception:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_PATH.value,
            "error": {
                "code": ErrorCode.INVALID_PATH.value,
                "message": f"Invalid path: '{path}'",
                "next_action": {
                    "command": "codegraph status",
                    "reason": "Check repository files and paths.",
                },
            },
            "path": path,
            **meta,
        }

    if is_sensitive(Path(relative)):
        return {
            "status": "invalid_request",
            "error_code": ErrorCode.SENSITIVE_FILE_ACCESS_DENIED.value,
            "error": {
                "code": ErrorCode.SENSITIVE_FILE_ACCESS_DENIED.value,
                "message": f"Access to sensitive file '{relative}' is blocked.",
                "next_action": {
                    "command": "codegraph privacy",
                    "reason": "Review protected file boundaries.",
                },
            },
            "path": relative,
            **meta,
        }

    file_row = con.execute(
        "SELECT hash, language, category FROM files WHERE path=?",
        (relative,),
    ).fetchone()

    if not file_row and not resolved.is_file():
        return {
            "status": "not_found",
            "error_code": ErrorCode.INVALID_PATH.value,
            "error": {
                "code": ErrorCode.INVALID_PATH.value,
                "message": f"File does not exist: '{relative}'",
                "next_action": {
                    "command": "codegraph status",
                    "reason": "Check repository files and paths.",
                },
            },
            "path": relative,
            **meta,
        }

    # Query symbols in file
    symbols_rows = con.execute(
        "SELECT canonical_id, name, qualified_name, kind, start_line, end_line "
        "FROM symbols WHERE path=? ORDER BY start_line ASC, canonical_id ASC",
        (relative,),
    ).fetchall()

    symbols = [
        {
            "canonical_id": s["canonical_id"],
            "name": s["name"],
            "qualified_name": s["qualified_name"],
            "kind": s["kind"],
            "start_line": s["start_line"],
            "end_line": s["end_line"],
        }
        for s in symbols_rows
    ]
    classes = [s for s in symbols if s["kind"] in ("class", "interface")]
    functions = [s for s in symbols if s["kind"] in ("function", "method")]

    # Query imports
    import_rows = con.execute(
        "SELECT module, name, alias, line, imported_module, imported_name, resolved_path "
        "FROM imports WHERE source_path=? ORDER BY line ASC, module ASC",
        (relative,),
    ).fetchall()
    imports = [
        {
            "module": i["module"],
            "name": i["name"],
            "alias": i["alias"],
            "line": i["line"],
            "imported_module": i["imported_module"],
            "imported_name": i["imported_name"],
            "resolved_path": i["resolved_path"],
        }
        for i in import_rows
    ]

    # Query routes in file
    route_rows = con.execute(
        "SELECT endpoint_id, framework, http_method, route_path, handler_name, line "
        "FROM framework_routes WHERE file_path=? ORDER BY line ASC, route_path ASC",
        (relative,),
    ).fetchall()
    routes = [
        {
            "endpoint_id": r["endpoint_id"],
            "framework": r["framework"],
            "method": r["http_method"],
            "path": r["route_path"],
            "handler": r["handler_name"],
            "line": r["line"],
        }
        for r in route_rows
    ]

    file_size = resolved.stat().st_size if resolved.exists() else 0
    file_hash = file_row["hash"] if file_row else ""
    language = file_row["language"] if file_row else "unknown"

    content: str | None = None
    if include_content and resolved.exists():
        content = resolved.read_text(encoding="utf-8", errors="replace")
        if len(content) > 50_000:
            content = content[:50_000] + "\n...[truncated at 50,000 chars]"

    ev = [
        make_evidence(
            file=relative,
            start_line=1,
            end_line=len(symbols_rows) or 1,
            evidence_type="file_ast",
            canonical_id=relative,
        )
    ]

    result: dict[str, Any] = {
        "status": "ok",
        "file": relative,
        **meta,
        "hash": file_hash,
        "language": language,
        "size_bytes": file_size,
        "classes": classes,
        "functions": functions,
        "imports": imports,
        "routes": routes,
        "evidence": ev,
    }
    if include_content:
        result["content"] = content
    return result


# ---------------------------------------------------------------------------
# 5. get_references
# ---------------------------------------------------------------------------
def get_references(
    con: sqlite3.Connection,
    repository: Path,
    canonical_id: str,
) -> dict[str, Any]:
    """Return all known references and call sites to a canonical symbol with evidence."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_id = canonical_id.strip()
    meta = get_index_metadata(con, repository)
    if not clean_id:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Canonical ID must be non-empty.",
                "next_action": {
                    "command": "codegraph resolve <symbol>",
                    "reason": "Resolve canonical ID before querying references.",
                },
            },
            "canonical_id": canonical_id,
            **meta,
            "count": 0,
            "references": [],
        }

    short_name = clean_id.split(":")[-1].split(".")[-1]

    # 1. Search 'references' table
    ref_rows = con.execute(
        "SELECT source_symbol_id, relationship, confidence, path, start_line, end_line, evidence "
        "FROM 'references' "
        "WHERE target_symbol_id=? OR target_symbol_id LIKE ? "
        "ORDER BY path ASC, start_line ASC",
        (clean_id, f"%.{clean_id}"),
    ).fetchall()

    # 2. Search 'calls' table
    call_rows = con.execute(
        "SELECT source_path, callee, line, confidence, source_symbol_id "
        "FROM calls "
        "WHERE resolved_symbol_id=? OR qualified_callee=? OR callee=? "
        "ORDER BY source_path ASC, line ASC",
        (clean_id, clean_id, short_name),
    ).fetchall()

    references: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for r in ref_rows:
        key = (r["path"], r["start_line"], r["source_symbol_id"] or "")
        if key not in seen:
            seen.add(key)
            references.append(
                {
                    "canonical_id": r["source_symbol_id"] or "",
                    "file": r["path"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"],
                    "reference_type": r["relationship"].lower(),
                    "confidence": r["confidence"],
                    "evidence": make_evidence(
                        file=r["path"],
                        start_line=r["start_line"],
                        end_line=r["end_line"],
                        evidence_type="reference",
                        canonical_id=r["source_symbol_id"],
                    ),
                }
            )

    for c in call_rows:
        key = (c["source_path"], c["line"], c["source_symbol_id"] or "")
        if key not in seen:
            seen.add(key)
            references.append(
                {
                    "canonical_id": c["source_symbol_id"] or "",
                    "file": c["source_path"],
                    "start_line": c["line"],
                    "end_line": c["line"],
                    "reference_type": "call",
                    "confidence": c["confidence"],
                    "evidence": make_evidence(
                        file=c["source_path"],
                        start_line=c["line"],
                        end_line=c["line"],
                        evidence_type="call",
                        canonical_id=c["source_symbol_id"],
                    ),
                }
            )

    references.sort(key=lambda r: (str(r["file"]), int(r["start_line"]), str(r["canonical_id"])))

    return {
        "status": "ok",
        "canonical_id": clean_id,
        **meta,
        "count": len(references),
        "references": references,
    }


# ---------------------------------------------------------------------------
# 6. get_callers
# ---------------------------------------------------------------------------
def get_callers(
    con: sqlite3.Connection,
    repository: Path,
    canonical_id: str,
) -> dict[str, Any]:
    """Return functions and methods that call the specified canonical symbol."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_id = canonical_id.strip()
    meta = get_index_metadata(con, repository)
    if not clean_id:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Canonical ID must be non-empty.",
                "next_action": {
                    "command": "codegraph resolve <symbol>",
                    "reason": "Resolve canonical ID before querying callers.",
                },
            },
            "canonical_id": canonical_id,
            **meta,
            "count": 0,
            "callers": [],
        }

    short_name = clean_id.split(":")[-1].split(".")[-1]

    # Query calls joined with symbols to get authoritative caller canonical IDs
    rows = con.execute(
        "SELECT c.source_path, c.callee, c.qualified_callee, c.line, c.confidence, "
        "c.source_symbol_id, s.canonical_id AS caller_canon, s.name AS caller_name "
        "FROM calls c "
        "LEFT JOIN symbols s ON s.canonical_id = c.source_symbol_id "
        "WHERE c.resolved_symbol_id=? OR c.qualified_callee=? OR c.callee=? "
        "ORDER BY c.source_path ASC, c.line ASC",
        (clean_id, clean_id, short_name),
    ).fetchall()

    callers: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for r in rows:
        caller_id = r["caller_canon"] or r["source_symbol_id"] or r["caller_name"] or r["source_path"]
        key = (r["source_path"], r["line"], caller_id)
        if key not in seen:
            seen.add(key)
            callers.append(
                {
                    "caller": caller_id,
                    "canonical_id": r["caller_canon"] or r["source_symbol_id"] or "",
                    "file": r["source_path"],
                    "line": r["line"],
                    "confidence": r["confidence"],
                    "call_site": {
                        "file": r["source_path"],
                        "line": r["line"],
                        "callee": r["callee"],
                    },
                    "evidence": make_evidence(
                        file=r["source_path"],
                        start_line=r["line"],
                        end_line=r["line"],
                        evidence_type="call",
                        canonical_id=caller_id,
                    ),
                }
            )

    callers.sort(key=lambda c: (str(c["file"]), int(c["line"]), str(c["caller"])))

    return {
        "status": "ok",
        "canonical_id": clean_id,
        **meta,
        "count": len(callers),
        "callers": callers,
    }


# ---------------------------------------------------------------------------
# 7. get_callees
# ---------------------------------------------------------------------------
def get_callees(
    con: sqlite3.Connection,
    repository: Path,
    canonical_id: str,
) -> dict[str, Any]:
    """Return functions and methods called by the specified canonical symbol."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_id = canonical_id.strip()
    meta = get_index_metadata(con, repository)
    if not clean_id:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Canonical ID must be non-empty.",
                "next_action": {
                    "command": "codegraph resolve <symbol>",
                    "reason": "Resolve canonical ID before querying callees.",
                },
            },
            "canonical_id": canonical_id,
            **meta,
            "count": 0,
            "callees": [],
        }

    # Find the symbol record to get line bounds
    sym_row = con.execute(
        "SELECT id, canonical_id, path, start_line, end_line FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
        (clean_id, clean_id, clean_id),
    ).fetchone()

    query_id = sym_row["canonical_id"] if sym_row else clean_id
    query_path = sym_row["path"] if sym_row else None

    if sym_row and query_path:
        rows = con.execute(
            "SELECT c.source_path, c.callee, c.qualified_callee, c.line, c.confidence, "
            "c.source_symbol_id, c.resolved_symbol_id, "
            "s.canonical_id AS callee_canon, s.path AS callee_path "
            "FROM calls c "
            "LEFT JOIN symbols s ON (s.canonical_id = c.resolved_symbol_id OR s.qualified_name = c.qualified_callee) "
            "WHERE (c.source_symbol_id=? OR (c.source_path=? AND c.line >= ? AND c.line <= ?)) "
            "ORDER BY c.line ASC",
            (query_id, query_path, sym_row["start_line"], sym_row["end_line"]),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT c.source_path, c.callee, c.qualified_callee, c.line, c.confidence, "
            "c.source_symbol_id, c.resolved_symbol_id, "
            "s.canonical_id AS callee_canon, s.path AS callee_path "
            "FROM calls c "
            "LEFT JOIN symbols s ON (s.canonical_id = c.resolved_symbol_id OR s.qualified_name = c.qualified_callee) "
            "WHERE c.source_symbol_id=? "
            "ORDER BY c.line ASC",
            (query_id,),
        ).fetchall()

    callees: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for r in rows:
        callee_name = r["callee"]
        target_cid = r["callee_canon"] or r["resolved_symbol_id"]
        if target_cid or r["callee_path"]:
            call_type = "resolved_call"
        elif "." in str(r["qualified_callee"] or ""):
            call_type = "external_call"
        else:
            call_type = "unresolved_call"

        key = (r["source_path"], r["line"], callee_name)
        if key not in seen:
            seen.add(key)
            callees.append(
                {
                    "callee": callee_name,
                    "canonical_id": target_cid,
                    "call_type": call_type,
                    "file": r["source_path"],
                    "line": r["line"],
                    "confidence": r["confidence"],
                    "evidence": make_evidence(
                        file=r["source_path"],
                        start_line=r["line"],
                        end_line=r["line"],
                        evidence_type="call",
                        canonical_id=target_cid or query_id,
                    ),
                }
            )

    callees.sort(key=lambda c: (str(c["call_type"]), str(c["canonical_id"] or ""), int(c["line"])))

    return {
        "status": "ok",
        "canonical_id": clean_id,
        **meta,
        "count": len(callees),
        "callees": callees,
        "resolved_calls": [c for c in callees if c["call_type"] == "resolved_call"],
        "unresolved_calls": [c for c in callees if c["call_type"] == "unresolved_call"],
        "external_calls": [c for c in callees if c["call_type"] == "external_call"],
    }


# ---------------------------------------------------------------------------
# 8. trace_path
# ---------------------------------------------------------------------------
def trace_path(
    con: sqlite3.Connection,
    repository: Path,
    from_symbol: str,
    to_symbol: str,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Find a deterministic relationship path between two known symbols."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    clean_from = from_symbol.strip()
    clean_to = to_symbol.strip()
    meta = get_index_metadata(con, repository)

    if max_depth < 1 or max_depth > 10:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_DEPTH.value,
            "error": {
                "code": ErrorCode.INVALID_DEPTH.value,
                "message": f"Invalid graph traversal depth {max_depth}; allowed range is 1..5.",
                "next_action": {
                    "command": "codegraph trace --depth 2 <symbol>",
                    "reason": "Specify a traversal depth between 1 and 5.",
                },
            },
            "from": from_symbol,
            "to": to_symbol,
            **meta,
            "path": [],
        }

    bounded_depth = max(1, min(max_depth, 5))

    if not clean_from or not clean_to:
        return {
            "status": "error",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "Both source_symbol and target_symbol must be non-empty.",
                "next_action": {
                    "command": "codegraph trace <source> <target>",
                    "reason": "Provide valid source and target symbol names.",
                },
            },
            "from": from_symbol,
            "to": to_symbol,
            **meta,
            "path": [],
        }

    # Resolve from and to targets
    from_row = con.execute(
        "SELECT canonical_id, qualified_name, name FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
        (clean_from, clean_from, clean_from),
    ).fetchone()

    to_row = con.execute(
        "SELECT canonical_id, qualified_name, name FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
        (clean_to, clean_to, clean_to),
    ).fetchone()

    if not from_row or not to_row:
        missing = clean_from if not from_row else clean_to
        return {
            "status": "not_found",
            "error": {
                "code": ErrorCode.SYMBOL_NOT_FOUND.value,
                "message": f"Symbol not found: '{missing}'",
                "next_action": {
                    "command": f"codegraph search {missing}",
                    "reason": "Verify symbol exists in the repository.",
                },
            },
            "from": clean_from,
            "to": clean_to,
            **meta,
            "path": [],
        }

    start_canon = from_row["canonical_id"]
    target_canon = to_row["canonical_id"]
    target_names = {to_row["canonical_id"], to_row["qualified_name"], to_row["name"]}

    if start_canon == target_canon:
        return {
            "status": "ok",
            "from": clean_from,
            "to": clean_to,
            **meta,
            "path_length": 0,
            "path": [],
        }

    # Deterministic BFS search
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(start_canon, [])])
    visited: set[str] = {start_canon}

    while queue:
        curr_sym, path = queue.popleft()
        if len(path) >= bounded_depth:
            continue

        curr_short = curr_sym.split(":")[-1].split(".")[-1]

        # Query outgoing edges from calls
        edges = con.execute(
            "SELECT c.callee, c.qualified_callee, c.resolved_symbol_id, c.source_path, c.line "
            "FROM calls c "
            "WHERE c.source_symbol_id=? OR c.callee=? "
            "ORDER BY c.source_path ASC, c.line ASC",
            (curr_sym, curr_short),
        ).fetchall()

        # Query outgoing edges from graph_edges
        graph_rows = con.execute(
            "SELECT target, relationship, file, start_line, end_line "
            "FROM graph_edges "
            "WHERE source=? AND relationship IN ('CALLS', 'IMPORTS', 'HANDLED_BY') "
            "ORDER BY relationship ASC, target ASC",
            (curr_sym,),
        ).fetchall()

        all_steps: list[tuple[str, str, str, int, int]] = []
        for e in edges:
            dest = e["resolved_symbol_id"] or e["qualified_callee"] or e["callee"]
            all_steps.append((dest, "CALLS", e["source_path"], e["line"], e["line"]))
        for g in graph_rows:
            all_steps.append((g["target"], g["relationship"], g["file"], g["start_line"], g["end_line"]))

        # Sort steps deterministically
        all_steps.sort(key=lambda s: (s[0], s[1], s[2], s[3]))

        for dest_sym, rel, s_file, s_line, e_line in all_steps:
            dest_row = con.execute(
                "SELECT canonical_id FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
                (dest_sym, dest_sym, dest_sym),
            ).fetchone()
            dest_canon = dest_row["canonical_id"] if dest_row else dest_sym

            new_path = list(path) + [
                {
                    "source": curr_sym,
                    "target": dest_canon,
                    "relationship": rel,
                    "evidence": make_evidence(
                        file=s_file,
                        start_line=s_line,
                        end_line=e_line,
                        evidence_type="path_edge",
                        canonical_id=dest_canon,
                    ),
                }
            ]

            if dest_canon == target_canon or dest_sym in target_names:
                return {
                    "status": "ok",
                    "from": clean_from,
                    "to": clean_to,
                    **meta,
                    "path_length": len(new_path),
                    "path": new_path,
                }

            if dest_canon and dest_canon not in visited:
                visited.add(dest_canon)
                queue.append((dest_canon, new_path))

    return {
        "status": "not_found",
        "from": clean_from,
        "to": clean_to,
        "reachable": False,
        "message": f"No relationship path found between '{clean_from}' and '{clean_to}' within depth {bounded_depth}.",
        **meta,
        "path": [],
    }


# ---------------------------------------------------------------------------
# 9. get_imports
# ---------------------------------------------------------------------------
def get_imports(
    con: sqlite3.Connection,
    repository: Path,
    file: str | None = None,
    canonical_id: str | None = None,
) -> dict[str, Any]:
    """Return imports and import relationships for a file or canonical symbol."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    target_path = file

    if canonical_id and not target_path:
        sym_row = con.execute(
            "SELECT path FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
            (canonical_id, canonical_id, canonical_id),
        ).fetchone()
        if sym_row:
            target_path = sym_row["path"]

    if not target_path:
        return {
            "status": "invalid_request",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "At least one of 'file' or 'canonical_id' must be specified.",
                "next_action": {
                    "command": "codegraph get-file <path>",
                    "reason": "Specify a valid file path or canonical ID.",
                },
            },
            **meta,
            "count": 0,
            "imports": [],
        }

    rows = con.execute(
        "SELECT source_path, module, name, alias, imported_module, imported_name, resolved_path, line "
        "FROM imports WHERE source_path=? ORDER BY line ASC, module ASC",
        (target_path,),
    ).fetchall()

    imports = [
        {
            "source": r["source_path"],
            "target": r["imported_module"] or r["module"],
            "import_type": "symbol" if r["name"] else "module",
            "file": r["source_path"],
            "line": r["line"],
            "resolved_target": r["resolved_path"],
            "evidence": make_evidence(
                file=r["source_path"],
                start_line=r["line"],
                end_line=r["line"],
                evidence_type="import",
                canonical_id=r["source_path"],
            ),
        }
        for r in rows
    ]

    imports.sort(key=lambda i: (str(i["file"]), int(i["line"]), str(i["target"])))

    return {
        "status": "ok",
        "file": target_path,
        "canonical_id": canonical_id,
        **meta,
        "count": len(imports),
        "imports": imports,
    }


# ---------------------------------------------------------------------------
# 10. get_dependents
# ---------------------------------------------------------------------------
def get_dependents(
    con: sqlite3.Connection,
    repository: Path,
    canonical_id: str | None = None,
    file: str | None = None,
) -> dict[str, Any]:
    """Reverse dependency query: return files and symbols that depend on the target."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    target = canonical_id or file
    if not target:
        return {
            "status": "invalid_request",
            "error_code": ErrorCode.INVALID_ARGUMENT.value,
            "error": {
                "code": ErrorCode.INVALID_ARGUMENT.value,
                "message": "At least one of 'canonical_id' or 'file' must be specified.",
                "next_action": {
                    "command": "codegraph resolve <symbol>",
                    "reason": "Specify a valid canonical ID or file path.",
                },
            },
            **meta,
            "count": 0,
            "dependents": [],
        }

    clean_target = target.strip()
    short_name = clean_target.split(":")[-1].split(".")[-1]
    dependents: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    # 1. Reverse imports
    imp_rows = con.execute(
        "SELECT source_path, line, module FROM imports "
        "WHERE module=? OR imported_module=? OR resolved_path=? OR source_path=? "
        "ORDER BY source_path ASC, line ASC",
        (clean_target, clean_target, clean_target, clean_target),
    ).fetchall()
    for r in imp_rows:
        key = ("imports", r["source_path"], r["line"])
        if key not in seen:
            seen.add(key)
            dependents.append(
                {
                    "dependent": r["source_path"],
                    "dependent_type": "file",
                    "relationship": "imports",
                    "file": r["source_path"],
                    "line": r["line"],
                    "evidence": make_evidence(
                        file=r["source_path"],
                        start_line=r["line"],
                        end_line=r["line"],
                        evidence_type="import",
                        canonical_id=r["source_path"],
                    ),
                }
            )

    # 2. Reverse calls
    call_rows = con.execute(
        "SELECT source_symbol_id, source_path, line FROM calls "
        "WHERE resolved_symbol_id=? OR qualified_callee=? OR callee=? "
        "ORDER BY source_path ASC, line ASC",
        (clean_target, clean_target, short_name),
    ).fetchall()
    for r in call_rows:
        dep_sym = r["source_symbol_id"] or r["source_path"]
        key = ("calls", r["source_path"], r["line"])
        if key not in seen:
            seen.add(key)
            dependents.append(
                {
                    "dependent": dep_sym,
                    "dependent_type": "symbol",
                    "relationship": "calls",
                    "file": r["source_path"],
                    "line": r["line"],
                    "evidence": make_evidence(
                        file=r["source_path"],
                        start_line=r["line"],
                        end_line=r["line"],
                        evidence_type="call",
                        canonical_id=dep_sym,
                    ),
                }
            )

    # 3. Inheritance
    inh_rows = con.execute(
        "SELECT source_symbol, source_file, line, source_canonical_id FROM inheritance "
        "WHERE base_name=? OR base_name LIKE ? "
        "ORDER BY source_file ASC, line ASC",
        (clean_target, f"%.{short_name}"),
    ).fetchall()
    for r in inh_rows:
        key = ("inherits", r["source_file"], r["line"])
        if key not in seen:
            seen.add(key)
            dependents.append(
                {
                    "dependent": r["source_canonical_id"] or r["source_symbol"],
                    "dependent_type": "symbol",
                    "relationship": "inherits",
                    "file": r["source_file"],
                    "line": r["line"],
                    "evidence": make_evidence(
                        file=r["source_file"],
                        start_line=r["line"],
                        end_line=r["line"],
                        evidence_type="inheritance",
                        canonical_id=r["source_canonical_id"],
                    ),
                }
            )

    dependents.sort(key=lambda d: (str(d["relationship"]), str(d["file"]), int(d["line"])))

    return {
        "status": "ok",
        "target": clean_target,
        **meta,
        "count": len(dependents),
        "dependents": dependents,
    }


# ---------------------------------------------------------------------------
# 11. list_routes
# ---------------------------------------------------------------------------
def list_routes(
    con: sqlite3.Connection,
    repository: Path,
    framework: str | None = None,
    method: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Expose application routes discovered from the repository."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    query = (
        "SELECT endpoint_id, framework, http_method, route_path, handler_name, "
        "handler_canonical_id, file_path, line, evidence, confidence "
        "FROM framework_routes WHERE 1=1 "
    )
    params: list[str] = []
    if framework:
        query += "AND framework=? "
        params.append(framework.lower())
    if method:
        query += "AND UPPER(http_method)=? "
        params.append(method.upper())
    if path:
        query += "AND route_path LIKE ? "
        params.append(f"%{path}%")

    query += "ORDER BY route_path ASC, http_method ASC"
    try:
        rows = con.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        rows = []

    routes = [
        {
            "method": r["http_method"],
            "path": r["route_path"],
            "handler": r["handler_canonical_id"] or r["handler_name"],
            "file": r["file_path"],
            "start_line": r["line"],
            "end_line": r["line"],
            "framework": r["framework"],
            "evidence": make_evidence(
                file=r["file_path"],
                start_line=r["line"],
                end_line=r["line"],
                evidence_type="route",
                canonical_id=r["handler_canonical_id"],
            ),
        }
        for r in rows
    ]

    return {
        "status": "ok",
        **meta,
        "count": len(routes),
        "routes": routes,
    }


# ---------------------------------------------------------------------------
# 12. get_architecture
# ---------------------------------------------------------------------------
def get_architecture(
    con: sqlite3.Connection,
    repository: Path,
) -> dict[str, Any]:
    """Return structural overview of repository architecture."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    arch = arch_get_architecture(con, repository)

    route_summary = arch.get("route_summary")
    routes = route_summary.get("routes", []) if isinstance(route_summary, dict) else []
    dep_summary = arch.get("dependency_summary")
    major_deps = dep_summary.get("top_dependencies", []) if isinstance(dep_summary, dict) else []
    test_summary = arch.get("test_summary")
    test_frameworks = test_summary.get("frameworks", []) if isinstance(test_summary, dict) else []
    model_summary = arch.get("data_model_summary")
    data_models = model_summary.get("models", []) if isinstance(model_summary, dict) else []

    return {
        "status": "ok",
        **meta,
        "repository": str(repository.resolve()),
        "languages": arch.get("languages", ["Python"]),
        "directories": arch.get("directories", []),
        "modules": arch.get("top_level_modules", []),
        "entrypoints": arch.get("entrypoints", []),
        "routes": routes,
        "major_dependencies": major_deps,
        "test_frameworks": test_frameworks,
        "data_models": data_models,
    }


# ---------------------------------------------------------------------------
# 13. get_git_impact
# ---------------------------------------------------------------------------
def get_git_impact(
    con: sqlite3.Connection,
    repository: Path,
    base: str = "HEAD~1",
    head: str = "HEAD",
) -> dict[str, Any]:
    """Determine code affected by Git changes between base and head."""
    unindexed = check_index_available(con, repository)
    if unindexed:
        return unindexed

    meta = get_index_metadata(con, repository)
    diffs = changed_files(repository, since=base, until=head)
    changed_paths = [d.path for d in diffs]

    changed_symbols: list[str] = []
    added_symbols: list[str] = []
    removed_symbols: list[str] = []
    modified_symbols: list[str] = []

    affected_callers: list[dict[str, Any]] = []
    affected_callees: list[dict[str, Any]] = []
    affected_dependents: list[dict[str, Any]] = []
    affected_routes: list[dict[str, Any]] = []

    for d in diffs:
        if d.status == "A":
            s_rows = con.execute("SELECT canonical_id, name FROM symbols WHERE path=?", (d.path,)).fetchall()
            for s in s_rows:
                added_symbols.append(s["canonical_id"] or s["name"])
        elif d.status == "D":
            removed_symbols.append(d.path)
        else:
            s_rows = con.execute("SELECT canonical_id, name FROM symbols WHERE path=?", (d.path,)).fetchall()
            sym_names = {r["name"] for r in s_rows}
            matched = changed_symbols_since(repository, base, sym_names)
            for m in matched:
                modified_symbols.append(m)
                changed_symbols.append(m)

    # Compute callers and callees of modified symbols
    for sym in modified_symbols:
        callers_res = get_callers(con, repository, sym)
        for c in callers_res.get("callers", []):
            affected_callers.append(c)

        callees_res = get_callees(con, repository, sym)
        for c in callees_res.get("callees", []):
            affected_callees.append(c)

        dep_res = get_dependents(con, repository, canonical_id=sym)
        for d in dep_res.get("dependents", []):
            affected_dependents.append(d)

    # Affected routes
    for p in changed_paths:
        r_rows = con.execute("SELECT * FROM framework_routes WHERE file_path=?", (p,)).fetchall()
        for r in r_rows:
            affected_routes.append(
                {
                    "method": r["http_method"],
                    "path": r["route_path"],
                    "handler": r["handler_canonical_id"],
                    "file": r["file_path"],
                }
            )

    return {
        "status": "ok",
        "base": base,
        "head": head,
        **meta,
        "summary": {
            "changed_files_count": len(diffs),
            "affected_symbol_count": len(set(changed_symbols + added_symbols)),
            "affected_route_count": len(affected_routes),
            "affected_dependent_count": len(affected_dependents),
        },
        "changed_files": [d.as_dict() for d in diffs],
        "changed_symbols": sorted(list(set(changed_symbols + added_symbols))),
        "added_symbols": sorted(added_symbols),
        "removed_symbols": sorted(removed_symbols),
        "modified_symbols": sorted(modified_symbols),
        "affected_callers": affected_callers,
        "affected_callees": affected_callees,
        "affected_dependents": affected_dependents,
        "affected_routes": affected_routes,
    }
