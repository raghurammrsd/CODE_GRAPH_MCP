"""Tests for Context Compiler 2.0: Two-stage retrieval, coverage layers, explainability, and budget."""
from pathlib import Path

from codegraph.context import ContextPacket, get_context
from codegraph.indexing import Indexer
from codegraph.task import TaskSpec


def _setup_rich_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "rich_repo"
    repo.mkdir()

    (repo / "routes.py").write_text("""# Entrypoint route
def handle_payment_route():
    from payment_service import PaymentService
    return PaymentService().charge(100)
""")

    (repo / "payment_service.py").write_text("""# Service layer
class PaymentService:
    def charge(self, amount: int) -> bool:
        from payment_gateway import execute_transaction
        return execute_transaction(amount)
""")

    (repo / "payment_gateway.py").write_text("""# Data / gateway layer
def execute_transaction(amount: int) -> bool:
    return amount > 0
""")

    (repo / "test_payment.py").write_text("""# Test layer
from payment_service import PaymentService

def test_charge_success():
    service = PaymentService()
    assert service.charge(50) is True
""")

    Indexer(repo).index()
    return repo


def test_context_compiler_v2_coverage_and_explain(tmp_path: Path) -> None:
    repo = _setup_rich_repo(tmp_path)
    indexer = Indexer(repo)

    with indexer.session() as con:
        packet = get_context(
            con=con,
            repository=repo,
            task="Explain payment processing flow from handle_payment_route to charge",
            intent="explain",
            max_tokens=5000,
            explain=True,
        )

        assert isinstance(packet, ContextPacket)
        assert packet.task_fingerprint != ""
        assert isinstance(packet.conflicts, list)
        assert isinstance(packet.git_facts, list)

        # Execution and Explain validation
        assert packet.execution is not None
        explain_meta = packet.execution.get("explain")
        assert explain_meta is not None
        assert "stage1_candidate_count" in explain_meta
        assert "stage2_candidate_count" in explain_meta
        assert "coverage_layers" in explain_meta
        assert "why_selected" in explain_meta
        assert "rejections" in explain_meta

        # Check why_selected entries exist for selected items
        why_map = explain_meta["why_selected"]
        assert len(why_map) > 0
        for _item_id, reasons in why_map.items():
            assert isinstance(reasons, list)
            assert len(reasons) > 0

        # Budget verification
        assert packet.budget is not None
        assert packet.selected_token_estimate <= 5000
        assert packet.candidate_token_estimate >= packet.selected_token_estimate


def test_context_compiler_v2_conflict_propagation(tmp_path: Path) -> None:
    repo = _setup_rich_repo(tmp_path)
    indexer = Indexer(repo)

    spec = TaskSpec(
        schema_version="2.0",
        raw_prompt="Modify payment service with conflict",
        intent="modify",
        goal="Modify payment service",
        targets=("PaymentService",),
        entities=(),
        operations=(),
        constraints=(),
        exclusions=("PaymentService",),
        scope_paths=(),
        scope_modules=(),
        frameworks=(),
        time_scope="all",
        priority_targets=(),
        ambiguities=(),
        assumptions=(),
        unknowns=(),
        confidence="LOW",
        conflicts=("Conflict detected: target 'PaymentService' is also excluded",),
    )

    with indexer.session() as con:
        packet = get_context(
            con=con,
            repository=repo,
            task=spec,
            max_tokens=3000,
        )

        assert len(packet.conflicts) > 0
        assert "PaymentService" in packet.conflicts[0]


def test_context_compiler_v2_resource_modes(tmp_path: Path) -> None:
    repo = _setup_rich_repo(tmp_path)
    indexer = Indexer(repo)

    with indexer.session() as con:
        packet_fast = get_context(
            con=con,
            repository=repo,
            task="Find charge method",
            mode="FAST",
        )
        assert packet_fast.mode == "FAST"

        packet_deep = get_context(
            con=con,
            repository=repo,
            task="Find charge method",
            mode="DEEP",
        )
        assert packet_deep.mode == "DEEP"
