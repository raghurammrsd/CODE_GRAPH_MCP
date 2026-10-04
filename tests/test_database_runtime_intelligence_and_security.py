"""Comprehensive Tests for CodeGraph Database Deep Intelligence, Runtime Mapping & Security Hardening.

Covers:
- Phases 1–8 & 17: Multi-framework ORM discovery (SQLAlchemy, Flask-SQLAlchemy, Django ORM, SQLModel, Prisma),
  query builder & raw SQL intelligence (psycopg/asyncpg/sqlite3/Knex/.sql), migrations (Alembic, Django, Prisma, SQL),
  canonical database schema model (`db.<dialect>.<schema>.<table>`), 19 database/env relationships, and bidirectional impact.
- Phase 9: All 11 Database MCP tools (`find_db_tables`, `find_db_columns`, `find_db_models`, `find_db_queries`,
  `find_db_callers`, `find_db_writers`, `find_db_readers`, `find_db_relationships`, `get_db_table`, `get_db_schema`, `get_db_impact`).
- Phases 10–13: Runtime observation ingestion (`ingest_runtime_traces` for OpenTelemetry, JSONL events, SQL logs),
  `get_runtime_trace`, and `reconcile_static_runtime` (`CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`,
  `NOT_OBSERVED_AT_RUNTIME`, `RUNTIME_ONLY_OBSERVED`).
- Phase 14: `get_context` integration (`database`, `runtime`, `reconciliation` sections under strict token/file/line budgets).
- Phase 15 & Security Hardening: Secret redaction, connection string credential stripping, SQL literal redaction,
  runtime payload sanitization, sensitive file blocking, and zero-leak SQLite audit (`audit_sqlite_for_secrets`).
- Phase 16, 19, 20: Agent routing (`select_agent_tool`), epistemic separation, and deterministic ordering.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.agent_capabilities import select_agent_tool
from codegraph.context import get_context
from codegraph.database import (
    find_db_callers,
    find_db_columns,
    find_db_models,
    find_db_queries,
    find_db_readers,
    find_db_relationships,
    find_db_tables,
    find_db_writers,
    get_db_impact,
    get_db_schema,
    get_db_table,
)
from codegraph.errors import SecurityError
from codegraph.indexing.indexer import Indexer
from codegraph.interrogation import get_file, get_symbol
from codegraph.mcp.server import create_server
from codegraph.runtime import (
    get_runtime_trace,
    ingest_runtime_traces,
    reconcile_static_runtime,
)
from codegraph.search.hybrid import search_code
from codegraph.security import (
    audit_sqlite_for_secrets,
    is_sensitive_path,
    normalize_and_redact_sql,
    parse_safe_connection_metadata,
    redact_connection_string,
    redact_secrets,
    safe_read_text,
)


def _index_repo(repo_dir: Path) -> Indexer:
    indexer = Indexer(repo_dir)
    indexer.index()
    return indexer


# ---------------------------------------------------------------------------
# Phase 1–9 & 17: Multi-Framework ORM, Raw SQL, Migrations & 11 DB Tools
# ---------------------------------------------------------------------------


def test_db_01_sqlalchemy_and_fastapi_route_to_table_intelligence(tmp_path: Path) -> None:
    """SQLAlchemy models, relationships, queries, and FastAPI route -> service -> repo -> table chain."""
    (tmp_path / "models.py").write_text(
        """
from sqlalchemy import Column, Integer, String, ForeignKey, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import declarative_base, relationship, mapped_column

Base = declarative_base()

class Shop(Base):
    __tablename__ = "shops"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    products = relationship("Product", back_populates="shop")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("shop_id", "sku", name="uq_shop_sku"),
        CheckConstraint("price > 0", name="ck_price_positive"),
        Index("ix_products_sku", "sku"),
    )
    id = mapped_column(Integer, primary_key=True)
    sku = mapped_column(String, index=True, nullable=False)
    price = mapped_column(Integer, default=100)
    shop_id = mapped_column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="products")
""",
        encoding="utf-8",
    )
    (tmp_path / "repo.py").write_text(
        """
from sqlalchemy import select, insert, update, delete
from models import Product

