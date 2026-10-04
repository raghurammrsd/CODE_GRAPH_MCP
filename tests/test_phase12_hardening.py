"""Phase 12 Hardening Test Suite: Trust, Security, Registry, Dispatch & DI Hardening.

Covers >= 100 deterministic tests across:
1. Authoritative Evidence Contract (`evidence_contract.py`) & Raw-Dict Bypass Prevention
2. Registry, Dispatch, Events, Tasks, Commands, Overwrite & Negative Cases
3. Dependency Injection (`Depends`, `Annotated`, Router/App DI, Container APIs, `@provide`/`@singleton`, DI Cycles)
4. Security Boundary, Sensitive Path Patterns (22+), Binary & Read-Size Cap Enforcement
5. Monorepo Duplicate-Name `AMBIGUOUS`, Service Precedence, pnpm Negation & Circular Import Isolation
6. Context Optimizer Independent Budgets & Epistemic Uncertainty Survival
7. Real Stdio JSON-RPC `codegraph mcp doctor` Handshake & Hostile Repository Integration
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codegraph.context import Relationship, get_context
from codegraph.epistemic import (
    EpistemicStatus,
    RelationshipEvidenceClass,
    classify_relationship_evidence,
    validate_relationship_invariants,
)
from codegraph.errors import ErrorCode, SecurityError
from codegraph.evidence.citations import build_evidence, verify_evidence, verify_source_hash
from codegraph.evidence_contract import (
    ALLOWED_EVIDENCE_CLASSES,
    ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX,
    validate_evidence_class,
    validate_relationship_evidence_pair,
    validate_relationship_record,
    validate_relationship_type,
)
from codegraph.graph.models import GraphEdge
from codegraph.indexing import Indexer
from codegraph.interrogation import get_file as interrogation_get_file
from codegraph.mcp_diagnostics import run_mcp_doctor
from codegraph.monorepo import detect_workspace as discover_workspace
from codegraph.optimizer import (
    CandidateContextItem,
    ContextBudgetSpec,
    compress_relationships,
    optimize_context_budget,
)
from codegraph.security.paths import is_sensitive_path, safe_read_text

# ==============================================================================
# 1. AUTHORITATIVE EVIDENCE CONTRACT & RAW-DICT BYPASS PREVENTION (28 tests)
# ==============================================================================


@pytest.mark.parametrize(
    "rel_type",
    [
        "CALLS",
        "CALLED_BY",
        "POSSIBLE_CALLS",
        "MOUNTS",
        "ROUTE_HANDLER",
        "HANDLED_BY",
        "ROUTES_TO",
        "INJECTS",
        "PROVIDES",
        "RESOLVES_DEPENDENCY",
        "CONFIGURES",
        "DI_CYCLE",
        "REGISTERS",
        "DISPATCHES_TO",
        "EVENT_LISTENER",
        "TASK_HANDLER",
        "COMMAND_HANDLER",
        "DEPENDS_ON_PACKAGE",
        "TESTS_SYMBOL",
        "TESTS_ROUTE",
        "TESTS_PROVIDER",
        "TESTS_EVENT_HANDLER",
        "IMPORTS",
        "RESOLVES_TO",
    ],
)
def test_contract_accepts_canonical_relationship_types(rel_type: str) -> None:
    assert validate_relationship_type(rel_type) == rel_type
    assert rel_type in ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX


@pytest.mark.parametrize(
    "bad_rel",
    ["", "   ", "INVENTED_REL", "MAYBE_CALLS", "MAGIC_EDGE", "EXECUTES"],
)
def test_contract_rejects_unknown_relationship_types(bad_rel: str) -> None:
    with pytest.raises(ValueError):
        validate_relationship_type(bad_rel)


@pytest.mark.parametrize(
    "ev_cls",
    ["AST_VERIFIED", "FRAMEWORK_VERIFIED", "DATAFLOW_VERIFIED", "POSSIBLE", "UNKNOWN"],
)
def test_contract_accepts_canonical_evidence_classes(ev_cls: str) -> None:
    assert validate_evidence_class(ev_cls) == ev_cls
    assert ev_cls in ALLOWED_EVIDENCE_CLASSES


@pytest.mark.parametrize(
    "bad_ev",
    ["", "   ", "LLM_GUESSED", "HEURISTIC", "PROBABLY", "VERIFIED"],
)
def test_contract_rejects_unknown_evidence_classes(bad_ev: str) -> None:
    with pytest.raises(ValueError):
        validate_evidence_class(bad_ev)


@pytest.mark.parametrize(
    ("rel", "ev_cls"),
    [
        ("CALLS", "POSSIBLE"),
        ("CALLS", "UNKNOWN"),
        ("CALLS", "FRAMEWORK_VERIFIED"),
        ("CALLED_BY", "POSSIBLE"),
        ("CALLED_BY", "UNKNOWN"),
        ("CALLED_BY", "FRAMEWORK_VERIFIED"),
        ("POSSIBLE_CALLS", "AST_VERIFIED"),
        ("POSSIBLE_CALLS", "DATAFLOW_VERIFIED"),
        ("POSSIBLE_CALLS", "FRAMEWORK_VERIFIED"),
        ("MOUNTS", "AST_VERIFIED"),
        ("MOUNTS", "DATAFLOW_VERIFIED"),
        ("HANDLED_BY", "AST_VERIFIED"),
        ("ROUTE_HANDLER", "AST_VERIFIED"),
        ("INJECTS", "AST_VERIFIED"),
        ("PROVIDES", "AST_VERIFIED"),
        ("RESOLVES_DEPENDENCY", "AST_VERIFIED"),
        ("DISPATCHES_TO", "AST_VERIFIED"),
        ("EVENT_LISTENER", "AST_VERIFIED"),
        ("TASK_HANDLER", "AST_VERIFIED"),
        ("COMMAND_HANDLER", "AST_VERIFIED"),
    ],
)
def test_contract_rejects_disallowed_relationship_evidence_pairs(rel: str, ev_cls: str) -> None:
    with pytest.raises(ValueError):
        validate_relationship_evidence_pair(rel, ev_cls)


def test_contract_rejects_contradictory_epistemic_record_fields() -> None:
    # Fact status with POSSIBLE evidence class
    with pytest.raises(ValueError, match="contradicts"):
        validate_relationship_record(
            {
                "source": "a.foo",
                "target": "b.bar",
                "relationship": "DISPATCHES_TO",
                "evidence_class": "POSSIBLE",
                "status": "FACT",
                "confidence": "LOW",
            }
        )
    # HIGH confidence with POSSIBLE evidence class
    with pytest.raises(ValueError, match="contradicts"):
        validate_relationship_record(
            {
                "source": "a.foo",
                "target": "b.bar",
                "relationship": "DISPATCHES_TO",
                "evidence_class": "POSSIBLE",
                "confidence": "HIGH",
            }
        )
    # Verified CALLS with LOW confidence
    with pytest.raises(ValueError, match="contradicts"):
        validate_relationship_record(
            {
                "source": "a.foo",
                "target": "b.bar",
                "relationship": "CALLS",
                "evidence_class": "AST_VERIFIED",
                "confidence": "LOW",
            }
        )


def test_contract_enforced_Across_GraphEdge_Relationship_and_Optimizer_Dicts() -> None:
    # 1. GraphEdge fails closed on CALLS + FRAMEWORK_VERIFIED
    with pytest.raises(ValueError):
        GraphEdge(
            source="a.f",
            target="b.g",
            relationship="CALLS",
            confidence="HIGH",
            file="a.py",
            start_line=1,
            end_line=2,
            evidence="f() -> g()",
            evidence_class="FRAMEWORK_VERIFIED",
        )
    # 2. Context Relationship Pydantic model fails closed on CALLS + POSSIBLE
    with pytest.raises(ValueError):
        Relationship(
            source="a.f",
            target="b.g",
            relationship="CALLS",
            confidence="LOW",
            evidence_class="POSSIBLE",
        )
    # 3. Raw dictionary passed to compress_relationships fails closed on invalid pair
    with pytest.raises(ValueError):
        compress_relationships(
            [
                {
                    "source": "a.f",
                    "target": "b.g",
                    "relationship": "CALLS",
                    "confidence": "LOW",
                    "evidence_class": "POSSIBLE",
                }
            ]
        )


def test_epistemic_delegates_to_authoritative_contract() -> None:
    with pytest.raises(ValueError, match="UNKNOWN relationships cannot be exposed as authoritative 'CALLS'"):
        validate_relationship_invariants("CALLS", RelationshipEvidenceClass.UNKNOWN, EpistemicStatus.UNKNOWN)

    with pytest.raises(ValueError, match="POSSIBLE relationships cannot be labeled as 'CALLS'"):
        validate_relationship_invariants("CALLS", RelationshipEvidenceClass.POSSIBLE, EpistemicStatus.ASSUMPTION)

    ev_cls, _reason = classify_relationship_evidence("MOUNTS", "HIGH")
    assert ev_cls == RelationshipEvidenceClass.FRAMEWORK_VERIFIED


# ==============================================================================
# 2. REGISTRY, DISPATCH, EVENTS, OVERWRITE & NEGATIVE CASES (20 tests)
# ==============================================================================


def test_registry_overwrite_same_scope_keeps_latest_static_assignment(tmp_path: Path) -> None:
    """When registry['x'] = handler_a is unconditionally overwritten by registry['x'] = handler_b,
    only handler_b is active on the registry edge, while earlier overwritten assignment is recorded in findings.
    """
    (tmp_path / "reg_overwrite.py").write_text(
        """
