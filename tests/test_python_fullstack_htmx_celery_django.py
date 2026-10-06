"""Test Python Full-Stack (Django, FastAPI, Flask) super-powers:
1. HTMX and Alpine.js frontend attribute extraction and route linking.
2. Celery background task lineage (.delay(), .apply_async(), send_task()).
3. Django Signals and receiver linking (@receiver, signal.connect).
4. View template rendering detection (render_template, TemplateResponse, CBV template_name).
5. End-to-end multi-layer full-stack trace.
"""

from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.interrogation import (
    get_callees,
    get_callers,
    list_routes,
    trace_path,
)


def test_htmx_and_alpine_extraction(tmp_path: Path) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir(parents=True)
    html_file = template_dir / "users.html"
    html_file.write_text(
        """<!DOCTYPE html>
<html>
<body>
  <div x-data="{ open: false }">
    <button @click="open = !open" x-on:keydown.escape="open = false">Menu</button>
    <div x-show="open" x-init="fetchStats()">Stats</div>
  </div>

  <table id="user-table">
    <tr id="user-42">
      <td>Alice</td>
      <td>
        <button hx-post="/users/42/delete"
                hx-target="#user-42"
                hx-swap="outerHTML"
                hx-trigger="click">
          Delete
        </button>
      </td>
    </tr>
    <tr id="user-43">
      <td>Bob</td>
      <td>
        <a hx-get="/users/43/details"
           hx-target="#modal-body"
           hx-trigger="mouseenter once">
          Preview
        </a>
      </td>
    </tr>
  </table>

  <div hx-get="/api/live-stats" hx-trigger="every 2s" hx-target="#stats-panel"></div>
</body>
</html>
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check bindings table for HTMX requests
        htmx_bindings = con.execute(
            "SELECT target_name, file_path, line, base_expr, dict_entries_json "
            "FROM local_bindings WHERE expr_kind='HTMX_REQUEST' ORDER BY line ASC"
        ).fetchall()

        assert len(htmx_bindings) == 3
        # First HTMX binding is POST /users/42/delete
        assert htmx_bindings[0]["target_name"] == "/users/42/delete"
        assert htmx_bindings[0]["base_expr"] == "POST"
        assert "#user-42" in htmx_bindings[0]["dict_entries_json"]
        assert "outerHTML" in htmx_bindings[0]["dict_entries_json"]

        # Second HTMX binding is GET /users/43/details
        assert htmx_bindings[1]["target_name"] == "/users/43/details"
        assert htmx_bindings[1]["base_expr"] == "GET"
        assert "#modal-body" in htmx_bindings[1]["dict_entries_json"]

        # Third HTMX binding is GET /api/live-stats
        assert htmx_bindings[2]["target_name"] == "/api/live-stats"
        assert htmx_bindings[2]["base_expr"] == "GET"
        assert "every 2s" in htmx_bindings[2]["dict_entries_json"]

        # Check symbols table for HTMX actions
        htmx_symbols = con.execute(
            "SELECT name, kind, path FROM symbols WHERE kind='htmx_action'"
        ).fetchall()
        assert len(htmx_symbols) == 3

        # Check Alpine events extracted in local_bindings
        alpine_bindings = con.execute(
            "SELECT target_name, expr_kind FROM local_bindings WHERE expr_kind='ALPINE_EVENT'"
        ).fetchall()
        assert len(alpine_bindings) >= 2


def test_celery_task_lineage(tmp_path: Path) -> None:
    tasks_file = tmp_path / "tasks.py"
    tasks_file.write_text(
        """from celery import shared_task

@shared_task
def send_welcome_email(user_id: int):
    return True

@shared_task
def process_order_payment(order_id: int, amount: float):
    return True
""",
        encoding="utf-8",
    )

    services_file = tmp_path / "services.py"
    services_file.write_text(
        """from tasks import send_welcome_email, process_order_payment

def register_user(user_id: int):
    # Celery delay call
    send_welcome_email.delay(user_id)

def checkout_order(order_id: int, total: float):
    # Celery apply_async call
    process_order_payment.apply_async(args=[order_id, total], countdown=30)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check graph_edges for DISPATCHES_TASK and CALLS
        task_edges = con.execute(
            "SELECT source, target, relationship, confidence FROM graph_edges "
            "WHERE relationship IN ('DISPATCHES_TASK', 'CALLS') "
            "ORDER BY relationship ASC, source ASC"
        ).fetchall()

        dispatches = [e for e in task_edges if e["relationship"] == "DISPATCHES_TASK"]
        assert len(dispatches) >= 2

        # Verify register_user dispatches to send_welcome_email
        reg_dispatch = [d for d in dispatches if "register_user" in d["source"]]
        assert len(reg_dispatch) == 1
        assert "send_welcome_email" in reg_dispatch[0]["target"]

        # Verify checkout_order dispatches to process_order_payment
        chk_dispatch = [d for d in dispatches if "checkout_order" in d["source"]]
        assert len(chk_dispatch) == 1
        assert "process_order_payment" in chk_dispatch[0]["target"]

        # Test callers of send_welcome_email
        callers_res = get_callers(con, tmp_path, symbol="send_welcome_email")
        assert callers_res["status"] == "ok"
        caller_names = [c["caller"] for c in callers_res["callers"]]
        assert any("register_user" in name for name in caller_names)

        # Test callees of checkout_order
        callees_res = get_callees(con, tmp_path, symbol="checkout_order")
        assert callees_res["status"] == "ok"
        callee_names = [c["callee"] for c in callees_res["callees"]]
        assert any("process_order_payment" in name for name in callee_names)

        # Test deterministic trace from checkout_order to process_order_payment
        trace_res = trace_path(con, tmp_path, from_symbol="checkout_order", to_symbol="process_order_payment")
        assert trace_res["status"] == "ok"
        assert trace_res["path_length"] >= 1


def test_django_signals_lineage(tmp_path: Path) -> None:
    models_file = tmp_path / "models.py"
    models_file.write_text(
        """class Customer:
    def save(self):
        pass

    def delete(self):
        pass
""",
        encoding="utf-8",
    )

    signals_file = tmp_path / "signals.py"
    signals_file.write_text(
        """from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete
from models import Customer

@receiver(post_save, sender=Customer)
def on_customer_created(sender, instance, created, **kwargs):
    pass

def on_customer_deleted(sender, instance, **kwargs):
    pass

post_delete.connect(on_customer_deleted, sender=Customer)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check signal edges
        sig_edges = con.execute(
            "SELECT source, target, relationship, confidence FROM graph_edges "
            "WHERE relationship IN ('TRIGGERS_SIGNAL', 'HANDLES_SIGNAL') "
            "ORDER BY relationship ASC, source ASC"
        ).fetchall()

        triggers = [e for e in sig_edges if e["relationship"] == "TRIGGERS_SIGNAL"]
        assert len(triggers) >= 2

        # Customer or Customer.save triggers on_customer_created
        assert any("on_customer_created" in t["target"] and "Customer" in t["source"] for t in triggers)

        # Customer or Customer.delete triggers on_customer_deleted (via connect)
        assert any("on_customer_deleted" in t["target"] and "Customer" in t["source"] for t in triggers)

        # HANDLES_SIGNAL connects receiver back to Customer
        handles = [e for e in sig_edges if e["relationship"] == "HANDLES_SIGNAL"]
        assert any("on_customer_created" in h["source"] and "Customer" in h["target"] for h in handles)

        # Test trace_path from Customer to on_customer_created
        trace_res = trace_path(con, tmp_path, from_symbol="Customer.save", to_symbol="on_customer_created")
        assert trace_res["status"] == "ok"
        assert trace_res["path_length"] >= 1


def test_view_template_rendering(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text(
        """from flask import Flask, render_template

app = Flask(__name__)

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", active=True)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check graph_edges for RENDERS_TEMPLATE
        render_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges WHERE relationship='RENDERS_TEMPLATE'"
        ).fetchall()

        assert len(render_edges) == 1
        assert "dashboard" in render_edges[0]["source"]
        assert render_edges[0]["target"] == "dashboard.html"

        # Check list_routes returns dashboard with templates_rendered
        routes_res = list_routes(con, tmp_path)
        assert routes_res["status"] == "ok"
        assert len(routes_res["routes"]) == 1
        route = routes_res["routes"][0]
        assert route["path"] == "/dashboard"
        assert len(route["templates_rendered"]) == 1
        assert route["templates_rendered"][0]["template"] == "dashboard.html"


def test_end_to_end_fullstack_htmx_route_celery_signal(tmp_path: Path) -> None:
    # 1. Template with HTMX button calling POST /api/orders/99/cancel
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "orders.html").write_text(
        """<div id="order-card-99">
  <button hx-post="/api/orders/99/cancel"
          hx-target="#order-card-99"
          hx-swap="outerHTML">
    Cancel Order
  </button>
</div>
""",
        encoding="utf-8",
    )

    # 2. Celery tasks
    (tmp_path / "tasks.py").write_text(
        """from celery import shared_task

@shared_task
def notify_cancellation(order_id: int):
    pass
""",
        encoding="utf-8",
    )

    # 3. Model with Signal
    (tmp_path / "models.py").write_text(
        """class Order:
    def save(self):
        pass
""",
        encoding="utf-8",
    )

    (tmp_path / "signals.py").write_text(
        """from django.dispatch import receiver
from django.db.models.signals import post_save
from models import Order

@receiver(post_save, sender=Order)
def on_order_saved(sender, instance, **kwargs):
    pass
""",
        encoding="utf-8",
    )

    # 4. Flask / FastAPI controller
    (tmp_path / "routes.py").write_text(
        """from flask import Flask, render_template
from tasks import notify_cancellation
from models import Order

app = Flask(__name__)

@app.route("/api/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id: int):
    order = Order()
    order.save()
    notify_cancellation.delay(order_id)
    return render_template("orders.html")
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Verify routes interrogation links HTMX button straight to cancel_order
        routes_res = list_routes(con, tmp_path)
        assert routes_res["status"] == "ok"
        matching_routes = [r for r in routes_res["routes"] if "cancel" in r["path"]]
        assert len(matching_routes) == 1
        route = matching_routes[0]

        # HTMX button matched!
        assert len(route["htmx_callers"]) == 1
        assert route["htmx_callers"][0]["url"] == "/api/orders/99/cancel"
        assert route["htmx_callers"][0]["method"] == "POST"
        assert route["htmx_callers"][0]["target"] == "#order-card-99"

        # Template rendered matched!
        assert len(route["templates_rendered"]) == 1
        assert "orders.html" in route["templates_rendered"][0]["template"]

        # Celery dispatch traced
        trace_celery = trace_path(con, tmp_path, from_symbol="cancel_order", to_symbol="notify_cancellation")
        assert trace_celery["status"] == "ok"
        assert trace_celery["path_length"] >= 1

        # Signal dispatch traced from Order.save to on_order_saved
        trace_signal = trace_path(con, tmp_path, from_symbol="Order.save", to_symbol="on_order_saved")
        assert trace_signal["status"] == "ok"
        assert trace_signal["path_length"] >= 1
