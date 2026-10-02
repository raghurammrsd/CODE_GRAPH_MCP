"""Per-task benchmark failure analysis with deterministic FN/FP classification.

Emits a TaskDiagnosticReport for every benchmark task with:
- True/false positive/negative symbol sets
- Relationship true/false positive/negative sets
- Exclusion violation detection
- FalseNegativeClass classification: why expected symbols were missed
- FalsePositiveClass classification: why wrong symbols were retrieved
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class FalseNegativeClass(StrEnum):
    """Why was an expected symbol not retrieved?"""

    TARGET_RESOLUTION = "TARGET_RESOLUTION"
    # Target never appeared in the query because it was excluded or not recognized
    LEXICAL_RECALL = "LEXICAL_RECALL"
    # Short name never matched any retrieved candidate
    QUALIFIED_NAME_RESOLUTION = "QUALIFIED_NAME_RESOLUTION"
    # Qualified form (A.B) needed; only bare A was retrieved
    GRAPH_TRAVERSAL = "GRAPH_TRAVERSAL"
    # Symbol reachable via CALLS/HANDLED_BY but traversal didn't reach it
    REFERENCE_RESOLUTION = "REFERENCE_RESOLUTION"
    # Symbol appears in imports/references table but not in candidates
    FRAMEWORK_DETECTION = "FRAMEWORK_DETECTION"
    # Symbol is a route handler that wasn't matched by framework retrieval
    TEST_LINKING = "TEST_LINKING"
    # Symbol is a test function that wasn't discovered via test linking
    RANKING = "RANKING"
    # Symbol was a candidate but ranked below effective cutoff
    BUDGET_PRUNING = "BUDGET_PRUNING"
    # Symbol was ranked but pruned by token budget optimizer
    OVER_FILTERING = "OVER_FILTERING"
    # Symbol was rejected by exclusion filter even though not explicitly excluded


class FalsePositiveClass(StrEnum):
    """Why was an unrequested symbol retrieved?"""

    LEXICAL_NOISE = "LEXICAL_NOISE"
    # Shares substring with query but is semantically unrelated
    GRAPH_POLLUTION = "GRAPH_POLLUTION"
    # Retrieved via graph expansion from an irrelevant seed symbol
    WRONG_TARGET = "WRONG_TARGET"
    # Retrieved a different homonym of the intended target
    WRONG_RELATIONSHIP = "WRONG_RELATIONSHIP"
    # Relationship type doesn't match task intent
    FRAMEWORK_NOISE = "FRAMEWORK_NOISE"
    # Route or handler unrelated to the query task
    TEST_NOISE = "TEST_NOISE"
    # Test file/symbol unrelated to task
    IMPORT_NOISE = "IMPORT_NOISE"
    # Import-expanded symbol that is stdlib/utility
    DUPLICATE_SYMBOL = "DUPLICATE_SYMBOL"
    # Same logical symbol under different qualified names
    PARENT_SCOPE_NOISE = "PARENT_SCOPE_NOISE"
    # Parent class retrieved when only a child method was relevant
    RANKING_ERROR = "RANKING_ERROR"
    # Score was inflated by an incorrect heuristic


@dataclass
class TaskDiagnosticReport:
    """Full per-task diagnostic breakdown."""

    task_id: str
    category: str
    intent: str
    prompt: str
    task_spec: dict[str, Any]
    target_resolution: dict[str, Any]  # target -> how it was resolved
    expected_symbols: list[str]
    retrieved_symbols: list[str]
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    expected_relationships: list[str]
    retrieved_relationships: list[str]
    relationship_true_positives: list[str]
    relationship_false_positives: list[str]
    relationship_false_negatives: list[str]
    excluded_symbols: list[str]
    excluded_files: list[str]
    exclusion_violations: list[str]
    expected_routes: list[str]
    retrieved_routes: list[str]
    expected_tests: list[str]
    retrieved_tests: list[str]
    candidate_count: int
    selected_count: int
    candidate_tokens: int
    selected_tokens: int
    reduction_ratio: float
    latency_ms: float
    retrieval_reasons: dict[str, list[str]] = field(default_factory=dict)  # symbol -> reason codes
    fn_classifications: list[str] = field(default_factory=list)  # FalseNegativeClass values
    fp_classifications: list[str] = field(default_factory=list)  # FalsePositiveClass values
    stage_of_entry: dict[str, str] = field(default_factory=dict)  # symbol -> stage entered (target_resolution, search, graph, test, route)
    stage_of_exit: dict[str, str] = field(default_factory=dict)   # symbol -> stage dropped/rejected
    first_seen_reason: dict[str, str] = field(default_factory=dict)
    rejection_reason: dict[str, str] = field(default_factory=dict)
    final_selection_reason: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

_STDLIB_PREFIXES = ("os.", "sys.", "re.", "io.", "json.", "pathlib.", "typing.", "abc.", "collections.")
_GENERIC_NAMES = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "run",
     "call", "start", "stop", "test", "init", "main", "handler", "login",
     "logout", "register", "index", "home"}
)


def _normalize_sym(s: str) -> str:
    """Normalize symbol for comparison: strip module prefix noise."""
    return s.strip()


def _short(s: str) -> str:
    return s.split(".")[-1]


def classify_false_negatives(
    expected: list[str],
    retrieved: list[str],
    packet_dict: dict[str, Any],
    task_spec_dict: dict[str, Any],
    excluded_symbols: list[str] | None = None,
    excluded_files: list[str] | None = None,
) -> list[str]:
    """Classify each false negative by the most likely root cause."""
    retrieved_set = {_normalize_sym(s) for s in retrieved}
    retrieved_short = {_short(s) for s in retrieved}
    exclusions_set = set(excluded_symbols or [])
    set(excluded_files or [])

    # Build sets from packet for deeper analysis
    budget = packet_dict.get("budget") or {}
    rejections = budget.get("rejections") or []
    rejected_syms: set[str] = set()
    pruned_syms: set[str] = set()
    for rej in rejections:
        sym = str(rej.get("symbol") or "")
        reason = str(rej.get("reason") or "").lower()
        if sym:
            rejected_syms.add(sym)
            if "budget" in reason or "token" in reason:
                pruned_syms.add(sym)

    entry_points = {str(ep.get("handler", "")) for ep in (packet_dict.get("entry_points") or [])}
    {str(ep.get("route_path", "")) for ep in (packet_dict.get("entry_points") or [])}

    targets_in_spec = set(task_spec_dict.get("targets") or [])
    priority_targets = set(task_spec_dict.get("priority_targets") or [])

    classifications: list[str] = []

    for sym in expected:
        if _normalize_sym(sym) in retrieved_set:
            continue  # it's a TP, skip

        short = _short(sym)
        cls: FalseNegativeClass | None = None

        # OVER_FILTERING: was in exclusions but shouldn't be
        if sym in exclusions_set or any(sym.startswith(excl + ".") for excl in exclusions_set):
            # it's supposed to be excluded; don't classify as FN
            continue

        # TARGET_RESOLUTION: never even queried (not in targets or priority_targets)
        if not (sym in targets_in_spec or short in targets_in_spec
                or sym in priority_targets or short in priority_targets):
            # Check if the symbol's short name was a query at all
            cls = FalseNegativeClass.TARGET_RESOLUTION

        # LEXICAL_RECALL: short name also not in retrieved
        elif short not in retrieved_short:
            if "." in sym:
                cls = FalseNegativeClass.QUALIFIED_NAME_RESOLUTION
            else:
                cls = FalseNegativeClass.LEXICAL_RECALL

        # BUDGET_PRUNING: was in rejections with budget reason
        elif sym in pruned_syms or short in {_short(p) for p in pruned_syms}:
            cls = FalseNegativeClass.BUDGET_PRUNING

        # RANKING: rejected but not budget reason
        elif sym in rejected_syms or short in {_short(r) for r in rejected_syms}:
            cls = FalseNegativeClass.RANKING

        # FRAMEWORK_DETECTION: expected as a route handler
        elif short in entry_points:
            cls = FalseNegativeClass.FRAMEWORK_DETECTION

        # TEST_LINKING: looks like a test symbol
        elif short.startswith("test_") or "test" in sym.lower().split(".")[0]:
            cls = FalseNegativeClass.TEST_LINKING

        # GRAPH_TRAVERSAL: short name retrieved but not full qualified form
        elif short in retrieved_short:
            cls = FalseNegativeClass.QUALIFIED_NAME_RESOLUTION

        else:
            cls = FalseNegativeClass.GRAPH_TRAVERSAL

        if cls is not None:
            classifications.append(cls.value)

    return classifications


def classify_false_positives(
    expected: list[str],
    retrieved: list[str],
    excluded_symbols: list[str] | None = None,
    excluded_files: list[str] | None = None,
    packet_dict: dict[str, Any] | None = None,
) -> list[str]:
    """Classify each false positive by the most likely root cause."""
    expected_set = {_normalize_sym(s) for s in expected}
    expected_short = {_short(s) for s in expected}
    exclusions_set = set(excluded_symbols or [])
    set(excluded_files or [])

    packet_dict = packet_dict or {}
    symbols_with_reasons: list[dict[str, Any]] = packet_dict.get("symbols") or []
    reason_map: dict[str, list[str]] = {}
    for s in symbols_with_reasons:
        sym = str(s.get("symbol") or "")
        reasons = s.get("reasons") or []
        reason_map[sym] = [str(r.get("code") or r) for r in reasons]

    classifications: list[str] = []

    for sym in retrieved:
        norm = _normalize_sym(sym)
        short = _short(sym)
        if norm in expected_set:
            continue  # Exact TP, skip

        # DUPLICATE_SYMBOL: different qualified name for same logical concept
        if short in expected_short and ("." in sym or norm != short):
            classifications.append(FalsePositiveClass.DUPLICATE_SYMBOL.value)
            continue

        if short in expected_short:
            continue  # TP matched on short name, skip

        # EXCLUSION VIOLATION: should have been filtered
        if sym in exclusions_set or any(sym.startswith(excl + ".") for excl in exclusions_set):
            # This is an exclusion violation, not a regular FP
            continue

        reasons = reason_map.get(sym, [])
        cls: FalsePositiveClass | None = None

        # TEST_NOISE: test file/symbol but task isn't TEST intent
        if "test" in sym.lower() and short.startswith("test_"):
            cls = FalsePositiveClass.TEST_NOISE

        # IMPORT_NOISE: stdlib prefix or very short generic name
        elif any(sym.startswith(p) for p in _STDLIB_PREFIXES):
            cls = FalsePositiveClass.IMPORT_NOISE

        # PARENT_SCOPE_NOISE: parent class of an expected method
        elif not short.endswith(sym) and any(
            e.startswith(sym + ".") for e in expected_set
        ):
            cls = FalsePositiveClass.PARENT_SCOPE_NOISE

        # LEXICAL_NOISE: generic name that shares substring
        elif short.lower() in _GENERIC_NAMES:
            cls = FalsePositiveClass.LEXICAL_NOISE

        # GRAPH_POLLUTION: retrieved via graph with low score
        elif "GRAPH_DISTANCE" in reasons or "DIRECT_CALLEE" in reasons:
            cls = FalsePositiveClass.GRAPH_POLLUTION

        # FRAMEWORK_NOISE: route/handler via framework retrieval
        elif "ENTRY_POINT" in reasons:
            cls = FalsePositiveClass.FRAMEWORK_NOISE

        # RANKING_ERROR: inflated score
        elif "NAME_MATCH" in reasons and short.lower() in _GENERIC_NAMES:
            cls = FalsePositiveClass.RANKING_ERROR

        else:
            cls = FalsePositiveClass.LEXICAL_NOISE

        if cls is not None:
            classifications.append(cls.value)

    return classifications


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_task_diagnostic(
    task_id: str,
    category: str,
    intent: str,
    prompt: str,
    packet_dict: dict[str, Any],
    expected_symbols: list[str],
    expected_relationships: list[str],
    expected_routes: list[str],
    expected_tests: list[str],
    excluded_symbols: list[str],
    excluded_files: list[str],
    latency_ms: float,
) -> TaskDiagnosticReport:
    """Build a complete TaskDiagnosticReport from a context packet."""

    # Extract retrieved symbols
    raw_symbols: list[dict[str, Any]] = packet_dict.get("symbols") or []
    retrieved_symbols = [str(s.get("symbol") or "") for s in raw_symbols if s.get("symbol")]

    {s.strip() for s in retrieved_symbols}
    {s.strip() for s in expected_symbols}

    # Short-name comparison helper
    def _matches(expected_sym: str, retrieved_sym: str) -> bool:
        """True if expected_sym matches retrieved_sym (exact or short-name)."""
        e = expected_sym.strip()
        r = retrieved_sym.strip()
        if e == r:
            return True
        if _short(e) == _short(r) and _short(e):
            return True
        # partial qualified match: AuthService matches AuthService.login? No. AuthService.login matches AuthService? No.
        # But "login" matches "AuthService.login"? Yes for short form
        if _short(e) == r or e == _short(r):
            return True
        return False

    # Compute TP/FP/FN with short-name matching
    true_positives: list[str] = []
    false_negatives: list[str] = []
    for e in expected_symbols:
        if any(_matches(e, r) for r in retrieved_symbols):
            true_positives.append(e)
        else:
            false_negatives.append(e)

    false_positives: list[str] = []
    for r in retrieved_symbols:
        if not any(_matches(e, r) for e in expected_symbols):
            false_positives.append(r)

    # Relationships
    raw_rels: list[dict[str, Any]] = packet_dict.get("relationships") or []
    retrieved_rels = [
        f"{r.get('source')}->{r.get('target')}" for r in raw_rels if r.get("source") and r.get("target")
    ]
    expected_rel_set = set(expected_relationships)
    retrieved_rel_set = set(retrieved_rels)
    rel_tp = sorted(expected_rel_set & retrieved_rel_set)
    rel_fp = sorted(retrieved_rel_set - expected_rel_set)
    rel_fn = sorted(expected_rel_set - retrieved_rel_set)

    # Routes
    raw_eps = packet_dict.get("entry_points") or []
    retrieved_routes = [str(ep.get("route_path") or ep.get("endpoint_id") or "") for ep in raw_eps]

    # Tests
    raw_tests: list[dict[str, Any]] = packet_dict.get("tests") or []
    retrieved_tests = [str(t.get("symbol") or t.get("file") or "") for t in raw_tests if t]

    # Exclusion violations
    excl_set = set(excluded_symbols)
    exclusion_violations = [
        s for s in retrieved_symbols
        if s in excl_set or any(s.startswith(excl + ".") for excl in excl_set)
    ]

    # Token budget info
    budget = packet_dict.get("budget") or {}
    candidate_tokens = int(budget.get("candidate_tokens") or 0)
    selected_tokens = int(budget.get("selected_tokens") or 0)
    reduction_ratio = float(budget.get("reduction_ratio") or 0.0)

    # Candidate/selected counts
    execution = packet_dict.get("execution") or {}
    candidate_count = int(execution.get("candidate_count") or len(raw_symbols))
    selected_count = int(execution.get("selected_count") or len(raw_symbols))

    # Retrieval reasons map
    retrieval_reasons: dict[str, list[str]] = {}
    for s in raw_symbols:
        sym = str(s.get("symbol") or "")
        reasons = s.get("reasons") or []
        retrieval_reasons[sym] = [str(r.get("code") or r) for r in reasons]

    # Task spec
    task_spec_dict: dict[str, Any] = packet_dict.get("task_spec") or {}

    # Target resolution (lightweight: check if each expected target was in spec targets)
    spec_targets = set(task_spec_dict.get("targets") or [])
    target_resolution: dict[str, Any] = {}
    for sym in expected_symbols:
        short = _short(sym)
        if sym in spec_targets or short in spec_targets:
            target_resolution[sym] = {"method": "spec_target", "confidence": "HIGH"}
        elif any(_matches(sym, r) for r in retrieved_symbols):
            target_resolution[sym] = {"method": "retrieval_match", "confidence": "MEDIUM"}
        else:
            target_resolution[sym] = {"method": "not_found", "confidence": "UNKNOWN"}

    # Classify FN/FP
    fn_classes = classify_false_negatives(
        expected_symbols, retrieved_symbols, packet_dict, task_spec_dict,
        excluded_symbols, excluded_files,
    )
    fp_classes = classify_false_positives(
        expected_symbols, retrieved_symbols, excluded_symbols, excluded_files, packet_dict
    )

    # Detailed stage provenance tracking
    stage_of_entry: dict[str, str] = {}
    stage_of_exit: dict[str, str] = {}
    first_seen_reason: dict[str, str] = {}
    rejection_reason: dict[str, str] = {}
    final_selection_reason: dict[str, str] = {}

    for s in raw_symbols:
        sym = str(s.get("symbol") or "")
        reasons = s.get("reasons") or []
        first_code = str(reasons[0].get("code") if reasons and isinstance(reasons[0], dict) else (reasons[0] if reasons else "SELECTED"))
        stage_of_entry[sym] = "RETRIEVAL_CANDIDATE"
        first_seen_reason[sym] = first_code
        final_selection_reason[sym] = f"Score={s.get('score', 0.0)}"

    rejections: list[dict[str, Any]] = execution.get("rejections") or budget.get("rejections") or []
    for rej in rejections:
        sym = str(rej.get("symbol") or rej.get("canonical_id") or rej.get("item_id") or "")
        reason = str(rej.get("reason") or "BUDGET_PRUNED")
        if sym:
            stage_of_exit[sym] = "BUDGET_OPTIMIZER"
            rejection_reason[sym] = reason

    return TaskDiagnosticReport(
        task_id=task_id,
        category=category,
        intent=intent,
        prompt=prompt,
        task_spec=task_spec_dict,
        target_resolution=target_resolution,
        expected_symbols=expected_symbols,
        retrieved_symbols=retrieved_symbols,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        expected_relationships=expected_relationships,
        retrieved_relationships=retrieved_rels,
        relationship_true_positives=rel_tp,
        relationship_false_positives=rel_fp,
        relationship_false_negatives=rel_fn,
        excluded_symbols=excluded_symbols,
        excluded_files=excluded_files,
        exclusion_violations=exclusion_violations,
        expected_routes=expected_routes,
        retrieved_routes=retrieved_routes,
        expected_tests=expected_tests,
        retrieved_tests=retrieved_tests,
        candidate_count=candidate_count,
        selected_count=selected_count,
        candidate_tokens=candidate_tokens,
        selected_tokens=selected_tokens,
        reduction_ratio=reduction_ratio,
        latency_ms=latency_ms,
        retrieval_reasons=retrieval_reasons,
        fn_classifications=fn_classes,
        fp_classifications=fp_classes,
        stage_of_entry=stage_of_entry,
        stage_of_exit=stage_of_exit,
        first_seen_reason=first_seen_reason,
        rejection_reason=rejection_reason,
        final_selection_reason=final_selection_reason,
    )