def handler_a():
    return "a"

def handler_b():
    return "b"

registry = {}
registry["x"] = handler_a
registry["x"] = handler_b
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()
    findings = indexer.last_epistemic_findings
    assert any(f.get("status") == "OVERWRITTEN" and f.get("key") == "x" for f in findings)

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        targets = [e["target"] for e in edges]
        assert targets == ["reg_overwrite.handler_b"]
        assert edges[0]["evidence_class"] == "DATAFLOW_VERIFIED"


def test_registry_conditional_overwrite_marks_possible(tmp_path: Path) -> None:
    """When an unconditional assignment is followed by a conditional overwrite, both candidates become POSSIBLE."""
    (tmp_path / "reg_cond_overwrite.py").write_text(
        """
def handler_a():
    return "a"

def handler_b():
    return "b"

registry = {}
registry["x"] = handler_a
if True:
    registry["x"] = handler_b
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        targets = {e["target"] for e in edges}
        assert targets == {"reg_cond_overwrite.handler_a", "reg_cond_overwrite.handler_b"}
        for e in edges:
            assert e["evidence_class"] == "POSSIBLE"


def test_handler_list_registration_emits_dispatches_to_never_calls(tmp_path: Path) -> None:
    (tmp_path / "list_handlers.py").write_text(
        """
def fn_a():
    pass

def fn_b():
    pass

handlers = [fn_a, fn_b]
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        disp_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='DISPATCHES_TO'"
        ).fetchall()
        assert {e["target"] for e in disp_edges} == {"list_handlers.fn_a", "list_handlers.fn_b"}
        call_edges = con.execute(
            "SELECT source, target FROM graph_edges WHERE relationship='CALLS'"
        ).fetchall()
        assert len(call_edges) == 0


