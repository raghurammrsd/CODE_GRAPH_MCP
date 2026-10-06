"""AWS SQS message producer and consumer detector.

Detects:
  - Publishers / Producers: sqs.send_message(QueueUrl=...), sqs.send_message_batch()
  - Consumers / Workers: sqs.receive_message(QueueUrl=...), @sqs_handler()
"""
from __future__ import annotations

import ast
from typing import Any

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
)


def _extract_queue_name(url_or_name: str) -> str:
    """Extract queue name from SQS URL or name string."""
    clean = url_or_name.strip().rstrip("/")
    if "/" in clean:
        return clean.split("/")[-1]
    return clean


def detect_sqs(
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

    class SQSVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.current_function: str = f"{module_name}.<module>"

        def visit_FunctionDef(self, fn: ast.FunctionDef) -> None:
            prev = self.current_function
            self.current_function = f"{module_name}.{fn.name}"
            # Check for decorator like @sqs_handler
            for dec in fn.decorator_list:
                dec_func = dec.func if isinstance(dec, ast.Call) else dec
                dec_name = getattr(dec_func, "id", "") or getattr(dec_func, "attr", "")
                if "sqs" in dec_name.lower():
                    q_name = ""
                    if isinstance(dec, ast.Call):
                        for kw in dec.keywords:
                            if kw.arg in ("queue", "queue_name", "queue_url") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                q_name = _extract_queue_name(kw.value.value)
                    if q_name:
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.AWS_SQS,
                                destination=q_name,
                                queue_id=f"aws_sqs:{q_name}",
                                handler_canonical_id=f"{module_name}.{fn.name}",
                                file_path=file_path,
                                line=fn.lineno,
                                handler_snippet=get_line_snippet(fn.lineno),
                                confidence="HIGH",
                                metadata={"decorator": dec_name},
                            )
                        )
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
                # Producer: send_message, send_message_batch
                if attr in ("send_message", "send_message_batch"):
                    q_name = ""
                    meta: dict[str, Any] = {"method": attr}
                    for kw in node.keywords:
                        if kw.arg == "QueueUrl" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            q_name = _extract_queue_name(kw.value.value)
                        elif kw.arg in ("DelaySeconds", "MessageDeduplicationId", "MessageGroupId"):
                            meta[kw.arg] = True

                    if q_name:
                        producers.append(
                            AsyncProducerRecord(
                                system=AsyncMessagingSystem.AWS_SQS,
                                destination=q_name,
                                queue_id=f"aws_sqs:{q_name}",
                                caller_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                call_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata=meta,
                            )
                        )

                # Consumer: receive_message
                elif attr == "receive_message":
                    q_name = ""
                    for kw in node.keywords:
                        if kw.arg == "QueueUrl" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            q_name = _extract_queue_name(kw.value.value)
                    if q_name:
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.AWS_SQS,
                                destination=q_name,
                                queue_id=f"aws_sqs:{q_name}",
                                handler_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                handler_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"method": "receive_message"},
                            )
                        )

            self.generic_visit(node)

    SQSVisitor().visit(tree)

    return producers, consumers
