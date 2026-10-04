"""Regression tests for CodeGraph Engine v2.1.5 external repository evaluation fixes.

Covers all 4 concrete issues discovered during external Python repository testing:
- ISSUE 1: MCP Argument Consistency (`symbol` primary + `canonical_id`/`name` aliases across symbol tools)
- ISSUE 2: `get_context` Argument Clarity (`query` primary + `task` string/dict compatibility alias)
- ISSUE 3: Symmetric Factory Resolution (`InventoryService.place_order` forward/reverse/path agreement + epistemic honesty)
- ISSUE 4: `get_context` Output Boundary (`max_tokens`, `max_files`, `max_lines`, hard limits, truncation metadata)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codegraph.context import get_context
from codegraph.graph.traversal import find_callees, find_callers
from codegraph.indexing import Indexer
from codegraph.interrogation import (
    get_callees,
    get_callers,
    trace_path,
)
from codegraph.mcp.server import create_server
from codegraph.optimizer import (
    HARD_MAX_FILES,
    HARD_MAX_LINES,
    HARD_MAX_TOKENS,
)


def _setup_inventory_repo(tmp_path: Path) -> Path:
    """Create and index a realistic multi-file Python repository with factory, service, callers, and dynamic dispatch."""
    repo = tmp_path / "inventory_repo"
    pkg = repo / "app"
    pkg.mkdir(parents=True)
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)

    (pkg / "__init__.py").write_text("", encoding="utf-8")

    # 1. Service module with InventoryService.place_order and same-file factory
    (pkg / "services.py").write_text(
        '''"""Inventory domain service and factories."""
from __future__ import annotations


class InventoryService:
    """Manages warehouse inventory reservations and order placement."""

    def __init__(self, db_url: str = "sqlite://") -> None:
        self.db_url = db_url

    def place_order(self, sku: str, quantity: int) -> dict[str, object]:
        """Place an inventory order for the given SKU and quantity."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return {"sku": sku, "quantity": quantity, "status": "RESERVED"}

    def cancel_order(self, order_id: str) -> bool:
        return True


class MockInventoryService:
    """Alternative service implementation for ambiguous factory tests."""

    def place_order(self, sku: str, quantity: int) -> dict[str, object]:
        return {"sku": sku, "quantity": quantity, "status": "MOCK"}


def get_inventory_service(db_url: str = "sqlite://") -> InventoryService:
    """Cross-file factory returning InventoryService via local variable."""
    svc = InventoryService(db_url=db_url)
    return svc


def create_direct_inventory_service() -> InventoryService:
    """Factory returning InventoryService directly."""
    return InventoryService()


def get_ambiguous_service(use_mock: bool):
    """Ambiguous factory returning different classes across branches."""
    if use_mock:
        return MockInventoryService()
    return InventoryService()


def get_dynamic_service(registry: object, name: str):
    """Dynamic factory using getattr that cannot be statically proven."""
    factory_fn = getattr(registry, name)
    return factory_fn()


def same_file_caller(sku: str) -> dict[str, object]:
    """Caller in the same file using a factory function."""
    local_svc = create_direct_inventory_service()
    return local_svc.place_order(sku, 1)
''',
        encoding="utf-8",
    )

    # 2. Cross-file callers using local factory binding, chained factory call, self.<attr> factory binding, and dynamic/ambiguous calls
    (pkg / "handlers.py").write_text(
        '''"""Order handlers invoking InventoryService through factories."""
from __future__ import annotations

from app.services import (
    get_ambiguous_service,
    get_dynamic_service,
    get_inventory_service,
)


def checkout_endpoint(sku: str, quantity: int) -> dict[str, object]:
    """Cross-file caller using local variable assigned from factory."""
    service = get_inventory_service("postgres://prod")
    return service.place_order(sku, quantity)


def quick_buy_endpoint(sku: str) -> dict[str, object]:
    """Cross-file caller using chained factory call."""
    return get_inventory_service("postgres://prod").place_order(sku, 1)


class OrderWorkflow:
    """Workflow class storing factory result on self.inventory."""

    def __init__(self) -> None:
        self.inventory = get_inventory_service("postgres://workflow")

    def execute_order(self, sku: str, qty: int) -> dict[str, object]:
        return self.inventory.place_order(sku, qty)