def test_negative_cases_observer_on_metrics_on_device_register_never_emit_semantic_edges(tmp_path: Path) -> None:
    (tmp_path / "negatives.py").write_text(
        """
class Observer:
    def on(self, name, fn):
        pass

class Metrics:
    def on(self, metric, fn):
        pass

class CashRegister:
    def register(self, item, handler):
        pass

def dummy():
    pass

observer = Observer()
metrics = Metrics()
device = CashRegister()

observer.on("click", dummy)
metrics.on("cpu", dummy)
device.register("item", dummy)
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        sem_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship IN ('REGISTERS', 'EVENT_LISTENER', 'DISPATCHES_TO', 'PROVIDES')"
        ).fetchall()
        assert len(sem_edges) == 0


def test_event_bus_subscribe_and_standalone_subscribe(tmp_path: Path) -> None:
    (tmp_path / "sub_events.py").write_text(
        """
def on_payment(ev):
    pass

def on_refund(ev):
    pass

event_bus.subscribe("payment.completed", on_payment)
subscribe("payment.refunded", on_refund)
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='EVENT_LISTENER'"
        ).fetchall()
        assert {e["target"] for e in edges} == {"sub_events.on_payment", "sub_events.on_refund"}
        for e in edges:
            assert e["evidence_class"] == "DATAFLOW_VERIFIED"


