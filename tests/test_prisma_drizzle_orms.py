"""Tests for Subsystem 3C: Node.js Database ORMs (Prisma & Drizzle).

Verifies:
- Prisma schema parsing: models, columns, data types, primary keys, foreign keys, @map attributes.
- Prisma query call-site tracking: prisma.<model>.create (WRITES_TABLE) and findMany (READS_TABLE).
- Drizzle ORM schema parsing: pgTable declarations, columns, data types, primary keys, notNull, references.
- Drizzle query call-site tracking: db.select().from(), db.insert(), and db.query.<model>.findMany().
- Database interrogation tools: find_db_tables, get_db_table, find_db_writers, find_db_readers.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.database import (
    extract_database_from_file,
    find_db_readers,
    find_db_tables,
    find_db_writers,
    get_db_table,
)
from codegraph.indexing.indexer import Indexer


def test_prisma_schema_extraction_unit():
    schema_prisma = """
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Invoice {
  id        String   @id @default(uuid())
  number    String   @unique @map("invoice_number")
  amount    Float
  status    String   @default("DRAFT")
  userId    String   @map("user_id")
  user      User     @relation(fields: [userId], references: [id])
  createdAt DateTime @default(now()) @map("created_at")

  @@map("invoices")
}

model User {
  id       String    @id
  email    String    @unique
  invoices Invoice[]

  @@map("users")
}
"""
    res = extract_database_from_file(
        schema_prisma,
        "prisma/schema.prisma",
        language="prisma",
    )

    # Tables
    tbl_names = {e.table_name for e in res.entities if e.kind == "Table"}
    assert tbl_names == {"invoices", "users"}

    # Columns for invoices
    inv_cols = {e.column_name: e for e in res.entities if e.kind == "Column" and e.table_name == "invoices"}
    assert "id" in inv_cols
    assert inv_cols["id"].is_primary_key
    assert "invoice_number" in inv_cols
    assert inv_cols["invoice_number"].is_unique
    assert "user_id" in inv_cols
    assert inv_cols["user_id"].is_foreign_key
    assert "amount" in inv_cols
    assert "status" in inv_cols
    assert "created_at" in inv_cols

    # MAPS_TO_COLUMN edges
    col_edges = [e for e in res.edges if e.relationship == "MAPS_TO_COLUMN"]
    assert len(col_edges) >= 8


def test_drizzle_schema_extraction_unit():
    drizzle_schema = """
import { pgTable, serial, text, numeric, integer, timestamp } from 'drizzle-orm/pg-core';

export const invoices = pgTable('invoices', {
  id: serial('id').primaryKey(),
  invoiceNumber: text('invoice_number').notNull().unique(),
  amount: numeric('amount').notNull(),
  userId: integer('user_id').references(() => users.id),
  createdAt: timestamp('created_at').defaultNow(),
});

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull().unique(),
});
"""
    res = extract_database_from_file(
        drizzle_schema,
        "src/db/schema.ts",
        language="typescript",
    )

    # Tables
    tbl_names = {e.table_name for e in res.entities if e.kind == "Table"}
    assert tbl_names == {"invoices", "users"}

    # Columns
    inv_cols = {e.column_name: e for e in res.entities if e.kind == "Column" and e.table_name == "invoices"}
    assert "id" in inv_cols
    assert inv_cols["id"].is_primary_key
    assert "invoice_number" in inv_cols
    assert inv_cols["invoice_number"].is_unique
    assert not inv_cols["invoice_number"].nullable
    assert "user_id" in inv_cols
    assert inv_cols["user_id"].is_foreign_key
    assert "amount" in inv_cols
    assert not inv_cols["amount"].nullable


def test_prisma_drizzle_indexer_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # 1. Prisma schema
        prisma_dir = repo / "prisma"
        prisma_dir.mkdir(parents=True, exist_ok=True)
        (prisma_dir / "schema.prisma").write_text("""
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Invoice {
  id        String   @id @default(uuid())
  amount    Float
  userId    String   @map("user_id")

  @@map("invoices")
}
""")

        # 2. Service using Prisma
        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "invoice.service.ts").write_text("""
export class InvoiceService {
  async createInvoice(data: any) {
    return await prisma.invoice.create({ data });
  }

  async listInvoices() {
    return await prisma.invoice.findMany();
  }
}
""")

        # 3. Drizzle schema and queries
        (src_dir / "drizzle_schema.ts").write_text("""
import { pgTable, serial, text } from 'drizzle-orm/pg-core';

export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  status: text('status').notNull(),
});
""")

        (src_dir / "order.service.ts").write_text("""
import { db } from './db';
import { orders } from './drizzle_schema';

export async function insertOrder(status: string) {
  return await db.insert(orders).values({ status });
}

export async function queryOrders() {
  return await db.select().from(orders);
}

export async function relationalFindOrders() {
  return await db.query.orders.findMany();
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # 1. Tables check via find_db_tables
            tbl_res = find_db_tables(con, repo)
            tbl_names = {t["table_name"] for t in tbl_res["tables"]}
            assert "invoices" in tbl_names
            assert "orders" in tbl_names

            # 2. Columns check via get_db_table
            inv_table = get_db_table(con, repo, table="invoices")
            inv_col_names = {c["column_name"] for c in inv_table["columns"]}
            assert "id" in inv_col_names
            assert "amount" in inv_col_names
            assert "user_id" in inv_col_names

            # 3. Prisma query checks: find_db_writers and find_db_readers
            inv_writers = find_db_writers(con, repo, table="invoices")
            writer_callers = {w.get("source") or w.get("symbol") or w.get("caller_symbol_id") for w in inv_writers["writers"]}
            assert any("createInvoice" in c for c in writer_callers if c)

            inv_readers = find_db_readers(con, repo, table="invoices")
            reader_callers = {r.get("source") or r.get("symbol") or r.get("caller_symbol_id") for r in inv_readers["readers"]}
            assert any("listInvoices" in c for c in reader_callers if c)

            # 4. Drizzle query checks: find_db_writers and find_db_readers
            order_writers = find_db_writers(con, repo, table="orders")
            order_writer_callers = {w.get("source") or w.get("symbol") or w.get("caller_symbol_id") for w in order_writers["writers"]}
            assert any("insertOrder" in c for c in order_writer_callers if c)

            order_readers = find_db_readers(con, repo, table="orders")
            order_reader_callers = {r.get("source") or r.get("symbol") or r.get("caller_symbol_id") for r in order_readers["readers"]}
            assert any("queryOrders" in c or "relationalFindOrders" in c for c in order_reader_callers if c)
