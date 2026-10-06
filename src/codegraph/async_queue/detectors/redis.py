"""Redis Pub/Sub and Streams async message detector.

Detects:
  - Publishers / Producers: r.publish(channel, message), r.xadd(stream, fields)
  - Consumers / Workers: pubsub.subscribe(channel), r.xread({stream: id})
"""
from __future__ import annotations

import ast
from typing import Any

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
)


def detect_redis(
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

    class RedisVisitor(ast.NodeVisitor):
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
                # Producer: r.publish("channel", ...), r.xadd("stream", ...)
                if attr in ("publish", "xadd"):
                    channel_or_stream = ""
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        channel_or_stream = node.args[0].value
                    for kw in node.keywords:
                        if kw.arg in ("channel", "name") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            channel_or_stream = kw.value.value

                    if channel_or_stream:
                        meta: dict[str, Any] = {"method": attr, "type": "stream" if attr == "xadd" else "pubsub"}
                        producers.append(
                            AsyncProducerRecord(
                                system=AsyncMessagingSystem.REDIS,
                                destination=channel_or_stream,
                                queue_id=f"redis:{channel_or_stream}",
                                caller_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                call_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata=meta,
                            )
                        )

                # Consumer: pubsub.subscribe("channel"), r.xread({"stream": ...})
                elif attr == "subscribe":
                    channels: list[str] = []
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            channels.append(arg.value)
                        elif isinstance(arg, (ast.List, ast.Tuple)):
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    channels.append(elt.value)

                    for ch in channels:
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.REDIS,
                                destination=ch,
                                queue_id=f"redis:{ch}",
                                handler_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                handler_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"type": "pubsub"},
                            )
                        )

                elif attr == "xread":
                    streams: list[str] = []
                    if node.args and isinstance(node.args[0], ast.Dict):
                        for k in node.args[0].keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                streams.append(k.value)

                    for st in streams:
                        consumers.append(
                            AsyncConsumerRecord(
                                system=AsyncMessagingSystem.REDIS,
                                destination=st,
                                queue_id=f"redis:{st}",
                                handler_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                handler_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"type": "stream"},
                            )
                        )

            self.generic_visit(node)

    RedisVisitor().visit(tree)

    return producers, consumers
