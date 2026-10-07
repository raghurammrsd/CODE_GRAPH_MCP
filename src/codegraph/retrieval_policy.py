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

_DB_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "MAPS_TO_TABLE",
    "MAPS_TO_COLUMN",
    "READS_TABLE",
    "WRITES_TABLE",
    "READS_COLUMN",
    "WRITES_COLUMN",
    "REFERENCES_TABLE",
    "REFERENCES_COLUMN",
    "FOREIGN_KEY_TO",
    "HAS_PRIMARY_KEY",
    "HAS_INDEX",
    "HAS_UNIQUE_CONSTRAINT",
    "HAS_CHECK_CONSTRAINT",
    "MIGRATES_TABLE",
    "QUERIES_DATABASE",
    "ORM_RELATION",
    "POSSIBLE_TABLE",
    "UNKNOWN_TABLE",
    "READS_ENV",
})

_ROBLOX_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "REQUIRES_MODULE",
    "CLIENT_DISPATCHES_REMOTE",
    "SERVER_HANDLES_REMOTE",
    "GETS_SERVICE",
    "PROVIDES_SERVICE",
    "READS_PERSISTENCE",
    "WRITES_PERSISTENCE",
    "CONFIGURES_PERSISTENCE",
})


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
    max_package_depth: int = 2
    preferred_target_types: tuple[str, ...] = ()
    required_dimensions: tuple[str, ...] = ("TARGET", "SERVICE", "TEST")

    def allows(self, relationship: str) -> bool:
        """Return True if the relationship type is permitted for this policy."""
        if not self.allowed_relationship_types:
            return True
        rel = relationship.upper()
        if (
            rel in self.allowed_relationship_types
            or rel in _DB_RELATIONSHIP_TYPES
            or rel in _ROBLOX_RELATIONSHIP_TYPES
        ):
            return True
        if rel.startswith("TESTS") and "TESTS" in self.allowed_relationship_types:
            return True
        return False


# ---------------------------------------------------------------------------
# Policy definitions
# ---------------------------------------------------------------------------

_POLICIES: dict[str, RetrievalPolicy] = {}


def _register(policy: RetrievalPolicy) -> None:
    _POLICIES[policy.intent.upper()] = policy


