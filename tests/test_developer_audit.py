from __future__ import annotations

from pathlib import Path

from codegraph.context import get_context
from codegraph.epistemic import (
    ConfidenceLevel,
    EpistemicStatus,
    FreshnessLevel,
    assumption,
    conflict,
    fact,
    inference,
    unknown,
)
from codegraph.indexing import Indexer


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "audit_repo"
    repo.mkdir()
    (repo / "service.py").write_text(
        "class AuthService:\n"
        "    def authenticate(self, user: str, token: str) -> bool:\n"
        "        return user == 'admin'\n"
        "\n"
        "    def logout(self, user: str) -> None:\n"
        "        pass\n"
        "\n"
        "class TokenService:\n"
        "    def issue_token(self, user: str) -> str:\n"
        "        return 'tok-123'\n",
        encoding="utf-8",
    )
    (repo / "extra.py").write_text(
        "# Low relevance utility functions\n"
        "def helper_one(): pass\n"
        "def helper_two(): pass\n",
        encoding="utf-8",
    )
    indexer = Indexer(repo)
    indexer.index()
    return repo


def test_epistemic_constructs() -> None:
    assert EpistemicStatus.FACT.value == "FACT"
    assert EpistemicStatus.ASSUMPTION.value == "ASSUMPTION"
    assert EpistemicStatus.INFERENCE.value == "INFERENCE"
    assert EpistemicStatus.UNKNOWN.value == "UNKNOWN"
    assert EpistemicStatus.CONFLICT.value == "CONFLICT"

    assert ConfidenceLevel.HIGH.value == "HIGH"
    assert FreshnessLevel.FRESH.value == "FRESH"

    f = fact("Service exists", file="service.py")
    assert f.status == EpistemicStatus.FACT
    assert f.confidence == "HIGH"

    a = assumption("User is authenticated")
    assert a.status == EpistemicStatus.ASSUMPTION

    inf = inference("Likely called by auth controller")
    assert inf.status == EpistemicStatus.INFERENCE

    u = unknown("Missing route definition")
    assert u.status == EpistemicStatus.UNKNOWN

    c = conflict("Source hash mismatch")
    assert c.status == EpistemicStatus.CONFLICT


def test_context_explain_mode_rejections(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    indexer = Indexer(repo)

    with indexer.session() as con:
        # Request context with tight token budget and explain=True
        packet = get_context(
            con,
            repo,
            task="Explain AuthService authenticate",
            max_tokens=200,  # Very small budget to induce rejections
            explain=True,
        )

        assert packet.execution is not None
        assert "rejections" in packet.execution
        assert "retrieval_plan" in packet.execution

        rejections = packet.execution["rejections"]
        assert isinstance(rejections, list)
        if rejections:
            first_rej = rejections[0]
            assert "file" in first_rej
            assert "reason" in first_rej
            assert "relevance" in first_rej
            assert isinstance(first_rej["reason"], str)
