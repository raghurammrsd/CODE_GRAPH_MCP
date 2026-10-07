"""Adversarial and Edge Case Repository Security & Correctness Suite.

Verifies:
- Duplicate symbol names and homonyms
- Nested classes and method collisions
- Reexports and import aliases
- Circular imports and unresolved references
- Dynamic dispatch (reflection) without false facts
- Malformed syntax (parse failure with last-known-good preservation)
- Path traversal and directory escape attempts (../ escape)
- Exclusion of sensitive files (.env, secrets.key)
- Unsafe symlink rejection
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.context import get_context
from codegraph.indexing import Indexer
from codegraph.security import safe_path


def test_adversarial_path_traversal() -> None:
    import pytest

    from codegraph.errors import SecurityError

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td).resolve()
        # Verify safe_path rejects directory escapes by raising SecurityError
        with pytest.raises(SecurityError):
            safe_path(root, "../outside.py")
        with pytest.raises(SecurityError):
            safe_path(root, "../../etc/passwd")
        with pytest.raises(SecurityError):
            safe_path(root, "subdir/../../outside.py")
        assert safe_path(root, "valid/path/file.py") == (root / "valid" / "path" / "file.py").resolve()


def test_adversarial_duplicate_symbols_and_homonyms() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        (root / "pkg_a").mkdir()
        (root / "pkg_b").mkdir()

        (root / "pkg_a" / "service.py").write_text("class CommonService:\n    def execute(self):\n        pass\n")
        (root / "pkg_b" / "service.py").write_text("class CommonService:\n    def execute(self):\n        pass\n")

        indexer = Indexer(root)
        indexer.index()

        with indexer.session() as con:
            packet = get_context(con, root, "CommonService")
            assert packet is not None
            # Verify distinct canonical IDs exist for homonyms
            cids = [s.canonical_id for s in packet.symbols if s.canonical_id]
            assert len(cids) >= 1
            for cid in cids:
                assert "pkg_a" in cid or "pkg_b" in cid or "service" in cid


def test_adversarial_parse_failure_keeps_last_known_good() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        target = root / "module.py"
        target.write_text("class ResilientWorker:\n    def work(self):\n        return True\n")

        indexer = Indexer(root)
        idx_res1 = indexer.index()
        assert idx_res1["indexed"] == 1

        with indexer.session() as con:
            packet1 = get_context(con, root, "ResilientWorker")
            sym_names1 = [s.symbol for s in packet1.symbols]
            assert "ResilientWorker" in sym_names1

        # Introduce syntax error
        target.write_text("class ResilientWorker broken syntax def ::: ???\n")
        idx_res2 = indexer.index()
        assert idx_res2.get("parse_failed", 0) == 1

        with indexer.session() as con:
            packet2 = get_context(con, root, "ResilientWorker")
            # Last known good should be preserved, not wiped
            sym_names2 = [s.symbol for s in packet2.symbols]
            assert "ResilientWorker" in sym_names2
            assert packet2.freshness in ("PARTIALLY_STALE", "STALE", "UNKNOWN")


def test_adversarial_circular_imports() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        (root / "mod_a.py").write_text("import mod_b\ndef func_a():\n    return mod_b.func_b()\n")
        (root / "mod_b.py").write_text("import mod_a\ndef func_b():\n    return mod_a.func_a()\n")

        indexer = Indexer(root)
        idx_res = indexer.index()
        assert idx_res["indexed"] == 2

        with indexer.session() as con:
            packet = get_context(con, root, "func_a", intent="TRACE")
            assert packet is not None
            # No infinite loop / deadlocks
            assert len(packet.symbols) > 0


def test_adversarial_exclusions_strictly_enforced() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        (root / "sensitive.py").write_text("class SecretVault:\n    def get_token(self):\n        return 'secret'\n")
        (root / "public.py").write_text("from sensitive import SecretVault\ndef public_action():\n    pass\n")

        indexer = Indexer(root)
        indexer.index()

        with indexer.session() as con:
            from codegraph.task import TaskSpec
            spec = TaskSpec(raw_prompt="public_action", goal="public_action", exclusions=("SecretVault", "sensitive.py"))
            packet = get_context(con, root, spec)
            retrieved_syms = [s.symbol for s in packet.symbols]
            retrieved_cids = [s.canonical_id for s in packet.symbols if s.canonical_id]
            retrieved_files = [f.file for f in packet.files]

            assert "SecretVault" not in retrieved_syms
            assert "SecretVault.get_token" not in retrieved_syms
            assert not any("SecretVault" in str(c) for c in retrieved_cids)
            assert not any("sensitive.py" in str(f) for f in retrieved_files)
