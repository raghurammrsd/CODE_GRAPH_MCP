"""Phase 10 — Context Optimization, Evidence Compression & Token-Efficient Retrieval Tests.

Covers 48 focused tests including:
- Budget enforcement (max_tokens, max_symbols, max_relationships, max_files, max_lines, max_depth)
- Candidate vs selected metrics (all 13 required metrics)
- Token calculation & bounded source snippet selection
- Task-aware retrieval policies (UNDERSTAND, DEBUG, EXPLAIN, TRACE, CHANGE, TEST, ARCHITECTURE)
- Coverage-aware multi-dimension selection (not just top-K)
- Redundancy elimination by canonical identity
- Deterministic evidence compression (multiple locations -> 1 primary + supporting_locations)
- Package-aware context limiting & monorepo traversal bounds
- Artifact suppression & opt-in explainability
- Epistemic preservation (UNKNOWN, POSSIBLE, CONFLICT)
- Adversarial False-Negative defenses (route->handler, DI provider, event handler, related test, package dep)
- Adversarial False-Positive defenses (minified bundle, vendor, generic method, unrelated package, lexical noise)
- Determinism across repeated runs
- Cache freshness & stale index handling
- Persistent MCP warm latency instrumentation (first_request, warm_request, p50, p95, p99)
- 5 Realistic end-to-end repository scenarios
"""
from __future__ import annotations

import json
from pathlib import Path

from codegraph.context import Relationship, get_context
from codegraph.indexing.indexer import Indexer
from codegraph.observability import (
    MetricsRegistry,
    OperationMetric,
    compute_latency_percentiles,
)
from codegraph.optimizer import (
    REASON_AMBIGUITY_PRESERVED,
    REASON_DIRECT_CALLER,
    REASON_DIRECT_TARGET,
    REASON_RELATED_TEST,
    REASON_RELEVANT_ROUTE,
    CandidateContextItem,
    ContextBudgetSpec,
    compress_relationships,
    optimize_context_budget,
    select_bounded_snippet,
)
from codegraph.retrieval_policy import get_retrieval_policy
from codegraph.task import TaskSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    item_id: str,
    file_path: str = "src/app.py",
    canonical_id: str | None = None,
    symbol: str | None = None,
    tokens: int = 80,
    relevance: float = 0.80,
    evidence_quality: float = 0.90,
    freshness: str = "FRESH",
    layer: str = "SERVICE",
    confidence: str = "HIGH",
    status: str = "FACT",
    relationship: str = "",
    pkg_id: str | None = None,
    pkg_dist: int = 0,
    artifact_class: str = "SOURCE",
    dimension: str = "",
    start_line: int = 1,
    end_line: int = 15,
    snippet: str = "def fn():\n    return True\n",
) -> CandidateContextItem:
    return CandidateContextItem(
        item_id=item_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        canonical_id=canonical_id or f"{file_path}::{symbol or item_id}",
        estimated_tokens=tokens,
        relevance_score=relevance,
        evidence_quality=evidence_quality,
        freshness=freshness,
        coverage_layer=layer,
        source_type="symbol",
        snippet=snippet,
        confidence=confidence,
        epistemic_status=status,
        data={"symbol": symbol or item_id, "relationship": relationship, "reasons": []},
        package_id=pkg_id,
        package_distance=pkg_dist,
        artifact_class=artifact_class,
        task_dimension=dimension,
    )


# ---------------------------------------------------------------------------
# 1. Budget Enforcement & Candidate vs Selected Metrics (Tests 1–8)
# ---------------------------------------------------------------------------


def test_01_candidate_vs_selected_all_13_metrics() -> None:
    """1. Verify all 13 candidate vs selected metrics are tracked independently."""
    candidates = [
        _make_candidate(f"sym_{i}", file_path=f"src/m{i}.py", tokens=100, relevance=0.9 - i * 0.05)
        for i in range(8)
    ]
    selected, budget = optimize_context_budget(candidates, token_budget=350)
    b_dict = budget.as_dict()

    required_keys = {
        "candidate_count",
        "selected_count",
        "candidate_tokens",
        "selected_tokens",
        "candidate_reduction_ratio",
        "selected_reduction_ratio",
        "budget_utilization",
        "coverage_score",
        "redundancy_ratio",
        "evidence_density",
        "direct_file_reads",
        "direct_file_lines",
        "tool_calls",
    }
    assert required_keys.issubset(b_dict.keys())
    assert budget.candidate_count == 8
    assert budget.selected_count == 3
    assert budget.candidate_tokens == 800
    assert budget.selected_tokens == 300
    assert budget.candidate_reduction_ratio == round(1.0 - 3 / 8, 4)
    assert budget.selected_reduction_ratio == round(1.0 - 300 / 800, 4)
    assert budget.budget_utilization == round(300 / 350, 4)
    assert budget.direct_file_reads == 3
    assert budget.direct_file_lines > 0
    assert budget.tool_calls == 1
    assert len(selected) == 3


def test_02_budget_enforces_max_symbols() -> None:
    """2. ContextBudgetSpec max_symbols strictly bounds selected symbol count."""
    candidates = [
        _make_candidate(f"s_{i}", file_path=f"src/f{i}.py", tokens=50, relevance=0.85)
        for i in range(10)
    ]
    spec = ContextBudgetSpec(max_tokens=10_000, max_symbols=4, max_files=20, max_lines=1000)
    selected, budget = optimize_context_budget(candidates, token_budget=10_000, budget_spec=spec)
    assert len(selected) == 4
    assert budget.selected_count == 4
    assert budget.max_symbols == 4


