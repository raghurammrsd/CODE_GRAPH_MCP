"""Graph traversal and query engine: call graph, dependency graph, impact analysis, tests.

Confidence Vocabulary:
  HIGH   — parser-confirmed, symbol-resolved, source-backed (verified)
  MEDIUM — structurally inferred (unique match, partial resolution, same module)
  LOW    — textual/heuristic match (unverified)
  UNKNOWN — unresolved reference / dynamic call

Edge Classifications:
  STRUCTURAL: DEFINES, CONTAINS, EXPORTS, REEXPORTS
  SEMANTIC:   IMPORTS, CALLS, EXTENDS, IMPLEMENTS, HANDLED_BY, TESTS
  UNCERTAIN:  POSSIBLE_CALLS

Architectural Invariant:
  Graph is a projection of resolved source facts and references.
  Heuristics are never promoted to verified CALLS.
  Inverses (e.g. A --CALLS--> B queryable as CALLED_BY) do not duplicate independent facts.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from codegraph.evidence.citations import get_repository_from_con, verify_source_hash
from codegraph.freshness import index_generation
from codegraph.indexing.models import Symbol
from codegraph.resources import get_global_governor, get_graph_cache

from .models import GraphEdge


class AttrDict(dict[str, Any]):
    """Dict subclass that provides attribute access for ergonomics and JSON compatibility."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


_NOISY_UNRESOLVED_NAMES = frozenset({
    "size", "shape", "view", "transpose", "squeeze", "unsqueeze", "reshape", "item", "dim",
    "get", "keys", "values", "items", "append", "extend", "pop", "insert", "clear", "copy",
    "format", "split", "strip", "lstrip", "rstrip", "join", "replace", "startswith", "endswith",
    "lower", "upper", "count", "index", "find", "update", "add", "remove", "discard",
    "encode", "decode", "read", "write", "close", "flush", "seek", "tell",
    "print", "len", "range", "str", "int", "float", "bool", "dict", "list", "set", "tuple",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr", "type", "id",
    "min", "max", "sum", "all", "any", "zip", "enumerate", "map", "filter", "sorted", "reversed",
    "cat", "stack", "zeros", "ones", "empty", "tensor", "from_numpy", "device", "to", "backward",
})


# ---------------------------------------------------------------------------
# Symbol Query API
# ---------------------------------------------------------------------------


def get_symbol(con: sqlite3.Connection, canonical_id: str) -> Symbol | None:
    """Retrieve a single symbol by its exact canonical ID."""
    row = con.execute(
        "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
        "id, canonical_id, language, module, scope, signature, content_hash, "
        "parent_symbol_id, visibility, return_type, parameter_count, documentation "
        "FROM symbols WHERE canonical_id=? OR id=? LIMIT 1",
        (canonical_id, canonical_id),
    ).fetchone()
    if not row:
        return None
    return _row_to_symbol(row)


def find_symbol_exact(con: sqlite3.Connection, qualified_name: str) -> list[Symbol]:
    """Retrieve symbols matching exact canonical_id or qualified_name."""
    rows = con.execute(
        "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
        "id, canonical_id, language, module, scope, signature, content_hash, "
        "parent_symbol_id, visibility, return_type, parameter_count, documentation "
        "FROM symbols WHERE canonical_id=? OR qualified_name=? "
        "ORDER BY path, start_line",
        (qualified_name, qualified_name),
    ).fetchall()
    return [_row_to_symbol(r) for r in rows]


def find_symbols(
    con: sqlite3.Connection, name: str, max_results: int = 50
) -> list[Symbol]:
    """Find symbols by canonical ID, qualified name, or short name with deterministic ranking.

    - If query has dots and matches canonical_id, returns exact canonical match.
    - If query has dots and matches qualified_name, returns qualified matches.
    - If query has no dots, returns symbols where name = query, preserving all distinct modules.
    """
    clean = name.strip()
    if not clean:
        return []

    # 1. Exact canonical ID match
    canon_rows = con.execute(
        "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
        "id, canonical_id, language, module, scope, signature, content_hash, "
        "parent_symbol_id, visibility, return_type, parameter_count, documentation "
        "FROM symbols WHERE canonical_id=? ORDER BY path, start_line LIMIT ?",
        (clean, max_results),
    ).fetchall()
    if canon_rows:
        return [_row_to_symbol(r) for r in canon_rows]

    # 2. Qualified name match if dotted
    if "." in clean:
        q_rows = con.execute(
            "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
            "id, canonical_id, language, module, scope, signature, content_hash, "
            "parent_symbol_id, visibility, return_type, parameter_count, documentation "
            "FROM symbols WHERE qualified_name=? OR canonical_id LIKE ? "
            "ORDER BY path, start_line LIMIT ?",
            (clean, f"%.{clean}", max_results),
        ).fetchall()
        if q_rows:
            return [_row_to_symbol(r) for r in q_rows]

    # 3. Short name match
    short_rows = con.execute(
        "SELECT name, qualified_name, kind, path, start_line, end_line, decorators, "
        "id, canonical_id, language, module, scope, signature, content_hash, "
        "parent_symbol_id, visibility, return_type, parameter_count, documentation "
        "FROM symbols WHERE name=? ORDER BY path, start_line, canonical_id LIMIT ?",
        (clean, max_results),
    ).fetchall()
    return [_row_to_symbol(r) for r in short_rows]


find_symbol = find_symbols


def _row_to_symbol(r: sqlite3.Row) -> Symbol:
    dec_list = [d for d in str(r["decorators"]).split(",") if d]
    return Symbol(
        id=str(r["id"]),
        canonical_id=str(r["canonical_id"]),
        name=str(r["name"]),
        qualified_name=str(r["qualified_name"]),
        kind=str(r["kind"]),
        start_line=int(r["start_line"]),
        end_line=int(r["end_line"]),
        file_path=str(r["path"]),
        decorators=dec_list,
        language=str(r["language"]),
        module=str(r["module"]),
        path=str(r["path"]),
        scope=str(r["scope"]),
        signature=str(r["signature"]),
        content_hash=str(r["content_hash"]),
        parent_symbol_id=r["parent_symbol_id"],
        visibility=str(r["visibility"]),
        return_type=r["return_type"],
        parameter_count=r["parameter_count"],
        documentation=r["documentation"],
    )


# ---------------------------------------------------------------------------
# References & Call Graph API
# ---------------------------------------------------------------------------