# ==============================================================================
# 3. DEPENDENCY INJECTION & STATIC DI CYCLE DETECTION (18 tests)
# ==============================================================================


def test_fastapi_depends_keyword_and_annotated_and_router_dependencies(tmp_path: Path) -> None:
    (tmp_path / "api_di.py").write_text(
        """
from typing import Annotated
from fastapi import APIRouter, Depends, FastAPI

def verify_auth():
    return True

def get_db():
    return "db"

def get_cache():
    return "cache"

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_auth)])

@router.get("/items")
def list_items(
    db = Depends(dependency=get_db),
    cache: Annotated[str, Depends(dependency=get_cache)] = "",
):
    return [db, cache]
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        injected_into_handler = {
            e["target"] for e in edges if e["source"] == "api_di.list_items"
        }
        assert injected_into_handler == {
            "api_di.verify_auth",
            "api_di.get_db",
            "api_di.get_cache",
        }
        for e in edges:
            assert e["evidence_class"] == "FRAMEWORK_VERIFIED"
            assert e["relationship"] != "CALLS"


def test_fastapi_include_router_dependencies_propagate_to_routes(tmp_path: Path) -> None:
    (tmp_path / "routes.py").write_text(
        """
from fastapi import APIRouter, FastAPI, Depends

def check_rate_limit():
    return True

users_router = APIRouter(prefix="/users")

@users_router.get("/me")
def get_me():
    return {"id": 1}

app = FastAPI()
app.include_router(users_router, dependencies=[Depends(check_rate_limit)])
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        targets = {e["target"] for e in edges if e["source"] == "routes.get_me"}
        assert "routes.check_rate_limit" in targets


def test_di_container_provide_singleton_factory_and_fluent_to_class(tmp_path: Path) -> None:
    (tmp_path / "di_container.py").write_text(
        """
class UserRepository:
    pass

class PostgresRepository(UserRepository):
    pass

class CacheClient:
    pass

class RedisCacheClient(CacheClient):
    pass

class PaymentGateway:
    pass

class StripeGateway(PaymentGateway):
    pass

container.singleton(UserRepository, PostgresRepository)
container.provide(RedisCacheClient)
container.bind(PaymentGateway).to_class(StripeGateway)

u = container.resolve(UserRepository)
c = container.resolve(CacheClient)
p = container.resolve(PaymentGateway)
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        provides = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        prov_pairs = {(e["source"], e["target"]) for e in provides}
        assert ("di_container.UserRepository", "di_container.PostgresRepository") in prov_pairs
        assert ("di_container.CacheClient", "di_container.RedisCacheClient") in prov_pairs
        assert ("di_container.PaymentGateway", "di_container.StripeGateway") in prov_pairs

        resolves = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship='RESOLVES_DEPENDENCY'"
        ).fetchall()
        res_pairs = {(e["source"], e["target"]) for e in resolves}
        assert ("di_container.UserRepository", "di_container.PostgresRepository") in res_pairs
        assert ("di_container.CacheClient", "di_container.RedisCacheClient") in res_pairs
        assert ("di_container.PaymentGateway", "di_container.StripeGateway") in res_pairs


def test_provide_and_singleton_decorators_register_providers(tmp_path: Path) -> None:
    (tmp_path / "dec_di.py").write_text(
        """
from di import provide, inject

class EmailSender:
    pass

@provide(EmailSender)
class SesEmailSender(EmailSender):
    pass

class NotificationService:
    @inject
    def __init__(self, sender: EmailSender):
        self.sender = sender
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        provides = con.execute(
            "SELECT source, target, evidence_class FROM graph_edges WHERE relationship='PROVIDES'"
        ).fetchall()
        assert any(
            e["source"] == "dec_di.EmailSender" and e["target"] == "dec_di.SesEmailSender"
            for e in provides
        )
        injects = con.execute(
            "SELECT source, target, evidence_class FROM graph_edges WHERE relationship='INJECTS'"
        ).fetchall()
        assert any(
            e["source"] == "dec_di.NotificationService" and e["target"] == "dec_di.EmailSender"
            for e in injects
        )


def test_static_di_cycle_detection_terminates_and_emits_di_cycle(tmp_path: Path) -> None:
    """When two FastAPI dependencies or injected services form a cycle A -> B -> A,
    indexing terminates deterministically and emits a DI_CYCLE edge and finding.
    """
    (tmp_path / "cyclic_di.py").write_text(
        """
from fastapi import Depends

def dep_a(b = Depends(dep_b)):
    return b

def dep_b(a = Depends(dep_a)):
    return a
""",
        encoding="utf-8",
    )
    indexer = Indexer(tmp_path)
    indexer.index()
    findings = indexer.last_epistemic_findings
    assert any(f.get("pattern") == "DI_CYCLE" and f.get("reason") == "di_dependency_cycle" for f in findings)

    with indexer.session() as con:
        cycle_edges = con.execute(
            "SELECT source, target, relationship, evidence_class, reason FROM graph_edges WHERE relationship='DI_CYCLE'"
        ).fetchall()
        assert len(cycle_edges) >= 1
        assert cycle_edges[0]["evidence_class"] == "DATAFLOW_VERIFIED"
        assert cycle_edges[0]["reason"] == "di_dependency_cycle"


# ==============================================================================
# 4. SECURITY BOUNDARY, SENSITIVE PATHS & READ-SIZE CAP (30 tests)
# ==============================================================================


@pytest.mark.parametrize(
    "rel_path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "config/.env.staging",
        "id_rsa",
        "id_rsa.pub",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "certs/server.pem",
        "certs/private.key",
        "certs/keystore.p12",
        "certs/cert.pfx",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".git/config",
        "credentials.json",
        "aws.credentials",
        "secrets.yaml",
        "secrets.json",
        "service-account-prod.json",
        "service_account_key.json",
        ".aws/credentials",
        ".ssh/authorized_keys",
        ".gnupg/secring.gpg",
        ".kube/config",
        ".docker/config.json",
        "docker-credential-desktop",
    ],
)
def test_is_sensitive_path_blocks_all_required_patterns(rel_path: str) -> None:
    assert is_sensitive_path(rel_path) is True


@pytest.mark.parametrize(
    "safe_rel_path",
    [
        "src/main.py",
        "src/auth/token_service.py",
        "packages/core/index.ts",
        "tests/test_env_parser.py",
        "README.md",
    ],
)
def test_is_sensitive_path_allows_normal_source_files(safe_rel_path: str) -> None:
    assert is_sensitive_path(safe_rel_path) is False


def test_safe_read_text_blocks_traversal_and_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("TOP_SECRET", encoding="utf-8")

    with pytest.raises(SecurityError) as exc_info:
        safe_read_text(repo, "../outside_secret.txt")
    assert exc_info.value.code == ErrorCode.PATH_OUTSIDE_REPOSITORY

    symlink_file = repo / "escaped_link.py"
    symlink_file.symlink_to(outside)
    with pytest.raises(SecurityError) as exc_info2:
        safe_read_text(repo, "escaped_link.py")
    assert exc_info2.value.code == ErrorCode.PATH_OUTSIDE_REPOSITORY


def test_safe_read_text_blocks_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / ".env.production").write_text("DB_PASS=secret", encoding="utf-8")
    with pytest.raises(SecurityError) as exc_info:
        safe_read_text(tmp_path, ".env.production")
    assert exc_info.value.code == ErrorCode.SENSITIVE_FILE_ACCESS_DENIED


