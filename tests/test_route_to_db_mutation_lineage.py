"""Acceptance tests for Step 2: Route -> Database Mutation Lineage.

Verifies:
1. End-to-end bounded traversal:
   POST /api/v1/orders/checkout
           ↓
   checkout()
           ↓
   OrderService.checkout()
           ↓
   InventoryRepository
           ↓
   ORM / SQL
           ↓
   inventory (read & write)
   orders (write)
   payments (write)
2. Exact source evidence citations, call chain lineage, deterministic ordering (table ASC, column ASC).
3. No unrelated tables (e.g. audit_logs, products).
4. Preservation of UNKNOWN epistemic states when reachable queries are dynamic.
5. Integration into list_routes and direct get_route_db_lineage calls.
6. Cycle protection and bounded depth (max_depth=4).
"""
from __future__ import annotations

from pathlib import Path

from codegraph.database import get_route_db_lineage
from codegraph.indexing.indexer import Indexer
from codegraph.interrogation import list_routes


def _create_fullstack_checkout_repo(root: Path) -> None:
    (root / "models.py").write_text(
        """
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    sku = Column(String, nullable=False)
    quantity = Column(Integer, default=0)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    status = Column(String, default="pending")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String, default="completed")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
""",
        encoding="utf-8",
    )

    (root / "repositories.py").write_text(
        """
class InventoryRepository:
    def get_stock(self, session, item_id: int):
        cursor = session.connection()
        cursor.execute("SELECT id, quantity, sku FROM inventory WHERE id = :id", {"id": item_id})

    def update_stock(self, session, item_id: int, new_qty: int):
        cursor = session.connection()
        cursor.execute("UPDATE inventory SET quantity = :qty WHERE id = :id", {"qty": new_qty, "id": item_id})

class AuditRepository:
    def log_event(self, session, action: str):
        cursor = session.connection()
        cursor.execute("INSERT INTO audit_logs (id, action) VALUES (:id, :action)", {"id": 1, "action": action})
""",
        encoding="utf-8",
    )

    (root / "services.py").write_text(
        """
from repositories import InventoryRepository

class OrderService:
    def checkout(self, session, user_id: int, item_id: int, amount: int):
        inv_repo = InventoryRepository()
        inv_repo.get_stock(session, item_id)
        inv_repo.update_stock(session, item_id, 10)
        cursor = session.connection()
        cursor.execute(
            "INSERT INTO orders (id, user_id, total, status) VALUES (:id, :user_id, :total, :status)",
            {"id": 100, "user_id": user_id, "total": amount, "status": "paid"},
        )
        cursor.execute(
            "INSERT INTO payments (id, order_id, amount, status) VALUES (:id, :order_id, :amount, :status)",
            {"id": 200, "order_id": 100, "amount": amount, "status": "success"},
        )
""",
        encoding="utf-8",
    )

    (root / "routes.py").write_text(
        """
from fastapi import APIRouter
from services import OrderService
from repositories import AuditRepository

router = APIRouter()

@router.post("/api/v1/orders/checkout")
def checkout(session=None):
    svc = OrderService()
    svc.checkout(session, user_id=1, item_id=42, amount=99)

@router.post("/api/v1/dynamic-exec")
def dynamic_exec(table_name: str, session=None):
    cursor = session.connection()
    cursor.execute(f"SELECT * FROM {table_name}")

@router.get("/api/v1/audit/logs")
def get_audit_logs(session=None):
    audit = AuditRepository()
    audit.log_event(session, "viewed_logs")
""",
        encoding="utf-8",
    )