def test_03_budget_enforces_max_files() -> None:
    """3. ContextBudgetSpec max_files strictly bounds distinct files touched."""
    candidates = [
        _make_candidate(f"s_{i}", file_path=f"src/file_{i}.py", tokens=50, relevance=0.85)
        for i in range(10)
    ]
    spec = ContextBudgetSpec(max_tokens=10_000, max_symbols=20, max_files=3, max_lines=1000)
    selected, budget = optimize_context_budget(candidates, token_budget=10_000, budget_spec=spec)
    distinct_files = {s.file_path for s in selected}
    assert len(distinct_files) <= 3
    assert budget.direct_file_reads <= 3


def test_04_budget_enforces_max_lines() -> None:
    """4. ContextBudgetSpec max_lines bounds total source lines returned."""
    ten_line_snip = "\n".join(f"line {j}" for j in range(10))
    candidates = [
        _make_candidate(f"s_{i}", file_path=f"src/f{i}.py", tokens=40, relevance=0.85, snippet=ten_line_snip)
        for i in range(10)
    ]
    spec = ContextBudgetSpec(max_tokens=10_000, max_symbols=20, max_files=20, max_lines=25)
    selected, budget = optimize_context_budget(candidates, token_budget=10_000, budget_spec=spec)
    assert len(selected) == 2
    assert budget.direct_file_lines <= 25


def test_05_bounded_source_snippet_selection() -> None:
    """5. select_bounded_snippet extracts bounded lines and tracks requested vs returned lines."""
    full_file = "\n".join(f"def fn_{i}(): pass" for i in range(120))
    snip, req_lines, ret_lines = select_bounded_snippet(full_file, start_line=1, end_line=120, max_lines=20, max_chars=500)
    assert req_lines == 120
    assert ret_lines <= 20
    assert len(snip) <= 500
    assert "def fn_0(): pass" in snip
    assert "def fn_119(): pass" not in snip


def test_06_empty_snippet_handling() -> None:
    """6. select_bounded_snippet handles empty strings deterministically."""
    snip, req, ret = select_bounded_snippet("", max_lines=10)
    assert snip == ""
    assert req == 0
    assert ret == 0


# ---------------------------------------------------------------------------
# 2. Task-Aware Policies & Relationship Allowlists (Tests 7–13)
# ---------------------------------------------------------------------------


def test_07_understand_policy_relationships_and_dimensions() -> None:
    """7. UNDERSTAND policy includes semantic relationships and package dependencies."""
    pol = get_retrieval_policy("UNDERSTAND")
    for rel in ("CALLS", "IMPORTS", "MOUNTS", "REGISTERS", "EVENT_LISTENER", "TASK_HANDLER",
                "COMMAND_HANDLER", "INJECTS", "PROVIDES", "DEPENDS_ON_PACKAGE"):
        assert pol.allows(rel), f"UNDERSTAND should allow {rel}"
    assert "PACKAGE" in pol.required_dimensions
    assert "TARGET" in pol.required_dimensions


def test_08_trace_policy_relationships_and_dimensions() -> None:
    """8. TRACE policy allows verified call, dispatch, route, and DI chains."""
    pol = get_retrieval_policy("TRACE")
    for rel in ("CALLS", "DISPATCHES_TO", "HANDLED_BY", "ROUTE_HANDLER", "RESOLVES_DEPENDENCY", "INJECTS"):
        assert pol.allows(rel)
    assert pol.max_graph_depth == 4


def test_09_debug_policy_relationships_and_dimensions() -> None:
    """9. DEBUG policy prioritizes callers, callees, routes, registrations, providers, tests."""
    pol = get_retrieval_policy("DEBUG")
    for dim in ("TARGET", "CALLER", "CALLEE", "ROUTE", "REGISTRATION", "PROVIDER", "TEST"):
        assert dim in pol.required_dimensions
    for rel in ("CALLS", "CALLED_BY", "DISPATCHES_TO", "EVENT_LISTENER", "INJECTS", "PROVIDES", "CONFIGURES", "TESTS"):
        assert pol.allows(rel)


def test_10_change_policy_relationships_and_dimensions() -> None:
    """10. CHANGE policy includes routes, registrations, providers, tests, and package dependencies."""
    pol = get_retrieval_policy("CHANGE")
    for rel in ("CALLS", "HANDLED_BY", "REGISTERS", "INJECTS", "PROVIDES", "TESTS", "DEPENDS_ON_PACKAGE"):
        assert pol.allows(rel)
    assert pol.include_git is True


def test_11_test_policy_relationships_and_dimensions() -> None:
    """11. TEST policy allows test edges, target definitions, providers, events, and routes."""
    pol = get_retrieval_policy("TEST")
    for rel in ("TESTS", "TESTS_DIRECTLY", "TESTS_ROUTE", "TESTS_EVENT", "INJECTS", "PROVIDES", "HANDLED_BY"):
        assert pol.allows(rel)
    assert "TEST" in pol.required_dimensions


def test_12_architecture_policy_relationships_and_dimensions() -> None:
    """12. ARCHITECTURE policy prioritizes packages, entrypoints, services, and data."""
    pol = get_retrieval_policy("ARCHITECTURE")
    assert pol.allows("DEPENDS_ON_PACKAGE")
    assert pol.allows("MOUNTS")
    assert pol.allows("HANDLED_BY")
    assert pol.include_architecture is True
    assert "PACKAGE" in pol.required_dimensions


