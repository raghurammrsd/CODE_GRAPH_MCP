from __future__ import annotations

import hashlib
from pathlib import Path

from codegraph.evidence.citations import Evidence, verify_evidence
from codegraph.indexing import Indexer


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "service.py").write_text(
        "class AuthService:\n"
        "    def authenticate(self, user: str, token: str) -> bool:\n"
        "        return user == 'admin' and token == 'secret'\n"
        "\n"
        "    def logout(self, user: str) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    indexer = Indexer(repo)
    indexer.index()
    return repo


def test_verify_evidence_fresh(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    file_content = (repo / "service.py").read_bytes()
    expected_hash = hashlib.sha256(file_content).hexdigest()

    indexer = Indexer(repo)
    with indexer.session() as con:
        ev = Evidence(
            file="service.py",
            start_line=1,
            end_line=3,
            symbol="AuthService.authenticate",
            snippet="def authenticate(self, user: str, token: str) -> bool:",
        )
        report = verify_evidence(con, repo, ev, expected_content_hash=expected_hash)
        assert report.valid is True
        assert report.exists is True
        assert report.hash_matches is True
        assert report.lines_valid is True
        assert report.status == "FACT"
        assert report.confidence == "HIGH"
        assert report.freshness == "FRESH"


def test_verify_evidence_modified_hash(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    old_hash = hashlib.sha256((repo / "service.py").read_bytes()).hexdigest()

    # Modify file on disk without re-indexing
    (repo / "service.py").write_text(
        "class AuthService:\n"
        "    def authenticate(self, user: str, token: str) -> bool:\n"
        "        # modified implementation\n"
        "        return False\n",
        encoding="utf-8",
    )

    indexer = Indexer(repo)
    with indexer.session() as con:
        ev = Evidence(
            file="service.py",
            start_line=1,
            end_line=3,
            symbol="AuthService.authenticate",
            snippet="",
        )
        report = verify_evidence(con, repo, ev, expected_content_hash=old_hash)
        assert report.valid is False
        assert report.hash_matches is False
        assert report.status == "CONFLICT"
        assert report.freshness == "STALE"
        assert "hash mismatch" in report.reason.lower()


def test_verify_evidence_nonexistent_file(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    indexer = Indexer(repo)
    with indexer.session() as con:
        ev = Evidence(
            file="nonexistent.py",
            start_line=1,
            end_line=5,
            symbol="missing",
            snippet="",
        )
        report = verify_evidence(con, repo, ev)
        assert report.valid is False
        assert report.exists is False
        assert report.status == "UNKNOWN"
        assert "not found" in report.reason.lower()


def test_verify_evidence_invalid_line_range(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    indexer = Indexer(repo)
    with indexer.session() as con:
        # start > end
        ev1 = Evidence(
            file="service.py",
            start_line=10,
            end_line=3,
            symbol=None,
            snippet="",
        )
        report1 = verify_evidence(con, repo, ev1)
        assert report1.valid is False
        assert report1.lines_valid is False
        assert report1.status == "CONFLICT"

        # end line exceeds file total
        ev2 = Evidence(
            file="service.py",
            start_line=1,
            end_line=999,
            symbol=None,
            snippet="",
        )
        report2 = verify_evidence(con, repo, ev2)
        assert report2.valid is False
        assert report2.lines_valid is False


def test_verify_evidence_path_traversal(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    indexer = Indexer(repo)
    with indexer.session() as con:
        ev = Evidence(
            file="../../etc/passwd",
            start_line=1,
            end_line=5,
            symbol=None,
            snippet="",
        )
        report = verify_evidence(con, repo, ev)
        assert report.valid is False
        assert report.status == "UNKNOWN"
        assert "boundary" in report.reason.lower() or "error" in report.reason.lower()
