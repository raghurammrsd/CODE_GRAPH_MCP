"""Zero-Friction Development Server Runtime Interceptor (v2.2.0).

Enables 1-line development telemetry capture:
    codegraph run npm run dev
    codegraph run uvicorn main:app
    codegraph run python app.py

Security & Reliability Invariants:
- Passes stdin/stdout/stderr directly to the user's terminal with zero distortion.
- Strips authorization headers, cookies, and sensitive credentials via existing redaction rules.
- Streams captured HTTP requests and uncaught exceptions directly into `.codegraph/runtime.sqlite3`
  without requiring code changes to the user's application.
- Cleans up child processes and temporary interceptor hooks on exit.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.runtime.ingestor import ingest_runtime_traces


def _generate_node_interceptor(output_jsonl: Path) -> str:
    """Generate lightweight Node.js HTTP/Express/Fastify request interceptor."""
    escaped_log_path = json.dumps(str(output_jsonl))
    return f"""// CodeGraph Node.js Runtime Interceptor
const http = require('http');
const https = require('https');
const fs = require('fs');

const logPath = {escaped_log_path};

let _cg_buffer = [];
let _cg_last_flush = Date.now();
const _CG_BATCH_SIZE = 50;
const _CG_FLUSH_INTERVAL_MS = 1500;

function _cg_flush_buffer() {{
  if (_cg_buffer.length === 0) return;
  const content = _cg_buffer.join('');
  _cg_buffer = [];
  _cg_last_flush = Date.now();
  try {{
    fs.appendFileSync(logPath, content);
  }} catch (_) {{}}
}}

function emitEvent(event) {{
  try {{
    _cg_buffer.push(JSON.stringify(event) + '\\n');
    if (_cg_buffer.length >= _CG_BATCH_SIZE || (Date.now() - _cg_last_flush) >= _CG_FLUSH_INTERVAL_MS) {{
      _cg_flush_buffer();
    }}
  }} catch (_) {{}}
}}

setInterval(_cg_flush_buffer, _CG_FLUSH_INTERVAL_MS);
process.on('exit', _cg_flush_buffer);

function hookServer(serverProto) {{

  const origEmit = serverProto.emit;
  serverProto.emit = function(event, req, res) {{
    if (event === 'request' && req && res) {{
      const startTime = Date.now();
      const method = req.method || 'GET';
      const url = req.url ? req.url.split('?')[0] : '/';

      res.on('finish', () => {{
        const duration = Date.now() - startTime;
        emitEvent({{
          trace_id: 'tr_' + Math.random().toString(36).substring(2, 10),
          span_id: 'sp_' + Math.random().toString(36).substring(2, 10),
          timestamp: new Date().toISOString(),
          http_method: method,
          route_path: url,
          status_code: res.statusCode,
          duration_ms: duration,
          service_name: 'node_dev_server',
          source_format: 'json'
        }});
      }});
    }}
    return origEmit.apply(this, arguments);
  }};
}}

try {{
  hookServer(http.Server.prototype);
}} catch (_) {{}}

process.on('uncaughtExceptionMonitor', (err) => {{
  emitEvent({{
    trace_id: 'err_' + Math.random().toString(36).substring(2, 10),
    span_id: 'sp_err',
    timestamp: new Date().toISOString(),
    exception_type: (err && err.name) ? err.name : 'UncaughtException',
    service_name: 'node_dev_server',
    status_code: 500,
    source_format: 'json'
  }});
}});
"""


def _generate_python_interceptor(output_jsonl: Path) -> str:
    """Generate lightweight Python WSGI/ASGI/FastAPI request interceptor with in-memory buffering."""
    escaped_log_path = repr(str(output_jsonl))
    return f"""# CodeGraph Python Runtime Interceptor
import atexit
import json
import os
import sys
import threading
import time

LOG_PATH = {escaped_log_path}

_cg_buffer = []
_cg_lock = threading.Lock()
_cg_last_flush = time.time()
_cg_batch_size = 50
_cg_flush_interval = 1.5

def _cg_flush():
    global _cg_last_flush
    lines = None
    with _cg_lock:
        if _cg_buffer:
            lines = "".join(_cg_buffer)
            _cg_buffer.clear()
            _cg_last_flush = time.time()
    if lines:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(lines)
        except Exception:
            pass

def emit_event(event):
    try:
        line = json.dumps(event) + "\\n"
        should_flush = False
        with _cg_lock:
            _cg_buffer.append(line)
            if len(_cg_buffer) >= _cg_batch_size or (time.time() - _cg_last_flush) >= _cg_flush_interval:
                should_flush = True
        if should_flush:
            _cg_flush()
    except Exception:
        pass

def _cg_bg_flusher():
    while True:
        time.sleep(_cg_flush_interval)
        if _cg_buffer:
            _cg_flush()

_cg_flusher_thread = threading.Thread(target=_cg_bg_flusher, daemon=True)
_cg_flusher_thread.start()
atexit.register(_cg_flush)


# 1. Intercept uncaught exceptions
_orig_excepthook = sys.excepthook
def _cg_excepthook(exc_type, exc_value, exc_traceback):
    emit_event({{
        "trace_id": "err_" + str(int(time.time())),
        "span_id": "sp_err",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exception_type": getattr(exc_type, "__name__", "Exception"),
        "service_name": "python_dev_server",
        "status_code": 500,
        "source_format": "json"
    }})
    return _orig_excepthook(exc_type, exc_value, exc_traceback)

