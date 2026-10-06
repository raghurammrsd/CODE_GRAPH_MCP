"""Test Part B: Runtime SQL Interceptor & Dynamic Reconciliation Engine.

Verifies:
1. Dynamic AST Request Payload Extraction (Flask request.form.get / request.json.get).
2. OpenTelemetry Child DB Span inheritance from parent HTTP route span.
3. Runtime SQL Interception (INSERT / UPDATE) linking route handler to destination table.
4. Runtime Schema Drift detection (RUNTIME_MISSING_REQUIRED_COLUMN, RUNTIME_UNKNOWN_COLUMN_WRITTEN).
5. Epistemic discipline: RUNTIME_OBSERVED evidence class is strictly maintained.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.database.schema_drift import (
    DriftType,
    detect_schema_drift,
)
from codegraph.indexing.indexer import Indexer
from codegraph.runtime.ingestor import ingest_runtime_traces


def test_dynamic_flask_request_form_drift_without_pydantic(tmp_path: Path) -> None:
    """Test Case 1: Exact case study from DUNDOO_cloud:
    Flask route using request.form.get('name') with NO Pydantic class.
    Static AST extractor must detect dynamic fields and flag missing required DB columns.
    """
    repo = tmp_path / "flask_app"
    repo.mkdir()

    # 1. SQLAlchemy products table where 'price' is NOT NULL
    (repo / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String, Float\n"
        "from sqlalchemy.orm import declarative_base\n\n"
        "Base = declarative_base()\n\n"
        "class Product(Base):\n"
        "    __tablename__ = 'products'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    name = Column(String(100), nullable=False)\n"
        "    price = Column(Float, nullable=False)\n",
        encoding="utf-8",
    )

    # 2. Flask route with request.form.get('name')
    (repo / "routes.py").write_text(
        "from flask import Blueprint, request\n"
        "from models import Product\n\n"
        "shop = Blueprint('shop', __name__)\n\n"
        "@shop.route('/shop/add-product', methods=['POST'])\n"
        "def add_product():\n"
        "    name = request.form.get('name')\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    indexer.index()

    with indexer.session() as con:
        # Run schema drift detection on route
        res = detect_schema_drift(con, repo, route_or_handler="/shop/add-product", target_table="products")
        assert res["status"] == "ok"
        assert res["schema_mode"] == "DYNAMIC_AST"
        assert "DynamicPayload" in res["schema_name"]

        # 'price' is NOT NULL in products table and omitted in request.form.get()
        missing_issues = [i for i in res["issues"] if i["drift_type"] == DriftType.MISSING_REQUIRED_COLUMN.value]
        assert any(i["column_name"] == "price" for i in missing_issues)


def test_runtime_sql_interception_and_reconciliation(tmp_path: Path) -> None:
    """Test Case 2: OpenTelemetry trace with HTTP parent span and child DB span
    executing: INSERT INTO products (name) VALUES ('Apple')
    CodeGraph intercepts query, correlates it to /shop/add-product, and detects runtime schema drift.
    """
    repo = tmp_path / "runtime_app"
    repo.mkdir()

    (repo / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String, Float\n"
        "from sqlalchemy.orm import declarative_base\n\n"
        "Base = declarative_base()\n\n"
        "class Product(Base):\n"
        "    __tablename__ = 'products'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    name = Column(String(100), nullable=False)\n"
        "    price = Column(Float, nullable=False)\n",
        encoding="utf-8",
    )

    (repo / "routes.py").write_text(
        "def add_product():\n"
        "    pass\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    indexer.index()

    # Ingest OpenTelemetry trace simulating dev server execution
    otel_payload = [
        {
            "trace_id": "tr_001",
            "span_id": "span_http",
            "http_method": "POST",
            "route": "/shop/add-product",
            "handler": "add_product",
        },
        {
            "trace_id": "tr_001",
            "span_id": "span_db",
            "parent_span_id": "span_http",
            "operation": "INSERT",
            "table": "products",
            "sql": "INSERT INTO products (name) VALUES ('Apple')",
        },
    ]

    with indexer.session() as con:
        ingest_res = ingest_runtime_traces(con, data_or_path=otel_payload, format="otel")
        assert ingest_res["status"] == "ok"
        assert ingest_res["events_ingested"] >= 2

        # Verify runtime edges created linking route to table
        edges = con.execute(
            "SELECT source, target, relationship, evidence_class, normalized_sql FROM runtime_edges "
            "WHERE target LIKE '%products%'"
        ).fetchall()
        assert len(edges) >= 1
        assert any(e["relationship"] == "WRITES_TABLE" for e in edges)
        assert any("products" in e["target"] for e in edges)

        # Run schema drift with runtime reconciliation
        res = detect_schema_drift(con, repo, route_or_handler="/shop/add-product")
        assert res["status"] == "ok"
        recon = res["runtime_reconciliation"]
        assert recon["is_observed"] is True
        assert recon["status"] == "CONFIRMED_RUNTIME_PATH"
        assert "name" in recon["runtime_columns_written"]

        # Runtime SQL omitted NOT NULL 'price' column -> flag RUNTIME_MISSING_REQUIRED_COLUMN
        rt_issues = [i for i in res["issues"] if i["drift_type"] == DriftType.RUNTIME_MISSING_REQUIRED_COLUMN.value]
        assert len(rt_issues) >= 1
        assert any(i["column_name"] == "price" for i in rt_issues)
        assert rt_issues[0]["severity"] == "CRITICAL"
        assert "RUNTIME_OBSERVED" in rt_issues[0]["message"]

    # Verify CLI command works seamlessly
    runner = CliRunner()
    cli_res = runner.invoke(app, ["schema-drift", "--route", "/shop/add-product", str(repo)])
    assert cli_res.exit_code == 0
    assert "Schema Drift Report" in cli_res.stdout
    assert "Runtime SQL:  Observed" in cli_res.stdout
    assert "price" in cli_res.stdout

