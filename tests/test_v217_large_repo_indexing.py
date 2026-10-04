"""Regression and performance invariant tests for CodeGraph v2.1.7 Large Repository Indexing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.config import Settings
from codegraph.graph.models import GraphEdge
from codegraph.indexing.indexer import Indexer, check_database_health
from codegraph.indexing.models import normalize_module
from codegraph.indexing.telemetry import (
    INDEXING_PHASES,
    IndexingTelemetry,
    format_progress_block,
)

runner = CliRunner()


def _create_sample_repo(root: Path, num_modules: int = 12) -> Path:
    """Create a realistic multi-file repository with routes, ORM models, queries, and tests."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('"""App package."""\n', encoding="utf-8")

    (pkg / "models.py").write_text(
        '''"""Database models."""
from sqlalchemy import Column, Integer, String, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase

engine = create_engine("postgresql://localhost:5432/appdb")

class Base(DeclarativeBase):
    pass

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    total_cents = Column(Integer, nullable=False)
''',
        encoding="utf-8",
    )

    (pkg / "repository.py").write_text(
        '''"""Database access layer."""
from .models import Account, Invoice

def find_account(session, email: str):
    return session.query(Account).filter_by(email=email).first()

def create_invoice(session, account_id: int, total_cents: int):
    inv = Invoice(account_id=account_id, total_cents=total_cents)
    session.add(inv)
    session.commit()
    return inv
''',
        encoding="utf-8",
    )

    (pkg / "routes.py").write_text(
        '''"""FastAPI routes."""
from fastapi import APIRouter
from .repository import find_account, create_invoice

router = APIRouter(prefix="/api")

@router.get("/accounts/{email}")
def get_account_endpoint(email: str, session=None):
    return find_account(session, email)

@router.post("/invoices")
def post_invoice_endpoint(account_id: int, total_cents: int, session=None):
    return create_invoice(session, account_id, total_cents)
''',
        encoding="utf-8",
    )

    for i in range(num_modules):
        (pkg / f"service_{i:02d}.py").write_text(
            f'''"""Service module {i}."""
from .repository import find_account

class Service{i}:
    def process(self, session, email: str):
        acct = find_account(session, email)
        return acct
''',
            encoding="utf-8",
        )

    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_routes.py").write_text(
        '''"""Route tests."""
from app.routes import get_account_endpoint, post_invoice_endpoint

def test_endpoints():
    assert callable(get_account_endpoint)
    assert callable(post_invoice_endpoint)
''',
        encoding="utf-8",
    )
    return root


def test_16_phase_telemetry_and_progress_formatting(tmp_path: Path) -> None:
    """Phase 1: All 16 indexing pipeline phases are deterministically recorded."""
    repo = _create_sample_repo(tmp_path, num_modules=8)
    seen_phases: list[str] = []

    def _on_progress(phase: str, current: int, total: int, tel: IndexingTelemetry) -> None:
        seen_phases.append(phase)
        assert current <= total

    indexer = Indexer(repo, Settings(repository=repo), commit_batch_size=4)
    res = indexer.index(progress_callback=_on_progress)
    assert res["scanned"] == 13
    assert res["indexed"] == 13

    tel = indexer.last_telemetry
    assert tel is not None
    assert set(tel.phases.keys()) == {k for k, _ in INDEXING_PHASES}
    assert len(tel.phases) == 16

    assert tel.phases["repository_scan"].files_processed == 13
    assert tel.phases["file_reading"].files_processed == 13
    assert tel.phases["file_classification"].files_processed == 13
    assert tel.phases["ast_parsing"].files_processed == 13
    assert tel.phases["symbol_extraction"].items_processed > 0
    assert tel.phases["import_extraction"].items_processed > 0
    assert tel.phases["framework_analysis"].items_processed > 0
    assert tel.phases["database_analysis"].items_processed > 0
    assert tel.phases["symbol_resolution"].items_processed > 0
    assert tel.phases["relationship_resolution"].items_processed > 0
    assert tel.phases["graph_edge_creation"].items_processed > 0
    assert tel.phases["sqlite_writes"].db_writes > 0
    assert tel.phases["fts_updates"].db_writes > 0
    assert tel.phases["post_processing"].elapsed_seconds > 0
    assert tel.phases["final_commit_checkpoint"].db_writes > 0

    assert tel.rss_before_mb >= 0.0
    assert tel.post_parse_rss_mb >= 0.0
    assert tel.peak_rss_mb >= tel.rss_before_mb
    assert tel.steady_state_rss_mb >= 0.0
    assert tel.commit_batches >= 3
    assert tel.checkpoints >= 3
    assert len(seen_phases) >= 4

    block = format_progress_block("symbol_resolution", 18420, 28573, 252.0, memory_mb=410.0)
    assert "Phase: Symbol Resolution" in block
    assert "18,420 / 28,573 files" in block
    assert "64%" in block
    assert "elapsed: 4m 12s" in block
    assert "files/min" in block
    assert "memory: 410 MB" in block


def test_wildcard_and_reexport_budget_safeguards(tmp_path: Path) -> None:
    """Phase 4: Wildcard imports and deep/cyclic re-exports respect budgets and emit UNKNOWN findings."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    # 1. Cyclic wildcard imports between cycle_a and cycle_b must terminate cleanly
    (pkg / "cycle_a.py").write_text("from .cycle_b import *\ndef func_a(): return 1\n", encoding="utf-8")
    (pkg / "cycle_b.py").write_text("from .cycle_a import *\ndef func_b(): return 2\n", encoding="utf-8")
    (pkg / "use_cycle.py").write_text(
        "from .cycle_a import *\ndef call_both():\n    return func_a() + func_b()\n",
        encoding="utf-8",
    )

    # 2. Deep re-export chain exceeding max_reexport_depth=3
    (pkg / "deep_0.py").write_text("def deep_target(): return 42\n", encoding="utf-8")
    for depth in range(1, 6):
        (pkg / f"deep_{depth}.py").write_text(
            f"from .deep_{depth - 1} import deep_target\n__all__ = ['deep_target']\n",
            encoding="utf-8",
        )
    (pkg / "use_deep.py").write_text(
        "from .deep_5 import deep_target\ndef run_deep():\n    return deep_target()\n",
        encoding="utf-8",
    )

    # Index with tight max_reexport_depth=3 to trigger budget protection
    indexer = Indexer(
        tmp_path,
        Settings(repository=tmp_path),
        max_reexport_depth=3,
        max_wildcard_expansions=10,
    )
    res = indexer.index()
    assert res["indexed"] == 11

    budget_findings = [
        f for f in indexer.last_epistemic_findings
        if f.get("reason") == "resolution_budget_exceeded"
    ]
    assert len(budget_findings) >= 1
    assert all(f["status"] == "UNKNOWN" for f in budget_findings)

    # Now index with default budget (depth=16) and verify deep_target resolves cleanly
    indexer_full = Indexer(tmp_path, Settings(repository=tmp_path))
    indexer_full.db_path.unlink(missing_ok=True)
    indexer_full.index()
    with indexer_full.session() as con:
        edge = con.execute(
            "SELECT target, confidence FROM graph_edges "
            "WHERE source LIKE '%run_deep' AND relationship='CALLS'"
        ).fetchone()
        assert edge is not None
        assert "deep_target" in str(edge["target"])
        assert str(edge["confidence"]) == "HIGH"


