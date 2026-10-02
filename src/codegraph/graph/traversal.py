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
    short_name = symbol.split(".")[-1]
    results: list[AttrDict] = []
    seen: set[tuple[str, str | None, int]] = set()

    # 1. Resolved CALLS edges from references table
    rows = con.execute(
        "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
        "path, start_line, end_line, evidence, source_hash "
        "FROM 'references' "
        "WHERE relationship='CALLS' AND (target_symbol_id=? OR target_symbol_id LIKE ? OR target_symbol_id LIKE ?) "
        "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
        (symbol, f"%.{symbol}", f"%.{short_name}", max_results),
    ).fetchall()

    for r in rows:
        key = (r["path"], r["source_symbol_id"], r["start_line"])
        if key in seen:
            continue
        seen.add(key)
        st = verify_source_hash(repo, r["path"], r["source_hash"])
        results.append(
            AttrDict(
                file=r["path"],
                path=r["path"],
                symbol=r["source_symbol_id"],
                source_symbol_id=r["source_symbol_id"],
                callee=short_name,
                target_symbol_id=r["target_symbol_id"],
                line=r["start_line"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                relationship="CALLS",
                confidence=r["confidence"] if st == "current" else "LOW",
                evidence=r["evidence"],
                evidence_status=st,
            )
        )

    # 2. Check static calls table (for unresolved or partially resolved calls)
    if len(results) < max_results:
        rem = max_results - len(results)
        call_rows = con.execute(
            "SELECT source_path, callee, qualified_callee, line, confidence, source_symbol_id, resolved_symbol_id "
            "FROM calls WHERE callee=? OR qualified_callee=? OR resolved_symbol_id=? LIMIT ?",
            (short_name, symbol, symbol, rem),
        ).fetchall()

        for cr in call_rows:
            key = (cr["source_path"], cr["source_symbol_id"], cr["line"])
            if key in seen:
                continue
            seen.add(key)
            conf = cr["confidence"] or "LOW"
            rel = "CALLS" if conf in ("HIGH", "MEDIUM") else "POSSIBLE_CALLS"
            results.append(
                AttrDict(
                    file=cr["source_path"],
                    path=cr["source_path"],
                    symbol=cr["source_symbol_id"] or cr["source_path"],
                    source_symbol_id=cr["source_symbol_id"],
                    callee=cr["callee"],
                    qualified_callee=cr["qualified_callee"],
                    line=cr["line"],
                    start_line=cr["line"],
                    end_line=cr["line"],
                    relationship=rel,
                    confidence=conf,
                    evidence=f"Static call site '{cr['callee']}()' in {cr['source_path']}:{cr['line']}",
                )
            )

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
    short_name = symbol.split(".")[-1]
    results: list[AttrDict] = []
    seen: set[tuple[str, str | None, int]] = set()

    # 1. Check resolved references where source_symbol_id matches symbol
    rows = con.execute(
        "SELECT source_symbol_id, target_symbol_id, relationship, confidence, "
        "path, start_line, end_line, evidence, source_hash "
        "FROM 'references' "
        "WHERE (source_symbol_id=? OR source_symbol_id LIKE ? OR source_symbol_id LIKE ?) "
        "AND relationship IN ('CALLS', 'UNRESOLVED_REFERENCE') "
        "ORDER BY confidence = 'HIGH' DESC, path, start_line LIMIT ?",
        (symbol, f"%.{symbol}", f"%.{short_name}", max_results),
    ).fetchall()

    for r in rows:
        key = (r["path"], r["target_symbol_id"], r["start_line"])
        if key in seen:
            continue
        seen.add(key)
        callee_nm = r["target_symbol_id"].split(".")[-1] if r["target_symbol_id"] else "unresolved"
        st = verify_source_hash(repo, r["path"], r["source_hash"])
        results.append(
            AttrDict(
                callee=callee_nm,
                qualified_callee=r["target_symbol_id"],
                target_symbol_id=r["target_symbol_id"],
                source_symbol_id=r["source_symbol_id"],
                file=r["path"],
                path=r["path"],
                line=r["start_line"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                relationship=r["relationship"],
                confidence=r["confidence"] if st == "current" else "LOW",
                evidence=r["evidence"],
                evidence_status=st,
            )
        )

    # 2. Check chunks / calls table if references did not contain calls
    if not results:
        chunk = con.execute(
            "SELECT path, start_line, end_line, content FROM chunks "
            "WHERE symbol=? OR symbol LIKE ? LIMIT 1",
            (symbol, f"%.{symbol}"),
        ).fetchone()
        if chunk:
            call_rows = con.execute(
                "SELECT callee, qualified_callee, line, confidence FROM calls "
                "WHERE source_path=? AND line >= ? AND line <= ? LIMIT ?",
                (chunk["path"], chunk["start_line"], chunk["end_line"], max_results),
            ).fetchall()
            for cr in call_rows:
                results.append(
                    AttrDict(
                        callee=cr["callee"],
                        qualified_callee=cr["qualified_callee"],
                        line=cr["line"],
                        start_line=cr["line"],
                        end_line=cr["line"],
                        file=chunk["path"],
                        path=chunk["path"],
                        relationship="CALLS" if cr["confidence"] in ("HIGH", "MEDIUM") else "POSSIBLE_CALLS",
                        confidence=cr["confidence"] or "LOW",
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
    """Find test files statically linked to a symbol or file path with verified provenance."""
    gov = get_global_governor()
    max_results = min(max_results, gov.policy.max_graph_nodes_per_query)
    gen = index_generation(con)
    cache = get_graph_cache()
    cache_key = (gen, "related_tests", symbol_or_path, max_results)
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, list):
        return cached

    short = symbol_or_path.split(".")[-1]
    module_name = (
        symbol_or_path.replace("/", ".").rsplit(".", 1)[0]
        if "." in symbol_or_path
        else symbol_or_path
    )
    tests: list[dict[str, object]] = []
    seen: set[str] = set()

    # 1. VERIFIED: Tests that directly call or reference the symbol in 'references' table
    ref_rows = con.execute(
        "SELECT path, source_symbol_id, start_line, evidence FROM 'references' "
        "WHERE (target_symbol_id=? OR target_symbol_id LIKE ? OR target_symbol_id=?) "
        "AND relationship IN ('CALLS', 'TESTS') LIMIT ?",
        (symbol_or_path, f"%.{short}", short, max_results),
    ).fetchall()
    for row in ref_rows:
        if _TEST_FILE_RE.search(row["path"]) and row["path"] not in seen:
            seen.add(row["path"])
            tests.append(
                {
                    "file": row["path"],
                    "symbol": row["source_symbol_id"],
                    "relationship": "TESTS_SYMBOL",
                    "classification": "VERIFIED_TEST",
                    "confidence": "HIGH",
                    "evidence": f"Test verifies symbol: {row['evidence']}",
                }
            )

    # 2. VERIFIED: Tests that import the containing module
    imp_rows = con.execute(
        "SELECT DISTINCT source_path FROM imports "
        "WHERE module=? OR resolved_module=? OR module LIKE ? LIMIT ?",
        (module_name, module_name, f"%{short}%", max_results),
    ).fetchall()
    for row in imp_rows:
        p = row["source_path"]
        if _TEST_FILE_RE.search(p) and p not in seen:
            seen.add(p)
            tests.append(
                {
                    "file": p,
                    "symbol": None,
                    "relationship": "TEST_IMPORTS_MODULE",
                    "classification": "VERIFIED_TEST",
                    "confidence": "HIGH",
                    "evidence": f"Test file imports module '{module_name}'",
                }
            )

    # 3. POSSIBLE: Test symbols whose name contains the target name
    sym_rows = con.execute(
        "SELECT qualified_name, path, start_line FROM symbols "
        "WHERE name LIKE ? AND path LIKE ? LIMIT ?",
        (f"%{short}%", "%test%", max_results),
    ).fetchall()
    for row in sym_rows:
        if _TEST_FILE_RE.search(row["path"]) and row["path"] not in seen:
            seen.add(row["path"])
            tests.append(
                {
                    "file": row["path"],
                    "symbol": row["qualified_name"],
                    "start_line": row["start_line"],
                    "relationship": "TEST_COVERS_SYMBOL",
                    "classification": "POSSIBLE_TEST",
                    "confidence": "MEDIUM",
                    "evidence": f"Test name contains '{short}'",
                }
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
                if f not in seen:
                    seen.add(f)
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
    """Perform a bounded reverse-graph impact analysis for a symbol or file."""
    short_name = symbol_or_file.split(".")[-1]
    is_file = "/" in symbol_or_file or symbol_or_file.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))

    direct_callers: list[dict[str, object]] = []
    transitive_callers: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    dependent_modules: list[dict[str, object]] = []
    related_apis: list[dict[str, object]] = []
    related_tests = find_related_tests(con, symbol_or_file, max_results=20)

    # 1. Direct callers
    direct = find_callers(con, symbol_or_file, max_results=max_results)
    for d in direct:
        direct_callers.append(
            {
                "file": d.get("file"),
                "symbol": d.get("symbol"),
                "line": d.get("line"),
                "relationship": d.get("relationship", "CALLS"),
                "confidence": d.get("confidence", "HIGH"),
                "label": "verified" if d.get("confidence") == "HIGH" else "possible",
                "evidence": d.get("evidence", ""),
            }
        )

    # 2. Transitive callers
    if max_depth > 1:
        seen_files = {str(c_dict.get("file")) for c_dict in direct_callers}
        for caller_entry in direct_callers[:15]:
            src_sym = caller_entry.get("symbol") or caller_entry.get("file")
            if src_sym:
                second = find_callers(con, str(src_sym), max_results=10)
                for s in second:
                    if str(s.get("file")) not in seen_files:
                        seen_files.add(str(s.get("file")))
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

    # 3. Dependencies
    if is_file:
        deps = get_dependency_graph(con, symbol_or_file, depth=1, max_results=50)
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
        mod_name = symbol_or_file.replace("/", ".").rsplit(".", 1)[0]
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
    else:
        defn = con.execute(
            "SELECT path FROM symbols WHERE canonical_id=? OR qualified_name=? OR name=? LIMIT 1",
            (symbol_or_file, symbol_or_file, short_name),
        ).fetchone()
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

    # 4. Related APIs (Framework endpoints routing to or matching this handler)
    route_rows = con.execute(
        "SELECT endpoint_id, framework, http_method, route_path, handler_canonical_id, file_path, line, evidence "
        "FROM framework_routes WHERE handler_canonical_id LIKE ? OR handler_name=?",
        (f"%{short_name}%", short_name),
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

    return {
        "subject": symbol_or_file,
        "direct_callers": direct_callers[:max_results],
        "transitive_callers": transitive_callers[:max_results],
        "dependencies": dependencies,
        "dependent_modules": dependent_modules,
        "related_apis": related_apis,
        "related_tests": related_tests,
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