def find_references(
    con: sqlite3.Connection,
    canonical_id: str,
    max_results: int = 100,
) -> list[AttrDict]:
    """Return verified and pending references targeting the given symbol."""
    repo = get_repository_from_con(con)
    rows = con.execute(
        "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
        "path, start_line, end_line, evidence, source_hash, indexed_commit, evidence_status "
        "FROM 'references' "
        "WHERE target_symbol_id=? OR target_symbol_id LIKE ? "
        "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
        (canonical_id, f"%.{canonical_id}", max_results),
    ).fetchall()

    results: list[AttrDict] = []
    for r in rows:
        st = verify_source_hash(repo, r["path"], r["source_hash"])
        results.append(
            AttrDict(
                source_symbol_id=r["source_symbol_id"],
                target_symbol_id=r["target_symbol_id"],
                source=r["source_symbol_id"],
                target=r["target_symbol_id"],
                relationship=r["relationship"],
                confidence=r["confidence"] if st == "current" else "LOW",
                path=r["path"],
                file=r["path"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                line=r["start_line"],
                evidence=r["evidence"],
                source_hash=r["source_hash"],
                indexed_commit=r["indexed_commit"],
                evidence_status=st,
            )
        )
    return results


def find_callers(
    con: sqlite3.Connection,
    symbol: str,
    max_results: int = 50,
) -> list[AttrDict]:
    """Return verified callers from resolved references, falling back to static calls table.

    Verified callers carry confidence 'HIGH' or 'MEDIUM' and relationship 'CALLS'.
    Unverified textual matches carry confidence 'LOW' and relationship 'POSSIBLE_CALLS'.
    """
    gov = get_global_governor()
    max_results = min(max_results, gov.policy.max_graph_nodes_per_query)
    gen = index_generation(con)
    cache = get_graph_cache()
    cache_key = (gen, "callers", symbol, max_results)
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, list):
        return cached

    repo = get_repository_from_con(con)
    clean_sym = symbol.strip()
    short_name = clean_sym.split(":")[-1].split(".")[-1]
    results: list[AttrDict] = []
    seen: set[tuple[str, str | None, int]] = set()
    resolved_lines: set[tuple[str, int]] = set()

    # Resolve symbol to canonical IDs when present in symbols table
    target_canons: list[str] = []
    try:
        sym_rows = con.execute(
            "SELECT canonical_id, qualified_name FROM symbols "
            "WHERE canonical_id=? OR qualified_name=? OR name=? "
            "ORDER BY (canonical_id=?) DESC, (qualified_name=?) DESC",
            (clean_sym, clean_sym, clean_sym, clean_sym, clean_sym),
        ).fetchall()
        exact_canons = [str(r["canonical_id"]) for r in sym_rows if r["canonical_id"] == clean_sym]
        exact_qnames = [str(r["canonical_id"]) for r in sym_rows if r["qualified_name"] == clean_sym]
        if exact_canons:
            target_canons = exact_canons
        elif exact_qnames:
            target_canons = exact_qnames
        elif sym_rows and "." not in clean_sym:
            target_canons = [str(r["canonical_id"]) for r in sym_rows]
    except Exception:
        target_canons = []

    # 1. Resolved CALLS edges from references table
    if target_canons:
        ph = ",".join("?" for _ in target_canons)
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            f"WHERE relationship='CALLS' AND (target_symbol_id IN ({ph}) OR target_symbol_id=? OR target_symbol_id LIKE ?) "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            [*target_canons, clean_sym, f"%.{clean_sym}", max_results],
        ).fetchall()
    elif "." in clean_sym:
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            "WHERE relationship='CALLS' AND (target_symbol_id=? OR target_symbol_id LIKE ?) "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            (clean_sym, f"%.{clean_sym}", max_results),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            "WHERE relationship='CALLS' AND (target_symbol_id=? OR target_symbol_id LIKE ? OR target_symbol_id LIKE ?) "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            (clean_sym, f"%.{clean_sym}", f"%.{short_name}", max_results),
        ).fetchall()

    for r in rows:
        key = (r["path"], r["source_symbol_id"], r["start_line"])
        if key in seen:
            continue
        seen.add(key)
        resolved_lines.add((r["path"], int(r["start_line"])))
        st = verify_source_hash(repo, r["path"], r["source_hash"])
        ev_text = str(r["evidence"] or "")
        ev_cls = "DATAFLOW_VERIFIED" if ("resolved via" in ev_text.lower() or "factory" in ev_text.lower()) else "AST_VERIFIED"
        results.append(
            AttrDict(
                file=r["path"],
                path=r["path"],
                symbol=r["source_symbol_id"],
                caller=r["source_symbol_id"],
                canonical_id=r["source_symbol_id"],
                source_symbol_id=r["source_symbol_id"],
                callee=short_name,
                target_symbol_id=r["target_symbol_id"],
                line=r["start_line"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                relationship="CALLS",
                evidence_class=ev_cls,
                confidence=r["confidence"] if st == "current" else "LOW",
                evidence=ev_text,
                evidence_status=st,
            )
        )

    # 2. Check static calls table (for unresolved or partially resolved calls)
    if len(results) < max_results:
        rem = max_results - len(results)
        if target_canons:
            ph = ",".join("?" for _ in target_canons)
            call_rows = con.execute(
                "SELECT source_path, callee, qualified_callee, line, confidence, source_symbol_id, resolved_symbol_id "
                f"FROM calls WHERE resolved_symbol_id IN ({ph}) OR qualified_callee=? OR (resolved_symbol_id IS NULL AND callee=?) LIMIT ?",
                [*target_canons, clean_sym, short_name, rem * 2],
            ).fetchall()
        else:
            call_rows = con.execute(
                "SELECT source_path, callee, qualified_callee, line, confidence, source_symbol_id, resolved_symbol_id "
                "FROM calls WHERE callee=? OR qualified_callee=? OR resolved_symbol_id=? LIMIT ?",
                (short_name, clean_sym, clean_sym, rem * 2),
            ).fetchall()

        target_canon_set = set(target_canons)
        for cr in call_rows:
            if (cr["source_path"], int(cr["line"])) in resolved_lines:
                continue
            if cr["resolved_symbol_id"] and target_canon_set and cr["resolved_symbol_id"] not in target_canon_set:
                continue
            key = (cr["source_path"], cr["source_symbol_id"], cr["line"])
            if key in seen:
                continue
            seen.add(key)
            conf = cr["confidence"] or "LOW"
            rel = "CALLS" if conf in ("HIGH", "MEDIUM") else "POSSIBLE_CALLS"
            ev_cls = "AST_VERIFIED" if rel == "CALLS" else ("UNKNOWN" if conf == "UNKNOWN" else "POSSIBLE")
            results.append(
                AttrDict(
                    file=cr["source_path"],
                    path=cr["source_path"],
                    symbol=cr["source_symbol_id"] or cr["source_path"],
                    caller=cr["source_symbol_id"] or cr["source_path"],
                    canonical_id=cr["source_symbol_id"] or "",
                    source_symbol_id=cr["source_symbol_id"],
                    callee=cr["callee"],
                    qualified_callee=cr["qualified_callee"],
                    target_symbol_id=cr["resolved_symbol_id"],
                    line=cr["line"],
                    start_line=cr["line"],
                    end_line=cr["line"],
                    relationship=rel,
                    evidence_class=ev_cls,
                    confidence=conf,
                    evidence=f"Static call site '{cr['callee']}()' in {cr['source_path']}:{cr['line']}",
                )
            )
            if len(results) >= max_results:
                break

    final_callers = results[:max_results]
    cache.set(cache_key, final_callers)
    return final_callers


get_callers = find_callers


def find_callees(
    con: sqlite3.Connection,
    symbol: str,
    max_results: int = 50,
) -> list[AttrDict]:
    """Return callees called by the given symbol's body."""
    gov = get_global_governor()
    max_results = min(max_results, gov.policy.max_graph_nodes_per_query)
    gen = index_generation(con)
    cache = get_graph_cache()
    cache_key = (gen, "callees", symbol, max_results)
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, list):
        return cached

    repo = get_repository_from_con(con)
    clean_sym = symbol.strip()
    short_name = clean_sym.split(":")[-1].split(".")[-1]
    results: list[AttrDict] = []
    seen: set[tuple[str, str | None, int]] = set()

    source_canons: list[str] = []
    try:
        sym_rows = con.execute(
            "SELECT canonical_id, qualified_name FROM symbols "
            "WHERE canonical_id=? OR qualified_name=? OR name=? "
            "ORDER BY (canonical_id=?) DESC, (qualified_name=?) DESC",
            (clean_sym, clean_sym, clean_sym, clean_sym, clean_sym),
        ).fetchall()
        exact_canons = [str(r["canonical_id"]) for r in sym_rows if r["canonical_id"] == clean_sym]
        exact_qnames = [str(r["canonical_id"]) for r in sym_rows if r["qualified_name"] == clean_sym]
        if exact_canons:
            source_canons = exact_canons
        elif exact_qnames:
            source_canons = exact_qnames
        elif sym_rows and "." not in clean_sym:
            source_canons = [str(r["canonical_id"]) for r in sym_rows]
    except Exception:
        source_canons = []

    # 1. Check resolved references where source_symbol_id matches symbol
    if source_canons:
        ph = ",".join("?" for _ in source_canons)
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            f"WHERE (source_symbol_id IN ({ph}) OR source_symbol_id=? OR source_symbol_id LIKE ?) "
            "AND relationship IN ('CALLS', 'UNRESOLVED_REFERENCE') "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            [*source_canons, clean_sym, f"%.{clean_sym}", max_results],
        ).fetchall()
    elif "." in clean_sym:
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            "WHERE (source_symbol_id=? OR source_symbol_id LIKE ?) "
            "AND relationship IN ('CALLS', 'UNRESOLVED_REFERENCE') "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            (clean_sym, f"%.{clean_sym}", max_results),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
            "path, start_line, end_line, evidence, source_hash "
            "FROM 'references' "
            "WHERE (source_symbol_id=? OR source_symbol_id LIKE ? OR source_symbol_id LIKE ?) "
            "AND relationship IN ('CALLS', 'UNRESOLVED_REFERENCE') "
            "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
            (clean_sym, f"%.{clean_sym}", f"%.{short_name}", max_results),
        ).fetchall()

    for r in rows:
        key = (r["path"], r["target_symbol_id"], r["start_line"])
        if key in seen:
            continue
        callee_nm = r["target_symbol_id"].split(".")[-1] if r["target_symbol_id"] else "unresolved"
        # Prune noisy standard primitive / builtin / tensor method calls that clutter the graph with UNKNOWN noise
        if r["relationship"] == "UNRESOLVED_REFERENCE" and (
            callee_nm in _NOISY_UNRESOLVED_NAMES or callee_nm.startswith("_")
        ):
            continue
        seen.add(key)
        st = verify_source_hash(repo, r["path"], r["source_hash"])
        ev_text = str(r["evidence"] or "")
        ev_cls = (
            "UNKNOWN"
            if r["relationship"] == "UNRESOLVED_REFERENCE"
            else ("DATAFLOW_VERIFIED" if ("resolved via" in ev_text.lower() or "factory" in ev_text.lower()) else "AST_VERIFIED")
        )
        results.append(
            AttrDict(
                callee=callee_nm,
                qualified_callee=r["target_symbol_id"],
                canonical_id=r["target_symbol_id"],
                target_symbol_id=r["target_symbol_id"],
                source_symbol_id=r["source_symbol_id"],
                file=r["path"],
                path=r["path"],
                line=r["start_line"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                relationship=r["relationship"],
                evidence_class=ev_cls,
                confidence=r["confidence"] if st == "current" else "LOW",
                evidence=ev_text,
                evidence_status=st,
            )
        )

    # 2. Check chunks / calls table if references did not contain calls
    if not results:
        chunk = con.execute(
            "SELECT path, start_line, end_line, content FROM chunks "
            "WHERE symbol=? OR symbol LIKE ? LIMIT 1",
            (clean_sym, f"%.{clean_sym}"),
        ).fetchone()
        if chunk:
            call_rows = con.execute(
                "SELECT callee, qualified_callee, resolved_symbol_id, line, confidence FROM calls "
                "WHERE source_path=? AND line >= ? AND line <= ? LIMIT ?",
                (chunk["path"], chunk["start_line"], chunk["end_line"], max_results),
            ).fetchall()
            for cr in call_rows:
                conf = cr["confidence"] or "LOW"
                rel = "CALLS" if conf in ("HIGH", "MEDIUM") else "POSSIBLE_CALLS"
                results.append(
                    AttrDict(
                        callee=cr["callee"],
                        qualified_callee=cr["resolved_symbol_id"] or cr["qualified_callee"],
                        canonical_id=cr["resolved_symbol_id"],
                        target_symbol_id=cr["resolved_symbol_id"],
                        line=cr["line"],
                        start_line=cr["line"],
                        end_line=cr["line"],
                        file=chunk["path"],
                        path=chunk["path"],
                        relationship=rel,
                        evidence_class="AST_VERIFIED" if rel == "CALLS" else ("UNKNOWN" if conf == "UNKNOWN" else "POSSIBLE"),
                        confidence=conf,
                        evidence=f"Call site in {chunk['path']}:{cr['line']}",
                    )
                )

    final_callees = results[:max_results]
    cache.set(cache_key, final_callees)
    return final_callees


get_callees = find_callees


def find_implementations(
    con: sqlite3.Connection,
    canonical_id: str,
    max_results: int = 50,
) -> list[AttrDict]:
    """Find classes or interfaces that EXTENDS or IMPLEMENTS canonical_id."""
    short = canonical_id.split(".")[-1]
    rows = con.execute(
        "SELECT source_symbol_id, target_symbol_id, relationship, confidence, path, start_line, end_line, evidence "
        "FROM 'references' "
        "WHERE relationship IN ('EXTENDS', 'IMPLEMENTS') AND (target_symbol_id=? OR target_symbol_id LIKE ? OR target_symbol_id=?) "
        "ORDER BY path, start_line LIMIT ?",
        (canonical_id, f"%.{canonical_id}", short, max_results),
    ).fetchall()

    return [
        AttrDict(
            implementor=r["source_symbol_id"],
            target=r["target_symbol_id"],
            relationship=r["relationship"],
            confidence=r["confidence"],
            file=r["path"],
            line=r["start_line"],
            evidence=r["evidence"],
        )
        for r in rows
    ]


def get_call_graph(
    con: sqlite3.Connection,
    symbol: str | None = None,
    depth: int = 2,
    max_results: int = 100,
) -> list[AttrDict]:
    """Return call graph edges up to `depth` hops."""
    if depth < 1:
        depth = 1
    if depth > 5:
        depth = 5

    edges: list[AttrDict] = []
    visited: set[tuple[str, str]] = set()

    if symbol:
        frontier = {symbol}
        for _ in range(depth):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for sym in frontier:
                callers = find_callers(con, sym, max_results=max_results)
                for c in callers:
                    src = c.get("source_symbol_id") or c.get("file")
                    tgt = c.get("target_symbol_id") or sym
                    edge_key = (str(src), str(tgt))
                    if edge_key not in visited:
                        visited.add(edge_key)
                        edges.append(
                            AttrDict(
                                source=src,
                                target=tgt,
                                relationship=c.get("relationship", "CALLS"),
                                confidence=c.get("confidence", "HIGH"),
                                file=c.get("file"),
                                line=c.get("line"),
                                evidence=c.get("evidence", ""),
                            )
                        )
                        if src and str(src) not in frontier:
                            next_frontier.add(str(src))
            frontier = next_frontier
        return edges[:max_results]
    else:
        rows = con.execute(
            "SELECT source, target, relationship, confidence, file, start_line, evidence "
            "FROM graph_edges WHERE relationship IN ('CALLS', 'POSSIBLE_CALLS', 'HANDLED_BY', 'ROUTES_TO') "
            "LIMIT ?",
            (max_results,),
        ).fetchall()
        return [
            AttrDict(
                source=r["source"],
                target=r["target"],
                relationship=r["relationship"],
                confidence=r["confidence"],
                file=r["file"],
                line=r["start_line"],
                evidence=r["evidence"],
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Dependency & Import Graph API
# ---------------------------------------------------------------------------


def get_dependency_graph(
    con: sqlite3.Connection,
    path: str | None = None,
    depth: int = 2,
    max_results: int = 200,
) -> list[dict[str, object]]:
    """Return import dependency edges, optionally scoped to a starting file."""
    if depth < 1:
        depth = 1
    if depth > 5:
        depth = 5

    if path:
        visited: set[str] = set()
        frontier = {path}
        edges: list[dict[str, object]] = []
        for _ in range(depth):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for src in frontier:
                if src in visited:
                    continue
                visited.add(src)
                rows = con.execute(
                    "SELECT module, resolved_path FROM imports WHERE source_path=? LIMIT ?",
                    (src, max_results),
                ).fetchall()
                for row in rows:
                    edges.append(
                        {
                            "source": src,
                            "target": row["module"],
                            "resolved_target": row["resolved_path"],
                            "relationship": "IMPORTS",
                            "confidence": "HIGH",
                            "evidence": f"Import '{row['module']}' in {src}",
                        }
                    )
                    if row["resolved_path"] and row["resolved_path"] not in visited:
                        next_frontier.add(row["resolved_path"])
            frontier = next_frontier - visited
        return edges[:max_results]
    else:
        rows = con.execute(
            "SELECT source_path, module, resolved_path FROM imports LIMIT ?", (max_results,)
        ).fetchall()
        return [
            {
                "source": r["source_path"],
                "target": r["module"],
                "resolved_target": r["resolved_path"],
                "relationship": "IMPORTS",
                "confidence": "HIGH",
                "evidence": "Parser-extracted import declaration",
            }
            for r in rows
        ]


def find_importers(
    con: sqlite3.Connection,
    module: str,
    max_results: int = 100,
) -> list[dict[str, object]]:
    """Return files that import a given module or file."""
    rows = con.execute(
        "SELECT source_path, module, name, alias, resolved_path FROM imports "
        "WHERE module=? OR resolved_module=? OR resolved_path=? OR full_name LIKE ? "
        "ORDER BY source_path LIMIT ?",
        (module, module, module, f"{module}%", max_results),
    ).fetchall()
    return [
        {
            "importer": r["source_path"],
            "module": r["module"],
            "name": r["name"],
            "alias": r["alias"],
            "resolved_path": r["resolved_path"],
            "confidence": "HIGH",
            "evidence": "Parser-extracted import declaration",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Test Intelligence API
# ---------------------------------------------------------------------------

_TEST_FILE_RE = re.compile(
    r"(^|[_/])test[_s]?[_/]|[_/]spec[_/]|test[_s]?\.(py|js|ts|jsx|tsx)$|spec\.(py|js|ts|jsx|tsx)$",
    re.IGNORECASE,
)


def find_related_tests(
    con: sqlite3.Connection,
    symbol_or_path: str,
    max_results: int = 20,
) -> list[dict[str, object]]:
    """Find test files and test symbols statically linked to a symbol, route, or file with verified provenance."""
    gov = get_global_governor()
    max_results = min(max_results, gov.policy.max_graph_nodes_per_query)
    gen = index_generation(con)
    cache = get_graph_cache()
    cache_key = (gen, "related_tests", symbol_or_path, max_results)
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, list):
        return cached

    clean_target = symbol_or_path.strip()
    path_only = clean_target
    for method in ("POST ", "GET ", "PUT ", "DELETE ", "PATCH ", "HEAD ", "OPTIONS "):
        if path_only.startswith(method):
            path_only = path_only[len(method):].strip()
            break
    tests: list[dict[str, object]] = []
    seen: set[tuple[str, str | None]] = set()  # (file, test_symbol)

    def add_test(
        file_path: str,
        test_sym: str | None,
        target_sym: str,
        rel: str,
        classification: str,
        confidence: str,
        evidence_class: str,
        reason: str,
        evidence: str,
        start_line: int = 1,
    ) -> None:
        key = (file_path, test_sym)
        if key in seen:
            return
        seen.add(key)
        tests.append(
            {
                "file": file_path,
                "symbol": test_sym,
                "test_symbol": test_sym,
                "target_symbol": target_sym,
                "relationship": rel,
                "classification": classification,
                "confidence": confidence,
                "evidence_class": evidence_class,
                "reason": reason,
                "evidence": evidence,
                "line": start_line,
                "start_line": start_line,
            }
        )

    # 1. Target identification
    target_canonical_ids: set[str] = set()
    target_routes: list[sqlite3.Row] = []

    # Check if target is an API route or endpoint ID
    route_rows = con.execute(
        "SELECT endpoint_id, framework, http_method, route_path, handler_name, handler_canonical_id, file_path, line, evidence "
        "FROM framework_routes WHERE endpoint_id = ? OR route_path = ? OR normalized_route = ? OR route_path = ?",
        (
            clean_target,
            clean_target,
            clean_target,
            path_only,
        ),
    ).fetchall()
    target_routes.extend(route_rows)

    # Check if target is in symbols table
    sym_rows = con.execute(
        "SELECT canonical_id, qualified_name, name, path, start_line FROM symbols "
        "WHERE canonical_id = ? OR qualified_name = ? OR name = ?",
        (clean_target, clean_target, clean_target),
    ).fetchall()
    for s_row in sym_rows:
        target_canonical_ids.add(str(s_row["canonical_id"]))

    if not target_canonical_ids and not target_routes:
        # Check if target is a file
        f_row = con.execute("SELECT path FROM files WHERE path = ?", (clean_target,)).fetchone()
        if f_row:
            file_syms = con.execute("SELECT canonical_id FROM symbols WHERE path = ?", (clean_target,)).fetchall()
            for fs in file_syms:
                target_canonical_ids.add(str(fs["canonical_id"]))
        else:
            target_canonical_ids.add(clean_target)

    # Also check if any target_canonical_id is an API route handler
    for c_id in list(target_canonical_ids):
        c_short = c_id.split(".")[-1]
        hr_rows = con.execute(
            "SELECT endpoint_id, framework, http_method, route_path, handler_name, handler_canonical_id, file_path, line, evidence "
            "FROM framework_routes WHERE handler_canonical_id = ? OR handler_name = ?",
            (c_id, c_short),
        ).fetchall()
        for hr in hr_rows:
            if hr["endpoint_id"] not in [r["endpoint_id"] for r in target_routes]:
                target_routes.append(hr)

    # 2. Collect tests

    # A. Route tests (TESTS_ROUTE edges)
    for r in target_routes:
        ep_id = r["endpoint_id"]
        rt_edges = con.execute(
            "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
            "FROM graph_edges WHERE target = ? AND relationship IN ('TESTS_ROUTE', 'TESTS')",
            (ep_id,),
        ).fetchall()
        for e in rt_edges:
            add_test(
                file_path=e["file"],
                test_sym=e["source"],
                target_sym=ep_id,
                rel="TESTS_ROUTE",
                classification="VERIFIED_TEST",
                confidence="HIGH",
                evidence_class=e["evidence_class"] or "FRAMEWORK_VERIFIED",
                reason=e["reason"] or f"http_client_test:{r['http_method']} {r['route_path']}",
                evidence=e["evidence"] or f"Test exercises route {r['route_path']}",
                start_line=e["start_line"],
            )

    # B. Event / Registry Handler tests (TESTS_EVENT_HANDLER)
    for c_id in target_canonical_ids:
        c_short = c_id.split(".")[-1]
        dispatch_tests = con.execute(
            "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
            "FROM graph_edges WHERE (target = ? OR target LIKE ?) AND relationship = 'TESTS_EVENT_HANDLER'",
            (c_id, f"%.{c_short}"),
        ).fetchall()
        for dte in dispatch_tests:
            add_test(
                file_path=dte["file"],
                test_sym=dte["source"],
                target_sym=c_id,
                rel="TESTS_EVENT_HANDLER",
                classification="POSSIBLE_TEST",
                confidence="MEDIUM",
                evidence_class="FRAMEWORK_VERIFIED",
                reason=dte["reason"] or "event_dispatch_test",
                evidence=dte["evidence"] or f"Test dispatches event exercising {c_id}",
                start_line=dte["start_line"],
            )

    # C. DI Provider tests (TESTS_PROVIDER)
    for c_id in target_canonical_ids:
        c_short = c_id.split(".")[-1]
        di_edges = con.execute(
            "SELECT source, target FROM graph_edges WHERE (source = ? OR target = ?) AND relationship IN ('PROVIDES', 'RESOLVES_DEPENDENCY', 'INJECTS')",
            (c_id, c_id),
        ).fetchall()
        related_prov_canons = {c_id}
        for de in di_edges:
            related_prov_canons.add(de["source"])
            related_prov_canons.add(de["target"])

        for prov in related_prov_canons:
            prov_edges = con.execute(
                "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
                "FROM graph_edges WHERE (target = ? OR target LIKE ?) AND relationship = 'TESTS_PROVIDER'",
                (prov, f"%.{prov.split('.')[-1]}"),
            ).fetchall()
            for pe in prov_edges:
                add_test(
                    file_path=pe["file"],
                    test_sym=pe["source"],
                    target_sym=prov,
                    rel="TESTS_PROVIDER",
                    classification="VERIFIED_TEST",
                    confidence="HIGH",
                    evidence_class="DATAFLOW_VERIFIED",
                    reason=pe["reason"] or "dependency_provider_test",
                    evidence=pe["evidence"] or f"Test fixture provides {prov}",
                    start_line=pe["start_line"],
                )

    # D. Direct symbol tests via graph_edges and references (TESTS, TESTS_SYMBOL, CALLS)
    for c_id in target_canonical_ids:
        c_short = c_id.split(".")[-1]
        edge_rows = con.execute(
            "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
            "FROM graph_edges WHERE (target = ? OR target LIKE ?) AND relationship IN ('TESTS', 'TESTS_SYMBOL')",
            (c_id, f"%.{c_short}"),
        ).fetchall()
        for e in edge_rows:
            if _TEST_FILE_RE.search(e["file"]):
                add_test(
                    file_path=e["file"],
                    test_sym=e["source"],
                    target_sym=c_id,
                    rel="TESTS_SYMBOL",
                    classification="VERIFIED_TEST",
                    confidence=e["confidence"] or "HIGH",
                    evidence_class=e["evidence_class"] or "AST_VERIFIED",
                    reason=e["reason"] or "direct_test_call",
                    evidence=e["evidence"] or f"Test exercises {c_id}",
                    start_line=e["start_line"],
                )

        ref_rows = con.execute(
            "SELECT path, source_symbol_id, start_line, evidence FROM 'references' "
            "WHERE (target_symbol_id = ? OR target_symbol_id LIKE ? OR target_symbol_id = ?) "
            "AND relationship IN ('CALLS', 'TESTS')",
            (c_id, f"%.{c_short}", c_short),
        ).fetchall()
        for r in ref_rows:
            if _TEST_FILE_RE.search(r["path"]):
                add_test(
                    file_path=r["path"],
                    test_sym=r["source_symbol_id"],
                    target_sym=c_id,
                    rel="TESTS_SYMBOL",
                    classification="VERIFIED_TEST",
                    confidence="HIGH",
                    evidence_class="AST_VERIFIED",
                    reason="direct_test_call",
                    evidence=f"Test verifies symbol: {r['evidence']}",
                    start_line=r["start_line"],
                )

    # E. Test imports target symbol specifically
    for c_id in target_canonical_ids:
        c_short = c_id.split(".")[-1]
        imp_rows = con.execute(
            "SELECT DISTINCT source_path, line FROM imports "
            "WHERE (imported_name = ? OR local_name = ? OR name = ?)",
            (c_short, c_short, c_short),
        ).fetchall()
        for imp in imp_rows:
            p = imp["source_path"]
            if _TEST_FILE_RE.search(p):
                add_test(
                    file_path=p,
                    test_sym=None,
                    target_sym=c_id,
                    rel="TEST_IMPORTS_SYMBOL",
                    classification="VERIFIED_TEST",
                    confidence="HIGH",
                    evidence_class="AST_VERIFIED",
                    reason="test_imports_target_symbol",
                    evidence=f"Test file specifically imports target '{c_short}'",
                    start_line=imp["line"] or 1,
                )

    # F. Indirect test helper calls
    for c_id in target_canonical_ids:
        direct_callers = con.execute(
            "SELECT source_path, source_symbol_id, line FROM calls "
            "WHERE (qualified_callee = ? OR callee = ?) AND (source_path LIKE '%test%' OR source_path LIKE '%spec%')",
            (c_id, c_id.split(".")[-1]),
        ).fetchall()
        for dc in direct_callers:
            helper_canon = dc["source_symbol_id"]
            if helper_canon and not helper_canon.split(".")[-1].startswith("test_"):
                outer_calls = con.execute(
                    "SELECT source_path, source_symbol_id, line FROM calls WHERE (qualified_callee = ? OR callee = ?)",
                    (helper_canon, helper_canon.split(".")[-1]),
                ).fetchall()
                for oc in outer_calls:
                    if _TEST_FILE_RE.search(oc["source_path"]):
                        add_test(
                            file_path=oc["source_path"],
                            test_sym=oc["source_symbol_id"],
                            target_sym=c_id,
                            rel="TEST_HELPER_CALL",
                            classification="POSSIBLE_TEST",
                            confidence="MEDIUM",
                            evidence_class="AST_VERIFIED",
                            reason=f"indirect_test_helper:{helper_canon.split('.')[-1]}",
                            evidence=f"Test calls helper '{helper_canon}' which calls target",
                            start_line=oc["line"] or 1,
                        )

    # G. Imports containing module fallback
    module_name = (
        clean_target.replace("/", ".").rsplit(".", 1)[0]
        if "." in clean_target
        else clean_target
    )
    if not tests:
        mod_imps = con.execute(
            "SELECT DISTINCT source_path FROM imports "
            "WHERE module = ? OR resolved_module = ?",
            (module_name, module_name),
        ).fetchall()
        for mi in mod_imps:
            p = mi["source_path"]
            if _TEST_FILE_RE.search(p):
                add_test(
                    file_path=p,
                    test_sym=None,
                    target_sym=clean_target,
                    rel="TEST_IMPORTS_MODULE",
                    classification="VERIFIED_TEST",
                    confidence="HIGH",
                    evidence_class="AST_VERIFIED",
                    reason="test_imports_module",
                    evidence=f"Test file imports module '{module_name}'",
                    start_line=1,
                )

    if not tests:
        return [
            {
                "result": "no_static_link_found",
                "detail": (
                    f"No statically linked test found for '{symbol_or_path}'. "
                    "This does not mean tests are completely absent — dynamic test frameworks "
                    "or naming conventions outside our patterns may cover this symbol."
                ),
            }
        ]

    final_tests = tests[:max_results]
    cache.set(cache_key, final_tests)
    return final_tests


def find_affected_tests(
    con: sqlite3.Connection,
    changed_targets: list[str],
    max_results: int = 50,
) -> list[dict[str, object]]:
    """Return tests affected by changes to any of `changed_targets`."""
    affected: list[dict[str, object]] = []
    seen: set[str] = set()
    for target in changed_targets:
        res = find_related_tests(con, target, max_results=max_results)
        for t in res:
            if "result" not in t:
                f = str(t.get("file", ""))
                sym = str(t.get("symbol", ""))
                key = f"{f}:{sym}"
                if key not in seen:
                    seen.add(key)
                    affected.append(t)
    return affected[:max_results]


# ---------------------------------------------------------------------------
# Impact Analysis Engine
# ---------------------------------------------------------------------------


def analyze_impact(
    con: sqlite3.Connection,
    symbol_or_file: str,
    max_depth: int = 3,
    max_results: int = 100,
) -> dict[str, object]:
    """Perform a bounded reverse-graph impact analysis across 5 explicit categories:
    DIRECT, FRAMEWORK, SEMANTIC, DI, and TEST.
    """
    clean_target = symbol_or_file.strip()
    short_name = clean_target.split(".")[-1]
    is_file = "/" in clean_target or clean_target.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))

    direct_callers: list[dict[str, object]] = []
    transitive_callers: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    dependent_modules: list[dict[str, object]] = []
    related_apis: list[dict[str, object]] = []
    related_tests = find_related_tests(con, clean_target, max_results=20)

    # Structured impact items list & 5-category buckets
    impact_items: list[dict[str, object]] = []
    seen_impact: set[tuple[str, str | None, str]] = set()  # (category, source, relationship)

    def add_impact_item(
        source: str,
        target: str | None,
        relationship: str,
        category: str,  # DIRECT | FRAMEWORK | SEMANTIC | DI | TEST
        evidence_class: str,
        reason: str,
        impact_reason: str,
        file_path: str | None,
        start_line: int | None = None,
        end_line: int | None = None,
        rank: int = 5,
        freshness: str = "FRESH",
    ) -> None:
        key = (category, source, relationship)
        if key in seen_impact:
            return
        seen_impact.add(key)
        impact_items.append(
            {
                "source": source,
                "target": target,
                "relationship": relationship,
                "category": category,
                "evidence_class": evidence_class,
                "reason": reason,
                "impact_reason": impact_reason,
                "file": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "rank": rank,
                "freshness": freshness,
            }
        )

    # Check if symbol exists in database
    target_sym = con.execute(
        "SELECT canonical_id, qualified_name, name, path, start_line, end_line FROM symbols "
        "WHERE canonical_id = ? OR qualified_name = ? OR name = ? LIMIT 1",
        (clean_target, clean_target, clean_target),
    ).fetchone()

    target_file = con.execute("SELECT path FROM files WHERE path = ?", (clean_target,)).fetchone()

    # Handle deleted/unknown symbol gracefully
    if not target_sym and not target_file and not is_file:
        add_impact_item(
            source=clean_target,
            target=None,
            relationship="UNKNOWN",
            category="DIRECT",
            evidence_class="UNKNOWN",
            reason="Symbol not found in current index (may be deleted or renamed)",
            impact_reason="deleted_symbol",
            file_path=None,
            rank=8,
            freshness="STALE",
        )

    # 1. Direct callers (DIRECT)
    direct = find_callers(con, clean_target, max_results=max_results)
    for d in direct:
        f_p = d.get("file")
        s_id = d.get("symbol")
        ln = d.get("line")
        direct_callers.append(
            {
                "file": f_p,
                "symbol": s_id,
                "line": ln,
                "relationship": d.get("relationship", "CALLS"),
                "confidence": d.get("confidence", "HIGH"),
                "label": "verified" if d.get("confidence") == "HIGH" else "possible",
                "evidence": d.get("evidence", ""),
            }
        )
        add_impact_item(
            source=str(s_id or f_p),
            target=clean_target,
            relationship="CALLS",
            category="DIRECT",
            evidence_class="AST_VERIFIED",
            reason=f"Direct call: {s_id} calls {clean_target}",
            impact_reason="direct_caller",
            file_path=str(f_p) if f_p else None,
            start_line=int(ln) if ln else None,
            rank=2,
        )

    # 2. Transitive callers (DIRECT, depth 2+)
    if max_depth > 1:
        seen_transitive = {(str(c_dict.get("file")), str(c_dict.get("symbol"))) for c_dict in direct_callers}
        for caller_entry in direct_callers[:15]:
            src_sym = caller_entry.get("symbol") or caller_entry.get("file")
            if src_sym:
                second = find_callers(con, str(src_sym), max_results=10)
                for s in second:
                    key = (str(s.get("file")), str(s.get("symbol")))
                    if key not in seen_transitive:
                        seen_transitive.add(key)
                        transitive_callers.append(
                            {
                                "file": s.get("file"),
                                "symbol": s.get("symbol"),
                                "line": s.get("line"),
                                "relationship": s.get("relationship", "CALLS"),
                                "confidence": s.get("confidence", "LOW"),
                                "label": "possible",
                                "evidence": s.get("evidence", ""),
                            }
                        )
                        add_impact_item(
                            source=str(s.get("symbol") or s.get("file")),
                            target=str(src_sym),
                            relationship="CALLS",
                            category="DIRECT",
                            evidence_class="POSSIBLE",
                            reason=f"Transitive call through {src_sym}",
                            impact_reason="indirect_dependent",
                            file_path=str(s.get("file")) if s.get("file") else None,
                            start_line=int(s["line"]) if s.get("line") else None,
                            rank=7,
                        )

    # 3. Dependencies & Importers (DIRECT)
    if is_file:
        deps = get_dependency_graph(con, clean_target, depth=1, max_results=50)
        for dep_entry in deps:
            dependencies.append(
                {
                    "target": dep_entry.get("target"),
                    "resolved_target": dep_entry.get("resolved_target"),
                    "relationship": "IMPORTS",
                    "label": "verified",
                    "evidence": dep_entry.get("evidence", ""),
                }
            )
        mod_name = clean_target.replace("/", ".").rsplit(".", 1)[0]
        importers = find_importers(con, mod_name, max_results=50)
        for imp in importers:
            dependent_modules.append(
                {
                    "importer": imp.get("importer"),
                    "module": imp.get("module"),
                    "label": "verified",
                    "evidence": imp.get("evidence", ""),
                }
            )
            add_impact_item(
                source=str(imp.get("importer")),
                target=mod_name,
                relationship="IMPORTS",
                category="DIRECT",
                evidence_class="AST_VERIFIED",
                reason=f"Direct import of module '{mod_name}'",
                impact_reason="direct_import",
                file_path=str(imp.get("importer")),
                rank=6,
            )
    else:
        defn = target_sym
        if defn:
            deps = get_dependency_graph(con, defn["path"], depth=1, max_results=50)
            for dep_entry in deps:
                dependencies.append(
                    {
                        "target": dep_entry.get("target"),
                        "resolved_target": dep_entry.get("resolved_target"),
                        "relationship": "IMPORTS",
                        "label": "verified",
                        "evidence": dep_entry.get("evidence", ""),
                    }
                )

    # 4. Related APIs & Framework Routes (FRAMEWORK)
    target_canon = target_sym["canonical_id"] if target_sym else clean_target
    route_rows = con.execute(
        "SELECT endpoint_id, framework, http_method, route_path, handler_canonical_id, file_path, line, evidence "
        "FROM framework_routes WHERE handler_canonical_id = ? OR handler_canonical_id LIKE ? OR handler_name = ?",
        (target_canon, f"%{short_name}%", short_name),
    ).fetchall()
    for rr in route_rows:
        related_apis.append(
            {
                "endpoint_id": rr["endpoint_id"],
                "framework": rr["framework"],
                "http_method": rr["http_method"],
                "route": rr["route_path"],
                "handler": rr["handler_canonical_id"],
                "file": rr["file_path"],
                "line": rr["line"],
                "label": "verified",
                "evidence": rr["evidence"],
            }
        )
        add_impact_item(
            source=rr["endpoint_id"],
            target=rr["handler_canonical_id"],
            relationship="ROUTES_TO",
            category="FRAMEWORK",
            evidence_class="FRAMEWORK_VERIFIED",
            reason=f"Route {rr['route_path']} [{rr['http_method']}] routed to handler",
            impact_reason="route_handler",
            file_path=rr["file_path"],
            start_line=rr["line"],
            rank=3,
        )

    # 5. Semantic Registries & Event Handlers (SEMANTIC)
    sem_rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
        "FROM graph_edges WHERE (target = ? OR target LIKE ?) "
        "AND relationship IN ('REGISTERS', 'EVENT_LISTENER', 'TASK_HANDLER', 'COMMAND_HANDLER', 'DISPATCHES_TO')",
        (target_canon, f"%{short_name}"),
    ).fetchall()
    for sr in sem_rows:
        rel = sr["relationship"]
        imp_reason = (
            "registered_handler"
            if rel == "REGISTERS"
            else ("event_listener" if rel == "EVENT_LISTENER" else ("dispatches_to" if rel == "DISPATCHES_TO" else "semantic_handler"))
        )
        add_impact_item(
            source=sr["source"],
            target=sr["target"],
            relationship=rel,
            category="SEMANTIC",
            evidence_class=sr["evidence_class"] or "FRAMEWORK_VERIFIED",
            reason=sr["reason"] or f"Semantic registration: {sr['source']} {rel} {sr['target']}",
            impact_reason=imp_reason,
            file_path=sr["file"],
            start_line=sr["start_line"],
            rank=5,
        )

    # 6. Dependency Injection & Providers (DI)
    di_rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class, reason "
        "FROM graph_edges WHERE (source = ? OR target = ? OR source LIKE ? OR target LIKE ?) "
        "AND relationship IN ('INJECTS', 'PROVIDES', 'RESOLVES_DEPENDENCY')",
        (target_canon, target_canon, f"%{short_name}", f"%{short_name}"),
    ).fetchall()
    for dr in di_rows:
        rel = dr["relationship"]
        imp_reason = (
            "dependency_injected"
            if rel == "INJECTS"
            else ("dependency_provider" if rel == "PROVIDES" else "resolves_dependency")
        )
        add_impact_item(
            source=dr["source"],
            target=dr["target"],
            relationship=rel,
            category="DI",
            evidence_class=dr["evidence_class"] or "DATAFLOW_VERIFIED",
            reason=dr["reason"] or f"Dependency relationship: {dr['source']} {rel} {dr['target']}",
            impact_reason=imp_reason,
            file_path=dr["file"],
            start_line=dr["start_line"],
            rank=4,
        )

    # 7. Related Tests (TEST)
    for t in related_tests:
        if "result" not in t:
            f_p = t.get("file")
            t_sym = t.get("symbol") or t.get("test_symbol") or f_p
            add_impact_item(
                source=str(t_sym),
                target=clean_target,
                relationship=str(t.get("relationship", "TESTS")),
                category="TEST",
                evidence_class=str(t.get("evidence_class", "AST_VERIFIED")),
                reason=str(t.get("reason", "test_exercises_target")),
                impact_reason="direct_test" if "SYMBOL" in str(t.get("relationship", "")) else "route_test",
                file_path=str(f_p) if f_p else None,
                start_line=int(str(t["line"])) if t.get("line") is not None else None,
                rank=1,
            )

    # Sort impact items deterministically by (rank, category, file, line, source)
    impact_items.sort(
        key=lambda x: (
            int(str(x.get("rank") or 99)),
            str(x.get("category") or ""),
            str(x.get("file") or ""),
            int(str(x.get("start_line") or 0)),
            str(x.get("source") or ""),
        )
    )

    # Group into categories dictionary
    categories: dict[str, list[dict[str, object]]] = {
        "DIRECT": [],
        "FRAMEWORK": [],
        "SEMANTIC": [],
        "DI": [],
        "TEST": [],
    }
    for item in impact_items:
        cat = str(item.get("category", "DIRECT"))
        if cat in categories:
            categories[cat].append(item)

    return {
        "subject": clean_target,
        "direct_callers": direct_callers[:max_results],
        "transitive_callers": transitive_callers[:max_results],
        "dependencies": dependencies,
        "dependent_modules": dependent_modules,
        "related_apis": related_apis,
        "related_tests": related_tests,
        "impact_items": impact_items,
        "categories": categories,
        "label_legend": {
            "verified": "Parser-confirmed relationship with concrete source evidence",
            "inferred": "Structurally inferred relationship",
            "possible": "Heuristic match — not statically verified",
        },
        "note": "Static analysis cannot confirm runtime behavior. Do not assert failure solely from static data.",
    }


