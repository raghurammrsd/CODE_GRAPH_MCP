"""Global Token Budget Optimizer, Redundancy Control, Evidence Compression, and Coverage Engine.

Maximizes evidence quality, relationship coverage, freshness, and diversity of useful
context under strict deterministic budget constraints while eliminating redundant chunks
and compressing repeated evidence without weakening epistemic guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraph.task import TaskSpec

# Reason codes for selected context candidates
REASON_DIRECT_TARGET = "DIRECT_TARGET"
REASON_DIRECT_CALLER = "DIRECT_CALLER"
REASON_VERIFIED_CALLEE = "VERIFIED_CALLEE"
REASON_RELEVANT_ROUTE = "RELEVANT_ROUTE"
REASON_RELATED_TEST = "RELATED_TEST"
REASON_PACKAGE_OWNER = "PACKAGE_OWNER"
REASON_DEPENDENCY_PACKAGE = "DEPENDENCY_PACKAGE"
REASON_HIGH_VALUE_EVIDENCE = "HIGH_VALUE_EVIDENCE"
REASON_COVERAGE_FILL = "COVERAGE_FILL"
REASON_AMBIGUITY_PRESERVED = "AMBIGUITY_PRESERVED"

_EVIDENCE_CLASS_RANK = {
    "AST_VERIFIED": 5,
    "FRAMEWORK_VERIFIED": 4,
    "DATAFLOW_VERIFIED": 3,
    "POSSIBLE": 2,
    "UNKNOWN": 1,
}

_CONFIDENCE_RANK = {
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
}


# Hard upper safety limits enforced even when omitted or exceeded
HARD_MAX_TOKENS = 20_000
HARD_MAX_FILES = 30
HARD_MAX_LINES = 1_500
HARD_MAX_SYMBOLS = 50
HARD_MAX_RELATIONSHIPS = 60


@dataclass(frozen=True)
class ContextBudgetSpec:
    """Explicit deterministic context budget bounds."""

    max_tokens: int = 20_000
    max_symbols: int = 25
    max_relationships: int = 30
    max_files: int = 15
    max_lines: int = 500
    max_depth: int = 3
    max_package_depth: int = 2

    def as_dict(self) -> dict[str, int]:
        return {
            "max_tokens": self.max_tokens,
            "max_symbols": self.max_symbols,
            "max_relationships": self.max_relationships,
            "max_files": self.max_files,
            "max_lines": self.max_lines,
            "max_depth": self.max_depth,
            "max_package_depth": self.max_package_depth,
        }


@dataclass(frozen=True)
class ContextBudget:
    candidate_tokens: int
    selected_tokens: int
    reduction_ratio: float
    budget_limit: int
    rejections: tuple[dict[str, object], ...] = ()
    candidate_count: int = 0
    selected_count: int = 0
    candidate_reduction_ratio: float = 0.0
    selected_reduction_ratio: float = 0.0
    budget_utilization: float = 0.0
    coverage_score: float = 0.0
    redundancy_ratio: float = 0.0
    evidence_density: float = 0.0
    direct_file_reads: int = 0
    direct_file_lines: int = 0
    selected_files: int = 0
    selected_lines: int = 0
    truncated: bool = False
    tool_calls: int = 1
    max_symbols: int = 25
    max_relationships: int = 30
    max_files: int = 15
    max_lines: int = 500
    max_depth: int = 3
    max_package_depth: int = 2
    covered_dimensions: tuple[str, ...] = ()
    missing_dimensions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "candidate_tokens": self.candidate_tokens,
            "selected_tokens": self.selected_tokens,
            "selected_files": self.selected_files,
            "selected_lines": self.selected_lines,
            "truncated": self.truncated,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "candidate_reduction_ratio": round(self.candidate_reduction_ratio, 4),
            "selected_reduction_ratio": round(self.selected_reduction_ratio, 4),
            "budget_limit": self.budget_limit,
            "budget_utilization": round(self.budget_utilization, 4),
            "coverage_score": round(self.coverage_score, 4),
            "redundancy_ratio": round(self.redundancy_ratio, 4),
            "evidence_density": round(self.evidence_density, 4),
            "direct_file_reads": self.direct_file_reads,
            "direct_file_lines": self.direct_file_lines,
            "tool_calls": self.tool_calls,
            "max_symbols": self.max_symbols,
            "max_relationships": self.max_relationships,
            "max_files": self.max_files,
            "max_lines": self.max_lines,
            "max_depth": self.max_depth,
            "max_package_depth": self.max_package_depth,
            "covered_dimensions": list(self.covered_dimensions),
            "missing_dimensions": list(self.missing_dimensions),
            "rejections": list(self.rejections),
        }


@dataclass(frozen=True)
class ContextCandidate:
    candidate_id: str
    canonical_id: str | None
    source_type: str
    estimated_tokens: int
    relevance: float
    evidence_quality: float
    freshness: float
    relationship_value: float
    coverage_value: float
    redundancy_group: str | None
    status: str
    confidence: str
    reason_code: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "canonical_id": self.canonical_id,
            "source_type": self.source_type,
            "estimated_tokens": self.estimated_tokens,
            "relevance": self.relevance,
            "evidence_quality": self.evidence_quality,
            "freshness": self.freshness,
            "relationship_value": self.relationship_value,
            "coverage_value": self.coverage_value,
            "redundancy_group": self.redundancy_group,
            "status": self.status,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
        }


@dataclass
class CandidateContextItem:
    item_id: str
    file_path: str
    start_line: int
    end_line: int
    canonical_id: str | None
    estimated_tokens: int
    relevance_score: float  # 0.0 - 1.0
    evidence_quality: float  # 0.0 - 1.0
    freshness: str  # FRESH | PARTIALLY_STALE | STALE | UNKNOWN
    coverage_layer: str  # ENTRYPOINT | HANDLER | SERVICE | DATA | TEST | GIT | ARCHITECTURE | GENERAL
    source_type: str  # chunk | symbol | edge | test | git | route
    snippet: str
    confidence: str = "HIGH"
    relationship_value: float = 0.5
    epistemic_status: str = "FACT"  # FACT | ASSUMPTION | INFERENCE | UNKNOWN | CONFLICT | POSSIBLE | AMBIGUOUS
    coverage_value: float = 0.5
    data: dict[str, Any] = field(default_factory=dict)
    why_selected: list[str] = field(default_factory=list)
    reason_code: str = ""
    package_id: str | None = None
    package_distance: int = 0  # 0=owner, 1=direct dep, 2=transitive, 99=unrelated
    artifact_class: str = "SOURCE"
    graph_distance: int = 0
    task_dimension: str = ""

    @property
    def relevance(self) -> float:
        return self.relevance_score

    @property
    def status(self) -> str:
        return self.epistemic_status

    @property
    def redundancy_group(self) -> str:
        return self.duplicate_key

    @property
    def duplicate_key(self) -> str:
        """Deterministic grouping key for redundancy detection by canonical identity."""
        if self.canonical_id:
            return f"sym:{self.canonical_id}"
        sym = self.data.get("symbol")
        if sym:
            return f"sym:{self.file_path}::{sym}"
        return f"loc:{self.file_path}:{self.start_line}"

    @property
    def line_count(self) -> int:
        if self.snippet:
            return max(1, len(self.snippet.splitlines()))
        return max(1, self.end_line - self.start_line + 1)

    def infer_dimension(self) -> str:
        """Determine the task coverage dimension represented by this candidate."""
        if self.task_dimension:
            return self.task_dimension
        if self.epistemic_status in ("UNKNOWN", "CONFLICT", "POSSIBLE", "AMBIGUOUS"):
            return "UNKNOWN"
        rel = str(self.data.get("relationship") or "").upper()
        reasons = self.data.get("reasons", [])
        reason_codes = {getattr(r, "code", "") for r in reasons}
        if any(c in reason_codes for c in ("EXACT_CANONICAL", "EXACT_QUALIFIED", "EXACT_SYMBOL")):
            return "TARGET"
        if self.coverage_layer == "ENTRYPOINT" or rel in ("HANDLED_BY", "ROUTES_TO", "MOUNTS", "ROUTE_HANDLER"):
            return "ROUTE"
        if self.coverage_layer == "TEST" or rel.startswith("TEST") or self.source_type == "test":
            return "TEST"
        if rel in ("INJECTS", "PROVIDES", "RESOLVES_DEPENDENCY", "CONFIGURES"):
            return "PROVIDER"
        if rel in ("REGISTERS", "DISPATCHES_TO", "EVENT_LISTENER", "TASK_HANDLER", "COMMAND_HANDLER"):
            return "REGISTRATION"
        if rel == "DEPENDS_ON_PACKAGE":
            return "PACKAGE"
        if "DIRECT_CALLER" in reason_codes or "POSSIBLE_CALLER" in reason_codes or rel in ("CALLERS", "CALLED_BY", "POSSIBLE_CALLS"):
            return "CALLER"
        if "DIRECT_CALLEE" in reason_codes or rel == "CALLS":
            return "CALLEE"
        if self.coverage_layer == "GIT":
            return "GIT"
        if self.coverage_layer in ("SERVICE", "DATA", "HANDLER"):
            return self.coverage_layer
        return "TARGET" if self.relevance_score >= 0.7 else "GENERAL"

    def infer_reason_code(self, is_coverage_fill: bool = False) -> str:
        """Assign an explainable reason code for selection."""
        if self.reason_code:
            return self.reason_code
        if self.epistemic_status in ("UNKNOWN", "CONFLICT", "POSSIBLE", "AMBIGUOUS"):
            return REASON_AMBIGUITY_PRESERVED
        dim = self.infer_dimension()
        if dim == "TARGET":
            return REASON_DIRECT_TARGET
        if dim == "ROUTE":
            return REASON_RELEVANT_ROUTE
        if dim == "TEST":
            return REASON_RELATED_TEST
        if dim == "CALLER":
            return REASON_DIRECT_CALLER
        if dim == "CALLEE":
            return REASON_VERIFIED_CALLEE
        if dim in ("PROVIDER", "REGISTRATION"):
            return REASON_HIGH_VALUE_EVIDENCE
        if self.package_id and self.package_distance == 0:
            return REASON_PACKAGE_OWNER
        if self.package_id and self.package_distance in (1, 2):
            return REASON_DEPENDENCY_PACKAGE
        if is_coverage_fill:
            return REASON_COVERAGE_FILL
        return REASON_HIGH_VALUE_EVIDENCE

    def to_context_candidate(self) -> ContextCandidate:
        f_mult = _freshness_multiplier(self.freshness)
        return ContextCandidate(
            candidate_id=self.item_id,
            canonical_id=self.canonical_id,
            source_type=self.source_type,
            estimated_tokens=self.estimated_tokens,
            relevance=self.relevance_score,
            evidence_quality=self.evidence_quality,
            freshness=f_mult,
            relationship_value=self.relationship_value,
            coverage_value=self.coverage_value,
            redundancy_group=self.duplicate_key,
            status=self.epistemic_status,
            confidence=self.confidence,
            reason_code=self.reason_code or self.infer_reason_code(),
        )


def _freshness_multiplier(freshness: str) -> float:
    if freshness == "FRESH":
        return 1.0
    if freshness == "PARTIALLY_STALE":
        return 0.7
    if freshness == "STALE":
        return 0.3
    return 0.5


def _confidence_penalty(confidence: str) -> float:
    if confidence == "HIGH":
        return 0.0
    if confidence == "MEDIUM":
        return 0.1
    return 0.25


def _epistemic_multiplier(status: str) -> float:
    if status == "FACT":
        return 1.0
    if status == "ASSUMPTION":
        return 0.85
    if status == "INFERENCE":
        return 0.70
    if status == "UNKNOWN":
        return 0.40
    if status == "CONFLICT":
        return 0.30
    return 0.70


def _artifact_penalty(artifact_class: str) -> float:
    cat = artifact_class.upper()
    if cat in ("MINIFIED", "BUNDLE", "BUILD_ARTIFACT", "BINARY"):
        return 0.50
    if cat == "VENDOR":
        return 0.40
    if cat == "GENERATED":
        return 0.20
    return 0.0


def _package_adjustment(package_distance: int) -> float:
    if package_distance == 0:
        return 0.08  # target package bonus
    if package_distance == 1:
        return 0.04  # direct dependency/dependent bonus
    if package_distance == 2:
        return 0.0
    if package_distance >= 99:
        return -0.15  # unrelated workspace package penalty
    return -0.05 * (package_distance - 1)


def compute_item_utility(
    item: CandidateContextItem,
    selected_layers: set[str],
    selected_duplicate_keys: set[str],
    selected_dimensions: set[str] | None = None,
) -> float:
    """Calculate deterministic utility score for a candidate context item."""
    fresh_factor = _freshness_multiplier(item.freshness)
    conf_penalty = _confidence_penalty(item.confidence)
    epistemic_factor = _epistemic_multiplier(item.epistemic_status)
    art_penalty = _artifact_penalty(item.artifact_class)
    pkg_adj = _package_adjustment(item.package_distance) if item.package_id else 0.0
    dist_penalty = min(0.20, 0.04 * max(0, item.graph_distance))

    # Coverage reward: boost item if it introduces a required layer or dimension not yet represented
    dim = item.infer_dimension()
    layer_unseen = item.coverage_layer not in selected_layers
    dim_unseen = selected_dimensions is not None and dim not in selected_dimensions and dim != "GENERAL"
    coverage_factor = 1.3 if (layer_unseen or dim_unseen) else 1.0

    # Redundancy penalty: heavily discount items sharing duplicate keys with already selected items
    redundancy_penalty = 0.5 if item.duplicate_key in selected_duplicate_keys else 0.0

    utility = (
        (item.relevance_score * 0.40)
        + (item.evidence_quality * 0.20)
        + (item.relationship_value * 0.15)
        + (fresh_factor * 0.15)
        + (epistemic_factor * 0.10)
        + pkg_adj
    ) * coverage_factor

    final_score = max(0.01, utility - redundancy_penalty - conf_penalty - art_penalty - dist_penalty)
    return round(final_score, 4)


def _is_excluded(item: CandidateContextItem, task_spec: TaskSpec | None) -> bool:
    """Return True if this candidate violates a hard exclusion constraint.

    Hierarchical rules:
    - "AuthService" excludes AuthService AND AuthService.login AND AuthService.*
    - "src/admin_panel" excludes any file_path starting with that prefix
    - Canonical-ID comparison preferred over raw string matching
    """
    if not task_spec or not task_spec.exclusions:
        return False
    item_sym = item.canonical_id or str(item.data.get("symbol") or "")
    item_file = item.file_path or ""
    for excl in task_spec.exclusions:
        if not excl:
            continue
        # ── exact symbol match ───────────────────────────────────────────
        if item_sym and (item_sym == excl):
            return True
        # ── hierarchical: AuthService excludes AuthService.anything ──────
        if item_sym and (
            item_sym.startswith(excl + ".") or item_sym.startswith(excl + ":")
        ):
            return True
        # ── exact file match ─────────────────────────────────────────────
        if item_file and item_file == excl:
            return True
        # ── file path prefix (module/directory exclusion) ────────────────
        if item_file and (item_file.startswith(excl + "/") or item_file.startswith(excl + "\\")):
            return True
        # ── file contains the exclusion path segment ─────────────────────
        if item_file and len(excl) >= 4 and excl in item_file:
            return True
        # ── substring match on symbol (kept for backward compat, len >= 4) ─
        if item_sym and len(excl) >= 4 and excl in item_sym:
            return True
    return False


def select_bounded_snippet(
    content: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 35,
    max_chars: int = 800,
) -> tuple[str, int, int]:
    """Extract a deterministic, bounded source snippet without dumping entire files.

    Returns:
        (bounded_snippet, requested_lines, returned_lines)
    """
    if not content:
        return "", 0, 0
    lines = content.splitlines()
    total_requested = len(lines)
    if total_requested == 0:
        return "", 0, 0

    bounded_lines = lines[:max(1, max_lines)]
    text = "\n".join(bounded_lines)
    if len(text) > max_chars:
        text = text[:max_chars]
        bounded_lines = text.splitlines()

    returned_lines = len(bounded_lines)
    return text, total_requested, returned_lines


def compress_relationships(
    relationships: list[Any],
    max_relationships: int = 30,
) -> tuple[list[Any], dict[str, Any]]:
    """Deterministically compress duplicate relationship findings while preserving traceability.

    Rules:
    - Group strictly by (source, target, relationship). Never merge different relationship types.
    - Keep the strongest evidence class and highest confidence as the primary record.
    - Retain concise supporting locations when multiple locations prove the same direct fact.
    - Never drop the only evidence for a claim.
    - Never convert UNKNOWN into a positive relationship or POSSIBLE into verified.
    """
    if not relationships:
        return [], {"raw_count": 0, "compressed_count": 0, "duplicates_merged": 0}

    from codegraph.evidence_contract import validate_relationship_record

    grouped: dict[tuple[str, str, str], list[Any]] = {}
    order_keys: list[tuple[str, str, str]] = []

    for r in relationships:
        validated = validate_relationship_record(r)
        if isinstance(r, dict):
            r["relationship"] = validated.relationship
            r["evidence_class"] = validated.evidence_class
            r["confidence"] = validated.confidence
            r["status"] = validated.status
        key = (validated.source, validated.target, validated.relationship)
        if key not in grouped:
            grouped[key] = []
            order_keys.append(key)
        grouped[key].append(r)

    compressed: list[Any] = []
    duplicates_merged = 0

    for key in order_keys:
        group = grouped[key]
        if len(group) == 1:
            compressed.append(group[0])
            continue

        duplicates_merged += len(group) - 1

        # Sort group to pick the strongest primary record deterministically
        def _rel_rank(item: Any) -> tuple[int, int, str, int]:
            conf = str(getattr(item, "confidence", "HIGH") if not isinstance(item, dict) else item.get("confidence", "HIGH")).upper()
            ev_cls = str(getattr(item, "evidence_class", "") if not isinstance(item, dict) else item.get("evidence_class", "")).upper()
            f_path = str(getattr(item, "file", "") or (item.get("file", "") if isinstance(item, dict) else ""))
            s_line = int(getattr(item, "start_line", 0) or (item.get("start_line", 0) if isinstance(item, dict) else 0) or 0)
            return (
                -_EVIDENCE_CLASS_RANK.get(ev_cls, 0),
                -_CONFIDENCE_RANK.get(conf, 0),
                f_path,
                s_line,
            )

        sorted_group = sorted(group, key=_rel_rank)
        primary = sorted_group[0]

        # Collect concise supporting locations (up to 4 additional locations)
        supporting_locs: list[str] = []
        for extra in sorted_group[1:]:
            ef = str(getattr(extra, "file", "") or (extra.get("file", "") if isinstance(extra, dict) else ""))
            el = getattr(extra, "start_line", None) if not isinstance(extra, dict) else extra.get("start_line")
            loc_str = f"{ef}:{el}" if ef and el else ef
            if loc_str and loc_str not in supporting_locs:
                supporting_locs.append(loc_str)

        if hasattr(primary, "supporting_locations"):
            try:
                object.__setattr__(primary, "supporting_locations", supporting_locs[:4])
                object.__setattr__(primary, "occurrence_count", len(group))
            except Exception:
                pass
        elif isinstance(primary, dict):
            primary["supporting_locations"] = supporting_locs[:4]
            primary["occurrence_count"] = len(group)

        compressed.append(primary)

    # Sort compressed relationships deterministically:
    # 1. Confidence rank desc
    # 2. Source, relationship, target ascending
    def _final_rel_sort(item: Any) -> tuple[int, str, str, str]:
        conf = str(getattr(item, "confidence", "HIGH") if not isinstance(item, dict) else item.get("confidence", "HIGH")).upper()
        src = str(getattr(item, "source", "") if not isinstance(item, dict) else item.get("source", ""))
        rel = str(getattr(item, "relationship", "") if not isinstance(item, dict) else item.get("relationship", ""))
        tgt = str(getattr(item, "target", "") if not isinstance(item, dict) else item.get("target", ""))
        return (-_CONFIDENCE_RANK.get(conf, 0), src, rel, tgt)

    compressed.sort(key=_final_rel_sort)
    bounded = compressed[:max(1, max_relationships)]

    stats = {
        "raw_count": len(relationships),
        "compressed_count": len(bounded),
        "duplicates_merged": duplicates_merged,
    }
    return bounded, stats


def optimize_context_budget(
    candidates: list[CandidateContextItem],
    token_budget: int,
    task_spec: TaskSpec | None = None,
    budget_spec: ContextBudgetSpec | None = None,
    required_dimensions: tuple[str, ...] = ("TARGET", "SERVICE", "TEST"),
    verified_claims_count: int = 0,
    tool_calls: int = 1,
) -> tuple[list[CandidateContextItem], ContextBudget]:
    """Deterministically select the highest-utility, coverage-preserving subset of candidates."""
    raw_max_symbols = budget_spec.max_symbols if budget_spec else 25
    raw_max_relationships = budget_spec.max_relationships if budget_spec else 30
    raw_max_files = budget_spec.max_files if budget_spec else 15
    raw_max_lines = budget_spec.max_lines if budget_spec else 500
    max_depth = budget_spec.max_depth if budget_spec else 3
    max_package_depth = budget_spec.max_package_depth if budget_spec else 2

    was_clamped = (
        token_budget > HARD_MAX_TOKENS
        or raw_max_symbols > HARD_MAX_SYMBOLS
        or raw_max_relationships > HARD_MAX_RELATIONSHIPS
        or raw_max_files > HARD_MAX_FILES
        or raw_max_lines > HARD_MAX_LINES
    )
    token_budget = min(token_budget, HARD_MAX_TOKENS)
    max_symbols = max(1, min(raw_max_symbols, HARD_MAX_SYMBOLS))
    max_relationships = max(1, min(raw_max_relationships, HARD_MAX_RELATIONSHIPS))
    max_files = max(1, min(raw_max_files, HARD_MAX_FILES))
    max_lines = max(1, min(raw_max_lines, HARD_MAX_LINES))

    if not candidates or token_budget <= 0 or (budget_spec is not None and (budget_spec.max_files <= 0 or budget_spec.max_lines <= 0)):
        return [], ContextBudget(
            candidate_tokens=sum(c.estimated_tokens for c in candidates) if candidates else 0,
            selected_tokens=0,
            reduction_ratio=1.0 if candidates else 0.0,
            budget_limit=max(0, token_budget),
            candidate_count=len(candidates) if candidates else 0,
            selected_count=0,
            candidate_reduction_ratio=1.0 if candidates else 0.0,
            selected_reduction_ratio=1.0 if candidates else 0.0,
            budget_utilization=0.0,
            coverage_score=0.0,
            redundancy_ratio=0.0,
            evidence_density=0.0,
            direct_file_reads=0,
            direct_file_lines=0,
            selected_files=0,
            selected_lines=0,
            truncated=bool(candidates),
            tool_calls=tool_calls,
            max_symbols=max_symbols,
            max_relationships=max_relationships,
            max_files=max_files,
            max_lines=max_lines,
            max_depth=max_depth,
            max_package_depth=max_package_depth,
            covered_dimensions=(),
            missing_dimensions=required_dimensions,
        )

    candidate_count_total = len(candidates)
    candidate_tokens_total = sum(c.estimated_tokens for c in candidates)

    # Initial deterministic sort of candidates:
    # 1. Relevance score descending
    # 2. Evidence quality descending
    # 3. Package distance ascending
    # 4. Canonical ID or file path ascending (stable tie-breaker)
    # 5. Start line ascending
    sorted_candidates = sorted(
        candidates,
        key=lambda x: (
            -x.relevance_score,
            -x.evidence_quality,
            x.package_distance,
            x.canonical_id or x.file_path,
            x.start_line,
        ),
    )

    selected: list[CandidateContextItem] = []
    selected_layers: set[str] = set()
    selected_dimensions: set[str] = set()
    selected_duplicate_keys: set[str] = set()
    selected_files: set[str] = set()
    selected_tokens = 0
    selected_lines = 0
    selected_symbols_count = 0
    snippet_trimmed = False

    def _is_epistemic_uncertainty(item: CandidateContextItem) -> bool:
        ev_cls = str(item.data.get("evidence_class", "")).upper()
        return (
            item.epistemic_status in ("UNKNOWN", "CONFLICT", "POSSIBLE", "AMBIGUOUS")
            or ev_cls in ("UNKNOWN", "POSSIBLE")
            or item.source_type in ("uncertainty", "finding")
        )

    def _can_fit(item: CandidateContextItem, is_epistemic_uncertainty: bool = False) -> bool:
        if item.graph_distance > max_depth:
            return False
        if item.package_distance != 99 and item.package_distance > max_package_depth:
            return False
        if selected_tokens + item.estimated_tokens > token_budget:
            return False
        if not is_epistemic_uncertainty and selected_symbols_count >= max_symbols:
            return False
        if (
            not is_epistemic_uncertainty
            and item.file_path
            and item.file_path not in selected_files
            and len(selected_files) >= max_files
        ):
            return False
        if (
            not is_epistemic_uncertainty
            and selected_lines + item.line_count > max_lines
        ):
            return False
        return True

    def _trim_to_fit(item: CandidateContextItem, is_epistemic_uncertainty: bool = False) -> bool:
        nonlocal snippet_trimmed
        if item.graph_distance > max_depth:
            return False
        if item.package_distance != 99 and item.package_distance > max_package_depth:
            return False
        if not is_epistemic_uncertainty and selected_symbols_count >= max_symbols:
            return False
        if (
            not is_epistemic_uncertainty
            and item.file_path
            and item.file_path not in selected_files
            and len(selected_files) >= max_files
        ):
            return False
        rem_tokens = token_budget - selected_tokens
        rem_lines = max_lines - selected_lines if not is_epistemic_uncertainty else max(1, max_lines - selected_lines)
        if rem_tokens <= 0 or rem_lines <= 0:
            return False
        max_chars = max(4, rem_tokens * 4)
        lines = (item.snippet or "").splitlines()
        bounded_lines = lines[:rem_lines] if lines else []
        trimmed_text = "\n".join(bounded_lines)
        if len(trimmed_text) > max_chars:
            trimmed_text = trimmed_text[:max_chars]
        item.snippet = trimmed_text
        item.estimated_tokens = min(rem_tokens, max(1, len(trimmed_text) // 4))
        snippet_trimmed = True
        return _can_fit(item, is_epistemic_uncertainty=is_epistemic_uncertainty)

    def _accept(item: CandidateContextItem, is_coverage_fill: bool, why: list[str]) -> None:
        nonlocal selected_tokens, selected_lines, selected_symbols_count
        item.reason_code = item.infer_reason_code(is_coverage_fill=is_coverage_fill)
        item.why_selected = [f"Reason: {item.reason_code}"] + why
        selected.append(item)
        selected_tokens += item.estimated_tokens
        selected_lines += item.line_count
        if not _is_epistemic_uncertainty(item):
            selected_symbols_count += 1
        selected_layers.add(item.coverage_layer)
        selected_dimensions.add(item.infer_dimension())
        selected_duplicate_keys.add(item.duplicate_key)
        if item.file_path:
            selected_files.add(item.file_path)

    # Pass 0: Preserve high-value UNKNOWN / POSSIBLE / CONFLICT / AMBIGUOUS findings
    for item in sorted_candidates:
        if _is_excluded(item, task_spec):
            continue
        if _is_epistemic_uncertainty(item) and item.relevance_score >= 0.2:
            if item.duplicate_key not in selected_duplicate_keys:
                if _can_fit(item, is_epistemic_uncertainty=True) or _trim_to_fit(item, is_epistemic_uncertainty=True):
                    _accept(
                        item,
                        is_coverage_fill=True,
                        why=[
                            f"Epistemic preservation: '{item.epistemic_status}'",
                            f"Relevance: {item.relevance_score:.2f}",
                        ],
                    )

    # Pass 1a: Task Dimension Coverage pass — ensure required task dimensions
    # (e.g. TARGET, CALLER, CALLEE, ROUTE, REGISTRATION, PROVIDER, TEST, PACKAGE)
    # get represented before filling with repetitive candidates of the same dimension
    for req_dim in required_dimensions:
        if req_dim in selected_dimensions:
            continue
        for item in sorted_candidates:
            if item in selected or _is_excluded(item, task_spec):
                continue
            if item.relevance_score < 0.2:
                continue
            if item.duplicate_key in selected_duplicate_keys:
                continue
            if item.infer_dimension() == req_dim:
                if _can_fit(item) or (req_dim == "TARGET" and len(selected) == 0 and _trim_to_fit(item)):
                    _accept(
                        item,
                        is_coverage_fill=True,
                        why=[
                            f"Task dimension coverage guarantee: '{req_dim}'",
                            f"Relevance: {item.relevance_score:.2f}",
                        ],
                    )
                    break

    # Pass 1b: Architectural Layer Coverage pass — ensure distinct layers
    # (e.g. ENTRYPOINT, SERVICE, DATA, TEST, GIT) get represented if candidates exist
    for item in sorted_candidates:
        if item in selected or _is_excluded(item, task_spec):
            continue
        if item.relevance_score < 0.2:
            continue
        if item.duplicate_key in selected_duplicate_keys:
            continue
        if item.coverage_layer not in selected_layers and item.coverage_layer != "GENERAL":
            if _can_fit(item):
                _accept(
                    item,
                    is_coverage_fill=True,
                    why=[
                        f"Coverage layer guarantee: '{item.coverage_layer}'",
                        f"Relevance: {item.relevance_score:.2f}",
                    ],
                )

    # Pass 2: Utility-driven knapsack pass for remaining budget
    remaining_candidates = [c for c in sorted_candidates if c not in selected]

    scored_pool: list[tuple[float, CandidateContextItem]] = []
    for item in remaining_candidates:
        u = compute_item_utility(item, selected_layers, selected_duplicate_keys, selected_dimensions)
        scored_pool.append((u, item))

    # Sort remaining pool deterministically by utility desc, item id asc
    scored_pool.sort(
        key=lambda pair: (
            -pair[0],
            -pair[1].relevance_score,
            pair[1].package_distance,
            pair[1].canonical_id or pair[1].file_path,
            pair[1].start_line,
        )
    )

    for utility, item in scored_pool:
        if _is_excluded(item, task_spec):
            continue
        # Strict duplicate elimination by canonical identity
        if item.duplicate_key in selected_duplicate_keys:
            continue
        # Minimum relevance threshold to avoid packing irrelevant items
        if item.relevance_score < 0.35 or utility < 0.25:
            continue
        if _can_fit(item):
            _accept(
                item,
                is_coverage_fill=False,
                why=[
                    f"Knapsack utility score: {utility:.2f}",
                    f"Relevance: {item.relevance_score:.2f}, Evidence: {item.evidence_quality:.2f}, Freshness: {item.freshness}",
                ],
            )

    # Fallback Pass: If tight budget prevented any candidate from fitting, trim the top non-excluded candidate
    if not selected:
        for item in sorted_candidates:
            if _is_excluded(item, task_spec):
                continue
            if _trim_to_fit(item):
                _accept(
                    item,
                    is_coverage_fill=True,
                    why=[
                        "Primary target preserved under tight budget via bounded snippet truncation",
                        f"Relevance: {item.relevance_score:.2f}",
                    ],
                )
                break

    # Final deterministic ordering for presentation:
    # Coverage layers first (ENTRYPOINT -> HANDLER -> SERVICE -> DATA -> TEST -> GIT -> ARCHITECTURE -> GENERAL),
    # then relevance descending, file path, and line number
    _LAYER_ORDER = {
        "ENTRYPOINT": 0,
        "HANDLER": 1,
        "SERVICE": 2,
        "DATA": 3,
        "TEST": 4,
        "GIT": 5,
        "ARCHITECTURE": 6,
        "GENERAL": 7,
    }

    selected.sort(
        key=lambda x: (
            _LAYER_ORDER.get(x.coverage_layer, 9),
            -x.relevance_score,
            x.file_path,
            x.start_line,
        )
    )

    token_reduction = (
        1.0 - (selected_tokens / max(candidate_tokens_total, 1))
        if candidate_tokens_total > 0
        else 0.0
    )
    cand_reduction = (
        1.0 - (len(selected) / max(candidate_count_total, 1))
        if candidate_count_total > 0
        else 0.0
    )
    utilization = min(1.0, selected_tokens / max(token_budget, 1))

    # Coverage score over available required dimensions
    available_dims = {c.infer_dimension() for c in candidates if not _is_excluded(c, task_spec)}
    effective_req_dims = [d for d in required_dimensions if d in available_dims] or list(required_dimensions)
    covered_dims = tuple(d for d in required_dimensions if d in selected_dimensions)
    missing_dims = tuple(d for d in required_dimensions if d not in selected_dimensions)
    if effective_req_dims:
        cov_score = sum(1 for d in effective_req_dims if d in selected_dimensions) / len(effective_req_dims)
    else:
        cov_score = 1.0 if selected else 0.0

    # Redundancy ratio in selected items (should be 0.0 due to canonical deduplication)
    seen_sel_keys: set[str] = set()
    dup_sel = 0
    for s in selected:
        if s.duplicate_key in seen_sel_keys:
            dup_sel += 1
        else:
            seen_sel_keys.add(s.duplicate_key)
    redundancy_ratio = dup_sel / max(len(selected), 1)

    # Evidence density: verified claims (selected symbols + verified relationships) per 100 selected tokens
    total_claims = len(selected) + max(0, verified_claims_count)
    evidence_density = (total_claims / max(selected_tokens / 100.0, 1.0)) if selected_tokens > 0 else 0.0

    rejections_list: list[dict[str, object]] = []
    selected_ids = {s.item_id for s in selected}
    budget_rejected_count = 0
    for item in candidates:
        if item.item_id not in selected_ids:
            if _is_excluded(item, task_spec):
                reason = "Hard exclusion constraint"
            elif item.duplicate_key in selected_duplicate_keys:
                reason = f"Duplicate of selected symbol/chunk ({item.duplicate_key})"
            elif item.graph_distance > max_depth:
                reason = f"Graph depth limit reached ({max_depth} hops)"
                budget_rejected_count += 1
            elif item.package_distance != 99 and item.package_distance > max_package_depth:
                reason = f"Package depth limit reached ({max_package_depth} hops)"
                budget_rejected_count += 1
            elif selected_symbols_count >= max_symbols:
                reason = f"Symbol budget limit reached ({max_symbols} symbols)"
                budget_rejected_count += 1
            elif item.file_path not in selected_files and len(selected_files) >= max_files:
                reason = f"File budget limit reached ({max_files} files)"
                budget_rejected_count += 1
            elif selected_lines + item.line_count > max_lines:
                reason = f"Line budget limit reached ({max_lines} lines)"
                budget_rejected_count += 1
            elif item.estimated_tokens + selected_tokens > token_budget:
                reason = f"Token budget limit reached ({token_budget} tokens)"
                budget_rejected_count += 1
            elif item.freshness == "STALE":
                reason = "Stale source hash on disk"
            else:
                reason = f"Lower utility/relevance ({item.relevance_score:.2f}) compared to selected candidates"
            rejections_list.append(
                {
                    "item_id": item.item_id,
                    "file": item.file_path,
                    "start_line": item.start_line,
                    "symbol": item.canonical_id or item.data.get("symbol"),
                    "reason": reason,
                    "relevance": item.relevance_score,
                }
            )

    is_truncated = bool(was_clamped or snippet_trimmed or budget_rejected_count > 0)

    budget = ContextBudget(
        candidate_tokens=candidate_tokens_total,
        selected_tokens=selected_tokens,
        reduction_ratio=round(token_reduction, 4),
        budget_limit=token_budget,
        rejections=tuple(rejections_list[:50]),
        candidate_count=candidate_count_total,
        selected_count=len(selected),
        candidate_reduction_ratio=round(cand_reduction, 4),
        selected_reduction_ratio=round(token_reduction, 4),
        budget_utilization=round(utilization, 4),
        coverage_score=round(cov_score, 4),
        redundancy_ratio=round(redundancy_ratio, 4),
        evidence_density=round(evidence_density, 4),
        direct_file_reads=len(selected_files),
        direct_file_lines=selected_lines,
        selected_files=len(selected_files),
        selected_lines=selected_lines,
        truncated=is_truncated,
        tool_calls=tool_calls,
        max_symbols=max_symbols,
        max_relationships=max_relationships,
        max_files=max_files,
        max_lines=max_lines,
        max_depth=max_depth,
        max_package_depth=max_package_depth,
        covered_dimensions=covered_dims,
        missing_dimensions=missing_dims,
    )

    return selected, budget
