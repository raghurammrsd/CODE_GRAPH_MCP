"""Deterministic Agent Capability Registry, Task Classification & Tool-Selection Policy.

Solves:
- Deterministic agent task classification (13 canonical categories)
- Complete 39-tool capability registry derived from actual MCP server schemas
- Capability matrix mapping task categories to CodeGraph MCP tools
- Tool-selection policy with explicit evidence guarantees and limitations
- Machine-readable capability manifest (`get_capability_manifest()`)
- Safe fallback policy preserving epistemic states (`UNKNOWN`, `POSSIBLE`, `AMBIGUOUS`)

Invariants:
- Never claim CodeGraph will always be used; AI agents retain tool-selection autonomy.
- For trivial single-file edits (`LOCAL_EDIT`), direct file inspection is preferred.
- `UNKNOWN` from CodeGraph means "static analysis could not establish the relationship",
  NEVER "there is no relationship".
- `POSSIBLE` means a plausible static candidate that requires targeted source verification.
- Output is 100% deterministic with zero environment-specific absolute paths.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from codegraph import __version__


class AgentTaskCategory(StrEnum):
    """Canonical agent task categories for tool-selection routing."""

    LOCAL_EDIT = "LOCAL_EDIT"
    SYMBOL_LOOKUP = "SYMBOL_LOOKUP"
    RELATIONSHIP = "RELATIONSHIP"
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    CHANGE_IMPACT = "CHANGE_IMPACT"
    TEST_DISCOVERY = "TEST_DISCOVERY"
    ROUTE_DISCOVERY = "ROUTE_DISCOVERY"
    DIAGNOSTIC = "DIAGNOSTIC"
    ARCHITECTURE = "ARCHITECTURE"
    PACKAGE = "PACKAGE"
    MULTI_FILE_INVESTIGATION = "MULTI_FILE_INVESTIGATION"
    EXPLANATION = "EXPLANATION"


@dataclass(frozen=True)
class ToolCapabilitySpec:
    """Declarative specification for a single CodeGraph MCP tool."""

    tool_name: str
    capability: str
    description: str
    task_types: tuple[str, ...]
    required_inputs: tuple[str, ...]
    expected_output_type: str
    relationship_types_returned: tuple[str, ...]
    evidence_guarantees: str
    does_not_prove: str
    useful_situations: tuple[str, ...]
    avoid_when: tuple[str, ...]
    profiles: tuple[str, ...]
    optional_inputs: tuple[str, ...] = ()
    minimal_invocation: str = ""
    advanced_invocation: str = ""
    result_fields: tuple[str, ...] = ()
    typical_followup: str = ""
    common_mistakes: tuple[str, ...] = ()
    example_request: str = ""
    example_call: str = ""
    example_interpretation: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "capability": self.capability,
            "description": self.description,
            "task_types": list(self.task_types),
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "expected_output_type": self.expected_output_type,
            "relationship_types_returned": list(self.relationship_types_returned),
            "evidence_guarantees": self.evidence_guarantees,
            "does_not_prove": self.does_not_prove,
            "useful_situations": list(self.useful_situations),
            "avoid_when": list(self.avoid_when),
            "profiles": list(self.profiles),
            "minimal_invocation": self.minimal_invocation,
            "advanced_invocation": self.advanced_invocation,
            "result_fields": list(self.result_fields),
            "typical_followup": self.typical_followup,
            "common_mistakes": list(self.common_mistakes),
            "example_request": self.example_request,
            "example_call": self.example_call,
            "example_interpretation": self.example_interpretation,
        }


@dataclass(frozen=True)
class TaskCapabilityRule:
    """Capability matrix entry mapping a task category to recommended CodeGraph usage."""

    category: AgentTaskCategory
    should_use_codegraph: bool
    primary_tool: str | None
    acceptable_tools: tuple[str, ...]
    recommended_sequence: tuple[str, ...]
    direct_inspection_acceptable: bool
    rationale: str

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "should_use_codegraph": self.should_use_codegraph,
            "primary_tool": self.primary_tool,
            "acceptable_tools": list(self.acceptable_tools),
            "recommended_sequence": list(self.recommended_sequence),
            "direct_inspection_acceptable": self.direct_inspection_acceptable,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Explicit Agent Routing Manifest & Default Agent Profile (Phases 3 & 7)
# ---------------------------------------------------------------------------

ROUTING_MANIFEST: dict[str, str] = {
    "symbol_discovery": "find_symbol",
    "literal_search": "search_code",
    "caller_discovery": "find_callers",
    "callee_discovery": "find_callees",
    "reference_discovery": "find_references",
    "route_discovery": "find_routes",
    "test_discovery": "find_tests",
    "source_inspection": "get_file",
    "context_synthesis": "get_context",
    "architecture_analysis": "get_architecture",
    "relationship_trace": "trace_path",
    "change_impact": "get_git_impact",
    "db_tables": "find_db_tables",
    "db_columns": "find_db_columns",
    "db_models": "find_db_models",
    "db_queries": "find_db_queries",
    "db_callers": "find_db_callers",
    "db_writers": "find_db_writers",
    "db_readers": "find_db_readers",
    "db_relationships": "find_db_relationships",
    "db_table_details": "get_db_table",
    "db_schema": "get_db_schema",
    "db_impact": "get_db_impact",
    "runtime_ingest": "ingest_runtime_traces",
    "runtime_trace": "get_runtime_trace",
    "runtime_reconcile": "reconcile_static_runtime",
    "git_state": "get_git_state",
    "git_diff": "compare_git",
    "change_impact_deep": "get_change_impact",
    "context_freshness": "check_context_freshness",
    "symbol_history": "trace_symbol_history",
    "semantic_conflicts": "detect_semantic_conflicts",
    "safe_rename": "safe_rename",
    "rollback_refactor": "rollback_refactor",
}

DEFAULT_AGENT_PROFILE_TOOLS: tuple[str, ...] = (
    # DISCOVERY (7)
    "find_symbol",
    "search_code",
    "find_references",
    "find_callers",
    "find_callees",
    "find_tests",
    "find_routes",
    # DETAILS (5)
    "get_symbol",
    "get_file",
    "get_context",
    "get_architecture",
    "get_git_impact",
    # GRAPH (2)
    "trace_path",
    "trace_flow",
)


# ---------------------------------------------------------------------------
# Canonical Tool Registry (All 42 Exposed MCP Tools)
# ---------------------------------------------------------------------------

TOOL_CAPABILITY_REGISTRY: tuple[ToolCapabilitySpec, ...] = (
    # 1. resolve_symbol
    ToolCapabilitySpec(
        tool_name="resolve_symbol",
        capability="symbol_resolution",
        description=(
            "Resolve a symbol name, qualified name, canonical ID, or route into its canonical repository identity and file/line location. "
            "Use as the first step before relationship queries when exact symbol identity is unknown or potentially ambiguous. "
            "Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). "
            "Returns canonical_id, ambiguity_state, and candidate alternatives. "
            "Does not prove runtime execution or dynamic monkey-patching."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TRACE.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "name"),
        expected_output_type="SymbolResolutionResult",
        relationship_types_returned=("DEFINES", "RESOLVES_TO"),
        evidence_guarantees="AST-verified symbol definition coordinates and explicit AMBIGUOUS/UNKNOWN states.",
        does_not_prove="Does not prove runtime call edges or dynamic attribute injection.",
        useful_situations=(
            "Locating where a class, function, or method is canonically defined",
            "Disambiguating homonymous symbols across multiple modules or packages",
            "Grounding a symbol name into a canonical_id before calling get_callers or trace_path",
        ),
        avoid_when=(
            "Purely local single-file text edit where the file and line are already open",
            "Repeatedly resolving the same canonical_id already returned in the current session",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='resolve_symbol(symbol="AuthService")',
        advanced_invocation='resolve_symbol(symbol="src.auth.service.AuthService.authenticate")',
        result_fields=("status", "canonical_id", "qualified_name", "file", "start_line", "end_line", "ambiguity_state", "matches", "alternatives"),
        typical_followup="get_callers, get_callees, get_references, trace_path, or get_context",
        common_mistakes=(
            "Calling resolve_symbol repeatedly in a loop for the same symbol",
            "Choosing matches[0] blindly when ambiguity_state is AMBIGUOUS",
        ),
        example_request="Where is AuthService defined?",
        example_call='resolve_symbol(symbol="AuthService")',
        example_interpretation="Inspect canonical_id, file, and start_line..end_line; if ambiguity_state == 'AMBIGUOUS', compare alternatives by module/package.",
    ),
    # 2. search_symbols
    ToolCapabilitySpec(
        tool_name="search_symbols",
        capability="symbol_discovery",
        description=(
            "Search indexed repository symbols by partial name or keyword with ranked relevance. "
            "Use when exact symbol spelling is unknown and you need candidate symbol definitions. "
            "Returns ranked symbol definitions with file paths and line spans. "
            "Does not return module import graphs or call relationships."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("query",),
        optional_inputs=("top_k",),
        expected_output_type="SymbolSearchResult",
        relationship_types_returned=("DEFINES",),
        evidence_guarantees="AST-extracted symbol declarations with source file and line numbers.",
        does_not_prove="Does not prove who calls or imports the matched symbols.",
        useful_situations=(
            "Finding where a feature or domain concept is defined across the codebase",
            "Discovering candidate symbols before calling resolve_symbol or get_context",
        ),
        avoid_when=(
            "Discovering module imports or reverse dependencies (use get_imports or get_dependents instead)",
            "Editing a single known file locally",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='search_symbols(query="authenticate")',
        advanced_invocation='search_symbols(query="token validator", top_k=10)',
        result_fields=("status", "query", "results", "canonical_id", "qualified_name", "kind", "file", "start_line", "end_line"),
        typical_followup="resolve_symbol or get_context",
        common_mistakes=(
            "Treating lexical symbol search matches as proof of causal call relationships",
            "Using search_symbols to check module imports instead of get_imports",
        ),
        example_request="Find symbols related to password verification.",
        example_call='search_symbols(query="verify_password", top_k=10)',
        example_interpretation="Select the matching symbol definition and pass its symbol or canonical_id to get_callers or get_context.",
    ),
    # 3. get_symbol
    ToolCapabilitySpec(
        tool_name="get_symbol",
        capability="symbol_inspection",
        description=(
            "Return authoritative signature, kind, parent scope, decorators, and bounded source snippet for a symbol. "
            "Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). "
            "Use when you have a symbol name or canonical_id and need its declaration metadata. "
            "Does not traverse multi-hop call graphs."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "name"),
        expected_output_type="SymbolDetailResult",
        relationship_types_returned=("DEFINES", "CONTAINS"),
        evidence_guarantees="AST-verified symbol signature, decorators, and exact line span.",
        does_not_prove="Does not prove downstream impact or callers outside the symbol body.",
        useful_situations=(
            "Inspecting a symbol's signature, return type, and decorators without reading the entire file",
        ),
        avoid_when=(
            "Tracing multi-hop execution flows (use trace_path or get_context instead)",
        ),
        profiles=("agent", "core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_symbol(symbol="AuthService.authenticate")',
        advanced_invocation='get_symbol(canonical_id="src/auth/service.py:AuthService.authenticate")',
        result_fields=("status", "canonical_id", "qualified_name", "kind", "signature", "decorators", "file", "start_line", "end_line", "snippet"),
        typical_followup="get_file (if full method body beyond snippet is needed) or find_callees",
        common_mistakes=(
            "Calling get_symbol when multi-file callers/callees are needed (use find_callers or get_context)",
        ),
        example_request="What is the exact signature and decorator list of login_endpoint?",
        example_call='get_symbol(symbol="login_endpoint")',
        example_interpretation="Read signature, decorators, and start_line..end_line from the returned declaration record.",
    ),
    # 4. get_file
    ToolCapabilitySpec(
        tool_name="get_file",
        capability="file_structure_inspection",
        description=(
            "Open and inspect a repository file's structural AST outline or a bounded line range (`path`, `start_line`, `end_line`, `max_lines`). "
            "Use after `search_code`, `find_symbol`, or `find_routes` identifies a target file and line span across Python, HTML, Jinja, JS, TS, CSS, YAML, JSON, or Markdown. "
            "Blocks path traversal, binary files, and sensitive files; does not prove cross-file callers."
        ),
        task_types=(
            AgentTaskCategory.LOCAL_EDIT.value,
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("path",),
        optional_inputs=("start_line", "end_line", "max_lines", "include_content"),
        expected_output_type="FileStructureResult",
        relationship_types_returned=("DEFINES", "IMPORTS"),
        evidence_guarantees="Bounded on-disk source lines (`start_line`..`end_line`, `truncated`) plus parser-extracted symbols and imports.",
        does_not_prove="Does not prove reverse dependents across the repository.",
        useful_situations=(
            "Opening a targeted line range (`start_line`, `end_line`) of a Python, HTML, Jinja, JS, CSS, or config file",
            "Reviewing the symbols and imports inside a module before editing",
        ),
        avoid_when=(
            "Reading an entire huge file without `start_line`/`end_line` bounds",
        ),
        profiles=("agent", "core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_file(path="src/auth/service.py", start_line=1, end_line=80)',
        advanced_invocation='get_file(path="templates/dashboard.html", start_line=40, end_line=110, max_lines=200)',
        result_fields=("status", "path", "file", "start_line", "end_line", "content", "truncated", "category", "file_category", "artifact_type", "symbols", "imports", "freshness"),
        typical_followup="perform targeted code edit or call find_callers/find_callees on discovered symbols",
        common_mistakes=(
            "Setting include_content=True on huge files instead of passing start_line and end_line",
        ),
        example_request="Show lines 40 to 110 of templates/dashboard.html.",
        example_call='get_file(path="templates/dashboard.html", start_line=40, end_line=110)',
        example_interpretation="Inspect `content`, `start_line`, `end_line`, and `truncated` for the requested file range.",
    ),
    # 5. get_references
    ToolCapabilitySpec(
        tool_name="get_references",
        capability="reference_relationship",
        description=(
            "Return verified and candidate references to a symbol across the repository with evidence_class labels. "
            "Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). "
            "Use for cross-file reference, registration, dispatch, or DI binding lookup. "
            "Does not guarantee dynamic reflection targets when evidence_class is UNKNOWN or POSSIBLE."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "name"),
        expected_output_type="ReferenceListResult",
        relationship_types_returned=(
            "CALLS",
            "IMPORTS",
            "REGISTERS",
            "DISPATCHES_TO",
            "EVENT_LISTENER",
            "INJECTS",
            "PROVIDES",
            "RESOLVES_DEPENDENCY",
            "REFERENCES",
        ),
        evidence_guarantees="Source-backed reference locations with explicit confidence and evidence_class.",
        does_not_prove="Does not prove runtime execution order or unindexed external consumers.",
        useful_situations=(
            "Finding all usages, registrations, or DI bindings of a symbol across files",
            "Checking if a symbol is referenced before refactoring or deleting it",
        ),
        avoid_when=(
            "Purely local variable rename inside a single function scope",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_references(symbol="command_registry")',
        advanced_invocation='get_references(canonical_id="src/dispatch/registry.py:command_registry")',
        result_fields=("status", "canonical_id", "references", "relationship", "evidence_class", "confidence", "file", "start_line"),
        typical_followup="read_file on specific reference sites or get_context",
        common_mistakes=(
            "Treating REGISTERS or INJECTS references as direct CALLS edges",
            "Treating POSSIBLE references as verified facts without source confirmation",
        ),
        example_request="Where is command_registry referenced or populated?",
        example_call='get_references(symbol="command_registry")',
        example_interpretation="Check each reference item's relationship (e.g., REGISTERS, DISPATCHES_TO) and evidence_class.",
    ),
    # 6. get_callers
    ToolCapabilitySpec(
        tool_name="get_callers",
        capability="caller_relationship",
        description=(
            "Return statically verified callers of a symbol with confidence and evidence_class. "
            "Primary input: `symbol` (also accepts `canonical_id` as a compatibility alias using the exact same resolution path). "
            "Use for multi-file call-relationship and upstream impact questions. "
            "Does not prove runtime dispatch unless evidence_class indicates framework/dataflow verification."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id",),
        expected_output_type="CallerListResult",
        relationship_types_returned=("CALLS", "POSSIBLE_CALLS", "DISPATCHES_TO", "HANDLED_BY"),
        evidence_guarantees="Call-site file, line, source caller symbol, and RelationshipEvidenceClass.",
        does_not_prove="Does not prove dead-code reachability at runtime or reflective eval/getattr calls.",
        useful_situations=(
            "Answering 'What calls function X?' across the repository",
            "Tracing upstream callers during debugging or change-impact analysis",
        ),
        avoid_when=(
            "Single-file local edit where call relationships do not matter",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_callers(symbol="verify_password")',
        advanced_invocation='get_callers(canonical_id="src/auth/security.py:verify_password")',
        result_fields=("status", "canonical_id", "callers", "source", "relationship", "evidence_class", "confidence", "file", "start_line"),
        typical_followup="stop if callers list answers the question, or read_file on specific call sites",
        common_mistakes=(
            "Claiming 'nothing calls X' when dynamic dispatch edges are marked UNKNOWN",
            "Passing an ambiguous bare name without calling resolve_symbol first",
        ),
        example_request="What calls verify_password across the codebase?",
        example_call='get_callers(symbol="verify_password")',
        example_interpretation="Inspect callers list; verified callers carry relationship='CALLS' and evidence_class='AST_VERIFIED' or 'DATAFLOW_VERIFIED'.",
    ),
    # 7. get_callees
    ToolCapabilitySpec(
        tool_name="get_callees",
        capability="callee_relationship",
        description=(
            "Return symbols called or invoked by the specified symbol with evidence_class classification. "
            "Primary input: `symbol` (also accepts `canonical_id` as a compatibility alias using the exact same resolution path). "
            "Use to inspect downstream dependencies invoked by a function or handler. "
            "Does not resolve dynamic callbacks passed as opaque runtime arguments."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id",),
        expected_output_type="CalleeListResult",
        relationship_types_returned=("CALLS", "POSSIBLE_CALLS", "INJECTS", "RESOLVES_DEPENDENCY"),
        evidence_guarantees="AST/dataflow-verified outgoing calls with exact call-site line numbers.",
        does_not_prove="Does not prove external network calls or dynamically constructed strings.",
        useful_situations=(
            "Answering 'What does function X call?' without manually reading every imported module",
            "Following execution downstream from an endpoint or task handler",
        ),
        avoid_when=(
            "The function body is 5 lines long and already visible in context",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_callees(symbol="process_checkout")',
        advanced_invocation='get_callees(canonical_id="src/orders/service.py:process_checkout")',
        result_fields=("status", "canonical_id", "callees", "target", "relationship", "evidence_class", "confidence", "file", "start_line"),
        typical_followup="get_symbol or trace_path on downstream targets",
        common_mistakes=(
            "Assuming POSSIBLE_CALLS edges are guaranteed to execute on every code path",
        ),
        example_request="What does process_checkout call downstream?",
        example_call='get_callees(symbol="process_checkout")',
        example_interpretation="Read each outgoing edge in callees along with its target, relationship, and evidence_class.",
    ),
    # 8. trace_path
    ToolCapabilitySpec(
        tool_name="trace_path",
        capability="execution_path_tracing",
        description=(
            "Compute deterministic multi-hop relationship paths between two symbols (`from_symbol` -> `to_symbol`). "
            "Use when tracing how an entrypoint, route, or caller reaches a downstream service or database function. "
            "Returns ordered hop edges with relationship types and evidence classes. "
            "Does not prove runtime branch conditions along the path."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.RELATIONSHIP.value,
        ),
        required_inputs=("from_symbol", "to_symbol"),
        optional_inputs=("start_symbol", "target_symbol", "source_symbol", "max_depth"),
        expected_output_type="PathTraceResult",
        relationship_types_returned=(
            "CALLS",
            "HANDLED_BY",
            "MOUNTS",
            "DISPATCHES_TO",
            "INJECTS",
            "PROVIDES",
            "RESOLVES_DEPENDENCY",
            "TASK_HANDLER",
            "COMMAND_HANDLER",
            "EVENT_LISTENER",
        ),
        evidence_guarantees="Ordered multi-hop chain where every hop carries file, line, and evidence_class.",
        does_not_prove="Does not prove that a conditional runtime branch is taken for a specific input payload.",
        useful_situations=(
            "Proving how an HTTP endpoint or CLI command reaches a downstream repository or helper",
            "Connecting two symbols across multiple intermediate modules",
        ),
        avoid_when=(
            "Only a single symbol is known and you want general context (use get_context instead)",
        ),
        profiles=("agent", "core", "graph", "minimal", "developer", "full"),
        minimal_invocation='trace_path(from_symbol="login_endpoint", to_symbol="find_by_email")',
        advanced_invocation='trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=5)',
        result_fields=("status", "from_symbol", "to_symbol", "path", "paths", "hops", "evidence_class", "confidence"),
        typical_followup="get_file on specific hop lines if branch logic must be verified",
        common_mistakes=(
            "Treating an empty path at max_depth=2 as proof of no connection without checking higher depth or dynamic dispatch",
        ),
        example_request="How does login_endpoint reach UserRepository.find_by_email?",
        example_call='trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)',
        example_interpretation="Inspect the ordered hops in path/paths and verify each hop's relationship and evidence_class.",
    ),
    # 9. get_imports
    ToolCapabilitySpec(
        tool_name="get_imports",
        capability="module_import_inspection",
        description=(
            "Return parser-extracted module and symbol imports for a file or symbol (`file` or `symbol`; `canonical_id` and `path` supported as aliases). "
            "Use for forward dependency and package boundary questions. "
            "Does not return reverse importers (use get_dependents for reverse dependencies)."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.PACKAGE.value,
        ),
        required_inputs=("file",),
        optional_inputs=("symbol", "canonical_id", "path"),
        expected_output_type="ImportsResult",
        relationship_types_returned=("IMPORTS", "DEPENDS_ON_PACKAGE", "CROSS_PACKAGE_IMPORT"),
        evidence_guarantees="AST-verified import statements and resolved internal module paths.",
        does_not_prove="Does not prove whether an imported symbol is actually invoked at runtime.",
        useful_situations=(
            "Inspecting what modules or workspace packages a file depends on",
        ),
        avoid_when=(
            "Finding what files import this module (use get_dependents instead)",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_imports(file="src/auth/routes.py")',
        advanced_invocation='get_imports(symbol="src/auth/routes.py:login_endpoint")',
        result_fields=("status", "file", "imports", "source", "target", "relationship", "evidence_class"),
        typical_followup="get_dependents or get_architecture",
        common_mistakes=(
            "Using get_imports when looking for reverse dependents (use get_dependents)",
        ),
        example_request="What modules does src/auth/routes.py import?",
        example_call='get_imports(file="src/auth/routes.py")',
        example_interpretation="Inspect the imports list for internal module paths and cross-package imports.",
    ),
    # 10. get_dependents
    ToolCapabilitySpec(
        tool_name="get_dependents",
        capability="reverse_dependency_inspection",
        description=(
            "Return files, symbols, and packages that import or depend on the target symbol or file (`symbol` or `file`; `canonical_id` and `path` supported as aliases). "
            "Use for blast-radius, change-impact, and package boundary analysis. "
            "Does not prove runtime failure without checking test and caller evidence."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.PACKAGE.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "file", "path"),
        expected_output_type="DependentsResult",
        relationship_types_returned=("IMPORTS", "CALLS", "DEPENDS_ON_PACKAGE", "TESTS"),
        evidence_guarantees="Verified reverse import and call edges pointing to the target.",
        does_not_prove="Does not prove unindexed external repository consumers.",
        useful_situations=(
            "Determining which modules or packages break if a shared symbol or file signature changes",
        ),
        avoid_when=(
            "Editing a private helper that is never exported or referenced outside one function",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_dependents(symbol="UserRepository")',
        advanced_invocation='get_dependents(file="src/auth/repository.py")',
        result_fields=("status", "dependents", "source", "target", "relationship", "evidence_class", "file"),
        typical_followup="find_related_tests or analyze_impact",
        common_mistakes=(
            "Confusing forward imports (get_imports) with reverse dependents (get_dependents)",
        ),
        example_request="Which modules depend on src/auth/repository.py?",
        example_call='get_dependents(file="src/auth/repository.py")',
        example_interpretation="Review the dependents list to see all upstream files and symbols importing the module.",
    ),
    # 11. list_routes
    ToolCapabilitySpec(
        tool_name="list_routes",
        capability="route_discovery",
        description=(
            "Return HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols. "
            "Use when locating API endpoints, route handlers, or mounted sub-applications (FastAPI, Flask, Django, Express, NestJS). "
            "Does not prove runtime middleware authentication unless traced via get_context or trace_path."
        ),
        task_types=(
            AgentTaskCategory.ROUTE_DISCOVERY.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=("framework", "method", "path"),
        expected_output_type="RouteListResult",
        relationship_types_returned=("HANDLED_BY", "ROUTE_HANDLER", "MOUNTS", "ROUTES_TO"),
        evidence_guarantees="Framework-verified route paths, HTTP methods, composed mount prefixes, and handler canonical IDs.",
        does_not_prove="Does not prove external API gateway or reverse-proxy rewrite rules outside the repository.",
        useful_situations=(
            "Answering 'Which route handles /api/v1/auth/login?'",
            "Listing all API entrypoints in a service before tracing a request flow",
        ),
        avoid_when=(
            "Working on a pure library or CLI module with no web routes",
        ),
        profiles=("core", "graph", "minimal", "developer", "full"),
        minimal_invocation="list_routes()",
        advanced_invocation='list_routes(method="POST", path="/api/v1/auth/login")',
        result_fields=("status", "routes", "route_path", "http_method", "handler_name", "canonical_id", "framework", "file", "line", "evidence_class"),
        typical_followup="resolve_symbol, trace_path, or get_context(intent='TRACE')",
        common_mistakes=(
            "Grepping for route path strings that are split across router prefix mounts instead of calling list_routes",
        ),
        example_request="Which handler serves POST /api/v1/auth/login?",
        example_call='list_routes(method="POST", path="/api/v1/auth/login")',
        example_interpretation="Read handler_name, canonical_id, and file:line from the matched route entry.",
    ),
    # 12. get_architecture
    ToolCapabilitySpec(
        tool_name="get_architecture",
        capability="architecture_overview",
        description=(
            "Return structural repository overview including modules, workspace packages (`DEPENDS_ON_PACKAGE`), entrypoints, and layer relationships. "
            "Use for high-level architecture, monorepo package boundary, and onboarding questions. "
            "Does not replace symbol-level evidence for specific bug fixes."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.PACKAGE.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="ArchitectureOverviewResult",
        relationship_types_returned=("IMPORTS", "DEPENDS_ON_PACKAGE", "CONTAINS_PACKAGE", "MOUNTS", "HANDLED_BY"),
        evidence_guarantees="Manifest-backed workspace packages and AST-verified module dependency counts.",
        does_not_prove="Does not infer package boundaries from directory names without manifest evidence.",
        useful_situations=(
            "Understanding overall system structure, entrypoints, and monorepo package dependencies",
        ),
        avoid_when=(
            "Fixing a localized bug in a single already-known function",
        ),
        profiles=("agent", "core", "graph", "minimal", "developer", "full"),
        minimal_invocation="get_architecture()",
        advanced_invocation="get_architecture()",
        result_fields=("status", "modules", "packages", "package_dependencies", "entrypoints", "routes", "summary"),
        typical_followup="get_context(intent='ARCHITECTURE') or get_imports/get_dependents",
        common_mistakes=(
            "Inferring package boundaries from folder names like apps/ or packages/ when get_architecture shows no manifest",
        ),
        example_request="How is this monorepo structured and what are the workspace packages?",
        example_call="get_architecture()",
        example_interpretation="Inspect packages, package_dependencies, and entrypoints for manifest-verified boundaries.",
    ),
    # 13. get_git_impact
    ToolCapabilitySpec(
        tool_name="get_git_impact",
        capability="change_impact_analysis",
        description=(
            "Compute deterministic change impact between Git refs (`base`..`head`), including modified symbols, downstream callers, affected packages, and covering tests. "
            "Use for PR review, regression analysis, and pre-commit blast-radius checks. "
            "Does not execute tests; reports static test-to-symbol coverage edges."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("base", "head"),
        expected_output_type="GitImpactResult",
        relationship_types_returned=("CALLS", "TESTS", "TESTS_SYMBOL", "DEPENDS_ON_PACKAGE", "IMPORTS"),
        evidence_guarantees="Git diff line mapping intersected with AST symbol spans and graph dependents.",
        does_not_prove="Does not prove whether tests pass or fail at runtime.",
        useful_situations=(
            "Finding affected callers, packages, and tests after recent commits or before a refactor",
        ),
        avoid_when=(
            "No Git history is relevant and you only need to look up a single symbol definition",
        ),
        profiles=("agent", "core", "graph", "minimal", "developer", "full"),
        minimal_invocation="get_git_impact()",
        advanced_invocation='get_git_impact(base="HEAD~3", head="HEAD")',
        result_fields=("status", "base", "head", "changed_files", "modified_symbols", "impacted_callers", "affected_packages", "related_tests"),
        typical_followup="find_tests or get_file on modified symbols",
        common_mistakes=(
            "Assuming get_git_impact runs pytest; it computes static impact and test selection",
        ),
        example_request="What symbols, packages, and tests are impacted by the latest commit?",
        example_call='get_git_impact(base="HEAD~1", head="HEAD")',
        example_interpretation="Inspect modified_symbols, impacted_callers, affected_packages, and related_tests.",
    ),
    # 14. get_context
    ToolCapabilitySpec(
        tool_name="get_context",
        capability="bounded_repository_context",
        description=(
            "Compile a token-bounded, coverage-optimized ContextPacket containing verified symbols, compressed relationships, routes, DI providers, packages, and related tests. "
            "Primary input: `query` (natural-language question, symbol, or task description; `task` is also supported as a compatibility alias for string or structured TaskSpec dict). "
            "Budget controls: `max_tokens` (default 4000, hard cap 20000), `max_files` (default 25, hard cap 40), `max_lines` (default 500, hard cap 1500). "
            "Preserves UNKNOWN, POSSIBLE, and AMBIGUOUS states explicitly. "
            "Does not return full raw files; use targeted get_file or read_file only if exact omitted lines are needed afterward."
        ),
        task_types=(
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.EXPLANATION.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.PACKAGE.value,
        ),
        required_inputs=("query",),
        optional_inputs=("task", "intent", "max_tokens", "max_files", "max_lines", "top_k", "plan", "mode", "explain", "resource_mode"),
        expected_output_type="ContextPacket",
        relationship_types_returned=(
            "CALLS",
            "POSSIBLE_CALLS",
            "IMPORTS",
            "HANDLED_BY",
            "MOUNTS",
            "REGISTERS",
            "DISPATCHES_TO",
            "EVENT_LISTENER",
            "TASK_HANDLER",
            "COMMAND_HANDLER",
            "INJECTS",
            "PROVIDES",
            "RESOLVES_DEPENDENCY",
            "CONFIGURES",
            "DEPENDS_ON_PACKAGE",
            "TESTS",
            "TESTS_SYMBOL",
            "TESTS_ROUTE",
            "TESTS_PROVIDER",
            "TESTS_EVENT_HANDLER",
        ),
        evidence_guarantees=(
            "Bounded source snippets, compressed relationships with supporting_locations, "
            "coverage_score, budget metadata (selected_tokens, candidate_tokens, selected_files, selected_lines, truncated), "
            "and explicit UNKNOWN/POSSIBLE/AMBIGUOUS preservation."
        ),
        does_not_prove="Does not execute code or fabricate edges for unresolvable dynamic dispatch.",
        useful_situations=(
            "Investigating a bug, route flow, DI chain, or multi-file feature in one bounded call",
            "Gathering target symbol + callers + callees + related tests + package context within a strict token/file/line budget",
        ),
        avoid_when=(
            "Trivial one-file edit where the exact lines are already known",
        ),
        profiles=("agent", "graph", "minimal", "developer", "full"),
        minimal_invocation='get_context(query="Debug authentication failure in login_endpoint")',
        advanced_invocation='get_context(query="Trace DI chain for get_current_user", intent="DEBUG", max_tokens=4000, max_files=25, max_lines=500, explain=True)',
        result_fields=("symbols", "relationships", "routes", "tests", "packages", "unknowns", "conflicts", "uncertainties", "freshness", "selected_tokens", "candidate_tokens", "selected_files", "selected_lines", "coverage_score", "truncated", "candidate_token_estimate", "selected_token_estimate", "context_reduction_pct", "coverage"),
        typical_followup="get_file on specific line ranges if implementation details outside snippets are required",
        common_mistakes=(
            "Calling get_context multiple times with identical arguments instead of reading the returned ContextPacket",
            "Ignoring the unknowns, conflicts, uncertainties, and truncated fields in the ContextPacket",
        ),
        example_request="How does UserRepository get injected into UserController and what tests cover it?",
        example_call='get_context(query="How does UserRepository get injected into UserController", intent="DEBUG", max_tokens=4000)',
        example_interpretation="Inspect symbols, INJECTS/PROVIDES relationships, tests, selected_tokens/coverage_score/truncated, and any unknowns/conflicts/uncertainties.",
    ),
    # 15. find_related_tests
    ToolCapabilitySpec(
        tool_name="find_related_tests",
        capability="test_discovery",
        description=(
            "Return test files and test functions statically linked to a target symbol (`symbol`; `canonical_id` supported as alias) via direct calls, imports, fixtures, or route invocation. "
            "Use when answering 'Which tests cover symbol X?' before or after a code change. "
            "Never fabricates coverage from lexical similarity alone."
        ),
        task_types=(
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "max_results"),
        expected_output_type="RelatedTestsResult",
        relationship_types_returned=("TESTS", "TESTS_SYMBOL", "TESTS_ROUTE", "TESTS_PROVIDER", "TESTS_EVENT_HANDLER", "CALLS", "IMPORTS"),
        evidence_guarantees="AST/fixture/route-verified links from test functions to target symbols.",
        does_not_prove="Does not prove runtime line coverage percentage or assertion completeness.",
        useful_situations=(
            "Selecting the exact pytest/jest test functions to run after modifying a symbol",
        ),
        avoid_when=(
            "Editing documentation or comments with no behavioral impact",
        ),
        profiles=("graph", "developer", "full"),
        minimal_invocation='find_related_tests(symbol="AuthService.authenticate")',
        advanced_invocation='find_related_tests(symbol="login_endpoint", max_results=20)',
        result_fields=("test_symbol", "file", "start_line", "end_line", "relationship", "evidence_class", "confidence", "reason"),
        typical_followup="read_file on the test function if test assertions need inspection",
        common_mistakes=(
            "Assuming empty results mean no dynamic integration test exists if tests invoke external URLs via env vars",
        ),
        example_request="Which tests cover BillingService.charge_card?",
        example_call='find_related_tests(symbol="BillingService.charge_card")',
        example_interpretation="Inspect each returned test symbol, its file path, and the linking relationship (e.g., TESTS_SYMBOL, TESTS_ROUTE).",
    ),
    # 16. analyze_impact
    ToolCapabilitySpec(
        tool_name="analyze_impact",
        capability="symbol_blast_radius",
        description=(
            "Compute downstream callers, dependents, affected routes, and related tests if a symbol (`symbol`; `canonical_id` supported as alias) is modified. "
            "Use before refactoring or changing a function/class signature. "
            "Does not prove runtime failure without inspecting call sites."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "max_depth"),
        expected_output_type="SymbolImpactResult",
        relationship_types_returned=("CALLS", "CALLED_BY", "IMPORTS", "HANDLED_BY", "TESTS", "DEPENDS_ON_PACKAGE"),
        evidence_guarantees="Multi-hop reverse dependency traversal with hop distances and evidence classes.",
        does_not_prove="Does not prove dynamic string-based reflection consumers.",
        useful_situations=(
            "Evaluating blast radius of a signature or behavior change to a symbol",
        ),
        avoid_when=(
            "Adding a brand-new standalone helper with no existing callers",
        ),
        profiles=("graph", "developer", "full"),
        minimal_invocation='analyze_impact(symbol="DatabasePool.acquire")',
        advanced_invocation='analyze_impact(symbol="DatabasePool.acquire", max_depth=4)',
        result_fields=("symbol", "direct_callers", "transitive_callers", "dependent_files", "affected_routes", "related_tests"),
        typical_followup="find_related_tests or read_file on direct_callers",
        common_mistakes=(
            "Modifying a public signature without checking direct_callers and affected_routes",
        ),
        example_request="What breaks if we change DatabasePool.acquire?",
        example_call='analyze_impact(symbol="DatabasePool.acquire", max_depth=3)',
        example_interpretation="Review direct_callers, transitive_callers, affected_routes, and related_tests.",
    ),
    # 17. read_file
    ToolCapabilitySpec(
        tool_name="read_file",
        capability="targeted_source_read",
        description=(
            "Read a bounded line range (1..500 lines) of a non-sensitive repository file. "
            "Use AFTER CodeGraph tools identify the exact file and line span, or directly for trivial single-file edits. "
            "Blocks path traversal and sensitive credential files. Does not compute cross-file relationships."
        ),
        task_types=(
            AgentTaskCategory.LOCAL_EDIT.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("path",),
        optional_inputs=("start_line", "end_line"),
        expected_output_type="FileContentSlice",
        relationship_types_returned=(),
        evidence_guarantees="Exact on-disk source lines within repository privacy boundaries.",
        does_not_prove="Does not compute cross-file callers, DI bindings, or test links.",
        useful_situations=(
            "Inspecting exact implementation lines inside a symbol span identified by CodeGraph",
            "Performing a simple single-file edit",
        ),
        avoid_when=(
            "Scanning dozens of files blindly instead of calling resolve_symbol or get_context first",
        ),
        profiles=("minimal", "developer", "full"),
        minimal_invocation='read_file(path="src/auth/service.py", start_line=1, end_line=60)',
        advanced_invocation='read_file(path="src/auth/service.py", start_line=40, end_line=95)',
        result_fields=("file", "start_line", "end_line", "content"),
        typical_followup="perform code edit or synthesize final answer",
        common_mistakes=(
            "Requesting >500 lines or attempting to read .env / secret key files (blocked by security policy)",
        ),
        example_request="Read lines 10 to 45 of src/auth/service.py.",
        example_call='read_file(path="src/auth/service.py", start_line=10, end_line=45)',
        example_interpretation="Inspect exact implementation statements in content for the requested line span.",
    ),
    # 18. search_code
    ToolCapabilitySpec(
        tool_name="search_code",
        capability="lexical_code_search",
        description=(
            "Search literal text, HTML/Jinja template IDs, UI strings, CSS selectors, config keys, or route paths across readable repository files and indexed code chunks. "
            "Use instead of grep when searching for exact text, button labels, or template strings. "
            "Does not prove semantic call, import, or route relationships; never creates semantic graph edges from text matches."
        ),
        task_types=(
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("query",),
        optional_inputs=("top_k", "path_filter", "file_types", "include_tests", "include_configs", "max_results"),
        expected_output_type="CodeChunkSearchResult",
        relationship_types_returned=(),
        evidence_guarantees="Ranked source and text matches with file path, exact line number, matched_text, snippet, match_type, and file_category.",
        does_not_prove="Does not prove module import graphs or caller/callee relationships; never creates semantic edges.",
        useful_situations=(
            "Locating UI button labels, HTML/Jinja template IDs, CSS selectors, error message strings, SQL fragments, or configuration keys",
        ),
        avoid_when=(
            "Answering who calls a function or what a module imports (use find_callers, get_callers, or get_imports)",
        ),
        profiles=("agent", "minimal", "developer", "full"),
        minimal_invocation='search_code(query="Add Manual Entry")',
        advanced_invocation='search_code(query="Add Manual Entry", file_types=["html", "jinja2"], max_results=10)',
        result_fields=("path", "file", "line", "start_line", "end_line", "matched_text", "snippet", "category", "file_category", "match_type", "symbol", "score", "reason"),
        typical_followup="get_file on the matched path and line range, or find_symbol on enclosing symbol",
        common_mistakes=(
            "Using search_code instead of find_callers/get_callers for structural symbol relationship queries",
        ),
        example_request="Where is the 'Add Manual Entry' button in HTML?",
        example_call='search_code(query="Add Manual Entry", top_k=10)',
        example_interpretation="Inspect the matched `path`, `line`, `matched_text`, and `snippet`, then open the surrounding lines with `get_file`.",
    ),
    # 19. find_symbol
    ToolCapabilitySpec(
        tool_name="find_symbol",
        capability="exact_symbol_lookup",
        description=(
            "Find function, method, or class definitions by exact short name or qualified name (`symbol`; `name` and `canonical_id` supported as aliases). "
            "Use instead of grep when locating where a class, function, or method is defined. "
            "Does not return callers, callees, or ambiguity alternatives like resolve_symbol."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("name", "canonical_id"),
        expected_output_type="SymbolLocationList",
        relationship_types_returned=("DEFINES",),
        evidence_guarantees="AST-indexed symbol rows matching name or qualified_name.",
        does_not_prove="Does not disambiguate routes or compute call relationships.",
        useful_situations=(
            "Quickly listing all definitions matching an exact symbol name",
        ),
        avoid_when=(
            "Searching for literal UI strings or HTML template text (use search_code instead)",
        ),
        profiles=("agent", "minimal", "developer", "full"),
        minimal_invocation='find_symbol(symbol="AuthService")',
        advanced_invocation='find_symbol(symbol="src.auth.service.AuthService")',
        result_fields=("symbol", "kind", "file", "start_line", "end_line"),
        typical_followup="get_symbol, get_file, or find_callers",
        common_mistakes=(
            "Using find_symbol with partial substrings (use search_symbols or search_code for partial matching)",
        ),
        example_request="Where is InventoryService defined?",
        example_call='find_symbol(symbol="InventoryService")',
        example_interpretation="Inspect file and start_line..end_line for each definition.",
    ),
    # 20. find_references
    ToolCapabilitySpec(
        tool_name="find_references",
        capability="textual_chunk_references",
        description=(
            "Find textual occurrences and references of a symbol name (`symbol`; `name` and `canonical_id` supported as aliases) across indexed code chunks. "
            "Use when locating references or mentions of an identifier across files. "
            "Does not prove semantic call edges; use get_references when full relationship classification is required."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("name", "canonical_id"),
        expected_output_type="ChunkReferenceList",
        relationship_types_returned=(),
        evidence_guarantees="Lexical substring matches inside indexed code chunks.",
        does_not_prove="Does not prove AST-verified call or reference semantics.",
        useful_situations=(
            "Finding all code chunks referencing an identifier across the repository",
        ),
        avoid_when=(
            "Searching for arbitrary non-symbol UI text in HTML templates (use search_code instead)",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation='find_references(symbol="parse_bill")',
        advanced_invocation='find_references(symbol="FEATURE_FLAG_X")',
        result_fields=("file", "symbol", "start_line", "end_line"),
        typical_followup="get_file on matched chunks to verify context",
        common_mistakes=(
            "Treating find_references chunk hits as verified CALLS edges",
        ),
        example_request="Find all references to parse_bill.",
        example_call='find_references(symbol="parse_bill")',
        example_interpretation="Inspect matched files and line ranges as reference sites.",
    ),
    # 21. find_callers
    ToolCapabilitySpec(
        tool_name="find_callers",
        capability="direct_caller_query",
        description=(
            "Find functions and methods that call the specified symbol (`symbol`; `canonical_id` supported as alias) up to `max_results`. "
            "Use instead of grep or search_code when answering 'who calls X?'. "
            "Does not prove runtime execution of conditional branches; preserves POSSIBLE and UNKNOWN evidence classes."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "max_results"),
        expected_output_type="CallerEdgeList",
        relationship_types_returned=("CALLS", "POSSIBLE_CALLS"),
        evidence_guarantees="Graph edges with relationship, confidence, evidence_class, and call-site coordinates.",
        does_not_prove="Does not prove runtime execution or dynamic reflection calls.",
        useful_situations=(
            "Answering 'Who calls function X?' with a bounded result list",
        ),
        avoid_when=(
            "Single-file local edits",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation='find_callers(symbol="place_order")',
        advanced_invocation='find_callers(symbol="verify_password", max_results=50)',
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "file", "start_line"),
        typical_followup="get_file or trace_path",
        common_mistakes=(
            "Ignoring evidence_class on POSSIBLE_CALLS rows",
        ),
        example_request="Who calls place_order?",
        example_call='find_callers(symbol="place_order", max_results=20)',
        example_interpretation="Inspect each caller's source symbol, file, line, and evidence_class.",
    ),
    # 22. find_callees
    ToolCapabilitySpec(
        tool_name="find_callees",
        capability="direct_callee_query",
        description=(
            "Find functions and methods called by the specified symbol (`symbol`; `canonical_id` supported as alias) up to `max_results`. "
            "Use instead of reading multiple files manually when answering 'what does X call?'. "
            "Does not resolve opaque runtime callbacks; preserves POSSIBLE and UNKNOWN evidence classes."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "max_results"),
        expected_output_type="CalleeEdgeList",
        relationship_types_returned=("CALLS", "POSSIBLE_CALLS"),
        evidence_guarantees="Outgoing call edges with target, confidence, evidence_class, and line numbers.",
        does_not_prove="Does not prove external service behavior or dynamic eval calls.",
        useful_situations=(
            "Answering 'What does function X call?' with a bounded result list",
        ),
        avoid_when=(
            "Single-file local edits",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation='find_callees(symbol="place_order")',
        advanced_invocation='find_callees(symbol="login_endpoint", max_results=30)',
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "file", "start_line"),
        typical_followup="get_symbol or get_file on target callees",
        common_mistakes=(
            "Treating POSSIBLE_CALLS as guaranteed execution",
        ),
        example_request="What does place_order call?",
        example_call='find_callees(symbol="place_order", max_results=20)',
        example_interpretation="Inspect each outgoing call edge's target and evidence_class.",
    ),
    # 23. get_call_graph
    ToolCapabilitySpec(
        tool_name="get_call_graph",
        capability="neighborhood_call_graph",
        description=(
            "Compute the multi-hop call graph rooted at `symbol` (`canonical_id` supported as alias) up to `depth` and `max_results`. "
            "Use when exploring the multi-hop call neighborhood around a central service or controller. "
            "Does not prove runtime reachability for specific inputs."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "depth", "max_results"),
        expected_output_type="CallGraphEdgeList",
        relationship_types_returned=("CALLS", "POSSIBLE_CALLS", "DISPATCHES_TO", "HANDLED_BY"),
        evidence_guarantees="Bounded multi-hop subgraph edges with hop depth and evidence metadata.",
        does_not_prove="Does not prove that every branch in the call graph executes on a single request.",
        useful_situations=(
            "Mapping 2-hop or 3-hop call neighborhoods around a core function",
        ),
        avoid_when=(
            "You only need direct 1-hop callers (use get_callers) or a path between two known endpoints (use trace_path)",
        ),
        profiles=("graph", "developer", "full"),
        minimal_invocation='get_call_graph(symbol="AuthService.authenticate")',
        advanced_invocation='get_call_graph(symbol="AuthService.authenticate", depth=3, max_results=50)',
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "depth", "file", "start_line"),
        typical_followup="trace_path or read_file",
        common_mistakes=(
            "Requesting large depth values when depth=2 already captures the relevant neighborhood",
        ),
        example_request="Show the 2-hop call graph around AuthService.authenticate.",
        example_call='get_call_graph(symbol="AuthService.authenticate", depth=2, max_results=50)',
        example_interpretation="Inspect the returned edges by hop depth and relationship type.",
    ),
    # 24. get_dependency_graph
    ToolCapabilitySpec(
        tool_name="get_dependency_graph",
        capability="module_dependency_graph",
        description=(
            "Return module-level `IMPORTS` graph edges across the repository or filtered to `file_path`. "
            "Use when inspecting raw module-to-module import topology. "
            "Does not prove symbol-level call invocation; prefer get_imports or get_dependents for targeted queries."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.PACKAGE.value,
        ),
        required_inputs=(),
        optional_inputs=("file_path",),
        expected_output_type="DependencyGraphEdgeList",
        relationship_types_returned=("IMPORTS",),
        evidence_guarantees="AST-extracted module IMPORTS edges with source, target, and confidence.",
        does_not_prove="Does not prove whether imported symbols are called.",
        useful_situations=(
            "Inspecting module import edges for a specific file or across a small repository",
        ),
        avoid_when=(
            "Querying a single file's imports (prefer get_imports)",
        ),
        profiles=("full",),
        minimal_invocation='get_dependency_graph(file_path="src/auth/service.py")',
        advanced_invocation="get_dependency_graph()",
        result_fields=("source", "target", "relationship", "confidence", "evidence"),
        typical_followup="get_architecture or get_dependents",
        common_mistakes=(
            "Calling get_dependency_graph() without file_path when only one module's imports are needed",
        ),
        example_request="Show import graph edges originating from src/auth/service.py.",
        example_call='get_dependency_graph(file_path="src/auth/service.py")',
        example_interpretation="Inspect each IMPORTS edge from source to target module.",
    ),
    # 25. compile_task
    ToolCapabilitySpec(
        tool_name="compile_task",
        capability="task_normalization_and_planning",
        description=(
            "Normalize a developer question or task (`query`; `task` supported as string or TaskSpec dict alias) into a structured `TaskSpec`, ground targets against the index, detect ambiguities, and build a `RetrievalPlan`. "
            "Use before get_context when you want to inspect target resolution and ambiguity candidates prior to context retrieval. "
            "Does not retrieve source code snippets."
        ),
        task_types=(
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.TRACE.value,
        ),
        required_inputs=("query",),
        optional_inputs=("task", "max_tokens", "resource_mode"),
        expected_output_type="CompiledTaskPlan",
        relationship_types_returned=(),
        evidence_guarantees="Deterministic TaskSpec, ambiguity list, candidate entrypoints, and RetrievalPlan.",
        does_not_prove="Does not return symbol bodies or relationship edges until get_context is called.",
        useful_situations=(
            "Pre-checking whether task targets are ambiguous before compiling a full ContextPacket",
        ),
        avoid_when=(
            "A direct call to get_context or resolve_symbol is sufficient",
        ),
        profiles=("minimal", "developer", "full"),
        minimal_invocation='compile_task(query="Trace login route to database")',
        advanced_invocation='compile_task(query="Debug AuthService", max_tokens=15000, resource_mode="CONSERVATIVE")',
        result_fields=("task_spec", "ambiguity", "ambiguities", "entry_points", "retrieval_plan", "recommended_next_step"),
        typical_followup="get_context(query=..., plan=retrieval_plan)",
        common_mistakes=(
            "Stopping after compile_task without calling get_context to retrieve actual evidence",
        ),
        example_request="Compile a retrieval plan for debugging AuthService.",
        example_call='compile_task(query="Debug AuthService")',
        example_interpretation="Check ambiguities and entry_points, then pass the query or plan to get_context.",
    ),
    # 26. plan_retrieval
    ToolCapabilitySpec(
        tool_name="plan_retrieval",
        capability="retrieval_plan_preview",
        description=(
            "Construct a deterministic `RetrievalPlan` for a question or task (`query`; `task` supported as alias) without executing graph or source retrieval. "
            "Use to inspect planned retrieval steps, token budgets, and query expansions. "
            "Does not return code snippets or relationship edges."
        ),
        task_types=(
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=("query",),
        optional_inputs=("task", "max_tokens", "resource_mode"),
        expected_output_type="RetrievalPlanDict",
        relationship_types_returned=(),
        evidence_guarantees="Deterministic step list, token budget allocation, and expanded queries.",
        does_not_prove="Does not execute retrieval or prove symbol relationships.",
        useful_situations=(
            "Inspecting how CodeGraph plans to allocate token budget for a complex query",
        ),
        avoid_when=(
            "Normal interactive tasks where get_context can be called directly",
        ),
        profiles=("developer", "full"),
        minimal_invocation='plan_retrieval(query="Explain payment processing flow")',
        advanced_invocation='plan_retrieval(query="Explain payment flow", max_tokens=10000, resource_mode="BALANCED")',
        result_fields=("intent", "steps", "token_budget", "expanded_queries", "ambiguities"),
        typical_followup="get_context",
        common_mistakes=(
            "Calling both plan_retrieval and compile_task redundantly before get_context",
        ),
        example_request="Preview the retrieval plan for tracing payment processing.",
        example_call='plan_retrieval(query="Trace payment processing")',
        example_interpretation="Inspect steps and expanded_queries, then invoke get_context.",
    ),
    # 27. get_recent_changes
    ToolCapabilitySpec(
        tool_name="get_recent_changes",
        capability="git_diff_file_list",
        description=(
            "Return repository files modified between two Git refs (`since`..`until`) in a read-only sandboxed query. "
            "Use when reviewing recent commits or identifying which files changed before running impact analysis. "
            "Does not compute downstream symbol callers; use get_git_impact for symbol-level blast radius."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("since", "until"),
        expected_output_type="GitChangedFilesList",
        relationship_types_returned=(),
        evidence_guarantees="Git diff status and relative file paths between refs.",
        does_not_prove="Does not compute symbol-level callers or covering tests (use get_git_impact).",
        useful_situations=(
            "Listing files touched in the last N commits during debugging or code review",
        ),
        avoid_when=(
            "You need symbol-level callers and affected tests (prefer get_git_impact)",
        ),
        profiles=("developer", "full"),
        minimal_invocation="get_recent_changes()",
        advanced_invocation='get_recent_changes(since="HEAD~5", until="HEAD")',
        result_fields=("path", "status"),
        typical_followup="get_git_impact or get_file",
        common_mistakes=(
            "Calling get_recent_changes and manually reading every changed file instead of calling get_git_impact",
        ),
        example_request="Which files changed in the last 5 commits?",
        example_call='get_recent_changes(since="HEAD~5", until="HEAD")',
        example_interpretation="Inspect each changed file's path and change status.",
    ),
    # 28. get_file_history
    ToolCapabilitySpec(
        tool_name="get_file_history",
        capability="git_file_commit_history",
        description=(
            "Return recent Git commits touching a specific repository file (`path`, up to `n` commits). "
            "Use when investigating when and why a specific file was recently modified. "
            "Does not return full commit diffs or cross-file dependency impact."
        ),
        task_types=(
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("path",),
        optional_inputs=("n",),
        expected_output_type="FileCommitHistoryList",
        relationship_types_returned=(),
        evidence_guarantees="Commit hashes, authors, timestamps, and commit subjects touching `path`.",
        does_not_prove="Does not prove which specific symbol inside the file caused a regression.",
        useful_situations=(
            "Checking recent commit history on a buggy file",
        ),
        avoid_when=(
            "Static symbol relationships or current source code are sufficient",
        ),
        profiles=("developer", "full"),
        minimal_invocation='get_file_history(path="src/auth/service.py")',
        advanced_invocation='get_file_history(path="src/auth/service.py", n=5)',
        result_fields=("commit", "author", "date", "subject"),
        typical_followup="get_git_impact(base=commit, head='HEAD')",
        common_mistakes=(
            "Passing an absolute path outside the repository",
        ),
        example_request="Show the last 5 commits touching src/auth/service.py.",
        example_call='get_file_history(path="src/auth/service.py", n=5)',
        example_interpretation="Inspect the commit hashes and subjects to identify relevant recent changes.",
    ),
    # 29. analyze_change_impact
    ToolCapabilitySpec(
        tool_name="analyze_change_impact",
        capability="git_range_change_impact",
        description=(
            "Analyze changed files, modified symbols, downstream callers, and related tests between Git refs `since` and `until`. "
            "Use for commit-range impact analysis when `since`/`until` parameter naming is preferred. "
            "Does not execute tests at runtime."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
        ),
        required_inputs=(),
        optional_inputs=("since", "until"),
        expected_output_type="ChangeImpactReport",
        relationship_types_returned=("CALLS", "TESTS", "IMPORTS"),
        evidence_guarantees="Git diff mapped to indexed symbols, callers, and related tests.",
        does_not_prove="Does not prove runtime test pass/fail status.",
        useful_situations=(
            "Analyzing blast radius of commits between `since` and `until`",
        ),
        avoid_when=(
            "Analyzing impact of a hypothetical edit not yet in Git (use analyze_impact instead)",
        ),
        profiles=("developer", "full"),
        minimal_invocation="analyze_change_impact()",
        advanced_invocation='analyze_change_impact(since="HEAD~2", until="HEAD")',
        result_fields=("changed_files", "modified_symbols", "callers", "related_tests"),
        typical_followup="find_related_tests or read_file",
        common_mistakes=(
            "Calling both get_git_impact and analyze_change_impact on the same commit range",
        ),
        example_request="Analyze change impact between HEAD~2 and HEAD.",
        example_call='analyze_change_impact(since="HEAD~2", until="HEAD")',
        example_interpretation="Inspect modified_symbols, downstream callers, and related_tests.",
    ),
    # 30. get_repository_status
    ToolCapabilitySpec(
        tool_name="get_repository_status",
        capability="index_status_and_freshness",
        description=(
            "Return repository indexing status, generation counter, freshness state (`FRESH` or `STALE`), symbol counts, and modified/deleted file lists. "
            "Use to check whether the index is fresh before trusting cached graph facts after disk edits. "
            "Does not re-index the repository automatically."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="RepositoryStatusReport",
        relationship_types_returned=(),
        evidence_guarantees="On-disk mtime/hash comparison against indexed file records.",
        does_not_prove="Does not prove external git remote state.",
        useful_situations=(
            "Checking if freshness is FRESH or STALE after editing files",
            "Inspecting total indexed files, symbols, graph_edges, and framework_routes",
        ),
        avoid_when=(
            "Normal read-only queries when freshness is already included in tool responses",
        ),
        profiles=("minimal", "developer", "full"),
        minimal_invocation="get_repository_status()",
        advanced_invocation="get_repository_status()",
        result_fields=("repository", "generation", "freshness", "freshness_detail", "files_indexed", "symbols_indexed", "graph_edges", "framework_routes", "modified_files", "deleted_files", "parse_failed_files"),
        typical_followup="read_file on modified_files if freshness is STALE",
        common_mistakes=(
            "Presenting cached graph edges from modified_files as current truth when freshness == 'STALE'",
        ),
        example_request="Is the CodeGraph index fresh and how many symbols are indexed?",
        example_call="get_repository_status()",
        example_interpretation="Check freshness ('FRESH' vs 'STALE'), symbols_indexed, and modified_files.",
    ),
    # 31. trace_call
    ToolCapabilitySpec(
        tool_name="trace_call",
        capability="directional_call_traversal",
        description=(
            "Traverse callers, callees, or both from a single `symbol` (`canonical_id` supported as alias) up to `depth` with confidence and relationship labels. "
            "Use when exploring upstream and/or downstream call trees from one symbol without a known second endpoint. "
            "Does not prove runtime branch execution."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.RELATIONSHIP.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "depth", "callers", "callees", "both"),
        expected_output_type="DirectionalCallTraceList",
        relationship_types_returned=("CALLS", "CALLED_BY", "POSSIBLE_CALLS"),
        evidence_guarantees="Directional multi-hop call traversal with hop depth and confidence.",
        does_not_prove="Does not prove runtime reachability under specific input conditions.",
        useful_situations=(
            "Tracing 2 hops of upstream callers (`callers=True`) or downstream callees (`callees=True`) from one symbol",
        ),
        avoid_when=(
            "Both start and target symbols are known (prefer trace_path)",
        ),
        profiles=("developer", "full"),
        minimal_invocation='trace_call(symbol="verify_password", depth=2, callers=True)',
        advanced_invocation='trace_call(symbol="AuthService.authenticate", depth=2, both=True)',
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "depth", "file", "start_line"),
        typical_followup="read_file on specific hops",
        common_mistakes=(
            "Using trace_call when trace_path(from_symbol, to_symbol) would directly connect two known symbols",
        ),
        example_request="Trace 2 hops of upstream callers for verify_password.",
        example_call='trace_call(symbol="verify_password", depth=2, callers=True)',
        example_interpretation="Inspect each hop's source, target, depth, and evidence_class.",
    ),
    # 32. get_project_structure
    ToolCapabilitySpec(
        tool_name="get_project_structure",
        capability="indexed_file_list",
        description=(
            "Return up to 500 indexed repository-relative source file paths in deterministic sorted order. "
            "Use for a flat inventory of indexed files when exploring a small project. "
            "Does not return package dependency graphs or entrypoints (prefer get_architecture)."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="IndexedFilePathList",
        relationship_types_returned=(),
        evidence_guarantees="Sorted list of non-sensitive indexed file paths.",
        does_not_prove="Does not prove package ownership or module relationships.",
        useful_situations=(
            "Listing indexed file paths in a small repository",
        ),
        avoid_when=(
            "Understanding architecture, entrypoints, or monorepo packages (prefer get_architecture)",
        ),
        profiles=("full",),
        minimal_invocation="get_project_structure()",
        advanced_invocation="get_project_structure()",
        result_fields=("path",),
        typical_followup="get_file or get_architecture",
        common_mistakes=(
            "Calling get_project_structure instead of get_architecture for architectural questions",
        ),
        example_request="List all indexed file paths in the repository.",
        example_call="get_project_structure()",
        example_interpretation="Inspect the returned list of relative POSIX file paths.",
    ),
    # 33. get_dependencies
    ToolCapabilitySpec(
        tool_name="get_dependencies",
        capability="raw_import_table_dump",
        description=(
            "List up to 500 raw parser-extracted `(source_path, imported)` rows from the imports table. "
            "Use for bulk inspection of raw import statements across the repository. "
            "Does not resolve workspace package boundaries; prefer get_imports or get_architecture."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.PACKAGE.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="RawImportRowList",
        relationship_types_returned=("IMPORTS",),
        evidence_guarantees="AST-extracted import strings per source file.",
        does_not_prove="Does not prove installed third-party package versions.",
        useful_situations=(
            "Auditing raw import strings across the repository",
        ),
        avoid_when=(
            "Inspecting imports of a single file (prefer get_imports)",
        ),
        profiles=("full",),
        minimal_invocation="get_dependencies()",
        advanced_invocation="get_dependencies()",
        result_fields=("source_path", "imported"),
        typical_followup="get_imports",
        common_mistakes=(
            "Using get_dependencies when get_imports(file=...) is much more targeted",
        ),
        example_request="List raw import statements across indexed files.",
        example_call="get_dependencies()",
        example_interpretation="Inspect source_path and imported module names.",
    ),
    # 34. get_file_symbols
    ToolCapabilitySpec(
        tool_name="get_file_symbols",
        capability="file_symbol_table",
        description=(
            "List extracted symbols (`symbol`, `kind`, `start_line`, `end_line`) in a single repository-relative file. "
            "Use for a lightweight symbol table of one file when imports and artifact metadata are not needed. "
            "Does not return cross-file relationships; prefer get_file for full file outline."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
        ),
        required_inputs=("path",),
        optional_inputs=(),
        expected_output_type="FileSymbolRowList",
        relationship_types_returned=("DEFINES",),
        evidence_guarantees="AST-extracted symbol names, kinds, and line spans within `path`.",
        does_not_prove="Does not return file imports or callers.",
        useful_situations=(
            "Listing symbol names and line ranges inside a single file",
        ),
        avoid_when=(
            "You also need file imports and artifact classification (prefer get_file)",
        ),
        profiles=("full",),
        minimal_invocation='get_file_symbols(path="src/auth/service.py")',
        advanced_invocation='get_file_symbols(path="src/auth/routes.py")',
        result_fields=("symbol", "kind", "start_line", "end_line"),
        typical_followup="get_symbol or read_file",
        common_mistakes=(
            "Passing a symbol name instead of a file path",
        ),
        example_request="List all symbols defined in src/auth/service.py.",
        example_call='get_file_symbols(path="src/auth/service.py")',
        example_interpretation="Inspect each symbol's qualified name, kind, and line span.",
    ),
    # 35. get_graph
    ToolCapabilitySpec(
        tool_name="get_graph",
        capability="structural_graph_edges",
        description=(
            "Return up to `limit` (1..500) parser-confirmed definition and import graph edges with evidence metadata. "
            "Use for inspecting raw structural `DEFINES` and `IMPORTS` edges in small repositories or diagnostics. "
            "Does not replace targeted relationship tools like get_callers or trace_path."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=(),
        optional_inputs=("limit",),
        expected_output_type="GraphEdgeList",
        relationship_types_returned=("DEFINES", "IMPORTS"),
        evidence_guarantees="Validated structural edges with source, target, relationship, and confidence.",
        does_not_prove="Does not return task-ranked context or multi-hop traces.",
        useful_situations=(
            "Sampling raw structural graph edges during diagnostics",
        ),
        avoid_when=(
            "Answering targeted symbol or route questions (use get_callers, trace_path, or get_context)",
        ),
        profiles=("developer", "full"),
        minimal_invocation="get_graph()",
        advanced_invocation="get_graph(limit=100)",
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "file", "line"),
        typical_followup="get_architecture",
        common_mistakes=(
            "Dumping get_graph(limit=500) instead of querying the specific symbol with get_callers/get_references",
        ),
        example_request="Sample the first 50 structural edges in the graph.",
        example_call="get_graph(limit=50)",
        example_interpretation="Inspect source, target, and relationship for each edge.",
    ),
    # 36. search_memory
    ToolCapabilitySpec(
        tool_name="search_memory",
        capability="local_memory_lookup",
        description=(
            "Search local SQLite repository memory notes by keyword up to `limit` (1..100). "
            "Use only to recall previously stored local session notes. "
            "Never overrides current AST or source-file evidence; does not prove current repository state."
        ),
        task_types=(
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("query",),
        optional_inputs=("limit",),
        expected_output_type="MemoryNoteList",
        relationship_types_returned=(),
        evidence_guarantees="Local key-value notes stored in the repository memory table.",
        does_not_prove="Never proves current code structure; source code and AST evidence always take precedence.",
        useful_situations=(
            "Looking up user-saved architectural notes in local memory",
        ),
        avoid_when=(
            "Verifying actual code relationships (always use AST/graph tools instead)",
        ),
        profiles=("full",),
        minimal_invocation='search_memory(query="auth")',
        advanced_invocation='search_memory(query="deployment", limit=10)',
        result_fields=("key", "value"),
        typical_followup="resolve_symbol or get_context to verify against current source",
        common_mistakes=(
            "Trusting stale memory notes over current AST evidence",
        ),
        example_request="Search saved memory notes for 'auth'.",
        example_call='search_memory(query="auth", limit=10)',
        example_interpretation="Treat returned notes as auxiliary context subordinate to live source evidence.",
    ),
    # 37. get_evidence
    ToolCapabilitySpec(
        tool_name="get_evidence",
        capability="file_evidence_extraction",
        description=(
            "Return bounded source-derived `Evidence` citations (`file`, `start_line`, `end_line`, `symbol`, `snippet`, `content_hash`) for a non-sensitive file or symbol. "
            "Use when constructing hash-verifiable code citations. "
            "Blocks sensitive files and does not compute cross-file callers."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=("path",),
        optional_inputs=("symbol",),
        expected_output_type="EvidenceCitationList",
        relationship_types_returned=(),
        evidence_guarantees="Indexed chunk snippets paired with SHA-256 content hashes and line coordinates.",
        does_not_prove="Does not compute cross-file relationship edges.",
        useful_situations=(
            "Fetching verifiable evidence snippets for a symbol inside a known file",
        ),
        avoid_when=(
            "Reading arbitrary line ranges (use read_file) or sensitive files (blocked)",
        ),
        profiles=("developer", "full"),
        minimal_invocation='get_evidence(path="src/auth/service.py")',
        advanced_invocation='get_evidence(path="src/auth/service.py", symbol="AuthService.authenticate")',
        result_fields=("file", "start_line", "end_line", "symbol", "snippet", "content_hash"),
        typical_followup="verify_evidence",
        common_mistakes=(
            "Requesting evidence on sensitive files such as .env (raises SecurityError)",
        ),
        example_request="Get verifiable evidence chunks for AuthService.authenticate in src/auth/service.py.",
        example_call='get_evidence(path="src/auth/service.py", symbol="AuthService.authenticate")',
        example_interpretation="Inspect snippet, start_line..end_line, and content_hash.",
    ),
    # 38. verify_evidence
    ToolCapabilitySpec(
        tool_name="verify_evidence",
        capability="evidence_hash_verification",
        description=(
            "Verify that a cited evidence span (`file_path`, `start_line`, `end_line`) exists on disk, matches `expected_hash`, and is not stale. "
            "Use to validate whether previously retrieved evidence is still current after repository edits. "
            "Does not re-index modified files."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("file_path", "start_line", "end_line"),
        optional_inputs=("expected_hash", "symbol"),
        expected_output_type="EvidenceVerificationResult",
        relationship_types_returned=(),
        evidence_guarantees="Cryptographic hash and line-bound check against current on-disk file content.",
        does_not_prove="Does not prove semantic correctness of the code inside the span.",
        useful_situations=(
            "Confirming a cited snippet has not drifted on disk before applying a patch",
        ),
        avoid_when=(
            "Freshly retrieved evidence in a read-only session where no files were modified",
        ),
        profiles=("minimal", "developer", "full"),
        minimal_invocation='verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20)',
        advanced_invocation='verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20, symbol="AuthService")',
        result_fields=("valid", "file", "start_line", "end_line", "reason", "current_hash"),
        typical_followup="read_file if valid is False",
        common_mistakes=(
            "Continuing to rely on a snippet when verify_evidence returns valid=False",
        ),
        example_request="Verify that lines 1..20 of src/auth/service.py are still valid.",
        example_call='verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20)',
        example_interpretation="Check valid boolean and reason field.",
    ),
    # 39. get_resource_status
    ToolCapabilitySpec(
        tool_name="get_resource_status",
        capability="resource_governor_diagnostics",
        description=(
            "Return current resource governor state including memory usage, pressure level, concurrency limits, and activity mode. "
            "Use for diagnosing server resource pressure or throttling behavior. "
            "Does not inspect repository source code or symbols."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="ResourceGovernorState",
        relationship_types_returned=(),
        evidence_guarantees="Live process memory and governor concurrency telemetry.",
        does_not_prove="Does not report symbol index freshness (use get_repository_status for index freshness).",
        useful_situations=(
            "Checking if the MCP server is under memory pressure or running in CONSERVATIVE mode",
        ),
        avoid_when=(
            "Answering normal code navigation or relationship questions",
        ),
        profiles=("minimal", "developer", "full"),
        minimal_invocation="get_resource_status()",
        advanced_invocation="get_resource_status()",
        result_fields=("mode", "pressure", "rss_mb", "active_tasks"),
        typical_followup="get_repository_status",
        common_mistakes=(
            "Confusing get_resource_status (memory/CPU governor) with get_repository_status (index freshness/symbol counts)",
        ),
        example_request="Check current resource governor pressure and memory mode.",
        example_call="get_resource_status()",
        example_interpretation="Inspect mode, pressure, and rss_mb.",
    ),
    # 40. find_tests
    ToolCapabilitySpec(
        tool_name="find_tests",
        capability="test_discovery",
        description=(
            "Find test files and test functions statically linked to a target symbol (`symbol`; `canonical_id` supported as alias) via direct calls, imports, fixtures, or route invocation. "
            "Use instead of grep when answering 'what tests cover symbol X?'. "
            "Does not execute tests at runtime and never fabricates coverage from lexical similarity alone."
        ),
        task_types=(
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "max_results"),
        expected_output_type="RelatedTestsResult",
        relationship_types_returned=("TESTS", "TESTS_SYMBOL", "TESTS_ROUTE", "TESTS_PROVIDER", "TESTS_EVENT_HANDLER", "CALLS", "IMPORTS"),
        evidence_guarantees="AST/fixture/route-verified links from test functions to target symbols.",
        does_not_prove="Does not prove runtime line coverage percentage or assertion completeness.",
        useful_situations=(
            "Selecting the exact pytest/jest test functions to run after modifying a symbol",
            "Answering 'What tests cover parse_bill?' with verified test links",
        ),
        avoid_when=(
            "Editing documentation or comments with no behavioral impact",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation='find_tests(symbol="parse_bill")',
        advanced_invocation='find_tests(symbol="AuthService.authenticate", max_results=20)',
        result_fields=("test_symbol", "file", "start_line", "end_line", "relationship", "evidence_class", "confidence", "reason"),
        typical_followup="get_file on the test function if test assertions need inspection",
        common_mistakes=(
            "Guessing test coverage from filename similarity instead of calling find_tests",
        ),
        example_request="What tests cover parse_bill?",
        example_call='find_tests(symbol="parse_bill")',
        example_interpretation="Inspect each returned test symbol, its file path, and the linking relationship (e.g., TESTS_SYMBOL, TESTS_ROUTE).",
    ),
    # 41. find_routes
    ToolCapabilitySpec(
        tool_name="find_routes",
        capability="route_discovery",
        description=(
            "Find HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols across FastAPI, Flask, Django, Express, and NestJS. "
            "Use instead of grep when locating API endpoints or route handlers. "
            "Does not prove runtime middleware authentication unless traced via trace_path or get_context."
        ),
        task_types=(
            AgentTaskCategory.ROUTE_DISCOVERY.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=("framework", "method", "path"),
        expected_output_type="RouteListResult",
        relationship_types_returned=("HANDLED_BY", "ROUTE_HANDLER", "MOUNTS", "ROUTES_TO"),
        evidence_guarantees="Framework-verified route paths, HTTP methods, composed mount prefixes, and handler canonical IDs.",
        does_not_prove="Does not prove external API gateway or reverse-proxy rewrite rules outside the repository.",
        useful_situations=(
            "Answering 'Where is /api/scan-bill handled?'",
            "Discovering API entrypoints before calling trace_path to the database or service layer",
        ),
        avoid_when=(
            "Working on a pure library or CLI module with no web routes",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation="find_routes()",
        advanced_invocation='find_routes(method="POST", path="/api/scan-bill")',
        result_fields=("status", "routes", "route_path", "http_method", "handler_name", "canonical_id", "framework", "file", "line", "evidence_class"),
        typical_followup="trace_path, find_callees, or get_file on the matched handler",
        common_mistakes=(
            "Grepping for route path strings that are split across router prefix mounts instead of calling find_routes",
        ),
        example_request="Where is /api/scan-bill handled?",
        example_call='find_routes(path="/api/scan-bill")',
        example_interpretation="Read handler_name, canonical_id, and file:line from the matched route entry.",
    ),
    # 42. trace_flow
    ToolCapabilitySpec(
        tool_name="trace_flow",
        capability="bidirectional_flow_tracing",
        description=(
            "Trace multi-hop upstream callers and downstream callees around a single symbol (`symbol`; `canonical_id` supported as alias) up to `depth`. "
            "Use when exploring bidirectional execution flow around a function or handler without a known second endpoint. "
            "Does not prove runtime branch execution; use trace_path when both endpoints are known."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.RELATIONSHIP.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("canonical_id", "depth", "callers", "callees", "both"),
        expected_output_type="DirectionalCallTraceList",
        relationship_types_returned=("CALLS", "CALLED_BY", "POSSIBLE_CALLS"),
        evidence_guarantees="Bidirectional multi-hop call traversal with hop depth, confidence, and evidence_class.",
        does_not_prove="Does not prove runtime reachability under specific input conditions.",
        useful_situations=(
            "Exploring upstream callers and downstream callees around a single symbol in one call",
        ),
        avoid_when=(
            "Both start and target symbols are known (prefer trace_path)",
        ),
        profiles=("agent", "developer", "full"),
        minimal_invocation='trace_flow(symbol="place_order", depth=2)',
        advanced_invocation='trace_flow(symbol="AuthService.authenticate", depth=2, both=True)',
        result_fields=("source", "target", "relationship", "confidence", "evidence_class", "depth", "file", "start_line"),
        typical_followup="get_file on specific hops",
        common_mistakes=(
            "Using trace_flow when trace_path(from_symbol, to_symbol) would directly connect two known symbols",
        ),
        example_request="Trace the upstream and downstream call flow around place_order.",
        example_call='trace_flow(symbol="place_order", depth=2)',
        example_interpretation="Inspect each hop's source, target, depth, and evidence_class.",
    ),
    # 43. find_db_tables
    ToolCapabilitySpec(
        tool_name="find_db_tables",
        capability="database_table_discovery",
        description=(
            "Find database tables discovered across ORM models, raw SQL queries, and migrations. "
            "Use instead of grep when asking which database tables exist in this repository. "
            "Returns canonical IDs (`db.<dialect>.<schema>.<table>`), columns, ORM models, and evidence classes (`FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`, `POSSIBLE`, `UNKNOWN`). "
            "Does not connect to live databases or execute SQL."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "dialect", "schema"),
        expected_output_type="DatabaseTableListResult",
        relationship_types_returned=("MAPS_TO_TABLE", "READS_TABLE", "WRITES_TABLE", "MIGRATES_TABLE", "POSSIBLE_TABLE", "UNKNOWN_TABLE"),
        evidence_guarantees="Static ORM, SQL, and migration table definitions with canonical IDs and explicit dialect/schema uncertainty.",
        does_not_prove="Does not inspect live production database catalogs or unindexed external schemas.",
        useful_situations=(
            "Answering 'Which database tables exist in this repository?'",
            "Discovering canonical table IDs before calling get_db_table or find_db_callers",
        ),
        avoid_when=(
            "Working on a repository with zero database, ORM, or SQL usage",
        ),
        profiles=("full",),
        minimal_invocation="find_db_tables()",
        advanced_invocation='find_db_tables(table="products", dialect="postgres")',
        result_fields=("status", "tables", "count"),
        typical_followup="get_db_table, find_db_callers, or find_db_writers",
        common_mistakes=(
            "Grepping for CREATE TABLE when tables are defined via SQLAlchemy/Django/Prisma ORM models",
        ),
        example_request="Which database tables exist in this repository?",
        example_call="find_db_tables()",
        example_interpretation="Inspect tables list for canonical_id, table_name, dialect, orm_models, and evidence_class.",
    ),
    # 44. find_db_columns
    ToolCapabilitySpec(
        tool_name="find_db_columns",
        capability="database_column_discovery",
        description=(
            "Find database columns, data types, nullability, primary keys, and foreign keys across tables and ORM models. "
            "Use instead of grep when locating where a table column is defined or mapped (`MAPS_TO_COLUMN`, `HAS_PRIMARY_KEY`, `FOREIGN_KEY_TO`). "
            "Returns column definitions and source coordinates. "
            "Does not inspect live database catalogs."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "column"),
        expected_output_type="DatabaseColumnListResult",
        relationship_types_returned=("MAPS_TO_COLUMN", "HAS_PRIMARY_KEY", "FOREIGN_KEY_TO", "HAS_UNIQUE_CONSTRAINT"),
        evidence_guarantees="ORM field-to-column mappings and SQL/migration column definitions with file:line evidence.",
        does_not_prove="Does not prove live database column values or runtime constraint violations.",
        useful_situations=(
            "Answering 'What columns exist in bills?' or 'Where is column total_amount defined?'",
        ),
        avoid_when=(
            "You already called get_db_table(table=...) which includes all columns for that table",
        ),
        profiles=("full",),
        minimal_invocation='find_db_columns(table="bills")',
        advanced_invocation='find_db_columns(table="bills", column="total_amount")',
        result_fields=("status", "columns", "count"),
        typical_followup="find_db_writers, find_db_readers, or get_db_impact",
        common_mistakes=(
            "Assuming ORM attribute name always equals SQL column name without checking MAPS_TO_COLUMN",
        ),
        example_request="What columns exist in the bills table?",
        example_call='find_db_columns(table="bills")',
        example_interpretation="Inspect each column's canonical_id, data_type, is_primary_key, foreign_key_target, and file:start_line.",
    ),
    # 45. find_db_models
    ToolCapabilitySpec(
        tool_name="find_db_models",
        capability="database_orm_model_discovery",
        description=(
            "Find ORM models (SQLAlchemy, Flask-SQLAlchemy, Django ORM, SQLModel, Prisma) and their `MAPS_TO_TABLE` mappings. "
            "Use when asking which model class maps to a database table or vice versa. "
            "Returns model name, table, canonical ID, and `FRAMEWORK_VERIFIED` evidence. "
            "Does not import or execute application model modules."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=("model", "table"),
        expected_output_type="DatabaseModelListResult",
        relationship_types_returned=("MAPS_TO_TABLE", "MAPS_TO_COLUMN", "ORM_RELATION"),
        evidence_guarantees="Framework-verified ORM model declarations and table mappings.",
        does_not_prove="Does not execute dynamic metaclass table name generators.",
        useful_situations=(
            "Finding which ORM class maps to table 'products' or listing all ORM models in the repository",
        ),
        avoid_when=(
            "Repository uses only raw SQL with no ORM layer",
        ),
        profiles=("full",),
        minimal_invocation="find_db_models()",
        advanced_invocation='find_db_models(table="products")',
        result_fields=("status", "models", "count"),
        typical_followup="get_db_table or find_symbol",
        common_mistakes=(
            "Guessing pluralized table names instead of checking MAPS_TO_TABLE via find_db_models",
        ),
        example_request="Which ORM model maps to the products table?",
        example_call='find_db_models(table="products")',
        example_interpretation="Read name, table_name, framework, file, and start_line from the matched model entry.",
    ),
    # 46. find_db_queries
    ToolCapabilitySpec(
        tool_name="find_db_queries",
        capability="database_query_discovery",
        description=(
            "Find database queries (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) across ORM calls, query builders, and raw SQL strings. "
            "Use when asking which queries touch a table or what SQL a function executes. "
            "Returns `READS_TABLE`, `WRITES_TABLE`, `POSSIBLE_TABLE`, or `UNKNOWN_TABLE` with redacted snippets. "
            "Never exposes SQL literal secret parameters."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.TRACE.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "symbol", "operation"),
        expected_output_type="DatabaseQueryListResult",
        relationship_types_returned=("READS_TABLE", "WRITES_TABLE", "READS_COLUMN", "WRITES_COLUMN", "POSSIBLE_TABLE", "UNKNOWN_TABLE", "QUERIES_DATABASE"),
        evidence_guarantees="AST- and framework-verified query operations with normalized/redacted SQL snippets and uncertainty preservation.",
        does_not_prove="Does not execute SQL queries or prove query execution plans.",
        useful_situations=(
            "Listing all SELECT/INSERT/UPDATE/DELETE operations targeting a table or inside a service function",
        ),
        avoid_when=(
            "Looking for general Python function callers unrelated to database persistence",
        ),
        profiles=("full",),
        minimal_invocation='find_db_queries(table="orders")',
        advanced_invocation='find_db_queries(table="orders", operation="INSERT")',
        result_fields=("status", "queries", "count"),
        typical_followup="get_file on the query file:start_line or find_db_callers",
        common_mistakes=(
            "Treating dynamic string-interpolated SQL (`POSSIBLE_TABLE`/`UNKNOWN_TABLE`) as guaranteed static table proof",
        ),
        example_request="What database queries run against the orders table?",
        example_call='find_db_queries(table="orders")',
        example_interpretation="Inspect operation, relationship, source_symbol, columns, evidence_class, and redacted snippet.",
    ),
    # 47. find_db_callers
    ToolCapabilitySpec(
        tool_name="find_db_callers",
        capability="database_caller_discovery",
        description=(
            "Find all functions, methods, and upstream HTTP routes (`HANDLED_BY`) that read from or write to a database table. "
            "Use instead of grep when asking which code or route reaches a table. "
            "Returns direct accessors, upstream routes, relationships (`READS_TABLE`, `WRITES_TABLE`), and evidence classes. "
            "Does not prove runtime query frequency."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("table",),
        optional_inputs=(),
        expected_output_type="DatabaseCallersResult",
        relationship_types_returned=("READS_TABLE", "WRITES_TABLE", "CALLS", "HANDLED_BY", "POSSIBLE_TABLE"),
        evidence_guarantees="Direct table readers/writers plus transitive upstream callers and HTTP route entrypoints.",
        does_not_prove="Does not prove runtime execution frequency unless paired with get_runtime_trace.",
        useful_situations=(
            "Answering 'Which route or service accesses the products table?'",
        ),
        avoid_when=(
            "You only want write mutations (prefer find_db_writers) or only reads (prefer find_db_readers)",
        ),
        profiles=("full",),
        minimal_invocation='find_db_callers(table="products")',
        advanced_invocation='find_db_callers(table="products")',
        result_fields=("status", "table", "direct_accessors", "upstream_routes", "count"),
        typical_followup="trace_path or get_file on the accessor symbol",
        common_mistakes=(
            "Grepping for table names in route files when routes call services that call repositories",
        ),
        example_request="Which routes and functions access the products table?",
        example_call='find_db_callers(table="products")',
        example_interpretation="Inspect direct_accessors and upstream_routes for symbol, relationship, and file:start_line.",
    ),
    # 48. find_db_writers
    ToolCapabilitySpec(
        tool_name="find_db_writers",
        capability="database_writer_discovery",
        description=(
            "Find all symbols and queries that write (`INSERT`, `UPDATE`, `DELETE`) to a database table or column (`WRITES_TABLE`, `WRITES_COLUMN`). "
            "Use when investigating data mutations, state changes, or write blast radius. "
            "Returns writer symbols, operations, file:line citations, and redacted snippets. "
            "Does not execute database transactions."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "column"),
        expected_output_type="DatabaseWritersResult",
        relationship_types_returned=("WRITES_TABLE", "WRITES_COLUMN"),
        evidence_guarantees="Verified INSERT/UPDATE/DELETE and ORM mutation call sites with source coordinates.",
        does_not_prove="Does not prove whether a database transaction commits or rolls back at runtime.",
        useful_situations=(
            "Answering 'Which service writes to the products table or updates inventory.quantity?'",
        ),
        avoid_when=(
            "Investigating read-only SELECT queries (use find_db_readers)",
        ),
        profiles=("full",),
        minimal_invocation='find_db_writers(table="products")',
        advanced_invocation='find_db_writers(table="inventory", column="quantity")',
        result_fields=("status", "writers", "count"),
        typical_followup="find_callers on the writer symbol or get_file on the mutation lines",
        common_mistakes=(
            "Confusing read queries with write mutations when debugging corrupted state",
        ),
        example_request="Which functions write to the products table?",
        example_call='find_db_writers(table="products")',
        example_interpretation="Inspect writers for symbol, operation (INSERT/UPDATE/DELETE), columns, file, and start_line.",
    ),
    # 49. find_db_readers
    ToolCapabilitySpec(
        tool_name="find_db_readers",
        capability="database_reader_discovery",
        description=(
            "Find all symbols and queries that read (`SELECT`, `.query()`, `.objects.filter()`, `.findMany()`) from a database table or column (`READS_TABLE`, `READS_COLUMN`). "
            "Use when tracing where table data is consumed across services and views. "
            "Returns reader symbols, operations, and evidence classes. "
            "Does not prove runtime cache hits."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.TRACE.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "column"),
        expected_output_type="DatabaseReadersResult",
        relationship_types_returned=("READS_TABLE", "READS_COLUMN", "POSSIBLE_TABLE"),
        evidence_guarantees="Verified SELECT and ORM read query sites with file and line spans.",
        does_not_prove="Does not prove whether results are served from an in-memory cache at runtime.",
        useful_situations=(
            "Answering 'What code reads from users or reads column email?'",
        ),
        avoid_when=(
            "Looking only for INSERT/UPDATE/DELETE mutations (use find_db_writers)",
        ),
        profiles=("full",),
        minimal_invocation='find_db_readers(table="users")',
        advanced_invocation='find_db_readers(table="users", column="email")',
        result_fields=("status", "readers", "count"),
        typical_followup="get_file on the reader symbol or get_db_impact",
        common_mistakes=(
            "Assuming a function that imports a model always reads from its table without checking READS_TABLE",
        ),
        example_request="Which functions read from the users table?",
        example_call='find_db_readers(table="users")',
        example_interpretation="Inspect readers for symbol, table, columns, evidence_class, and file:start_line.",
    ),
    # 50. find_db_relationships
    ToolCapabilitySpec(
        tool_name="find_db_relationships",
        capability="database_relationship_discovery",
        description=(
            "Find database schema and ORM relationships (`FOREIGN_KEY_TO`, `ORM_RELATION`, `MAPS_TO_TABLE`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `MIGRATES_TABLE`). "
            "Use when inspecting foreign keys, table joins, or model associations. "
            "Preserves explicit database relationship types and never collapses them into generic `DEPENDS_ON`."
        ),
        task_types=(
            AgentTaskCategory.RELATIONSHIP.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=("table",),
        expected_output_type="DatabaseRelationshipsResult",
        relationship_types_returned=(
            "MAPS_TO_TABLE",
            "MAPS_TO_COLUMN",
            "FOREIGN_KEY_TO",
            "ORM_RELATION",
            "HAS_PRIMARY_KEY",
            "HAS_INDEX",
            "HAS_UNIQUE_CONSTRAINT",
            "HAS_CHECK_CONSTRAINT",
            "MIGRATES_TABLE",
        ),
        evidence_guarantees="Explicit schema and ORM relationship edges with canonical source/target IDs and source coordinates.",
        does_not_prove="Does not prove unindexed database triggers on external servers.",
        useful_situations=(
            "Answering 'What foreign keys or ORM relationships exist for orders?'",
        ),
        avoid_when=(
            "Looking for function-to-function call edges (use find_callers/find_callees)",
        ),
        profiles=("full",),
        minimal_invocation="find_db_relationships()",
        advanced_invocation='find_db_relationships(table="orders")',
        result_fields=("status", "relationships", "count"),
        typical_followup="get_db_table or get_db_impact",
        common_mistakes=(
            "Collapsing FOREIGN_KEY_TO or ORM_RELATION into generic DEPENDS_ON edges",
        ),
        example_request="What foreign key and ORM relationships exist on the orders table?",
        example_call='find_db_relationships(table="orders")',
        example_interpretation="Inspect source, target, relationship (e.g. FOREIGN_KEY_TO, ORM_RELATION), and evidence_class.",
    ),
    # 51. get_db_table
    ToolCapabilitySpec(
        tool_name="get_db_table",
        capability="database_table_details",
        description=(
            "Return complete structural details for a database table including columns, primary keys, foreign keys, indexes, constraints, ORM models, readers, writers, migrations, and upstream routes. "
            "Use when inspecting a specific table's schema and code usage in one call. "
            "Does not query live database servers."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("table",),
        optional_inputs=(),
        expected_output_type="DatabaseTableDetailResult",
        relationship_types_returned=(
            "MAPS_TO_TABLE",
            "MAPS_TO_COLUMN",
            "READS_TABLE",
            "WRITES_TABLE",
            "FOREIGN_KEY_TO",
            "HAS_PRIMARY_KEY",
            "HAS_INDEX",
            "MIGRATES_TABLE",
            "ORM_RELATION",
        ),
        evidence_guarantees="Consolidated static schema, ORM mapping, reader/writer, route, and migration evidence for the table.",
        does_not_prove="Does not return live table row counts or production data rows.",
        useful_situations=(
            "Inspecting everything known about a database table (columns, models, readers, writers, routes, migrations)",
        ),
        avoid_when=(
            "Table name is unknown (call find_db_tables first)",
        ),
        profiles=("full",),
        minimal_invocation='get_db_table(table="products")',
        advanced_invocation='get_db_table(table="products")',
        result_fields=("status", "table", "canonical_id", "dialect", "schema", "columns", "primary_keys", "foreign_keys", "indexes", "orm_models", "readers", "writers", "migrations", "upstream_routes"),
        typical_followup="get_db_impact or get_file on model/migration files",
        common_mistakes=(
            "Reading multiple migration files manually before calling get_db_table",
        ),
        example_request="Show me the schema, models, readers, and writers for the products table.",
        example_call='get_db_table(table="products")',
        example_interpretation="Inspect columns, primary_keys, foreign_keys, orm_models, readers, writers, and upstream_routes.",
    ),
    # 52. get_db_schema
    ToolCapabilitySpec(
        tool_name="get_db_schema",
        capability="database_schema_overview",
        description=(
            "Return a repository-wide database schema summary including all discovered tables, columns, ORM models, foreign keys, and migrations. "
            "Use for database architecture overviews or schema audits. "
            "Preserves `UNKNOWN` dialect and schema when not statically provable and never guesses database names."
        ),
        task_types=(
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.EXPLANATION.value,
        ),
        required_inputs=(),
        optional_inputs=("dialect", "schema"),
        expected_output_type="DatabaseSchemaOverviewResult",
        relationship_types_returned=("MAPS_TO_TABLE", "FOREIGN_KEY_TO", "ORM_RELATION", "MIGRATES_TABLE", "READS_ENV"),
        evidence_guarantees="Repository-wide database topology with explicit dialect/schema uncertainty and redacted env metadata.",
        does_not_prove="Does not connect to external database servers or read `.env` secret values.",
        useful_situations=(
            "Understanding the complete data model, tables, foreign keys, and migration history of a repository",
        ),
        avoid_when=(
            "Only one known table needs inspection (prefer get_db_table)",
        ),
        profiles=("full",),
        minimal_invocation="get_db_schema()",
        advanced_invocation='get_db_schema(dialect="postgres", schema="public")',
        result_fields=("status", "dialects", "schemas", "tables", "orm_models", "foreign_keys", "migrations", "env_variables"),
        typical_followup="get_db_table on specific tables of interest",
        common_mistakes=(
            "Assuming postgres/public when the repository only uses generic ORM declarations (`UNKNOWN` dialect/schema)",
        ),
        example_request="Give me an overview of the entire database schema and foreign keys in this repo.",
        example_call="get_db_schema()",
        example_interpretation="Inspect tables, orm_models, foreign_keys, migrations, and env_variables.",
    ),
    # 53. get_db_impact
    ToolCapabilitySpec(
        tool_name="get_db_impact",
        capability="database_change_impact",
        description=(
            "Compute bidirectional Code <-> Database change impact for a table or column, returning affected ORM models, readers, writers, upstream HTTP routes, migrations, and statically linked tests. "
            "Use before renaming or altering a database table or column. "
            "Does not execute database migrations or tests."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("table", "column"),
        expected_output_type="DatabaseImpactResult",
        relationship_types_returned=("MAPS_TO_TABLE", "MAPS_TO_COLUMN", "READS_TABLE", "WRITES_TABLE", "READS_COLUMN", "WRITES_COLUMN", "FOREIGN_KEY_TO", "MIGRATES_TABLE", "TESTS"),
        evidence_guarantees="Bidirectional impact across ORM models, queries, service callers, HTTP routes, migrations, and tests.",
        does_not_prove="Does not prove runtime migration locking or production table size.",
        useful_situations=(
            "Answering 'What breaks if I rename or drop column shop_id on products?'",
        ),
        avoid_when=(
            "Analyzing impact of a pure non-database helper function (use analyze_impact)",
        ),
        profiles=("full",),
        minimal_invocation='get_db_impact(table="products")',
        advanced_invocation='get_db_impact(table="products", column="shop_id")',
        result_fields=("status", "table", "column", "affected_models", "affected_readers", "affected_writers", "affected_routes", "affected_migrations", "affected_tests"),
        typical_followup="get_file on affected models/writers and find_tests",
        common_mistakes=(
            "Renaming a database column in an ORM model without checking raw SQL readers/writers via get_db_impact",
        ),
        example_request="What code, routes, and tests are impacted if products.shop_id changes?",
        example_call='get_db_impact(table="products", column="shop_id")',
        example_interpretation="Inspect affected_models, affected_readers, affected_writers, affected_routes, affected_migrations, and affected_tests.",
    ),
    # 54. ingest_runtime_traces
    ToolCapabilitySpec(
        tool_name="ingest_runtime_traces",
        capability="runtime_trace_ingestion",
        description=(
            "Ingest optional runtime observation traces (OpenTelemetry JSON, structured JSON/JSONL events, or SQL query logs) into CodeGraph's `RUNTIME_OBSERVED` layer. "
            "Use when grounding static analysis with recorded runtime traces. "
            "Automatically strips headers/cookies/bodies, redacts SQL bind parameters and secrets, and never converts runtime observations into static `AST_VERIFIED` proof."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=(),
        optional_inputs=("source_path", "format", "payload", "max_events", "sample_rate"),
        expected_output_type="RuntimeIngestResult",
        relationship_types_returned=("CALLS", "HANDLED_BY", "READS_TABLE", "WRITES_TABLE", "QUERIES_DATABASE"),
        evidence_guarantees="Sanitized RUNTIME_OBSERVED edges with observation_count, first_seen, last_seen, and runtime_generation.",
        does_not_prove="Never proves static AST_VERIFIED relationships and never launches or instruments the user application.",
        useful_situations=(
            "Loading recorded OpenTelemetry spans, JSONL runtime events, or SQL logs before calling get_runtime_trace or reconcile_static_runtime",
        ),
        avoid_when=(
            "No runtime trace file or payload is available (static tools work without runtime data)",
        ),
        profiles=("full",),
        minimal_invocation='ingest_runtime_traces(source_path="traces/otel.json")',
        advanced_invocation='ingest_runtime_traces(source_path="traces/events.jsonl", format="jsonl", max_events=1000, sample_rate=1.0)',
        result_fields=("status", "runtime_generation", "events_ingested", "edges_recorded", "redacted_fields"),
        typical_followup="get_runtime_trace or reconcile_static_runtime",
        common_mistakes=(
            "Treating RUNTIME_OBSERVED edges as static AST_VERIFIED proof",
        ),
        example_request="Ingest the OpenTelemetry trace file traces/scan_bill.json.",
        example_call='ingest_runtime_traces(source_path="traces/scan_bill.json")',
        example_interpretation="Confirm status=='ok', events_ingested, and runtime_generation.",
    ),
    # 55. get_runtime_trace
    ToolCapabilitySpec(
        tool_name="get_runtime_trace",
        capability="runtime_trace_interrogation",
        description=(
            "Retrieve aggregated runtime execution edges (`RUNTIME_OBSERVED`) and reverse maps (`table -> runtime writers/readers`, `route -> runtime tables`) with `observation_count`, `first_seen`, `last_seen`, and `runtime_generation`. "
            "Use when asking what actually happened at runtime. "
            "Does not treat unobserved paths as impossible."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("route", "symbol", "table"),
        expected_output_type="RuntimeTraceResult",
        relationship_types_returned=("CALLS", "HANDLED_BY", "READS_TABLE", "WRITES_TABLE", "QUERIES_DATABASE"),
        evidence_guarantees="Aggregated RUNTIME_OBSERVED edges with observation counts, timestamps, and sanitized SQL templates.",
        does_not_prove="Does not prove that unobserved static branches cannot execute under other inputs.",
        useful_situations=(
            "Answering 'What happened at runtime when /api/scan-bill ran?' or 'Which runtime queries wrote to bills?'",
        ),
        avoid_when=(
            "No runtime traces have been ingested into the repository index",
        ),
        profiles=("full",),
        minimal_invocation="get_runtime_trace()",
        advanced_invocation='get_runtime_trace(route="/api/scan-bill", table="bills")',
        result_fields=("status", "edges", "observations", "reverse_maps", "count"),
        typical_followup="reconcile_static_runtime or get_file",
        common_mistakes=(
            "Claiming a branch is dead code merely because observation_count is 0 in a single trace sample",
        ),
        example_request="What happened at runtime when /api/scan-bill executed?",
        example_call='get_runtime_trace(route="/api/scan-bill")',
        example_interpretation="Inspect edges (`evidence_class='RUNTIME_OBSERVED'`), observation_count, and reverse_maps.",
    ),
    # 56. reconcile_static_runtime
    ToolCapabilitySpec(
        tool_name="reconcile_static_runtime",
        capability="static_runtime_reconciliation",
        description=(
            "Reconcile static repository edges against ingested runtime observations, classifying edges into `CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`, `NOT_OBSERVED_AT_RUNTIME`, and `RUNTIME_ONLY_OBSERVED`. "
            "Use when comparing static code analysis with runtime behavior. "
            "Never treats `NOT_OBSERVED_AT_RUNTIME` as proof that a path cannot execute."
        ),
        task_types=(
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DIAGNOSTIC.value,
        ),
        required_inputs=(),
        optional_inputs=("symbol", "route", "table"),
        expected_output_type="StaticRuntimeReconciliationResult",
        relationship_types_returned=("CALLS", "HANDLED_BY", "READS_TABLE", "WRITES_TABLE", "POSSIBLE_CALLS", "POSSIBLE_TABLE"),
        evidence_guarantees="Explicit four-bucket reconciliation preserving both static evidence classes and RUNTIME_OBSERVED / RUNTIME_UNOBSERVED states.",
        does_not_prove="Never overwrites static AST_VERIFIED edges and never treats NOT_OBSERVED_AT_RUNTIME as dead-code proof.",
        useful_situations=(
            "Answering 'Where do static and runtime paths differ?' or 'Which dynamic calls were observed only at runtime?'",
        ),
        avoid_when=(
            "Only static analysis is needed and no runtime traces have been ingested",
        ),
        profiles=("full",),
        minimal_invocation="reconcile_static_runtime()",
        advanced_invocation='reconcile_static_runtime(route="/api/scan-bill", table="bills")',
        result_fields=("status", "confirmed_runtime_paths", "static_runtime_conflicts", "not_observed_at_runtime", "runtime_only_observed", "summary"),
        typical_followup="get_file on runtime_only_observed or static_runtime_conflicts locations",
        common_mistakes=(
            "Deleting code in NOT_OBSERVED_AT_RUNTIME without checking if it handles rare error or admin paths",
        ),
        example_request="Where does the runtime behavior of /api/scan-bill differ from static analysis?",
        example_call='reconcile_static_runtime(route="/api/scan-bill")',
        example_interpretation="Inspect confirmed_runtime_paths, static_runtime_conflicts, not_observed_at_runtime, and runtime_only_observed.",
    ),
    # 57. get_git_state
    ToolCapabilitySpec(
        tool_name="get_git_state",
        capability="git_state_tracking",
        description=(
            "Track current Git branch, HEAD commit, indexed commit, working tree modifications, staged files, and explicit freshness states (CLEAN, DIRTY, STALE, REINDEXING, ERROR). "
            "Use when asking if the index is up to date, which files changed, or what git branch is active. "
            "Does not perform a full repository scan when an incremental update is safe."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="GitStateReport",
        relationship_types_returned=(),
        evidence_guarantees="Deterministic Git rev-parse and status porcelain v1 inspection.",
        does_not_prove="Does not prove semantic impact; reports file-level and commit-level freshness.",
        useful_situations=(
            "Checking if repository has uncommitted changes or if re-indexing is required after pulling git commits",
        ),
        avoid_when=(
            "You need symbol-level blast radius rather than repository freshness status",
        ),
        profiles=("full",),
        minimal_invocation="get_git_state()",
        advanced_invocation="get_git_state()",
        result_fields=("is_git", "branch", "current_head", "indexed_head", "freshness", "working_tree", "reindex_required", "detail"),
        typical_followup="compare_git or get_change_impact if files were modified",
        common_mistakes=(
            "Assuming CLEAN means all tests pass; CLEAN only indicates index matches working tree and HEAD",
        ),
        example_request="Is my CodeGraph index currently up to date with Git HEAD?",
        example_call="get_git_state()",
        example_interpretation="Inspect freshness (CLEAN, DIRTY, or STALE) and working_tree.modified_files.",
    ),
    # 58. compare_git
    ToolCapabilitySpec(
        tool_name="compare_git",
        capability="structural_git_diff",
        description=(
            "Compare two Git revisions, commits, or branches structurally. "
            "Detects added/deleted/modified/renamed files, AST symbol changes, relationship diffs, routes, and affected tests. "
            "Use when comparing branches or commits structurally. "
            "Does not execute repository code."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=("base", "head", "branch_comparison"),
        expected_output_type="StructuralDiffResult",
        relationship_types_returned=("CALLS", "IMPORTS", "ROUTES_TO", "TESTS"),
        evidence_guarantees="AST parsing of before/after revisions with exact file:line citations and similarity scores.",
        does_not_prove="Does not execute code or run test assertions.",
        useful_situations=(
            "Understanding structural changes between two branches or commits without parsing raw diff text",
        ),
        avoid_when=(
            "You only need high-level commit log summaries without AST symbol diffs",
        ),
        profiles=("full",),
        minimal_invocation='compare_git(base="HEAD~1", head="HEAD")',
        advanced_invocation='compare_git(base="main", head="my-feature", branch_comparison=True)',
        result_fields=("base_ref", "head_ref", "added_files", "deleted_files", "modified_files", "renamed_files", "added_symbols", "removed_symbols", "changed_symbols", "changed_routes", "affected_tests"),
        typical_followup="get_change_impact to find downstream callers of changed symbols",
        common_mistakes=(
            "Expecting compare_git to format unified diff text; it outputs AST and structural symbol objects",
        ),
        example_request="What symbols, routes, and tests changed structurally between main and this branch?",
        example_call='compare_git(base="main", head="HEAD", branch_comparison=True)',
        example_interpretation="Inspect packages, modules, changed_symbols, and changed_routes.",
    ),
    # 59. get_change_impact
    ToolCapabilitySpec(
        tool_name="get_change_impact",
        capability="deep_change_impact_analysis",
        description=(
            "Compute deep downstream change impact across callers, callees, framework routes, covering tests, mutating database queries, and monorepo packages. "
            "Returns ranked entities with explicit confidence (FACT, POSSIBLE, UNKNOWN) and blast radius score. "
            "Use when evaluating ripple effects of git commits. "
            "Does not execute repository test suites."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.TEST_DISCOVERY.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("base", "head", "max_depth", "max_results"),
        expected_output_type="DeepImpactResult",
        relationship_types_returned=("CALLS", "CALLED_BY", "ROUTES_TO", "TESTS", "WRITES_TABLE", "READS_TABLE", "DEPENDS_ON"),
        evidence_guarantees="Complete graph traversal connecting modified AST symbols to callers, routes, tests, and DB queries.",
        does_not_prove="Does not prove runtime execution frequencies; reports static graph reachability.",
        useful_situations=(
            "Evaluating what code, routes, database writes, and tests will break if git changes are merged",
        ),
        avoid_when=(
            "No git changes exist and you are analyzing a single untouched function",
        ),
        profiles=("full",),
        minimal_invocation="get_change_impact()",
        advanced_invocation='get_change_impact(base="HEAD~3", head="HEAD", max_depth=2, max_results=50)',
        result_fields=("base_ref", "head_ref", "changed_files", "changed_symbols", "direct_callers", "transitive_callers", "affected_routes", "affected_tests", "db_writers", "blast_radius_score"),
        typical_followup="find_tests or get_file on affected_routes / direct_callers",
        common_mistakes=(
            "Relying solely on textual search instead of graph reachability for blast radius analysis",
        ),
        example_request="What is the blast radius and which routes, callers, and tests are affected by my branch?",
        example_call='get_change_impact(base="HEAD~1", head="HEAD")',
        example_interpretation="Inspect blast_radius_score, direct_callers, affected_routes, and affected_tests.",
    ),
    # 60. check_context_freshness
    ToolCapabilitySpec(
        tool_name="check_context_freshness",
        capability="context_freshness_validation",
        description=(
            "Validate whether a previously compiled context packet or task context is still VALID, PARTIALLY_STALE, or STALE. "
            "Guarantees that changes to unrelated files keep context VALID. "
            "Use when checking if previously compiled context remains valid after edits. "
            "Does not invalidate context when only unrelated files change."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=("task", "context_packet"),
        expected_output_type="ContextFreshnessResult",
        relationship_types_returned=(),
        evidence_guarantees="Intersection of Git diff line/file changes against exact symbol and file references in context packet.",
        does_not_prove="Does not recompile context; reports freshness validity and recommended action.",
        useful_situations=(
            "Checking if previously cached or generated AI context packet is still safe to use after editing files",
        ),
        avoid_when=(
            "Compiling brand-new context from scratch for an initial prompt",
        ),
        profiles=("full",),
        minimal_invocation='check_context_freshness(task="Fix auth timeout")',
        advanced_invocation="check_context_freshness(context_packet=my_packet)",
        result_fields=("status", "base_commit", "current_head", "repository_dirty", "context_files", "changed_relevant_files", "unrelated_changed_files", "invalidated_symbols", "reason", "recommended_action"),
        typical_followup="get_context if status is STALE or PARTIALLY_STALE",
        common_mistakes=(
            "Assuming any file change invalidates context; unrelated changes leave context VALID",
        ),
        example_request="Is my current context packet still valid after my recent git modifications?",
        example_call='check_context_freshness(task="Fix auth timeout")',
        example_interpretation="Inspect status: VALID means safe to proceed, STALE means recompile required.",
    ),
    # 61. trace_symbol_history
    ToolCapabilitySpec(
        tool_name="trace_symbol_history",
        capability="symbol_history_tracing",
        description=(
            "Trace deterministic symbol evolution across Git history: introduced, modified, moved across files, renamed, or deleted. "
            "Uses AST structure and body hashes to differentiate FACT from POSSIBLE/AMBIGUOUS renames. "
            "Use when discovering when a symbol was added, moved, or renamed. "
            "Does not guess ambiguous renames without evidence."
        ),
        task_types=(
            AgentTaskCategory.SYMBOL_LOOKUP.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("symbol",),
        optional_inputs=("path", "max_commits"),
        expected_output_type="SymbolHistoryResult",
        relationship_types_returned=(),
        evidence_guarantees="Git log history correlated with AST body hashes and file rename metadata.",
        does_not_prove="Does not guarantee intent behind refactors; reports structural code evolution.",
        useful_situations=(
            "Tracing when a function was introduced, modified, moved to a different module, or renamed",
        ),
        avoid_when=(
            "You only need current static callers and callees in the working tree",
        ),
        profiles=("full",),
        minimal_invocation='trace_symbol_history(symbol="AuthService")',
        advanced_invocation='trace_symbol_history(symbol="AuthService", path="src/auth.py", max_commits=20)',
        result_fields=("symbol", "current_path", "events", "total_commits_evaluated", "status", "detail"),
        typical_followup="get_symbol or get_file on historical commit",
        common_mistakes=(
            "Assuming all renames are FACT; ambiguous renames are explicitly flagged as AMBIGUOUS or POSSIBLE",
        ),
        example_request="Trace the history and renames of AuthService across git commits.",
        example_call='trace_symbol_history(symbol="AuthService")',
        example_interpretation="Inspect events list for INTRODUCED, MODIFIED, MOVED, or RENAMED occurrences.",
    ),
    # 62. detect_semantic_conflicts
    ToolCapabilitySpec(
        tool_name="detect_semantic_conflicts",
        capability="semantic_merge_conflict_detection",
        description=(
            "Detect semantic and contract conflicts between Git branches (calling deleted symbols, broken call signatures, or missing route handlers). "
            "Use when verifying whether branches can be safely merged without semantic breakage. "
            "Does not report false conflicts when branches are structurally compatible."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.ARCHITECTURE.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=("base_branch", "head_branch"),
        expected_output_type="SemanticConflictResult",
        relationship_types_returned=("CALLS", "IMPORTS", "ROUTES_TO"),
        evidence_guarantees="Deterministic cross-branch AST call-site and definition verification.",
        does_not_prove="Does not execute code; reports contract incompatibility between revisions.",
        useful_situations=(
            "Checking if a feature branch introduces calls to symbols deleted or modified on main",
            "Pre-merge validation before merging PRs to prevent semantic regression",
        ),
        avoid_when=(
            "Branches are known to be identical or when checking working tree cleanliness",
        ),
        profiles=("full",),
        minimal_invocation='detect_semantic_conflicts(base_branch="main", head_branch="feature")',
        advanced_invocation='detect_semantic_conflicts(base_branch="main", head_branch="HEAD")',
        result_fields=("base_branch", "head_branch", "has_conflicts", "total_conflicts", "conflicts", "summary"),
        typical_followup="get_file or get_symbol on conflicted symbols",
        common_mistakes=(
            "Assuming Git text merge passes mean no semantic conflicts; semantic conflicts occur even with 0 text conflicts",
        ),
        example_request="Are there any semantic merge conflicts between main and this branch?",
        example_call='detect_semantic_conflicts(base_branch="main", head_branch="HEAD")',
        example_interpretation="Inspect has_conflicts and conflicts list for DELETED_SYMBOL_REFERENCED or CALL_SIGNATURE_MISMATCH.",
    ),
    # 49. safe_rename
    ToolCapabilitySpec(
        tool_name="safe_rename",
        capability="ast_symbol_refactor",
        description=(
            "Perform a deterministic, syntax-validated, transaction-safe AST rename of a symbol across the repository. "
            "Use when renaming a function, method, or class across multiple files safely with in-memory preview diffs. "
            "Does not prove runtime equivalence beyond AST syntax validation and statically verified references."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("target", "new_name"),
        optional_inputs=("dry_run", "force_uncertain"),
        expected_output_type="RefactorResult",
        relationship_types_returned=("DEFINES", "CALLS", "IMPORTS"),
        evidence_guarantees="Token-exact replacement with in-memory ast.parse syntax validation and atomic rollback manifest.",
        does_not_prove="Does not prove semantic preservation beyond AST syntax validation and statically verified references.",
        useful_situations=(
            "Renaming a function, method, or class safely across multiple files without breaking references",
            "Previewing exact diffs before executing an atomic codebase refactoring",
        ),
        avoid_when=(
            "Trivial single-file edit of a local variable inside an already-open function",
        ),
        profiles=("full",),
        minimal_invocation='safe_rename(target="AuthService", new_name="AuthenticationService", dry_run=True)',
        advanced_invocation='safe_rename(target="AuthService.verify", new_name="verify_token", dry_run=False, force_uncertain=False)',
        result_fields=("status", "target_symbol", "new_name", "risk", "files_changed", "spans_count", "diffs", "rollback_id", "errors"),
        typical_followup="rollback_refactor if undo needed, or find_tests to run affected test suite",
        common_mistakes=(
            "Applying without inspecting preview diffs when dry_run=True",
            "Using invalid Python identifiers with spaces or keywords",
        ),
        example_request="Rename AuthService to AuthenticationService and preview all diffs.",
        example_call='safe_rename(target="AuthService", new_name="AuthenticationService", dry_run=True)',
        example_interpretation="Inspect status=='READY', diffs, risk=='LOW', and affected_tests before applying.",
    ),
    # 50. rollback_refactor
    ToolCapabilitySpec(
        tool_name="rollback_refactor",
        capability="refactor_transaction_rollback",
        description=(
            "Atomically rollback an applied refactoring transaction using its rollback manifest ID. "
            "Use when reverting an applied refactoring transaction to restore original source files cleanly. "
            "Does not restore files if they were modified externally after refactoring was applied."
        ),
        task_types=(
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=("transaction_id",),
        optional_inputs=(),
        expected_output_type="RefactorResult",
        relationship_types_returned=(),
        evidence_guarantees="Precondition SHA-256 validation and atomic file replacement with os.replace.",
        does_not_prove="Cannot rollback if files were modified externally after refactoring was applied.",
        useful_situations=(
            "Undoing an applied refactoring transaction cleanly to restore original code bytes",
        ),
        avoid_when=(
            "Transaction was not applied or files have subsequent manual edits",
        ),
        profiles=("full",),
        minimal_invocation='rollback_refactor(transaction_id="rf_abc123")',
        advanced_invocation='rollback_refactor(transaction_id="rf_abc123")',
        result_fields=("status", "target_symbol", "new_name", "files_changed", "rollback_id", "errors"),
        typical_followup="get_repository_status to verify repository state",
        common_mistakes=(
            "Calling rollback after modifying the files externally (which blocks rollback for safety)",
        ),
        example_request="Undo the refactor with transaction ID rf_12345.",
        example_call='rollback_refactor(transaction_id="rf_12345")',
        example_interpretation="Inspect status=='ROLLED_BACK' and files_changed.",
    ),
    # 65. get_live_services
    ToolCapabilitySpec(
        tool_name="get_live_services",
        capability="live_service_discovery",
        description=(
            "Detect and attribute active localhost services, ports, PIDs, frameworks, and workspace sub-packages with zero idle CPU. "
            "Use when diagnosing running dev servers or multi-service architectures. "
            "Does not prove live HTTP response payloads or application layer health."
        ),
        task_types=(
            AgentTaskCategory.DIAGNOSTIC.value,
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="Kernel socket table inspection and static configuration discovery with 5-second TTL cache.",
        does_not_prove="Does not prove live HTTP response payloads or application layer health.",
        useful_situations=(
            "Identifying running backend and frontend dev servers",
            "Attributing localhost ports to workspace sub-directories",
        ),
        avoid_when=(
            "Dev servers are not running or only static AST analysis is required",
        ),
        profiles=("full",),
        minimal_invocation="get_live_services()",
        advanced_invocation="get_live_services()",
        result_fields=("live_services", "configured_services", "count"),
        typical_followup="get_distributed_trace or list_routes",
        common_mistakes=(
            "Polling get_live_services in a rapid spin loop instead of relying on the 5-second TTL cache",
        ),
        example_request="What dev servers are running on localhost?",
        example_call="get_live_services()",
        example_interpretation="Inspect live_services for active listening ports and PIDs.",
    ),
    # 66. check_db_drift
    ToolCapabilitySpec(
        tool_name="check_db_drift",
        capability="database_schema_drift",
        description=(
            "Detect database schema drift between migration files, live database state, and code ORM models with zero idle CPU. "
            "Flags unmapped tables, missing columns, and migration version state. "
            "Use when verifying whether database migrations are up to date with code models. "
            "Does not execute SQL data assertions or validate column constraints against live row data."
        ),
        task_types=(
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="Comparison of SQLite/PostgreSQL schemas and migration folder state with 5-second TTL cache.",
        does_not_prove="Does not execute SQL data assertions or validate column constraints against live row data.",
        useful_situations=(
            "Verifying whether database migrations are up to date with code models",
            "Diagnosing missing table or column runtime errors",
        ),
        avoid_when=(
            "Project does not utilize SQL databases or database models",
        ),
        profiles=("full",),
        minimal_invocation="check_db_drift()",
        advanced_invocation="check_db_drift()",
        result_fields=("status", "unmapped_tables", "missing_columns", "migration_version", "is_drifted"),
        typical_followup="get_db_schema or find_db_tables",
        common_mistakes=(
            "Assuming check_db_drift executes database migrations rather than inspecting drift",
        ),
        example_request="Check if our database schema has drifted from migrations.",
        example_call="check_db_drift()",
        example_interpretation="Check if is_drifted is true and review missing_columns.",
    ),
    # 67. check_route_schema_drift
    ToolCapabilitySpec(
        tool_name="check_route_schema_drift",
        capability="route_schema_validation_drift",
        description=(
            "Use when detecting schema validation drift between a route/handler input schema (Pydantic BaseModel, Django Form, DRF Serializer) "
            "and destination database table columns. "
            "Flags MISSING_REQUIRED_COLUMN, NULLABILITY_MISMATCH, TYPE_INCOMPATIBILITY, LENGTH_CONSTRAINT_DRIFT, and UNUSED_SCHEMA_FIELD. "
            "Does not execute live requests."
        ),
        task_types=(
            AgentTaskCategory.DEBUG.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
        ),
        required_inputs=(),
        optional_inputs=("route", "handler", "table", "schema"),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="Deterministic AST and database schema entity comparison.",
        does_not_prove="Does not execute live HTTP requests or live SQL transactions.",
        useful_situations=(
            "Validating route request payload models against destination database columns",
            "Preventing runtime NOT NULL constraint failures and type mismatches before deployment",
        ),
        avoid_when=(
            "Inspecting static code symbols unrelated to HTTP routes or database persistence",
        ),
        profiles=("full",),
        minimal_invocation='check_route_schema_drift(route="/api/v1/orders/checkout")',
        advanced_invocation='check_route_schema_drift(route="/api/v1/orders/checkout", table="orders", schema="CheckoutRequest")',
        result_fields=("status", "route_or_handler", "target_table", "schema_name", "drift_count", "critical_count", "warning_count", "info_count", "issues"),
        typical_followup="get_route_db_lineage or get_db_table",
        common_mistakes=(
            "Assuming check_route_schema_drift executes HTTP requests rather than inspecting static schemas",
        ),
        example_request="Check for schema drift on our checkout route.",
        example_call='check_route_schema_drift(route="/api/v1/orders/checkout")',
        example_interpretation="Review issues for MISSING_REQUIRED_COLUMN or NULLABILITY_MISMATCH.",
    ),
    # 68. get_distributed_trace
    ToolCapabilitySpec(
        tool_name="get_distributed_trace",
        capability="distributed_trace_reconstruction",
        description=(
            "Stitch and reconstruct multi-service distributed execution trees across frontend, backend, and database boundaries for a specific W3C trace ID. "
            "Use when tracing cross-service requests or debugging multi-service latency bottlenecks. "
            "Does not capture unobserved code paths or untraced sidecar requests."
        ),
        task_types=(
            AgentTaskCategory.TRACE.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=("trace_id",),
        optional_inputs=(),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="W3C traceparent stitching across multi-service runtime observations.",
        does_not_prove="Does not capture unobserved code paths or untraced sidecar requests.",
        useful_situations=(
            "Tracing an end-to-end user request from UI click to backend SQL execution",
            "Pinpointing which service failed in a distributed microservice workflow",
        ),
        avoid_when=(
            "Static code traversal is sufficient or dev servers have not captured runtime traces",
        ),
        profiles=("full",),
        minimal_invocation='get_distributed_trace(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")',
        advanced_invocation='get_distributed_trace(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")',
        result_fields=("trace_id", "status", "root_span", "total_spans", "services_involved", "timeline"),
        typical_followup="get_runtime_trace or reconcile_static_runtime",
        common_mistakes=(
            "Passing span_id instead of trace_id to get_distributed_trace",
        ),
        example_request="Trace the distributed execution for trace ID 4bf92f3577b34da6a3ce929d0e0e4736.",
        example_call='get_distributed_trace(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")',
        example_interpretation="Review timeline and services_involved to locate execution bottlenecks or failures.",
    ),
    # 68. check_api_drift
    ToolCapabilitySpec(
        tool_name="check_api_drift",
        capability="client_server_api_drift",
        description=(
            "Detect client-server API contract drift between frontend fetch or axios calls and backend route registrations. "
            "Flags orphaned client endpoints (404s) and HTTP method mismatches (405s). "
            "Use when validating frontend API calls against backend endpoints before deployment. "
            "Does not execute live HTTP requests or validate dynamic URL strings constructed via runtime interpolation."
        ),
        task_types=(
            AgentTaskCategory.ROUTE_DISCOVERY.value,
            AgentTaskCategory.CHANGE_IMPACT.value,
            AgentTaskCategory.DEBUG.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="Cross-layer AST static verification comparing frontend fetch calls with backend route trees.",
        does_not_prove="Does not execute live HTTP requests or validate dynamic URL concatenation at runtime.",
        useful_situations=(
            "Finding broken API endpoint paths in frontend client code",
            "Detecting HTTP method mismatches before deployment",
        ),
        avoid_when=(
            "Frontend code does not use REST fetch/axios calls to backend routes",
        ),
        profiles=("full",),
        minimal_invocation="check_api_drift()",
        advanced_invocation="check_api_drift()",
        result_fields=("status", "orphaned_client_routes", "method_mismatches", "verified_contracts_count"),
        typical_followup="find_routes or list_routes",
        common_mistakes=(
            "Assuming check_api_drift catches dynamic URL template literals constructed via arbitrary runtime string interpolation",
        ),
        example_request="Check if any frontend API calls mismatch backend routes.",
        example_call="check_api_drift()",
        example_interpretation="Inspect orphaned_client_routes for potential 404s.",
    ),
    # 69. get_monorepo_packages
    ToolCapabilitySpec(
        tool_name="get_monorepo_packages",
        capability="monorepo_package_discovery",
        description=(
            "Catalog monorepo workspace packages, tools (pnpm, Turborepo, npm/yarn workspaces), entry points, and inter-package dependencies. "
            "Use when mapping multi-package repository structure and package boundaries. "
            "Does not prove build system execution order or runtime dependency loading."
        ),
        task_types=(
            AgentTaskCategory.PACKAGE.value,
            AgentTaskCategory.ARCHITECTURE.value,
        ),
        required_inputs=(),
        optional_inputs=(),
        expected_output_type="dict[str, Any]",
        relationship_types_returned=(),
        evidence_guarantees="Deterministic workspace manifest analysis across pnpm, yarn, npm, Turborepo, Cargo, and Poetry.",
        does_not_prove="Does not prove build system execution order or runtime dependency loading.",
        useful_situations=(
            "Mapping multi-package repository structure and package boundaries",
            "Tracing internal dependency graph between workspace packages",
        ),
        avoid_when=(
            "Repository is a single standalone package without workspaces",
        ),
        profiles=("full",),
        minimal_invocation="get_monorepo_packages()",
        advanced_invocation="get_monorepo_packages()",
        result_fields=("tool", "packages", "dependency_graph", "root_path"),
        typical_followup="get_architecture or get_dependencies",
        common_mistakes=(
            "Expecting get_monorepo_packages to build or run package package.json scripts",
        ),
        example_request="List all packages in this monorepo and their dependencies.",
        example_call="get_monorepo_packages()",
        example_interpretation="Inspect packages mapping to understand package names, root paths, and dependencies.",
    ),
)

_TOOL_BY_NAME: dict[str, ToolCapabilitySpec] = {t.tool_name: t for t in TOOL_CAPABILITY_REGISTRY}


# ---------------------------------------------------------------------------
# Capability Matrix (Task Category -> Tool Selection Rule)
# ---------------------------------------------------------------------------

CAPABILITY_MATRIX: dict[AgentTaskCategory, TaskCapabilityRule] = {
    AgentTaskCategory.LOCAL_EDIT: TaskCapabilityRule(
        category=AgentTaskCategory.LOCAL_EDIT,
        should_use_codegraph=False,
        primary_tool=None,
        acceptable_tools=("read_file", "get_file"),
        recommended_sequence=("read_file",),
        direct_inspection_acceptable=True,
        rationale="Single-file local edits (typos, formatting, local variable renames) do not require cross-file graph queries.",
    ),
    AgentTaskCategory.SYMBOL_LOOKUP: TaskCapabilityRule(
        category=AgentTaskCategory.SYMBOL_LOOKUP,
        should_use_codegraph=True,
        primary_tool="resolve_symbol",
        acceptable_tools=("resolve_symbol", "search_symbols", "get_symbol", "find_symbol"),
        recommended_sequence=("resolve_symbol", "get_symbol"),
        direct_inspection_acceptable=False,
        rationale="Use resolve_symbol, find_symbol, or search_symbols to locate canonical symbol definitions without blind grep.",
    ),
    AgentTaskCategory.RELATIONSHIP: TaskCapabilityRule(
        category=AgentTaskCategory.RELATIONSHIP,
        should_use_codegraph=True,
        primary_tool="get_callers",
        acceptable_tools=("resolve_symbol", "get_callers", "get_callees", "get_references", "get_imports", "get_dependents", "find_callers", "find_callees", "find_references"),
        recommended_sequence=("resolve_symbol", "get_callers"),
        direct_inspection_acceptable=False,
        rationale="Use find_callers/get_callers, find_callees/get_callees, or find_references/get_references to retrieve AST/framework-verified relationships.",
    ),
    AgentTaskCategory.TRACE: TaskCapabilityRule(
        category=AgentTaskCategory.TRACE,
        should_use_codegraph=True,
        primary_tool="trace_path",
        acceptable_tools=("trace_path", "list_routes", "find_routes", "resolve_symbol", "get_context", "get_callees", "trace_call", "trace_flow"),
        recommended_sequence=("list_routes", "resolve_symbol", "trace_path"),
        direct_inspection_acceptable=False,
        rationale="Use trace_path (or find_routes/list_routes -> resolve_symbol -> trace_path) to prove multi-hop execution chains.",
    ),
    AgentTaskCategory.DEBUG: TaskCapabilityRule(
        category=AgentTaskCategory.DEBUG,
        should_use_codegraph=True,
        primary_tool="get_context",
        acceptable_tools=("get_context", "resolve_symbol", "get_callers", "get_callees", "find_related_tests", "find_tests", "search_code", "get_file"),
        recommended_sequence=("resolve_symbol", "get_context"),
        direct_inspection_acceptable=False,
        rationale="Use get_context (intent='DEBUG') to gather target, callers, callees, DI providers, and related tests in one bounded packet.",
    ),
    AgentTaskCategory.CHANGE_IMPACT: TaskCapabilityRule(
        category=AgentTaskCategory.CHANGE_IMPACT,
        should_use_codegraph=True,
        primary_tool="get_git_impact",
        acceptable_tools=("get_git_impact", "get_change_impact", "compare_git", "get_git_state", "check_context_freshness", "trace_symbol_history", "analyze_impact", "analyze_change_impact", "get_dependents", "get_callers", "find_related_tests", "find_tests", "get_context"),
        recommended_sequence=("get_git_state", "compare_git", "get_change_impact"),
        direct_inspection_acceptable=False,
        rationale="Use get_git_state, compare_git, and get_change_impact to deterministically compute structural diffs, affected callers, routes, packages, and tests.",
    ),
    AgentTaskCategory.TEST_DISCOVERY: TaskCapabilityRule(
        category=AgentTaskCategory.TEST_DISCOVERY,
        should_use_codegraph=True,
        primary_tool="find_related_tests",
        acceptable_tools=("find_related_tests", "find_tests", "get_git_impact", "get_context", "resolve_symbol"),
        recommended_sequence=("resolve_symbol", "find_related_tests"),
        direct_inspection_acceptable=False,
        rationale="Use find_tests/find_related_tests or get_context(intent='TEST') to locate statically linked test functions.",
    ),
    AgentTaskCategory.ROUTE_DISCOVERY: TaskCapabilityRule(
        category=AgentTaskCategory.ROUTE_DISCOVERY,
        should_use_codegraph=True,
        primary_tool="list_routes",
        acceptable_tools=("list_routes", "find_routes", "resolve_symbol", "trace_path", "get_context", "search_code"),
        recommended_sequence=("list_routes", "resolve_symbol"),
        direct_inspection_acceptable=False,
        rationale="Use find_routes/list_routes to discover HTTP endpoints, mounted router prefixes, and handler symbols.",
    ),
    AgentTaskCategory.DIAGNOSTIC: TaskCapabilityRule(
        category=AgentTaskCategory.DIAGNOSTIC,
        should_use_codegraph=True,
        primary_tool="get_repository_status",
        acceptable_tools=("get_repository_status", "get_resource_status", "verify_evidence"),
        recommended_sequence=("get_repository_status",),
        direct_inspection_acceptable=True,
        rationale="Use get_repository_status to check index freshness, symbol counts, and database health.",
    ),
    AgentTaskCategory.ARCHITECTURE: TaskCapabilityRule(
        category=AgentTaskCategory.ARCHITECTURE,
        should_use_codegraph=True,
        primary_tool="get_architecture",
        acceptable_tools=("get_architecture", "get_context", "list_routes", "find_routes", "get_imports", "get_dependents"),
        recommended_sequence=("get_architecture", "get_context"),
        direct_inspection_acceptable=False,
        rationale="Use get_architecture to inspect module boundaries, entrypoints, and workspace package dependencies.",
    ),
    AgentTaskCategory.PACKAGE: TaskCapabilityRule(
        category=AgentTaskCategory.PACKAGE,
        should_use_codegraph=True,
        primary_tool="get_context",
        acceptable_tools=("get_context", "get_architecture", "get_imports", "get_dependents"),
        recommended_sequence=("get_architecture", "get_context"),
        direct_inspection_acceptable=False,
        rationale="Use get_architecture and get_context to inspect manifest-backed workspace packages and DEPENDS_ON_PACKAGE edges.",
    ),
    AgentTaskCategory.MULTI_FILE_INVESTIGATION: TaskCapabilityRule(
        category=AgentTaskCategory.MULTI_FILE_INVESTIGATION,
        should_use_codegraph=True,
        primary_tool="get_context",
        acceptable_tools=("get_context", "search_code", "search_symbols", "resolve_symbol", "trace_path", "get_callers", "get_callees", "get_file"),
        recommended_sequence=("search_symbols", "resolve_symbol", "get_context"),
        direct_inspection_acceptable=False,
        rationale="Use get_context, search_code, or targeted graph tools first to avoid blind multi-file reading.",
    ),
    AgentTaskCategory.EXPLANATION: TaskCapabilityRule(
        category=AgentTaskCategory.EXPLANATION,
        should_use_codegraph=True,
        primary_tool="get_context",
        acceptable_tools=("get_context", "resolve_symbol", "get_symbol", "get_callees", "get_file"),
        recommended_sequence=("resolve_symbol", "get_context"),
        direct_inspection_acceptable=False,
        rationale="Use get_context (intent='EXPLAIN' or 'UNDERSTAND') to retrieve verified definitions and dependencies.",
    ),
}


# ---------------------------------------------------------------------------
# Recommended Tool Sequences (Section 10)
# ---------------------------------------------------------------------------

RECOMMENDED_TOOL_SEQUENCES: tuple[dict[str, object], ...] = (
    {
        "question": "Where is authentication implemented?",
        "category": AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
        "sequence": ["search_symbols", "resolve_symbol", "get_context"],
        "notes": "Search candidate auth symbols, resolve canonical identity, then fetch bounded context.",
    },
    {
        "question": "What calls verify_password?",
        "category": AgentTaskCategory.RELATIONSHIP.value,
        "sequence": ["resolve_symbol", "get_callers"],
        "notes": "Resolve verify_password to its canonical_id, then query verified callers.",
    },
    {
        "question": "Which route reaches login?",
        "category": AgentTaskCategory.TRACE.value,
        "sequence": ["list_routes", "resolve_symbol", "trace_path"],
        "notes": "List routes to identify the endpoint handler, resolve symbols, and trace the execution path.",
    },
    {
        "question": "What tests are affected if UserService changes?",
        "category": AgentTaskCategory.TEST_DISCOVERY.value,
        "sequence": ["resolve_symbol", "find_related_tests"],
        "notes": "Resolve UserService and query statically linked test functions (or get_git_impact for commit diffs).",
    },
    {
        "question": "How does this dependency get injected?",
        "category": AgentTaskCategory.DEBUG.value,
        "sequence": ["resolve_symbol", "get_context"],
        "notes": "Resolve target symbol and compile context to inspect INJECTS, PROVIDES, and RESOLVES_DEPENDENCY edges.",
    },
    {
        "question": "Where is the upload bill button in HTML?",
        "category": AgentTaskCategory.MULTI_FILE_INVESTIGATION.value,
        "sequence": ["search_code", "get_file"],
        "notes": "Use search_code for literal UI/HTML/template text discovery, then open the matched line range with get_file.",
    },
    {
        "question": "Fix a typo in the docstring of format_date in utils/dates.py",
        "category": AgentTaskCategory.LOCAL_EDIT.value,
        "sequence": ["read_file"],
        "notes": "Single-file local edit: direct file inspection is sufficient; do not call CodeGraph.",
    },
)


# ---------------------------------------------------------------------------
# MCP Profile Recommendations (Section 21)
# ---------------------------------------------------------------------------

MCP_PROFILE_RECOMMENDATIONS: dict[str, dict[str, object]] = {
    "agent": {
        "profile": "agent",
        "tool_count": 14,
        "recommended_for": "Focused AI coding agent workflow across discovery, file inspection, context synthesis, and graph tracing",
        "included_tools": sorted(DEFAULT_AGENT_PROFILE_TOOLS),
    },
    "core": {
        "profile": "core",
        "tool_count": 13,
        "recommended_for": "Simple symbol lookup, relationship queries, and low-overhead interrogation sessions",
        "included_tools": [
            "get_architecture",
            "get_callees",
            "get_callers",
            "get_dependents",
            "get_file",
            "get_git_impact",
            "get_imports",
            "get_references",
            "get_symbol",
            "list_routes",
            "resolve_symbol",
            "search_symbols",
            "trace_path",
        ],
    },
    "graph": {
        "profile": "graph",
        "tool_count": 17,
        "recommended_for": "Tracing, change-impact, test discovery, and architecture sessions",
        "included_tools": [
            "analyze_impact",
            "find_related_tests",
            "get_architecture",
            "get_call_graph",
            "get_callees",
            "get_callers",
            "get_context",
            "get_dependents",
            "get_file",
            "get_git_impact",
            "get_imports",
            "get_references",
            "get_symbol",
            "list_routes",
            "resolve_symbol",
            "search_symbols",
            "trace_path",
        ],
    },
    "minimal": {
        "profile": "minimal",
        "tool_count": 21,
        "recommended_for": "Context-heavy coding sessions needing core interrogation plus get_context and read_file",
        "included_tools": [
            "compile_task",
            "find_symbol",
            "get_architecture",
            "get_callees",
            "get_callers",
            "get_context",
            "get_dependents",
            "get_file",
            "get_git_impact",
            "get_imports",
            "get_references",
            "get_repository_status",
            "get_resource_status",
            "get_symbol",
            "list_routes",
            "read_file",
            "resolve_symbol",
            "search_code",
            "search_symbols",
            "trace_path",
            "verify_evidence",
        ],
    },
    "developer": {
        "profile": "developer",
        "tool_count": 34,
        "recommended_for": "Full interactive development with impact analysis, test linking, and git history",
        "included_tools": [
            "analyze_change_impact",
            "analyze_impact",
            "compile_task",
            "find_callees",
            "find_callers",
            "find_references",
            "find_related_tests",
            "find_symbol",
            "get_architecture",
            "get_call_graph",
            "get_callees",
            "get_callers",
            "get_context",
            "get_dependents",
            "get_evidence",
            "get_file",
            "get_file_history",
            "get_git_impact",
            "get_graph",
            "get_imports",
            "get_recent_changes",
            "get_references",
            "get_repository_status",
            "get_resource_status",
            "get_symbol",
            "list_routes",
            "plan_retrieval",
            "read_file",
            "resolve_symbol",
            "search_code",
            "search_symbols",
            "trace_call",
            "trace_path",
            "verify_evidence",
        ],
    },
    "full": {
        "profile": "full",
        "tool_count": 70,
        "recommended_for": "Complete diagnostic, database intelligence, runtime reconciliation, benchmark, and repository administration sessions",
        "included_tools": [
            "analyze_change_impact",
            "analyze_impact",
            "check_api_drift",
            "check_context_freshness",
            "check_db_drift",
            "check_route_schema_drift",
            "compare_git",
            "compile_task",
            "detect_semantic_conflicts",
            "find_callees",
            "find_callers",
            "find_db_callers",
            "find_db_columns",
            "find_db_models",
            "find_db_queries",
            "find_db_readers",
            "find_db_relationships",
            "find_db_tables",
            "find_db_writers",
            "find_references",
            "find_related_tests",
            "find_routes",
            "find_symbol",
            "find_tests",
            "get_architecture",
            "get_call_graph",
            "get_callees",
            "get_callers",
            "get_change_impact",
            "get_context",
            "get_db_impact",
            "get_db_schema",
            "get_db_table",
            "get_dependencies",
            "get_dependency_graph",
            "get_dependents",
            "get_distributed_trace",
            "get_evidence",
            "get_file",
            "get_file_history",
            "get_file_symbols",
            "get_git_impact",
            "get_git_state",
            "get_graph",
            "get_imports",
            "get_live_services",
            "get_monorepo_packages",
            "get_project_structure",
            "get_recent_changes",
            "get_references",
            "get_repository_status",
            "get_resource_status",
            "get_runtime_trace",
            "get_symbol",
            "ingest_runtime_traces",
            "list_routes",
            "plan_retrieval",
            "read_file",
            "reconcile_static_runtime",
            "resolve_symbol",
            "rollback_refactor",
            "safe_rename",
            "search_code",
            "search_memory",
            "search_symbols",
            "trace_call",
            "trace_flow",
            "trace_path",
            "trace_symbol_history",
            "verify_evidence",
        ],
    },
}


# ---------------------------------------------------------------------------
# Deterministic Task Classification & Tool Selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskClassificationResult:
    """Result of classifying an agent task prompt."""

    category: AgentTaskCategory
    should_use_codegraph: bool
    primary_tool: str | None
    acceptable_tools: tuple[str, ...]
    recommended_sequence: tuple[str, ...]
    direct_inspection_acceptable: bool
    confidence: str
    rationale: str

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "should_use_codegraph": self.should_use_codegraph,
            "primary_tool": self.primary_tool,
            "acceptable_tools": list(self.acceptable_tools),
            "recommended_sequence": list(self.recommended_sequence),
            "direct_inspection_acceptable": self.direct_inspection_acceptable,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


_LOCAL_EDIT_PATTERNS = re.compile(
    r"\b(typo|docstring|comment|rename local variable|format|indent|whitespace|"
    r"fix spelling|add a log line|change string literal|update constant in)\b",
    re.IGNORECASE,
)
_FILE_INSPECTION_PATTERNS = re.compile(
    r"\b(show lines|read lines|open lines|lines\s+\d+\s*(?:to|-|\.\.)\s*\d+\s+of)\b",
    re.IGNORECASE,
)
_LITERAL_SEARCH_PATTERNS = re.compile(
    r"\b(button in (?:the )?html|in (?:the )?html|in (?:the )?template|in (?:the )?jinja|"
    r"html template|ui text|button label|css selector|css class|literal string|"
    r"error message string|search text)\b",
    re.IGNORECASE,
)
_DIAGNOSTIC_PATTERNS = re.compile(
    r"\b(index status|repository status|is codegraph indexed|database health|freshness|resource status|mcp doctor)\b",
    re.IGNORECASE,
)
_ROUTE_PATTERNS = re.compile(
    r"(\b(?:which route|list routes|find routes|http endpoint|api endpoint|mounted router|url path|route handler)\b|"
    r"\bwhere is\s+/[A-Za-z0-9_./{}:-]+\s+handled\b|"
    r"(?:GET|POST|PUT|DELETE|PATCH)\s+/|"
    r"(?<![@\w])/api/)",
    re.IGNORECASE,
)
_TRACE_PATTERNS = re.compile(
    r"\b(trace|execution path|path from|reach(?:es)?|flow from|from route to|call chain from|"
    r"end-to-end flow|how does request reach)\b",
    re.IGNORECASE,
)
_TEST_PATTERNS = re.compile(
    r"\b(which tests|what tests|related tests|test coverage|tests cover|tests for|tests affected|"
    r"find tests|regression tests)\b",
    re.IGNORECASE,
)
_CHANGE_IMPACT_PATTERNS = re.compile(
    r"\b(change impact|blast radius|git impact|what changed in git|could it break|affected if|"
    r"what breaks if|if .* changes|impact of changing|recent commits|diff impact|refactoring impact)\b",
    re.IGNORECASE,
)
_PACKAGE_PATTERNS = re.compile(
    r"\b(monorepo|workspace package|package boundary|package dependencies|cross-package|"
    r"DEPENDS_ON_PACKAGE|packages depend|which package owns)\b",
    re.IGNORECASE,
)
_ARCHITECTURE_PATTERNS = re.compile(
    r"\b(architecture|system overview|high-level structure|module boundaries|layer overview|"
    r"project structure|architectural layers|repository structured|how is .* structured)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_PATTERNS = re.compile(
    r"\b(what calls|who calls|callers of|callees of|what does .* call|references to|"
    r"find all references to|where is .* referenced|who imports|what imports|dependents of|"
    r"registered handlers|event listeners for|dispatches to)\b",
    re.IGNORECASE,
)
_DEBUG_PATTERNS = re.compile(
    r"\b(debug|why is .* failing|investigate bug|exception in|error when|null pointer|"
    r"dependency inject(?:ed|ion)|how does .* get injected|provider for|Depends\(|@inject)\b",
    re.IGNORECASE,
)
_SYMBOL_LOOKUP_PATTERNS = re.compile(
    r"\b(where is .* defined|find symbol|locate class|locate function|resolve symbol|"
    r"definition of|signature of)\b",
    re.IGNORECASE,
)
_MULTI_FILE_PATTERNS = re.compile(
    r"\b(where is .* implemented|across the repository|across files|multi-file|"
    r"how do .* interact|investigate how)\b",
    re.IGNORECASE,
)
_RUNTIME_RECONCILE_PATTERNS = re.compile(
    r"\b(reconcile|static and runtime|static vs runtime|differ from static|runtime conflict|not observed at runtime|runtime only)\b",
    re.IGNORECASE,
)
_RUNTIME_INGEST_PATTERNS = re.compile(
    r"\b(ingest .* trace|load .* trace|import .* trace|ingest runtime)\b",
    re.IGNORECASE,
)
_RUNTIME_TRACE_PATTERNS = re.compile(
    r"\b(at runtime|happened at runtime|runtime trace|runtime execution|observed at runtime|when .* ran)\b",
    re.IGNORECASE,
)
_DB_TABLES_PATTERNS = re.compile(
    r"\b(which tables|what tables|database tables|tables exist|list tables|find tables)\b",
    re.IGNORECASE,
)
_DB_COLUMNS_PATTERNS = re.compile(
    r"\b(what columns|which columns|columns exist|columns in|column .* defined)\b",
    re.IGNORECASE,
)
_DB_MODELS_PATTERNS = re.compile(
    r"\b(which orm|what orm|orm model|models map|model maps to)\b",
    re.IGNORECASE,
)
_DB_WRITERS_PATTERNS = re.compile(
    r"\b(writes to|write to|inserts into|updates table|deletes from|mutates table|which route writes|which service writes)\b",
    re.IGNORECASE,
)
_DB_READERS_PATTERNS = re.compile(
    r"\b(reads from|read from|selects from|queries table|which service reads)\b",
    re.IGNORECASE,
)
_DB_IMPACT_PATTERNS = re.compile(
    r"\b(drop column|rename column|alter table|database impact|table impact|column impact)\b",
    re.IGNORECASE,
)
_DB_SCHEMA_PATTERNS = re.compile(
    r"\b(database schema|db schema|schema overview|foreign keys in)\b",
    re.IGNORECASE,
)


_INDEX_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "check", "code", "do",
    "does", "examine", "explain", "file", "find", "for", "from", "function",
    "get", "how", "in", "inspect", "into", "investigate", "is", "it", "look",
    "lookup", "method", "of", "on", "or", "review", "see", "show", "tell",
    "the", "this", "to", "understand", "use", "used", "using", "what", "when",
    "where", "which", "who", "why", "with", "work", "works",
})


def _classify_via_repository_index(
    clean: str,
    con: sqlite3.Connection,
) -> TaskClassificationResult | None:
    """Ground bare identifiers, routes, and packages in the prompt against the SQLite index."""
    from codegraph.target_resolver import TargetType, resolve_target

    # 1. Check route-like tokens against indexed framework_routes
    route_tokens = re.findall(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9_./{}:-]+)", clean)
    for r_tok in route_tokens:
        try:
            row = con.execute(
                "SELECT route_path, handler_name FROM framework_routes "
                "WHERE route_path=? OR normalized_route=? OR endpoint_id=? LIMIT 1",
                (r_tok, r_tok, r_tok),
            ).fetchone()
            if row is not None:
                return _rule_to_result(
                    CAPABILITY_MATRIX[AgentTaskCategory.ROUTE_DISCOVERY],
                    confidence="HIGH",
                )
        except sqlite3.OperationalError:
            pass

    # 2. Extract identifier and package tokens
    raw_tokens = re.findall(
        r"(@[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|[A-Za-z_][A-Za-z0-9_.]*)",
        clean,
    )
    candidate_tokens = [
        tok for tok in raw_tokens if tok.lower() not in _INDEX_STOPWORDS and len(tok) >= 2
    ]
    if not candidate_tokens:
        return None

    # 3. Check package edges in graph_edges
    for tok in candidate_tokens:
        try:
            pkg_row = con.execute(
                "SELECT 1 FROM graph_edges "
                "WHERE relationship IN ('DEPENDS_ON_PACKAGE', 'PACKAGE_IMPORTS', "
                "'CROSS_PACKAGE_IMPORT', 'CONTAINS_PACKAGE') "
                "AND (source=? OR target=? OR source LIKE ? OR target LIKE ?) LIMIT 1",
                (tok, tok, f"%:{tok}", f"%:{tok}"),
            ).fetchone()
            if pkg_row is not None:
                return _rule_to_result(
                    CAPABILITY_MATRIX[AgentTaskCategory.PACKAGE],
                    confidence="HIGH",
                )
        except sqlite3.OperationalError:
            pass

    # 4. Resolve symbols via first-class TargetResolver
    resolved_symbols = []
    seen_canonical: set[str] = set()
    for tok in candidate_tokens:
        res = resolve_target(tok, con)
        if res.is_resolved() and res.canonical_id and res.canonical_id not in seen_canonical:
            seen_canonical.add(res.canonical_id)
            resolved_symbols.append(res)

    if not resolved_symbols:
        return None

    # Check if any resolved symbol is a test or in a test file
    for res in resolved_symbols:
        f_path = (res.file_path or "").lower()
        q_name = (res.qualified_name or "").lower()
        if (
            res.target_type == TargetType.TEST
            or "test_" in f_path
            or "/tests/" in f_path
            or f_path.startswith("tests/")
            or q_name.startswith("test_")
            or ".test_" in q_name
        ):
            return _rule_to_result(
                CAPABILITY_MATRIX[AgentTaskCategory.TEST_DISCOVERY],
                confidence="HIGH",
            )

    # Check if two or more distinct repository symbols are referenced -> TRACE
    if len(resolved_symbols) >= 2:
        return _rule_to_result(
            CAPABILITY_MATRIX[AgentTaskCategory.TRACE],
            confidence="HIGH",
        )

    # Check if single resolved symbol participates in DI (INJECTS / PROVIDES)
    for res in resolved_symbols:
        try:
            di_row = con.execute(
                "SELECT 1 FROM graph_edges "
                "WHERE relationship IN ('INJECTS', 'PROVIDES') "
                "AND (source=? OR target=? OR source=? OR target=?) LIMIT 1",
                (
                    res.canonical_id or "",
                    res.canonical_id or "",
                    res.qualified_name or "",
                    res.qualified_name or "",
                ),
            ).fetchone()
            if di_row is not None:
                return _rule_to_result(
                    CAPABILITY_MATRIX[AgentTaskCategory.DEBUG],
                    confidence="HIGH",
                )
        except sqlite3.OperationalError:
            pass

    # Single resolved symbol -> SYMBOL_LOOKUP
    return _rule_to_result(
        CAPABILITY_MATRIX[AgentTaskCategory.SYMBOL_LOOKUP],
        confidence="HIGH",
    )


def classify_agent_task(
    prompt: str,
    file_count_hint: int | None = None,
    con: sqlite3.Connection | None = None,
) -> TaskClassificationResult:
    """Deterministically classify a developer or agent task into one of the 13 categories.

    When `con` (an indexed SQLite connection) is provided, prompts that do not match
    explicit lexical intent patterns are grounded against indexed routes, packages,
    DI edges, test symbols, and canonical symbol definitions in sub-millisecond time.
    """
    clean = (prompt or "").strip()
    if not clean:
        rule = CAPABILITY_MATRIX[AgentTaskCategory.EXPLANATION]
        return _rule_to_result(rule, confidence="LOW")

    # 1. Explicit single-file local edit check
    if _LOCAL_EDIT_PATTERNS.search(clean) and not _RELATIONSHIP_PATTERNS.search(clean):
        if file_count_hint is None or file_count_hint <= 1:
            return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.LOCAL_EDIT], confidence="HIGH")

    # 1b. Explicit bounded line-range file opening (e.g. "Show lines 40 to 110 of dashboard.html")
    if _FILE_INSPECTION_PATTERNS.search(clean):
        file_rule = TaskCapabilityRule(
            category=AgentTaskCategory.SYMBOL_LOOKUP,
            should_use_codegraph=True,
            primary_tool="get_file",
            acceptable_tools=("get_file", "read_file"),
            recommended_sequence=("get_file",),
            direct_inspection_acceptable=True,
            rationale="Use get_file(path, start_line, end_line) to open targeted line ranges of repository files.",
        )
        return _rule_to_result(file_rule, confidence="HIGH")

    # 1c. Explicit literal text / HTML / template / UI string search
    if _LITERAL_SEARCH_PATTERNS.search(clean):
        lit_rule = TaskCapabilityRule(
            category=AgentTaskCategory.MULTI_FILE_INVESTIGATION,
            should_use_codegraph=True,
            primary_tool="search_code",
            acceptable_tools=("search_code", "get_file"),
            recommended_sequence=("search_code", "get_file"),
            direct_inspection_acceptable=False,
            rationale="Use search_code for literal text, HTML/Jinja template strings, UI labels, and config keys, then get_file to inspect lines.",
        )
        return _rule_to_result(lit_rule, confidence="HIGH")

    # 2. Diagnostic / health check
    if _DIAGNOSTIC_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.DIAGNOSTIC], confidence="HIGH")

    # 3. Trace check (especially route -> handler -> service or path between symbols)
    if _TRACE_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.TRACE], confidence="HIGH")

    # 4. Route discovery check
    if _ROUTE_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.ROUTE_DISCOVERY], confidence="HIGH")

    # 5. Test discovery check (prioritized when explicitly asking about tests)
    if _TEST_PATTERNS.search(clean) and not _CHANGE_IMPACT_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.TEST_DISCOVERY], confidence="HIGH")

    # 6. Change impact check
    if _CHANGE_IMPACT_PATTERNS.search(clean):
        if _TEST_PATTERNS.search(clean) and "git" not in clean.lower() and "commit" not in clean.lower():
            return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.TEST_DISCOVERY], confidence="HIGH")
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.CHANGE_IMPACT], confidence="HIGH")

    # 7. Package / workspace boundary check
    if _PACKAGE_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.PACKAGE], confidence="HIGH")

    # 8. Architecture overview check
    if _ARCHITECTURE_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.ARCHITECTURE], confidence="HIGH")

    # 9. Relationship check (callers, callees, references, imports, dependents, events, registries)
    if _RELATIONSHIP_PATTERNS.search(clean):
        rule = CAPABILITY_MATRIX[AgentTaskCategory.RELATIONSHIP]
        lower = clean.lower()
        if "callee" in lower or re.search(r"what does .+ call", lower):
            custom_rule = TaskCapabilityRule(
                category=AgentTaskCategory.RELATIONSHIP,
                should_use_codegraph=True,
                primary_tool="get_callees",
                acceptable_tools=rule.acceptable_tools,
                recommended_sequence=("resolve_symbol", "get_callees"),
                direct_inspection_acceptable=False,
                rationale=rule.rationale,
            )
            return _rule_to_result(custom_rule, confidence="HIGH")
        if "reference" in lower or "registered" in lower or "event listener" in lower or "dispatch" in lower:
            custom_rule = TaskCapabilityRule(
                category=AgentTaskCategory.RELATIONSHIP,
                should_use_codegraph=True,
                primary_tool="get_references",
                acceptable_tools=rule.acceptable_tools,
                recommended_sequence=("resolve_symbol", "get_references"),
                direct_inspection_acceptable=False,
                rationale=rule.rationale,
            )
            return _rule_to_result(custom_rule, confidence="HIGH")
        if "what imports" in lower or "who imports" in lower or "dependents of" in lower:
            custom_rule = TaskCapabilityRule(
                category=AgentTaskCategory.RELATIONSHIP,
                should_use_codegraph=True,
                primary_tool="get_dependents",
                acceptable_tools=rule.acceptable_tools,
                recommended_sequence=("resolve_symbol", "get_dependents"),
                direct_inspection_acceptable=False,
                rationale=rule.rationale,
            )
            return _rule_to_result(custom_rule, confidence="HIGH")
        return _rule_to_result(rule, confidence="HIGH")

    # 10. Debug / DI / bug investigation check
    if _DEBUG_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.DEBUG], confidence="HIGH")

    # 11. Symbol lookup check
    if _SYMBOL_LOOKUP_PATTERNS.search(clean):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.SYMBOL_LOOKUP], confidence="HIGH")

    # 12. Optional SQLite index-grounded classification (when con is provided)
    if con is not None:
        indexed_result = _classify_via_repository_index(clean, con)
        if indexed_result is not None:
            return indexed_result

    # 13. Multi-file investigation check
    if _MULTI_FILE_PATTERNS.search(clean) or (file_count_hint is not None and file_count_hint > 1):
        return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.MULTI_FILE_INVESTIGATION], confidence="MEDIUM")

    # 14. Default: EXPLANATION
    return _rule_to_result(CAPABILITY_MATRIX[AgentTaskCategory.EXPLANATION], confidence="MEDIUM")


def select_agent_tool(
    prompt: str,
    con: sqlite3.Connection | None = None,
) -> dict[str, object]:
    """Route a natural-language agent question to its canonical `ROUTING_MANIFEST` tool and sequence.

    Uses the clean `find_*` / `get_*` / `trace_*` agent-profile vocabulary defined in `ROUTING_MANIFEST`.
    """
    cls = classify_agent_task(prompt, con=con)
    clean = (prompt or "").strip().lower()

    if _RUNTIME_RECONCILE_PATTERNS.search(clean):
        routing_key = "runtime_reconcile"
        primary = ROUTING_MANIFEST["runtime_reconcile"]
        seq: tuple[str, ...] = ("reconcile_static_runtime", "get_file")
        acceptable: tuple[str, ...] = ("reconcile_static_runtime", "get_runtime_trace")
    elif _RUNTIME_INGEST_PATTERNS.search(clean):
        routing_key = "runtime_ingest"
        primary = ROUTING_MANIFEST["runtime_ingest"]
        seq = ("ingest_runtime_traces", "get_runtime_trace")
        acceptable = ("ingest_runtime_traces",)
    elif _RUNTIME_TRACE_PATTERNS.search(clean):
        routing_key = "runtime_trace"
        primary = ROUTING_MANIFEST["runtime_trace"]
        seq = ("get_runtime_trace", "reconcile_static_runtime")
        acceptable = ("get_runtime_trace", "reconcile_static_runtime")
    elif _DB_TABLES_PATTERNS.search(clean):
        routing_key = "db_tables"
        primary = ROUTING_MANIFEST["db_tables"]
        seq = ("find_db_tables", "get_db_table")
        acceptable = ("find_db_tables", "get_db_schema", "get_db_table")
    elif _DB_COLUMNS_PATTERNS.search(clean):
        routing_key = "db_columns"
        primary = ROUTING_MANIFEST["db_columns"]
        seq = ("find_db_columns", "get_db_table")
        acceptable = ("find_db_columns", "get_db_table")
    elif _DB_MODELS_PATTERNS.search(clean):
        routing_key = "db_models"
        primary = ROUTING_MANIFEST["db_models"]
        seq = ("find_db_models", "get_db_table")
        acceptable = ("find_db_models", "get_db_table")
    elif _DB_WRITERS_PATTERNS.search(clean):
        routing_key = "db_writers"
        primary = ROUTING_MANIFEST["db_writers"]
        seq = ("find_db_writers", "find_db_callers")
        acceptable = ("find_db_writers", "find_db_callers", "find_db_queries")
    elif _DB_READERS_PATTERNS.search(clean):
        routing_key = "db_readers"
        primary = ROUTING_MANIFEST["db_readers"]
        seq = ("find_db_readers", "find_db_callers")
        acceptable = ("find_db_readers", "find_db_callers", "find_db_queries")
    elif _DB_IMPACT_PATTERNS.search(clean):
        routing_key = "db_impact"
        primary = ROUTING_MANIFEST["db_impact"]
        seq = ("get_db_impact", "find_tests")
        acceptable = ("get_db_impact", "analyze_impact")
    elif _DB_SCHEMA_PATTERNS.search(clean):
        routing_key = "db_schema"
        primary = ROUTING_MANIFEST["db_schema"]
        seq = ("get_db_schema", "get_db_table")
        acceptable = ("get_db_schema", "find_db_tables", "find_db_relationships")
    elif _FILE_INSPECTION_PATTERNS.search(clean):
        routing_key = "source_inspection"
        primary = ROUTING_MANIFEST["source_inspection"]
        seq = ("get_file",)
        acceptable = ("get_file", "read_file")
    elif _LITERAL_SEARCH_PATTERNS.search(clean):
        routing_key = "literal_search"
        primary = ROUTING_MANIFEST["literal_search"]
        seq = ("search_code", "get_file")
        acceptable = ("search_code",)
    elif cls.category == AgentTaskCategory.ARCHITECTURE:
        routing_key = "architecture_analysis"
        primary = ROUTING_MANIFEST["architecture_analysis"]
        seq = ("get_architecture",)
        acceptable = ("get_architecture", "get_context")
    elif cls.category == AgentTaskCategory.SYMBOL_LOOKUP:
        routing_key = "symbol_discovery"
        primary = ROUTING_MANIFEST["symbol_discovery"]
        seq = ("find_symbol", "get_symbol")
        acceptable = ("find_symbol", "resolve_symbol", "get_symbol", "search_symbols")
    elif cls.category == AgentTaskCategory.RELATIONSHIP:
        if cls.primary_tool == "get_callees":
            routing_key = "callee_discovery"
            primary = ROUTING_MANIFEST["callee_discovery"]
            seq = ("find_callees",)
            acceptable = ("find_callees", "get_callees")
        elif cls.primary_tool == "get_references":
            routing_key = "reference_discovery"
            primary = ROUTING_MANIFEST["reference_discovery"]
            seq = ("find_references",)
            acceptable = ("find_references", "get_references")
        else:
            routing_key = "caller_discovery"
            primary = ROUTING_MANIFEST["caller_discovery"]
            seq = ("find_callers",)
            acceptable = ("find_callers", "get_callers")
    elif cls.category == AgentTaskCategory.TRACE:
        routing_key = "relationship_trace"
        primary = ROUTING_MANIFEST["relationship_trace"]
        if "route" in clean or "api" in clean or "endpoint" in clean:
            seq = ("find_routes", "trace_path")
        else:
            seq = ("trace_path",)
        acceptable = ("trace_path", "find_routes", "list_routes", "trace_flow")
    elif cls.category == AgentTaskCategory.ROUTE_DISCOVERY:
        routing_key = "route_discovery"
        primary = ROUTING_MANIFEST["route_discovery"]
        seq = ("find_routes", "get_file")
        acceptable = ("find_routes", "list_routes", "search_code")
    elif cls.category == AgentTaskCategory.TEST_DISCOVERY:
        routing_key = "test_discovery"
        primary = ROUTING_MANIFEST["test_discovery"]
        seq = ("find_tests",)
        acceptable = ("find_tests", "find_related_tests")
    elif cls.category == AgentTaskCategory.CHANGE_IMPACT:
        routing_key = "change_impact"
        primary = ROUTING_MANIFEST["change_impact"]
        seq = ("get_git_impact", "find_tests")
        acceptable = ("get_git_impact", "analyze_impact", "analyze_change_impact")
    else:
        routing_key = "context_synthesis"
        primary = ROUTING_MANIFEST["context_synthesis"]
        seq = ("get_context", "get_file")
        acceptable = ("get_context",)

    return {
        "prompt": prompt,
        "category": cls.category.value,
        "routing_key": routing_key,
        "selected_tool": primary,
        "recommended_sequence": list(seq),
        "acceptable_tools": list(acceptable),
        "confidence": cls.confidence,
    }


def _rule_to_result(rule: TaskCapabilityRule, confidence: str) -> TaskClassificationResult:
    return TaskClassificationResult(
        category=rule.category,
        should_use_codegraph=rule.should_use_codegraph,
        primary_tool=rule.primary_tool,
        acceptable_tools=rule.acceptable_tools,
        recommended_sequence=rule.recommended_sequence,
        direct_inspection_acceptable=rule.direct_inspection_acceptable,
        confidence=confidence,
        rationale=rule.rationale,
    )


# ---------------------------------------------------------------------------
# Epistemic & Fallback Policy (Section 11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackDecision:
    """Structured decision for when and how an agent may fall back to direct repository tools."""

    fallback_allowed: bool
    fallback_reason: str
    epistemic_status: str  # VERIFIED | POSSIBLE | UNKNOWN | AMBIGUOUS | STALE | DISCONNECTED
    relationship_exists_claim_allowed: bool
    no_relationship_claim_allowed: bool
    required_agent_action: str

    def as_dict(self) -> dict[str, object]:
        return {
            "fallback_allowed": self.fallback_allowed,
            "fallback_reason": self.fallback_reason,
            "epistemic_status": self.epistemic_status,
            "relationship_exists_claim_allowed": self.relationship_exists_claim_allowed,
            "no_relationship_claim_allowed": self.no_relationship_claim_allowed,
            "required_agent_action": self.required_agent_action,
        }


def evaluate_fallback_policy(
    mcp_state: str = "CONNECTED",
    evidence_class: str | None = None,
    ambiguity_state: str = "CLEAR",
    freshness: str = "FRESH",
) -> FallbackDecision:
    """Evaluate safe fallback behavior while strictly preserving epistemic invariants."""
    state_upper = mcp_state.upper()
    if state_upper in ("DISCONNECTED", "UNAVAILABLE", "SERVER_FAILED", "TOOLS_UNAVAILABLE"):
        return FallbackDecision(
            fallback_allowed=True,
            fallback_reason=f"CodeGraph MCP is {state_upper}",
            epistemic_status="DISCONNECTED",
            relationship_exists_claim_allowed=False,
            no_relationship_claim_allowed=False,
            required_agent_action="Use direct repository search/file reads and verify claims manually.",
        )

    if freshness.upper() == "STALE":
        return FallbackDecision(
            fallback_allowed=True,
            fallback_reason="CodeGraph index is STALE relative to working tree modifications",
            epistemic_status="STALE",
            relationship_exists_claim_allowed=False,
            no_relationship_claim_allowed=False,
            required_agent_action="Verify modified files directly with read_file or re-index before relying on stale edges.",
        )

    amb_upper = ambiguity_state.upper()
    if amb_upper in ("AMBIGUOUS", "CONFLICT"):
        return FallbackDecision(
            fallback_allowed=True,
            fallback_reason=f"Target resolution is {amb_upper} with multiple candidate symbols",
            epistemic_status="AMBIGUOUS",
            relationship_exists_claim_allowed=False,
            no_relationship_claim_allowed=False,
            required_agent_action=(
                "Inspect candidate alternatives returned by CodeGraph; never arbitrarily pick one without disambiguating."
            ),
        )

    ev_upper = (evidence_class or "AST_VERIFIED").upper()
    if ev_upper == "UNKNOWN":
        return FallbackDecision(
            fallback_allowed=True,
            fallback_reason="Static analysis returned UNKNOWN (dynamic dispatch or unresolvable target)",
            epistemic_status="UNKNOWN",
            relationship_exists_claim_allowed=False,
            no_relationship_claim_allowed=False,  # CRITICAL: UNKNOWN != "there is no relationship"
            required_agent_action=(
                "Treat UNKNOWN as 'static analysis could not establish the relationship' (NOT 'no relationship exists'). "
                "Use targeted read_file on the call site to inspect dynamic behavior."
            ),
        )

    if ev_upper == "POSSIBLE":
        return FallbackDecision(
            fallback_allowed=True,
            fallback_reason="Static analysis returned POSSIBLE candidate relationship",
            epistemic_status="POSSIBLE",
            relationship_exists_claim_allowed=False,  # Must not claim as verified fact without source check
            no_relationship_claim_allowed=False,
            required_agent_action=(
                "Report relationship as POSSIBLE (candidate) and perform targeted read_file on cited lines to confirm."
            ),
        )

    return FallbackDecision(
        fallback_allowed=False,
        fallback_reason="Verified static evidence returned by CodeGraph",
        epistemic_status="VERIFIED",
        relationship_exists_claim_allowed=True,
        no_relationship_claim_allowed=False,
        required_agent_action=(
            "Rely on verified CodeGraph evidence; use targeted read_file only if line-by-line implementation details are needed."
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic Capability Manifest (Section 5 & Section 19)
# ---------------------------------------------------------------------------


def get_capability_manifest() -> dict[str, Any]:
    """Return a deterministic, environment-independent capability manifest for AI coding agents."""
    capabilities = sorted({spec.capability for spec in TOOL_CAPABILITY_REGISTRY})
    tool_mappings = {
        spec.tool_name: spec.as_dict()
        for spec in sorted(TOOL_CAPABILITY_REGISTRY, key=lambda s: s.tool_name)
    }
    task_mappings = {
        cat.value: CAPABILITY_MATRIX[cat].as_dict()
        for cat in sorted(CAPABILITY_MATRIX.keys(), key=lambda c: c.value)
    }

    return {
        "schema_version": "1.0",
        "server_name": "codegraph",
        "version": __version__,
        "summary": (
            "CodeGraph is strongest for repository relationships, database intelligence, runtime reconciliation, "
            "architecture, routes, tests, DI, packages, change impact, literal repository text search, and bounded file inspection."
        ),
        "selection_principle": (
            "Use CodeGraph when repository relationships, database schemas/queries, runtime traces, multi-file reasoning, or literal text/template search make it materially useful. "
            "For simple single-file local edits, direct file inspection is acceptable."
        ),
        "routing_manifest": dict(ROUTING_MANIFEST),
        "default_agent_profile_tools": list(DEFAULT_AGENT_PROFILE_TOOLS),
        "capabilities": capabilities,
        "profiles": {k: MCP_PROFILE_RECOMMENDATIONS[k] for k in sorted(MCP_PROFILE_RECOMMENDATIONS.keys())},
        "tool_mappings": tool_mappings,
        "task_mappings": task_mappings,
        "recommended_sequences": [dict(seq) for seq in RECOMMENDED_TOOL_SEQUENCES],
        "recommended_usage_order": [
            "1. Classify the task (LOCAL_EDIT vs literal text/template search vs database/runtime vs symbol/relationship/multi-file task).",
            "2. If LOCAL_EDIT on a single known file, use direct file inspection (get_file or read_file).",
            "3. If searching for literal text, HTML/Jinja IDs, UI strings, CSS selectors, or config keys, call search_code.",
            "4. If querying database tables, columns, ORM models, or SQL queries, call find_db_tables, get_db_table, find_db_callers, find_db_writers, or get_db_impact.",
            "5. If symbol identity is needed, call find_symbol or resolve_symbol (or search_symbols if spelling is unknown).",
            "6. Call the smallest targeted CodeGraph tool (find_callers/get_callers, find_callees/get_callees, trace_path, find_routes/list_routes, find_tests/find_related_tests, get_git_impact, or get_context).",
            "7. Inspect structured evidence and epistemic labels (AST_VERIFIED, STATIC_VERIFIED, FRAMEWORK_VERIFIED, DATAFLOW_VERIFIED, RUNTIME_OBSERVED, RUNTIME_UNOBSERVED, POSSIBLE, UNKNOWN, AMBIGUOUS).",
            "8. Use targeted get_file(path, start_line, end_line) on specific line ranges when exact source lines are needed.",
        ],
        "evidence_semantics": {
            "AST_VERIFIED": "Directly proven by syntax tree definition, import, or call.",
            "STATIC_VERIFIED": "Directly proven by static SQL DDL/DML parsing or migration schema definitions.",
            "FRAMEWORK_VERIFIED": "Proven by deterministic framework semantics (FastAPI/Flask/Django/Express routes, ORM models, Celery tasks, Click commands, DI).",
            "DATAFLOW_VERIFIED": "Proven by conservative local variable, container, or registry binding resolution.",
            "RUNTIME_OBSERVED": "Observed in an ingested runtime trace (OpenTelemetry, JSONL events, or SQL query logs); never converted into static AST_VERIFIED proof.",
            "RUNTIME_UNOBSERVED": "Static relationship was not observed in the ingested runtime trace sample; never proves the path is impossible.",
            "POSSIBLE": "Plausible static candidate (e.g., conditional binding, dynamic SQL table interpolation, or interface match); never treat as verified fact without source confirmation.",
            "UNKNOWN": "Static analysis could not establish the target (e.g., dynamic getattr/eval or opaque SQL string). UNKNOWN never means 'no relationship exists'.",
            "AMBIGUOUS": "Multiple symbols or tables match the target name; inspect alternatives rather than guessing.",
            "STALE": "File on disk was modified since indexing; verify with get_file/read_file or re-index.",
        },
        "limitations": [
            "Does not execute repository code, launch user applications, or connect to live databases.",
            "Does not resolve arbitrary runtime string reflection (eval, getattr with dynamic strings) without runtime trace ingestion.",
            "Does not see external repositories or unindexed third-party registry source code.",
            "Does not replace reading exact function body lines when editing complex business logic.",
        ],
    }


def get_tool_capability(tool_name: str) -> ToolCapabilitySpec | None:
    """Look up the declarative capability spec for a tool by name."""
    return _TOOL_BY_NAME.get(tool_name)

