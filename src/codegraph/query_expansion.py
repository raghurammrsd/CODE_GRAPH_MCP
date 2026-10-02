"""Qualified Query Expansion for CodeGraph MCP v2.1.

Converts raw target terms into precise, explainable search queries.

Key rules:
  1. If a term resolves to a canonical_id, use canonical_id as the search term
  2. If a term resolves to a qualified_name, use qualified_name
  3. If a term matches a route, also expand to the handler symbol
  4. Generic method names MUST be qualified when qualified context exists:
     e.g. "get" → "AdminDashboardView.get" (never bare "get")
  5. Every expansion is recorded as a QueryExpansion with full provenance

Every expansion is source-backed. No fabricated terms.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from codegraph.target_resolver import TargetResolution, TargetType, resolve_target

# ---------------------------------------------------------------------------
# Generic name set — these must never be emitted as bare search terms
# ---------------------------------------------------------------------------

_GENERIC_NAMES: frozenset[str] = frozenset({
    "get", "post", "put", "delete", "patch", "head", "options",
    "run", "call", "start", "stop", "test", "init", "main",
    "handler", "login", "logout", "register", "index", "home",
    "create", "update", "destroy", "show", "list", "detail",
    "load", "save", "close", "open", "reset", "check",
})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueryExpansion:
    original_term: str
    expanded_term: str
    reason: str
    source_symbol: str | None  # canonical_id of the source, if any
    qualification_level: str   # CANONICAL | QUALIFIED | SHORT | LEXICAL | ROUTE
    confidence: str            # HIGH | MEDIUM | LOW


# ---------------------------------------------------------------------------
# Main expansion function
# ---------------------------------------------------------------------------

def expand_query_terms(
    raw_terms: list[str] | tuple[str, ...],
    con: sqlite3.Connection,
    target_resolutions: dict[str, TargetResolution] | None = None,
    max_expansions: int = 8,
) -> list[QueryExpansion]:
    """Expand raw target terms to precise, qualified search queries.

    Args:
        raw_terms: Terms from task_spec.priority_targets or task_spec.targets.
        con: Active SQLite connection to the indexed repository.
        target_resolutions: Pre-computed TargetResolution map (optional).
            If provided, avoids duplicate resolution work.
        max_expansions: Maximum total expansions to emit.

    Returns:
        List of QueryExpansion records, deduplicated by expanded_term.
    """
    expansions: list[QueryExpansion] = []
    seen_expanded: set[str] = set()
    resolutions = target_resolutions or {}

    def _emit(
        original: str,
        expanded: str,
        reason: str,
        source_symbol: str | None,
        level: str,
        confidence: str,
    ) -> None:
        if expanded and expanded not in seen_expanded:
            seen_expanded.add(expanded)
            expansions.append(QueryExpansion(
                original_term=original,
                expanded_term=expanded,
                reason=reason,
                source_symbol=source_symbol,
                qualification_level=level,
                confidence=confidence,
            ))

    for term in raw_terms:
        if len(expansions) >= max_expansions:
            break

        clean = term.strip()
        if not clean or len(clean) < 2:
            continue

        is_generic = clean.lower() in _GENERIC_NAMES

        # Use pre-computed resolution if available, otherwise resolve fresh
        resolution = resolutions.get(clean) or resolve_target(clean, con)

        # ── 1. Canonical ID ───────────────────────────────────────────────
        if resolution.canonical_id and resolution.confidence in ("HIGH", "MEDIUM"):
            _emit(
                clean, resolution.canonical_id,
                f"Resolved canonical ID for '{clean}'",
                resolution.canonical_id,
                "CANONICAL", resolution.confidence,
            )

        # ── 2. Qualified name (if different from canonical_id) ─────────────
        if (
            resolution.qualified_name
            and resolution.qualified_name != resolution.canonical_id
            and resolution.confidence in ("HIGH", "MEDIUM")
        ):
            _emit(
                clean, resolution.qualified_name,
                f"Qualified name resolution for '{clean}'",
                resolution.canonical_id,
                "QUALIFIED", resolution.confidence,
            )

        # ── 3. Route → handler expansion ──────────────────────────────────
        if resolution.target_type == TargetType.API_ENDPOINT:
            route_rows = con.execute(
                "SELECT handler_name, file_path FROM framework_routes "
                "WHERE route_path=? OR endpoint_id=? LIMIT 3",
                (clean, resolution.canonical_id or clean),
            ).fetchall()
            for rr in route_rows:
                handler = rr["handler_name"]
                if handler:
                    _emit(
                        clean, handler,
                        f"Route '{clean}' handler expansion",
                        handler, "ROUTE", "HIGH",
                    )

        # ── 4. Generic names: qualify or suppress ──────────────────────────
        if is_generic:
            # We already emitted the qualified form via resolution above.
            # If resolution didn't find a qualified form, search for one.
            if not resolution.is_resolved():
                # Try to find any symbol whose short name == clean
                qrows = con.execute(
                    "SELECT canonical_id, qualified_name, name FROM symbols "
                    "WHERE name=? ORDER BY kind, path LIMIT 5",
                    (clean,),
                ).fetchall()
                for qr in qrows:
                    qname = qr["qualified_name"]
                    cid = qr["canonical_id"]
                    if qname and "." in qname:
                        # Qualified form exists — emit it, not the bare name
                        _emit(
                            clean, qname,
                            f"Generic name '{clean}' qualified to '{qname}'",
                            cid, "QUALIFIED", "MEDIUM",
                        )
                    # Never emit the bare generic name if qualified form exists
            # If still nothing: skip the bare generic name entirely
            continue  # do NOT fall through to SHORT expansion

        # ── 5. Short name fallback (non-generic) ──────────────────────────
        if not resolution.is_resolved():
            # Use bare term only for non-generic identifiers with reasonable length
            if len(clean) >= 3:
                _emit(
                    clean, clean,
                    f"Lexical short name for unresolved term '{clean}'",
                    None, "LEXICAL", "LOW",
                )
        elif clean not in seen_expanded:
            # Term already resolved but short name wasn't emitted separately
            # — only emit if not generic
            _emit(
                clean, clean,
                f"Short name '{clean}'",
                resolution.canonical_id, "SHORT", "MEDIUM",
            )

    return expansions[:max_expansions]


def get_search_queries(expansions: list[QueryExpansion]) -> list[str]:
    """Extract the deduplicated list of search query strings from expansions."""
    seen: set[str] = set()
    queries: list[str] = []
    for e in expansions:
        if e.expanded_term not in seen:
            seen.add(e.expanded_term)
            queries.append(e.expanded_term)
    return queries
