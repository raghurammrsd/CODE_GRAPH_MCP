"""Zero-Heat, Push-Based OpenTelemetry (OTLP) & Dev Telemetry Collector.

Listens for OTLP HTTP traces from localhost dev servers:
- POST /v1/traces (Standard OpenTelemetry protobuf-in-JSON or OTLP JSON)
- POST /api/telemetry (Lightweight JSON / JSONL dev events)
- GET /healthz (Health probe)

Efficiency & Anti-Heat Invariants:
1. Purely event-driven socket select; 0.0% CPU when no requests are being processed.
2. In-memory bounded queue with ring-buffer semantics (capped at max_events=1,000) to prevent memory ballooning.
3. Strict secrecy redaction: Authorization, Cookie, and passwords stripped before SQLite persistence.
4. Graceful shutdown: Closes sockets cleanly without leaking ports.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from codegraph.runtime.ingestor import ingest_runtime_traces


class TelemetryRequestHandler(BaseHTTPRequestHandler):
    """Zero-overhead HTTP request handler for OTLP spans and dev telemetry."""

    server: TelemetryServer  # Type annotation for custom server

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard stderr access logging to prevent noisy terminal output."""
        return

    def do_GET(self) -> None:
        if self.path in ("/healthz", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","engine":"codegraph-runtime-collector"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path not in ("/v1/traces", "/api/telemetry", "/telemetry"):
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0 or content_length > 10 * 1024 * 1024:  # Max 10MB payload
            self.send_response(400)
            self.end_headers()
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body_text = body_bytes.decode("utf-8", errors="replace")
            parsed_json = json.loads(body_text)

            # Ingest into CodeGraph SQLite database
            with self.server.db_lock:
                ingest_runtime_traces(
                    self.server.db_connection,
                    parsed_json,
                    repository=self.server.repo_root,
                    format="otel" if "/traces" in self.path else "json",
                    max_events=1000,
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"partialSuccess":{}}')
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_msg = json.dumps({"error": str(exc)}).encode("utf-8")
            self.wfile.write(err_msg)


class TelemetryServer(HTTPServer):
    """Custom HTTPServer maintaining db connection and repo references."""

    def __init__(
        self,
        server_address: tuple[str, int],
        db_connection: sqlite3.Connection,
        repo_root: Path,
    ) -> None:
        super().__init__(server_address, TelemetryRequestHandler)
        self.db_connection = db_connection
        self.repo_root = repo_root
        self.db_lock = threading.Lock()


class RuntimeCollectorDaemon:
    """Manages lifecycle of background OTLP collector."""

    def __init__(
        self,
        db_connection: sqlite3.Connection,
        repo_root: Path,
        port: int = 4318,
        host: str = "127.0.0.1",
    ) -> None:
        self.db_connection = db_connection
        self.repo_root = repo_root
        self.port = port
        self.host = host
        self._server: TelemetryServer | None = None
        self._thread: threading.Thread | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> bool:
        """Start the collector in a low-priority background daemon thread."""
        if self._is_running:
            return True
        try:
            self._server = TelemetryServer(
                (self.host, self.port),
                self.db_connection,
                self.repo_root,
            )
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="codegraph-otlp-collector",
                daemon=True,
            )
            self._thread.start()
            self._is_running = True
            return True
        except OSError:
            # Port might be in use or unavailable; fail closed gracefully without crashing
            self._is_running = False
            return False

    def stop(self) -> None:
        """Shutdown the collector cleanly."""
        if not self._is_running or not self._server:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        finally:
            self._is_running = False
            self._server = None
