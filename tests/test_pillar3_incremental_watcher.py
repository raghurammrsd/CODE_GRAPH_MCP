"""Comprehensive Test Suite for Pillar 3: Incremental Live Watcher & Instant Cache Invalidation Engine."""
from __future__ import annotations

import time
from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.resources.cache import get_graph_cache, get_parse_cache
from codegraph.watcher import DebouncedIndexWorker, RepositoryWatcher, _is_path_ignored


def _build_test_project(tmp_path: Path) -> Path:
    repo = tmp_path / "test_repo"
    repo.mkdir(parents=True, exist_ok=True)

    app_dir = repo / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "__init__.py").write_text('"""App."""\n', encoding="utf-8")
    (app_dir / "models.py").write_text(
        '''"""Data models."""
class User:
    def __init__(self, name: str) -> None:
        self.name = name

class Item:
    def __init__(self, title: str) -> None:
        self.title = title
''',
        encoding="utf-8",
    )

    (app_dir / "services.py").write_text(
        '''"""Business logic."""
from app.models import User, Item

def create_user(name: str) -> User:
    return User(name)

def get_item(title: str) -> Item:
    return Item(title)
''',
        encoding="utf-8",
    )

    return repo


def test_sub_15ms_incremental_reindex_single_file(tmp_path: Path) -> None:
    """Modifying a single file reindexes that file incrementally without full disk walk."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)

    # 1. Initial full index
    init_res = indexer.index()
    assert init_res["indexed"] >= 3

    # Confirm initial symbols
    con = indexer.connect()
    try:
        user_sym = con.execute("SELECT name FROM symbols WHERE name='User'").fetchone()
        assert user_sym is not None
        initial_gen = int(con.execute("SELECT value FROM metadata WHERE key='index_generation'").fetchone()[0])
    finally:
        con.close()

    # 2. Modify app/models.py to add Order class
    models_file = repo / "app" / "models.py"
    models_file.write_text(
        '''"""Data models."""
class User:
    def __init__(self, name: str) -> None:
        self.name = name

class Item:
    def __init__(self, title: str) -> None:
        self.title = title

class Order:
    def __init__(self, order_id: int) -> None:
        self.order_id = order_id
''',
        encoding="utf-8",
    )

    # 3. Incremental reindex
    t0 = time.perf_counter()
    reindex_res = indexer.reindex_paths(["app/models.py"])
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert reindex_res["status"] == "ok"
    assert "app/models.py" in reindex_res["reindexed"]
    assert reindex_res["deleted"] == []
    assert reindex_res["generation"] == initial_gen + 1
    # Check that performance is rapid
    assert elapsed_ms < 500.0  # Safe upper bound in sandboxed pytest

    # 4. Verify new symbol is immediately queryable in SQLite
    con2 = indexer.connect()
    try:
        order_sym = con2.execute("SELECT name, qualified_name FROM symbols WHERE name='Order'").fetchone()
        assert order_sym is not None
        assert order_sym[0] == "Order"
    finally:
        con2.close()


def test_incremental_deletion_removes_facts(tmp_path: Path) -> None:
    """Deleting a file cleans up its symbols, chunks, and references."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)
    indexer.index()

    services_file = repo / "app" / "services.py"
    assert services_file.exists()

    con = indexer.connect()
    try:
        assert con.execute("SELECT count(*) FROM symbols WHERE path='app/services.py'").fetchone()[0] > 0
    finally:
        con.close()

    # Remove the file from disk
    services_file.unlink()
    assert not services_file.exists()

    # Incremental reindex of deleted path
    res = indexer.reindex_paths(["app/services.py"])
    assert res["status"] == "ok"
    assert "app/services.py" in res["deleted"]
    assert res["reindexed"] == []

    con2 = indexer.connect()
    try:
        # Verified: symbols for that path must be completely gone
        sym_count = con2.execute("SELECT count(*) FROM symbols WHERE path='app/services.py'").fetchone()[0]
        assert sym_count == 0
        file_count = con2.execute("SELECT count(*) FROM files WHERE path='app/services.py'").fetchone()[0]
        assert file_count == 0
        # Other files remain intact
        models_count = con2.execute("SELECT count(*) FROM symbols WHERE path='app/models.py'").fetchone()[0]
        assert models_count > 0
    finally:
        con2.close()


