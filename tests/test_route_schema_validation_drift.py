"""Acceptance tests for Layer 2: Route Input Schema vs Database Column Drift Detection.

Verifies:
1. MISSING_REQUIRED_COLUMN: DB column is NOT NULL with no default, but route schema lacks the field.
2. NULLABILITY_MISMATCH: Route schema allows None/Optional, but DB column rejects NULL.
3. TYPE_INCOMPATIBILITY: Route schema type conflicts with DB column type (e.g., int vs TEXT/VARCHAR).
4. LENGTH_CONSTRAINT_DRIFT: Route schema allows max_length > DB column length constraint.
5. UNUSED_SCHEMA_FIELD: Route schema accepts a field not present in destination table.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.database.schema_drift import (
    DriftSeverity,
    DriftType,
    detect_schema_drift,
)
from codegraph.indexing.indexer import Indexer

runner = CliRunner()


def test_route_schema_validation_drift_acceptance():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        app_dir = repo / "app"
        app_dir.mkdir(parents=True, exist_ok=True)

        # 1. Database model: SQLAlchemy orders table
        (app_dir / "models.py").write_text("""
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    total_cents = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    coupon_code = Column(String(10), nullable=True)
    notes = Column(Text, nullable=True)
""", encoding="utf-8")

        # 2. Pydantic schemas: CheckoutRequest with intentional drift
        (app_dir / "schemas.py").write_text("""
from pydantic import BaseModel, Field
from typing import Optional

class CheckoutRequest(BaseModel):
    # Drift 1: total_cents is nullable in schema, but NOT NULL in DB (NULLABILITY_MISMATCH)
    total_cents: Optional[int] = None

    # Drift 2: coupon_code max_length=50 in schema, but VARCHAR(10) in DB (LENGTH_CONSTRAINT_DRIFT)
    coupon_code: Optional[str] = Field(None, max_length=50)

    # Drift 3: notes is int in schema, but TEXT in DB (TYPE_INCOMPATIBILITY)
    notes: Optional[int] = None

    # Drift 4: referral_source not in orders table (UNUSED_SCHEMA_FIELD)
    referral_source: str = "web"

    # Drift 5: user_id is NOT NULL in DB, but MISSING entirely from CheckoutRequest (MISSING_REQUIRED_COLUMN)
""", encoding="utf-8")

        # 3. Route handler: FastAPI checkout endpoint
        (app_dir / "api.py").write_text("""
from fastapi import APIRouter
from app.models import Order
from app.schemas import CheckoutRequest

router = APIRouter()

@router.post("/api/v1/orders/checkout")
def checkout(payload: CheckoutRequest, session=None):
    cursor = session.connection()
    cursor.execute(
        "INSERT INTO orders (user_id, total_cents) VALUES (:user_id, :total_cents)",
        {"user_id": 1, "total_cents": payload.total_cents},
    )
    return {"status": "ok"}