# ---------------------------------------------------------------------------
# Backward-Compatible Public Trace / Import / Definition APIs
# ---------------------------------------------------------------------------


def trace_call(
    con: sqlite3.Connection,
    symbol: str,
    max_depth: int = 2,
    callers: bool = True,
    callees: bool = False,
    both: bool = False,
) -> list[dict[str, object]]:
    """Return definition, callers, and/or callees with explicit confidence and relationship labels.

    Hard bound: max_depth is clamped to max 5.
    Explicit labels: CALLER, CALLEE, DEFINES, IMPORTS, HANDLED_BY.
    """
    effective_depth = max(1, min(max_depth, 5))
    if both:
        do_callers = True
        do_callees = True
    elif callees and not callers:
        do_callers = False
        do_callees = True
    elif callers and not callees:
        do_callers = True
        do_callees = False
    elif not callers and not callees:
        do_callers = True
        do_callees = True
    else:
        do_callers = callers
        do_callees = callees

    definitions = con.execute(
        "SELECT canonical_id, qualified_name, path, start_line, end_line FROM symbols "
        "WHERE canonical_id=? OR qualified_name=? OR name=?",
        (symbol, symbol, symbol),
    ).fetchall()

    output: list[dict[str, object]] = []
    seen: set[tuple[str, str, int, str]] = set()

    # 1. Definitions
    for d in definitions:
        key = (d["qualified_name"], d["path"], d["start_line"], "DEFINES")
        if key not in seen:
            seen.add(key)
            output.append(
                {
                    "symbol": d["qualified_name"],
                    "canonical_id": d["canonical_id"],
                    "file": d["path"],
                    "start_line": d["start_line"],
                    "end_line": d["end_line"],
                    "relationship": "DEFINES",
                    "confidence": "HIGH",
                    "evidence": "Parser-extracted symbol definition",
                }
            )

    # 2. Handled-by routes
    try:
        route_rows = con.execute(
            "SELECT endpoint_id, file_path, line FROM framework_routes "
            "WHERE handler_name=? OR handler_canonical_id=?",
            (symbol, symbol),
        ).fetchall()
        for rr in route_rows:
            key = (rr["endpoint_id"], rr["file_path"], rr["line"], "HANDLED_BY")
            if key not in seen:
                seen.add(key)
                output.append(
                    {
                        "symbol": rr["endpoint_id"],
                        "file": rr["file_path"],
                        "start_line": rr["line"],
                        "end_line": rr["line"],
                        "relationship": "HANDLED_BY",
                        "confidence": "HIGH",
                        "evidence": f"Route definition for {rr['endpoint_id']}",
                    }
                )
    except sqlite3.OperationalError:
        pass

    # 3. Callers traversal
    if do_callers:
        current_symbols = [symbol]
        visited_callers: set[str] = set()
        for depth_step in range(effective_depth):
            next_symbols: list[str] = []
            for sym in current_symbols:
                if sym in visited_callers:
                    continue
                visited_callers.add(sym)
                caller_items = find_callers(con, sym, max_results=20)
                for c in caller_items:
                    c_sym = str(c.get("symbol") or "")
                    c_file = str(c.get("file") or "")
                    c_line = int(c.get("start_line") or 1)
                    key = (c_sym, c_file, c_line, "CALLER")
                    if key not in seen:
                        seen.add(key)
                        output.append(
                            {
                                "symbol": c_sym,
                                "file": c_file,
                                "start_line": c_line,
                                "end_line": int(c.get("end_line") or c_line),
                                "relationship": "CALLER",
                                "confidence": str(c.get("confidence", "LOW")),
                                "evidence": str(c.get("evidence", f"Call reference to '{sym}'")),
                                "depth": depth_step + 1,
                            }
                        )
                        if c_sym:
                            next_symbols.append(c_sym)
            current_symbols = next_symbols
            if not current_symbols:
                break

    # 4. Callees traversal
    if do_callees:
        current_symbols = [symbol]
        visited_callees: set[str] = set()
        for depth_step in range(effective_depth):
            next_symbols = []
            for sym in current_symbols:
                if sym in visited_callees:
                    continue
                visited_callees.add(sym)
                callee_items = find_callees(con, sym, max_results=20)
                for c in callee_items:
                    c_sym = str(c.get("qualified_callee") or c.get("callee") or "")
                    c_file = str(c.get("file") or "")
                    c_line = int(c.get("start_line") or c.get("line") or 1)
                    key = (c_sym, c_file, c_line, "CALLEE")
                    if key not in seen:
                        seen.add(key)
                        output.append(
                            {
                                "symbol": c_sym,
                                "file": c_file,
                                "start_line": c_line,
                                "end_line": int(c.get("end_line") or c_line),
                                "relationship": "CALLEE",
                                "confidence": str(c.get("confidence", "LOW")),
                                "evidence": str(c.get("evidence", f"Direct callee of '{sym}'")),
                                "depth": depth_step + 1,
                            }
                        )
                        if c_sym:
                            next_symbols.append(c_sym)
            current_symbols = next_symbols
            if not current_symbols:
                break

    return output


