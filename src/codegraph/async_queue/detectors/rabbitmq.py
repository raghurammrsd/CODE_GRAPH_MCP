"""RabbitMQ / AMQP / Pika message producer and consumer detector.

Detects:
  - Publishers / Producers: channel.basic_publish(exchange=..., routing_key=...)
  - Consumers / Workers: channel.basic_consume(queue=..., on_message_callback=...)
"""
from __future__ import annotations

import ast
from typing import Any

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
)


def detect_rabbitmq(
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

    class RabbitMQVisitor(ast.NodeVisitor):
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
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                # Producer: basic_publish
                if attr in ("basic_publish", "publish"):
                    routing_key = ""
                    exchange = ""
                    meta: dict[str, Any] = {"method": attr}
                    for kw in node.keywords:
                        if kw.arg == "routing_key" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            routing_key = kw.value.value
                        elif kw.arg == "exchange" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            exchange = kw.value.value

                    dest = routing_key or exchange
                    if dest:
                        if exchange:
                            meta["exchange"] = exchange
                        if routing_key:
                            meta["routing_key"] = routing_key

                        producers.append(
                            AsyncProducerRecord(
                                system=AsyncMessagingSystem.RABBITMQ,
                                destination=dest,
                                queue_id=f"rabbitmq:{dest}",
                                caller_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                call_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata=meta,
                            )
                        )

                # Consumer: basic_consume
                elif attr in ("basic_consume", "consume"):
                    queue_name = ""
                    callback_fn_name = ""
                    for kw in node.keywords:
                        if kw.arg == "queue" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            queue_name = kw.value.value
                        elif kw.arg == "on_message_callback":
                            if isinstance(kw.value, ast.Name):
                                callback_fn_name = kw.value.id

                    if queue_name:
                        handler_id = f"{module_name}.{callback_fn_name}" if callback_fn_name else self.current_function
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.RABBITMQ,
                                destination=queue_name,
                                queue_id=f"rabbitmq:{queue_name}",
                                handler_canonical_id=handler_id,
                                file_path=file_path,
                                line=node.lineno,
                                handler_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"callback": callback_fn_name} if callback_fn_name else {},
                            )
                        )

            self.generic_visit(node)

    RabbitMQVisitor().visit(tree)

    return producers, consumers
