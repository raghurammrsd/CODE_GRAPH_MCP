"""Apache Kafka producer and consumer detector.

Detects:
  - Publishers / Producers: producer.send(topic, ...), producer.produce(topic, ...)
  - Consumers / Workers: @consumer(topic), @subscriber(topic), KafkaConsumer(topic), consumer.subscribe([topic])
"""
from __future__ import annotations

import ast
from typing import Any

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
)

_KAFKA_CONSUMER_DECORATORS = {
    "consumer",
    "kafka_consumer",
    "subscriber",
    "consume",
    "agent",
}


def detect_kafka(
    tree: ast.AST,
    content: str,
    file_path: str,
    module_name: str,
) -> tuple[list[AsyncProducerRecord], list[AsyncConsumerRecord]]:
    producers: list[AsyncProducerRecord] = []
    consumers: list[AsyncConsumerRecord] = []
    lines = content.splitlines()

    def get_line_snippet(lineno: int) -> str:
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    # 1. Detect consumers via decorators or subscriber calls
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                dec_func = dec.func if isinstance(dec, ast.Call) else dec
                dec_name = getattr(dec_func, "id", "") or getattr(dec_func, "attr", "")

                if dec_name.lower() in _KAFKA_CONSUMER_DECORATORS:
                    topic = ""
                    if isinstance(dec, ast.Call):
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            topic = dec.args[0].value
                        for kw in dec.keywords:
                            if kw.arg in ("topic", "topics") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                topic = kw.value.value

                    if topic:
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.KAFKA,
                                destination=topic,
                                queue_id=f"kafka:{topic}",
                                handler_canonical_id=f"{module_name}.{node.name}",
                                file_path=file_path,
                                line=node.lineno,
                                handler_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"decorator": dec_name},
                            )
                        )

    # 2. Detect producers & programmatic consumers inside function scopes
    class KafkaCallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.current_function: str = f"{module_name}.<module>"

        def visit_FunctionDef(self, fn: ast.FunctionDef) -> None:
            prev = self.current_function
            self.current_function = f"{module_name}.{fn.name}"
            self.generic_visit(fn)
            self.current_function = prev

        def visit_AsyncFunctionDef(self, fn: ast.AsyncFunctionDef) -> None:
            prev = self.current_function
            self.current_function = f"{module_name}.{fn.name}"
            self.generic_visit(fn)
            self.current_function = prev

        def visit_Call(self, node: ast.Call) -> None:
            # Check for producer.send(topic, ...) or producer.produce(topic, ...)
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("send", "produce"):
                topic = ""
                meta: dict[str, Any] = {"method": node.func.attr}
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    topic = node.args[0].value
                for kw in node.keywords:
                    if kw.arg == "topic" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        topic = kw.value.value
                    elif kw.arg in ("key", "partition", "headers"):
                        meta[kw.arg] = True

                if topic:
                    producers.append(
                        AsyncProducerRecord(
                            system=AsyncMessagingSystem.KAFKA,
                            destination=topic,
                            queue_id=f"kafka:{topic}",
                            caller_canonical_id=self.current_function,
                            file_path=file_path,
                            line=node.lineno,
                            call_snippet=get_line_snippet(node.lineno),
                            confidence="HIGH",
                            metadata=meta,
                        )
                    )

            # Check for consumer.subscribe([topic, ...])
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "subscribe":
                topic_list: list[str] = []
                if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    for elt in node.args[0].elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            topic_list.append(elt.value)
                for kw in node.keywords:
                    if kw.arg == "topics" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                topic_list.append(elt.value)

                for t in topic_list:
                    consumers.append(
                        AsyncConsumerRecord(
                            system=AsyncMessagingSystem.KAFKA,
                            destination=t,
                            queue_id=f"kafka:{t}",
                            handler_canonical_id=self.current_function,
                            file_path=file_path,
                            line=node.lineno,
                            handler_snippet=get_line_snippet(node.lineno),
                            confidence="HIGH",
                            metadata={"method": "subscribe"},
                        )
                    )

            # Check for KafkaConsumer(topic, ...)
            elif isinstance(node.func, ast.Name) and node.func.id == "KafkaConsumer":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    t = node.args[0].value
                    consumers.append(
                        AsyncConsumerRecord(
                            system=AsyncMessagingSystem.KAFKA,
                            destination=t,
                            queue_id=f"kafka:{t}",
                            handler_canonical_id=self.current_function,
                            file_path=file_path,
                            line=node.lineno,
                            handler_snippet=get_line_snippet(node.lineno),
                            confidence="HIGH",
                            metadata={"method": "KafkaConsumer"},
                        )
                    )

            self.generic_visit(node)

    KafkaCallVisitor().visit(tree)

    return producers, consumers
