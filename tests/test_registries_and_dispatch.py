from pathlib import Path

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.indexing import Indexer


def test_false_positive_obj_register(tmp_path: Path) -> None:
    """Verify that arbitrary obj.register() calls are NOT classified as REGISTERS."""
    src = tmp_path / "app.py"
    src.write_text(
        """
class Device:
    def register(self, code):
        pass

device = Device()
device.register("12345")
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='REGISTERS'"
        ).fetchall()
        assert len(edges) == 0, "obj.register() must not produce REGISTERS edge"


def test_false_positive_metrics_on(tmp_path: Path) -> None:
    """Verify that metrics.on() or feature.on() is NOT classified as EVENT_LISTENER."""
    src = tmp_path / "telemetry.py"
    src.write_text(
        """
class Metrics:
    def on(self):
        pass

metrics = Metrics()
metrics.on()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert len(edges) == 0, "metrics.on() must not produce EVENT_LISTENER edge"


def test_dynamic_registry_key_and_no_fabricated_target(tmp_path: Path) -> None:
    """Verify dynamic registry key produces NO fabricated graph target with empty/unknown ID."""
    src = tmp_path / "dynamic_reg.py"
    src.write_text(
        """
def my_handler():
    return True

registry = {}
user_key = input()
registry[user_key] = my_handler
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute("SELECT source, target, relationship FROM graph_edges").fetchall()
        for e in edges:
            assert e["target"] not in ("", "UNKNOWN", None), f"Fabricated target found in edge: {dict(e)}"
            assert e["target"] != "<DYNAMIC>"


def test_unknown_registry_target_no_fabricated_target(tmp_path: Path) -> None:
    """Verify dynamic/unknown registry target produces NO fabricated graph edge."""
    src = tmp_path / "unknown_reg.py"
    src.write_text(
        """
import importlib

registry = {}
registry["plugin"] = importlib.import_module("runtime_plugin")
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship IN ('REGISTERS', 'DISPATCHES_TO')"
        ).fetchall()
        assert len(edges) == 0, "Unknown dynamic target must not emit a fabricated edge"


def test_simple_registry_register_grounded(tmp_path: Path) -> None:
    """Verify registry.register('users', get_users) emits REGISTERS with DATAFLOW_VERIFIED."""
    src = tmp_path / "reg.py"
    src.write_text(
        """
def get_users():
    return ["alice", "bob"]

command_registry.register("users", get_users)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='REGISTERS'"
        ).fetchall()
        assert len(edges) == 1
        edge = edges[0]
        assert edge["target"] == "reg.get_users"
        assert edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value
        assert edge["relationship"] != "CALLS"


def test_dictionary_dispatch_and_call(tmp_path: Path) -> None:
    """Verify HANDLERS = {'create': create_user} and HANDLERS['create']() emits DISPATCHES_TO."""
    src = tmp_path / "dispatch.py"
    src.write_text(
        """
def create_user():
    return True

HANDLERS = {
    "create": create_user,
}

def main():
    HANDLERS["create"]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        assert len(edges) >= 1
        targets = [e["target"] for e in edges]
        assert "dispatch.create_user" in targets
        for e in edges:
            assert e["relationship"] != "CALLS"
            assert e["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_list_subscript_dispatch(tmp_path: Path) -> None:
    """Verify PIPELINE = [step1, step2] and PIPELINE[1]() emits DISPATCHES_TO."""
    src = tmp_path / "pipeline.py"
    src.write_text(
        """
def step1(): pass
def step2(): pass

PIPELINE = [step1, step2]

def run():
    PIPELINE[1]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        assert len(edges) == 1
        assert edges[0]["target"] == "pipeline.step2"
        assert edges[0]["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_event_listener_registration(tmp_path: Path) -> None:
    """Verify event_bus.on('user.created', handle_user) emits EVENT_LISTENER."""
    src = tmp_path / "events.py"
    src.write_text(
        """
def handle_user_created(event):
    pass

event_bus.on("user.created", handle_user_created)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert len(edges) == 1
        assert edges[0]["target"] == "events.handle_user_created"
        assert edges[0]["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value
        assert edges[0]["relationship"] != "CALLS"


def test_cross_file_shared_registry_deterministic(tmp_path: Path) -> None:
    """Verify cross-file shared registry with deterministic population resolves DATAFLOW_VERIFIED."""
    (tmp_path / "reg_store.py").write_text(
        """
HANDLERS = {}
""",
        encoding="utf-8",
    )
    (tmp_path / "handlers.py").write_text(
        """
def list_items():
    return []
""",
        encoding="utf-8",
    )
    (tmp_path / "setup_reg.py").write_text(
        """
from reg_store import HANDLERS
from handlers import list_items

HANDLERS["items"] = list_items
""",
        encoding="utf-8",
    )
    (tmp_path / "client.py").write_text(
        """
from reg_store import HANDLERS

def execute():
    HANDLERS["items"]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        assert len(edges) >= 1
        targets = [e["target"] for e in edges]
        assert "handlers.list_items" in targets
        for e in edges:
            assert e["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_cross_file_ambiguous_registry_mutation(tmp_path: Path) -> None:
    """Verify conflicting cross-file mutations for the same key remain POSSIBLE."""
    (tmp_path / "reg_store.py").write_text("HANDLERS = {}", encoding="utf-8")
    (tmp_path / "mod_a.py").write_text(
        """
def handle_a(): pass
from reg_store import HANDLERS
HANDLERS["conflict"] = handle_a
""",
        encoding="utf-8",
    )
    (tmp_path / "mod_b.py").write_text(
        """
def handle_b(): pass
from reg_store import HANDLERS
HANDLERS["conflict"] = handle_b
""",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text(
        """
from reg_store import HANDLERS
def run():
    HANDLERS["conflict"]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        verified_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO' AND source LIKE '%main%' AND evidence_class='DATAFLOW_VERIFIED'"
        ).fetchall()
        assert len(verified_edges) == 0, "Conflicting cross-file mutations must NOT be DATAFLOW_VERIFIED"


def test_semantic_invariants_never_calls(tmp_path: Path) -> None:
    """Verify REGISTERS, DISPATCHES_TO, and EVENT_LISTENER never become CALLS."""
    src = tmp_path / "invariants.py"
    src.write_text(
        """
def create_user(): pass
def handle_event(e): pass
def deploy_cmd(): pass

HANDLERS = {"create": create_user}
command_registry.register("deploy", deploy_cmd)
event_bus.on("user.created", handle_event)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Check all edges where relationship is CALLS
        call_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        targets = {e["target"] for e in call_edges}
        assert "invariants.create_user" not in targets, "Registration must not become CALLS"
        assert "invariants.handle_event" not in targets, "Event listener must not become CALLS"
        assert "invariants.deploy_cmd" not in targets, "Registry register must not become CALLS"


def test_javascript_dispatch_and_event_emitter(tmp_path: Path) -> None:
    """Verify JS/TS dispatch tables and event emitter produce DISPATCHES_TO and EVENT_LISTENER."""
    src = tmp_path / "app.js"
    src.write_text(
        """
function createUser() { return true; }
function handleData(d) { return d; }

const handlers = {
  create: createUser
};

eventEmitter.on("data", handleData);
handlers["create"]();
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        evt_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert len(evt_edges) == 1
        assert evt_edges[0]["target"] == "app.handleData"
        assert evt_edges[0]["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

        disp_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        assert len(disp_edges) >= 1
        disp_targets = [e["target"] for e in disp_edges]
        assert "app.createUser" in disp_targets


def test_repeated_indexing_determinism(tmp_path: Path) -> None:
    """Verify that re-indexing produces identical deterministic results and counts."""
    src = tmp_path / "pipeline.py"
    src.write_text(
        """
def task1(): pass
def task2(): pass

task_registry.register("t1", task1)
task_registry.register("t2", task2)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges_1 = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target"
        ).fetchall()
        refs_1 = con.execute("SELECT count(*) FROM 'references'").fetchone()[0]

    # Re-index
    indexer.index()

    with indexer.session() as con:
        edges_2 = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges ORDER BY source, target"
        ).fetchall()
        refs_2 = con.execute("SELECT count(*) FROM 'references'").fetchone()[0]

    assert len(edges_1) == len(edges_2)
    assert refs_1 == refs_2
    for e1, e2 in zip(edges_1, edges_2, strict=True):
        assert dict(e1) == dict(e2)


def test_sequential_registry_reassignment(tmp_path: Path) -> None:
    """Verify earlier dispatch resolves to first assignment; later dispatch resolves to reassignment."""
    src = tmp_path / "seq.py"
    src.write_text(
        """
def f1(): pass
def f2(): pass

HANDLERS = {}
HANDLERS["run"] = f1
def step1():
    HANDLERS["run"]()

HANDLERS["run"] = f2
def step2():
    HANDLERS["run"]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        e1 = con.execute(
            "SELECT target, relationship, evidence_class FROM graph_edges WHERE source='seq.step1' AND relationship='DISPATCHES_TO'"
        ).fetchone()
        assert e1 is not None
        assert e1["target"] == "seq.f1"

        e2 = con.execute(
            "SELECT target, relationship, evidence_class FROM graph_edges WHERE source='seq.step2' AND relationship='DISPATCHES_TO'"
        ).fetchone()
        assert e2 is not None
        assert e2["target"] == "seq.f2"


def test_conditional_registry_reassignment(tmp_path: Path) -> None:
    """Verify conditional registration is classified as POSSIBLE, not DATAFLOW_VERIFIED."""
    src = tmp_path / "cond.py"
    src.write_text(
        """
def f1(): pass
def f2(): pass

command_registry = {}
condition = True
if condition:
    command_registry.register("exec", f1)
else:
    command_registry.register("exec", f2)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='REGISTERS'"
        ).fetchall()
        assert len(edges) == 2
        for e in edges:
            assert e["evidence_class"] == RelationshipEvidenceClass.POSSIBLE.value


def test_registry_register_with_alias(tmp_path: Path) -> None:
    """Verify registry.register with an alias resolves to the concrete underlying function."""
    src = tmp_path / "alias_reg.py"
    src.write_text(
        """
def real_handler():
    return 42

h_alias = real_handler
command_registry.register("compute", h_alias)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edge = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='REGISTERS'"
        ).fetchone()
        assert edge is not None
        assert edge["target"] == "alias_reg.real_handler"
        assert edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_registry_register_with_attribute_alias(tmp_path: Path) -> None:
    """Verify registry.register with an attribute alias resolves to class method."""
    (tmp_path / "controller.py").write_text(
        """
class UserController:
    @staticmethod
    def get_all():
        return []
""",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text(
        """
from controller import UserController

command_registry.register("users", UserController.get_all)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edge = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='REGISTERS'"
        ).fetchone()
        assert edge is not None
        assert edge["target"] == "controller.UserController.get_all"
        assert edge["evidence_class"] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value

