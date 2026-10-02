"""Tests for TaskSpec and task understanding contract."""

from codegraph.planner import compute_task_spec_hash
from codegraph.task import (
    AmbiguityCandidate,
    AmbiguityStatus,
    TaskAmbiguity,
    TaskIntent,
    TaskSpec,
    canonicalize_intent,
)


def test_task_spec_creation_and_defaults() -> None:
    spec = TaskSpec(raw_prompt="Trace login authentication flow", goal="Trace login flow")
    assert spec.raw_prompt == "Trace login authentication flow"
    assert spec.intent == TaskIntent.UNDERSTAND.value
    assert spec.confidence == "HIGH"
    assert isinstance(spec.targets, tuple)
    assert isinstance(spec.constraints, tuple)


def test_task_spec_as_dict() -> None:
    spec = TaskSpec(
        raw_prompt="Fix 401 error in UserService.authenticate",
        intent=TaskIntent.DEBUG.value,
        goal="Fix 401 error in UserService.authenticate",
        targets=("UserService.authenticate",),
        scope_paths=("src/auth/service.py",),
        constraints=("NO_MOCK",),
    )
    d = spec.as_dict()
    assert d["raw_prompt"] == spec.raw_prompt
    assert d["intent"] == "DEBUG"
    assert d["targets"] == ("UserService.authenticate",)
    assert d["scope_paths"] == ("src/auth/service.py",)
    assert d["constraints"] == ("NO_MOCK",)


def test_task_spec_hash_determinism() -> None:
    spec1 = TaskSpec(
        goal="Explain repository architecture",
        intent=TaskIntent.ARCHITECTURE.value,
        targets=("core",),
    )
    spec2 = TaskSpec(
        goal="Explain repository architecture",
        intent=TaskIntent.ARCHITECTURE.value,
        targets=("core",),
    )
    h1 = compute_task_spec_hash(spec1)
    h2 = compute_task_spec_hash(spec2)
    assert h1 == h2

    # Changing target changes hash
    spec3 = TaskSpec(
        goal="Explain repository architecture",
        intent=TaskIntent.ARCHITECTURE.value,
        targets=("network",),
    )
    h3 = compute_task_spec_hash(spec3)
    assert h1 != h3


def test_ambiguity_candidate_and_status() -> None:
    candidate = AmbiguityCandidate(
        canonical_id="src/auth.py::login",
        name="login",
        path="src/auth.py",
        kind="function",
        confidence="HIGH",
        reason="exact symbol match",
    )
    d = candidate.as_dict()
    assert d["canonical_id"] == "src/auth.py::login"
    assert d["name"] == "login"
    assert d["path"] == "src/auth.py"

    ambiguity = TaskAmbiguity(
        status=AmbiguityStatus.AMBIGUOUS,
        target="login",
        candidates=(candidate,),
        assumption="Assumed primary entry point",
    )
    ad = ambiguity.as_dict()
    assert ad["status"] == "AMBIGUOUS"
    assert ad["target"] == "login"
    assert len(ad["candidates"]) == 1
    assert ad["assumption"] == "Assumed primary entry point"


def test_canonicalize_intent() -> None:
    assert canonicalize_intent("troubleshoot") == TaskIntent.DEBUG
    assert canonicalize_intent("callgraph") == TaskIntent.TRACE
    assert canonicalize_intent("modify") == TaskIntent.CHANGE
    assert canonicalize_intent("overview") == TaskIntent.ARCHITECTURE
    assert canonicalize_intent("unknown_thing") == TaskIntent.UNDERSTAND