# TRACE — follow the full verified call/dispatch/DI/route chain
_register(RetrievalPolicy(
    intent="TRACE",
    allowed_relationship_types=frozenset({
        "HANDLED_BY", "ROUTE_HANDLER", "ROUTES_TO", "MOUNTS",
        "CALLS", "DISPATCHES_TO", "RESOLVES_DEPENDENCY", "INJECTS", "PROVIDES",
        "DEPENDS_ON", "IMPORTS", "TESTS", "POSSIBLE_CALLS",
        "DEFINES", "CONTAINS", "PARALLEL_IMPLEMENTATION",
        "DISPATCHES_TASK", "TRIGGERS_SIGNAL", "HANDLES_SIGNAL", "RENDERS_TEMPLATE",
        "DISPATCHES_FORWARD", "TOOL_HANDLER", "PIPELINE_STEP",
    }),
    preferred_flow=("ENTRYPOINT", "HANDLER", "SERVICE", "DATA", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=4,
    max_package_depth=2,
    preferred_target_types=("API_ENDPOINT", "FUNCTION", "METHOD", "CLASS"),
    required_dimensions=("TARGET", "ROUTE", "CALLER", "CALLEE", "PROVIDER", "TEST"),
))

# UNDERSTAND — explain structure, definitions, dependencies, package & route ownership
_register(RetrievalPolicy(
    intent="UNDERSTAND",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS", "PARALLEL_IMPLEMENTATION",
        "MOUNTS", "HANDLED_BY", "ROUTE_HANDLER",
        "REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER",
        "DISPATCHES_TASK", "TRIGGERS_SIGNAL", "HANDLES_SIGNAL", "RENDERS_TEMPLATE",
        "DISPATCHES_FORWARD", "TOOL_HANDLER", "PIPELINE_STEP",
        "INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY", "CONFIGURES",
        "DEPENDS_ON_PACKAGE", "TESTS",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "DEPENDENCIES", "CALLERS_CALLEES"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=2,
    max_package_depth=1,
    preferred_target_types=("CLASS", "FUNCTION", "MODULE"),
    required_dimensions=("TARGET", "CALLER", "CALLEE", "ROUTE", "PACKAGE", "TEST"),
))

# DEBUG — find callers, callees, error paths, registrations, DI, configuration, tests, unknowns
_register(RetrievalPolicy(
    intent="DEBUG",
    allowed_relationship_types=frozenset({
        "CALLS", "CALLED_BY", "DEPENDS_ON", "TESTS", "IMPORTS",
        "POSSIBLE_CALLS", "DEFINES", "PARALLEL_IMPLEMENTATION",
        "HANDLED_BY", "MOUNTS", "ROUTE_HANDLER",
        "REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER",
        "DISPATCHES_TASK", "TRIGGERS_SIGNAL", "HANDLES_SIGNAL", "RENDERS_TEMPLATE",
        "DISPATCHES_FORWARD", "TOOL_HANDLER", "PIPELINE_STEP",
        "INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY", "CONFIGURES",
        "DEPENDS_ON_PACKAGE",
    }),
    preferred_flow=("TARGET", "EXECUTION_PATH", "ERROR_PATH", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=3,
    max_package_depth=2,
    preferred_target_types=("FUNCTION", "METHOD", "CLASS"),
    required_dimensions=("TARGET", "CALLER", "CALLEE", "ROUTE", "REGISTRATION", "PROVIDER", "TEST"),
))

# IMPACT — what depends on, calls, or tests the target?
_register(RetrievalPolicy(
    intent="IMPACT",
    allowed_relationship_types=frozenset({
        "CALLED_BY", "DEPENDS_ON", "IMPLEMENTED_BY", "TESTS", "CALLS",
        "IMPORTS", "POSSIBLE_CALLS", "PROVIDES", "INJECTS",
        "HANDLED_BY", "MOUNTS", "REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER",
        "TASK_HANDLER", "COMMAND_HANDLER", "DEPENDS_ON_PACKAGE",
    }),
    preferred_flow=("TARGET", "CALLERS", "DEPENDENTS", "TEST"),
    include_callers=True,
    include_callees=False,
    include_tests=True,
    include_framework=False,
    max_graph_depth=3,
    max_package_depth=2,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD", "MODULE"),
    required_dimensions=("TARGET", "CALLER", "ROUTE", "PROVIDER", "TEST", "PACKAGE"),
))

# REVIEW — review changes; needs callers, callees, tests, and git context
_register(RetrievalPolicy(
    intent="REVIEW",
    allowed_relationship_types=frozenset({
        "CALLS", "CALLED_BY", "DEPENDS_ON", "TESTS", "IMPORTS", "POSSIBLE_CALLS",
        "HANDLED_BY", "INJECTS", "PROVIDES", "REGISTERS", "DEPENDS_ON_PACKAGE",
    }),
    preferred_flow=("TARGET", "HANDLER", "SERVICE", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_git=True,
    include_framework=True,
    max_graph_depth=2,
    max_package_depth=1,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
    required_dimensions=("TARGET", "CALLER", "CALLEE", "TEST", "GIT"),
))

# REFACTOR — similar to UNDERSTAND but emphasizes callers and tests
_register(RetrievalPolicy(
    intent="REFACTOR",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS", "PARALLEL_IMPLEMENTATION",
        "TESTS", "INJECTS", "PROVIDES", "DEPENDS_ON_PACKAGE",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "CALLERS_CALLEES", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=False,
    max_graph_depth=2,
    max_package_depth=1,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
    required_dimensions=("TARGET", "CALLER", "CALLEE", "TEST"),
))

# CHANGE — modify existing behavior; needs definition + callers + routes + providers + registrations + tests + packages
_register(RetrievalPolicy(
    intent="CHANGE",
    allowed_relationship_types=frozenset({
        "DEFINES", "CALLS", "CALLED_BY", "IMPORTS", "DEPENDS_ON", "TESTS",
        "POSSIBLE_CALLS", "PARALLEL_IMPLEMENTATION",
        "HANDLED_BY", "MOUNTS", "ROUTES_TO", "ROUTE_HANDLER",
        "REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER",
        "INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY", "CONFIGURES",
        "DEPENDS_ON_PACKAGE",
    }),
    preferred_flow=("TARGET", "HANDLER", "SERVICE", "DATA", "TEST"),
    include_callers=True,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    include_git=True,
    max_graph_depth=3,
    max_package_depth=2,
    preferred_target_types=("FUNCTION", "METHOD", "CLASS", "API_ENDPOINT"),
    required_dimensions=("TARGET", "CALLER", "ROUTE", "PROVIDER", "REGISTRATION", "TEST", "PACKAGE"),
))

# TEST — locate and contextualize test coverage, target implementation, provider/event/route relationships
_register(RetrievalPolicy(
    intent="TEST",
    allowed_relationship_types=frozenset({
        "TESTS", "CALLS", "DEPENDS_ON", "DEFINES", "IMPORTS",
        "HANDLED_BY", "MOUNTS", "ROUTE_HANDLER",
        "INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY",
        "REGISTERS", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER",
    }),
    preferred_flow=("TEST", "TARGET", "DEFINITIONS", "DEPENDENCIES"),
    include_callers=False,
    include_callees=True,
    include_tests=True,
    include_framework=True,
    max_graph_depth=2,
    max_package_depth=1,
    preferred_target_types=("TEST", "FUNCTION", "METHOD"),
    required_dimensions=("TEST", "TARGET", "PROVIDER", "ROUTE"),
))

# ARCHITECTURE — top-level module, package, route, and service relationships
_register(RetrievalPolicy(
    intent="ARCHITECTURE",
    allowed_relationship_types=frozenset({
        "IMPORTS", "DEPENDS_ON", "DEPENDS_ON_PACKAGE", "EXTERNAL_SERVICE",
        "ROUTES_TO", "HANDLED_BY", "MOUNTS",
        "DEFINES", "CONTAINS", "REGISTERS", "TASK_HANDLER", "COMMAND_HANDLER",
        "INJECTS", "PROVIDES", "CONFIGURES",
    }),
    preferred_flow=("ENTRYPOINT", "SERVICE", "DATA", "EXTERNAL"),
    include_callers=False,
    include_callees=False,
    include_tests=False,
    include_architecture=True,
    include_framework=True,
    max_graph_depth=1,
    max_package_depth=3,
    preferred_target_types=("MODULE", "API_ENDPOINT", "CLASS"),
    required_dimensions=("PACKAGE", "ENTRYPOINT", "SERVICE", "DATA"),
))

# EXPLAIN — like UNDERSTAND with full framework/route/package facts
_register(RetrievalPolicy(
    intent="EXPLAIN",
    allowed_relationship_types=frozenset({
        "DEFINES", "CONTAINS", "CALLS", "IMPORTS", "DEPENDS_ON",
        "HANDLED_BY", "ROUTES_TO", "MOUNTS", "ROUTE_HANDLER",
        "POSSIBLE_CALLS", "EXTENDS", "IMPLEMENTS",
        "PARALLEL_IMPLEMENTATION", "REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER",
        "TASK_HANDLER", "COMMAND_HANDLER",
        "INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY", "CONFIGURES",
        "DEPENDS_ON_PACKAGE", "TESTS",
    }),
    preferred_flow=("TARGET", "DEFINITIONS", "DEPENDENCIES", "CALLERS_CALLEES"),
    include_callers=True,
    include_callees=True,
    include_tests=False,
    include_framework=True,
    max_graph_depth=2,
    max_package_depth=1,
    preferred_target_types=("CLASS", "FUNCTION", "METHOD"),
    required_dimensions=("TARGET", "CALLER", "CALLEE", "ROUTE", "PACKAGE"),
))

# Default fallback (same as UNDERSTAND)
_DEFAULT_POLICY = _POLICIES["UNDERSTAND"]
RETRIEVAL_POLICIES: dict[str, RetrievalPolicy] = _POLICIES


def get_retrieval_policy(intent: str) -> RetrievalPolicy:
    """Return the RetrievalPolicy for the given intent string.

    Falls back to UNDERSTAND if the intent is not recognized.
    """
    return _POLICIES.get(intent.upper().strip(), _DEFAULT_POLICY)

