"""Tests for deterministic task normalization and keyword/target extraction."""

from codegraph.task import (
    TaskIntent,
    extract_keywords_from_prompt,
    normalize_task_spec,
)


def test_normalize_intent_detection() -> None:
    # DEBUG
    s_debug, _ = normalize_task_spec("Fix the 500 error in login endpoint")
    assert s_debug.intent in (TaskIntent.DEBUG.value, TaskIntent.CHANGE.value)

    # UNDERSTAND
    s_understand, _ = normalize_task_spec("How does the token cache work?")
    assert s_understand.intent == TaskIntent.UNDERSTAND.value

    # CHANGE
    s_change, _ = normalize_task_spec("Modify user profile update endpoint")
    assert s_change.intent == TaskIntent.CHANGE.value

    # REFACTOR
    s_refactor, _ = normalize_task_spec("Clean up and refactor database connection pooling")
    assert s_refactor.intent == TaskIntent.REFACTOR.value

    # TRACE
    s_trace, _ = normalize_task_spec("Trace request execution from router down to SQL query")
    assert s_trace.intent == TaskIntent.TRACE.value

    # IMPACT
    s_impact, _ = normalize_task_spec("What is the blast radius and impact if I modify AuthService.login?")
    assert s_impact.intent == TaskIntent.IMPACT.value

    # REVIEW
    s_review, _ = normalize_task_spec("Review the recent changes in authentication")
    assert s_review.intent == TaskIntent.REVIEW.value

    # TEST
    s_test, _ = normalize_task_spec("Find all tests covering payment gateway")
    assert s_test.intent == TaskIntent.TEST.value

    # ARCHITECTURE
    s_arch, _ = normalize_task_spec("What is the high-level architecture overview?")
    assert s_arch.intent == TaskIntent.ARCHITECTURE.value


def test_target_extraction_from_prompt() -> None:
    kw = extract_keywords_from_prompt("Please inspect 'UserService.validate_token' and src/auth/jwt.py")
    assert "UserService.validate_token" in kw
    assert any("jwt.py" in k for k in kw)


def test_target_extraction_from_identifiers() -> None:
    kw = extract_keywords_from_prompt("Refactor DatabaseSessionManager to support async transactions")
    assert "DatabaseSessionManager" in kw


def test_normalize_with_constraints_and_operations() -> None:
    spec, ambiguities = normalize_task_spec("Trace auth flow, do not modify files, check recent changes")
    assert "READ_ONLY" in spec.constraints
    assert "TRACE" in spec.operations
    assert "INSPECT_RECENT_CHANGES" in spec.operations
    assert spec.time_scope == "RECENT_CHANGES"


def test_normalize_dict_input() -> None:
    d = {
        "task": "Fix token validation bug",
        "intent": "debug",
        "targets": ["TokenValidator.validate"],
        "constraints": ["NO_NETWORK"],
    }
    spec, _ = normalize_task_spec(d)
    assert spec.intent == TaskIntent.DEBUG.value
    assert "TokenValidator.validate" in spec.targets
    assert "NO_NETWORK" in spec.constraints
