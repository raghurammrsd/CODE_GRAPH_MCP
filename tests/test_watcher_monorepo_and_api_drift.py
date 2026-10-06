"""Integration & Unit Tests for Watcher, Monorepo Workspaces, and API Contract Drift.

Validates:
- Sliding 250ms debouncer coalescing rapid file write bursts.
- Monorepo workspace detection (pnpm, yarn/npm, Turborepo) and inter-package mapping.
- Client-Server API contract drift (orphaned routes, HTTP method mismatches).
- MCP server registration and invocation of new tools.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from codegraph.api_drift import detect_api_contract_drift
from codegraph.indexing.indexer import Indexer
from codegraph.mcp.server import create_server
from codegraph.watcher import DebouncedIndexWorker, RepositoryWatcher


def test_debounced_index_worker_coalescing():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        indexer = Indexer(repo)

        batches_run: list[dict[str, int]] = []

        def _on_batch(res: dict[str, int]) -> None:
            batches_run.append(res)

        worker = DebouncedIndexWorker(
            indexer,
            debounce_delay_sec=0.1,  # Fast 100ms for test
            on_batch_complete=_on_batch,
        )

        # Rapidly fire 5 events within 20ms
        for i in range(5):
            worker.record_change(f"src/file_{i}.py")
            time.sleep(0.005)

        # Before 100ms expires, no batch should have completed yet
        assert len(batches_run) == 0

        # Wait for debounce window to settle
        time.sleep(0.2)

        # Exactly 1 batch run!
        assert len(batches_run) == 1
        assert worker.stats.batches_processed == 1
        assert worker.stats.events_received == 5
        worker.cancel()


def test_repository_watcher_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        watcher = RepositoryWatcher(repo, debounce_delay_sec=0.1)
        started = watcher.start()
        assert started is True
        assert watcher.worker.stats.is_running is True
        watcher.stop()
        assert watcher.worker.stats.is_running is False


def test_monorepo_workspace_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # 1. pnpm-workspace.yaml
        (repo / "pnpm-workspace.yaml").write_text("""
packages:
  - 'packages/*'
  - 'apps/*'
""")

        # 2. Package A: packages/ui
        ui_pkg = repo / "packages" / "ui"
        ui_pkg.mkdir(parents=True, exist_ok=True)
        (ui_pkg / "package.json").write_text("""{
  "name": "@acme/ui",
  "version": "1.0.0",
  "main": "src/index.ts"
}""")
        (ui_pkg / "src").mkdir()
        (ui_pkg / "src" / "index.ts").write_text("export const Button = () => null;")

        # 3. Package B: apps/web depending on Package A
        web_pkg = repo / "apps" / "web"
        web_pkg.mkdir(parents=True, exist_ok=True)
        (web_pkg / "package.json").write_text("""{
  "name": "@acme/web",
  "version": "1.0.0",
  "dependencies": {
    "@acme/ui": "workspace:*"
  }
}""")

        from codegraph.monorepo import discover_workspace
        ws = discover_workspace(repo)
        assert ws.workspace_type == "pnpm"
        assert len(ws.packages) == 2

        pkg_names = {p.name for p in ws.packages.values()}
        assert "@acme/ui" in pkg_names
        assert "@acme/web" in pkg_names

        # Cross-package dependency
        assert len(ws.dependencies) == 1
        dep = ws.dependencies[0]
        assert dep.source_name == "@acme/web"
        assert dep.target_name == "@acme/ui"


def test_api_contract_drift_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Backend FastAPI service defining GET /api/orders
        (src / "backend.py").write_text("""
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/orders")
def get_orders():
    return [{"id": 1}]
""")

        # 2. Frontend React calling:
        # - GET /api/orders (valid)
        # - POST /api/orders (method mismatch!)
        # - POST /api/unknown (orphaned client route!)
        (src / "App.tsx").write_text("""
import React from 'react';

export function OrderList() {
  fetch('/api/orders');
  fetch('/api/orders', { method: 'POST' });
  fetch('/api/unknown_billing_route', { method: 'POST' });
  return <div>Orders</div>;
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            drift_report = detect_api_contract_drift(con, repo)
            assert drift_report.has_drift is True

            drift_kinds = {d.kind for d in drift_report.drifts}
            assert "HTTP_METHOD_MISMATCH" in drift_kinds
            assert "ORPHANED_CLIENT_ROUTE" in drift_kinds

            # Verify specific message contents
            orphaned = [d for d in drift_report.drifts if d.kind == "ORPHANED_CLIENT_ROUTE"][0]
            assert "/api/unknown_billing_route" in orphaned.client_route

            mismatch = [d for d in drift_report.drifts if d.kind == "HTTP_METHOD_MISMATCH"][0]
            assert mismatch.client_method == "POST"
            assert "/api/orders" in mismatch.client_route


def test_mcp_server_new_production_tools():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        indexer = Indexer(repo)
        indexer.index()

        server = create_server(repo, profile="full")
        tools = server._tool_manager._tools

        # Verify all 5 new tools are registered in MCP
        assert "get_live_services" in tools
        assert "check_db_drift" in tools
        assert "get_distributed_trace" in tools
        assert "check_api_drift" in tools
        assert "get_monorepo_packages" in tools

        # Invoke them directly through tool manager
        live_res = tools["get_live_services"].fn()
        assert "live_services" in live_res
        assert "configured_services" in live_res

        drift_res = tools["check_db_drift"].fn()
        assert "is_drifted" in drift_res

        mono_res = tools["get_monorepo_packages"].fn()
        assert "package_count" in mono_res

        api_res = tools["check_api_drift"].fn()
        assert "has_drift" in api_res