def test_sqlite_composite_indexes_and_wal_truncation(tmp_path: Path) -> None:
    """Phases 5 & 6: Composite indexes are used by query planner and WAL is truncated on finish."""
    repo = _create_sample_repo(tmp_path, num_modules=20)
    indexer = Indexer(repo, Settings(repository=repo), commit_batch_size=5)
    indexer.index()

    tel = indexer.last_telemetry
    assert tel is not None
    # Final TRUNCATE checkpoint should reduce WAL to 0 bytes when no other connection is open
    assert tel.final_wal_bytes == 0

    with indexer.session() as con:
        plan_imp = con.execute(
            "EXPLAIN QUERY PLAN UPDATE imports SET resolved_path=?, resolved_module=? "
            "WHERE source_path=? AND line=? AND (local_name=? OR alias=? OR name=?)",
            ("a.py", "a", "b.py", 1, "x", "x", "x"),
        ).fetchall()
        plan_imp_str = " ".join(str(tuple(r)) for r in plan_imp)
        assert "idx_imports_source_line" in plan_imp_str

        plan_call = con.execute(
            "EXPLAIN QUERY PLAN UPDATE calls SET resolved_symbol_id=?, confidence=? "
            "WHERE source_path=? AND line=? AND callee=?",
            ("id", "HIGH", "b.py", 1, "fn"),
        ).fetchall()
        plan_call_str = " ".join(str(tuple(r)) for r in plan_call)
        assert "idx_calls_source_line" in plan_call_str


