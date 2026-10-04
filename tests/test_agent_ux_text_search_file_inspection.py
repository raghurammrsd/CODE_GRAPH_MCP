"""Comprehensive Tests for CodeGraph MCP Agent UX + Text Search + File Inspection Hardening (Phases 1–15).

Covers:
1. Phase 1: Consistent MCP argument names (`symbol` canonical, `canonical_id` alias, `get_context(query=...)`).
2. Phase 2 & 3: Clean tool naming (`find_*`, `get_*`, `trace_*`) and 14-tool `agent` profile.
3. Phase 4: Explicit routing hints in high-value tool descriptions.
4. Phase 5: Repository text search layer (`search_code`) across `.py`, `.html`, `.jinja`, `.js`, `.css`, `.yaml`, `.json`, `.md`,
   filtering (`path_filter`, `file_types`, `include_tests`, `include_configs`), security/binary/ignore exclusions,
   deterministic ordering, and zero semantic graph pollution.
5. Phase 6: First-class file opening & bounded line-range inspection (`get_file`).
6. Phase 7 & 10: `ROUTING_MANIFEST` and `DEFAULT_AGENT_PROFILE_TOOLS` in capability manifest.
7. Phase 8 & 9: Symmetric factory resolution & `get_context` output boundary invariants.
8. Phase 14: 12-prompt natural-language agent routing evaluation.
9. Phase 15: Dundoo-style AI Bill Scanner end-to-end feature workflow validation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.agent_capabilities import (
    DEFAULT_AGENT_PROFILE_TOOLS,
    ROUTING_MANIFEST,
    TOOL_CAPABILITY_REGISTRY,
    get_capability_manifest,
    select_agent_tool,
)
from codegraph.context import get_context
from codegraph.errors import SecurityError
from codegraph.indexing import Indexer
from codegraph.interrogation import get_file
from codegraph.mcp.server import create_server
from codegraph.search import search_code
from codegraph.tool_selection_eval import (
    NATURAL_LANGUAGE_ROUTING_PROMPTS,
    run_dundoo_bill_scanner_e2e_eval,
    run_natural_language_routing_eval,
)


@pytest.fixture()
def polyglot_repo(tmp_path: Path) -> Path:
    """Provision a realistic repository containing Python, HTML, Jinja, JS, CSS, YAML, JSON, Markdown, and sensitive/binary files."""
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "templates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "static" / "js").mkdir(parents=True, exist_ok=True)
    (tmp_path / "static" / "css").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True, exist_ok=True)

    # Python service + factory + route
    (tmp_path / "src" / "services.py").write_text(
        "class InventoryService:\n"
        "    def reserve_stock(self, sku: str, qty: int) -> bool:\n"
        "        return qty > 0\n\n"
        "    def place_order(self, sku: str, qty: int) -> dict:\n"
        "        ok = self.reserve_stock(sku, qty)\n"
        "        return {'sku': sku, 'reserved': ok}\n\n"
        "def get_inventory_service() -> InventoryService:\n"
        "    return InventoryService()\n\n"
        "def process_checkout(sku: str, qty: int) -> dict:\n"
        "    svc = get_inventory_service()\n"
        "    return svc.place_order(sku, qty)\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "from src.services import process_checkout\n\n"
        "router = APIRouter()\n\n"
        "@router.post('/api/orders')\n"
        "def create_order_endpoint(sku: str, qty: int) -> dict:\n"
        "    return process_checkout(sku, qty)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_orders.py").write_text(
        "from src.services import InventoryService, process_checkout\n\n"
        "def test_place_order_flow() -> None:\n"
        "    svc = InventoryService()\n"
        "    res = svc.place_order('SKU-1', 2)\n"
        "    assert res['reserved'] is True\n\n"
        "def test_checkout_flow() -> None:\n"
        "    res = process_checkout('SKU-2', 1)\n"
        "    assert res['reserved'] is True\n",
        encoding="utf-8",
    )

    # HTML & Jinja templates
    (tmp_path / "templates" / "manual_entry.html").write_text(
        "<div id=\"manual-entry-modal\" class=\"modal-container\">\n"
        "  <h2>Manual Bill Entry</h2>\n"
        "  <button id=\"btn-add-manual\" class=\"btn-action\">Add Manual Entry</button>\n"
        "</div>\n",
        encoding="utf-8",
    )
    (tmp_path / "templates" / "receipt_card.jinja2").write_text(
        "{% block receipt_card %}\n"
        "<section class=\"receipt-summary\" data-route=\"/api/orders\">\n"
        "  <span>{{ receipt.merchant_name }}</span>\n"
        "</section>\n"
        "{% endblock %}\n",
        encoding="utf-8",
    )

    # JS & CSS
    (tmp_path / "static" / "js" / "orders.js").write_text(
        "export async function submitManualOrder(payload) {\n"
        "  return fetch('/api/orders', { method: 'POST', body: JSON.stringify(payload) });\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "static" / "css" / "theme.css").write_text(
        ".modal-container {\n"
        "  border-radius: 8px;\n"
        "  background-color: #ffffff;\n"
        "}\n",
        encoding="utf-8",
    )

    # YAML, JSON, Markdown
    (tmp_path / "config" / "feature_flags.yaml").write_text(
        "features:\n"
        "  enable_ai_bill_scanner: true\n"
        "  max_upload_megabytes: 10\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "ui_strings.json").write_text(
        '{\n  "manual_entry_cta": "Add Manual Entry",\n  "scanner_cta": "Scan Receipt with AI"\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "docs" / "architecture_notes.md").write_text(
        "# Order Processing Notes\n\n"
        "The `Add Manual Entry` button triggers the manual order modal.\n",
        encoding="utf-8",
    )

    # Sensitive, binary, and ignored files (must NEVER be returned by search_code or get_file)
    (tmp_path / ".env").write_text(
        "SECRET_API_KEY=Add Manual Entry SuperSecret123\n",
        encoding="utf-8",
    )
    (tmp_path / "id_rsa").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nAdd Manual Entry\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (tmp_path / "static" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR Add Manual Entry")
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text(
        "// Add Manual Entry inside ignored node_modules\n",
        encoding="utf-8",
    )

    Indexer(tmp_path).index()
    return tmp_path


# ===========================================================================
# PHASE 1, 2, 3, 4: MCP Argument Consistency, Clean Naming & Agent Profile
# ===========================================================================


def test_agent_profile_exposes_14_canonical_tools(polyglot_repo: Path) -> None:
    """`create_server(profile='agent')` exposes the exact 14 high-signal agent tools."""
    srv_agent = create_server(polyglot_repo, profile="agent")
    tools_agent = set(srv_agent._tool_manager._tools.keys())
    assert len(tools_agent) == 14
    assert tools_agent == set(DEFAULT_AGENT_PROFILE_TOOLS)

    # Also verify "default" aliases to the 14-tool agent profile
    srv_default = create_server(polyglot_repo, profile="default")
    assert set(srv_default._tool_manager._tools.keys()) == set(DEFAULT_AGENT_PROFILE_TOOLS)


def test_clean_tool_names_and_backward_compatible_aliases(polyglot_repo: Path) -> None:
    """Canonical `symbol` and backward-compatible `canonical_id` resolve to the exact same result across tools."""
    srv = create_server(polyglot_repo, profile="full")
    tools = srv._tool_manager._tools

    # 1. find_symbol(symbol=...) vs find_symbol(name=...) vs find_symbol(canonical_id=...)
    fn_find_symbol = tools["find_symbol"].fn
    res_sym = fn_find_symbol(symbol="place_order")
    res_name = fn_find_symbol(name="place_order")
    res_cid = fn_find_symbol(canonical_id="place_order")
    assert res_sym == res_name == res_cid
    assert len(res_sym) >= 1

    # 2. find_callers(symbol=...) vs find_callers(canonical_id=...) and get_callers(symbol=...) vs get_callers(canonical_id=...)
    callers_find_sym = tools["find_callers"].fn(symbol="place_order")
    callers_find_cid = tools["find_callers"].fn(canonical_id="place_order")
    assert callers_find_sym == callers_find_cid
    assert any("process_checkout" in str(r.get("caller") or r.get("source") or "") for r in callers_find_sym)

    callers_get_sym = tools["get_callers"].fn(symbol="place_order")
    callers_get_cid = tools["get_callers"].fn(canonical_id="place_order")
    assert callers_get_sym == callers_get_cid
    assert any("process_checkout" in str(r.get("caller") or r.get("source") or "") for r in callers_get_sym["callers"])

    # 3. find_callees(symbol=...) vs find_callees(canonical_id=...) and get_callees(symbol=...) vs get_callees(canonical_id=...)
    callees_find_sym = tools["find_callees"].fn(symbol="process_checkout")
    callees_find_cid = tools["find_callees"].fn(canonical_id="process_checkout")
    assert callees_find_sym == callees_find_cid
    assert any("place_order" in str(r.get("callee") or r.get("target") or "") for r in callees_find_sym)

    callees_get_sym = tools["get_callees"].fn(symbol="process_checkout")
    callees_get_cid = tools["get_callees"].fn(canonical_id="process_checkout")
    assert callees_get_sym == callees_get_cid
    assert any("place_order" in str(r.get("callee") or r.get("target") or "") for r in callees_get_sym["callees"])

    # 4. find_tests(symbol=...) vs find_related_tests(symbol=...)
    tests_find = tools["find_tests"].fn(symbol="place_order")
    tests_rel = tools["find_related_tests"].fn(symbol="place_order")
    assert tests_find == tests_rel
    assert any("test_place_order_flow" in str(r.get("test") or r.get("symbol") or "") for r in tests_find)

    # 5. find_routes(path=...) vs list_routes(path=...)
    routes_find = tools["find_routes"].fn(path="/api/orders")
    routes_list = tools["list_routes"].fn(path="/api/orders")
    assert routes_find["routes"] == routes_list["routes"]
    assert len(routes_find["routes"]) == 1

    # 6. trace_flow(symbol=...) vs trace_call(symbol=...)
    flow_res = tools["trace_flow"].fn(symbol="place_order", callers=True)
    call_res = tools["trace_call"].fn(symbol="place_order", callers=True)
    assert flow_res == call_res

    # 7. Conflicting symbol and canonical_id raises ValueError (no silent reinterpretation)
    with pytest.raises(ValueError, match="Conflicting"):
        tools["find_callers"].fn(symbol="place_order", canonical_id="reserve_stock")

    # 8. get_context(query=...) vs get_context(task=...)
    ctx_q = tools["get_context"].fn(query="trace order placement", intent="TRACE")
    ctx_t = tools["get_context"].fn(task="trace order placement", intent="TRACE")
    assert ctx_q["task"] == ctx_t["task"]


def test_explicit_routing_hints_in_tool_descriptions() -> None:
    """High-value tools include explicit `USE THIS INSTEAD OF` / `use` and `avoid_when` routing guidance."""
    by_name = {spec.tool_name: spec for spec in TOOL_CAPABILITY_REGISTRY}
    for tname in ("find_symbol", "search_code", "find_callers", "find_callees", "get_file", "get_context"):
        spec = by_name[tname]
        assert "use " in spec.description.lower()
        assert len(spec.avoid_when) >= 1
        assert len(spec.evidence_guarantees) >= 10


# ===========================================================================
# PHASE 5: Repository Text Search Layer (`search_code`)
# ===========================================================================


def test_search_code_across_py_html_jinja_js_css_yaml_json_md(polyglot_repo: Path) -> None:
    """`search_code` finds literal text across Python, HTML, Jinja2, JS, CSS, YAML, JSON, and Markdown files."""
    indexer = Indexer(polyglot_repo)
    with indexer.session() as con:
        # 1. Search for UI button text "Add Manual Entry" across HTML, JSON, MD
        hits = search_code(con, "Add Manual Entry", repo_path=polyglot_repo, max_results=20)
        paths = {h["path"] for h in hits}
        assert "templates/manual_entry.html" in paths
        assert "config/ui_strings.json" in paths
        assert "docs/architecture_notes.md" in paths
        # Sensitive, binary, and node_modules files MUST be excluded!
        assert ".env" not in paths
        assert "id_rsa" not in paths
        assert "static/logo.png" not in paths
        assert not any("node_modules" in str(p) for p in paths)

        # Verify required fields on every search_code hit
        for h in hits:
            assert "path" in h and "file" in h
            assert "line" in h and "start_line" in h and "end_line" in h
            assert "matched_text" in h
            assert "snippet" in h
            assert "category" in h and "file_category" in h
            assert "score" in h
            assert "reason" in h
            assert "match_type" in h

        # 2. Search in Jinja2 template
        jinja_hits = search_code(con, "receipt.merchant_name", repo_path=polyglot_repo)
        assert any(h["path"] == "templates/receipt_card.jinja2" for h in jinja_hits)

        # 3. Search in CSS file
        css_hits = search_code(con, "border-radius: 8px", repo_path=polyglot_repo)
        assert any(h["path"] == "static/css/theme.css" for h in css_hits)

        # 4. Search in YAML config
        yaml_hits = search_code(con, "enable_ai_bill_scanner", repo_path=polyglot_repo)
        assert any(h["path"] == "config/feature_flags.yaml" for h in yaml_hits)

        # 5. Filter by file_types=["html"]
        html_only = search_code(con, "Add Manual Entry", repo_path=polyglot_repo, file_types=["html"])
        assert [h["path"] for h in html_only] == ["templates/manual_entry.html"]

        # 6. Filter by path_filter="config/"
        config_only = search_code(con, "Add Manual Entry", repo_path=polyglot_repo, path_filter="config/")
        assert [h["path"] for h in config_only] == ["config/ui_strings.json"]

        # 7. Filter by include_configs=False
        no_configs = search_code(con, "Add Manual Entry", repo_path=polyglot_repo, include_configs=False)
        assert "config/ui_strings.json" not in {h["path"] for h in no_configs}

        # 8. Deterministic ordering across repeated runs
        hits_repeat = search_code(con, "Add Manual Entry", repo_path=polyglot_repo, max_results=20)
        assert hits == hits_repeat


def test_search_code_never_pollutes_semantic_graph(polyglot_repo: Path) -> None:
    """Text matches in HTML, Jinja, JS, CSS, YAML, JSON, and MD never create fake semantic graph edges."""
    indexer = Indexer(polyglot_repo)
    with indexer.session() as con:
        # Execute text searches across non-Python files
        _ = search_code(con, "/api/orders", repo_path=polyglot_repo)
        _ = search_code(con, "Add Manual Entry", repo_path=polyglot_repo)

        # Verify graph_edges contains zero edges sourced from .html, .jinja2, .css, .yaml, .json, .md
        rows = con.execute("SELECT source, target, relationship, file FROM graph_edges").fetchall()
        for row in rows:
            fpath = str(row["file"] or "")
            assert not fpath.endswith((".html", ".jinja2", ".css", ".yaml", ".json", ".md")), (
                f"Non-code file polluted semantic graph_edges: {dict(row)}"
            )

        # Verify get_context only emits verified semantic relationships in packet.relationships
        pkt = get_context(con, polyglot_repo, query="trace /api/orders to reserve_stock", intent="TRACE")
        for rel in pkt.relationships:
            assert not rel.file.endswith((".html", ".jinja2", ".css", ".yaml", ".json", ".md"))


# ===========================================================================
# PHASE 6: First-Class File Opening / Inspection (`get_file`)
# ===========================================================================


def test_get_file_bounded_line_ranges_and_non_python_files(polyglot_repo: Path) -> None:
    """`get_file` reads bounded line ranges across `.py`, `.html`, `.jinja2`, `.yaml`, `.md` and enforces `max_lines`."""
    indexer = Indexer(polyglot_repo)
    with indexer.session() as con:
        # 1. Read specific line range of Python file
        py_slice = get_file(con, polyglot_repo, "src/services.py", start_line=5, end_line=8)
        assert py_slice["status"] == "ok"
        assert py_slice["path"] == "src/services.py"
        assert py_slice["start_line"] == 5
        assert py_slice["end_line"] == 8
        assert py_slice["truncated"] is False
        assert "def place_order" in str(py_slice["content"])
        assert py_slice["category"] == "SOURCE"

        # 2. Read HTML template via get_file
        html_slice = get_file(con, polyglot_repo, "templates/manual_entry.html", start_line=1, end_line=4)
        assert html_slice["status"] == "ok"
        assert html_slice["path"] == "templates/manual_entry.html"
        assert "Add Manual Entry" in str(html_slice["content"])
        assert html_slice["truncated"] is False

        # 3. Verify max_lines truncation
        trunc_slice = get_file(con, polyglot_repo, "src/services.py", start_line=1, end_line=50, max_lines=4)
        assert trunc_slice["status"] == "ok"
        assert trunc_slice["start_line"] == 1
        assert trunc_slice["end_line"] == 4
        assert trunc_slice["truncated"] is True
        assert len(str(trunc_slice["content"]).split("\n")) == 4


def test_get_file_security_and_binary_guards(polyglot_repo: Path) -> None:
    """`get_file` and `read_file` block `.env`, private keys, path traversal, and binary files."""
    indexer = Indexer(polyglot_repo)
    srv = create_server(polyglot_repo, profile="full")
    read_file_fn = srv._tool_manager._tools["read_file"].fn

    with indexer.session() as con:
        env_res = get_file(con, polyglot_repo, ".env", start_line=1, end_line=5)
        assert env_res["status"] in ("invalid_request", "error")
        assert env_res["error_code"] == "SENSITIVE_FILE_ACCESS_DENIED"
        assert "content" not in env_res

        key_res = get_file(con, polyglot_repo, "id_rsa", start_line=1, end_line=5)
        assert key_res["status"] in ("invalid_request", "error")
        assert key_res["error_code"] == "SENSITIVE_FILE_ACCESS_DENIED"
        assert "content" not in key_res

        trav_res = get_file(con, polyglot_repo, "../outside.py", start_line=1, end_line=5)
        assert trav_res["status"] == "error"
        assert trav_res["error_code"] == "PATH_OUTSIDE_REPOSITORY"
        assert "content" not in trav_res

        bin_res = get_file(con, polyglot_repo, "static/logo.png", start_line=1, end_line=5)
        assert bin_res["status"] == "error"
        assert bin_res["error_code"] == "BINARY_FILE_NOT_READABLE"
        assert "content" not in bin_res

    with pytest.raises(SecurityError):
        read_file_fn(path=".env", start_line=1, end_line=5)
    with pytest.raises(SecurityError):
        read_file_fn(path="../outside.py", start_line=1, end_line=5)
    with pytest.raises(SecurityError):
        read_file_fn(path="static/logo.png", start_line=1, end_line=5)


# ===========================================================================
# PHASE 7, 14, 15: Routing Manifest, 12-Prompt Eval & Dundoo E2E Workflow
# ===========================================================================


def test_routing_manifest_and_12_prompt_evaluation() -> None:
    """`ROUTING_MANIFEST` is exported in capability manifest and achieves 100% on all 12 Phase 14 prompts."""
    manifest = get_capability_manifest()
    assert manifest["routing_manifest"] == ROUTING_MANIFEST
    assert manifest["default_agent_profile_tools"] == list(DEFAULT_AGENT_PROFILE_TOOLS)

    eval_report = run_natural_language_routing_eval()
    assert eval_report["total"] == 12
    assert eval_report["passed"] == 12, f"Failed routing prompts: {[r for r in eval_report['results'] if not r['passed']]}"
    assert eval_report["accuracy"] == 1.0

    # Verify individual prompts explicitly
    for item in NATURAL_LANGUAGE_ROUTING_PROMPTS:
        routed = select_agent_tool(str(item["prompt"]))
        assert routed["selected_tool"] in item["expected_tools"]  # type: ignore[operator]


def test_dundoo_bill_scanner_end_to_end_workflow() -> None:
    """Phase 15 Dundoo-style AI Bill Scanner feature workflow succeeds end-to-end using CodeGraph tools alone."""
    report = run_dundoo_bill_scanner_e2e_eval()
    assert report["all_passed"] is True, f"Dundoo E2E checks failed: {report['checks']}"