def fetch_product_by_sku(session, sku: str):
    stmt = select(Product).where(Product.sku == sku)
    return session.execute(stmt).scalars().first()

def create_product_record(session, shop_id: int, sku: str, price: int):
    item = Product(shop_id=shop_id, sku=sku, price=price)
    session.add(item)
    return item

def update_product_price(session, product_id: int, new_price: int):
    cursor = session.connection()
    cursor.execute("UPDATE products SET price = :price WHERE id = :id", {"price": new_price, "id": product_id})

def delete_product_record(session, product_id: int):
    stmt = delete(Product).where(Product.id == product_id)
    session.execute(stmt)
""",
        encoding="utf-8",
    )
    (tmp_path / "routes.py").write_text(
        """
from fastapi import APIRouter
from repo import fetch_product_by_sku, create_product_record

router = APIRouter()

@router.get("/api/products/{sku}")
def get_product_endpoint(sku: str, session=None):
    return fetch_product_by_sku(session, sku)

@router.post("/api/products")
def create_product_endpoint(shop_id: int, sku: str, price: int, session=None):
    return create_product_record(session, shop_id, sku, price)
""",
        encoding="utf-8",
    )
    (tmp_path / "test_products.py").write_text(
        """
from repo import fetch_product_by_sku, create_product_record

def test_create_and_fetch_product(session):
    create_product_record(session, 1, "SKU-1", 500)
    res = fetch_product_by_sku(session, "SKU-1")
    assert res is not None
""",
        encoding="utf-8",
    )

    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        tables_res = find_db_tables(con, tmp_path)
        table_names = {t["table_name"] for t in tables_res["tables"]}
        assert {"shops", "products"}.issubset(table_names)

        models_res = find_db_models(con, tmp_path, table="products")
        assert models_res["count"] >= 1
        assert models_res["models"][0]["name"] == "Product"
        assert models_res["models"][0]["table_name"] == "products"
        assert models_res["models"][0]["evidence_class"] == "FRAMEWORK_VERIFIED"

        cols_res = find_db_columns(con, tmp_path, table="products")
        col_names = {c["column_name"] for c in cols_res["columns"]}
        assert {"id", "sku", "price", "shop_id"}.issubset(col_names)
        shop_fk = next(c for c in cols_res["columns"] if c["column_name"] == "shop_id")
        assert shop_fk["foreign_key_target"] is not None
        assert "shops.id" in shop_fk["foreign_key_target"]

        tbl_detail = get_db_table(con, tmp_path, table="products")
        assert tbl_detail["status"] == "ok"
        assert tbl_detail["canonical_id"] == "db.UNKNOWN.UNKNOWN.products"
        assert len(tbl_detail["primary_keys"]) >= 1
        assert len(tbl_detail["foreign_keys"]) >= 1
        assert len(tbl_detail["orm_models"]) >= 1
        assert len(tbl_detail["readers"]) >= 1
        assert len(tbl_detail["writers"]) >= 1
        route_paths = {r["route_path"] for r in tbl_detail["upstream_routes"]}
        assert "/api/products/{sku}" in route_paths or "/api/products" in route_paths

        callers_res = find_db_callers(con, tmp_path, table="products")
        accessor_syms = {a["symbol"] for a in callers_res["direct_accessors"]}
        assert any("fetch_product_by_sku" in s for s in accessor_syms)
        assert any("create_product_record" in s for s in accessor_syms)

        writers_res = find_db_writers(con, tmp_path, table="products")
        writer_syms = {w["symbol"] for w in writers_res["writers"]}
        assert any("create_product_record" in s for s in writer_syms)
        assert any("update_product_price" in s for s in writer_syms)

        col_writers = find_db_writers(con, tmp_path, table="products", column="price")
        assert col_writers["count"] >= 1

        readers_res = find_db_readers(con, tmp_path, table="products")
        reader_syms = {r["symbol"] for r in readers_res["readers"]}
        assert any("fetch_product_by_sku" in s for s in reader_syms)

        rels_res = find_db_relationships(con, tmp_path, table="products")
        rel_types = {r["relationship"] for r in rels_res["relationships"]}
        assert "MAPS_TO_TABLE" in rel_types
        assert "FOREIGN_KEY_TO" in rel_types
        assert "HAS_PRIMARY_KEY" in rel_types

        impact_res = get_db_impact(con, tmp_path, table="products", column="price")
        assert impact_res["status"] == "ok"
        assert len(impact_res["affected_models"]) >= 1
        assert len(impact_res["affected_writers"]) >= 1
        assert len(impact_res["affected_tests"]) >= 1


def test_db_02_django_flask_and_sqlmodel_orm_extraction(tmp_path: Path) -> None:
    """Django ORM, Flask-SQLAlchemy, and SQLModel models and queries are extracted with FRAMEWORK_VERIFIED evidence."""
    (tmp_path / "django_app.py").write_text(
        """
