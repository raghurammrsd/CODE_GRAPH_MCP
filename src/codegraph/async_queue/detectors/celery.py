"""Celery asynchronous task and canvas detector.

Detects:
  - Workers / Consumers: @app.task, @celery.task, @shared_task, @celery_app.task
  - Publishers / Producers: task.delay(), task.apply_async(), app.send_task()
"""
from __future__ import annotations

import ast
from typing import Any

from codegraph.async_queue.models import (
    AsyncConsumerRecord,
    AsyncMessagingSystem,
    AsyncProducerRecord,
)

_CELERY_TASK_DECORATORS = {
    "task",
    "shared_task",
}


def detect_celery(
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

    # Map of function names that are Celery tasks in this file
    local_tasks: dict[str, str] = {}  # fn_name -> task_name

    # 1. Detect consumers (task definitions)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                dec_func = dec.func if isinstance(dec, ast.Call) else dec
                dec_id = getattr(dec_func, "id", "")
                dec_attr = getattr(dec_func, "attr", "")

                if dec_id in _CELERY_TASK_DECORATORS or dec_attr in _CELERY_TASK_DECORATORS:
                    # Found a Celery task definition
                    task_name = f"{module_name}.{node.name}"
                    metadata: dict[str, Any] = {}

                    if isinstance(dec, ast.Call):
                        for kw in dec.keywords:
                            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                task_name = kw.value.value
                            elif kw.arg == "queue" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                metadata["queue"] = kw.value.value
                            elif kw.arg == "max_retries" and isinstance(kw.value, ast.Constant):
                                metadata["max_retries"] = kw.value.value
                            elif kw.arg == "autoretry_for":
                                metadata["autoretry"] = True
                            elif kw.arg == "retry_backoff":
                                metadata["retry_backoff"] = True

                    local_tasks[node.name] = task_name
                    canonical_id = f"{module_name}.{node.name}"
                    queue_id = f"celery:{task_name}"

                    consumers.append(
                        AsyncConsumerRecord(
                            system=AsyncMessagingSystem.CELERY,
                            destination=task_name,
                            queue_id=queue_id,
                            handler_canonical_id=canonical_id,
                            file_path=file_path,
                            line=node.lineno,
                            handler_snippet=get_line_snippet(node.lineno),
                            confidence="HIGH",
                            metadata=metadata,
                        )
                    )

    # 2. Detect producers (task invocations: .delay, .apply_async, app.send_task)
    class CallVisitor(ast.NodeVisitor):
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
                method_name = node.func.attr
                # Case A: task.delay(...) or task.apply_async(...)
                if method_name in ("delay", "apply_async"):
                    caller_val = node.func.value
                    task_target_name = ""
                    if isinstance(caller_val, ast.Name):
                        task_target_name = caller_val.id
                    elif isinstance(caller_val, ast.Attribute):
                        task_target_name = caller_val.attr

                    if task_target_name:
                        resolved_dest = local_tasks.get(task_target_name, task_target_name)
                        meta: dict[str, Any] = {"method": method_name}
                        if method_name == "apply_async":
                            for kw in node.keywords:
                                if kw.arg in ("countdown", "eta", "queue", "retry"):
                                    meta[kw.arg] = True

                        producers.append(
                            AsyncProducerRecord(
                                system=AsyncMessagingSystem.CELERY,
                                destination=resolved_dest,
                                queue_id=f"celery:{resolved_dest}",
                                caller_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                call_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata=meta,
                            )
                        )

                # Case B: app.send_task("task_name", ...)
                elif method_name == "send_task" and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        dest = first_arg.value
                        producers.append(
                            AsyncProducerRecord(
                                system=AsyncMessagingSystem.CELERY,
                                destination=dest,
                                queue_id=f"celery:{dest}",
                                caller_canonical_id=self.current_function,
                                file_path=file_path,
                                line=node.lineno,
                                call_snippet=get_line_snippet(node.lineno),
                                confidence="HIGH",
                                metadata={"method": "send_task"},
                            )
                        )

            self.generic_visit(node)

    CallVisitor().visit(tree)

    return producers, consumers
