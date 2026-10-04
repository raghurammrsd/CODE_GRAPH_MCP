"""Comprehensive regression test suite for Phase 3: Conservative Binding + Data-Flow.

Tests required by specification:
1. local shadowing: inner lexical scope assignment shadows outer scope
2. sequential reassignment: source-order awareness resolves to earlier vs later definition based on line
3. conditional ambiguity: branching/conditional assignments remain POSSIBLE/UNKNOWN
4. nested scopes: resolution traverses upward through enclosing scopes
5. unknown attribute base: ungrounded base objects return UNKNOWN rather than guessing
6. cross-file scope isolation: bindings in file A never pollute or resolve in file B
7. RESOLVES_TO traversal policy: RESOLVES_TO is an identity/binding edge, not a generic CALLS edge
8. JS/TS scope isolation: top-level vs function-scoped bindings in JS/TS
9. Chained alias resolution: a = target; b = a; c = b with cycle protection
10. Dictionary and list subscript dispatch: handlers["key"] and handlers[0]
11. Route handler aliasing: route handlers referencing aliases resolve to concrete symbol
"""
from __future__ import annotations

from pathlib import Path

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.graph.models import GraphSeedPolicy
from codegraph.indexing import Indexer
from codegraph.interrogation import list_routes


def test_local_shadowing(tmp_path: Path) -> None:
    """Verify inner function scope assignment shadows module-level assignment."""
    src = tmp_path / "shadowing.py"
    src.write_text(
        """
def target_global():
    pass

def target_local():
    pass

handler = target_global

def run():
    handler = target_local
    handler()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Find RESOLVES_TO edges for handler in run vs module
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason "
            "FROM graph_edges WHERE relationship='RESOLVES_TO' ORDER BY start_line ASC"
        ).fetchall()

        assert len(edges) >= 2
        # Module-level handler resolves to target_global
        mod_edge = [e for e in edges if e["source"] == "shadowing.handler"][0]
        assert mod_edge["target"] == "shadowing.target_global"
        assert mod_edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        # Inner-level handler in run resolves to target_local (shadowing module-level)
        local_edge = [e for e in edges if e["source"] == "shadowing.run.handler"][0]
        assert local_edge["target"] == "shadowing.target_local"
        assert local_edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_sequential_reassignment(tmp_path: Path) -> None:
    """Verify source-order awareness: earlier calls resolve to earlier bindings, later to later."""
    src = tmp_path / "sequential.py"
    src.write_text(
        """
def handler_one():
    pass

def handler_two():
    pass

h = handler_one
h()

h = handler_two
h()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        refs = con.execute(
            "SELECT target_symbol_id, start_line FROM 'references' "
            "WHERE relationship='CALLS' ORDER BY start_line ASC"
        ).fetchall()

        assert len(refs) == 2
        assert refs[0]["target_symbol_id"] == "sequential.handler_one"
        assert refs[0]["start_line"] == 9
        assert refs[1]["target_symbol_id"] == "sequential.handler_two"
        assert refs[1]["start_line"] == 12


def test_conditional_ambiguity_remains_possible_or_unknown(tmp_path: Path) -> None:
    """Verify branching/conditional assignments are marked POSSIBLE or UNKNOWN."""
    src = tmp_path / "conditional.py"
    src.write_text(
        """
def branch_a():
    pass

def branch_b():
    pass

cond = True
if cond:
    h = branch_a
else:
    h = branch_b

h()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Since h is conditionally assigned, it must NOT produce an authoritative AST_VERIFIED or DATAFLOW_VERIFIED CALLS edge
        calls = con.execute(
            "SELECT source, target, relationship, evidence_class "
            "FROM graph_edges WHERE relationship='CALLS' AND source LIKE 'conditional%'"
        ).fetchall()

        for c in calls:
            assert c["target"] not in ("conditional.branch_a", "conditional.branch_b")

        # In local_bindings, is_conditional should be recorded
        b_rows = con.execute("SELECT target_name, is_conditional FROM local_bindings WHERE target_name='h'").fetchall()
        assert len(b_rows) >= 2
        for b in b_rows:
            assert b["is_conditional"] == 1


def test_nested_scopes(tmp_path: Path) -> None:
    """Verify resolution traverses upward through enclosing scopes when not shadowed."""
    src = tmp_path / "nested.py"
    src.write_text(
        """
def shared_service():
    pass

service = shared_service

class MyController:
    def execute(self):
        # Uses service from module scope
        service()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        call_refs = con.execute(
            "SELECT target_symbol_id, source_symbol_id FROM 'references' "
            "WHERE relationship='CALLS' AND source_symbol_id='nested.MyController.execute'"
        ).fetchall()

        assert len(call_refs) == 1
        assert call_refs[0]["target_symbol_id"] == "nested.shared_service"


def test_unknown_attribute_base(tmp_path: Path) -> None:
    """Verify ungrounded base objects return UNKNOWN rather than guessing or fabricating edges."""
    src = tmp_path / "ungrounded.py"
    src.write_text(
        """
def process(dynamic_param):
    # dynamic_param is an ungrounded parameter
    handler = dynamic_param.mystery_method
    handler()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Must NOT produce a RESOLVES_TO edge or CALLS edge to mystery_method
        edges = con.execute(
            "SELECT target, relationship FROM graph_edges WHERE target LIKE '%mystery_method%'"
        ).fetchall()
        assert len(edges) == 0


def test_cross_file_scope_isolation(tmp_path: Path) -> None:
    """Verify variable bindings in file A are not visible in file B unless explicitly imported."""
    (tmp_path / "file_a.py").write_text(
        """
def secret_handler():
    pass

handler = secret_handler
""",
        encoding="utf-8",
    )

    (tmp_path / "file_b.py").write_text(
        """
# Does not import handler from file_a
def call_something():
    handler()  # Unbound identifier in file_b
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # handler() in file_b must NOT resolve to secret_handler in file_a
        refs = con.execute(
            "SELECT target_symbol_id FROM 'references' "
            "WHERE path='file_b.py' AND relationship='CALLS'"
        ).fetchall()

        for r in refs:
            assert r["target_symbol_id"] != "file_a.secret_handler"


def test_resolves_to_traversal_policy() -> None:
    """Verify RESOLVES_TO is an identity/binding edge, not a generic reachability traversal edge."""
    policy = GraphSeedPolicy()
    assert "RESOLVES_TO" not in policy.allowed_edges
    assert "CALLS" in policy.allowed_edges
    assert "ROUTES_TO" in policy.allowed_edges
    assert "MOUNTS" in policy.allowed_edges


def test_js_ts_scope_isolation(tmp_path: Path) -> None:
    """Verify JS/TS variable bindings respect top-level vs function scope."""
    src = tmp_path / "service.js"
    src.write_text(
        """
function topHandler() {}
function innerHandler() {}

const handler = topHandler;

function run() {
  const handler = innerHandler;
  handler();
}

handler();
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        bindings = con.execute(
            "SELECT target_name, scope, source_expr FROM local_bindings WHERE file_path='service.js'"
        ).fetchall()

        assert len(bindings) >= 2
        top_b = [b for b in bindings if not b["scope"]][0]
        assert top_b["source_expr"] == "topHandler"

        inner_b = [b for b in bindings if b["scope"] == "run"][0]
        assert inner_b["source_expr"] == "innerHandler"


def test_chained_alias_resolution_and_cycle_safety(tmp_path: Path) -> None:
    """Verify bounded multi-hop alias chains resolve, and cycles are safely guarded."""
    src = tmp_path / "chains.py"
    src.write_text(
        """
def target_func():
    pass

a = target_func
b = a
c = b

# Cyclic alias
x = y
y = x
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason "
            "FROM graph_edges WHERE relationship='RESOLVES_TO'"
        ).fetchall()

        c_edge = [e for e in edges if e["source"] == "chains.c"][0]
        assert c_edge["target"] == "chains.target_func"
        assert c_edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        # x and y cycles must NOT resolve to a target
        xy_edges = [e for e in edges if e["source"] in ("chains.x", "chains.y")]
        assert len(xy_edges) == 0


def test_dict_and_list_subscript_dispatch(tmp_path: Path) -> None:
    """Verify dictionary key and list index subscript bindings resolve to concrete targets."""
    src = tmp_path / "dispatch.py"
    src.write_text(
        """
def create_user():
    pass

def delete_user():
    pass

def list_users():
    pass

HANDLERS = {
    "create": create_user,
    "delete": delete_user,
}

LIST_HANDLERS = [list_users]

handle_create = HANDLERS["create"]
handle_list = LIST_HANDLERS[0]
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class "
            "FROM graph_edges WHERE relationship='RESOLVES_TO' ORDER BY source ASC"
        ).fetchall()

        create_edge = [e for e in edges if e["source"] == "dispatch.handle_create"][0]
        assert create_edge["target"] == "dispatch.create_user"
        assert create_edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        list_edge = [e for e in edges if e["source"] == "dispatch.handle_list"][0]
        assert list_edge["target"] == "dispatch.list_users"
        assert list_edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_route_handler_aliasing_resolution(tmp_path: Path) -> None:
    """Verify route handler referencing an alias resolves to the concrete underlying function."""
    src = tmp_path / "urls.py"
    src.write_text(
        """
from django.urls import path

def get_users_impl(request):
    return None

user_handler = get_users_impl

urlpatterns = [
    path("users/", user_handler),
]
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        res = list_routes(con, tmp_path)
        r_list = res["routes"]
        assert len(r_list) == 1
        assert r_list[0]["handler"] == "urls.get_users_impl"
        assert r_list[0]["path"] == "/users/"

        edge = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='ROUTES_TO'"
        ).fetchone()
        assert edge is not None
        assert edge["target"] == "urls.get_users_impl"
        assert edge["evidence_class"] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value


def test_resolves_to_is_never_calls(tmp_path: Path) -> None:
    """Verify alias assignments produce RESOLVES_TO edges and never CALLS edges."""
    src = tmp_path / "binding.py"
    src.write_text(
        """
def real_function():
    pass

my_alias = real_function
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        resolves_edges = con.execute(
            "SELECT source, target, relationship, evidence_class "
            "FROM graph_edges WHERE relationship='RESOLVES_TO'"
        ).fetchall()
        assert len(resolves_edges) == 1
        assert resolves_edges[0]["relationship"] == "RESOLVES_TO"
        assert resolves_edges[0]["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        # Must be ZERO CALLS edges
        call_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        assert len(call_edges) == 0
