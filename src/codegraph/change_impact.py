"""Production-Grade Semantic Change Impact & PR Blast Radius Engine.

Extends Git and AST impact analysis by tracing complete downstream chains:
    changed symbol / git diff
        ↓
    direct & transitive callers
        ↓
    frontend UI components (React/Next.js/Vue)
        ↓
    framework routes & public endpoints
        ↓
    database readers & writers (mutations, migrations)
        ↓
    covering tests & smart test execution recommendation
        ↓
    monorepo package boundaries & PR risk score

Every item carries explicit evidence, relationship type, source location,
epistemic confidence (FACT, POSSIBLE, UNKNOWN), and breaking change risk.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.graph.traversal import find_callees, find_callers, find_related_tests
from codegraph.monorepo import detect_workspace
from codegraph.structural_diff import compare_revisions

_FRONTEND_EXTENSIONS = (".tsx", ".jsx", ".vue", ".svelte")
_MUTATING_SQL_OPS = frozenset({"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "MIGRATE", "TRUNCATE"})


@dataclass
class ImpactedEntity:
    name: str
    kind: str  # "CALLER" | "CALLEE" | "FRONTEND_COMPONENT" | "ROUTE" | "TEST" | "DB_WRITER" | "DB_READER" | "PACKAGE"
    file: str
    line: int | None
    relationship: str  # "CALLS" | "HANDLED_BY" | "TESTS" | "WRITES_TABLE" | "READS_TABLE" | "DEPENDS_ON" | "FETCHES_ROUTE"
    depth: int
    confidence: str  # "FACT" | "POSSIBLE" | "UNKNOWN"
    reason: str
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "relationship": self.relationship,
            "depth": self.depth,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class DeepImpactReport:
    base_ref: str
    head_ref: str
    target_symbol: str | None = None
    changed_files: list[str] = field(default_factory=list)
    changed_symbols: list[dict[str, Any]] = field(default_factory=list)
    direct_callers: list[ImpactedEntity] = field(default_factory=list)
    transitive_callers: list[ImpactedEntity] = field(default_factory=list)
    affected_callees: list[ImpactedEntity] = field(default_factory=list)
    affected_frontend_components: list[ImpactedEntity] = field(default_factory=list)
    affected_routes: list[ImpactedEntity] = field(default_factory=list)
    affected_tests: list[ImpactedEntity] = field(default_factory=list)
    db_readers: list[ImpactedEntity] = field(default_factory=list)
    db_writers: list[ImpactedEntity] = field(default_factory=list)
    affected_packages: list[str] = field(default_factory=list)
    total_impacted_count: int = 0
    blast_radius_score: float = 0.0  # 0.0 - 100.0 scale
    risk_level: str = "LOW"  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    breaking_change_flags: list[str] = field(default_factory=list)
    recommended_test_command: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "target_symbol": self.target_symbol,
            "changed_files": self.changed_files,
            "changed_symbols": self.changed_symbols,
            "direct_callers": [c.as_dict() for c in self.direct_callers],
            "transitive_callers": [c.as_dict() for c in self.transitive_callers],
            "affected_callees": [c.as_dict() for c in self.affected_callees],
            "affected_frontend_components": [f.as_dict() for f in self.affected_frontend_components],
            "affected_routes": [r.as_dict() for r in self.affected_routes],
            "affected_tests": [t.as_dict() for t in self.affected_tests],
            "db_readers": [d.as_dict() for d in self.db_readers],
            "db_writers": [d.as_dict() for d in self.db_writers],
            "affected_packages": self.affected_packages,
            "total_impacted_count": self.total_impacted_count,
            "blast_radius_score": self.blast_radius_score,
            "risk_level": self.risk_level,
            "breaking_change_flags": self.breaking_change_flags,
            "recommended_test_command": self.recommended_test_command,
        }


def _is_frontend_file(path: str) -> bool:
    return any(path.endswith(ext) for ext in _FRONTEND_EXTENSIONS)


def _generate_test_command(affected_tests: list[ImpactedEntity]) -> str:
    """Generate smart targeted test execution command for only the affected test suite."""
    if not affected_tests:
        return ""

    test_files = sorted({t.file for t in affected_tests if t.file})
    py_files = [f for f in test_files if f.endswith(".py")]
    js_files = [f for f in test_files if f.endswith((".ts", ".tsx", ".js", ".jsx"))]

    commands: list[str] = []

    if py_files:
        test_fn_names = sorted({
            t.name for t in affected_tests
            if t.name and t.file.endswith(".py") and t.name.startswith("test_")
        })
        if test_fn_names and len(test_fn_names) <= 6:
            k_expr = " or ".join(test_fn_names)
            commands.append(f"pytest {' '.join(py_files[:4])} -k \"{k_expr}\"")
        else:
            commands.append(f"pytest {' '.join(py_files[:5])}")

    if js_files:
        commands.append(f"npm test -- {' '.join(js_files[:4])}")

    return " && ".join(commands)


def get_deep_change_impact(
    repository: Path,
    con: sqlite3.Connection,
    base: str = "HEAD~1",
    head: str = "HEAD",
    max_depth: int = 2,
    max_results: int = 50,
    symbol: str | None = None,
) -> DeepImpactReport:
    """Analyze full blast radius of git revision changes or a specific symbol across AST, UI, routes, tests, DB, and packages."""
    changed_symbols_list: list[dict[str, Any]] = []
    changed_files: list[str] = []

    # 1. Target symbol mode: analyze blast radius of a specific symbol on demand
    if symbol:
        clean_sym = symbol.strip()
        sym_rows = con.execute(
            "SELECT name, path, canonical_id, start_line, kind FROM symbols "
            "WHERE canonical_id = ? OR qualified_name = ? OR name = ? LIMIT 10",
            (clean_sym, clean_sym, clean_sym),
        ).fetchall()
        if sym_rows:
            for sr in sym_rows:
                changed_symbols_list.append({
                    "name": str(sr["name"]),
                    "path": str(sr["path"]),
                    "canonical_id": str(sr["canonical_id"]),
                    "line": int(sr["start_line"] or 1),
                    "kind": str(sr["kind"]),
                    "change_type": "TARGET",
                })
                changed_files.append(str(sr["path"]))
        else:
            changed_symbols_list.append({
                "name": clean_sym,
                "path": "",
                "canonical_id": clean_sym,
                "change_type": "TARGET",
            })
    else:
        # Fast path: identical refs have zero changes
        if base == head and head != "WORKING_TREE":
            return DeepImpactReport(base_ref=base, head_ref=head)

        diff_report = compare_revisions(repository, base=base, head=head, con=con)
        changed_symbols_list = [
            s.as_dict() for s in (diff_report.changed_symbols + diff_report.added_symbols + diff_report.removed_symbols)
        ]
        changed_files = diff_report.modified_files + diff_report.added_files + diff_report.deleted_files

        if not changed_symbols_list and not changed_files:
            return DeepImpactReport(base_ref=base, head_ref=head)

    direct_callers: list[ImpactedEntity] = []
    transitive_callers: list[ImpactedEntity] = []
    affected_callees: list[ImpactedEntity] = []
    affected_frontend_components: list[ImpactedEntity] = []
    affected_routes: list[ImpactedEntity] = []
    affected_tests: list[ImpactedEntity] = []
    db_readers: list[ImpactedEntity] = []
    db_writers: list[ImpactedEntity] = []

    seen_keys: set[str] = set()
    processed_symbols: set[str] = set()
    processed_transitive: set[str] = set()

    for s_info in changed_symbols_list[:max_results]:
        s_name = s_info["name"]
        s_path = s_info.get("path") or ""
        s_cid = s_info.get("canonical_id") or s_name

        if not s_name or s_name in processed_symbols:
            continue
        processed_symbols.add(s_name)

        # 1. Direct callers (1-hop)
        raw_callers = find_callers(con, s_name, max_results=max_results)
        # Also check canonical_id callers if distinct
        if s_cid != s_name:
            raw_callers.extend(find_callers(con, s_cid, max_results=max_results))

        for c in raw_callers:
            c_name = c.get("caller") or c.get("symbol") or ""
            c_file = c.get("file") or ""
            c_line = c.get("line")

            # Check if this caller is a frontend UI component (Pillar 1 bridge)
            is_frontend = _is_frontend_file(c_file)
            c_kind = "FRONTEND_COMPONENT" if is_frontend else "CALLER"
            c_key = f"{c_kind}:1:{c_file}:{c_name}"

            if c_key not in seen_keys:
                seen_keys.add(c_key)
                caller_entity = ImpactedEntity(
                    name=c_name,
                    kind=c_kind,
                    file=c_file,
                    line=c_line,
                    relationship="CALLS",
                    depth=1,
                    confidence="FACT",
                    reason=f"{'Frontend component' if is_frontend else 'Caller'} invokes modified symbol {s_name}",
                    evidence=f"{c_file}:{c_line} -> {s_name}",
                )
                if is_frontend:
                    affected_frontend_components.append(caller_entity)
                else:
                    direct_callers.append(caller_entity)

                # 2. Transitive callers (2-hop) if max_depth >= 2
                if max_depth >= 2 and c_name and c_name not in processed_transitive:
                    processed_transitive.add(c_name)
                    raw_trans = find_callers(con, c_name, max_results=10)
                    for tc in raw_trans:
                        tc_name = tc.get("caller") or tc.get("symbol") or ""
                        tc_file = tc.get("file") or ""
                        tc_line = tc.get("line")
                        tc_fe = _is_frontend_file(tc_file)
                        tc_kind = "FRONTEND_COMPONENT" if tc_fe else "CALLER"
                        tc_key = f"{tc_kind}:2:{tc_file}:{tc_name}"

                        if tc_key not in seen_keys and tc_name != s_name:
                            seen_keys.add(tc_key)
                            trans_entity = ImpactedEntity(
                                name=tc_name,
                                kind=tc_kind,
                                file=tc_file,
                                line=tc_line,
                                relationship="CALLS",
                                depth=2,
                                confidence="FACT",
                                reason=f"Transitively invokes {s_name} via {c_name}",
                                evidence=f"{tc_file}:{tc_line} -> {c_name} -> {s_name}",
                            )
                            if tc_fe:
                                affected_frontend_components.append(trans_entity)
                            else:
                                transitive_callers.append(trans_entity)

        # 3. Direct callees
        raw_callees = find_callees(con, s_name, max_results=max_results)
        for ce in raw_callees:
            ce_name = ce.get("callee") or ce.get("symbol") or ""
            ce_file = ce.get("file") or ""
            ce_line = ce.get("line")
            ce_key = f"CALLEE:{ce_file}:{ce_name}"
            if ce_key not in seen_keys:
                seen_keys.add(ce_key)
                affected_callees.append(
                    ImpactedEntity(
                        name=ce_name,
                        kind="CALLEE",
                        file=ce_file,
                        line=ce_line,
                        relationship="CALLED_BY",
                        depth=1,
                        confidence="FACT",
                        reason=f"Called by modified symbol {s_name}",
                        evidence=f"{s_path} -> {ce_name}",
                    )
                )

        # 4. Route impact across framework_routes, raw_framework_routes, and routes
        candidate_handlers = [(s_name, s_cid, 1, f"changed symbol {s_name}")]
        for c in raw_callers:
            c_cand_name = c.get("caller") or c.get("symbol") or ""
            if c_cand_name:
                candidate_handlers.append((c_cand_name, c_cand_name, 2, f"caller {c_cand_name} of {s_name}"))

        for rt_table in ("framework_routes", "raw_framework_routes", "routes"):
            try:
                table_check = con.execute(
                    f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{rt_table}'"
                ).fetchone()
                if not table_check or table_check[0] == 0:
                    continue

                for h_name, h_cid, h_depth, h_reason in candidate_handlers:
                    if rt_table == "routes":
                        route_rows = con.execute(
                            "SELECT path, method, handler_name, file, NULL FROM routes "
                            "WHERE handler_name = ? OR symbol = ?",
                            (h_name, h_name),
                        ).fetchall()
                    else:
                        route_rows = con.execute(
                            f"SELECT route_path, http_method, handler_name, file_path, line FROM {rt_table} "
                            "WHERE handler_name = ? OR handler_canonical_id = ? OR handler_canonical_id LIKE ?",
                            (h_name, h_cid, f"%{h_name}"),
                        ).fetchall()

                    for rr in route_rows:
                        r_path = str(rr[0] or "")
                        r_method = str(rr[1] or "GET").upper()
                        r_file = str(rr[3] or "")
                        r_line = int(rr[4]) if rr[4] is not None else None
                        r_key = f"ROUTE:{r_path}:{r_method}"
                        if r_key not in seen_keys:
                            seen_keys.add(r_key)
                            affected_routes.append(
                                ImpactedEntity(
                                    name=f"{r_method} {r_path}",
                                    kind="ROUTE",
                                    file=r_file,
                                    line=r_line,
                                    relationship="ROUTES_TO",
                                    depth=h_depth,
                                    confidence="FACT",
                                    reason=f"Endpoint reached via {h_reason}",
                                    evidence=f"Route {r_method} {r_path} -> {h_name} ({r_file})",
                                )
                            )

                            # Check if any frontend component fetches this route
                            try:
                                fetch_rows = con.execute(
                                    "SELECT target_name, file_path, line, scope FROM local_bindings "
                                    "WHERE expr_kind = 'REACT_FETCH_ROUTE' AND (target_name = ? OR target_name LIKE ?)",
                                    (r_path, f"%{r_path.rstrip('/')}%"),
                                ).fetchall()
                                for fr in fetch_rows:
                                    fe_name = str(fr[3] or Path(str(fr[1])).stem)
                                    fe_file = str(fr[1])
                                    fe_line = int(fr[2] or 1)
                                    fe_key = f"FRONTEND_COMPONENT:{fe_file}:{fe_name}"
                                    if fe_key not in seen_keys:
                                        seen_keys.add(fe_key)
                                        affected_frontend_components.append(
                                            ImpactedEntity(
                                                name=fe_name,
                                                kind="FRONTEND_COMPONENT",
                                                file=fe_file,
                                                line=fe_line,
                                                relationship="FETCHES_ROUTE",
                                                depth=h_depth + 1,
                                                confidence="FACT",
                                                reason=f"Frontend component fetches affected route {r_method} {r_path}",
                                                evidence=f"{fe_file}:{fe_line} -> {r_path}",
                                            )
                                        )
                            except sqlite3.OperationalError:
                                pass
                break
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                pass

        # 5. Tests targeting this symbol
        tests = find_related_tests(con, s_name, max_results=30)
        if s_cid != s_name:
            tests.extend(find_related_tests(con, s_cid, max_results=30))

        for t in tests:
            if t.get("result") == "no_static_link_found":
                continue
            t_name = str(t.get("symbol") or t.get("test") or "").strip()
            t_file = str(t.get("file") or "").strip()
            if not t_name and not t_file:
                continue

            t_line_raw = t.get("line")
            t_line = int(t_line_raw) if isinstance(t_line_raw, (int, str)) and str(t_line_raw).isdigit() else None
            t_key = f"TEST:{t_file}:{t_name}"
            if t_key not in seen_keys:
                seen_keys.add(t_key)
                affected_tests.append(
                    ImpactedEntity(
                        name=t_name,
                        kind="TEST",
                        file=t_file,
                        line=t_line,
                        relationship="TESTS",
                        depth=1,
                        confidence="FACT",
                        reason=f"Test targets modified symbol {s_name}",
                        evidence=f"{t_file}:{t_line} tests {s_name}",
                    )
                )

        # 6. Database readers and writers
        # Query db_queries table (and database_queries for backward compatibility)
        for db_table in ("db_queries", "database_queries"):
            try:
                table_check = con.execute(
                    f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{db_table}'"
                ).fetchone()
                if not table_check or table_check[0] == 0:
                    continue

                if db_table == "db_queries":
                    db_rows = con.execute(
                        "SELECT table_name, operation, file_path, start_line FROM db_queries "
                        "WHERE caller_symbol_id = ? OR caller_symbol_id LIKE ?",
                        (s_cid, f"%{s_name}"),
                    ).fetchall()
                else:
                    db_rows = con.execute(
                        "SELECT table_name, operation, file, line FROM database_queries "
                        "WHERE symbol = ? OR caller_symbol = ?",
                        (s_name, s_name),
                    ).fetchall()

                for dr in db_rows:
                    tbl = str(dr[0] or "")
                    op = str(dr[1] or "SELECT").upper()
                    f_path = str(dr[2] or s_path)
                    l_num = int(dr[3]) if dr[3] is not None else None
                    is_mutating = op in _MUTATING_SQL_OPS
                    kind = "DB_WRITER" if is_mutating else "DB_READER"
                    rel = "WRITES_TABLE" if is_mutating else "READS_TABLE"
                    db_key = f"{kind}:{tbl}:{op}:{s_name}"
                    if db_key not in seen_keys:
                        seen_keys.add(db_key)
                        entity = ImpactedEntity(
                            name=f"{op} {tbl}",
                            kind=kind,
                            file=f_path,
                            line=l_num,
                            relationship=rel,
                            depth=1,
                            confidence="FACT",
                            reason=f"{s_name} executes {op} on {tbl}",
                            evidence=f"{s_name} -> {op} {tbl} ({f_path}:{l_num})",
                        )
                        if is_mutating:
                            db_writers.append(entity)
                        else:
                            db_readers.append(entity)
                break
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                pass

    # 7. Monorepo package impact
    ws = detect_workspace(repository, con=con)
    affected_packages: set[str] = set()
    for p in changed_files:
        pkg = ws.get_package_for_file(p)
        if pkg:
            affected_packages.add(pkg.package_id)
            for dep in ws.get_dependent_packages(pkg.package_id):
                affected_packages.add(dep.package_id)

    total_count = (
        len(direct_callers)
        + len(transitive_callers)
        + len(affected_callees)
        + len(affected_frontend_components)
        + len(affected_routes)
        + len(affected_tests)
        + len(db_readers)
        + len(db_writers)
    )

    # 8. Blast radius score calculation: 0 - 100 scale
    score = min(
        100.0,
        (len(direct_callers) * 3.5)
        + (len(transitive_callers) * 1.5)
        + (len(affected_frontend_components) * 5.0)
        + (len(affected_routes) * 8.0)
        + (len(db_writers) * 6.0)
        + (len(affected_packages) * 5.0),
    )

    # Risk level classification
    if score >= 75.0:
        risk_level = "CRITICAL"
    elif score >= 50.0:
        risk_level = "HIGH"
    elif score >= 25.0:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Breaking change flags
    breaking_change_flags: list[str] = []
    if affected_routes:
        breaking_change_flags.append("PUBLIC_API_MODIFIED")
    if db_writers:
        breaking_change_flags.append("DB_MUTATION_IMPACT")
    if len(affected_packages) > 1:
        breaking_change_flags.append("CROSS_PACKAGE_IMPACT")
    if changed_symbols_list and not affected_tests:
        breaking_change_flags.append("UNCOVERED_BY_TESTS")

    # Smart test command recommendation
    rec_test_cmd = _generate_test_command(affected_tests)

    return DeepImpactReport(
        base_ref=base,
        head_ref=head,
        target_symbol=symbol,
        changed_files=changed_files,
        changed_symbols=changed_symbols_list,
        direct_callers=direct_callers[:max_results],
        transitive_callers=transitive_callers[:max_results],
        affected_callees=affected_callees[:max_results],
        affected_frontend_components=affected_frontend_components[:max_results],
        affected_routes=affected_routes,
        affected_tests=affected_tests[:max_results],
        db_readers=db_readers,
        db_writers=db_writers,
        affected_packages=sorted(affected_packages),
        total_impacted_count=total_count,
        blast_radius_score=round(score, 1),
        risk_level=risk_level,
        breaking_change_flags=breaking_change_flags,
        recommended_test_command=rec_test_cmd,
    )
