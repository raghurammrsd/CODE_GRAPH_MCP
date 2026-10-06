"""Comprehensive Tests for HTML Templates, Robust Mongoose/Drizzle Extraction, and Vite Aliases."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.database.extractor import extract_database_from_file
from codegraph.indexing import Indexer
from codegraph.indexing.parser import parse
from codegraph.indexing.templates import parse_html_template
from codegraph.tsconfig import TsConfigResolver

runner = CliRunner()


def test_html_template_parsing_and_event_handlers() -> None:
    html_content = """{% extends "base.html" %}
{% block content %}
<div id="cart-drawer" class="drawer">
  <button id="toggle-btn" onclick="quickToggleStock(42)">Toggle Stock</button>
  <button @click="showToast('saved')">Save</button>
  <button id="delete-btn" onclick="handleDelete">Delete</button>
  <button id="checkout-btn" @click="Cart.checkout">Checkout</button>
  <form action="/user/api/cart/checkout" method="POST">
    <input type="text" name="coupon" />
  </form>
</div>
<script>
  function inlineHelper() {
    return 100;
  }
</script>
{% endblock %}
"""
    res = parse_html_template(html_content, "templates/stock.html")
    assert res.parse_failed is False
    assert res.language == "html"

    # Symbols include DOM elements, template blocks, event handlers, and inline scripts
    sym_names = {s.name for s in res.symbols}
    assert "cart-drawer" in sym_names
    assert "toggle-btn" in sym_names
    assert "delete-btn" in sym_names
    assert "checkout-btn" in sym_names
    assert "content" in sym_names  # Jinja block
    assert "quickToggleStock" in sym_names  # event handler
    assert "handleDelete" in sym_names  # bare event handler
    assert "checkout" in sym_names  # qualified method event handler
    assert "inlineHelper" in sym_names  # inline script function

    # Calls include quickToggleStock, showToast, handleDelete, checkout
    call_callees = {c.callee for c in res.calls}
    assert "quickToggleStock" in call_callees
    assert "showToast" in call_callees
    assert "handleDelete" in call_callees
    assert "checkout" in call_callees

    # Form action in bindings
    form_bindings = [b for b in res.bindings if b.expr_kind == "HTML_FORM_ACTION"]
    assert len(form_bindings) == 1
    assert form_bindings[0].target_name == "/user/api/cart/checkout"
    assert form_bindings[0].base_expr == "POST"

    # Template inheritance
    assert len(res.inheritance) == 1
    assert res.inheritance[0].base_name == "base.html"


def test_html_parser_integration_via_parse() -> None:
    html_content = '<div id="app"><button onclick="initApp()"></button></div>'
    res = parse(html_content, "html", "index.html")
    assert res.language == "html"
    assert any(s.name == "app" for s in res.symbols)
    assert any(c.callee == "initApp" for c in res.calls)


def test_mongoose_dynamic_object_schema_extraction() -> None:
    js_content = """
const complexConfig = {
    amount: { 
        type: Number, 
        required: true 
    },
    ownerId: { 
        type: mongoose.Schema.Types.ObjectId, 
        ref: 'User' 
    },
    status: String,
};

const InvoiceSchema = new mongoose.Schema(complexConfig);
const Invoice = mongoose.model('Invoice', InvoiceSchema);
"""
    from codegraph.database.models import DatabaseEntityKind

    db_res = extract_database_from_file(js_content, "models/invoice.js", language="javascript")
    tables = [e for e in db_res.entities if e.kind in (DatabaseEntityKind.TABLE, DatabaseEntityKind.TABLE.value)]
    models = [e for e in db_res.entities if e.kind in (DatabaseEntityKind.ORM_MODEL, DatabaseEntityKind.ORM_MODEL.value)]
    columns = [e for e in db_res.entities if e.kind in (DatabaseEntityKind.COLUMN, DatabaseEntityKind.COLUMN.value)]

    assert any(t.table_name == "invoices" for t in tables)
    assert any(m.name == "Invoice" for m in models)

    col_names = {c.column_name for c in columns}
    assert "amount" in col_names
    assert "ownerId" in col_names or "ownerid" in col_names
    assert "status" in col_names

    # Foreign key relationship to users table from ref: 'User'
    owner_col = next(c for c in columns if c.column_name in ("ownerId", "ownerid"))
    assert owner_col.is_foreign_key is True
    assert owner_col.target_table == "users"


def test_drizzle_multiline_chained_methods_extraction() -> None:
    from codegraph.database.models import DatabaseEntityKind

    ts_content = """
export const users = pgTable('users', {
  id: serial('id')
    .primaryKey(),
  name: text('name')
    .notNull(),
  email: varchar('email', { length: 256 })
    .notNull()
    .unique(),
  roleId: integer('role_id')
    .references(() => roles.id),
});
"""
    db_res = extract_database_from_file(ts_content, "schema.ts", language="typescript")
    tables = [e for e in db_res.entities if e.kind in (DatabaseEntityKind.TABLE, DatabaseEntityKind.TABLE.value)]
    columns = [e for e in db_res.entities if e.kind in (DatabaseEntityKind.COLUMN, DatabaseEntityKind.COLUMN.value)]

    assert any(t.table_name == "users" for t in tables)
    col_dict = {c.column_name: c for c in columns}

    assert "id" in col_dict
    assert col_dict["id"].is_primary_key is True

    assert "name" in col_dict
    assert col_dict["name"].nullable is False

    assert "email" in col_dict
    assert col_dict["email"].is_unique is True
    assert col_dict["email"].nullable is False

    assert "role_id" in col_dict
    assert col_dict["role_id"].is_foreign_key is True
    assert col_dict["role_id"].target_table == "roles"


def test_vite_config_alias_resolution(tmp_path: Path) -> None:
    vite_config = """
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
"""
    (tmp_path / "vite.config.ts").write_text(vite_config)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Button.tsx").write_text("export const Button = () => null;")

    resolver = TsConfigResolver.load_from_repo(tmp_path)
    known_files = {"src/Button.tsx"}

    resolved = resolver.resolve_alias("@/Button", "src/App.tsx", known_files)
    assert resolved == "src/Button.tsx"


def test_cli_search_ext_and_package_options(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def find_me_python(): pass")
    (tmp_path / "src" / "component.tsx").write_text("export const find_me_react = () => null;")

    indexer = Indexer(tmp_path)
    indexer.index()

    # Search with --ext tsx: should return only component.tsx
    res = runner.invoke(app, ["search", "find_me", "-r", str(tmp_path), "--ext", "tsx", "--json"])
    assert res.exit_code == 0
    hits = json.loads(res.stdout)
    assert len(hits) == 1
    assert "component.tsx" in hits[0]["file"]
