from __future__ import annotations

from unittest.mock import patch

from codegraph.indexing.parser import parse


def test_python_single_pass_ast_walk_count() -> None:
    """Verify that parsing Python AST uses single-pass visitor with zero calls to ast.walk."""
    code = """
import os

class BaseService:
    def execute(self):
        return os.getenv("ENV")

class OrderService(BaseService):
    def process_order(self, order_id):
        def helper():
            return len(order_id)
        return helper()
"""
    with patch("ast.walk", side_effect=AssertionError("ast.walk should not be called in single-pass parser!")):
        result = parse(code, "python", "services/order.py")

    assert not result.parse_failed
    assert len(result.symbols) >= 4

    names = {s.name for s in result.symbols}
    assert {"BaseService", "execute", "OrderService", "process_order", "helper"} <= names

    # Verify scopes and canonical IDs
    sym_by_name = {s.name: s for s in result.symbols}
    assert sym_by_name["execute"].scope == "BaseService"
    assert sym_by_name["execute"].qualified_name == "BaseService.execute"
    assert sym_by_name["execute"].canonical_id == "services.order.BaseService.execute"
    assert sym_by_name["process_order"].scope == "OrderService"
    assert sym_by_name["helper"].scope == "OrderService.process_order"
    assert sym_by_name["helper"].qualified_name == "OrderService.process_order.helper"
    assert sym_by_name["helper"].canonical_id == "services.order.OrderService.process_order.helper"


def test_nested_classes_and_closures() -> None:
    """Verify arbitrarily deeply nested classes, methods, and functions maintain precise scope."""
    code = """
class Level1:
    class Level2:
        def level3_method(self):
            def level4_func():
                return 42
            return level4_func()
"""
    result = parse(code, "python", "pkg/nested.py")
    assert not result.parse_failed

    sym_by_name = {s.name: s for s in result.symbols}
    assert sym_by_name["Level1"].kind == "class"
    assert sym_by_name["Level2"].scope == "Level1"
    assert sym_by_name["level3_method"].scope == "Level1.Level2"
    assert sym_by_name["level3_method"].qualified_name == "Level1.Level2.level3_method"
    assert sym_by_name["level4_func"].scope == "Level1.Level2.level3_method"
    assert sym_by_name["level4_func"].qualified_name == "Level1.Level2.level3_method.level4_func"


def test_builtins_not_confused_with_local_calls() -> None:
    """Verify builtins like len, range, print are filtered from project call graph."""
    code = """
def calculate(items):
    total = len(items)
    for i in range(total):
        print(i)
    custom_func(total)
    return total
"""
    result = parse(code, "python", "calc.py")
    assert not result.parse_failed
    callee_names = {c.callee for c in result.calls}
    # Builtins must NOT become call refs
    assert "len" not in callee_names
    assert "range" not in callee_names
    assert "print" not in callee_names
    # Custom calls must be extracted
    assert "custom_func" in callee_names


def test_js_ts_multi_statement_and_scopes() -> None:
    """Verify JS/TS parser extracts multiple declarations on single lines and classes."""
    code = """
import { auth } from './auth';
export class UserController {
    login(req, res) { return auth(req); }
}
export function helper() { return 1; } export function secondHelper() { return 2; }
"""
    result = parse(code, "typescript", "src/controllers.ts")
    assert not result.parse_failed

    names = {s.name for s in result.symbols}
    assert "UserController" in names
    assert "login" in names
    assert "helper" in names
    assert "secondHelper" in names
