import asyncio
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

from codegraph.indexing import Indexer, SQLiteConnectionPool
from codegraph.mcp import create_server
from codegraph.runtime.runner import _generate_python_interceptor


def test_sqlite_connection_pool_concurrency_and_reentrancy(tmp_path: Path) -> None:
    """Test that SQLiteConnectionPool handles concurrent threads and re-entrant sessions safely."""
    db_file = tmp_path / "test.db"
    pool = SQLiteConnectionPool(db_file, max_size=5)

    # Initial table setup
    con, owner = pool.acquire()
    con.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, val INTEGER)")
    con.execute("INSERT INTO counter VALUES (1, 0)")
    pool.release(con, owner)

    def worker(i: int) -> int:
        # Re-entrant acquisition in the same thread
        c1, owner1 = pool.acquire()
        try:
            c2, owner2 = pool.acquire()
            assert c2 is c1, "Same thread must reuse active connection"
            assert not owner2, "Nested acquisition must not own transaction"
            pool.release(c2, owner2)

            row = c1.execute("SELECT val FROM counter WHERE id = 1").fetchone()
            val = int(row[0])
            return val
        finally:
            pool.release(c1, owner1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(worker, range(30)))

    assert len(results) == 30
    pool.close_all()


def test_indexer_session_thread_safety_and_reset(tmp_path: Path) -> None:
    """Test Indexer.session() using the connection pool across concurrent worker threads."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def run_job():\n    return 42\n")
    indexer = Indexer(repo)
    indexer.index()

    def query_symbols(i: int) -> int:
        with indexer.session() as con:
            count = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
            return int(count)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(query_symbols, range(20)))

    assert all(r == 1 for r in results)

    # Verify reset_pool
    indexer.reset_pool()
    with indexer.session() as con:
        assert con.execute("SELECT count(*) FROM symbols").fetchone()[0] == 1
    indexer.close()


def test_fastmcp_async_event_loop_concurrency(tmp_path: Path) -> None:
    """Test that FastMCP tools run asynchronously on anyio threadpool without blocking the event loop."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for i in range(5):
        (repo / f"service_{i}.py").write_text(f"def serve_{i}():\n    return {i}\n")
    indexer = Indexer(repo)
    indexer.index()

    server = create_server(repo, profile="agent")

    async def _run() -> None:
        async def call_worker(sym: str) -> bool:
            content, _ = await server.call_tool("find_symbol", {"symbol": sym})
            return len(content) > 0

        tasks = [call_worker(f"serve_{i % 5}") for i in range(15)]
        t0 = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0

        assert all(results)
        # 15 concurrent calls should finish in parallel rapidly
        assert elapsed < 5.0

    asyncio.run(_run())


def test_runtime_python_interceptor_batch_buffering(tmp_path: Path) -> None:
    """Test that Python runtime interceptor buffers events in memory and flushes cleanly on exit."""
    trace_file = tmp_path / "traces.jsonl"
    interceptor_code = _generate_python_interceptor(trace_file)

    script_file = tmp_path / "test_app.py"
    # Write a script that emits 65 events quickly (crossing batch threshold of 50)
    app_body = """
import sqlite3
con = sqlite3.connect(":memory:")
cur = con.cursor()
for i in range(65):
    cur.execute("SELECT " + str(i))
"""
    script_file.write_text(interceptor_code + app_body)

    result = subprocess.run([sys.executable, str(script_file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    assert trace_file.exists()
    lines = [line.strip() for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 65, f"Expected at least 65 trace lines, got {len(lines)}"

    # Check that events have valid JSON structure
    ev = json.loads(lines[0])
    assert "sql" in ev
    assert "duration_ms" in ev