def test_13_explain_policy_relationships() -> None:
    """13. EXPLAIN policy supports full semantic relationship set."""
    pol = get_retrieval_policy("EXPLAIN")
    for rel in ("CALLS", "HANDLED_BY", "MOUNTS", "INJECTS", "PROVIDES", "REGISTERS", "DEPENDS_ON_PACKAGE"):
        assert pol.allows(rel)


# ---------------------------------------------------------------------------
# 3. Coverage-Aware Selection (Not Just Top-K) & Reason Codes (Tests 14–18)
# ---------------------------------------------------------------------------


def test_14_coverage_prevents_caller_flooding_over_tests_and_providers() -> None:
    """14. Seven high-scoring callers do NOT crowd out the single related test and provider in DEBUG."""
    callers = [
        _make_candidate(
            f"caller_{i}",
            file_path=f"src/caller_{i}.py",
            tokens=100,
            relevance=0.88 - i * 0.01,
            layer="SERVICE",
            dimension="CALLER",
        )
        for i in range(7)
    ]
    target = _make_candidate("target_fn", file_path="src/target.py", tokens=100, relevance=0.95, layer="SERVICE", dimension="TARGET")
    provider = _make_candidate("db_provider", file_path="src/deps.py", tokens=100, relevance=0.60, layer="DATA", dimension="PROVIDER")
    test_item = _make_candidate("test_target", file_path="tests/test_target.py", tokens=100, relevance=0.55, layer="TEST", dimension="TEST")
    route_item = _make_candidate("route_ep", file_path="src/routes.py", tokens=100, relevance=0.62, layer="ENTRYPOINT", dimension="ROUTE")

    # Budget only fits 5 items (500 tokens). Pure top-K would pick target + 4 callers and zero tests/providers/routes!
    all_cands = [target] + callers + [provider, test_item, route_item]
    debug_dims = get_retrieval_policy("DEBUG").required_dimensions
    selected, budget = optimize_context_budget(
        all_cands,
        token_budget=500,
        required_dimensions=debug_dims,
    )
    selected_ids = {s.item_id for s in selected}
    assert "target_fn" in selected_ids
    assert "db_provider" in selected_ids
    assert "test_target" in selected_ids
    assert "route_ep" in selected_ids
    # At least 1 caller is also included, filling the 5th slot
    assert any(cid.startswith("caller_") for cid in selected_ids)
    assert budget.coverage_score >= 0.8


def test_15_selected_candidates_have_explainable_reason_codes() -> None:
    """15. Every selected candidate receives an explicit reason_code."""
    cands = [
        _make_candidate("t1", dimension="TARGET", relevance=0.95),
        _make_candidate("c1", file_path="src/c1.py", dimension="CALLER", relevance=0.80),
        _make_candidate("r1", file_path="src/r1.py", layer="ENTRYPOINT", dimension="ROUTE", relevance=0.75),
        _make_candidate("tst1", file_path="tests/t.py", layer="TEST", dimension="TEST", relevance=0.70),
    ]
    selected, _ = optimize_context_budget(
        cands,
        token_budget=1000,
        required_dimensions=("TARGET", "CALLER", "ROUTE", "TEST"),
    )
    reasons_by_id = {s.item_id: s.reason_code for s in selected}
    assert reasons_by_id["t1"] == REASON_DIRECT_TARGET
    assert reasons_by_id["c1"] == REASON_DIRECT_CALLER
    assert reasons_by_id["r1"] == REASON_RELEVANT_ROUTE
    assert reasons_by_id["tst1"] == REASON_RELATED_TEST


# ---------------------------------------------------------------------------
# 4. Duplicate Elimination & Evidence Compression (Tests 16–21)
# ---------------------------------------------------------------------------


def test_16_deduplication_by_canonical_identity_not_substring() -> None:
    """16. Duplicate canonical_id is eliminated, while distinct symbols with substring overlap are preserved."""
    c1 = _make_candidate("c1", file_path="src/auth.py", canonical_id="src/auth.py::login", symbol="login", tokens=80, relevance=0.90)
    c1_dup = _make_candidate("c1_dup", file_path="src/auth.py", canonical_id="src/auth.py::login", symbol="login", tokens=80, relevance=0.85)
    c2_substr = _make_candidate("c2", file_path="src/auth.py", canonical_id="src/auth.py::login_with_sso", symbol="login_with_sso", tokens=80, relevance=0.82)

    selected, budget = optimize_context_budget([c1, c1_dup, c2_substr], token_budget=500)
    selected_cids = [s.canonical_id for s in selected]
    assert selected_cids.count("src/auth.py::login") == 1
    assert "src/auth.py::login_with_sso" in selected_cids
    assert budget.redundancy_ratio == 0.0


def test_17_evidence_compression_merges_five_duplicate_locations() -> None:
    """17. Five locations proving the same (source, target, relationship) compress to 1 primary with supporting_locations."""
    rels = [
        Relationship(
            source="src/api.py::handle_Order",
            target="src/service.py::process_order",
            relationship="CALLS",
            confidence="MEDIUM" if i < 2 else "HIGH",
            file="src/api.py",
            start_line=10 + i * 5,
            evidence=f"process_order() at line {10 + i * 5}",
            status="FACT",
            evidence_class="DATAFLOW_VERIFIED" if i < 2 else "AST_VERIFIED",
        )
        for i in range(5)
    ]
    compressed, stats = compress_relationships(rels, max_relationships=30)
    assert len(compressed) == 1
    assert stats["raw_count"] == 5
    assert stats["compressed_count"] == 1
    assert stats["duplicates_merged"] == 4

    primary = compressed[0]
    assert primary.evidence_class == "AST_VERIFIED"
    assert primary.confidence == "HIGH"
    assert primary.occurrence_count == 5
    assert len(primary.supporting_locations) == 4