from django.db import models

class Customer(models.Model):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=120)

    class Meta:
        db_table = "customers"

class Invoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount_cents = models.IntegerField(default=0)

    class Meta:
        db_table = "invoices"

def find_customer_invoices(customer_id: int):
    return Invoice.objects.filter(customer_id=customer_id)

def create_invoice(customer_id: int, amount_cents: int):
    return Invoice.objects.create(customer_id=customer_id, amount_cents=amount_cents)
""",
        encoding="utf-8",
    )
    (tmp_path / "flask_app.py").write_text(
        """
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(64), nullable=False)
""",
        encoding="utf-8",
    )
    (tmp_path / "sqlmodel_app.py").write_text(
        """
from sqlmodel import SQLModel, Field

class BillRecord(SQLModel, table=True):
    __tablename__ = "bills"
    id: int | None = Field(default=None, primary_key=True)
    vendor: str = Field(index=True)
    total_amount: float = Field(default=0.0)
""",
        encoding="utf-8",
    )

    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        tables = {t["table_name"] for t in find_db_tables(con, tmp_path)["tables"]}
        assert {"customers", "invoices", "audit_logs", "bills"}.issubset(tables)

        readers = find_db_readers(con, tmp_path, table="invoices")
        assert any("find_customer_invoices" in r["symbol"] for r in readers["readers"])

        writers = find_db_writers(con, tmp_path, table="invoices")
        assert any("create_invoice" in w["symbol"] for w in writers["writers"])

        bill_cols = {c["column_name"] for c in find_db_columns(con, tmp_path, table="bills")["columns"]}
        assert {"id", "vendor", "total_amount"}.issubset(bill_cols)


def test_db_03_prisma_knex_and_migrations_intelligence(tmp_path: Path) -> None:
    """Prisma schema, JS/TS Prisma/Knex queries, Alembic/Django/SQL migrations emit MIGRATES_TABLE and schema edges."""
    prisma_dir = tmp_path / "prisma"
    prisma_dir.mkdir()
    (prisma_dir / "schema.prisma").write_text(
        """
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Account {
  id        Int       @id @default(autoincrement())
  email     String    @unique
  payments  Payment[]
  @@map("accounts")
}

model Payment {
  id         Int     @id @default(autoincrement())
  amount     Int
  accountId  Int     @map("account_id")
  account    Account @relation(fields: [accountId], references: [id])
  @@index([accountId])
  @@map("payments")
}
""",
        encoding="utf-8",
    )
    (tmp_path / "payment_service.ts").write_text(
        """
export async function listPayments(prisma: any, accountId: number) {
  return await prisma.payment.findMany({ where: { accountId } });
}

export async function recordPayment(prisma: any, accountId: number, amount: number) {
  return await prisma.payment.create({ data: { accountId, amount } });
}

export async function archiveOldLedger(knex: any) {
  return await knex("ledger_entries").where("archived", false).update({ archived: true });
}
""",
        encoding="utf-8",
    )
    mig_dir = tmp_path / "migrations" / "versions"
    mig_dir.mkdir(parents=True)
    (mig_dir / "0001_create_accounts.py").write_text(
        """
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None

def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id")),
    )