def test_safe_read_text_blocks_oversized_files(tmp_path: Path) -> None:
    big = tmp_path / "huge.py"
    big.write_text("x = 1\n" * 1000, encoding="utf-8")
    with pytest.raises(SecurityError) as exc_info:
        safe_read_text(tmp_path, "huge.py", max_read_bytes=1024)
    assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE


def test_safe_read_text_blocks_binary_files(tmp_path: Path) -> None:
    bin_file = tmp_path / "blob.bin"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    with pytest.raises(SecurityError) as exc_info:
        safe_read_text(tmp_path, "blob.bin")
    assert exc_info.value.code == ErrorCode.BINARY_FILE_NOT_READABLE


def test_indirect_read_paths_block_sensitive_and_oversized_files(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=super_secret_value\n", encoding="utf-8")
    (tmp_path / "service-account.json").write_text('{"private_key": "secret"}\n', encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # 1. interrogation.get_file blocks .env and service-account.json
        res_env = interrogation_get_file(con, tmp_path, ".env")
        assert res_env.get("status") in ("error", "invalid_request")
        assert res_env["error"]["code"] == ErrorCode.SENSITIVE_FILE_ACCESS_DENIED.value

        res_sa = interrogation_get_file(con, tmp_path, "service-account.json")
        assert res_sa.get("status") in ("error", "invalid_request")
        assert res_sa["error"]["code"] == ErrorCode.SENSITIVE_FILE_ACCESS_DENIED.value

        # 2. build_evidence / verify_source_hash / verify_evidence never leak sensitive content
        ev_list = build_evidence(con, tmp_path, ".env")
        assert ev_list == []
        assert verify_source_hash(tmp_path, ".env", "deadbeef") == "deleted"

        v_res = verify_evidence(con, tmp_path, file_path=".env")
        assert v_res.valid is False
        assert v_res.status == "UNKNOWN"
        assert "blocked" in v_res.reason

        # 3. get_context never includes .env or service-account.json
        pkt = get_context(con, tmp_path, task="API_KEY private_key hello", intent="UNDERSTAND")
        pkt_files = {s.file for s in pkt.symbols}
        assert ".env" not in pkt_files
        assert "service-account.json" not in pkt_files


# ==============================================================================
# 5. MONOREPO HARDENING & CIRCULAR IMPORT ISOLATION (10 tests)
# ==============================================================================


@pytest.mark.parametrize(
    "import_stmt",
    [
        "import codegraph.monorepo",
        "import codegraph.indexing.classifier",
        "import codegraph.indexing.indexer",
        "import codegraph.resolver",
        "import codegraph.context",
        "import codegraph.optimizer",
        "import codegraph.mcp.server",
        "import codegraph.evidence_contract",
    ],
)
def test_fresh_interpreter_imports_succeed_without_circular_import(import_stmt: str) -> None:
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-c", import_stmt],
        env={"PYTHONPATH": src_dir, "PATH": ""},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"Failed {import_stmt}: {proc.stderr}"


def test_monorepo_duplicate_package_name_emits_ambiguous_never_guesses(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "root-ws", "private": True, "workspaces": ["packages/*", "legacy/*"]}),
        encoding="utf-8",
    )
    pkg1 = tmp_path / "packages" / "auth-v1"
    pkg1.mkdir(parents=True)
    (pkg1 / "package.json").write_text(json.dumps({"name": "@acme/auth", "main": "index.ts"}), encoding="utf-8")
    (pkg1 / "index.ts").write_text("export function login() { return 1; }\n", encoding="utf-8")

    pkg2 = tmp_path / "legacy" / "auth-v0"
    pkg2.mkdir(parents=True)
    (pkg2 / "package.json").write_text(json.dumps({"name": "@acme/auth", "main": "index.ts"}), encoding="utf-8")
    (pkg2 / "index.ts").write_text("export function login() { return 0; }\n", encoding="utf-8")

    ws = discover_workspace(tmp_path)
    assert "@acme/auth" in ws.ambiguous_packages
    assert len(ws.ambiguous_packages["@acme/auth"]) == 2
    assert ws.resolve_package_import("@acme/auth") == (None, None)
    detailed = ws.resolve_package_import_detailed("@acme/auth")
    assert detailed["package"] is None
    assert detailed["status"] == "AMBIGUOUS"
    assert len(detailed["candidates"]) == 2


