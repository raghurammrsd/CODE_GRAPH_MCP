"""Intent-specific retrieval policies for CodeGraph MCP v2.1.

Each policy defines:
  - Allowed relationship types (graph edges that may participate)
  - Preferred coverage layers (ordered)
  - Traversal flags (callers, callees, tests, git, framework, architecture)
  - Maximum graph depth

Downstream retrieval MUST filter graph candidates to allowed_relationship_types.
This prevents unrelated relationships from polluting context merely because
they exist in the graph.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalPolicy:
    intent: str
    allowed_relationship_types: frozenset[str]
    preferred_flow: tuple[str, ...]
    include_callers: bool = True
    include_callees: bool = True
    include_tests: bool = True
    include_git: bool = False
    include_framework: bool = True
    include_architecture: bool = False
    max_graph_depth: int = 3
    preferred_target_types: tuple[str, ...] = ()

    def allows(self, relationship: str) -> bool:
        """Return True if the relationship type is permitted for this policy."""
        if not self.allowed_relationship_types:
            return True
        return relationship.upper() in self.allowed_relationship_types


# ---------------------------------------------------------------------------
# Policy definitions
# ---------------------------------------------------------------------------

_POLICIES: dict[str, RetrievalPolicy] = {}


def _register(policy: RetrievalPolicy) -> None:
    _POLICIES[policy.intent.upper()] = policy


# TRACE — follow the full call chain from endpoint to data layer
_register(RetrievalPolicy(
    intent="TRACE",
    allowed_relationship_types=frozenset({
        "HANDLED_BY", "ROUTES_TO", "CALLS", "DEPENDS_ON", "IMPORTS", "TESTS",
        "POSSIBLE_CALLS", "DEFINES", "CONTAINS", "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("ENTRYPOINT", "HANDLER", "SERVICE", "DATA", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=4,
    preferred_target_types=("API_ENDPOINT", "FUNCTION", "METHOD", "CLASS"),
))

# UNDERSTAND — explain structure, definitions, dependencies
_register(RetrievalPolicy(
    intent="UNDERSTAND",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS", "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "DEPENDENCIES", "CALLERS_CALLEES"),
    include_callers=True,
    include_callees=True,
    include_tests=False,
    include_framework=True,
    max_graph_depth=2,
    preferred_target_types=("CLASS", "FUNCTION", "MODULE"),
))

# DEBUG — find callers, callees, error paths, tests
_register(RetrievalPolicy(
    intent="DEBUG",
    allowed_relationship_types=frozenset({
        "CALLS", "CALLED_BY", "DEPENDS_ON", "TESTS", "IMPORTS",
        "POSSIBLE_CALLS", "DEFINES", "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("TARGET", "EXECUTION_PATH", "ERROR_PATH", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=3,
    preferred_target_types=("FUNCTION", "METHOD", "CLASS"),
))

# IMPACT — what depends on, calls, or tests the target?
_register(RetrievalPolicy(
    intent="IMPACT",
    allowed_relationship_types=frozenset({
        "CALLED_BY", "DEPENDS_ON", "IMPLEMENTED_BY", "TESTS", "CALLS",
        "IMPORTS", "POSSIBLE_CALLS",
    }),
    preferred_flow=("TARGET", "CALLERS", "DEPENDENTS", "TEST"),
    include_callers=True,
    include_callees=False,
    include_tests=True,
    include_framework=False,
    max_graph_depth=3,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD", "MODULE"),
))

# REVIEW — review changes; needs callers, callees, tests, and git context
_register(RetrievalPolicy(
    intent="REVIEW",
    allowed_relationship_types=frozenset({
        "CALLS", "CALLED_BY", "DEPENDS_ON", "TESTS", "IMPORTS", "POSSIBLE_CALLS",
    }),
    preferred_flow=("TARGET", "HANDLER", "SERVICE", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_git=True,
    include_framework=True,
    max_graph_depth=2,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
))

# REFACTOR — similar to UNDERSTAND but emphasizes callers and tests
_register(RetrievalPolicy(
    intent="REFACTOR",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS", "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "CALLERS_CALLEES", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=False,
    max_graph_depth=2,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
))

# CHANGE — modify existing behavior; needs definition + callers + tests
_register(RetrievalPolicy(
    intent="CHANGE",
    allowed_relationship_types=frozenset({
        "DEFINES", "CALLS", "CALLED_BY", "IMPORTS", "DEPENDS_ON", "TESTS",
        "POSSIBLE_CALLS", "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("TARGET", "HANDLER", "SERVICE", "DATA", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=3,
    preferred_target_types=("FUNCTION", "METHOD", "CLASS", "API_ENDPOINT"),
))

# TEST — locate and contextualize test coverage
_register(RetrievalPolicy(
    intent="TEST",
    allowed_relationship_types=frozenset({
        "TESTS", "CALLS", "DEPENDS_ON", "DEFINES", "IMPORTS",
    }),
    preferred_flow=("TEST", "TARGET", "DEFINITIONS", "DEPENDENCIES"),
    include_callers=False,
    include_callees=True,
    include_tests=True,
    include_framework=False,
    max_graph_depth=2,
    preferred_target_types=("TEST", "FUNCTION", "METHOD"),
))

# ARCHITECTURE — top-level module and service relationships
_register(RetrievalPolicy(
    intent="ARCHITECTURE",
    allowed_relationship_types=frozenset({
        "IMPORTS", "DEPENDS_ON", "EXTERNAL_SERVICE", "ROUTES_TO",
        "DEFINES", "CONTAINS",
    }),
    preferred_flow=("ENTRYPOINT", "SERVICE", "DATA", "EXTERNAL"),
    include_callers=False,
    include_callees=False,
    include_tests=False,
    include_architecture=True,
    include_framework=True,
    max_graph_depth=1,
    preferred_target_types=("MODULE", "API_ENDPOINT", "CLASS"),
))

# EXPLAIN — like UNDERSTAND but includes framework/route facts
_register(RetrievalPolicy(
    intent="EXPLAIN",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "HANDLED_BY", "ROUTES_TO", "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS",
        "PARALLEL_IMPLEMENTATION",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "DEPENDENCIES", "CALLERS_CALLEES"),
    include_callers=True,
    include_callees=True,
    include_tests=False,
    include_framework=True,
    max_graph_depth=2,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
))

# Default fallback (same as UNDERSTAND)
_DEFAULT_POLICY = _POLICIES["UNDERSTAND"]


def get_retrieval_policy(intent: str) -> RetrievalPolicy:
    """Return the RetrievalPolicy for the given intent string.

    Falls back to UNDERSTAND if the intent is not recognized.
    """
    return _POLICIES.get(intent.upper().strip(), _DEFAULT_POLICY)
