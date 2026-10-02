"""Lexical search using SQLite FTS5.

Retrieval is lexical + path/symbol ranking.  No semantic embeddings.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SearchResult:
    file: str
    symbol: str | None
    start_line: int
    end_line: int
    score: float
    reason: str
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# FTS5 reserved words that cannot appear as bare terms
_FTS5_RESERVED = frozenset({
    "AND", "OR", "NOT",
})

# FTS5 special characters to strip from terms
_FTS5_SPECIAL = re.compile(r"[^\w]")  # keep only word chars inside terms


def _safe_fts5_terms(query: str) -> list[str]:
    """Extract word-like tokens safe for FTS5 MATCH expressions.

    - Splits on non-alphanumeric characters (dots, dashes, etc.)
    - Drops single-character tokens
    - Drops FTS5 reserved words
    - Returns deduplicated list preserving order
    """
    # Split on anything that is not alphanumeric or underscore
    raw_tokens = re.split(r"[^A-Za-z0-9_]+", query)
    seen: set[str] = set()
    result: list[str] = []
    for tok in raw_tokens:
        tok = tok.strip()
        if len(tok) < 2:
            continue
        if tok.upper() in _FTS5_RESERVED:
            continue
        if tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result


def search(
    con: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    include_generated: bool = False,
) -> list[SearchResult]:
    terms = _safe_fts5_terms(query)
    if not terms:
        return []
    clauses = " OR ".join(terms)
    try:
        if include_generated:
            rows = con.execute(
                "SELECT c.path, c.symbol, c.start_line, c.end_line, c.content, "
                "bm25(chunks_fts) AS rank "
                "FROM chunks_fts "
                "JOIN chunks c ON c.id = chunks_fts.rowid "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (clauses, top_k * 3),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT c.path, c.symbol, c.start_line, c.end_line, c.content, "
                "bm25(chunks_fts) AS rank "
                "FROM chunks_fts "
                "JOIN chunks c ON c.id = chunks_fts.rowid "
                "LEFT JOIN files f ON f.path = c.path "
                "WHERE chunks_fts MATCH ? AND (f.category IS NULL OR f.category != 'GENERATED') "
                "ORDER BY rank LIMIT ?",
                (clauses, top_k * 3),
            ).fetchall()
    except sqlite3.OperationalError:
        try:
            rows = con.execute(
                "SELECT c.path, c.symbol, c.start_line, c.end_line, c.content, "
                "bm25(chunks_fts) AS rank "
                "FROM chunks_fts "
                "JOIN chunks c ON c.id = chunks_fts.rowid "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (clauses, top_k * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    results: list[SearchResult] = []
    query.lower()
    for row in rows:
        path_bonus = 1.0 if any(t.lower() in row["path"].lower() for t in terms) else 0.0
        symbol_bonus = (
            1.0
            if row["symbol"] and any(t.lower() in row["symbol"].lower() for t in terms)
            else 0.0
        )
        # Exact symbol match (highest bonus)
        exact_bonus = (
            0.5
            if row["symbol"] and any(
                t.lower() == row["symbol"].lower()
                or t.lower() == row["symbol"].split(".")[-1].lower()
                for t in terms
            )
            else 0.0
        )
        score = round(min(1.0, 0.3 + path_bonus * 0.15 + symbol_bonus * 0.2 + exact_bonus * 0.35), 2)
        reason = "lexical match"
        if symbol_bonus:
            reason += ", symbol match"
        if path_bonus:
            reason += ", path match"
        snippet = row["content"][:900]
        results.append(
            SearchResult(
                row["path"],
                row["symbol"],
                row["start_line"],
                row["end_line"],
                score,
                reason,
                snippet,
            )
        )

    # Sort by score descending (bm25 is negative, lower = better match)
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def search_lexical(con: sqlite3.Connection, query: str, top_k: int = 10) -> list[SearchResult]:
    """Lexical FTS5 search (wrapper around search)."""
    return search(con, query, top_k=top_k)


def _fetch_snippet(
    con: sqlite3.Connection, path: str, start: int, end: int, symbol: str | None = None
) -> str:
    try:
        row = con.execute(
            "SELECT content FROM chunks WHERE path=? AND start_line<=? AND end_line>=? LIMIT 1",
            (path, start, end),
        ).fetchone()
        if row and row["content"]:
            return str(row["content"])[:900]
        if symbol:
            row = con.execute(
                "SELECT content FROM chunks WHERE symbol=? LIMIT 1", (symbol,)
            ).fetchone()
            if row and row["content"]:
                return str(row["content"])[:900]
    except sqlite3.OperationalError:
        pass
    return ""


def search_exact_canonical_id(
    con: sqlite3.Connection, canonical_id: str
) -> list[SearchResult]:
    """Look up symbol by exact canonical ID."""
    clean = canonical_id.strip()
    if not clean:
        return []
    try:
        rows = con.execute(
            "SELECT canonical_id, qualified_name, path, start_line, end_line "
            "FROM symbols WHERE canonical_id=? ORDER BY path, start_line",
            (clean,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[SearchResult] = []
    for r in rows:
        snippet = _fetch_snippet(con, r["path"], r["start_line"], r["end_line"], r["qualified_name"])
        results.append(
            SearchResult(
                file=r["path"],
                symbol=r["qualified_name"] or r["canonical_id"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                score=1.0,
                reason="exact canonical id match",
                snippet=snippet,
            )
        )
    return results


def search_exact_qualified(
    con: sqlite3.Connection, qualified_name: str
) -> list[SearchResult]:
    """Look up symbol by exact qualified name."""
    clean = qualified_name.strip()
    if not clean:
        return []
    try:
        rows = con.execute(
            "SELECT canonical_id, qualified_name, path, start_line, end_line "
            "FROM symbols WHERE qualified_name=? OR canonical_id=? ORDER BY path, start_line",
            (clean, clean),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[SearchResult] = []
    for r in rows:
        snippet = _fetch_snippet(con, r["path"], r["start_line"], r["end_line"], r["qualified_name"])
        results.append(
            SearchResult(
                file=r["path"],
                symbol=r["qualified_name"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                score=0.95,
                reason="exact qualified match",
                snippet=snippet,
            )
        )
    return results


def search_exact_symbol(
    con: sqlite3.Connection, name: str
) -> list[SearchResult]:
    """Look up symbol by short identifier name."""
    clean = name.strip()
    if not clean:
        return []
    try:
        rows = con.execute(
            "SELECT canonical_id, qualified_name, path, start_line, end_line "
            "FROM symbols WHERE name=? ORDER BY path, start_line",
            (clean,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[SearchResult] = []
    for r in rows:
        snippet = _fetch_snippet(con, r["path"], r["start_line"], r["end_line"], r["qualified_name"])
        results.append(
            SearchResult(
                file=r["path"],
                symbol=r["qualified_name"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                score=0.90,
                reason="exact symbol match",
                snippet=snippet,
            )
        )
    return results


def search_route(
    con: sqlite3.Connection, route_or_endpoint: str
) -> list[SearchResult]:
    """Look up framework route by path or endpoint ID."""
    clean = route_or_endpoint.strip()
    if not clean:
        return []
    try:
        rows = con.execute(
            "SELECT route_path, http_method, handler_name, file_path, line, endpoint_id, evidence "
            "FROM framework_routes WHERE route_path=? OR endpoint_id=? ORDER BY file_path, line",
            (clean, clean),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[SearchResult] = []
    for r in rows:
        snippet = _fetch_snippet(con, r["file_path"], r["line"], r["line"], r["handler_name"])
        results.append(
            SearchResult(
                file=r["file_path"],
                symbol=r["handler_name"] or r["route_path"],
                start_line=r["line"],
                end_line=r["line"],
                score=0.95,
                reason=f"route match: {r['http_method']} {r['route_path']}",
                snippet=snippet,
            )
        )
    return results