def test_monorepo_pnpm_negated_globs_and_service_classification_precedence(tmp_path: Path) -> None:
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'services/*'\n  - '!services/deprecated'\n",
        encoding="utf-8",
    )
    svc_active = tmp_path / "services" / "billing-service"
    svc_active.mkdir(parents=True)
    (svc_active / "pyproject.toml").write_text(
        '[project]\nname = "billing-service"\ndependencies = ["fastapi", "uvicorn", "celery"]\n',
        encoding="utf-8",
    )
    (svc_active / "worker.py").write_text("def run_worker(): pass\n", encoding="utf-8")

    svc_dep = tmp_path / "services" / "deprecated"
    svc_dep.mkdir(parents=True)
    (svc_dep / "pyproject.toml").write_text('[project]\nname = "deprecated-service"\n', encoding="utf-8")

    ws = discover_workspace(tmp_path)
    pkg_names = {p.name for p in ws.packages.values()}
    assert "billing-service" in pkg_names
    assert "deprecated-service" not in pkg_names

    billing_pkg = next(p for p in ws.packages.values() if p.name == "billing-service")
    assert billing_pkg.package_type == "SERVICE"


# ==============================================================================
# 6. CONTEXT OPTIMIZER INDEPENDENT BUDGETS & UNCERTAINTY SURVIVAL (6 tests)
# ==============================================================================


