"""Lexical search using SQLite FTS5.

Retrieval is lexical + path/symbol ranking.  No semantic embeddings.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from codegraph.errors import SecurityError
from codegraph.indexing.classifier import (
    FileCategory,
    classify_file,
    is_ignored_by_codegraphignore,
    load_codegraphignore,
)
from codegraph.indexing.scanner import (
    IGNORED_DIRS,
    _gitignore_patterns,
    _ignored_by_gitignore,
    is_binary,
)
from codegraph.security import (
    DEFAULT_MAX_READ_BYTES,
    contains_private_key,
    is_sensitive_path,
    redact_secrets,
    safe_path,
)

_READABLE_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".html",
    ".htm",
    ".jinja",
    ".jinja2",
    ".j2",
    ".ejs",
    ".hbs",
    ".svelte",
    ".vue",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".css",
    ".scss",
    ".less",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".md",
    ".rst",
    ".txt",
    ".sql",
    ".prisma",
    ".sh",
    ".bash",
    ".zsh",
    ".graphql",
    ".proto",
})

_READABLE_TEXT_FILENAMES: frozenset[str] = frozenset({
    "dockerfile",
    "makefile",
    "procfile",
    "gemfile",
    "cmakelists.txt",
    "requirements.txt",
})


@dataclass(frozen=True)
class SearchResult:
    file: str
    symbol: str | None
    start_line: int
    end_line: int
    score: float
    reason: str
    snippet: str
    path: str = ""
    line: int = 0
    matched_text: str = ""
    category: str = "SOURCE"
    file_category: str = "SOURCE"

    def __post_init__(self) -> None:
        if not self.path:
            object.__setattr__(self, "path", self.file)
        if not self.line:
            object.__setattr__(self, "line", self.start_line)
        if not self.matched_text and self.snippet:
            lines = [ln.strip() for ln in self.snippet.splitlines() if ln.strip()]
            object.__setattr__(self, "matched_text", (lines[0][:300] if lines else ""))
        if not self.file_category:
            object.__setattr__(self, "file_category", self.category)

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


def _resolve_repository_from_con(
    con: sqlite3.Connection,
    repository: Path | None = None,
) -> Path | None:
    """Resolve the repository root path from explicit argument, metadata table, or database file path."""
    if repository is not None:
        try:
            resolved = repository.resolve(strict=True)
            if resolved.is_dir():
                return resolved
        except OSError:
            pass
    try:
        row = con.execute("SELECT value FROM metadata WHERE key='repository'").fetchone()
        if row and row[0]:
            cand = Path(str(row[0])).resolve(strict=True)
            if cand.is_dir():
                return cand
    except Exception:
        pass
    try:
        for r in con.execute("PRAGMA database_list").fetchall():
            if r[1] == "main" and r[2]:
                db_path = Path(str(r[2])).resolve(strict=True)
                if db_path.parent.is_dir():
                    return db_path.parent
    except Exception:
        pass
    return None


def _find_best_line_in_chunk(
    content: str,
    chunk_start_line: int,
    clean_query: str,
    terms: list[str],
) -> tuple[int, str, bool]:
    """Locate the specific 1-indexed line and matched text within a chunk."""
    lines = content.splitlines()
    if not lines:
        return chunk_start_line, "", False

    clean_q_lower = clean_query.lower()
    if clean_query:
        for idx, line in enumerate(lines):
            if clean_query in line:
                return chunk_start_line + idx, line.strip()[:300], True
        for idx, line in enumerate(lines):
            if clean_q_lower in line.lower():
                return chunk_start_line + idx, line.strip()[:300], True

    if terms:
        best_idx = 0
        best_hits = 0
        terms_lower = [t.lower() for t in terms]
        for idx, line in enumerate(lines):
            ll = line.lower()
            hits = sum(1 for t in terms_lower if t in ll)
            if hits > best_hits:
                best_hits = hits
                best_idx = idx
        if best_hits > 0:
            return chunk_start_line + best_idx, lines[best_idx].strip()[:300], False

    return chunk_start_line, lines[0].strip()[:300], False


def _search_repository_text_files(
    con: sqlite3.Connection,
    repo_root: Path,
    query: str,
    terms: list[str],
    excluded_categories: set[str],
    include_vendor: bool = False,
    include_build_artifacts: bool = False,
    max_file_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> list[SearchResult]:
    """Scan readable repository text files (.py, .html, .jinja, .js, .ts, .css, .json, .yaml, .md, etc.)
    for literal and lexical matches without polluting the semantic graph.
    """
    clean_q = query.strip()
    if not clean_q:
        return []
    clean_q_lower = clean_q.lower()
    terms_lower = [t.lower() for t in terms]

    gitignore = _gitignore_patterns(repo_root)
    codegraphignore = load_codegraphignore(repo_root)

    # Preload symbol spans by path so hits inside indexed files can optionally attach enclosing symbol name
    symbols_by_path: dict[str, list[tuple[int, int, str]]] = {}
    try:
        for srow in con.execute(
            "SELECT path, start_line, end_line, qualified_name FROM symbols ORDER BY path, start_line"
        ).fetchall():
            symbols_by_path.setdefault(str(srow["path"]), []).append(
                (int(srow["start_line"]), int(srow["end_line"]), str(srow["qualified_name"]))
            )
    except Exception:
        pass

    skip_dirs = set(IGNORED_DIRS)
    if include_vendor:
        skip_dirs -= {"node_modules", "vendor", ".venv", "venv"}
    if include_build_artifacts:
        skip_dirs -= {"dist", "build"}

    hits: list[SearchResult] = []

    for directory, dirs, files in os.walk(repo_root, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs
            if d not in skip_dirs and not d.startswith(".codegraph")
        )
        for filename in sorted(files):
            if filename.startswith(".codegraph"):
                continue
            absolute = Path(directory) / filename
            try:
                rel_unresolved = absolute.relative_to(repo_root)
            except ValueError:
                continue

            try:
                resolved = safe_path(repo_root, rel_unresolved)
            except SecurityError:
                continue

            try:
                relative = resolved.relative_to(repo_root)
            except ValueError:
                continue

            rel_posix = relative.as_posix()
            if is_sensitive_path(relative):
                continue

            suffix_lower = relative.suffix.lower()
            name_lower = relative.name.lower()
            if suffix_lower not in _READABLE_TEXT_EXTENSIONS and name_lower not in _READABLE_TEXT_FILENAMES:
                continue

            try:
                if not resolved.is_file():
                    continue
                st_size = resolved.stat().st_size
                if st_size == 0 or st_size > max_file_bytes:
                    continue
                if _ignored_by_gitignore(relative, gitignore) or is_ignored_by_codegraphignore(
                    relative, codegraphignore
                ):
                    continue
                if is_binary(resolved):
                    continue
                raw_content = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if contains_private_key(raw_content):
                continue

            content = redact_secrets(raw_content)
            cat_enum = classify_file(relative, content)
            cat_str = cat_enum.value
            if cat_str in excluded_categories:
                continue
            if cat_enum == FileCategory.BINARY:
                continue

            content_lower = content.lower()
            has_substring = clean_q_lower in content_lower
            has_all_terms = bool(terms_lower and len(terms_lower) >= 2 and all(t in content_lower for t in terms_lower))
            if not has_substring and not has_all_terms:
                continue

            lines = content.splitlines()
            path_bonus = 0.05 if (
                clean_q_lower in rel_posix.lower()
                or any(t in rel_posix.lower() for t in terms_lower)
            ) else 0.0

            file_spans = symbols_by_path.get(rel_posix, [])
            file_match_count = 0

            for idx, raw_line in enumerate(lines):
                line_lower = raw_line.lower()
                if clean_q in raw_line:
                    base_score = 0.92
                    reason = "exact literal match"
                elif clean_q_lower in line_lower:
                    base_score = 0.88
                    reason = "literal match"
                elif terms_lower and len(terms_lower) >= 2 and all(t in line_lower for t in terms_lower):
                    base_score = 0.78
                    reason = "lexical line match"
                else:
                    continue

                line_no = idx + 1
                enclosing_sym: str | None = None
                for s_start, s_end, s_qname in file_spans:
                    if s_start <= line_no <= s_end:
                        enclosing_sym = s_qname

                sym_bonus = 0.03 if (
                    enclosing_sym
                    and (
                        clean_q_lower in enclosing_sym.lower()
                        or any(t in enclosing_sym.lower() for t in terms_lower)
                    )
                ) else 0.0
                if sym_bonus > 0:
                    reason += ", symbol match"
                if path_bonus > 0:
                    reason += ", path match"

                score = round(min(1.0, base_score + path_bonus + sym_bonus), 2)
                win_start = max(1, line_no - 2)
                win_end = min(len(lines), line_no + 2)
                snippet = redact_secrets("\n".join(lines[win_start - 1 : win_end])[:900])
                matched_text = redact_secrets(raw_line.strip()[:300])

                hits.append(
                    SearchResult(
                        file=rel_posix,
                        symbol=enclosing_sym,
                        start_line=win_start,
                        end_line=win_end,
                        score=score,
                        reason=reason,
                        snippet=snippet,
                        path=rel_posix,
                        line=line_no,
                        matched_text=matched_text,
                        category=cat_str,
                        file_category=cat_str,
                    )
                )
                file_match_count += 1
                if file_match_count >= 5:
                    break

    return hits


def search(
    con: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    include_generated: bool = False,
    include_vendor: bool = False,
    include_bundles: bool = False,
    include_build_artifacts: bool = False,
    repository: Path | None = None,
    include_text_files: bool = True,
) -> list[SearchResult]:
    clean_query = query.strip()
    if not clean_query:
        return []

    terms = _safe_fts5_terms(clean_query)

    # Determine excluded categories
    excluded: list[str] = ["BINARY"]
    if not include_generated:
        excluded.append("GENERATED")
    if not include_vendor:
        excluded.append("VENDOR")
    if not include_bundles:
        excluded.extend(["BUNDLE", "MINIFIED"])
    if not include_build_artifacts:
        excluded.append("BUILD_ARTIFACT")

    rows: list[sqlite3.Row] = []
    if terms:
        clauses = " OR ".join(terms)
        try:
            if not excluded:
                rows = con.execute(
                    "SELECT c.path, c.symbol, c.start_line, c.end_line, c.content, "
                    "f.category AS category, bm25(chunks_fts) AS rank "
                    "FROM chunks_fts "
                    "JOIN chunks c ON c.id = chunks_fts.rowid "
                    "LEFT JOIN files f ON f.path = c.path "
                    "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                    (clauses, top_k * 3),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in excluded)
                rows = con.execute(
                    "SELECT c.path, c.symbol, c.start_line, c.end_line, c.content, "
                    "f.category AS category, bm25(chunks_fts) AS rank "
                    "FROM chunks_fts "
                    "JOIN chunks c ON c.id = chunks_fts.rowid "
                    "LEFT JOIN files f ON f.path = c.path "
                    f"WHERE chunks_fts MATCH ? AND (f.category IS NULL OR f.category NOT IN ({placeholders})) "
                    "ORDER BY rank LIMIT ?",
                    (clauses, *excluded, top_k * 3),
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
                rows = []

    results: list[SearchResult] = []
    for row in rows:
        rel_path = str(row["path"])
        if is_sensitive_path(rel_path):
            continue
        path_bonus = 1.0 if any(t.lower() in rel_path.lower() for t in terms) else 0.0
        symbol_bonus = (
            1.0
            if row["symbol"] and any(t.lower() in str(row["symbol"]).lower() for t in terms)
            else 0.0
        )
        # Exact symbol match (highest bonus)
        exact_bonus = (
            0.5
            if row["symbol"] and any(
                t.lower() == str(row["symbol"]).lower()
                or t.lower() == str(row["symbol"]).split(".")[-1].lower()
                for t in terms
            )
            else 0.0
        )
        content_str = redact_secrets(str(row["content"]))
        if (
            clean_query.lower() not in content_str.lower()
            and not any(t.lower() in content_str.lower() for t in terms)
            and not path_bonus
            and not symbol_bonus
        ):
            continue
        start_ln = int(row["start_line"])
        end_ln = int(row["end_line"])
        hit_line, matched_text, has_literal = _find_best_line_in_chunk(
            content_str, start_ln, clean_query, terms
        )
        matched_text = redact_secrets(matched_text)
        literal_bonus = 0.15 if has_literal else 0.0
        score = round(
            min(1.0, 0.3 + path_bonus * 0.15 + symbol_bonus * 0.2 + exact_bonus * 0.35 + literal_bonus),
            2,
        )
        reason = "exact literal match" if (clean_query in content_str) else (
            "literal match" if has_literal else "lexical match"
        )
        if symbol_bonus:
            reason += ", symbol match"
        if path_bonus:
            reason += ", path match"
        snippet = redact_secrets(content_str[:900])
        row_keys = row.keys() if hasattr(row, "keys") else []
        cat_val = str(row["category"]) if ("category" in row_keys and row["category"]) else classify_file(rel_path).value
        results.append(
            SearchResult(
                file=rel_path,
                symbol=row["symbol"],
                start_line=start_ln,
                end_line=end_ln,
                score=score,
                reason=reason,
                snippet=snippet,
                path=rel_path,
                line=hit_line,
                matched_text=matched_text,
                category=cat_val,
                file_category=cat_val,
            )
        )

    if include_text_files:
        repo_root = _resolve_repository_from_con(con, repository=repository)
        if repo_root is not None:
            text_hits = _search_repository_text_files(
                con=con,
                repo_root=repo_root,
                query=clean_query,
                terms=terms,
                excluded_categories=set(excluded),
                include_vendor=include_vendor,
                include_build_artifacts=include_build_artifacts,
            )
            for th in text_hits:
                covered = False
                for idx, existing in enumerate(results):
                    if (
                        existing.file == th.file
                        and existing.start_line <= th.line <= existing.end_line
                    ):
                        covered = True
                        if th.score > existing.score:
                            results[idx] = SearchResult(
                                file=existing.file,
                                symbol=existing.symbol or th.symbol,
                                start_line=existing.start_line,
                                end_line=existing.end_line,
                                score=th.score,
                                reason=th.reason,
                                snippet=existing.snippet,
                                path=existing.path,
                                line=th.line,
                                matched_text=th.matched_text,
                                category=existing.category,
                                file_category=existing.file_category,
                            )
                        break
                if not covered:
                    results.append(th)

    # Deterministic ordering: (-score, path, line, start_line)
    results.sort(key=lambda r: (-r.score, r.path, r.line, r.start_line))
    return results[:top_k]


def search_lexical(con: sqlite3.Connection, query: str, top_k: int = 10) -> list[SearchResult]:
    """Lexical FTS5 search (wrapper around search)."""
    return search(con, query, top_k=top_k)


def search_code(
    con: sqlite3.Connection,
    query: str,
    repo_path: Path | None = None,
    repository: Path | None = None,
    path_filter: str | None = None,
    file_types: list[str] | tuple[str, ...] | None = None,
    include_tests: bool = True,
    include_configs: bool = True,
    max_results: int = 20,
    top_k: int | None = None,
    include_generated: bool = False,
    include_vendor: bool = False,
    include_bundles: bool = False,
    include_build_artifacts: bool = False,
) -> list[dict[str, object]]:
    """Deterministic repository text search across code, templates, UI files, configs, and docs.

    Never creates or emits semantic graph relationships.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    effective_limit = top_k if top_k is not None else max_results
    if effective_limit <= 0:
        return []

    effective_repo = repo_path if repo_path is not None else repository
    raw_hits = search(
        con,
        clean_query,
        top_k=max(effective_limit * 5, 100),
        include_generated=include_generated,
        include_vendor=include_vendor,
        include_bundles=include_bundles,
        include_build_artifacts=include_build_artifacts,
        repository=effective_repo,
        include_text_files=True,
    )

    norm_path_filter = path_filter.strip().lower() if path_filter and path_filter.strip() else None
    norm_types: set[str] | None = None
    if file_types:
        cleaned_types = {ft.strip().lower().lstrip(".") for ft in file_types if ft and ft.strip()}
        if cleaned_types:
            norm_types = cleaned_types

    config_exts = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}
    filtered: list[dict[str, object]] = []

    for item in raw_hits:
        rel_path = item.path or item.file
        if is_sensitive_path(rel_path):
            continue
        p_obj = Path(rel_path)
        ext_no_dot = p_obj.suffix.lower().lstrip(".")
        cat_upper = (item.category or item.file_category or "SOURCE").upper()

        if norm_path_filter and norm_path_filter not in rel_path.lower():
            continue
        if norm_types is not None and ext_no_dot not in norm_types:
            continue
        if not include_tests:
            is_test_file = (
                cat_upper == "TEST"
                or "tests" in p_obj.parts
                or p_obj.name.startswith("test_")
                or p_obj.name.endswith("_test.py")
            )
            if is_test_file:
                continue
        if not include_configs:
            is_config_file = cat_upper == "CONFIG" or p_obj.suffix.lower() in config_exts
            if is_config_file:
                continue

        d = item.as_dict()
        # Add match_type for schema clarity
        reason_str = str(d.get("reason", ""))
        if "exact literal" in reason_str:
            d["match_type"] = "exact"
        elif "literal" in reason_str:
            d["match_type"] = "case_insensitive"
        else:
            d["match_type"] = "token"
        filtered.append(d)
        if len(filtered) >= effective_limit:
            break

    return filtered



def _fetch_snippet(
    con: sqlite3.Connection, path: str, start: int, end: int, symbol: str | None = None
) -> str:
    try:
        row = con.execute(
            "SELECT content FROM chunks WHERE path=? AND start_line<=? AND end_line>=? LIMIT 1",
            (path, start, end),
        ).fetchone()
        if row and row["content"]:
            return redact_secrets(str(row["content"])[:900])
        if symbol:
            row = con.execute(
                "SELECT content FROM chunks WHERE symbol=? LIMIT 1", (symbol,)
            ).fetchone()
            if row and row["content"]:
                return redact_secrets(str(row["content"])[:900])
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