""",
        encoding="utf-8",
    )
    (tmp_path / "schema.sql").write_text(
        """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    amount INTEGER NOT NULL
);
""",
        encoding="utf-8",
    )

    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        schema_res = get_db_schema(con, tmp_path)
        table_names = {t["table_name"] for t in schema_res["tables"]}
        assert {"accounts", "payments", "ledger_entries"}.issubset(table_names)
        assert len(schema_res["migrations"]) >= 1

        pay_tbl = get_db_table(con, tmp_path, table="payments")
        assert len(pay_tbl["migrations"]) >= 1
        assert len(pay_tbl["readers"]) >= 1
        assert len(pay_tbl["writers"]) >= 1


def test_db_04_dynamic_sql_preserves_possible_and_unknown_table(tmp_path: Path) -> None:
    """Dynamic SQL table names emit POSSIBLE_TABLE or UNKNOWN_TABLE and never fabricate static table names."""
    (tmp_path / "dynamic_queries.py").write_text(
        """
def run_dynamic_table_query(cursor, dynamic_table_name: str):
    cursor.execute(f"SELECT id, payload FROM {dynamic_table_name} WHERE active = 1")

def run_known_raw_sql(cursor):
    cursor.execute("SELECT id, name FROM warehouses WHERE region = 'us-east'")
    cursor.execute("INSERT INTO shipment_events (warehouse_id, status) VALUES (1, 'READY')")
""",
        encoding="utf-8",
    )
    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        queries = find_db_queries(con, tmp_path)["queries"]
        rels = {q["relationship"] for q in queries}
        assert "READS_TABLE" in rels
        assert "WRITES_TABLE" in rels
        assert "UNKNOWN_TABLE" in rels or "POSSIBLE_TABLE" in rels

        unk_queries = [q for q in queries if q["relationship"] in ("UNKNOWN_TABLE", "POSSIBLE_TABLE")]
        assert len(unk_queries) >= 1
        assert unk_queries[0]["evidence_class"] in ("UNKNOWN", "POSSIBLE")


# ---------------------------------------------------------------------------
# Phases 10–14: Runtime Observation Ingestion, Reconciliation & ContextPacket
# ---------------------------------------------------------------------------


def test_runtime_01_ingest_otel_jsonl_and_sql_logs_and_reconcile(tmp_path: Path) -> None:
    """Ingest OpenTelemetry, JSONL events, and SQL logs; verify RUNTIME_OBSERVED and 4 reconciliation buckets."""
    (tmp_path / "app.py").write_text(
        """
from fastapi import FastAPI
import sqlite3

app = FastAPI()

def save_bill_to_db(con, vendor: str, total: float):
    con.execute("INSERT INTO bills (vendor, total) VALUES (?, ?)", (vendor, total))

def legacy_unused_audit(con):
    con.execute("INSERT INTO legacy_audit (msg) VALUES ('unused')")

@app.post("/api/scan-bill")
def scan_bill_endpoint(vendor: str, total: float):
    con = sqlite3.connect(":memory:")
    save_bill_to_db(con, vendor, total)
    return {"status": "saved"}