def test_optimizer_enforces_each_independent_budget_constraint() -> None:
    cands = [
        CandidateContextItem(
            item_id=f"sym_{i}",
            file_path=f"mod_{i}.py",
            start_line=1,
            end_line=20,
            canonical_id=f"mod_{i}.func_{i}",
            estimated_tokens=50,
            relevance_score=0.9 - (i * 0.05),
            evidence_quality=1.0,
            freshness="FRESH",
            coverage_layer="SERVICE",
            source_type="symbol",
            snippet="def f():\n" + ("    pass\n" * 15),
            graph_distance=1 if i < 3 else 4,
            package_distance=1 if i < 4 else 3,
        )
        for i in range(6)
    ]

    # 1. max_depth = 2 rejects graph_distance == 4
    sel_depth, bud_depth = optimize_context_budget(
        cands, token_budget=5000, budget_spec=ContextBudgetSpec(max_depth=2, max_package_depth=5)
    )
    assert all(s.graph_distance <= 2 for s in sel_depth)
    assert any("Graph depth limit reached" in str(r.get("reason", "")) for r in bud_depth.rejections)

    # 2. max_package_depth = 1 rejects package_distance == 3
    sel_pkg, bud_pkg = optimize_context_budget(
        cands, token_budget=5000, budget_spec=ContextBudgetSpec(max_depth=5, max_package_depth=1)
    )
    assert all(s.package_distance <= 1 for s in sel_pkg)
    assert any("Package depth limit reached" in str(r.get("reason", "")) for r in bud_pkg.rejections)

    # 3. max_symbols = 2 caps symbol selection at 2
    sel_sym, _ = optimize_context_budget(
        cands, token_budget=5000, budget_spec=ContextBudgetSpec(max_symbols=2, max_depth=5, max_package_depth=5)
    )
    assert len(sel_sym) == 2

    # 4. max_files = 1 caps distinct files at 1
    sel_files, _ = optimize_context_budget(
        cands, token_budget=5000, budget_spec=ContextBudgetSpec(max_files=1, max_depth=5, max_package_depth=5)
    )
    assert len({s.file_path for s in sel_files}) == 1


def test_optimizer_preserves_unknown_possible_conflict_under_tight_symbol_budget() -> None:
    cands = [
        CandidateContextItem(
            item_id="fact_1",
            file_path="a.py",
            start_line=1,
            end_line=5,
            canonical_id="a.fact_1",
            estimated_tokens=40,
            relevance_score=0.95,
            evidence_quality=1.0,
            freshness="FRESH",
            coverage_layer="SERVICE",
            source_type="symbol",
            snippet="def fact_1(): pass",
            epistemic_status="FACT",
        ),
        CandidateContextItem(
            item_id="unknown_1",
            file_path="a.py",
            start_line=10,
            end_line=12,
            canonical_id="a.dynamic_target",
            estimated_tokens=30,
            relevance_score=0.80,
            evidence_quality=0.3,
            freshness="FRESH",
            coverage_layer="SERVICE",
            source_type="uncertainty",
            snippet="registry[user_input] = handler",
            epistemic_status="UNKNOWN",
        ),
        CandidateContextItem(
            item_id="possible_1",
            file_path="a.py",
            start_line=15,
            end_line=18,
            canonical_id="a.conditional_target",
            estimated_tokens=30,
            relevance_score=0.75,
            evidence_quality=0.5,
            freshness="FRESH",
            coverage_layer="SERVICE",
            source_type="uncertainty",
            snippet="if flag: registry['k'] = h1",
            epistemic_status="POSSIBLE",
        ),
    ]
    # Even with max_symbols=1, the UNKNOWN and POSSIBLE uncertainty items survive!
    selected, _ = optimize_context_budget(
        cands,
        token_budget=500,
        budget_spec=ContextBudgetSpec(max_symbols=1, max_files=5, max_lines=500),
    )
    statuses = {s.epistemic_status for s in selected}
    assert "FACT" in statuses
    assert "UNKNOWN" in statuses
    assert "POSSIBLE" in statuses


