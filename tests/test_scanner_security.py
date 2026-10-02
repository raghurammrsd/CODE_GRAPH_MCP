from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.errors import SecurityError
from codegraph.indexing.scanner import scan_with_stats
from codegraph.security import is_sensitive, safe_path


def test_safe_path_fail_closed_on_path_traversal(tmp_path: Path) -> None:
    """Verify safe_path strictly blocks directory traversal escapes."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("print('hello')")

    # Inside repo is allowed
    assert safe_path(root, "main.py") == (root / "main.py").resolve()

    # Traversal escaping root must raise SecurityError
    with pytest.raises(SecurityError, match="path escapes"):
        safe_path(root, "../outside.py")

    with pytest.raises(SecurityError, match="path escapes"):
        safe_path(root, "sub/../../outside.py")


def test_safe_path_fail_closed_on_external_symlink(tmp_path: Path) -> None:
    """Verify safe_path raises SecurityError on symlinks pointing outside the repository."""
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("SUPER_SECRET_TOKEN")

    symlink_path = root / "link_to_secret.py"
    try:
        symlink_path.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation not supported in this environment")

    with pytest.raises(SecurityError, match="path escapes"):
        safe_path(root, "link_to_secret.py")


def test_scanner_gracefully_skips_external_symlinks_without_crashing(tmp_path: Path) -> None:
    """Verify scanner catches SecurityError on escaping symlinks, records stats, and continues."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def run(): return 1")

    outside_dir = tmp_path / "outside_store"
    outside_dir.mkdir()
    outside_file = outside_dir / "external_leak.py"
    outside_file.write_text("def leaked(): pass")

    bad_symlink = root / "bad_link.py"
    try:
        bad_symlink.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symlink creation not supported in this environment")

    results, stats = scan_with_stats(root, max_file_size=100_000)

    # Scanned valid file
    accepted_files = {r.relative_path.as_posix() for r in results}
    assert "service.py" in accepted_files
    assert "bad_link.py" not in accepted_files

    # Security skip recorded
    assert stats.skipped_security >= 1
    assert stats.accepted == 1


def test_scanner_skips_secrets_and_gitignore(tmp_path: Path) -> None:
    """Verify scanner excludes sensitive files and respect .gitignore rules."""
    root = tmp_path / "repo"
    root.mkdir()

    (root / "app.py").write_text("print('app')")
    (root / ".env").write_text("API_KEY=12345")
    (root / "id_rsa").write_text("PRIVATE KEY")
    (root / ".gitignore").write_text("ignored_module.py\n*.tmp\n")
    (root / "ignored_module.py").write_text("def ignored(): pass")

    results, stats = scan_with_stats(root, max_file_size=100_000)

    accepted_files = {r.relative_path.as_posix() for r in results}
    assert "app.py" in accepted_files
    assert ".env" not in accepted_files
    assert "id_rsa" not in accepted_files
    assert "ignored_module.py" not in accepted_files

    assert stats.skipped_secret >= 2
    assert stats.skipped_ignored >= 1


def test_is_sensitive_patterns() -> None:
    """Verify sensitive pattern recognition for credentials, keys, and tokens."""
    assert is_sensitive(Path(".env"))
    assert is_sensitive(Path(".env.production"))
    assert is_sensitive(Path("id_rsa"))
    assert is_sensitive(Path("server.pem"))
    assert is_sensitive(Path("credentials.json"))
    assert not is_sensitive(Path("main.py"))
    assert not is_sensitive(Path("src/auth/service.py"))