def ambiguous_order_caller(sku: str, flag: bool) -> dict[str, object]:
    """Caller using an ambiguous conditional factory."""
    svc = get_ambiguous_service(flag)
    return svc.place_order(sku, 2)


def dynamic_order_caller(registry: object, hook_name: str, sku: str) -> object:
    """Caller using a genuinely dynamic getattr factory."""
    dyn_svc = get_dynamic_service(registry, hook_name)
    return dyn_svc.place_order(sku, 3)
''',
        encoding="utf-8",
    )

    # 3. Test file covering InventoryService.place_order and checkout_endpoint
    (tests_dir / "test_orders.py").write_text(
        '''"""Tests for order placement."""
from app.handlers import checkout_endpoint
from app.services import InventoryService


def test_place_order_direct() -> None:
    svc = InventoryService()
    res = svc.place_order("SKU-100", 2)
    assert res["status"] == "RESERVED"


def test_checkout_endpoint_flow() -> None:
    res = checkout_endpoint("SKU-200", 5)
    assert res["sku"] == "SKU-200"
''',
        encoding="utf-8",
    )

    Indexer(repo).index()
    return repo


def _get_mcp_tool_fn(server: Any, name: str) -> Any:
    tools = getattr(server._tool_manager, "_tools", {})
    assert name in tools, f"Tool {name} not registered on server"
    return tools[name].fn


def _as_dict(val: Any) -> Any:
    if isinstance(val, str):
        return json.loads(val)
    assert isinstance(val, (dict, list))
    return val


# ===========================================================================
# ISSUE 1 — MCP ARGUMENT CONSISTENCY
# ===========================================================================


def test_issue1_symbol_and_canonical_id_consistency_across_all_tools(tmp_path: Path) -> None:
    """Prove `symbol` is canonical primary input and `canonical_id` (and `name`) resolve identically across all symbol tools."""
    repo = _setup_inventory_repo(tmp_path)
    srv = create_server(repo, profile="full")

    # Resolve canonical ID first using `symbol` and `canonical_id` and `name`
    resolve_fn = _get_mcp_tool_fn(srv, "resolve_symbol")
    res_by_symbol = _as_dict(resolve_fn(symbol="InventoryService.place_order"))
    res_by_cid_alias = _as_dict(resolve_fn(canonical_id="InventoryService.place_order"))
    res_by_name_alias = _as_dict(resolve_fn(name="InventoryService.place_order"))
    assert res_by_symbol == res_by_cid_alias == res_by_name_alias
    canonical_id = res_by_symbol["symbol"]["canonical_id"]
    assert canonical_id.endswith("InventoryService.place_order")

    # Also test passing the full canonical_id via `symbol=` vs `canonical_id=`
    assert _as_dict(resolve_fn(symbol=canonical_id)) == _as_dict(resolve_fn(canonical_id=canonical_id))

    # Tools accepting both `symbol` and `canonical_id`:
    symbol_tools_with_aliases: list[tuple[str, dict[str, Any]]] = [
        ("get_symbol", {}),
        ("find_symbol", {}),
        ("find_references", {}),
        ("get_references", {}),
        ("get_callers", {}),
        ("get_callees", {}),
        ("find_callers", {"max_results": 25}),
        ("find_callees", {"max_results": 25}),
        ("get_call_graph", {"depth": 2, "max_results": 25}),
        ("find_related_tests", {"max_results": 10}),
        ("analyze_impact", {"max_depth": 2}),
        ("trace_call", {"depth": 2, "callers": True}),
        ("get_imports", {}),
        ("get_dependents", {}),
    ]

    for tool_name, extra_kwargs in symbol_tools_with_aliases:
        fn = _get_mcp_tool_fn(srv, tool_name)
        # 1. Qualified name via `symbol` vs `canonical_id`
        out_sym = _as_dict(fn(symbol="InventoryService.place_order", **extra_kwargs))
        out_cid = _as_dict(fn(canonical_id="InventoryService.place_order", **extra_kwargs))
        assert out_sym == out_cid, f"Mismatch between symbol and canonical_id on {tool_name} (qualified name)"

        # 2. Full canonical_id via `symbol` vs `canonical_id`
        out_full_sym = _as_dict(fn(symbol=canonical_id, **extra_kwargs))
        out_full_cid = _as_dict(fn(canonical_id=canonical_id, **extra_kwargs))
        assert out_full_sym == out_full_cid, f"Mismatch between symbol and canonical_id on {tool_name} (full canonical_id)"


def test_issue1_conflicting_or_empty_symbol_arguments_fail_closed(tmp_path: Path) -> None:
    """Ensure conflicting `symbol` vs `canonical_id` or empty inputs raise ValueError without silent reinterpretation."""
    repo = _setup_inventory_repo(tmp_path)
    srv = create_server(repo, profile="full")

    for tool_name in (
        "resolve_symbol",
        "get_symbol",
        "find_symbol",
        "find_references",
        "get_references",
        "get_callers",
        "get_callees",
        "find_callers",
        "find_callees",
        "get_call_graph",
        "find_related_tests",
        "analyze_impact",
        "trace_call",
    ):
        fn = _get_mcp_tool_fn(srv, tool_name)
        # Empty input must fail closed
        with pytest.raises(ValueError, match="requires a non-empty"):
            fn()
        with pytest.raises(ValueError, match="requires a non-empty"):
            fn(symbol="   ")
        # Conflicting symbol and canonical_id must fail closed
        with pytest.raises(ValueError, match="Conflicting"):
            fn(symbol="InventoryService.place_order", canonical_id="checkout_endpoint")

    # trace_path conflict & empty validation
    trace_path_fn = _get_mcp_tool_fn(srv, "trace_path")
    with pytest.raises(ValueError, match="requires a non-empty"):
        trace_path_fn(from_symbol="", to_symbol="InventoryService.place_order")
    with pytest.raises(ValueError, match="Conflicting"):
        trace_path_fn(
            from_symbol="checkout_endpoint",
            start_symbol="quick_buy_endpoint",
            to_symbol="InventoryService.place_order",
        )
    with pytest.raises(ValueError, match="Conflicting"):
        trace_path_fn(
            from_symbol="checkout_endpoint",
            to_symbol="InventoryService.place_order",
            target_symbol="InventoryService.cancel_order",
        )


# ===========================================================================
# ISSUE 2 — get_context ARGUMENT CLARITY
# ===========================================================================


def test_issue2_get_context_query_and_task_aliases(tmp_path: Path) -> None:
    """Prove `get_context`, `compile_task`, and `plan_retrieval` accept `query` (primary) and `task` (string or TaskSpec dict)."""
    repo = _setup_inventory_repo(tmp_path)
    srv = create_server(repo, profile="full")

    get_context_fn = _get_mcp_tool_fn(srv, "get_context")
    compile_task_fn = _get_mcp_tool_fn(srv, "compile_task")
    plan_retrieval_fn = _get_mcp_tool_fn(srv, "plan_retrieval")

    prompt = "Trace how checkout_endpoint calls InventoryService.place_order"

    # 1. Primary `query` parameter vs `task` string alias on MCP server
    ctx_via_query = _as_dict(get_context_fn(query=prompt, intent="TRACE", max_tokens=2000))
    ctx_via_task = _as_dict(get_context_fn(task=prompt, intent="TRACE", max_tokens=2000))
    assert ctx_via_query["symbols"] == ctx_via_task["symbols"]
    assert ctx_via_query["relationships"] == ctx_via_task["relationships"]
    assert ctx_via_query["selected_tokens"] == ctx_via_task["selected_tokens"]

    # 2. Structured TaskSpec dict via `task`
    structured_spec = {
        "raw_task": prompt,
        "intent": "TRACE",
        "targets": ["checkout_endpoint", "InventoryService.place_order"],
    }
    ctx_via_dict = _as_dict(get_context_fn(task=structured_spec, max_tokens=2000))
    assert len(ctx_via_dict["symbols"]) >= 1
    assert ctx_via_dict["selected_tokens"] <= 2000

    # 3. Direct Python API `get_context(con, repo, query=...)` and `get_context(con, repo, task=...)`
    with Indexer(repo).session() as con:
        direct_query_pkt = get_context(con, repo, query=prompt, intent="TRACE", max_tokens=2000).as_dict()
        direct_task_pkt = get_context(con, repo, task=prompt, intent="TRACE", max_tokens=2000).as_dict()
    assert direct_query_pkt["symbols"] == direct_task_pkt["symbols"]

    # 4. compile_task and plan_retrieval with `query` vs `task`
    ct_q = _as_dict(compile_task_fn(query=prompt))
    ct_t = _as_dict(compile_task_fn(task=prompt))
    assert ct_q["task_spec"] == ct_t["task_spec"]

    pr_q = _as_dict(plan_retrieval_fn(query=prompt))
    pr_t = _as_dict(plan_retrieval_fn(task=prompt))
    assert pr_q == pr_t

    # 5. Validation errors when neither is provided or when `query` and `task` conflict
    with pytest.raises(ValueError, match="Either 'query' or 'task'"):
        get_context_fn()
    with pytest.raises(ValueError, match="Either 'query' or 'task'"):
        get_context_fn(query="   ")
    with pytest.raises(ValueError, match="Conflicting"):
        get_context_fn(query="Debug checkout_endpoint", task="Debug cancel_order")


# ===========================================================================
# ISSUE 3 — SYMMETRIC FACTORY RESOLUTION
# ===========================================================================


def test_issue3_symmetric_factory_resolution_for_inventory_service_place_order(tmp_path: Path) -> None:
    """Verify forward, reverse, and path traversal agree on HIGH confidence DATAFLOW_VERIFIED CALLS for factory-bound calls."""
    repo = _setup_inventory_repo(tmp_path)

    with Indexer(repo).session() as con:
        # 1. Reverse traversal: get_callers & find_callers on InventoryService.place_order
        callers_res = get_callers(con, repo, symbol="InventoryService.place_order")
        assert callers_res["status"] == "ok"
        caller_map = {c["canonical_id"]: c for c in callers_res["callers"]}

        expected_verified_callers = {
            "app.handlers.checkout_endpoint": "DATAFLOW_VERIFIED",
            "app.handlers.quick_buy_endpoint": "DATAFLOW_VERIFIED",
            "app.handlers.OrderWorkflow.execute_order": "DATAFLOW_VERIFIED",
            "app.services.same_file_caller": "DATAFLOW_VERIFIED",
            "tests.test_orders.test_place_order_direct": "DATAFLOW_VERIFIED",
        }
        for caller_cid, expected_ev in expected_verified_callers.items():
            assert caller_cid in caller_map, f"Expected verified caller {caller_cid} in get_callers: {caller_map}"
            edge = caller_map[caller_cid]
            assert edge["confidence"] == "HIGH", f"Caller {caller_cid} should have HIGH confidence, got {edge}"
            assert edge["relationship"] == "CALLS", f"Caller {caller_cid} should have CALLS relationship, got {edge}"
            assert edge["evidence_class"] == expected_ev, f"Caller {caller_cid} should have {expected_ev}, got {edge}"

        # Verify find_callers matches get_callers symmetry
        f_callers = find_callers(con, "InventoryService.place_order")
        f_caller_map = {c["canonical_id"]: c for c in f_callers}
        for caller_cid, expected_ev in expected_verified_callers.items():
            assert caller_cid in f_caller_map, f"Expected {caller_cid} in find_callers: {f_caller_map}"
            assert f_caller_map[caller_cid]["confidence"] == "HIGH"
            assert f_caller_map[caller_cid]["relationship"] == "CALLS"
            assert f_caller_map[caller_cid]["evidence_class"] == expected_ev

        # 2. Forward traversal: find_callees & get_callees on each caller must symmetrically report InventoryService.place_order with HIGH confidence
        for caller_name in ("checkout_endpoint", "quick_buy_endpoint", "OrderWorkflow.execute_order", "same_file_caller"):
            callees_res = get_callees(con, repo, symbol=caller_name)
            assert callees_res["status"] == "ok"
            place_order_edges = [
                c for c in callees_res["callees"]
                if str(c.get("callee", "")).endswith("InventoryService.place_order")
                or str(c.get("target_symbol_id", "")).endswith("InventoryService.place_order")
            ]
            assert len(place_order_edges) == 1, f"Expected 1 verified place_order edge in get_callees({caller_name}), got {callees_res['callees']}"
            fwd_edge = place_order_edges[0]
            assert fwd_edge["confidence"] == "HIGH"
            assert fwd_edge["relationship"] == "CALLS"
            assert fwd_edge["evidence_class"] == "DATAFLOW_VERIFIED"

            f_callees = find_callees(con, caller_name)
            f_place_order = [
                c for c in f_callees
                if str(c.get("callee", "")).endswith("InventoryService.place_order")
                or str(c.get("target_symbol_id", "")).endswith("InventoryService.place_order")
            ]
            assert len(f_place_order) == 1, f"Expected 1 verified place_order edge in find_callees({caller_name}), got {f_callees}"
            assert f_place_order[0]["confidence"] == "HIGH"
            assert f_place_order[0]["relationship"] == "CALLS"
            assert f_place_order[0]["evidence_class"] == "DATAFLOW_VERIFIED"

        # 3. Path traversal: trace_path from checkout_endpoint to InventoryService.place_order
        path_res = trace_path(
            con,
            repo,
            from_symbol="checkout_endpoint",
            to_symbol="InventoryService.place_order",
        )
        assert path_res["status"] == "ok"
        assert path_res["path_length"] >= 1
        assert any(
            step["relationship"] == "CALLS"
            and step["confidence"] == "HIGH"
            and step["evidence_class"] == "DATAFLOW_VERIFIED"
            for step in path_res["path"]
        )


def test_issue3_epistemic_honesty_for_dynamic_and_ambiguous_factories(tmp_path: Path) -> None:
    """Ensure genuinely dynamic or ambiguous factories remain UNKNOWN and are NEVER upgraded to HIGH confidence CALLS."""
    repo = _setup_inventory_repo(tmp_path)

    with Indexer(repo).session() as con:
        # 1. Dynamic factory caller (`getattr(registry, name)()`)
        dyn_callees = get_callees(con, repo, symbol="dynamic_order_caller")["callees"]
        dyn_place_order = [c for c in dyn_callees if "place_order" in c["callee"]]
        assert len(dyn_place_order) >= 1
        for edge in dyn_place_order:
            assert edge["confidence"] == "UNKNOWN"
            assert edge["evidence_class"] == "UNKNOWN"
            assert edge["relationship"] != "CALLS"

        # 2. Ambiguous conditional factory caller (`if use_mock: MockInventoryService() else: InventoryService()`)
        amb_callees = get_callees(con, repo, symbol="ambiguous_order_caller")["callees"]
        amb_place_order = [c for c in amb_callees if "place_order" in c["callee"]]
        assert len(amb_place_order) >= 1
        for edge in amb_place_order:
            assert edge["confidence"] == "UNKNOWN"
            assert edge["evidence_class"] == "UNKNOWN"
            assert edge["relationship"] != "CALLS"

        # 3. Neither dynamic_order_caller nor ambiguous_order_caller may appear as a HIGH confidence caller of InventoryService.place_order
        callers_res = get_callers(con, repo, symbol="InventoryService.place_order")
        high_callers = {c["canonical_id"] for c in callers_res["callers"] if c["confidence"] == "HIGH"}
        assert "app.handlers.dynamic_order_caller" not in high_callers
        assert "app.handlers.ambiguous_order_caller" not in high_callers


# ===========================================================================
# ISSUE 4 — get_context OUTPUT BOUNDARY
# ===========================================================================


def test_issue4_get_context_default_and_tight_budget_enforcement(tmp_path: Path) -> None:
    """Verify `get_context` respects default and tight `max_tokens`, `max_files`, `max_lines` and populates budget metadata."""
    repo = _setup_inventory_repo(tmp_path)
    srv = create_server(repo, profile="full")
    get_context_fn = _get_mcp_tool_fn(srv, "get_context")

    # 1. Default MCP budget invocation
    default_pkt = _as_dict(
        get_context_fn(
            query="Trace checkout_endpoint to InventoryService.place_order",
            intent="TRACE",
        )
    )
    for required_meta_key in (
        "selected_tokens",
        "candidate_tokens",
        "selected_files",
        "selected_lines",
        "coverage_score",
        "truncated",
    ):
        assert required_meta_key in default_pkt, f"Missing {required_meta_key} at top level of ContextPacket"
        assert required_meta_key in default_pkt["metadata"], f"Missing {required_meta_key} in metadata"
        assert required_meta_key in default_pkt["budget"], f"Missing {required_meta_key} in budget"

    assert default_pkt["selected_tokens"] <= 4000
    assert len(default_pkt["selected_files"]) <= 15
    assert default_pkt["selected_lines"] <= 500
    assert 0.0 <= default_pkt["coverage_score"] <= 1.0
    assert isinstance(default_pkt["truncated"], bool)

    # 2. Tight budget invocation forcing truncation while preserving target symbol and epistemic state
    tight_pkt = _as_dict(
        get_context_fn(
            query="InventoryService.place_order",
            intent="DEBUG",
            max_tokens=180,
            max_files=1,
            max_lines=25,
        )
    )
    assert tight_pkt["selected_tokens"] <= 180
    assert len(tight_pkt["selected_files"]) <= 1
    assert tight_pkt["selected_lines"] <= 25
    assert tight_pkt["truncated"] is True
    assert len(tight_pkt["files"]) <= 1
    # Target symbol must still be preserved
    assert len(tight_pkt["symbols"]) >= 1
    assert any("place_order" in s["symbol"] for s in tight_pkt["symbols"])


def test_issue4_oversized_candidate_set_clamped_before_serialization(tmp_path: Path) -> None:
    """Verify an oversized repository with many candidate files/lines is bounded by hard limits before serialization."""
    repo = tmp_path / "large_repo"
    pkg = repo / "bigpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    # Generate 35 modules each defining a function that calls a central hub function with large docstrings/bodies
    hub_lines = [
        "def central_hub(payload: dict[str, object]) -> dict[str, object]:",
        '    """Central hub function called by 35 modules."""',
    ]
    for i in range(40):
        hub_lines.append(f"    step_{i} = payload.get('key_{i}', {i})")
    hub_lines.append("    return payload")
    (pkg / "hub.py").write_text("\n".join(hub_lines) + "\n", encoding="utf-8")

    for mod_idx in range(35):
        body_lines = [
            "from bigpkg.hub import central_hub",
            "",
            f"def caller_module_{mod_idx}(data: dict[str, object]) -> dict[str, object]:",
            f'    """Caller {mod_idx} invoking central_hub with multi-line body."""',
        ]
        for line_idx in range(30):
            body_lines.append(f"    local_val_{line_idx} = {mod_idx * 100 + line_idx}")
        body_lines.append("    return central_hub(data)")
        (pkg / f"mod_{mod_idx:02d}.py").write_text("\n".join(body_lines) + "\n", encoding="utf-8")

    Indexer(repo).index()

    with Indexer(repo).session() as con:
        # Request with huge budget parameters exceeding hard caps; optimizer must clamp to hard safety caps
        pkt = get_context(
            con,
            repo,
            query="central_hub",
            intent="IMPACT",
            max_tokens=999_999,
            max_files=999,
            max_lines=999_999,
        ).as_dict()

        assert pkt["selected_tokens"] <= HARD_MAX_TOKENS
        assert len(pkt["selected_files"]) <= HARD_MAX_FILES
        assert pkt["selected_lines"] <= HARD_MAX_LINES

        # Request with explicit max_files=4, max_lines=80
        bounded_pkt = get_context(
            con,
            repo,
            query="central_hub",
            intent="IMPACT",
            max_tokens=1500,
            max_files=4,
            max_lines=80,
        ).as_dict()

        assert bounded_pkt["selected_tokens"] <= 1500
        assert len(bounded_pkt["selected_files"]) <= 4
        assert bounded_pkt["selected_lines"] <= 80
        assert bounded_pkt["truncated"] is True
        assert bounded_pkt["candidate_tokens"] > bounded_pkt["selected_tokens"]

        # Invalid non-positive budgets must raise ValueError
        with pytest.raises(ValueError, match="must be positive integers"):
            get_context(con, repo, query="central_hub", max_tokens=0)
        with pytest.raises(ValueError, match="must be positive integers"):
            get_context(con, repo, query="central_hub", max_files=0)
        with pytest.raises(ValueError, match="must be positive integers"):
            get_context(con, repo, query="central_hub", max_lines=-5)