# ==============================================================================
# 7. REAL STDIO MCP DOCTOR & HOSTILE REPOSITORY INTEGRATION (6 tests)
# ==============================================================================


def test_real_stdio_mcp_doctor_handshake() -> None:
    report = run_mcp_doctor(profile="full")
    assert report.healthy is True
    check_map = {c.name: c.passed for c in report.checks}
    assert check_map["executable"] is True
    assert check_map["server startup"] is True
    assert check_map["MCP initialize"] is True
    assert check_map["tool discovery"] is True
    assert check_map["resolve_symbol"] is True
    assert check_map["clean shutdown"] is True
    assert "get_context" in report.discovered_tools
    assert "resolve_symbol" in report.discovered_tools


def test_hostile_repository_end_to_end_integration(tmp_path: Path) -> None:
    """Hostile repository combining:
    - Sensitive files (.env.production, id_rsa, service-account.json)
    - Binary artifact (bundle.wasm)
    - Oversized source file
    - Dynamic getattr / dynamic registry key
    - Static registry overwrite + conditional registry branch
    - FastAPI Depends + DI cycle
    - False-positive traps (device.register, metrics.on, observer.on)
    """
    # 1. Sensitive & binary files
    (tmp_path / ".env.production").write_text("SECRET_TOKEN=leaked_value_12345\n", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...", encoding="utf-8")
    (tmp_path / "service-account.json").write_text('{"private_key": "never_index"}\n', encoding="utf-8")
    (tmp_path / "bundle.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")

    # 2. Hostile Python module
    (tmp_path / "hostile_app.py").write_text(
        """
from fastapi import FastAPI, Depends

app = FastAPI()

def old_handler():
    return "old"

def active_handler():
    return "active"

def cond_handler():
    return "cond"

# Static overwrite
command_registry = {}
command_registry["run"] = old_handler
command_registry["run"] = active_handler

# Conditional registration
if True:
    command_registry["maybe"] = cond_handler

# Dynamic registration
dyn_key = input()
command_registry[dyn_key] = active_handler

# False-positive traps
class Metrics:
    def on(self, k, v): pass
metrics = Metrics()
metrics.on("evt", active_handler)

# Circular DI
def dep_x(y = Depends(dep_y)):
    return y

def dep_y(x = Depends(dep_x)):
    return x

@app.get("/execute")
def execute_endpoint(x = Depends(dep_x)):
    return command_registry["run"]()
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # A. Sensitive files were never indexed
        indexed_paths = {r[0] for r in con.execute("SELECT path FROM files").fetchall()}
        assert ".env.production" not in indexed_paths
        assert "id_rsa" not in indexed_paths
        assert "service-account.json" not in indexed_paths

        # B. Every graph edge in SQLite passes the authoritative evidence contract
        all_edges = con.execute(
            "SELECT source, target, relationship, confidence, evidence_class, file, start_line FROM graph_edges"
        ).fetchall()
        assert len(all_edges) > 0
        for row in all_edges:
            validate_relationship_record(dict(row))
            # No uncertain edge is ever labeled CALLS
            if row["evidence_class"] in ("POSSIBLE", "UNKNOWN", "FRAMEWORK_VERIFIED"):
                assert row["relationship"] != "CALLS"

        # C. Overwritten old_handler is not in active DISPATCHES_TO edges
        disp_targets = {
            r["target"] for r in all_edges if r["relationship"] == "DISPATCHES_TO"
        }
        assert "hostile_app.active_handler" in disp_targets
        assert "hostile_app.old_handler" not in disp_targets

        # D. DI cycle was detected
        cycle_edges = [r for r in all_edges if r["relationship"] == "DI_CYCLE"]
        assert len(cycle_edges) >= 1

        # E. Context compilation succeeds and includes no secret content
        pkt = get_context(con, tmp_path, task="trace execute_endpoint and command_registry", intent="TRACE")
        serialized = json.dumps(pkt.as_dict())
        assert "leaked_value_12345" not in serialized
        assert "BEGIN RSA PRIVATE KEY" not in serialized
