"""First-class Target Resolver for CodeGraph MCP v2.1.

Resolves raw user-supplied target strings (symbol names, routes, file paths,
class.method forms) against the indexed repository with an explicit,
ordered resolution strategy.

Resolution order:
  1. Exact canonical_id match
  2. Exact qualified_name match
  3. Exact endpoint / route match (route_path or endpoint_id)
  4. Module + symbol form (mod.sym → resolve module, then symbol)
  5. Class.method form (explicit dot-split + join lookup)
  6. Exact filename match
  7. Short name (name = raw) — MEDIUM if unique, AMBIGUOUS if multiple
  8. No match → UNKNOWN

Every resolution is source-backed: it only returns what is actually in the
index. It never fabricates relationships.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TargetType(StrEnum):
    FILE = "FILE"
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    API = "API"
    API_ENDPOINT = "API_ENDPOINT"
    TEST = "TEST"
    TYPE = "TYPE"
    CONFIG = "CONFIG"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    UNKNOWN = "UNKNOWN"


class ResolutionMethod(StrEnum):
    CANONICAL_ID = "CANONICAL_ID"
    EXACT_QUALIFIED = "EXACT_QUALIFIED"
    ROUTE_MATCH = "ROUTE_MATCH"
    MODULE_SYMBOL = "MODULE_SYMBOL"
    CLASS_METHOD = "CLASS_METHOD"
    FILENAME = "FILENAME"
    LEXICAL = "LEXICAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

_KIND_TO_TARGET_TYPE: dict[str, TargetType] = {
    "class": TargetType.CLASS,
    "function": TargetType.FUNCTION,
    "method": TargetType.METHOD,
    "module": TargetType.MODULE,
    "type": TargetType.TYPE,
    "test": TargetType.TEST,
    "config": TargetType.CONFIG,
    "file": TargetType.FILE,
}


def _kind_to_type(kind: str | None) -> TargetType:
    if not kind:
        return TargetType.UNKNOWN
    return _KIND_TO_TARGET_TYPE.get(kind.lower().strip(), TargetType.UNKNOWN)


@dataclass(frozen=True)
class TargetResolution:
    schema_version: str
    raw_target: str
    target_type: TargetType
    canonical_id: str | None
    qualified_name: str | None
    file_path: str | None
    line: int | None
    confidence: str  # HIGH | MEDIUM | LOW | UNKNOWN
    resolution_method: ResolutionMethod
    alternatives: tuple[dict[str, object], ...]  # other possible resolutions
    ambiguity_state: str  # CLEAR | ASSUMED | AMBIGUOUS | CONFLICT | UNKNOWN
    evidence_ids: tuple[str, ...]  # canonical_ids of evidence sources

    def is_resolved(self) -> bool:
        return self.confidence in ("HIGH", "MEDIUM") and self.canonical_id is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "raw_target": self.raw_target,
            "target_type": self.target_type.value,
            "canonical_id": self.canonical_id,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "line": self.line,
            "confidence": self.confidence,
            "resolution_method": self.resolution_method.value,
            "alternatives": list(self.alternatives),
            "ambiguity_state": self.ambiguity_state,
            "evidence_ids": list(self.evidence_ids),
        }


_SCHEMA_VERSION = "2.1"

# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

_SYMBOL_SELECT = (
    "SELECT canonical_id, qualified_name, name, kind, path, start_line "
    "FROM symbols"
)


def _row_to_resolution(
    row: sqlite3.Row,
    raw: str,
    method: ResolutionMethod,
    ambiguity_state: str = "CLEAR",
    confidence: str = "HIGH",
    alternatives: tuple[dict[str, object], ...] = (),
) -> TargetResolution:
    return TargetResolution(
        schema_version=_SCHEMA_VERSION,
        raw_target=raw,
        target_type=_kind_to_type(row["kind"]),
        canonical_id=row["canonical_id"],
        qualified_name=row["qualified_name"],
        file_path=row["path"],
        line=row["start_line"],
        confidence=confidence,
        resolution_method=method,
        alternatives=alternatives,
        ambiguity_state=ambiguity_state,
        evidence_ids=(row["canonical_id"],),
    )


def resolve_target(raw: str, con: sqlite3.Connection) -> TargetResolution:
    """Resolve a single raw target string against the indexed repository.

    Resolution order:
      1. Exact canonical_id
      2. Exact qualified_name
      3. Route/endpoint exact match
      4. module.symbol resolution
      5. Class.method resolution
      6. Exact filename
      7. Short name (name=raw)
      8. UNKNOWN fallback
    """
    clean = raw.strip()
    if not clean:
        return TargetResolution(
            schema_version=_SCHEMA_VERSION,
            raw_target=raw,
            target_type=TargetType.UNKNOWN,
            canonical_id=None,
            qualified_name=None,
            file_path=None,
            line=None,
            confidence="UNKNOWN",
            resolution_method=ResolutionMethod.UNKNOWN,
            alternatives=(),
            ambiguity_state="UNKNOWN",
            evidence_ids=(),
        )

    # ── 1. Exact canonical_id ────────────────────────────────────────────────
    row = con.execute(
        _SYMBOL_SELECT + " WHERE canonical_id=? LIMIT 1", (clean,)
    ).fetchone()
    if row:
        return _row_to_resolution(row, clean, ResolutionMethod.CANONICAL_ID)

    # ── 2. Exact qualified_name ──────────────────────────────────────────────
    row = con.execute(
        _SYMBOL_SELECT + " WHERE qualified_name=? LIMIT 1", (clean,)
    ).fetchone()
    if row:
        return _row_to_resolution(row, clean, ResolutionMethod.EXACT_QUALIFIED)

    # ── 3. Endpoint / route ──────────────────────────────────────────────────
    try:
        route_row = con.execute(
            "SELECT route_path, http_method, handler_name, file_path, line, endpoint_id "
            "FROM framework_routes "
            "WHERE route_path=? OR endpoint_id=? LIMIT 1",
            (clean, clean),
        ).fetchone()
        if route_row:
            return TargetResolution(
                schema_version=_SCHEMA_VERSION,
                raw_target=raw,
                target_type=TargetType.API_ENDPOINT,
                canonical_id=route_row["endpoint_id"] or f"{route_row['http_method']} {route_row['route_path']}",
                qualified_name=route_row["route_path"],
                file_path=route_row["file_path"],
                line=route_row["line"],
                confidence="HIGH",
                resolution_method=ResolutionMethod.ROUTE_MATCH,
                alternatives=(),
                ambiguity_state="CLEAR",
                evidence_ids=(route_row["endpoint_id"] or clean,),
            )
    except sqlite3.OperationalError:
        pass

    # ── 4. Module.symbol (e.g. "src.services.auth_service.AuthService") ─────
    if "." in clean:
        parts = clean.rsplit(".", 1)
        module_part, sym_part = parts[0], parts[1]
        row = con.execute(
            _SYMBOL_SELECT
            + " WHERE (module=? OR module LIKE ?) AND (name=? OR qualified_name=?) "
            "ORDER BY path, start_line LIMIT 1",
            (module_part, f"%.{module_part}", sym_part, clean),
        ).fetchone()
        if row:
            return _row_to_resolution(row, clean, ResolutionMethod.MODULE_SYMBOL)

    # ── 5. Class.method (e.g. "AdminDashboardView.get") ─────────────────────
    if "." in clean:
        class_part, method_part = clean.rsplit(".", 1)
        # Look for parent class, then find method inside it
        class_row = con.execute(
            _SYMBOL_SELECT + " WHERE (name=? OR qualified_name LIKE ?) AND kind='class' LIMIT 1",
            (class_part, f"%.{class_part}"),
        ).fetchone()
        if class_row:
            method_row = con.execute(
                _SYMBOL_SELECT
                + " WHERE name=? AND parent_symbol_id=? LIMIT 1",
                (method_part, class_row["canonical_id"]),
            ).fetchone()
            if method_row:
                return _row_to_resolution(method_row, clean, ResolutionMethod.CLASS_METHOD)
            # fallback: qualified_name contains the class.method pattern
            qrow = con.execute(
                _SYMBOL_SELECT + " WHERE qualified_name LIKE ? LIMIT 1",
                (f"%.{clean}",),
            ).fetchone()
            if qrow:
                return _row_to_resolution(qrow, clean, ResolutionMethod.CLASS_METHOD)

    # ── 6. Exact filename ────────────────────────────────────────────────────
    try:
        file_row = con.execute(
            "SELECT path FROM files WHERE path=? OR path LIKE ? LIMIT 1",
            (clean, f"%/{clean}"),
        ).fetchone()
        if file_row:
            return TargetResolution(
                schema_version=_SCHEMA_VERSION,
                raw_target=raw,
                target_type=TargetType.FILE,
                canonical_id=file_row["path"],
                qualified_name=file_row["path"],
                file_path=file_row["path"],
                line=None,
                confidence="HIGH",
                resolution_method=ResolutionMethod.FILENAME,
                alternatives=(),
                ambiguity_state="CLEAR",
                evidence_ids=(file_row["path"],),
            )
    except sqlite3.OperationalError:
        pass

    # ── 7. Short name (name = clean) — ambiguity-aware ──────────────────────
    short_rows = con.execute(
        _SYMBOL_SELECT + " WHERE name=? ORDER BY kind, path, start_line LIMIT 10",
        (clean,),
    ).fetchall()
    if len(short_rows) == 1:
        return _row_to_resolution(
            short_rows[0], clean, ResolutionMethod.LEXICAL,
            ambiguity_state="CLEAR", confidence="MEDIUM",
        )
    if len(short_rows) > 1:
        alternatives = tuple(
            {
                "canonical_id": r["canonical_id"],
                "qualified_name": r["qualified_name"],
                "kind": r["kind"],
                "path": r["path"],
                "line": r["start_line"],
            }
            for r in short_rows
        )
        # Pick the non-test one if unique
        non_test = [r for r in short_rows if "test" not in (r["path"] or "").lower()]
        if len(non_test) == 1:
            return _row_to_resolution(
                non_test[0], clean, ResolutionMethod.LEXICAL,
                ambiguity_state="ASSUMED", confidence="MEDIUM",
                alternatives=alternatives,
            )
        return TargetResolution(
            schema_version=_SCHEMA_VERSION,
            raw_target=raw,
            target_type=_kind_to_type(short_rows[0]["kind"]),
            canonical_id=short_rows[0]["canonical_id"],
            qualified_name=short_rows[0]["qualified_name"],
            file_path=short_rows[0]["path"],
            line=short_rows[0]["start_line"],
            confidence="LOW",
            resolution_method=ResolutionMethod.AMBIGUOUS,
            alternatives=alternatives,
            ambiguity_state="AMBIGUOUS",
            evidence_ids=tuple(r["canonical_id"] for r in short_rows),
        )

    # ── 8. UNKNOWN ───────────────────────────────────────────────────────────
    return TargetResolution(
        schema_version=_SCHEMA_VERSION,
        raw_target=raw,
        target_type=TargetType.UNKNOWN,
        canonical_id=None,
        qualified_name=None,
        file_path=None,
        line=None,
        confidence="UNKNOWN",
        resolution_method=ResolutionMethod.UNKNOWN,
        alternatives=(),
        ambiguity_state="UNKNOWN",
        evidence_ids=(),
    )


def resolve_targets(
    targets: list[str],
    con: sqlite3.Connection,
) -> dict[str, TargetResolution]:
    """Resolve a list of target strings. Returns mapping raw_target -> TargetResolution."""
    return {t: resolve_target(t, con) for t in targets}
