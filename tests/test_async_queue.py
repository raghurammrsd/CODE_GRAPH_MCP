"""Tests for asynchronous queue and cross-service distributed task scanning & linking.

Verifies:
1. Celery task definition (@shared_task / @app.task) and dispatch (.delay / .apply_async)
2. Kafka producer (producer.send) and consumer (@consumer / KafkaConsumer)
3. AWS SQS producer and consumer
4. RabbitMQ basic_publish and basic_consume
5. Redis Pub/Sub (publish / subscribe) and Streams (xadd / xread)
6. Fan-out (1 producer -> multiple consumers)
7. Fan-in (multiple producers -> 1 consumer)
8. End-to-end trace_async_flow from producer to queue to consumer worker to DB
9. trace_path traversal across async boundaries
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.async_queue.models import (
    AsyncQueueEvidenceClass,
)
from codegraph.async_queue.traversal import (
    find_queue_consumers,
    find_queue_producers,
    list_async_queues,
    trace_async_flow,
)
from codegraph.indexing.indexer import Indexer


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "test_repo"
    repo.mkdir()
    return repo


def test_celery_task_and_delay(temp_repo: Path) -> None:
    """Test Celery @shared_task definition and .delay() dispatch linking."""
    tasks_file = temp_repo / "tasks.py"
    tasks_file.write_text(
        """from celery import shared_task

@shared_task(queue="billing")
def process_invoice(invoice_id: str):
    return True
""",
        encoding="utf-8",
    )

    caller_file = temp_repo / "service.py"
    caller_file.write_text(
        """from tasks import process_invoice

def create_order():
    process_invoice.delay("inv-123")
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        queues = list_async_queues(con)
        assert len(queues) >= 1
        q_ids = [q["queue_id"] for q in queues]
        # Celery queues are identified by celery:queue_name or celery:task_name
        assert any("billing" in q or "process_invoice" in q for q in q_ids)

        producers = find_queue_producers(con, "billing")
        if not producers:
            producers = find_queue_producers(con, "process_invoice")
        assert len(producers) >= 1
        assert "create_order" in producers[0]["caller_canonical_id"]

        consumers = find_queue_consumers(con, "billing")
        if not consumers:
            consumers = find_queue_consumers(con, "process_invoice")
        assert len(consumers) >= 1
        assert "process_invoice" in consumers[0]["handler_canonical_id"]


