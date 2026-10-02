import tempfile
from pathlib import Path

from codegraph.architecture import detect_frameworks, get_architecture
from codegraph.config import Settings
from codegraph.indexing import Indexer


def test_detect_frameworks_from_ast_import_without_manifest():
    """Test that concrete import like 'from flask import Flask' detects flask even without requirements.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src = root / "src"
        src.mkdir()

        (src / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            fws = detect_frameworks(con, root)
            assert "flask" in fws

            arch = get_architecture(con, root)
            assert "flask" in arch.get("frameworks", [])


def test_detect_frameworks_from_nested_manifest():
    """Test that a requirements.txt in a subdirectory (e.g. refactored-output/requirements.txt) is detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        sub = root / "refactored-output"
        sub.mkdir()
        (sub / "requirements.txt").write_text("flask==3.0.0\nrequests>=2.28\n", encoding="utf-8")

        src = root / "src"
        src.mkdir()
        (src / "util.py").write_text("def ping(): return True\n", encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            fws = detect_frameworks(con, root)
            assert "flask" in fws


def test_no_false_positive_frameworks():
    """Test that a plain Python repo with no framework imports or manifests does not report frameworks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src = root / "src"
        src.mkdir()
        (src / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            fws = detect_frameworks(con, root)
            assert fws == []
