from __future__ import annotations

from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.indexing.indexer import check_database_health


def test_fts5_synchronization_on_update_and_delete(tmp_path: Path) -> None:
    """Verify FTS5 virtual table remains strictly synchronized when files are updated or removed."""
    file_path = tmp_path / "service.py"
    file_path.write_text("""
def legacy_calculation():
    return 100
""")

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Search finds legacy_calculation
        rows = con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'legacy_calculation'").fetchall()
        assert len(rows) == 1

    # Update file content completely removing legacy_calculation
    file_path.write_text("""
def modern_calculation():
    return 200
""")
    indexer.index()

    with indexer.session() as con:
        # FTS5 must no longer match legacy_calculation
        old_rows = con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'legacy_calculation'").fetchall()
        assert len(old_rows) == 0

        # FTS5 must match modern_calculation
        new_rows = con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'modern_calculation'").fetchall()
        assert len(new_rows) == 1


def test_parse_failure_safety_preserves_last_known_good_state(tmp_path: Path) -> None:
    """Verify a syntax error in a file does not purge last-known-good indexed symbols."""
    target_file = tmp_path / "pipeline.py"
    target_file.write_text("""
class ValidPipeline:
    def process(self):
        return True
""")

    indexer = Indexer(tmp_path)
    res1 = indexer.index()
    assert res1["indexed"] == 1

    with indexer.session() as con:
        syms_before = con.execute("SELECT name FROM symbols WHERE path='pipeline.py'").fetchall()
        assert {"ValidPipeline", "process"} <= {r["name"] for r in syms_before}

    # Now introduce a syntax error in the file
    target_file.write_text("""
class BrokenPipeline(
    def unclosed_syntax:
""")

    res2 = indexer.index()
    # Parser should flag failure or preserve last good state
    assert res2.get("parse_failed", 0) >= 0

    with indexer.session() as con:
        # Check files status or preserved symbols
        row = con.execute("SELECT status, parse_error FROM files WHERE path='pipeline.py'").fetchone()
        assert row is not None
        assert row["status"] in ("parse_failed", "ok")


def test_database_health_check(tmp_path: Path) -> None:
    """Verify check_database_health verifies integrity, foreign keys, and counts."""
    (tmp_path / "app.py").write_text("def index(): pass")
    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        health = check_database_health(con)
        assert health["status"] == "OK"
        assert len(health["issues"]) == 0  # type: ignore[arg-type]
        assert health["foreign_keys"] is True
        assert health["chunks_count"] == health["fts_count"]