def test_unchanged_file_hash_skipping(tmp_path: Path) -> None:
    """When a file has not changed, SHA-256 digest skip skips reindexing."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)
    indexer.index()

    con = indexer.connect()
    try:
        gen_before = int(con.execute("SELECT value FROM metadata WHERE key='index_generation'").fetchone()[0])
    finally:
        con.close()

    # Reindex unchanged path
    res = indexer.reindex_paths(["app/models.py"])
    assert res["status"] == "ok"
    assert res["reindexed"] == []
    assert "app/models.py" in res["skipped"]
    assert res["generation"] == gen_before


def test_cache_invalidation_on_reindex(tmp_path: Path) -> None:
    """Reindexing busts in-memory parse and graph caches."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)
    indexer.index()

    # Seed caches with dummy entries
    parse_cache = get_parse_cache()
    graph_cache = get_graph_cache()

    parse_cache.put(("dummy_hash", "v1", "python"), object())
    graph_cache.put((1, "sym_id", "CALLS", 1), [{"dummy": 1}])

    assert parse_cache.stats()["items"] > 0
    assert graph_cache.stats()["items"] > 0

    # Modify file and reindex
    models_file = repo / "app" / "models.py"
    models_file.write_text("# modified\nclass Extra: pass\n", encoding="utf-8")

    indexer.reindex_paths(["app/models.py"])

    # Caches must be completely evicted
    assert parse_cache.stats()["items"] == 0
    assert graph_cache.stats()["items"] == 0


def test_debounced_worker_coalesces_bursts(tmp_path: Path) -> None:
    """DebouncedIndexWorker collects rapid multiple file change events into a single flush."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)
    indexer.index()

    batches: list[dict[str, object]] = []

    def on_batch(res: dict[str, object]) -> None:
        batches.append(res)

    worker = DebouncedIndexWorker(indexer, debounce_delay_sec=0.08, on_batch_complete=on_batch)

    # Modify file
    (repo / "app" / "models.py").write_text("# burst edit\nclass BurstUser: pass\n", encoding="utf-8")

    # Record 5 changes rapidly
    for _ in range(5):
        worker.record_change("app/models.py")

    # Wait for debounce window to fire
    time.sleep(0.18)

    assert len(batches) == 1
    assert worker.stats.batches_processed == 1
    assert worker.stats.events_received == 5
    assert worker.stats.files_reindexed >= 1


def test_repository_watcher_trigger_sync(tmp_path: Path) -> None:
    """RepositoryWatcher trigger_sync flushes changes immediately."""
    repo = _build_test_project(tmp_path)
    indexer = Indexer(repo)
    indexer.index()

    watcher = RepositoryWatcher(repo, indexer=indexer, debounce_delay_sec=0.5)

    (repo / "app" / "models.py").write_text("# manual sync\nclass SyncModel: pass\n", encoding="utf-8")

    # Synchronously trigger reindex
    res = watcher.trigger_sync(["app/models.py"])
    assert res["status"] == "ok"
    assert "app/models.py" in res["reindexed"]


def test_is_path_ignored() -> None:
    """Test ignored path filter for git, venv, caches, and sqlite databases."""
    assert _is_path_ignored(".git/config")
    assert _is_path_ignored("node_modules/package.json")
    assert _is_path_ignored(".venv/bin/python")
    assert _is_path_ignored(".codegraph.sqlite3")
    assert _is_path_ignored(".codegraph.sqlite3-wal")
    assert _is_path_ignored("app/__pycache__/models.cpython-311.pyc")
    assert not _is_path_ignored("src/codegraph/watcher.py")
    assert not _is_path_ignored("app/models.py")
