"""Standardized Benchmark Task Model and Ground Truth Specifications."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class BenchmarkCategory(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    DEBUG = "DEBUG"
    TRACE = "TRACE"
    CHANGE = "CHANGE"
    IMPACT = "IMPACT"
    REVIEW = "REVIEW"
    REFACTOR = "REFACTOR"
    TEST = "TEST"
    ARCHITECTURE = "ARCHITECTURE"
    EXPLAIN = "EXPLAIN"


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    repository_id: str

    intent: str
    prompt: str

    expected_entry_points: tuple[str, ...] = ()
    expected_symbols: tuple[str, ...] = ()
    expected_relationships: tuple[tuple[str, str, str], ...] = ()
    expected_tests: tuple[str, ...] = ()

    allowed_files: tuple[str, ...] = ()
    excluded_files: tuple[str, ...] = ()
    excluded_symbols: tuple[str, ...] = ()

    expected_unknowns: tuple[str, ...] = ()
    expected_ambiguities: tuple[str, ...] = ()

    expected_path_nodes: tuple[str, ...] = ()  # e.g. (endpoint, handler, service, model)
    category: str = BenchmarkCategory.UNDERSTAND.value
    max_context_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["expected_relationships"] = [list(r) for r in self.expected_relationships]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkTask:
        raw_rels = data.get("expected_relationships", ())
        rels = tuple(
            tuple(r) if isinstance(r, (list, tuple)) and len(r) == 3 else (str(r), "", "")
            for r in raw_rels
        )
        return cls(
            task_id=str(data["task_id"]),
            repository_id=str(data.get("repository_id", "default")),
            intent=str(data.get("intent", "UNDERSTAND")),
            prompt=str(data.get("prompt", "")),
            expected_entry_points=tuple(data.get("expected_entry_points", ())),
            expected_symbols=tuple(data.get("expected_symbols", ())),
            expected_relationships=rels,
            expected_tests=tuple(data.get("expected_tests", ())),
            allowed_files=tuple(data.get("allowed_files", ())),
            excluded_files=tuple(data.get("excluded_files", ())),
            excluded_symbols=tuple(data.get("excluded_symbols", ())),
            expected_unknowns=tuple(data.get("expected_unknowns", ())),
            expected_ambiguities=tuple(data.get("expected_ambiguities", ())),
            expected_path_nodes=tuple(data.get("expected_path_nodes", ())),
            category=str(data.get("category", data.get("intent", "UNDERSTAND"))),
            max_context_tokens=data.get("max_context_tokens"),
            metadata=dict(data.get("metadata", {})),
        )