""", encoding="utf-8")

        # Index the repository
        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            res = detect_schema_drift(
                con,
                repo,
                route_or_handler="/api/v1/orders/checkout",
                target_table="orders",
                schema_name="CheckoutRequest",
            )

            assert res["status"] == "ok"
            assert res["target_table"] == "orders"
            assert res["schema_name"] == "CheckoutRequest"
            assert res["drift_count"] == 5
            assert res["critical_count"] == 3
            assert res["warning_count"] == 1
            assert res["info_count"] == 1

            issues_by_type = {i["drift_type"]: i for i in res["issues"]}

            # 1. MISSING_REQUIRED_COLUMN: user_id
            assert DriftType.MISSING_REQUIRED_COLUMN.value in issues_by_type
            miss_iss = issues_by_type[DriftType.MISSING_REQUIRED_COLUMN.value]
            assert miss_iss["field_name"] == "user_id"
            assert miss_iss["severity"] == DriftSeverity.CRITICAL.value

            # 2. NULLABILITY_MISMATCH: total_cents
            assert DriftType.NULLABILITY_MISMATCH.value in issues_by_type
            null_iss = issues_by_type[DriftType.NULLABILITY_MISMATCH.value]
            assert null_iss["field_name"] == "total_cents"
            assert null_iss["severity"] == DriftSeverity.CRITICAL.value

            # 3. TYPE_INCOMPATIBILITY: notes
            assert DriftType.TYPE_INCOMPATIBILITY.value in issues_by_type
            type_iss = issues_by_type[DriftType.TYPE_INCOMPATIBILITY.value]
            assert type_iss["field_name"] == "notes"
            assert type_iss["severity"] == DriftSeverity.CRITICAL.value

            # 4. LENGTH_CONSTRAINT_DRIFT: coupon_code
            assert DriftType.LENGTH_CONSTRAINT_DRIFT.value in issues_by_type
            len_iss = issues_by_type[DriftType.LENGTH_CONSTRAINT_DRIFT.value]
            assert len_iss["field_name"] == "coupon_code"
            assert len_iss["severity"] == DriftSeverity.WARNING.value

            # 5. UNUSED_SCHEMA_FIELD: referral_source
            assert DriftType.UNUSED_SCHEMA_FIELD.value in issues_by_type
            unused_iss = issues_by_type[DriftType.UNUSED_SCHEMA_FIELD.value]
            assert unused_iss["field_name"] == "referral_source"
            assert unused_iss["severity"] == DriftSeverity.INFO.value

        # Test CLI schema-drift command
        cli_res = runner.invoke(
            app,
            ["schema-drift", "--route", "/api/v1/orders/checkout", "-r", str(repo), "--table", "orders", "--schema", "CheckoutRequest", "--json"],
        )
        assert cli_res.exit_code == 0
        import json
        cli_data = json.loads(cli_res.stdout)
        assert cli_data["status"] == "ok"
        assert cli_data["drift_count"] == 5

        # 4. Test automatic inference without passing table or schema
        with indexer.connect() as con:
            auto_res = detect_schema_drift(
                con,
                repo,
                route_or_handler="/api/v1/orders/checkout",
            )
            assert auto_res["status"] == "ok"
            assert auto_res["target_table"] == "orders"
            assert auto_res["schema_name"] == "CheckoutRequest"
            assert auto_res["drift_count"] == 5


def test_django_form_schema_drift():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        app_dir = repo / "accounts"
        app_dir.mkdir(parents=True, exist_ok=True)

        # 1. Models: Django users table
        (app_dir / "models.py").write_text("""
from django.db import models

class User(models.Model):
    username = models.CharField(max_length=10)
    email = models.CharField(max_length=255)
    password_hash = models.CharField(max_length=255)
    age = models.IntegerField()

    class Meta:
        db_table = "users"
""", encoding="utf-8")

        # 2. Django Form: UserRegistrationForm with drift
        (app_dir / "forms.py").write_text("""
from django import forms

class UserRegistrationForm(forms.Form):
    # Drift 1: max_length=20 in Form, but max_length=10 in DB (LENGTH_CONSTRAINT_DRIFT)
    username = forms.CharField(max_length=20, required=True)

    # Drift 2: email is optional in form (required=False), but NOT NULL in DB (NULLABILITY_MISMATCH)
    email = forms.CharField(max_length=255, required=False)

    # Drift 3: extra_bio not in users table (UNUSED_SCHEMA_FIELD)
    extra_bio = forms.CharField(max_length=100)

    # Drift 4: password_hash is in DB but missing from form (MISSING_REQUIRED_COLUMN)
""", encoding="utf-8")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            res = detect_schema_drift(
                con,
                repo,
                route_or_handler="UserRegistrationForm",
                target_table="users",
                schema_name="UserRegistrationForm",
            )

            assert res["status"] == "ok"
            assert res["drift_count"] >= 4
            issues_by_type = {i["drift_type"]: i for i in res["issues"]}
            assert DriftType.MISSING_REQUIRED_COLUMN.value in issues_by_type
            assert DriftType.NULLABILITY_MISMATCH.value in issues_by_type
            assert DriftType.LENGTH_CONSTRAINT_DRIFT.value in issues_by_type
            assert DriftType.UNUSED_SCHEMA_FIELD.value in issues_by_type
