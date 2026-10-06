"""Tests for Express / JS router middleware awareness and terminal handler extraction."""
from __future__ import annotations

from codegraph.frameworks import analyze_js_ts_line


def test_express_middleware_with_named_handler() -> None:
    line = "router.post('/processing/upload', requireRoles('admin'), uploadInvoiceFile);"
    routes = analyze_js_ts_line(line, 10, "routes/processing.js", "processing", set())
    assert len(routes) == 1
    r = routes[0]
    assert r.http_method == "POST"
    assert r.route_path == "/processing/upload"
    assert r.handler_name == "uploadInvoiceFile"
    assert "requireRoles" in r.evidence


def test_express_middleware_with_async_arrow_delegate() -> None:
    line = "router.post('/approvals/:id/approve', requireRoles('finance'), async (req, res) => { await approveInvoice(req.params.id); });"
    routes = analyze_js_ts_line(line, 25, "routes/approvals.js", "approvals", set())
    assert len(routes) == 1
    r = routes[0]
    assert r.http_method == "POST"
    assert r.route_path == "/approvals/:id/approve"
    assert r.handler_name == "approveInvoice"
    assert "requireRoles" in r.evidence


def test_express_multiple_middlewares_and_controller() -> None:
    line = "app.get('/users', authMiddleware, validateQuery, userController.getUsers);"
    routes = analyze_js_ts_line(line, 30, "server.js", "server", set())
    assert len(routes) == 1
    r = routes[0]
    assert r.http_method == "GET"
    assert r.route_path == "/users"
    assert r.handler_name == "getUsers"
    assert "authMiddleware" in r.evidence
    assert "validateQuery" in r.evidence


def test_express_inline_handler_fallback() -> None:
    line = "router.get('/status', (req, res) => res.json({ active: true }));"
    routes = analyze_js_ts_line(line, 5, "status.js", "status", set())
    assert len(routes) == 1
    r = routes[0]
    assert r.handler_name == "status_handler"
