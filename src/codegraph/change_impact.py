"""Deep Change Impact Analysis Engine.

Extends existing Git impact analysis by tracing complete downstream chains:
    changed symbol
        ↓
    callers (direct & transitive)
        ↓
    callees
        ↓
    routes & endpoints
        ↓
    tests & test suites
        ↓
    DB readers & writers
        ↓
    downstream package dependencies

Every item carries explicit evidence, relationship type, source location,
and confidence/epistemic state (FACT, POSSIBLE, UNKNOWN).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.graph.traversal import find_callees, find_callers, find_related_tests
from codegraph.monorepo import detect_workspace
from codegraph.structural_diff import compare_revisions


@dataclass
class ImpactedEntity:
    name: str
    kind: str  # "CALLER" | "CALLEE" | "ROUTE" | "TEST" | "DB_WRITER" | "DB_READER" | "PACKAGE"
    file: str
    line: int | None
    relationship: str  # "CALLS" | "HANDLED_BY" | "TESTS" | "WRITES_TABLE" | "READS_TABLE" | "DEPENDS_ON"
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
    changed_files: list[str] = field(default_factory=list)
    changed_symbols: list[dict[str, Any]] = field(default_factory=list)
    direct_callers: list[ImpactedEntity] = field(default_factory=list)
    transitive_callers: list[ImpactedEntity] = field(default_factory=list)
    affected_callees: list[ImpactedEntity] = field(default_factory=list)
    affected_routes: list[ImpactedEntity] = field(default_factory=list)
    affected_tests: list[ImpactedEntity] = field(default_factory=list)
    db_readers: list[ImpactedEntity] = field(default_factory=list)
    db_writers: list[ImpactedEntity] = field(default_factory=list)
    affected_packages: list[str] = field(default_factory=list)
    total_impacted_count: int = 0
    blast_radius_score: float = 0.0  # 0.0 - 100.0 scale

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "changed_files": self.changed_files,
            "changed_symbols": self.changed_symbols,
            "direct_callers": [c.as_dict() for c in self.direct_callers],
            "transitive_callers": [c.as_dict() for c in self.transitive_callers],
            "affected_callees": [c.as_dict() for c in self.affected_callees],
            "affected_routes": [r.as_dict() for r in self.affected_routes],
            "affected_tests": [t.as_dict() for t in self.affected_tests],
            "db_readers": [d.as_dict() for d in self.db_readers],
            "db_writers": [d.as_dict() for d in self.db_writers],
            "affected_packages": self.affected_packages,
            "total_impacted_count": self.total_impacted_count,
            "blast_radius_score": self.blast_radius_score,
        }


def get_deep_change_impact(
    repository: Path,
    con: sqlite3.Connection,
    base: str = "HEAD~1",
    head: str = "HEAD",
    max_depth: int = 2,
    max_results: int = 50,
) -> DeepImpactReport:
    """Analyze full blast radius of git revision changes across AST, routes, tests, DB, and packages."""
    # Fast path: identical refs have zero changes
    if base == head and head != "WORKING_TREE":
        return DeepImpactReport(base_ref=base, head_ref=head)

    diff_report = compare_revisions(repository, base=base, head=head, con=con)

    changed_symbols_list: list[dict[str, Any]] = [
        s.as_dict() for s in (diff_report.changed_symbols + diff_report.added_symbols + diff_report.removed_symbols)
    ]
    changed_files = diff_report.modified_files + diff_report.added_files + diff_report.deleted_files

    if not changed_symbols_list and not changed_files:
        return DeepImpactReport(base_ref=base, head_ref=head)

    direct_callers: list[ImpactedEntity] = []
    transitive_callers: list[ImpactedEntity] = []
    affected_callees: list[ImpactedEntity] = []
    affected_routes: list[ImpactedEntity] = []
    affected_tests: list[ImpactedEntity] = []
    db_readers: list[ImpactedEntity] = []
    db_writers: list[ImpactedEntity] = []

    seen_keys: set[str] = set()
    processed_symbols: set[str] = set()
    processed_transitive: set[str] = set()

    for s_info in changed_symbols_list[:max_results]:
        s_name = s_info["name"]
        s_path = s_info["path"]

        if not s_name or s_name in processed_symbols:
            continue
        processed_symbols.add(s_name)

        # 1. Direct callers (1-hop)
        raw_callers = find_callers(con, s_name, max_results=max_results)
        for c in raw_callers:
            c_name = c.get("caller") or c.get("symbol") or ""
            c_file = c.get("file") or ""
            c_line = c.get("line")
            c_key = f"CALLER:1:{c_file}:{c_name}"
            if c_key not in seen_keys:
                seen_keys.add(c_key)
                direct_callers.append(
                    ImpactedEntity(
                        name=c_name,
                        kind="CALLER",
                        file=c_file,
                        line=c_line,
                        relationship="CALLS",
                        depth=1,
                        confidence="FACT",
                        reason=f"Invokes modified symbol {s_name}",
                        evidence=f"{c_file}:{c_line} -> {s_name}",
                    )
                )

                # 2. Transitive callers (2-hop) if max_depth >= 2
                if max_depth >= 2 and c_name and c_name not in processed_transitive:
                    processed_transitive.add(c_name)
                    raw_trans = find_callers(con, c_name, max_results=10)
                    for tc in raw_trans:
                        tc_name = tc.get("caller") or tc.get("symbol") or ""
                        tc_file = tc.get("file") or ""
                        tc_line = tc.get("line")
                        tc_key = f"CALLER:2:{tc_file}:{tc_name}"
                        if tc_key not in seen_keys and tc_name != s_name:
                            seen_keys.add(tc_key)
                            transitive_callers.append(
                                ImpactedEntity(
                                    name=tc_name,
                                    kind="CALLER",
                                    file=tc_file,
                                    line=tc_line,
                                    relationship="CALLS",
                                    depth=2,
                                    confidence="FACT",
                                    reason=f"Transitively invokes {s_name} via {c_name}",
                                    evidence=f"{tc_file}:{tc_line} -> {c_name} -> {s_name}",
                                )
                            )

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

        # 4. Route impact: does this symbol handle an endpoint or get called by a route?
        try:
            route_rows = con.execute(
                "SELECT path, method, handler_name, file FROM routes WHERE handler_name=? OR symbol=?",
                (s_name, s_name),
            ).fetchall()
            for rr in route_rows:
                r_key = f"ROUTE:{rr[0]}:{rr[1]}"
                if r_key not in seen_keys:
                    seen_keys.add(r_key)
                    affected_routes.append(
                        ImpactedEntity(
                            name=f"{rr[1]} {rr[0]}",
                            kind="ROUTE",
                            file=rr[3],
                            line=None,
                            relationship="ROUTES_TO",
                            depth=1,
                            confidence="FACT",
                            reason=f"Endpoint handled by changed symbol {s_name}",
                            evidence=f"Route {rr[1]} {rr[0]} -> {s_name}",
                        )
                    )
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

        # 5. Tests targeting this symbol
        tests = find_related_tests(con, s_name, max_results=20)
        for t in tests:
            t_name = str(t.get("symbol") or t.get("test") or "")
            t_file = str(t.get("file") or "")
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
        try:
            db_rows = con.execute(
                "SELECT table_name, operation, file, line FROM database_queries WHERE symbol=? OR caller_symbol=?",
                (s_name, s_name),
            ).fetchall()
            for dr in db_rows:
                tbl, op, f_path, l_num = dr[0], dr[1], dr[2], dr[3]
                is_mutating = op.upper() in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER")
                kind = "DB_WRITER" if is_mutating else "DB_READER"
                rel = "WRITES_TABLE" if is_mutating else "READS_TABLE"
                db_key = f"{kind}:{tbl}:{op}:{s_name}"
                if db_key not in seen_keys:
                    seen_keys.add(db_key)
                    entity = ImpactedEntity(
                        name=f"{op} {tbl}",
                        kind=kind,
                        file=f_path or s_path,
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
        + len(affected_routes)
        + len(affected_tests)
        + len(db_readers)
        + len(db_writers)
    )

    # Blast radius score calculation: 0 - 100
    # Factors: number of direct callers, routes impacted, db writers impacted, package boundaries crossed
    score = min(
        100.0,
        (len(direct_callers) * 3.5)
        + (len(transitive_callers) * 1.5)
        + (len(affected_routes) * 8.0)
        + (len(db_writers) * 6.0)
        + (len(affected_packages) * 5.0),
    )

    return DeepImpactReport(
        base_ref=base,
        head_ref=head,
        changed_files=changed_files,
        changed_symbols=changed_symbols_list,
        direct_callers=direct_callers[:max_results],
        transitive_callers=transitive_callers[:max_results],
        affected_callees=affected_callees[:max_results],
        affected_routes=affected_routes,
        affected_tests=affected_tests[:max_results],
        db_readers=db_readers,
        db_writers=db_writers,
        affected_packages=sorted(affected_packages),
        total_impacted_count=total_count,
        blast_radius_score=round(score, 1),
    )
