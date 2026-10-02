"""Global Token Budget Optimizer, Redundancy Control, and Coverage Engine.

Maximizes evidence quality, relationship coverage, freshness, and diversity of useful
context under a strict token budget constraint while eliminating redundant chunks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraph.task import TaskSpec


@dataclass(frozen=True)
class ContextBudget:
    candidate_tokens: int
    selected_tokens: int
    reduction_ratio: float
    budget_limit: int
    rejections: tuple[dict[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_tokens": self.candidate_tokens,
            "selected_tokens": self.selected_tokens,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "budget_limit": self.budget_limit,
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
    epistemic_status: str = "FACT"  # FACT | ASSUMPTION | INFERENCE | UNKNOWN | CONFLICT
    coverage_value: float = 0.5
    data: dict[str, Any] = field(default_factory=dict)
    why_selected: list[str] = field(default_factory=list)

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
        """Deterministic grouping key for redundancy detection."""
        if self.canonical_id:
            return f"sym:{self.canonical_id}"
        return f"loc:{self.file_path}:{self.start_line}"

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


def compute_item_utility(
    item: CandidateContextItem,
    selected_layers: set[str],
    selected_duplicate_keys: set[str],
) -> float:
    """Calculate deterministic utility score for a candidate context item."""
    fresh_factor = _freshness_multiplier(item.freshness)
    conf_penalty = _confidence_penalty(item.confidence)
    epistemic_factor = _epistemic_multiplier(item.epistemic_status)

    # Coverage reward: boost item if it introduces a required layer not yet represented
    coverage_factor = 1.3 if item.coverage_layer not in selected_layers else 1.0

    # Redundancy penalty: heavily discount items sharing duplicate keys with already selected items
    redundancy_penalty = 0.5 if item.duplicate_key in selected_duplicate_keys else 0.0

    utility = (
        (item.relevance_score * 0.40)
        + (item.evidence_quality * 0.20)
        + (item.relationship_value * 0.15)
        + (fresh_factor * 0.15)
        + (epistemic_factor * 0.10)
    ) * coverage_factor

    final_score = max(0.01, utility - redundancy_penalty - conf_penalty)
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


def optimize_context_budget(
    candidates: list[CandidateContextItem],
    token_budget: int,
    task_spec: TaskSpec | None = None,
) -> tuple[list[CandidateContextItem], ContextBudget]:
    """Deterministically select the highest-utility, coverage-preserving subset of candidates."""
    if not candidates or token_budget <= 0:
        return [], ContextBudget(
            candidate_tokens=0,
            selected_tokens=0,
            reduction_ratio=0.0,
            budget_limit=token_budget,
        )

    candidate_tokens_total = sum(c.estimated_tokens for c in candidates)

    # Initial deterministic sort of candidates:
    # 1. Relevance score descending
    # 2. Evidence quality descending
    # 3. Canonical ID or file path ascending (stable tie-breaker)
    # 4. Start line ascending
    sorted_candidates = sorted(
        candidates,
        key=lambda x: (
            -x.relevance_score,
            -x.evidence_quality,
            x.canonical_id or x.file_path,
            x.start_line,
        ),
    )

    selected: list[CandidateContextItem] = []
    selected_layers: set[str] = set()
    selected_duplicate_keys: set[str] = set()
    selected_tokens = 0

    # Pass 1: Coverage pass — ensure distinct layers (e.g. ENTRYPOINT, SERVICE, TEST, GIT)
    # get represented if candidates exist and fit within budget
    for item in sorted_candidates:
        if _is_excluded(item, task_spec):
            continue
        if item.relevance_score < 0.2:
            continue
        if item.coverage_layer not in selected_layers and item.coverage_layer != "GENERAL":
            if selected_tokens + item.estimated_tokens <= token_budget:
                item.why_selected = [
                    f"Coverage layer guarantee: '{item.coverage_layer}'",
                    f"Relevance: {item.relevance_score:.2f}",
                ]
                selected.append(item)
                selected_tokens += item.estimated_tokens
                selected_layers.add(item.coverage_layer)
                selected_duplicate_keys.add(item.duplicate_key)

    # Pass 2: Utility-driven knapsack pass for remaining budget
    remaining_candidates = [c for c in sorted_candidates if c not in selected]

    # Re-score remaining candidates with dynamic utility taking into account chosen layers/duplicates
    scored_pool: list[tuple[float, CandidateContextItem]] = []
    for item in remaining_candidates:
        u = compute_item_utility(item, selected_layers, selected_duplicate_keys)
        scored_pool.append((u, item))

    # Sort remaining pool deterministically by utility desc, item id asc
    scored_pool.sort(
        key=lambda pair: (
            -pair[0],
            -pair[1].relevance_score,
            pair[1].canonical_id or pair[1].file_path,
            pair[1].start_line,
        )
    )

    for utility, item in scored_pool:
        if _is_excluded(item, task_spec):
            continue
        # Check redundancy: if item is exact duplicate of something already selected, skip
        if item.duplicate_key in selected_duplicate_keys and utility < 0.2:
            continue
        # Minimum relevance threshold to avoid packing irrelevant items
        if item.relevance_score < 0.35 or utility < 0.25:
            continue
        if selected_tokens + item.estimated_tokens <= token_budget:
            item.why_selected = [
                f"Knapsack utility score: {utility:.2f}",
                f"Relevance: {item.relevance_score:.2f}, Evidence: {item.evidence_quality:.2f}, Freshness: {item.freshness}",
            ]
            selected.append(item)
            selected_tokens += item.estimated_tokens
            selected_layers.add(item.coverage_layer)
            selected_duplicate_keys.add(item.duplicate_key)

    # Final deterministic ordering for presentation:
    # Coverage layers first (ENTRYPOINT -> HANDLER -> SERVICE -> DATA -> TEST -> GIT -> ARCHITECTURE -> GENERAL),
    # then file path and line number
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

    reduction = (
        1.0 - (selected_tokens / max(candidate_tokens_total, 1))
        if candidate_tokens_total > 0
        else 0.0
    )

    rejections_list: list[dict[str, object]] = []
    selected_ids = {s.item_id for s in selected}
    for item in candidates:
        if item.item_id not in selected_ids:
            if item.duplicate_key in selected_duplicate_keys:
                reason = f"Duplicate of selected symbol/chunk in {item.file_path}"
            elif item.estimated_tokens + selected_tokens > token_budget:
                reason = f"Token budget limit reached ({token_budget} tokens)"
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

    budget = ContextBudget(
        candidate_tokens=candidate_tokens_total,
        selected_tokens=selected_tokens,
        reduction_ratio=reduction,
        budget_limit=token_budget,
        rejections=tuple(rejections_list[:50]),
    )

    return selected, budget