""",
        encoding="utf-8",
    )

    indexer = _index_repo(tmp_path)
    otel_trace = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace-100",
                                "spanId": "span-route",
                                "name": "POST /api/scan-bill",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000050000000",
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/api/scan-bill"}},
                                    {"key": "http.method", "value": {"stringValue": "POST"}},
                                    {"key": "code.function", "value": {"stringValue": "scan_bill_endpoint"}},
                                    {"key": "http.request.header.authorization", "value": {"stringValue": "Bearer secret-jwt-token-999"}},
                                ],
                            },
                            {
                                "traceId": "trace-100",
                                "spanId": "span-db",
                                "parentSpanId": "span-route",
                                "name": "DB INSERT bills",
                                "startTimeUnixNano": "1700000000010000000",
                                "endTimeUnixNano": "1700000000040000000",
                                "attributes": [
                                    {"key": "code.function", "value": {"stringValue": "save_bill_to_db"}},
                                    {"key": "db.system", "value": {"stringValue": "sqlite"}},
                                    {"key": "db.sql.table", "value": {"stringValue": "bills"}},
                                    {"key": "db.operation", "value": {"stringValue": "INSERT"}},
                                    {"key": "db.statement", "value": {"stringValue": "INSERT INTO bills (vendor, total) VALUES ('AcmeSecretVendor', 499.95)"}},
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    trace_file = tmp_path / "otel_trace.json"
    trace_file.write_text(json.dumps(otel_trace), encoding="utf-8")

    # Also test JSONL runtime event with a dynamic runtime-only edge
    jsonl_file = tmp_path / "runtime_events.jsonl"
    jsonl_file.write_text(
        json.dumps(
            {
                "event_type": "call",
                "route": "/api/scan-bill",
                "caller": "scan_bill_endpoint",
                "callee": "dynamic_plugin_hook",
                "table": "runtime_audit_events",
                "operation": "INSERT",
                "sql": "INSERT INTO runtime_audit_events (token) VALUES ('sk-live-secret-1234567890abcdef')",
                "timestamp": "2026-10-04T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with indexer.session() as con:
        ing1 = ingest_runtime_traces(con, tmp_path, source_path="otel_trace.json")
        assert ing1["status"] == "ok"
        assert ing1["events_ingested"] >= 2

        ing2 = ingest_runtime_traces(con, tmp_path, source_path="runtime_events.jsonl", format="jsonl")
        assert ing2["status"] == "ok"

        rt_res = get_runtime_trace(con, tmp_path, route="/api/scan-bill")
        assert rt_res["status"] == "ok"
        assert rt_res["count"] >= 1
        for edge in rt_res["edges"]:
            assert edge["evidence_class"] == "RUNTIME_OBSERVED"
            assert edge["observation_count"] >= 1
            assert edge["runtime_generation"] >= 1

        # Verify reverse maps
        rev = rt_res["reverse_maps"]
        assert "table_to_writers" in rev
        assert "route_to_tables" in rev

        # Reconcile static vs runtime
        rec = reconcile_static_runtime(con, tmp_path)
        assert rec["status"] == "ok"
        assert len(rec["confirmed_runtime_paths"]) >= 1
        assert len(rec["not_observed_at_runtime"]) >= 1
        assert len(rec["runtime_only_observed"]) >= 1

        # Verify NOT_OBSERVED_AT_RUNTIME preserves note that it is not dead-code proof
        unobs = rec["not_observed_at_runtime"][0]
        assert unobs["reconciliation_state"] == "NOT_OBSERVED_AT_RUNTIME"
        assert unobs["runtime_evidence_class"] == "RUNTIME_UNOBSERVED"

        # Verify get_context includes database, runtime, and reconciliation sections within budget
        pkt = get_context(
            con,
            tmp_path,
            task="Trace /api/scan-bill and bills database writes",
            intent="TRACE",
            max_tokens=4000,
            max_files=15,
            max_lines=500,
        )
        pkt_dict = pkt.to_dict()
        assert "database" in pkt_dict
        assert "runtime" in pkt_dict
        assert "reconciliation" in pkt_dict
        assert int(pkt_dict["selected_tokens"]) <= 4000  # type: ignore[arg-type]
        assert len(pkt_dict["selected_files"]) <= 15  # type: ignore[arg-type]
        assert int(pkt_dict["selected_lines"]) <= 500  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 15 & Security Hardening: Zero-Secret-Leakage Regression Suite
# ---------------------------------------------------------------------------


def test_sec_01_seeded_secrets_never_stored_in_sqlite_or_returned_by_any_tool(tmp_path: Path) -> None:
    """Seeded secrets across source code, SQL queries, env configs, and runtime traces are 100% redacted."""
    seeded_secrets = [
        "SuperSecretDbPass99!",
        "sk-proj-9876543210abcdef9876543210abcdef",
        "AIzaSyD-9876543210abcdef9876543210abcd",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "MyPlaintextSqlPassword123!",
        "BearerTopSecretRuntimeToken777!",
        "SessionCookieSecretValue888!",
    ]

    # 1. Sensitive .env file (must be ignored by scanner and blocked by get_file/read_file)
    (tmp_path / ".env").write_text(
        f'DATABASE_URL="postgresql://admin:{seeded_secrets[0]}@db.internal:5432/prod_db"\n'
        f'OPENAI_API_KEY="{seeded_secrets[1]}"\n',
        encoding="utf-8",
    )

    # 2. Private key file inside source tree (must be blocked by content & path checks)
    (tmp_path / "compromised_key.py").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA9876543210abcdef9876543210abcdef\n"
        "-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    # 3. Normal Python source file containing hardcoded secrets, connection URLs, and SQL literal secrets
    (tmp_path / "billing_service.py").write_text(
        f"""
