"""Context ranking engine — rigorous, explainable, normalized codebase relevance.

Ranking Hierarchy (without double counting):
  1. EXACT_CANONICAL match > EXACT_QUALIFIED match > EXACT_SYMBOL match > NAME_MATCH > PATH_MATCH / TEXT_MATCH
  2. Verified relationships (CALLS with HIGH confidence) > POSSIBLE_CALLS (LOW confidence)
  3. Graph distance geometric decay
  4. Intent-specific weight policies (EXPLAIN, DEBUG, MODIFY, REVIEW, TEST, IMPACT, ARCHITECTURE)
  5. Freshness weighting (STALE and PARTIALLY_STALE penalties)
  6. Source-type classification (source > config > doc > generated / vendor)
  7. Duplicate context penalties
  8. Stable deterministic tie-breaking: (-score, -evidence_prio, -exact_prio, dist, len(file), file)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RankingReason:
    code: str
    label: str
    contribution: float


@dataclass
class RankedItem:
    file: str
    symbol: str | None
    start_line: int
    end_line: int
    score: float
    reasons: list[RankingReason]
    snippet: str = ""
    token_estimate: int = 0
    canonical_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "symbol": self.symbol,
            "canonical_id": self.canonical_id,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "score": self.score,
            "reasons": [
                {"code": r.code, "label": r.label, "contribution": r.contribution}
                for r in self.reasons
            ],
            "snippet": self.snippet,
            "token_estimate": self.token_estimate,
        }

    def debug_format(self) -> str:
        out = [f"{self.canonical_id or self.symbol or self.file}"]
        out.append(f"score: {self.score:.2f}")
        pos = [r for r in self.reasons if r.contribution > 0]
        neg = [r for r in self.reasons if r.contribution < 0]
        if pos:
            out.append("\npositive:")
            for r in pos:
                out.append(f"+ {r.label:<24} +{r.contribution:.2f}")
        if neg:
            out.append("\nnegative:")
            for r in neg:
                out.append(f"- {r.label:<24} {r.contribution:.2f}")
        return "\n".join(out)


@dataclass(frozen=True)
class IntentWeights:
    target_bonus: float
    caller_bonus: float
    callee_bonus: float
    test_bonus: float
    entry_point_bonus: float
    distance_decay: float
    recent_bonus: float


_INTENT_WEIGHTS = {
    "explain": IntentWeights(0.30, 0.10, 0.20, 0.05, 0.10, 0.70, 0.05),
    "debug": IntentWeights(0.20, 0.20, 0.10, 0.15, 0.20, 0.80, 0.15),
    "modify": IntentWeights(0.40, 0.15, 0.15, 0.20, 0.05, 0.60, 0.10),
    "review": IntentWeights(0.20, 0.10, 0.10, 0.20, 0.05, 0.60, 0.20),
    "test": IntentWeights(0.20, 0.10, 0.05, 0.40, 0.05, 0.50, 0.10),
    "impact": IntentWeights(0.30, 0.30, 0.05, 0.10, 0.10, 0.90, 0.00),
    "architecture": IntentWeights(0.15, 0.05, 0.05, 0.05, 0.30, 0.50, 0.00),
    "default": IntentWeights(0.25, 0.10, 0.10, 0.10, 0.10, 0.70, 0.10),
}

_TEST_PATTERNS = re.compile(
    r"(^|[_/])test[_s]?[_/]|[_/]spec[_/]|test[_s]?\.(py|js|ts|jsx|tsx)$|spec\.(py|js|ts|jsx|tsx)$",
    re.IGNORECASE,
)

_ENTRY_PATTERNS = re.compile(
    r"(^|[_/])(main|app|server|index|wsgi|asgi|manage|run)\.(py|js|ts)$",
    re.IGNORECASE,
)

_VENDOR_PATTERNS = re.compile(
    r"(^|[_/])(node_modules|vendor|\.venv|venv|dist|build|generated)[_/]",
    re.IGNORECASE,
)


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def rank_candidates(
    candidates: list[dict[str, object]],
    query: str,
    intent: str | None = None,
    target_symbols: set[str] | None = None,
    recent_paths: set[str] | None = None,
    relationship_distance: dict[str, int] | None = None,
    max_results: int = 20,
    allowed_relationships: frozenset[str] | None = None,
) -> list[RankedItem]:
    """Deterministically rank candidates returning explainable, normalized scores between 0.0 and 1.0.

    Args:
        candidates: Raw candidate dicts from search and graph traversal.
        query: The task display string used for lexical matching.
        intent: Task intent string (e.g. "TRACE", "DEBUG", "UNDERSTAND").
        target_symbols: Set of target symbol names/IDs boosted during ranking.
        recent_paths: File paths recently modified (git-aware freshness boost).
        relationship_distance: Pre-computed BFS distances from target symbols.
        max_results: Maximum results to return.
        allowed_relationships: If provided, candidates whose relationship type is
            NOT in this set receive a penalty. From RetrievalPolicy.
    """
    weights = _INTENT_WEIGHTS.get(intent or "", _INTENT_WEIGHTS["default"])
    target_symbols = target_symbols or set()
    recent_paths = recent_paths or set()
    relationship_distance = relationship_distance or {}

    # Extract terms: dotted terms and word terms
    dotted_terms = {t.lower() for t in re.findall(r"[A-Za-z_][\w.]*\.[\w.]+", query)}
    word_terms = {t.lower() for t in re.findall(r"[A-Za-z_][\w]*", query) if len(t) > 1}
    for ts in target_symbols:
        word_terms.add(ts.lower().split(".")[-1])
        if "." in ts:
            dotted_terms.add(ts.lower())

    scored_items: list[RankedItem] = []

    for c in candidates:
        file_ = str(c.get("file", ""))
        canonical_id = str(c.get("canonical_id") or "") or None
        symbol = c.get("symbol") or c.get("qualified_name")
        symbol_str = str(symbol) if symbol else None
        start = int(str(c.get("start_line", 1)))
        end = int(str(c.get("end_line", start)))
        snippet = str(c.get("snippet", "") or c.get("content", ""))[:1200]
        confidence = str(c.get("confidence", "HIGH")).upper()
        freshness = str(c.get("freshness", "FRESH")).upper()
        relationship = str(c.get("relationship", ""))
        base_search_score = float(str(c.get("score", 0.0)))

        score = 0.0
        reasons: list[RankingReason] = []

        # 1. Base Symbol Matching (strictly hierarchical to avoid double counting)
        matched_exact = False
        canon_lower = canonical_id.lower() if canonical_id else ""
        sym_lower = symbol_str.lower() if symbol_str else ""
        short_name = sym_lower.split(".")[-1] if sym_lower else ""

        # Exact canonical match
        if canon_lower and any(dt == canon_lower or dt in canon_lower for dt in dotted_terms):
            val = weights.target_bonus + 0.20
            score += val
            reasons.append(RankingReason("EXACT_CANONICAL", "Exact canonical symbol match", round(val, 3)))
            matched_exact = True
        # Exact qualified name match
        elif sym_lower and any(dt == sym_lower or sym_lower.endswith(f".{dt}") for dt in dotted_terms):
            val = weights.target_bonus + 0.15
            score += val
            reasons.append(RankingReason("EXACT_QUALIFIED", "Exact qualified symbol match", round(val, 3)))
            matched_exact = True
        # Exact symbol name match
        elif short_name and short_name in word_terms:
            val = weights.target_bonus + 0.10
            score += val
            reasons.append(RankingReason("EXACT_SYMBOL", "Exact target symbol", round(val, 3)))
            matched_exact = True
        # Name relevance
        elif (short_name and any(wt in short_name for wt in word_terms)) or (
            sym_lower and any(wt in sym_lower for wt in word_terms)
        ):
            val = min(0.25, max(0.12, base_search_score))
            score += val
            reasons.append(RankingReason("NAME_MATCH", "Symbol name relevance", round(val, 3)))
        # Path relevance
        elif any(wt in file_.lower() for wt in word_terms):
            val = min(0.20, max(0.10, base_search_score))
            score += val
            reasons.append(RankingReason("PATH_MATCH", "File path relevance", round(val, 3)))
        elif base_search_score > 0:
            val = min(0.30, base_search_score)
            score += val
            reasons.append(RankingReason("TEXT_MATCH", "Lexical text match", round(val, 3)))

        # 2. Graph Relationship Distance & Direction
        sym_key = canonical_id or symbol_str
        if sym_key and sym_key in relationship_distance:
            dist = relationship_distance[sym_key]
            decay = weights.distance_decay ** dist
            val = 0.20 * decay
            score += val
            reasons.append(RankingReason("GRAPH_DISTANCE", f"Graph distance {dist}", round(val, 3)))
        elif relationship == "CALLS":
            val = weights.callee_bonus
            score += val
            reasons.append(RankingReason("DIRECT_CALLEE", "Direct callee", val))
        elif relationship in ("POSSIBLE_CALLS", "CALLERS"):
            multiplier = 1.0 if confidence in ("HIGH", "MEDIUM") else 0.5
            val = round(weights.caller_bonus * multiplier, 3)
            score += val
            reasons.append(
                RankingReason(
                    "DIRECT_CALLER" if multiplier == 1.0 else "POSSIBLE_CALLER",
                    "Direct caller" if multiplier == 1.0 else "Possible caller",
                    val,
                )
            )
        elif relationship == "HANDLED_BY":
            val = weights.target_bonus + 0.10
            score += val
            reasons.append(RankingReason("ENDPOINT_HANDLER", "Endpoint handler", round(val, 3)))
        elif relationship in ("EXTENDS", "IMPLEMENTS"):
            val = 0.10
            score += val
            reasons.append(RankingReason("INHERITANCE", f"Class {relationship.lower()}", val))

        # 2b. Policy relationship allowlist — penalize relationships not permitted for this intent
        if allowed_relationships and relationship and relationship.upper() not in allowed_relationships:
            penalty = 0.15
            score -= penalty
            reasons.append(RankingReason(
                "RELATIONSHIP_NOT_ALLOWED",
                f"Relationship '{relationship}' not in policy allowlist",
                -penalty,
            ))

        # 3. Evidence Quality
        if confidence == "HIGH":
            score += 0.10
            reasons.append(RankingReason("EVIDENCE_HIGH", "Verified source evidence", 0.10))
        elif confidence == "MEDIUM":
            score += 0.05
            reasons.append(RankingReason("EVIDENCE_MEDIUM", "Inferred relationship", 0.05))

        # 4. Freshness
        if freshness == "STALE":
            score -= 0.30
            reasons.append(RankingReason("STALE_SOURCE", "Stale evidence", -0.30))
        elif freshness == "PARTIALLY_STALE":
            score -= 0.10
            reasons.append(RankingReason("PARTIALLY_STALE", "Partially stale evidence", -0.10))

        # 5. Test Relationship
        is_test = bool(_TEST_PATTERNS.search(file_))
        if is_test and (relationship.startswith("TEST") or matched_exact):
            val = weights.test_bonus
            score += val
            reasons.append(RankingReason("TEST_RELATION", "Related test file", val))

        # 6. Entry Point & Framework Route
        is_entry = bool(_ENTRY_PATTERNS.search(file_))
        if is_entry:
            val = weights.entry_point_bonus
            score += val
            reasons.append(RankingReason("ENTRY_POINT", "Entry point", val))

        # 7. Vendor / Generated Penalty
        if _VENDOR_PATTERNS.search(file_):
            score -= 0.30
            reasons.append(RankingReason("VENDOR_PENALTY", "Vendor/generated code penalty", -0.30))

        # 8. Recency
        if file_ in recent_paths:
            val = weights.recent_bonus
            score += val
            reasons.append(RankingReason("RECENT_CHANGE", "Recently modified", val))

        score = max(0.0, min(1.0, score))

        scored_items.append(
            RankedItem(
                file=file_,
                symbol=symbol_str,
                canonical_id=canonical_id,
                start_line=start,
                end_line=end,
                score=round(score, 3),
                reasons=reasons,
                snippet=snippet,
                token_estimate=_token_estimate(snippet),
            )
        )

    # 9. Duplicate Context Penalty (deterministic pre-sort ensures stable penalty application)
    def pre_sort_key(item: RankedItem) -> tuple[float, str, str]:
        return (-item.score, item.file, str(item.canonical_id or item.symbol or ""))

    scored_items.sort(key=pre_sort_key)
    seen_symbols: set[str] = set()
    seen_files: set[str] = set()

    for item in scored_items:
        if item.score <= 0:
            continue
        penalty = 0.0
        sym_key = item.canonical_id or item.symbol
        if sym_key:
            if sym_key in seen_symbols:
                penalty += 0.20
            seen_symbols.add(sym_key)
        if item.file in seen_files:
            penalty += 0.10
        seen_files.add(item.file)

        if penalty > 0:
            item.score = max(0.0, round(item.score - penalty, 3))
            item.reasons.append(
                RankingReason("DUPLICATE_PENALTY", "Duplicate context penalty", -penalty)
            )

    # 10. Stable Tie-Breaking Sort
    def sort_key(item: RankedItem) -> tuple[float, int, int, int, int, str]:
        evidence_prio = 0
        if any(r.code == "EVIDENCE_HIGH" for r in item.reasons):
            evidence_prio = 2
        elif any(r.code == "EVIDENCE_MEDIUM" for r in item.reasons):
            evidence_prio = 1

        exact_prio = 0
        if any(r.code == "EXACT_CANONICAL" for r in item.reasons):
            exact_prio = 3
        elif any(r.code == "EXACT_QUALIFIED" for r in item.reasons):
            exact_prio = 2
        elif any(r.code == "EXACT_SYMBOL" for r in item.reasons):
            exact_prio = 1

        dist = 999
        for r in item.reasons:
            if r.code == "GRAPH_DISTANCE":
                try:
                    dist = int(r.label.split()[-1])
                except ValueError:
                    pass

        return (-item.score, -evidence_prio, -exact_prio, dist, len(item.file), item.file)

    scored_items.sort(key=sort_key)
    return scored_items[:max_results]


rank = rank_candidates
