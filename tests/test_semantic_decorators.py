"""Regression tests for Phase 5: Semantic Decorator, Task, and Command Framework Intelligence.

Invariants:
  - TASK_HANDLER != CALLS
  - COMMAND_HANDLER != CALLS
  - EVENT_LISTENER != CALLS
  - REGISTERS != CALLS
  - Unknown decorators remain ordinary AST metadata only (never semantic edges).
  - Dynamic arguments produce structured UNKNOWN findings, never fake canonical IDs.
  - Bounded, deterministic, no runtime execution.
"""
from __future__ import annotations

from pathlib import Path

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.indexing import Indexer
from codegraph.retrieval_policy import get_retrieval_policy


def test_1_recognized_task_decorator(tmp_path: Path) -> None:
    code = """
import celery
from celery import shared_task

@celery.task
def process_data():
    pass

@shared_task
def background_cleanup():
    pass
"""
    (tmp_path / "tasks.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) >= 2
        targets = {e[1] for e in edges}
        assert "tasks.process_data" in targets
        assert "tasks.background_cleanup" in targets
        for e in edges:
            assert e[2] == "TASK_HANDLER"
            assert e[3] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value


def test_2_recognized_command_decorator(tmp_path: Path) -> None:
    code = """
import click
import typer

app = typer.Typer()

@click.command(name="deploy")
def deploy_cli():
    pass

@app.command(name="serve")
def serve_cli():
    pass
"""
    (tmp_path / "cli.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='COMMAND_HANDLER'"
        ).fetchall()
        assert len(edges) >= 2
        targets = {e[1] for e in edges}
        assert "cli.deploy_cli" in targets
        assert "cli.serve_cli" in targets
        sources = {e[0] for e in edges}
        assert any("deploy" in s for s in sources)
        assert any("serve" in s for s in sources)


def test_3_recognized_event_listener_decorator(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver

class UserCreated:
    pass

@receiver(UserCreated)
def on_user_created(sender, **kwargs):
    pass
"""
    (tmp_path / "events.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert len(edges) >= 1
        edge = edges[0]
        assert "UserCreated" in edge[0]
        assert edge[1] == "events.on_user_created"
        assert edge[2] == "EVENT_LISTENER"
        assert edge[3] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value


def test_4_static_event_arguments_and_list(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver

class EventA:
    pass

class EventB:
    pass

@receiver([EventA, EventB])
def handle_multiple_events():
    pass
"""
    (tmp_path / "multi.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='EVENT_LISTENER' AND target='multi.handle_multiple_events'"
        ).fetchall()
        assert len(edges) == 2
        sources = {e[0] for e in edges}
        assert any("EventA" in s for s in sources)
        assert any("EventB" in s for s in sources)


def test_5_dynamic_argument_detection(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver
import config

@receiver(config.EVENT_NAME)
def dynamic_handler():
    pass
"""
    (tmp_path / "dyn.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Invariant: NO edge emitted for dynamic event name!
        edges = con.execute(
            "SELECT * FROM graph_edges WHERE target='dyn.dynamic_handler' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(edges) == 0

        # Stored in local_bindings with dynamic reason
        b = con.execute(
            "SELECT expr_kind, subscript_target FROM local_bindings WHERE target_name='dyn.dynamic_handler'"
        ).fetchone()
        assert b is not None
        assert b[0] == "SEMANTIC_DECORATOR"
        assert b[1] == "dynamic_event_name"


def test_6_decorator_alias_resolution(tmp_path: Path) -> None:
    code = """
import celery

task = celery.task

@task
def aliased_task():
    pass
"""
    (tmp_path / "alias_test.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE target='alias_test.aliased_task' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) >= 1
        edge = edges[0]
        assert edge[1] == "alias_test.aliased_task"
        assert edge[2] == "TASK_HANDLER"
        assert edge[3] == RelationshipEvidenceClass.DATAFLOW_VERIFIED.value


def test_7_cross_file_decorator_import(tmp_path: Path) -> None:
    dec_file = """
from celery import shared_task
"""
    tasks_file = """
from dec_mod import shared_task

@shared_task
def remote_task():
    pass
"""
    (tmp_path / "dec_mod.py").write_text(dec_file, encoding="utf-8")
    (tmp_path / "worker.py").write_text(tasks_file, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE target='worker.remote_task' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) >= 1
        assert edges[0][1] == "worker.remote_task"
        assert edges[0][2] == "TASK_HANDLER"


def test_8_multiple_decorators_on_same_function(tmp_path: Path) -> None:
    code = """
import celery
import click

@celery.task
@click.command(name="run_both")
def dual_purpose():
    pass
"""
    (tmp_path / "dual.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT relationship FROM graph_edges WHERE target='dual.dual_purpose' AND relationship != 'DEFINES'"
        ).fetchall()
        rels = {e[0] for e in edges}
        assert "TASK_HANDLER" in rels
        assert "COMMAND_HANDLER" in rels


def test_9_unknown_decorator_ignored_semantically(tmp_path: Path) -> None:
    code = """
def audit(f):
    return f

@audit
def audited_func():
    pass
"""
    (tmp_path / "audit_test.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Invariant: Unknown decorator NEVER becomes a semantic relationship
        edges = con.execute(
            "SELECT relationship FROM graph_edges WHERE target='audit_test.audited_func' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(edges) == 0

        # Preserved in symbols AST metadata
        sym = con.execute(
            "SELECT decorators FROM symbols WHERE canonical_id='audit_test.audited_func'"
        ).fetchone()
        assert sym is not None
        assert "audit" in sym[0]


def test_10_decorator_factory_unresolved(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver

def get_event_factory():
    pass

@receiver(get_event_factory())
def factory_event_handler():
    pass
"""
    (tmp_path / "factory_test.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Must NOT emit edge with fake target
        edges = con.execute(
            "SELECT * FROM graph_edges WHERE target='factory_test.factory_event_handler' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(edges) == 0

        # Reason is recorded in local_bindings
        b = con.execute(
            "SELECT subscript_target FROM local_bindings WHERE target_name='factory_test.factory_event_handler'"
        ).fetchone()
        assert b is not None
        assert b[0] == "unsupported_decorator_factory"


def test_11_class_decorator(tmp_path: Path) -> None:
    code = """
import celery

@celery.task
class ProcessJobTask:
    def run(self):
        pass
"""
    (tmp_path / "class_dec.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE target='class_dec.ProcessJobTask' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) >= 1
        assert edges[0][1] == "class_dec.ProcessJobTask"
        assert edges[0][2] == "TASK_HANDLER"


def test_12_method_decorator(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver

class SignalHandler:
    @receiver("my_signal")
    def handle_signal(self):
        pass
"""
    (tmp_path / "method_dec.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT relationship, target FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert len(edges) >= 1
        assert any("handle_signal" in e[1] for e in edges)


def test_13_task_handler_not_calls(tmp_path: Path) -> None:
    code = """
import celery

@celery.task
def task_alpha():
    pass
"""
    (tmp_path / "invar_task.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls = con.execute(
            "SELECT * FROM graph_edges WHERE target='invar_task.task_alpha' AND relationship='CALLS'"
        ).fetchall()
        assert len(calls) == 0

        handlers = con.execute(
            "SELECT relationship FROM graph_edges WHERE target='invar_task.task_alpha' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(handlers) == 1
        assert handlers[0][0] == "TASK_HANDLER"
        assert handlers[0][0] != "CALLS"


def test_14_command_handler_not_calls(tmp_path: Path) -> None:
    code = """
import click

@click.command()
def cmd_beta():
    pass
"""
    (tmp_path / "invar_cmd.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls = con.execute(
            "SELECT * FROM graph_edges WHERE target='invar_cmd.cmd_beta' AND relationship='CALLS'"
        ).fetchall()
        assert len(calls) == 0

        handlers = con.execute(
            "SELECT relationship FROM graph_edges WHERE target='invar_cmd.cmd_beta' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(handlers) == 1
        assert handlers[0][0] == "COMMAND_HANDLER"
        assert handlers[0][0] != "CALLS"


def test_15_event_listener_not_calls(tmp_path: Path) -> None:
    code = """
from django.dispatch import receiver

class SampleEvent:
    pass

@receiver(SampleEvent)
def listener_gamma():
    pass
"""
    (tmp_path / "invar_event.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        calls = con.execute(
            "SELECT * FROM graph_edges WHERE target='invar_event.listener_gamma' AND relationship='CALLS'"
        ).fetchall()
        assert len(calls) == 0

        listeners = con.execute(
            "SELECT relationship FROM graph_edges WHERE target='invar_event.listener_gamma' AND relationship != 'DEFINES'"
        ).fetchall()
        assert len(listeners) == 1
        assert listeners[0][0] == "EVENT_LISTENER"
        assert listeners[0][0] != "CALLS"


def test_16_repeated_indexing_determinism(tmp_path: Path) -> None:
    code = """
import celery
from celery import shared_task

@shared_task
def sync_job():
    pass
"""
    (tmp_path / "sync.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)

    # Run index 1
    indexer.index()
    with indexer.session() as con:
        count1 = con.execute("SELECT COUNT(*) FROM graph_edges WHERE relationship='TASK_HANDLER'").fetchone()[0]

    # Run index 2 (incremental unchanged)
    res2 = indexer.index()
    assert res2["unchanged"] == 1
    with indexer.session() as con:
        count2 = con.execute("SELECT COUNT(*) FROM graph_edges WHERE relationship='TASK_HANDLER'").fetchone()[0]
    assert count1 == count2 == 1

    # Run index 3 (re-index)
    indexer.index()
    with indexer.session() as con:
        count3 = con.execute("SELECT COUNT(*) FROM graph_edges WHERE relationship='TASK_HANDLER'").fetchone()[0]
    assert count3 == 1


def test_17_duplicate_semantic_registration_prevention(tmp_path: Path) -> None:
    code = """
import celery

@celery.task
@celery.task
def duplicate_decorated():
    pass
"""
    (tmp_path / "dup.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE target='dup.duplicate_decorated' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) == 1


def test_18_conditional_decorator_registration(tmp_path: Path) -> None:
    code = """
import celery

if True:
    @celery.task
    def conditional_job():
        pass
"""
    (tmp_path / "cond_dec.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT evidence_class, confidence, reason FROM graph_edges WHERE target='cond_dec.conditional_job' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) == 1
        assert edges[0][0] == RelationshipEvidenceClass.POSSIBLE.value
        assert edges[0][1] == "LOW"
        assert "Conditional" in edges[0][2]


def test_19_ambiguous_decorator_alias(tmp_path: Path) -> None:
    code = """
import celery

if True:
    task = celery.task
else:
    task = None

@task
def ambiguous_job():
    pass
"""
    (tmp_path / "ambig.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Invariant: Conditional/ambiguous alias cannot produce DATAFLOW_VERIFIED decorator
        edges = con.execute(
            "SELECT * FROM graph_edges WHERE target='ambig.ambiguous_job' AND relationship='TASK_HANDLER'"
        ).fetchall()
        assert len(edges) == 0


def test_20_source_evidence_correctness(tmp_path: Path) -> None:
    code = """
import celery

@celery.task(name="exact_job_name")
def worker_unit():
    pass
"""
    (tmp_path / "evid_test.py").write_text(code, encoding="utf-8")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edge = con.execute(
            "SELECT source, target, relationship, evidence, evidence_class, reason FROM graph_edges WHERE target='evid_test.worker_unit' AND relationship='TASK_HANDLER'"
        ).fetchone()
        assert edge is not None
        assert edge[0] == "exact_job_name"
        assert edge[1] == "evid_test.worker_unit"
        assert edge[2] == "TASK_HANDLER"
        assert "Task handler 'evid_test.worker_unit' registered" in edge[3]
        assert edge[4] == RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
        assert "Statically verified" in edge[5]


def test_retrieval_policy_trace_unpolluted() -> None:
    trace_policy = get_retrieval_policy("TRACE")
    assert not trace_policy.allows("TASK_HANDLER")
    assert not trace_policy.allows("COMMAND_HANDLER")

    understand_policy = get_retrieval_policy("UNDERSTAND")
    assert understand_policy.allows("TASK_HANDLER")
    assert understand_policy.allows("COMMAND_HANDLER")