def find_parallel_implementations(
    con: sqlite3.Connection,
    symbol: str,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Discover parallel implementations sharing algorithmic or domain roles."""
    clean = symbol.split(".")[-1]
    row = con.execute(
        "SELECT canonical_id, qualified_name, name, path, kind, parameter_count, return_type, module "
        "FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
        (symbol, symbol, clean),
    ).fetchone()
    if not row:
        return []

    source_path = row["path"]
    source_param_count = row["parameter_count"]
    source_kind = row["kind"]
    source_name = row["name"]
    source_canon = row["canonical_id"]

    results: list[dict[str, Any]] = []
    seen: set[str] = {source_canon, source_name}

    # Strategy A: Check shared callers
    shared_callee_rows = con.execute(
        "SELECT DISTINCT c2.callee, c2.qualified_callee, c2.source_path, s.canonical_id, s.path, s.start_line, s.end_line "
        "FROM calls c1 "
        "JOIN calls c2 ON c1.source_path = c2.source_path "
        "JOIN symbols s ON (s.canonical_id = c2.qualified_callee OR s.name = c2.callee) "
        "WHERE (c1.callee=? OR c1.qualified_callee=?) AND c2.callee != ? "
        "AND s.kind=? "
        "LIMIT ?",
        (source_name, source_canon, source_name, source_kind, max_results),
    ).fetchall()

    for sc in shared_callee_rows:
        canon = sc["canonical_id"]
        if canon in seen:
            continue
        seen.add(canon)
        results.append(
            {
                "symbol": sc["qualified_callee"] or sc["callee"],
                "canonical_id": canon,
                "file": sc["path"],
                "start_line": sc["start_line"],
                "end_line": sc["end_line"],
                "relationship": "PARALLEL_IMPLEMENTATION",
                "confidence": "MEDIUM",
                "evidence": f"Parallel implementation: shared caller context with '{source_name}'",
            }
        )

    # Strategy B: Sibling functions in same file/module with matching parameter count
    if len(results) < max_results and source_param_count is not None and source_param_count > 0:
        sibling_rows = con.execute(
            "SELECT canonical_id, qualified_name, name, path, start_line, end_line "
            "FROM symbols WHERE path=? AND kind=? AND parameter_count=? AND canonical_id != ? "
            "LIMIT ?",
            (source_path, source_kind, source_param_count, source_canon, max_results - len(results)),
        ).fetchall()
        for sib in sibling_rows:
            canon = sib["canonical_id"]
            if canon in seen:
                continue
            seen.add(canon)
            results.append(
                {
                    "symbol": sib["qualified_name"],
                    "canonical_id": canon,
                    "file": sib["path"],
                    "start_line": sib["start_line"],
                    "end_line": sib["end_line"],
                    "relationship": "PARALLEL_IMPLEMENTATION",
                    "confidence": "MEDIUM",
                    "evidence": f"Parallel implementation: sibling {source_kind} with matching signature in {source_path}",
                }
            )

    return results[:max_results]


def get_graph_summary(con: sqlite3.Connection) -> dict[str, object]:
    """Return bounded repository graph summary statistics."""
    node_counts_by_type: dict[str, int] = {}
    for r in con.execute("SELECT kind, count(*) FROM symbols GROUP BY kind").fetchall():
        node_counts_by_type[r[0]] = r[1]

    edge_counts_by_type: dict[str, int] = {
        "IMPORTS": con.execute("SELECT count(*) FROM imports").fetchone()[0],
        "CALLS": con.execute("SELECT count(*) FROM calls").fetchone()[0],
        "EXTENDS": con.execute("SELECT count(*) FROM inheritance").fetchone()[0],
    }
    try:
        edge_counts_by_type["HANDLED_BY"] = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
    except sqlite3.OperationalError:
        pass

    modules = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT module FROM symbols WHERE module != '' ORDER BY module LIMIT 50"
        ).fetchall()
    ]

    dependencies = [
        {"module": r[0], "count": r[1]}
        for r in con.execute(
            "SELECT module, count(*) AS c FROM imports GROUP BY module ORDER BY c DESC LIMIT 20"
        ).fetchall()
    ]

    route_count = 0
    try:
        route_count = con.execute("SELECT count(*) FROM framework_routes").fetchone()[0]
    except sqlite3.OperationalError:
        pass

    test_count = 0
    try:
        test_count = con.execute(
            "SELECT count(*) FROM files WHERE category='TEST' OR path LIKE 'tests/%' OR path LIKE 'test/%'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass

    return {
        "node_counts": node_counts_by_type,
        "edge_counts": edge_counts_by_type,
        "modules": modules,
        "top_dependencies": dependencies,
        "route_count": route_count,
        "test_count": test_count,
        "external_service_count": len([d for d in dependencies if "." not in d["module"] and "/" not in d["module"]]),
        "total_symbols": sum(node_counts_by_type.values()),
        "total_edges": sum(edge_counts_by_type.values()),
    }


def get_focused_graph(
    con: sqlite3.Connection,
    module: str | None = None,
    symbol: str | None = None,
    depth: int = 2,
) -> dict[str, object]:
    """Return bounded focused graph for a module or symbol."""
    bounded_depth = max(1, min(depth, 5))
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    if symbol:
        tr = trace_call(con, symbol, max_depth=bounded_depth, both=True)
        for item in tr[:100]:
            sym_name = str(item.get("symbol") or "")
            if sym_name and sym_name not in seen_nodes:
                seen_nodes.add(sym_name)
                nodes.append({
                    "id": sym_name,
                    "file": item.get("file"),
                    "line": item.get("start_line"),
                    "relationship": item.get("relationship"),
                })
            rel = str(item.get("relationship") or "")
            if rel in ("CALLER", "CALLEE", "HANDLED_BY"):
                src = sym_name if rel == "CALLEE" else symbol
                tgt = symbol if rel == "CALLEE" else sym_name
                edge_key = (src, tgt, rel)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "source": src,
                        "target": tgt,
                        "relationship": rel,
                        "confidence": item.get("confidence", "HIGH"),
                        "evidence": item.get("evidence", ""),
                    })
    elif module:
        rows = con.execute(
            "SELECT canonical_id, qualified_name, kind, path, start_line, end_line "
            "FROM symbols WHERE module=? OR path LIKE ? LIMIT 50",
            (module, f"%{module}%"),
        ).fetchall()
        for r in rows:
            cid = r["canonical_id"]
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                nodes.append({
                    "id": cid,
                    "name": r["qualified_name"],
                    "kind": r["kind"],
                    "file": r["path"],
                    "line": r["start_line"],
                })
        for n in nodes[:30]:
            sym = str(n.get("name") or "")
            callees = find_callees(con, sym, max_results=10)
            for c in callees:
                c_sym = str(c.get("qualified_callee") or c.get("callee") or "")
                if c_sym in seen_nodes:
                    edge_key = (sym, c_sym, "CALLS")
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "source": sym,
                            "target": c_sym,
                            "relationship": "CALLS",
                            "confidence": str(c.get("confidence", "HIGH")),
                            "evidence": str(c.get("evidence", "")),
                        })

    return {
        "module": module,
        "symbol": symbol,
        "depth": bounded_depth,
        "nodes": sorted(nodes, key=lambda n: str(n.get("id"))),
        "edges": sorted(edges, key=lambda e: (str(e.get("source")), str(e.get("target")))),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def import_edges(con: sqlite3.Connection) -> list[GraphEdge]:
    """Return parser-extracted import relationships with evidence metadata."""
    rows = con.execute(
        "SELECT source_path, module, resolved_path, line FROM imports ORDER BY source_path, line"
    ).fetchall()
    return [
        GraphEdge(
            source=r["source_path"],
            target=r["resolved_path"] or r["module"],
            relationship="IMPORTS",
            confidence="HIGH",
            file=r["source_path"],
            start_line=r["line"],
            end_line=r["line"],
            evidence=f"Parser-extracted import '{r['module']}'",
        )
        for r in rows
    ]


def definition_edges(con: sqlite3.Connection, limit: int = 500) -> list[GraphEdge]:
    """Return parser-confirmed definition and containment edges."""
    rows = con.execute(
        "SELECT canonical_id, qualified_name, kind, path, start_line, end_line, parent_symbol_id "
        "FROM symbols ORDER BY path, start_line LIMIT ?",
        (limit,),
    ).fetchall()
    edges: list[GraphEdge] = []
    for r in rows:
        if r["parent_symbol_id"]:
            edges.append(
                GraphEdge(
                    source=r["parent_symbol_id"],
                    target=r["canonical_id"],
                    relationship="CONTAINS",
                    confidence="HIGH",
                    file=r["path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    evidence=f"Containment {r['parent_symbol_id']} -> {r['canonical_id']}",
                )
            )
        else:
            edges.append(
                GraphEdge(
                    source=r["path"],
                    target=r["canonical_id"],
                    relationship="DEFINES",
                    confidence="HIGH",
                    file=r["path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    evidence=f"File {r['path']} defines {r['canonical_id']}",
                )
            )
    return edges
