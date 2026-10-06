"""Integration tests for Mongoose & MongoDB Document Persistence (Pillar 4 / Database).

Validates:
- Mongoose Schema & Model AST extraction
- Collections, fields, and ref foreign keys
- Document query operations (Model.find, Model.create)
- find_db_writers and find_db_readers integration
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.database import find_db_readers, find_db_tables, find_db_writers, get_db_table
from codegraph.indexing.indexer import Indexer


def test_mongoose_schema_and_queries():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Mongoose model & schema file
        (src / "invoice.model.ts").write_text("""
import mongoose, { Schema } from 'mongoose';

const invoiceSchema = new mongoose.Schema({
  amount: { type: Number, required: true },
  status: { type: String, default: 'pending' },
  user: { type: Schema.Types.ObjectId, ref: 'User' },
});

export const Invoice = mongoose.model('Invoice', invoiceSchema);
""")

        # 2. Service performing read and write queries
        (src / "invoice.service.ts").write_text("""
import { Invoice } from './invoice.model';

export class InvoiceService {
  async createInvoice(data: any) {
    return await Invoice.create(data);
  }

  async listInvoices() {
    return await Invoice.find({ status: 'pending' });
  }
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # 1. Collection check via find_db_tables
            tbl_res = find_db_tables(con, repo)
            tbl_names = {t["table_name"] for t in tbl_res["tables"]}
            assert "invoices" in tbl_names

            # 2. Columns/fields check via get_db_table
            inv_table = get_db_table(con, repo, table="invoices")
            inv_col_names = {c["column_name"] for c in inv_table["columns"]}
            assert "amount" in inv_col_names
            assert "status" in inv_col_names
            assert "user" in inv_col_names

            # 3. Mongoose query writers check via find_db_writers
            inv_writers = find_db_writers(con, repo, table="invoices")
            writer_callers = {w.get("source") or w.get("symbol") for w in inv_writers["writers"]}
            assert any("createInvoice" in str(c) for c in writer_callers if c)

            # 4. Mongoose query readers check via find_db_readers
            inv_readers = find_db_readers(con, repo, table="invoices")
            reader_callers = {r.get("source") or r.get("symbol") for r in inv_readers["readers"]}
            assert any("listInvoices" in str(c) for c in reader_callers if c)


def test_dynamic_mongoose_schema_with_type_annotations():
    """Verify that dynamic object references and TypeScript type annotations are extracted accurately."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        (src / "order.model.ts").write_text("""
import mongoose, { Schema, Model } from 'mongoose';

const complexConfig: Record<string, any> = {
    amount: { type: Number, required: true },
    ownerId: { type: Schema.Types.ObjectId, ref: 'User' },
    note: { type: String }
};

const OrderSchema: Schema = new mongoose.Schema(complexConfig, { timestamps: true });

export const Order: Model<any> = mongoose.model('Order', OrderSchema);
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            tbl_res = find_db_tables(con, repo)
            tbl_names = {t["table_name"] for t in tbl_res["tables"]}
            assert "orders" in tbl_names

            ord_table = get_db_table(con, repo, table="orders")
            ord_col_names = {c["column_name"] for c in ord_table["columns"]}
            assert "amount" in ord_col_names
            assert "ownerId" in ord_col_names
            assert "note" in ord_col_names