def test_incremental_dirty_file_database_intelligence(tmp_path: Path) -> None:
    """Phases 7 & 8: Streaming DB pass and incremental dirty-file DB update preserve all DB facts."""
    repo = _create_sample_repo(tmp_path, num_modules=10)
    indexer = Indexer(repo, Settings(repository=repo))
    indexer.index()

    with indexer.session() as con:
        initial_entities = con.execute("SELECT count(*) FROM db_entities").fetchone()[0]
        initial_queries = con.execute("SELECT count(*) FROM db_queries").fetchone()[0]
        initial_db_edges = con.execute(
            "SELECT count(*) FROM graph_edges WHERE relationship IN ('MAPS_TO_TABLE', 'READS_TABLE', 'WRITES_TABLE', 'FOREIGN_KEY_TO')"
        ).fetchone()[0]
    assert initial_entities >= 4
    assert initial_queries >= 2
    assert initial_db_edges >= 4

    # Modify a single service file (1 dirty file out of 15)
    svc0 = repo / "app" / "service_00.py"
    svc0.write_text(
        svc0.read_text(encoding="utf-8") + "\ndef extra_helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    indexer2 = Indexer(repo, Settings(repository=repo))
    res2 = indexer2.index()
    assert res2["indexed"] == 1
    assert res2["unchanged"] == 14

    tel2 = indexer2.last_telemetry
    assert tel2 is not None
    # Incremental DB pass should process only the 1 dirty file
    assert tel2.phases["database_analysis"].files_processed == 1

    with indexer2.session() as con:
        after_entities = con.execute("SELECT count(*) FROM db_entities").fetchone()[0]
        after_queries = con.execute("SELECT count(*) FROM db_queries").fetchone()[0]
        after_db_edges = con.execute(
            "SELECT count(*) FROM graph_edges WHERE relationship IN ('MAPS_TO_TABLE', 'READS_TABLE', 'WRITES_TABLE', 'FOREIGN_KEY_TO')"
        ).fetchone()[0]
        health = check_database_health(con, repo)

    assert after_entities == initial_entities
    assert after_queries == initial_queries
    assert after_db_edges == initial_db_edges
    assert health["status"] == "OK"


def test_ctrl_c_cancellation_and_clean_resume(tmp_path: Path) -> None:
    """Phase 9: Ctrl+C rolls back only active uncommitted batch, leaves DB valid, and resumes cleanly."""
    repo = _create_sample_repo(tmp_path, num_modules=15)

    # Interrupt after the first committed batch of 5 files
    def _interrupt_after_first_batch(phase: str, current: int, total: int, tel: IndexingTelemetry) -> None:
        if phase == "ast_parsing" and current >= 5:
            raise KeyboardInterrupt("Simulated Ctrl+C after first batch")

    indexer = Indexer(repo, Settings(repository=repo), commit_batch_size=5)
    partial = indexer.index(progress_callback=_interrupt_after_first_batch, catch_interrupt=True)
    assert partial.get("interrupted") == 1
    assert partial["indexed"] == 5
    assert indexer.last_telemetry is not None
    assert indexer.last_telemetry.interrupted is True

    # Verify DB health and metadata after interruption
    with indexer.session() as con:
        health = check_database_health(con, repo)
        assert health["status"] == "OK"
        files_in_db = con.execute("SELECT count(*) FROM files").fetchone()[0]
        assert files_in_db == 5
        status_row = con.execute("SELECT value FROM metadata WHERE key='index_status'").fetchone()
        dirty_row = con.execute("SELECT value FROM metadata WHERE key='resolution_dirty'").fetchone()
        assert str(status_row[0]) == "interrupted"
        assert str(dirty_row[0]) == "1"

    # Resume indexing on the next run: the 5 committed files are skipped (unchanged), remaining 15 are indexed
    indexer_resume = Indexer(repo, Settings(repository=repo), commit_batch_size=5)
    resumed = indexer_resume.index()
    assert resumed["unchanged"] == 5
    assert resumed["indexed"] == 15
    assert resumed["scanned"] == 20

    with indexer_resume.session() as con:
        health = check_database_health(con, repo)
        assert health["status"] == "OK"
        assert con.execute("SELECT count(*) FROM files").fetchone()[0] == 20
        assert con.execute("SELECT count(*) FROM graph_edges").fetchone()[0] > 0
        assert con.execute("SELECT count(*) FROM db_entities").fetchone()[0] >= 4
        status_row = con.execute("SELECT value FROM metadata WHERE key='index_status'").fetchone()
        dirty_row = con.execute("SELECT value FROM metadata WHERE key='resolution_dirty'").fetchone()
        assert str(status_row[0]) == "ok"
        assert str(dirty_row[0]) == "0"


def test_ctrl_c_during_post_processing_resumes_resolution(tmp_path: Path) -> None:
    """Phase 9: Ctrl+C during post-processing after all files are committed still runs resolution on resume."""
    repo = _create_sample_repo(tmp_path, num_modules=4)

    def _interrupt_in_post(phase: str, current: int, total: int, tel: IndexingTelemetry) -> None:
        if phase == "symbol_resolution":
            raise KeyboardInterrupt("Simulated Ctrl+C during symbol resolution")

    indexer = Indexer(repo, Settings(repository=repo), commit_batch_size=20)
    with pytest.raises(KeyboardInterrupt):
        indexer.index(progress_callback=_interrupt_in_post, catch_interrupt=False)

    # All 9 files were committed prior to post-processing, but resolution_dirty is '1'
    indexer_resume = Indexer(repo, Settings(repository=repo))
    resumed = indexer_resume.index()
    assert resumed["unchanged"] == 9
    assert resumed["indexed"] == 0

    with indexer_resume.session() as con:
        assert con.execute("SELECT count(*) FROM graph_edges").fetchone()[0] > 0
        dirty_row = con.execute("SELECT value FROM metadata WHERE key='resolution_dirty'").fetchone()
        assert str(dirty_row[0]) == "0"


def test_cli_index_quiet_verbose_json_modes(tmp_path: Path) -> None:
    """Phase 10: CLI `codegraph index` supports --quiet, --verbose, and --json."""
    repo = _create_sample_repo(tmp_path, num_modules=4)

    # 1. --quiet mode produces no stdout
    res_q = runner.invoke(app, ["index", str(repo), "--quiet"])
    assert res_q.exit_code == 0
    assert res_q.stdout.strip() == ""

    # 2. --verbose mode prints progress blocks and phase summary
    (repo / "app" / "service_00.py").write_text(
        (repo / "app" / "service_00.py").read_text(encoding="utf-8") + "\n# verbose touch\n",
        encoding="utf-8",
    )
    res_v = runner.invoke(app, ["index", str(repo), "--verbose"])
    assert res_v.exit_code == 0
    assert "Phase:" in res_v.stdout
    assert "Summary: elapsed=" in res_v.stdout
    assert "indexed=1" in res_v.stdout

    # 3. --json mode outputs structured summary + 16-phase telemetry
    res_j = runner.invoke(app, ["index", str(repo), "--json"])
    assert res_j.exit_code == 0
    data = json.loads(res_j.stdout)
    assert data["scanned"] == 9
    assert "telemetry" in data
    assert len(data["telemetry"]["phases"]) == 16


def test_graph_edge_direct_validation_and_normalize_module_cache() -> None:
    """Phase 3: Direct GraphEdge validation and normalize_module caching preserve invariants."""
    assert normalize_module("app/services/auth.py") == "app.services.auth"
    assert normalize_module("app/services/__init__.py") == "app.services"

    with pytest.raises(ValueError, match="non-empty"):
        GraphEdge(
            source="",
            target="b",
            relationship="CALLS",
            confidence="HIGH",
            file="a.py",
            start_line=1,
            end_line=1,
            evidence="b()",
        )