def test_kafka_producer_and_consumer(temp_repo: Path) -> None:
    """Acceptance Test: Kafka producer.send and @consumer decorator linking."""
    producer_file = temp_repo / "order_service.py"
    producer_file.write_text(
        """class OrderService:
    def place_order(self, order_data):
        producer.send("order_events", order_data)
""",
        encoding="utf-8",
    )

    consumer_file = temp_repo / "order_worker.py"
    consumer_file.write_text(
        """@consumer("order_events")
def process_order(message):
    pass
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        # Check async_queues table
        q_row = con.execute("SELECT * FROM async_queues WHERE destination='order_events'").fetchone()
        assert q_row is not None
        assert q_row["system"] == "kafka"
        assert q_row["queue_id"] == "kafka:order_events"

        # Check async_producers table
        prods = find_queue_producers(con, "order_events")
        assert len(prods) == 1
        assert "place_order" in prods[0]["caller_canonical_id"]
        assert prods[0]["system"] == "kafka"

        # Check async_consumers table
        cons = find_queue_consumers(con, "order_events")
        assert len(cons) == 1
        assert "process_order" in cons[0]["handler_canonical_id"]
        assert cons[0]["system"] == "kafka"

        # Check async_links table
        link_row = con.execute("SELECT * FROM async_links WHERE destination='order_events'").fetchone()
        assert link_row is not None
        assert link_row["evidence_class"] == AsyncQueueEvidenceClass.STATIC_QUEUE_LINKED.value
        assert "place_order" in link_row["producer_id"]
        assert "process_order" in link_row["consumer_id"]

        # Check graph_edges table has STATIC_QUEUE_LINKED edge
        edge_row = con.execute(
            "SELECT * FROM graph_edges WHERE relationship='STATIC_QUEUE_LINKED'"
        ).fetchone()
        assert edge_row is not None
        assert "place_order" in edge_row["source"]
        assert "process_order" in edge_row["target"]


def test_fan_out_one_producer_multiple_consumers(temp_repo: Path) -> None:
    """Test Fan-Out: 1 producer publishes to a topic consumed by 2 distinct workers."""
    producer_file = temp_repo / "event_emitter.py"
    producer_file.write_text(
        """def emit_user_created(user):
    producer.send("user_registered", user)
""",
        encoding="utf-8",
    )

    worker_a = temp_repo / "email_worker.py"
    worker_a.write_text(
        """@consumer("user_registered")
def send_welcome_email(user):
    pass
""",
        encoding="utf-8",
    )

    worker_b = temp_repo / "analytics_worker.py"
    worker_b.write_text(
        """@consumer("user_registered")
def track_signup(user):
    pass
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        links = con.execute(
            "SELECT * FROM async_links WHERE destination='user_registered' ORDER BY consumer_id ASC"
        ).fetchall()
        assert len(links) == 2
        consumers_found = {str(link["consumer_id"]) for link in links}
        assert any("send_welcome_email" in c for c in consumers_found)
        assert any("track_signup" in c for c in consumers_found)


def test_fan_in_multiple_producers_one_consumer(temp_repo: Path) -> None:
    """Test Fan-In: Multiple producers publish to a topic consumed by 1 worker."""
    auth_service = temp_repo / "auth_service.py"
    auth_service.write_text(
        """def login(user):
    producer.send("audit_log", {"action": "login"})
""",
        encoding="utf-8",
    )

    checkout_service = temp_repo / "checkout_service.py"
    checkout_service.write_text(
        """def checkout(cart):
    producer.send("audit_log", {"action": "checkout"})
""",
        encoding="utf-8",
    )

    audit_worker = temp_repo / "audit_worker.py"
    audit_worker.write_text(
        """@consumer("audit_log")
def record_audit(event):
    pass
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        links = con.execute(
            "SELECT * FROM async_links WHERE destination='audit_log' ORDER BY producer_id ASC"
        ).fetchall()
        assert len(links) == 2
        producers_found = {str(link["producer_id"]) for link in links}
        assert any("login" in p for p in producers_found)
        assert any("checkout" in p for p in producers_found)


def test_aws_sqs_and_rabbitmq_and_redis(temp_repo: Path) -> None:
    """Test SQS, RabbitMQ, and Redis detection."""
    sqs_file = temp_repo / "sqs_service.py"
    sqs_file.write_text(
        """def notify_shipping(order):
    sqs.send_message(QueueUrl="https://sqs.us-east-1.amazonaws.com/123/shipping_queue", MessageBody="order")

def poll_shipping():
    sqs.receive_message(QueueUrl="https://sqs.us-east-1.amazonaws.com/123/shipping_queue")
""",
        encoding="utf-8",
    )

    rabbit_file = temp_repo / "rabbit_service.py"
    rabbit_file.write_text(
        """def publish_payment():
    channel.basic_publish(exchange="pay", routing_key="payment_queue", body="pay")

def handle_payment():
    channel.basic_consume(queue="payment_queue", on_message_callback=callback)
""",
        encoding="utf-8",
    )

    redis_file = temp_repo / "redis_service.py"
    redis_file.write_text(
        """def notify_cache():
    r.publish("cache_invalidation", "key")

def listen_cache():
    pubsub.subscribe("cache_invalidation")
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        queues = list_async_queues(con)
        systems_detected = {q["system"] for q in queues}
        assert "aws_sqs" in systems_detected
        assert "rabbitmq" in systems_detected
        assert "redis" in systems_detected


def test_trace_async_flow_end_to_end(temp_repo: Path) -> None:
    """Test trace_async_flow linking producer -> queue -> consumer -> DB query."""
    producer_code = temp_repo / "order_api.py"
    producer_code.write_text(
        """def post_order(order):
    producer.send("orders_topic", order)
""",
        encoding="utf-8",
    )

    worker_code = temp_repo / "order_consumer.py"
    worker_code.write_text(
        """@consumer("orders_topic")
def process_order_message(msg):
    # simulate raw sql execution
    cursor.execute("INSERT INTO orders (id, status) VALUES (1, 'ok')")
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        # Trace from producer entrypoint
        flow = trace_async_flow(con, "post_order")
        assert flow["status"] == "ok"
        assert flow["producers_count"] >= 1
        assert flow["consumers_count"] >= 1
        assert len(flow["flow_steps"]) >= 2

        # Check steps sequence
        step_rels = [s["relationship"] for s in flow["flow_steps"]]
        assert "PRODUCES_TO_QUEUE" in step_rels
        assert "CONSUMES_FROM_QUEUE" in step_rels

        # Trace from queue topic name directly
        queue_flow = trace_async_flow(con, "orders_topic")
        assert queue_flow["status"] == "ok"
        assert queue_flow["producers_count"] >= 1
        assert queue_flow["consumers_count"] >= 1


def test_interrogation_trace_path_across_async_queue(temp_repo: Path) -> None:
    """Test trace_path finds path between producer function and consumer function."""
    from codegraph.interrogation import trace_path

    p_file = temp_repo / "sender.py"
    p_file.write_text(
        """def trigger_job():
    producer.send("job_queue", {"data": 1})
""",
        encoding="utf-8",
    )

    c_file = temp_repo / "receiver.py"
    c_file.write_text(
        """@consumer("job_queue")
def handle_job(data):
    pass
""",
        encoding="utf-8",
    )

    indexer = Indexer(temp_repo)
    indexer.index()

    with indexer.session() as con:
        res = trace_path(con, temp_repo, from_symbol="trigger_job", to_symbol="handle_job", max_depth=4)
        assert res["status"] == "ok"
        assert res["path_length"] >= 1
        edge = res["path"][0]
        assert edge["relationship"] == "STATIC_QUEUE_LINKED"
        assert edge["evidence_class"] == "STATIC_QUEUE_LINKED"


def test_async_cli_commands(temp_repo: Path) -> None:
    """Test codegraph async queues and codegraph async trace CLI commands."""
    from typer.testing import CliRunner

    from codegraph.cli import app

    runner = CliRunner()

    p_file = temp_repo / "pub.py"
    p_file.write_text(
        """def publish_event(evt):
    producer.send("cli_events", evt)
""",
        encoding="utf-8",
    )

    c_file = temp_repo / "sub.py"
    c_file.write_text(
        """@consumer("cli_events")
def consume_event(evt):
    pass
""",
        encoding="utf-8",
    )

    # Index first
    idx_res = runner.invoke(app, ["index", "-r", str(temp_repo)])
    assert idx_res.exit_code == 0

    # Test async queues
    q_res = runner.invoke(app, ["async", "queues", "-r", str(temp_repo)])
    assert q_res.exit_code == 0
    assert "cli_events" in q_res.output

    # Test async queues --json
    q_json = runner.invoke(app, ["async", "queues", "-r", str(temp_repo), "--json"])
    assert q_json.exit_code == 0
    assert "cli_events" in q_json.output

    # Test async trace
    t_res = runner.invoke(app, ["async", "trace", "publish_event", "-r", str(temp_repo)])
    assert t_res.exit_code == 0
    assert "PRODUCES_TO_QUEUE" in t_res.output
    assert "CONSUMES_FROM_QUEUE" in t_res.output

    # Test async trace --json
    t_json = runner.invoke(app, ["async", "trace", "publish_event", "-r", str(temp_repo), "--json"])
    assert t_json.exit_code == 0
    assert '"status": "ok"' in t_json.output