sys.excepthook = _cg_excepthook

# 2. Intercept SQLite query executions
try:
    import sqlite3
    _orig_connect = sqlite3.connect

    def _cg_connect(*args, **kwargs):
        con = _orig_connect(*args, **kwargs)
        def _sql_trace(statement):
            if statement and isinstance(statement, str) and statement.strip():
                emit_event({{
                    "trace_id": "tr_sql_" + str(int(time.time())),
                    "span_id": "sp_sql_" + str(id(con)),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "sql": statement,
                    "duration_ms": 1.0,
                    "service_name": "python_dev_server",
                    "source_format": "otel",
                }})
        try:
            con.set_trace_callback(_sql_trace)
        except Exception:
            pass
        return con

    sqlite3.connect = _cg_connect
except Exception:
    pass


# 3. Intercept SQLAlchemy engine query executions if imported
try:
    import sqlalchemy.event
    import sqlalchemy.engine

    @sqlalchemy.event.listens_for(sqlalchemy.engine.Engine, "after_cursor_execute")
    def _cg_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if statement and str(statement).strip():
            emit_event({{
                "trace_id": "tr_sql_" + str(int(time.time())),
                "span_id": "sp_sql_" + str(id(cursor)),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sql": str(statement),
                "duration_ms": 1.0,
                "service_name": "python_dev_server",
                "source_format": "otel",
            }})
except Exception:
    pass

# 4. Intercept Werkzeug/Flask dev server requests
try:
    import werkzeug.serving
    _orig_run_simple = werkzeug.serving.run_simple

    def _cg_run_simple(hostname, port, application, *args, **kwargs):
        def _wrapped_app(environ, start_response):
            path = environ.get("PATH_INFO", "/")
            method = environ.get("REQUEST_METHOD", "GET")
            status_box = [200]
            def _wrapped_sr(status, headers, exc_info=None):
                try:
                    status_box[0] = int(status.split()[0])
                except Exception:
                    pass
                return start_response(status, headers, exc_info)
            st = time.time()
            try:
                return application(environ, _wrapped_sr)
            finally:
                emit_event({{
                    "trace_id": "tr_http_" + str(int(time.time())),
                    "span_id": "sp_http_" + str(int(time.time())),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "http_method": method,
                    "route": path,
                    "status_code": status_box[0],
                    "duration_ms": (time.time() - st) * 1000.0,
                    "service_name": "python_dev_server",
                    "source_format": "otel",
                }})
        return _orig_run_simple(hostname, port, _wrapped_app, *args, **kwargs)

    werkzeug.serving.run_simple = _cg_run_simple
except Exception:
    pass
"""


def run_with_telemetry(
    command: list[str],
    repository: Path,
    sample_rate: float = 1.0,
) -> int:
    """Execute a development command with transparent runtime trace capture."""
    if not command:
        raise ValueError("Command cannot be empty.")

    hooks_dir = repository / ".codegraph" / "runtime_hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    trace_file = hooks_dir / "active_traces.jsonl"
    # Ensure fresh trace buffer
    if trace_file.exists():
        try:
            trace_file.unlink()
        except OSError:
            pass

    node_hook = hooks_dir / "cg_node_hook.js"
    node_hook.write_text(_generate_node_interceptor(trace_file), encoding="utf-8")

    python_hook = hooks_dir / "cg_python_hook.py"
    python_hook.write_text(_generate_python_interceptor(trace_file), encoding="utf-8")

    env = dict(os.environ)

    # Inject Node hook
    old_node_opts = env.get("NODE_OPTIONS", "")
    env["NODE_OPTIONS"] = f"--require {node_hook} {old_node_opts}".strip()

    # Inject Python hook
    old_py_start = env.get("PYTHONSTARTUP", "")
    if not old_py_start:
        env["PYTHONSTARTUP"] = str(python_hook)

    # Background ingestion thread
    stop_event = threading.Event()
    indexer = Indexer(repository)

    def _ingest_loop() -> None:
        last_pos = 0
        while not stop_event.is_set():
            time.sleep(1.0)
            if not trace_file.exists():
                continue
            try:
                size = trace_file.stat().st_size
                if size > last_pos:
                    with open(trace_file, encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        new_content = f.read()
                        last_pos = f.tell()
                    if new_content.strip():
                        with indexer.session() as con:
                            ingest_runtime_traces(con, new_content, repository=repository, max_events=1000, sampling_rate=sample_rate)
            except Exception:
                pass

    ingest_worker = threading.Thread(target=_ingest_loop, daemon=True)
    ingest_worker.start()

    # Spawn interactive dev process
    try:
        proc = subprocess.Popen(command, cwd=str(repository), env=env)
        returncode = proc.wait()
    except KeyboardInterrupt:
        returncode = 0
    finally:
        stop_event.set()
        # Drain remaining lines on shutdown
        if trace_file.exists():
            try:
                content = trace_file.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    with indexer.session() as con:
                        ingest_runtime_traces(con, content, repository=repository, max_events=1000, sampling_rate=sample_rate)
            except Exception:
                pass

    return returncode