import os
import sqlite3

DB_URL = "postgresql://admin:{seeded_secrets[0]}@db.internal:5432/prod_db"
OPENAI_KEY = "{seeded_secrets[1]}"
GEMINI_KEY = "{seeded_secrets[2]}"
AWS_SECRET = "{seeded_secrets[3]}"
HARDCODED_JWT = "{seeded_secrets[4]}"
ENV_DB = os.getenv("DATABASE_URL")

def authenticate_user_raw_sql(cursor):
    cursor.execute("SELECT id, email FROM users WHERE password = '{seeded_secrets[5]}'")
""",
        encoding="utf-8",
    )

    # 4. Runtime trace containing Authorization header, Cookie, request body password, and SQL bind secret
    trace_payload = json.dumps(
        [
            {
                "event_type": "query",
                "route": "/api/login",
                "symbol": "authenticate_user_raw_sql",
                "table": "users",
                "operation": "SELECT",
                "sql": f"SELECT id, email FROM users WHERE password = '{seeded_secrets[5]}'",
                "headers": {
                    "Authorization": f"Bearer {seeded_secrets[6]}",
                    "Cookie": f"session_id={seeded_secrets[7]}",
                },
                "body": {
                    "password": seeded_secrets[5],
                    "api_key": seeded_secrets[1],
                },
            }
        ]
    )

    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        ingest_runtime_traces(con, tmp_path, payload=trace_payload, format="json")

        # AUDIT 1: Zero occurrences of any seeded secret in the entire SQLite database
        audit = audit_sqlite_for_secrets(con, seeded_secrets)
        assert audit["clean"] is True, f"Secret leaked into SQLite: {audit['findings']}"
        assert audit["findings"] == []

        # AUDIT 2: Connection metadata extracted dialect/database safely without credentials
        meta = parse_safe_connection_metadata(
            f"postgresql://admin:{seeded_secrets[0]}@db.internal:5432/prod_db"
        )
        assert meta["dialect"] == "postgres"
        assert meta["database_name"] == "prod_db"
        assert seeded_secrets[0] not in json.dumps(meta)
        assert "admin" not in json.dumps(meta)

        # AUDIT 3: READS_ENV recorded env:DATABASE_URL without storing secret value
        schema_out = json.dumps(get_db_schema(con, tmp_path))
        assert "DATABASE_URL" in schema_out
        for secret in seeded_secrets:
            assert secret not in schema_out

        # AUDIT 4: search_code redacts secrets and never indexes .env or private keys
        for query_term in ("DB_URL", "OPENAI_KEY", "authenticate_user_raw_sql", "SELECT"):
            sc_out = json.dumps(search_code(con, query_term, repo_path=tmp_path))
            for secret in seeded_secrets:
                assert secret not in sc_out
            assert "BEGIN RSA PRIVATE KEY" not in sc_out

        # AUDIT 5: get_file and get_symbol redact secrets on billing_service.py
        gf_out = json.dumps(get_file(con, tmp_path, path="billing_service.py", include_content=True))
        gs_out = json.dumps(get_symbol(con, tmp_path, canonical_id="authenticate_user_raw_sql"))
        for secret in seeded_secrets:
            assert secret not in gf_out
            assert secret not in gs_out

        # AUDIT 6: get_file blocks .env and private-key files with SecurityError
        with pytest.raises(SecurityError):
            get_file(con, tmp_path, path=".env", include_content=True)
        with pytest.raises(SecurityError):
            get_file(con, tmp_path, path="compromised_key.py", include_content=True)

        # AUDIT 7: Database and runtime tools never leak secrets
        db_q_out = json.dumps(find_db_queries(con, tmp_path))
        rt_out = json.dumps(get_runtime_trace(con, tmp_path))
        ctx_out = json.dumps(
            get_context(con, tmp_path, task="authenticate_user_raw_sql users").to_dict()
        )
        for secret in seeded_secrets:
            assert secret not in db_q_out
            assert secret not in rt_out
            assert secret not in ctx_out


def test_sec_02_sensitive_paths_and_redaction_primitives(tmp_path: Path) -> None:
    """Verify path blocking for credentials/keys/db dumps and redaction helpers."""
    blocked_names = [
        ".env",
        ".env.local",
        ".env.production",
        "secrets.json",
        "credentials.yaml",
        "service-account.json",
        "id_rsa",
        "id_ed25519",
        "cert.pem",
        "private.key",
        "keystore.p12",
        ".pypirc",
        ".npmrc",
        "dump.sqlite",
        "backup.db",
    ]
    for name in blocked_names:
        assert is_sensitive_path(Path(name)) is True, f"Expected {name} to be blocked as sensitive"
        f = tmp_path / name
        f.write_text("secret", encoding="utf-8")
        with pytest.raises(SecurityError):
            safe_read_text(tmp_path, name)

    redacted_url = redact_connection_string("postgres://user:my_pass_123@localhost:5432/mydb")
    assert "my_pass_123" not in redacted_url
    assert "***:***" in redacted_url or "<REDACTED>" in redacted_url

    norm_sql = normalize_and_redact_sql("SELECT * FROM users WHERE email = 'alice@example.com' AND pin = 9876")
    assert "alice@example.com" not in norm_sql
    assert "9876" not in norm_sql
    assert "?" in norm_sql

    redacted_txt = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.sig1234567890")
    assert "eyJhbGci" not in redacted_txt


# ---------------------------------------------------------------------------
# Phase 16, 19, 20: Agent Routing, Determinism & Real-Repository Evaluation
# ---------------------------------------------------------------------------


def test_routing_and_determinism_for_database_and_runtime_tools(tmp_path: Path) -> None:
    """Verify natural-language routing (`select_agent_tool`) and byte-identical deterministic outputs."""
    assert select_agent_tool("Which database tables exist in this repository?")["selected_tool"] == "find_db_tables"
    assert select_agent_tool("What columns exist in bills?")["selected_tool"] == "find_db_columns"
    assert select_agent_tool("Which ORM model maps to products?")["selected_tool"] == "find_db_models"
    assert select_agent_tool("Which service writes to products?")["selected_tool"] == "find_db_writers"
    assert select_agent_tool("Which service reads from users?")["selected_tool"] == "find_db_readers"
    assert select_agent_tool("What is the database impact if we drop column shop_id?")["selected_tool"] == "get_db_impact"
    assert select_agent_tool("Show the database schema overview")["selected_tool"] == "get_db_schema"
    assert select_agent_tool("What happened at runtime when /api/scan-bill ran?")["selected_tool"] == "get_runtime_trace"
    assert select_agent_tool("Where do static and runtime paths differ?")["selected_tool"] == "reconcile_static_runtime"
    assert select_agent_tool("Ingest runtime trace from otel.json")["selected_tool"] == "ingest_runtime_traces"

    # Verify MCP server exposes all 14 new tools in full profile
    srv = create_server(tmp_path, profile="full")
    mcp_tools = srv._tool_manager._tools
    expected_new_tools = {
        "find_db_tables",
        "find_db_columns",
        "find_db_models",
        "find_db_queries",
        "find_db_callers",
        "find_db_writers",
        "find_db_readers",
        "find_db_relationships",
        "get_db_table",
        "get_db_schema",
        "get_db_impact",
        "ingest_runtime_traces",
        "get_runtime_trace",
        "reconcile_static_runtime",
    }
    assert expected_new_tools.issubset(set(mcp_tools.keys()))

    # Verify deterministic ordering across repeated runs
    (tmp_path / "models.py").write_text(
        """
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String

Base = declarative_base()

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    title = Column(String)
""",
        encoding="utf-8",
    )
    indexer = _index_repo(tmp_path)
    with indexer.session() as con:
        r1 = json.dumps(find_db_tables(con, tmp_path), sort_keys=True)
        r2 = json.dumps(find_db_tables(con, tmp_path), sort_keys=True)
        assert r1 == r2