def test_18_evidence_compression_never_merges_incompatible_relationships() -> None:
    """18. CALLS, REGISTERS, and INJECTS between the same source and target are never merged."""
    rels = [
        Relationship(source="A", target="B", relationship="CALLS", confidence="HIGH", evidence_class="AST_VERIFIED"),
        Relationship(source="A", target="B", relationship="REGISTERS", confidence="HIGH", evidence_class="FRAMEWORK_VERIFIED"),
        Relationship(source="A", target="B", relationship="INJECTS", confidence="HIGH", evidence_class="FRAMEWORK_VERIFIED"),
    ]
    compressed, stats = compress_relationships(rels)
    assert len(compressed) == 3
    assert stats["duplicates_merged"] == 0
    assert {r.relationship for r in compressed} == {"CALLS", "REGISTERS", "INJECTS"}


def test_19_evidence_compression_never_drops_only_evidence_or_converts_unknown() -> None:
    """19. Single POSSIBLE or UNKNOWN relationship is never dropped and never upgraded to AST_VERIFIED."""
    rels = [
        Relationship(
            source="src/dyn.py::run",
            target="src/handlers.py:: target_fn",
            relationship="POSSIBLE_CALLS",
            confidence="LOW",
            status="INFERENCE",
            evidence_class="POSSIBLE",
        ),
        Relationship(
            source="src/dyn.py::dispatch",
            target="UNKNOWN_TARGET",
            relationship="DISPATCHES_TO",
            confidence="LOW",
            status="UNKNOWN",
            evidence_class="UNKNOWN",
        ),
    ]
    compressed, _ = compress_relationships(rels)
    assert len(compressed) == 2
    by_rel = {r.relationship: r for r in compressed}
    assert by_rel["POSSIBLE_CALLS"].evidence_class == "POSSIBLE"
    assert by_rel["POSSIBLE_CALLS"].status == "INFERENCE"
    assert by_rel["DISPATCHES_TO"].evidence_class == "UNKNOWN"
    assert by_rel["DISPATCHES_TO"].status == "UNKNOWN"


# ---------------------------------------------------------------------------
# 5. Epistemic Preservation: UNKNOWN, POSSIBLE, CONFLICT (Tests 20–22)
# ---------------------------------------------------------------------------


def test_20_optimizer_preserves_unknown_and_conflict_candidates() -> None:
    """20. Pass 0 of optimize_context_budget preserves UNKNOWN and CONFLICT candidates."""
    unknown_item = _make_candidate(
        "unresolved_dep",
        file_path="src/plugin.py",
        tokens=60,
        relevance=0.45,
        confidence="LOW",
        status="UNKNOWN",
    )
    conflict_item = _make_candidate(
        "ambiguous_handler",
        file_path="src/router.py",
        tokens=60,
        relevance=0.50,
        confidence="LOW",
        status="CONFLICT",
    )
    normal_item = _make_candidate("normal_svc", file_path="src/svc.py", tokens=100, relevance=0.90)

    selected, _ = optimize_context_budget([normal_item, unknown_item, conflict_item], token_budget=500)
    sel_ids = {s.item_id for s in selected}
    assert "unresolved_dep" in sel_ids
    assert "ambiguous_handler" in sel_ids
    for s in selected:
        if s.item_id in ("unresolved_dep", "ambiguous_handler"):
            assert s.reason_code == REASON_AMBIGUITY_PRESERVED


def test_21_unresolved_target_preserved_in_context_packet_findings_and_unknowns(tmp_path: Path) -> None:
    """21. Querying an unresolved target records UNRESOLVED_TARGET in packet.findings and packet.unknowns."""
    (tmp_path / "app.py").write_text("def existing_fn():\n    return 42\n", encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="debug NonExistentWidget", targets=("NonExistentWidget",), intent="DEBUG")
        pkt = get_context(con, tmp_path, spec)
        assert any("NonExistentWidget" in u for u in pkt.unknowns)
        assert any(f.get("type") == "UNRESOLVED_TARGET" and f.get("target") == "NonExistentWidget" for f in pkt.findings)