def test_route_to_db_mutation_lineage_acceptance(tmp_path: Path) -> None:
    """Acceptance test verifying route -> handler -> service -> repo -> ORM/SQL -> table lineage."""
    _create_fullstack_checkout_repo(tmp_path)
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # 1. Query lineage for checkout route directly
        lineage = get_route_db_lineage(con, "POST /api/v1/orders/checkout")
        assert lineage["status"] == "ok"
        assert lineage["route"] == "/api/v1/orders/checkout"
        assert lineage["method"] == "POST"

        # Verify db_reads contains inventory with deterministic columns [id, quantity, sku]
        reads = lineage["db_reads"]
        assert len(reads) == 1
        inv_read = reads[0]
        assert inv_read["table"] == "inventory"
        assert inv_read["columns"] == ["id", "quantity", "sku"]
        assert inv_read["operations"] == ["SELECT"]
        assert inv_read["evidence_class"] == "AST_VERIFIED"
        assert inv_read["confidence"] == "HIGH"
        assert len(inv_read["call_chain"]) >= 2
        assert "checkout" in inv_read["call_chain"]
        assert len(inv_read["evidence"]) >= 1

        # Verify db_writes contains [inventory, orders, payments] in deterministic sorted order
        writes = lineage["db_writes"]
        write_tables = [w["table"] for w in writes]
        assert write_tables == ["inventory", "orders", "payments"]

        # Check inventory write
        inv_write = writes[0]
        assert inv_write["table"] == "inventory"
        assert inv_write["columns"] == ["quantity"]
        assert inv_write["operations"] == ["UPDATE"]
        assert inv_write["evidence_class"] == "AST_VERIFIED"
        assert inv_write["confidence"] == "HIGH"
        assert len(inv_write["call_chain"]) >= 2
        assert "checkout" in inv_write["call_chain"]

        # Check orders write
        order_write = writes[1]
        assert order_write["table"] == "orders"
        assert order_write["columns"] == ["id", "status", "total", "user_id"]
        assert order_write["operations"] == ["INSERT"]
        assert order_write["evidence_class"] == "AST_VERIFIED"

        # Check payments write
        payment_write = writes[2]
        assert payment_write["table"] == "payments"
        assert payment_write["columns"] == ["amount", "id", "order_id", "status"]
        assert payment_write["operations"] == ["INSERT"]
        assert payment_write["evidence_class"] == "AST_VERIFIED"

        # INVARIANT: No unrelated tables (audit_logs, products) must appear in checkout lineage
        all_lineage_tables = set(lineage["tables"])
        assert "audit_logs" not in all_lineage_tables
        assert "products" not in all_lineage_tables
        assert all_lineage_tables == {"inventory", "orders", "payments"}
        assert lineage["evidence_class"] == "AST_VERIFIED"


def test_list_routes_includes_db_reads_and_writes(tmp_path: Path) -> None:
    """Verify list_routes exposes db_reads and db_writes on every route dictionary."""
    _create_fullstack_checkout_repo(tmp_path)
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        res = list_routes(con, tmp_path)
        assert res["status"] == "ok"
        routes = res["routes"]
        checkout_route = next(r for r in routes if r["path"] == "/api/v1/orders/checkout")

        assert "db_reads" in checkout_route
        assert "db_writes" in checkout_route
        assert [r["table"] for r in checkout_route["db_reads"]] == ["inventory"]
        assert [w["table"] for w in checkout_route["db_writes"]] == ["inventory", "orders", "payments"]

        # Unrelated route only touches its own tables
        audit_route = next(r for r in routes if r["path"] == "/api/v1/audit/logs")
        assert [w["table"] for w in audit_route["db_writes"]] == ["audit_logs"]
        assert [r["table"] for r in audit_route["db_reads"]] == []


def test_dynamic_query_preserves_unknown_epistemic_state(tmp_path: Path) -> None:
    """Verify UNKNOWN epistemic state is preserved when reachable SQL cannot be statically proven."""
    _create_fullstack_checkout_repo(tmp_path)
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        dyn_lineage = get_route_db_lineage(con, "POST /api/v1/dynamic-exec")
        assert dyn_lineage["status"] == "ok"
        assert dyn_lineage["evidence_class"] == "UNKNOWN"
        tables = dyn_lineage["tables"]
        assert "UNKNOWN" in tables


def test_cycle_protection_and_bounded_traversal(tmp_path: Path) -> None:
    """Verify that recursive/cyclic calls and depth bounds terminate cleanly without infinite loops."""
    (tmp_path / "cyclic_app.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter()

def service_a(session):
    service_b(session)

def service_b(session):
    service_a(session)

@router.get("/api/v1/cyclic")
def cyclic_endpoint(session=None):
    service_a(session)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        res = get_route_db_lineage(con, "/api/v1/cyclic", max_depth=3)
        assert res["status"] == "ok"
        assert res["db_reads"] == []
        assert res["db_writes"] == []
        assert res["tables"] == []