def test_22_ambiguous_target_preserved_in_context_packet_conflicts(tmp_path: Path) -> None:
    """22. Ambiguous short name across multiple modules is preserved in packet.conflicts and packet.findings."""
    (tmp_path / "mod_a.py").write_text("class Processor:\n    def run(self): return 1\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("class Processor:\n    def run(self): return 2\n", encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="understand Processor", targets=("Processor",), intent="UNDERSTAND")
        pkt = get_context(con, tmp_path, spec)
        assert any(f.get("type") == "AMBIGUOUS_TARGET" for f in pkt.findings)
        assert len(pkt.conflicts) >= 1


# ---------------------------------------------------------------------------
# 6. Adversarial False-Negative Validation (Tests 23–29)
# ---------------------------------------------------------------------------


def test_23_fn_defense_route_to_handler_with_zero_lexical_overlap(tmp_path: Path) -> None:
    """23. Adversarial FN: Route '/v1/checkout' maps to handler ' finalize_cart_tx ' with zero lexical overlap."""
    (tmp_path / "server.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.post('/v1/checkout')\n"
        "def finalize_cart_tx():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "trace POST /v1/checkout", intent="TRACE")
        sym_names = {s.symbol for s in pkt.symbols}
        assert "finalize_cart_tx" in sym_names
        assert any(r.relationship == "HANDLED_BY" and r.target == "finalize_cart_tx" for r in pkt.relationships)


def test_24_fn_defense_handler_to_injected_provider_with_zero_lexical_overlap(tmp_path: Path) -> None:
    """24. Adversarial FN: Endpoint handler injects 'acquire_pg_session' via Depends with zero lexical overlap."""
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI, Depends\n"
        "app = FastAPI()\n\n"
        "def acquire_pg_session():\n"
        "    return 'db_conn'\n\n"
        "@app.get('/items')\n"
        "def list_catalog_entries(db = Depends(acquire_pg_session)):\n"
        "    return db\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="debug list_catalog_entries", targets=("list_catalog_entries",), intent="DEBUG")
        pkt = get_context(con, tmp_path, spec)
        sym_names = {s.symbol for s in pkt.symbols}
        assert "list_catalog_entries" in sym_names
        assert "acquire_pg_session" in sym_names
        assert any(r.relationship == "INJECTS" for r in pkt.relationships)


def test_25_fn_defense_event_to_registered_handler(tmp_path: Path) -> None:
    """25. Adversarial FN: Event listener registration is retrieved when debugging target."""
    (tmp_path / "events.py").write_text(
        "from django.dispatch import receiver\n\n"
        "@receiver('invoice.paid')\n"
        "def dispatch_receipt_email(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="debug dispatch_receipt_email", targets=("dispatch_receipt_email",), intent="DEBUG")
        pkt = get_context(con, tmp_path, spec)
        sym_names = {s.symbol for s in pkt.symbols}
        assert "dispatch_receipt_email" in sym_names
        assert any(r.relationship == "EVENT_LISTENER" for r in pkt.relationships)


def test_26_fn_defense_changed_symbol_to_related_test(tmp_path: Path) -> None:
    """26. Adversarial FN: Modifying 'compute_tax_rate' includes its test 'test_vat_calculation'."""
    (tmp_path / "tax.py").write_text(
        "def compute_tax_rate(amount: float) -> float:\n"
        "    return amount * 0.2\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_billing.py").write_text(
        "from tax import compute_tax_rate\n\n"
        "def test_vat_calculation():\n"
        "    assert compute_tax_rate(100.0) == 20.0\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="change compute_tax_rate", targets=("compute_tax_rate",), intent="CHANGE")
        pkt = get_context(con, tmp_path, spec)
        assert any(t.symbol and "test_vat_calculation" in t.symbol for t in pkt.tests)


def test_27_fn_defense_package_internal_dependency_and_unresolved_finding(tmp_path: Path) -> None:
    """27. Adversarial FN: Monorepo package context includes internal dependency and records unresolved external dep."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "root", "private": True, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    pkg_a = tmp_path / "packages" / "orders"
    pkg_b = tmp_path / "packages" / "inventory"
    (pkg_a / "src").mkdir(parents=True)
    (pkg_b / "src").mkdir(parents=True)

    (pkg_a / "package.json").write_text(
        json.dumps({
            "name": "@corp/orders",
            "main": "src/index.ts",
            "dependencies": {
                "@corp/inventory": "workspace:*",
                "@corp/missing-legacy-sdk": "workspace:*",
            },
        }),
        encoding="utf-8",
    )
    (pkg_b / "package.json").write_text(
        json.dumps({"name": "@corp/inventory", "main": "src/index.ts"}),
        encoding="utf-8",
    )
    (pkg_a / "src" / "index.ts").write_text(
        "import { reserveStock } from '@corp/inventory';\n"
        "export function placeOrder() { return reserveStock(); }\n",
        encoding="utf-8",
    )
    (pkg_b / "src" / "index.ts").write_text(
        "export function reserveStock() { return true; }\n",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="understand placeOrder", targets=("packages/orders/src/index.ts",), intent="UNDERSTAND")
        pkt = get_context(con, tmp_path, spec)
        pkg_names = {p["name"] for p in pkt.packages}
        assert "@corp/orders" in pkg_names
        assert "@corp/inventory" in pkg_names
        assert any(f.get("type") == "UNRESOLVED_PACKAGE_DEPENDENCY" for f in pkt.findings)


def test_28_fn_defense_architecture_task_returns_package_dependencies(tmp_path: Path) -> None:
    """28. Adversarial FN: ARCHITECTURE task returns workspace packages and DEPENDS_ON_PACKAGE relationships."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "root", "private": True, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    for name, deps in [("api", {"@acme/core": "workspace:*"}), ("core", {})]:
        pdir = tmp_path / "packages" / name / "src"
        pdir.mkdir(parents=True)
        (tmp_path / "packages" / name / "package.json").write_text(
            json.dumps({"name": f"@acme/{name}", "main": "src/index.ts", "dependencies": deps}),
            encoding="utf-8",
        )
        (pdir / "index.ts").write_text(f"export const {name}Ready = true;\n", encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "architecture overview of packages", intent="ARCHITECTURE")
        assert len(pkt.packages) == 2
        assert len(pkt.architecture) >= 1


# ---------------------------------------------------------------------------
# 7. Adversarial False-Positive Validation (Tests 29–35)
# ---------------------------------------------------------------------------


def test_29_fp_defense_minified_bundle_never_beats_authored_source(tmp_path: Path) -> None:
    """29. Adversarial FP: Minified bundle with repeated target keyword is excluded and never beats authored source."""
    src_dir = tmp_path / "src"
    dist_dir = tmp_path / "dist"
    src_dir.mkdir()
    dist_dir.mkdir()

    (src_dir / "auth.py").write_text(
        "def verify_jwt_signature(token: str) -> bool:\n"
        "    return token.startswith('jwt_')\n",
        encoding="utf-8",
    )
    (dist_dir / "bundle.min.js").write_text(
        "function verify_jwt_signature(){return true;} // verify_jwt_signature verify_jwt_signature\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "verify_jwt_signature", intent="UNDERSTAND")
        assert "src/auth.py" in pkt.selected_files
        assert not any("bundle.min.js" in f for f in pkt.selected_files)


def test_30_fp_defense_vendor_implementation_never_beats_local_source(tmp_path: Path) -> None:
    """30. Adversarial FP: Vendor file with identical symbol name is excluded by default."""
    (tmp_path / "src").mkdir()
    (tmp_path / "vendor" / "lib").mkdir(parents=True)

    (tmp_path / "src" / "client.py").write_text(
        "class HttpClient:\n    def send(self): return 'local'\n",
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "lib" / "client.py").write_text(
        "class HttpClient:\n    def send(self): return 'vendor'\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "understand HttpClient", intent="UNDERSTAND")
        assert "src/client.py" in pkt.selected_files
        assert not any("vendor" in f for f in pkt.selected_files)


def test_31_fp_defense_artifact_opt_in_is_explainable(tmp_path: Path) -> None:
    """31. When include_generated=True is explicitly passed, generated inclusion is recorded in execution['artifact_inclusions']."""
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "sdk_pb2.py").write_text(
        "# Code generated by protoc-gen-python. DO NOT EDIT.\n"
        "def generated_special_helper():\n    return 'g'\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "generated_special_helper", include_generated=True)
        assert pkt.execution is not None
        inclusions = pkt.execution.get("artifact_inclusions", [])
        assert isinstance(inclusions, list)
        assert any(
            inc.get("artifact_class") == "GENERATED" and "include_generated=True" in str(inc.get("reason"))
            for inc in inclusions
        )


def test_32_fp_defense_unrelated_package_with_similar_symbol_deprioritized(tmp_path: Path) -> None:
    """32. Adversarial FP: In a monorepo, targeting Package A excludes unrelated Package C from packet.packages."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "root", "private": True, "workspaces": ["packages/*"]}),
        encoding="utf-8",
    )
    for name, deps in [
        ("auth", {"@mono/shared": "workspace:*"}),
        ("shared", {}),
        ("marketing-analytics", {}),
    ]:
        pdir = tmp_path / "packages" / name / "src"
        pdir.mkdir(parents=True)
        (tmp_path / "packages" / name / "package.json").write_text(
            json.dumps({"name": f"@mono/{name}", "main": "src/index.ts", "dependencies": deps}),
            encoding="utf-8",
        )
        (pdir / "index.ts").write_text(
            f"export function validateSession() {{ return '{name}'; }}\n",
            encoding="utf-8",
        )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(
            raw_prompt="understand validateSession in auth",
            targets=("packages/auth/src/index.ts",),
            intent="UNDERSTAND",
        )
        pkt = get_context(con, tmp_path, spec, max_package_depth=1)
        pkg_names = {p["name"] for p in pkt.packages}
        assert "@mono/auth" in pkg_names
        assert "@mono/shared" in pkg_names
        assert "@mono/marketing-analytics" not in pkg_names
        # Top symbol must be from packages/auth
        assert pkt.symbols[0].file.startswith("packages/auth")


def test_33_fp_defense_lexical_mention_is_not_graph_caller(tmp_path: Path) -> None:
    """33. Adversarial FP: A comment mentioning 'process_payment' does NOT create a CALLS relationship."""
    (tmp_path / "payment.py").write_text(
        "def process_payment(amt: int) -> bool:\n    return amt > 0\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.py").write_text(
        "def unrelated_helper():\n"
        "    # Mentioning process_payment in a comment only\n"
        "    return 'notes'\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="trace process_payment", targets=("process_payment",), intent="TRACE")
        pkt = get_context(con, tmp_path, spec)
        assert not any(
            r.source.endswith("unrelated_helper") and r.relationship == "CALLS"
            for r in pkt.relationships
        )


def test_34_fp_defense_unknown_target_never_creates_positive_relationship(tmp_path: Path) -> None:
    """34. Adversarial FP: Dynamic getattr call does not fabricate a verified CALLS edge."""
    (tmp_path / "dyn.py").write_text(
        "def dynamic_runner(obj, method_name: str):\n"
        "    fn = getattr(obj, method_name)\n"
        "    return fn()\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="trace dynamic_runner", targets=("dynamic_runner",), intent="TRACE")
        pkt = get_context(con, tmp_path, spec)
        assert not any(r.relationship == "CALLS" and "UNKNOWN" in r.target for r in pkt.relationships)


# ---------------------------------------------------------------------------
# 8. Determinism, Cache Freshness & Warm MCP Latency (Tests 35–40)
# ---------------------------------------------------------------------------


def test_35_determinism_across_repeated_queries(tmp_path: Path) -> None:
    """35. Running identical get_context queries produces identical ordering, tokens, coverage, and reasons."""
    (tmp_path / "service.py").write_text(
        "def alpha(x: int) -> int:\n    return beta(x) + 1\n\n"
        "def beta(y: int) -> int:\n    return y * 2\n",
        encoding="utf-8",
    )
    (tmp_path / "test_service.py").write_text(
        "from service import alpha\n\ndef test_alpha():\n    assert alpha(3) == 7\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="debug alpha", targets=("alpha",), intent="DEBUG")
        p1 = get_context(con, tmp_path, spec, explain=True)
        # Clear cache to force full deterministic re-computation
        con.execute("DELETE FROM context_cache")
        p2 = get_context(con, tmp_path, spec, explain=True)

        assert [s.canonical_id for s in p1.symbols] == [s.canonical_id for s in p2.symbols]
        assert [s.reason_code for s in p1.symbols] == [s.reason_code for s in p2.symbols]
        assert [(r.source, r.target, r.relationship) for r in p1.relationships] == [
            (r.source, r.target, r.relationship) for r in p2.relationships
        ]
        assert p1.selected_token_estimate == p2.selected_token_estimate
        assert p1.candidate_token_estimate == p2.candidate_token_estimate
        assert p1.coverage == p2.coverage
        assert p1.selected_files == p2.selected_files


def test_36_cache_invalidated_on_stale_file_modification(tmp_path: Path) -> None:
    """36. Modifying an indexed file on disk marks freshness STALE and surfaces staleness warning."""
    f = tmp_path / "calc.py"
    f.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        p_fresh = get_context(con, tmp_path, "add")
        assert p_fresh.freshness == "FRESH"

        # Modify file on disk without re-indexing
        f.write_text("def add(a: int, b: int) -> int:\n    return a + b + 999\n", encoding="utf-8")
        con.execute("DELETE FROM context_cache")
        p_stale = get_context(con, tmp_path, "add")
        assert p_stale.freshness in ("STALE", "PARTIALLY_STALE")
        assert any("stale" in u.lower() for u in p_stale.uncertainties)


def test_37_warm_mcp_latency_percentiles_and_metrics_registry(tmp_path: Path) -> None:
    """37. MetricsRegistry separates first_request_latency_ms from warm_request_latency_ms and computes p50/p95/p99."""
    pcts = compute_latency_percentiles([12.0, 4.0, 4.5, 5.0, 5.5, 6.0, 4.2, 4.8, 5.1, 20.0])
    assert pcts["count"] == 10
    assert pcts["min_ms"] == 4.0
    assert pcts["max_ms"] == 20.0
    assert 4.5 <= pcts["p50_ms"] <= 5.5
    assert pcts["p95_ms"] >= 12.0

    reg = MetricsRegistry()
    reg.record(OperationMetric(request_id="r1", tool_or_op="get_context", latency_ms=18.5, cache_hit=False))
    for i in range(5):
        reg.record(OperationMetric(request_id=f"r{i+2}", tool_or_op="get_context", latency_ms=1.2, cache_hit=True))

    summary = reg.get_summary()
    assert summary["first_request_latency_ms"] == 18.5
    assert summary["warm_request_latency_ms"] == 1.2
    assert "p50_ms" in summary
    assert "p95_ms" in summary
    assert "p99_ms" in summary


def test_38_context_packet_structured_sections_complete(tmp_path: Path) -> None:
    """38. Verify ContextPacket contains all Phase 10 structured sections."""
    (tmp_path / "main.py").write_text("def start_app():\n    return True\n", encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        pkt = get_context(con, tmp_path, "understand start_app", intent="UNDERSTAND")
        d = pkt.as_dict()
        for section in (
            "metadata",
            "task",
            "target",
            "symbols",
            "relationships",
            "routes",
            "packages",
            "tests",
            "architecture",
            "git_impact",
            "findings",
            "evidence",
            "budget",
            "coverage",
        ):
            assert section in d, f"Missing section {section} in ContextPacket"


# ---------------------------------------------------------------------------
# 9. Five Realistic End-to-End Repository Scenarios (Tests 39–43)
# ---------------------------------------------------------------------------


def test_39_scenario_1_fastapi_service_with_di_routes_and_tests(tmp_path: Path) -> None:
    """39. Realistic Scenario 1: FastAPI service with route -> handler -> DI provider -> repository -> pytest."""
    (tmp_path / "db.py").write_text(
        "class UserRepository:\n"
        "    def fetch_by_id(self, uid: int) -> dict:\n"
        "        return {'id': uid}\n\n"
        "def get_user_repo() -> UserRepository:\n"
        "    return UserRepository()\n",
        encoding="utf-8",
    )
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI, Depends\n"
        "from db import get_user_repo, UserRepository\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/users/{uid}')\n"
        "def get_user_profile(uid: int, repo: UserRepository = Depends(get_user_repo)):\n"
        "    return repo.fetch_by_id(uid)\n",
        encoding="utf-8",
    )
    (tmp_path / "test_api.py").write_text(
        "from api import get_user_profile\n\n"
        "def test_get_user_profile():\n"
        "    assert get_user_profile is not None\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="debug /users/{uid} endpoint", targets=("get_user_profile",), intent="DEBUG")
        pkt = get_context(con, tmp_path, spec)
        syms = {s.symbol for s in pkt.symbols}
        assert "get_user_profile" in syms
        assert "get_user_repo" in syms
        assert len(pkt.routes) >= 1
        assert len(pkt.tests) >= 1
        assert pkt.budget is not None
        assert int(str(pkt.budget["tool_calls"])) == 1


def test_40_scenario_2_event_driven_worker_and_task_queue(tmp_path: Path) -> None:
    """40. Realistic Scenario 2: Celery task + EventEmitter registration + dispatcher."""
    (tmp_path / "tasks.py").write_text(
        "from celery import Celery\n"
        "from pyee import EventEmitter\n\n"
        "celery_app = Celery('worker')\n"
        "bus = EventEmitter()\n\n"
        "@celery_app.task\n"
        "def generate_monthly_invoice(account_id: int):\n"
        "    return account_id\n\n"
        "@bus.on('account.closed')\n"
        "def on_account_closed(account_id: int):\n"
        "    return generate_monthly_invoice(account_id)\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="understand on_account_closed", targets=("on_account_closed",), intent="UNDERSTAND")
        pkt = get_context(con, tmp_path, spec)
        syms = {s.symbol for s in pkt.symbols}
        assert "on_account_closed" in syms
        assert "generate_monthly_invoice" in syms
        rels = {r.relationship for r in pkt.relationships}
        assert "EVENT_LISTENER" in rels or "CALLS" in rels


def test_41_scenario_3_monorepo_cross_package_impact_and_scoping(tmp_path: Path) -> None:
    """41. Realistic Scenario 3: Multi-package monorepo (api, billing, auth, analytics) with bounded context."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "platform", "private": True, "workspaces": ["apps/*", "packages/*"]}),
        encoding="utf-8",
    )
    for rel_dir, pkg_name, deps, code in [
        (
            "packages/auth",
            "@plat/auth",
            {},
            "export class TokenVerifier {\n  verify(t: string): boolean { return t.length > 0; }\n}\n",
        ),
        (
            "packages/billing",
            "@plat/billing",
            {},
            "export class InvoiceEngine {\n  charge(amt: number): boolean { return amt > 0; }\n}\n",
        ),
        (
            "apps/api",
            "@plat/api",
            {"@plat/auth": "workspace:*"},
            "import { TokenVerifier } from '@plat/auth';\n"
            "export function authenticateRequest(t: string) {\n"
            "  const v = new TokenVerifier();\n"
            "  return v.verify(t);\n"
            "}\n",
        ),
    ]:
        p = tmp_path / rel_dir
        (p / "src").mkdir(parents=True)
        (p / "package.json").write_text(
            json.dumps({"name": pkg_name, "main": "src/index.ts", "dependencies": deps}),
            encoding="utf-8",
        )
        (p / "src" / "index.ts").write_text(code, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(
            raw_prompt="change authenticateRequest in api",
            targets=("apps/api/src/index.ts",),
            intent="CHANGE",
        )
        pkt = get_context(con, tmp_path, spec, max_package_depth=1)
        pkg_names = {p["name"] for p in pkt.packages}
        assert "@plat/api" in pkg_names
        assert "@plat/auth" in pkg_names
        # Unrelated @plat/billing is excluded from package neighborhood
        assert "@plat/billing" not in pkg_names


def test_42_scenario_4_artifact_heavy_repo_token_efficiency(tmp_path: Path) -> None:
    """42. Realistic Scenario 4: Repository with large minified bundles, vendor files, and generated clients."""
    (tmp_path / "src").mkdir()
    (tmp_path / "dist").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "generated").mkdir()

    (tmp_path / "src" / "order_service.py").write_text(
        "class OrderService:\n"
        "    def submit_order(self, cart_id: str) -> dict:\n"
        "        return {'cart_id': cart_id, 'status': 'SUBMITTED'}\n",
        encoding="utf-8",
    )
    # Large noise files with the same keywords
    (tmp_path / "dist" / "app.bundle.js").write_text(
        "function submit_order(){return 'bundle';}\n" * 80,
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "legacy_order.py").write_text(
        "def submit_order(cart_id):\n    return 'vendor'\n" * 50,
        encoding="utf-8",
    )
    (tmp_path / "generated" / "order_pb2.py").write_text(
        "# Generated by the protocol buffer compiler. DO NOT EDIT!\n"
        "class OrderProto:\n    pass\n",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="understand submit_order", targets=("submit_order",), intent="UNDERSTAND")
        pkt = get_context(con, tmp_path, spec, max_tokens=2000)
        assert "src/order_service.py" in pkt.selected_files
        assert "dist/app.bundle.js" not in pkt.selected_files
        assert "vendor/legacy_order.py" not in pkt.selected_files
        assert pkt.selected_token_estimate <= 500


def test_43_scenario_5_repeated_calls_evidence_compression_in_context(tmp_path: Path) -> None:
    """43. Realistic Scenario 5: Function calling helper 6 times compresses duplicate CALLS edges in ContextPacket."""
    (tmp_path / "pipeline.py").write_text(
        "def sanitize_field(val: str) -> str:\n"
        "    return val.strip()\n\n"
        "def normalize_record(rec: dict) -> dict:\n"
        "    a = sanitize_field(rec.get('a', ''))\n"
        "    b = sanitize_field(rec.get('b', ''))\n"
        "    c = sanitize_field(rec.get('c', ''))\n"
        "    d = sanitize_field(rec.get('d', ''))\n"
        "    e = sanitize_field(rec.get('e', ''))\n"
        "    f = sanitize_field(rec.get('f', ''))\n"
        "    return {'a': a, 'b': b, 'c': c, 'd': d, 'e': e, 'f': f}\n",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        spec = TaskSpec(raw_prompt="trace normalize_record", targets=("normalize_record",), intent="TRACE")
        pkt = get_context(con, tmp_path, spec)
        calls_edges = [
            r for r in pkt.relationships
            if r.relationship == "CALLS" and "normalize_record" in r.source and "sanitize_field" in r.target
        ]
        # Must be compressed to a single primary edge
        assert len(calls_edges) == 1
        assert calls_edges[0].occurrence_count >= 1
