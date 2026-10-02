"""Canonical TaskSpec, Ambiguity, and Task-Understanding Contract.

The user's AI model understands natural language and creates a structured TaskSpec.
CodeGraph MCP deterministically normalizes, validates, and grounds the TaskSpec against
actual repository facts, symbols, routes, and files with zero LLM API dependency.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

TASK_SPEC_SCHEMA_VERSION = "1.0"


class TaskIntent(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    DEBUG = "DEBUG"
    CHANGE = "CHANGE"
    REFACTOR = "REFACTOR"
    TRACE = "TRACE"
    IMPACT = "IMPACT"
    REVIEW = "REVIEW"
    TEST = "TEST"
    ARCHITECTURE = "ARCHITECTURE"
    EXPLAIN = "EXPLAIN"


_INTENT_PRIORITY_ORDER: list[tuple[str, TaskIntent]] = [
    ("blast_radius", TaskIntent.IMPACT),
    ("impact", TaskIntent.IMPACT),
    ("trace", TaskIntent.TRACE),
    ("callgraph", TaskIntent.TRACE),
    ("architecture", TaskIntent.ARCHITECTURE),
    ("overview", TaskIntent.ARCHITECTURE),
    ("refactor", TaskIntent.REFACTOR),
    ("restructure", TaskIntent.REFACTOR),
    ("review", TaskIntent.REVIEW),
    ("diff", TaskIntent.REVIEW),
    ("debug", TaskIntent.DEBUG),
    ("troubleshoot", TaskIntent.DEBUG),
    ("investigate", TaskIntent.DEBUG),
    ("test", TaskIntent.TEST),
    ("tests", TaskIntent.TEST),
    ("change", TaskIntent.CHANGE),
    ("modify", TaskIntent.CHANGE),
    ("edit", TaskIntent.CHANGE),
    ("fix", TaskIntent.CHANGE),
    ("patch", TaskIntent.CHANGE),
    ("understand", TaskIntent.UNDERSTAND),
    ("explain", TaskIntent.EXPLAIN),
]

_INTENT_SYNONYMS: dict[str, TaskIntent] = dict(_INTENT_PRIORITY_ORDER)


class AmbiguityStatus(StrEnum):
    CLEAR = "CLEAR"
    ASSUMED = "ASSUMED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class AmbiguityCandidate:
    canonical_id: str
    name: str
    path: str
    kind: str
    confidence: str = "HIGH"  # HIGH | MEDIUM | LOW
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TaskAmbiguity:
    status: AmbiguityStatus
    target: str
    candidates: tuple[AmbiguityCandidate, ...] = ()
    assumption: str | None = None
    conflict_detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "target": self.target,
            "candidates": [c.as_dict() for c in self.candidates],
            "assumption": self.assumption,
            "conflict_detail": self.conflict_detail,
        }


@dataclass(frozen=True)
class TaskSpec:
    schema_version: str = TASK_SPEC_SCHEMA_VERSION
    raw_prompt: str | None = None

    intent: str = TaskIntent.UNDERSTAND.value
    goal: str = ""

    targets: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()

    operations: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()

    scope_paths: tuple[str, ...] = ()
    scope_modules: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()

    time_scope: str | None = None

    priority_targets: tuple[str, ...] = ()

    ambiguities: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    confidence: str = "HIGH"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def fingerprint(self) -> str:
        """Compute deterministic SHA-256 fingerprint for this TaskSpec."""
        canonical = json.dumps(
            {
                "intent": self.intent,
                "goal": self.goal,
                "targets": sorted(self.targets),
                "entities": sorted(self.entities),
                "operations": sorted(self.operations),
                "constraints": sorted(self.constraints),
                "exclusions": sorted(self.exclusions),
                "scope_paths": sorted(self.scope_paths),
                "scope_modules": sorted(self.scope_modules),
                "frameworks": sorted(self.frameworks),
                "time_scope": self.time_scope or "",
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonicalize_intent(raw_intent: str | None) -> TaskIntent:
    """Deterministically map raw or case-insensitive intent strings to canonical TaskIntent."""
    if not raw_intent:
        return TaskIntent.UNDERSTAND
    cleaned = raw_intent.strip().lower().replace("-", "_")
    return _INTENT_SYNONYMS.get(cleaned, TaskIntent.UNDERSTAND)


class TargetExpressionType(StrEnum):
    EXPLICIT_SYMBOL_TARGET = "EXPLICIT_SYMBOL_TARGET"
    CONCEPT_TARGET = "CONCEPT_TARGET"
    NATURAL_LANGUAGE_TERM = "NATURAL_LANGUAGE_TERM"


_COMMON_NL_WORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "check", "verify", "trace",
    "show", "what", "where", "how", "when", "does", "after", "before", "code", "file",
    "route", "routes", "flow", "work", "works", "working", "database", "method", "class",
    "function", "explain", "understand", "modify", "refactor", "debug", "impact", "review",
    "find", "all", "case", "cases", "covering", "into", "over", "about", "such",
    "input", "inputs", "output", "outputs", "final", "results", "result", "user", "users",
    "data", "system", "systems", "handle", "handling", "start", "starting", "run", "running",
    "call", "calling", "test", "tests", "view", "views", "item", "items", "order", "orders",
    "list", "make", "need", "needs", "pass", "fail", "true", "false", "value", "values",
    "key", "keys", "main", "step", "steps", "path", "paths", "helper", "helpers",
    "service", "services", "component", "components", "feature", "features", "action", "actions",
    "details", "detail", "overview", "summary", "create", "update", "delete",
})


def classify_target_expression(expr: str) -> TargetExpressionType:
    """Classify a target expression into symbol, concept, or natural language term."""
    clean = expr.strip()
    if not clean:
        return TargetExpressionType.NATURAL_LANGUAGE_TERM

    # 1. Explicit syntax markers
    if "::" in clean:
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET
    if "." in clean:
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET
    if clean.startswith("/") or re.match(r"^(?:GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+/", clean, re.IGNORECASE):
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET
    if "/" in clean and any(clean.endswith(ext) for ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html")):
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET

    # 2. Multi-word phrases
    if " " in clean or "\t" in clean:
        words = [w.lower() for w in clean.split()]
        if all(w in _COMMON_NL_WORDS for w in words):
            return TargetExpressionType.NATURAL_LANGUAGE_TERM
        return TargetExpressionType.CONCEPT_TARGET

    # 3. Code naming conventions
    if "_" in clean:
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET

    # CamelCase (lowercase followed by uppercase, e.g. handleRequest)
    if re.search(r"[a-z][A-Z]", clean):
        return TargetExpressionType.EXPLICIT_SYMBOL_TARGET

    # PascalCase (starts uppercase, contains lowercase, length >= 3, e.g. AuthService, FakePayService)
    if clean[0].isupper() and any(c.islower() for c in clean[1:]) and len(clean) >= 3:
        if clean.lower() not in _COMMON_NL_WORDS:
            return TargetExpressionType.EXPLICIT_SYMBOL_TARGET
        return TargetExpressionType.NATURAL_LANGUAGE_TERM

    # 4. Check against common natural language words
    if clean.lower() in _COMMON_NL_WORDS:
        return TargetExpressionType.NATURAL_LANGUAGE_TERM

    # 5. Plain single word not in stopwords (e.g. authenticate, login)
    # Returns CONCEPT_TARGET: can match symbols in DB if present, but does not trigger UNKNOWN if absent
    return TargetExpressionType.CONCEPT_TARGET


_CODE_TOKEN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,}(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")
_ROUTE_TOKEN_RE = re.compile(r"\b(?:GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+(/[A-Za-z0-9_/{}\-.:*]*)", re.IGNORECASE)
_PATH_TOKEN_RE = re.compile(r"\b([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]+)\b")


def extract_keywords_from_prompt(prompt: str) -> list[str]:
    """Deterministically extract candidate identifiers, endpoints, and terms from a prompt."""
    candidates: list[str] = []

    # 1. Quoted terms
    for quoted in re.findall(r"['\"]([^'\"]+)['\"]", prompt):
        q = quoted.strip()
        if q and q not in candidates:
            if classify_target_expression(q) != TargetExpressionType.NATURAL_LANGUAGE_TERM:
                candidates.append(q)
            elif len(q.split()) > 1:
                candidates.append(q)

    # 2. HTTP endpoints (e.g. POST /login, /api/v1/auth)
    for m in _ROUTE_TOKEN_RE.finditer(prompt):
        route_str = m.group(0).strip()
        if route_str not in candidates:
            candidates.append(route_str)

    # 3. File paths
    for p in _PATH_TOKEN_RE.findall(prompt):
        if p not in candidates and not p.startswith("http"):
            candidates.append(p)

    # 4. Code identifiers (camelCase, snake_case, dotted symbols, potential functions)
    for sym in _CODE_TOKEN_RE.findall(prompt):
        if len(sym) >= 3:
            expr_type = classify_target_expression(sym)
            if expr_type in (TargetExpressionType.EXPLICIT_SYMBOL_TARGET, TargetExpressionType.CONCEPT_TARGET):
                if sym not in candidates:
                    candidates.append(sym)

    return candidates


def decompose_prompt(prompt: str) -> list[str]:
    """Decompose complex, multi-concept prompts into structured conceptual search targets.

    Splits multi-clause instructions, filters command boilerplate and instructions,
    and returns deduplicated technical concepts and identifiers.
    """
    cleaned = re.sub(
        r"\b(?:investigate why|check|verify|trace|find|show me|look for|please|don't modify anything|do not modify|do not change|read only)\b",
        "",
        prompt,
        flags=re.IGNORECASE,
    ).strip()

    tokens = extract_keywords_from_prompt(prompt)
    results: list[str] = list(tokens)

    # Split into clause chunks by commas, semicolons, and clause boundaries
    clauses = re.split(r"[,;\n\.\?!]+|\band\b", cleaned, flags=re.IGNORECASE)
    for clause in clauses:
        c = clause.strip()
        c = re.sub(r"^(?:the|a|an|why|how|what|where|when|all|any)\s+", "", c, flags=re.IGNORECASE).strip()
        if len(c) >= 3 and len(c.split()) <= 4:
            expr_type = classify_target_expression(c)
            if expr_type != TargetExpressionType.NATURAL_LANGUAGE_TERM:
                if not any(c.lower() == r.lower() for r in results):
                    results.append(c)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in results:
        norm = item.strip()
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            deduped.append(norm)

    return deduped


def expand_terms_with_repository(
    terms: list[str] | tuple[str, ...],
    con: sqlite3.Connection | None,
    max_expansions: int = 5,
) -> list[str]:
    """Expand user terminology with actual source-backed symbols and routes from the repository.

    Canonical implementation delegating to `codegraph.query_expansion.expand_query_terms`.
    Only introduces terms confirmed to exist in the repository index.
    """
    if not con or not terms:
        return list(terms)

    from codegraph.query_expansion import expand_query_terms, get_search_queries

    expanded_objs = expand_query_terms(terms, con, max_expansions=max_expansions)
    queries = get_search_queries(expanded_objs)

    expanded: list[str] = list(terms)
    seen: set[str] = {t.lower() for t in terms}
    for q in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            expanded.append(q)

    return expanded



def detect_target_ambiguity(
    target: str,
    con: sqlite3.Connection | None = None,
    exclusions: tuple[str, ...] | None = None,
) -> TaskAmbiguity:
    """Ground a target against the repository symbol table and detect potential ambiguities."""
    if not con or not target.strip():
        return TaskAmbiguity(status=AmbiguityStatus.CLEAR, target=target)

    clean_target = target.strip()

    # Check for direct specification conflict
    if exclusions and clean_target in exclusions:
        return TaskAmbiguity(
            status=AmbiguityStatus.CONFLICT,
            target=clean_target,
            conflict_detail=f"Target '{clean_target}' is in both targets and exclusions.",
        )

    # 1. Exact canonical ID check
    exact_canon = con.execute(
        "SELECT canonical_id, name, path, kind FROM symbols WHERE canonical_id=?",
        (clean_target,),
    ).fetchone()
    if exact_canon:
        cand = AmbiguityCandidate(
            canonical_id=exact_canon["canonical_id"],
            name=exact_canon["name"],
            path=exact_canon["path"],
            kind=exact_canon["kind"],
            confidence="HIGH",
            reason="Exact canonical ID match",
        )
        return TaskAmbiguity(
            status=AmbiguityStatus.CLEAR,
            target=clean_target,
            candidates=(cand,),
        )

    # 2. Framework endpoint check
    if " " in clean_target or clean_target.startswith("/"):
        route_row = con.execute(
            "SELECT endpoint_id, handler_name, file_path FROM framework_routes WHERE route_path=? OR endpoint_id=?",
            (clean_target, clean_target),
        ).fetchone()
        if route_row:
            cand = AmbiguityCandidate(
                canonical_id=route_row["endpoint_id"] or route_row["handler_name"],
                name=route_row["handler_name"],
                path=route_row["file_path"],
                kind="endpoint",
                confidence="HIGH",
                reason="Framework route match",
            )
            return TaskAmbiguity(
                status=AmbiguityStatus.CLEAR,
                target=clean_target,
                candidates=(cand,),
            )

    # 3. Check symbols by name or qualified_name
    rows = con.execute(
        "SELECT canonical_id, name, path, kind FROM symbols WHERE name=? OR qualified_name=?",
        (clean_target, clean_target),
    ).fetchall()

    if len(rows) == 1:
        r = rows[0]
        cand = AmbiguityCandidate(
            canonical_id=r["canonical_id"],
            name=r["name"],
            path=r["path"],
            kind=r["kind"],
            confidence="HIGH",
            reason="Uniquely matched symbol in repository",
        )
        return TaskAmbiguity(
            status=AmbiguityStatus.CLEAR,
            target=clean_target,
            candidates=(cand,),
        )

    if len(rows) > 1:
        candidates = tuple(
            AmbiguityCandidate(
                canonical_id=r["canonical_id"],
                name=r["name"],
                path=r["path"],
                kind=r["kind"],
                confidence="MEDIUM",
                reason=f"Defined in {r['path']}",
            )
            for r in rows
        )
        # Check if one candidate is in a primary/entrypoint module (e.g. routes.py, auth.py vs test_auth.py)
        non_test = [c for c in candidates if "test" not in c.path.lower()]
        kinds = {r["kind"] for r in rows}
        if len(kinds) > 1 and len(non_test) > 1:
            return TaskAmbiguity(
                status=AmbiguityStatus.CONFLICT,
                target=clean_target,
                candidates=candidates,
                conflict_detail=f"Target '{clean_target}' has conflicting symbol kinds ({', '.join(sorted(kinds))}) across multiple non-test definitions.",
            )

        if len(non_test) == 1:
            best = non_test[0]
            return TaskAmbiguity(
                status=AmbiguityStatus.ASSUMED,
                target=clean_target,
                candidates=candidates,
                assumption=f"Target '{clean_target}' assumed to resolve to {best.canonical_id} in {best.path}",
            )
        return TaskAmbiguity(
            status=AmbiguityStatus.AMBIGUOUS,
            target=clean_target,
            candidates=candidates,
        )

    # Check file path match
    file_row = con.execute(
        "SELECT path FROM files WHERE path=? OR path LIKE ?",
        (clean_target, f"%/{clean_target}"),
    ).fetchone()
    if file_row:
        cand = AmbiguityCandidate(
            canonical_id=file_row["path"],
            name=clean_target,
            path=file_row["path"],
            kind="file",
            confidence="HIGH",
            reason="Matched repository file path",
        )
        return TaskAmbiguity(
            status=AmbiguityStatus.CLEAR,
            target=clean_target,
            candidates=(cand,),
        )

    expr_type = classify_target_expression(clean_target)
    if expr_type == TargetExpressionType.EXPLICIT_SYMBOL_TARGET:
        return TaskAmbiguity(
            status=AmbiguityStatus.UNKNOWN,
            target=clean_target,
            candidates=(),
        )
    return TaskAmbiguity(
        status=AmbiguityStatus.CLEAR,
        target=clean_target,
        candidates=(),
    )


def normalize_task_spec(
    task: TaskSpec | dict[str, Any] | str,
    con: sqlite3.Connection | None = None,
) -> tuple[TaskSpec, tuple[TaskAmbiguity, ...]]:
    """Normalize user or agent input into a valid TaskSpec and detected ambiguities."""
    ambiguity_list: list[TaskAmbiguity] = []
    assumptions_list: list[str] = []
    ambiguities_desc: list[str] = []
    unknowns_list: list[str] = []
    conflicts_list: list[str] = []

    if isinstance(task, TaskSpec):
        raw_spec = task
        conflicts_list.extend(raw_spec.conflicts)
    elif isinstance(task, dict):
        raw_intent = task.get("intent")
        canonical_intent = canonicalize_intent(str(raw_intent) if raw_intent else None)
        targets_in = tuple(str(t).strip() for t in task.get("targets", []) if str(t).strip())
        conflicts_in = tuple(str(cf).strip() for cf in task.get("conflicts", []) if str(cf).strip())
        conflicts_list.extend(conflicts_in)
        raw_spec = TaskSpec(
            schema_version=str(task.get("schema_version", TASK_SPEC_SCHEMA_VERSION)),
            raw_prompt=task.get("raw_prompt") or task.get("goal") or task.get("task"),
            intent=canonical_intent.value,
            goal=str(task.get("goal") or task.get("task") or ""),
            targets=targets_in,
            entities=tuple(str(e).strip() for e in task.get("entities", []) if str(e).strip()),
            operations=tuple(str(o).strip().upper() for o in task.get("operations", []) if str(o).strip()),
            constraints=tuple(str(c).strip().upper() for c in task.get("constraints", []) if str(c).strip()),
            exclusions=tuple(str(x).strip() for x in task.get("exclusions", []) if str(x).strip()),
            scope_paths=tuple(str(p).strip() for p in task.get("scope_paths", []) if str(p).strip()),
            scope_modules=tuple(str(m).strip() for m in task.get("scope_modules", []) if str(m).strip()),
            frameworks=tuple(str(f).strip().lower() for f in task.get("frameworks", []) if str(f).strip()),
            time_scope=task.get("time_scope"),
            priority_targets=tuple(str(pt).strip() for pt in task.get("priority_targets", []) if str(pt).strip()),
            ambiguities=tuple(str(a).strip() for a in task.get("ambiguities", []) if str(a).strip()),
            assumptions=tuple(str(asmp).strip() for asmp in task.get("assumptions", []) if str(asmp).strip()),
            unknowns=tuple(str(u).strip() for u in task.get("unknowns", []) if str(u).strip()),
            conflicts=conflicts_in,
            confidence=str(task.get("confidence", "HIGH")),
        )
    else:
        # Raw string input fallback
        prompt_text = str(task).strip()
        filtered_text = re.sub(
            r"\b(?:do\s+not|don't|without)\s+(?:modify|edit|change)\b",
            "",
            prompt_text,
            flags=re.IGNORECASE,
        )
        detected_intent = TaskIntent.UNDERSTAND
        for term, intent_enum in _INTENT_PRIORITY_ORDER:
            if re.search(rf"\b{re.escape(term)}\b", filtered_text, re.IGNORECASE):
                detected_intent = intent_enum
                break

        extracted_targets = decompose_prompt(prompt_text)
        operations: list[str] = []
        if detected_intent == TaskIntent.TRACE:
            operations.append("TRACE")
        if "test" in prompt_text.lower():
            operations.append("FIND_RELATED_TESTS")
        if "recent" in prompt_text.lower() or "yesterday" in prompt_text.lower():
            operations.append("INSPECT_RECENT_CHANGES")

        constraints: list[str] = []
        if "don't modify" in prompt_text.lower() or "read only" in prompt_text.lower() or "do not modify" in prompt_text.lower():
            constraints.append("READ_ONLY")

        time_scope = "RECENT_CHANGES" if ("recent" in prompt_text.lower() or "yesterday" in prompt_text.lower()) else None

        raw_spec = TaskSpec(
            raw_prompt=prompt_text,
            intent=detected_intent.value,
            goal=prompt_text,
            targets=tuple(extracted_targets[:10]),
            operations=tuple(operations),
            constraints=tuple(constraints),
            time_scope=time_scope,
        )

    # Check for direct exclusions conflict
    for exc in raw_spec.exclusions:
        if exc in raw_spec.targets or exc in raw_spec.priority_targets:
            conflicts_list.append(f"Target '{exc}' is listed in both targets and exclusions.")

    # Perform repository target grounding & ambiguity check if DB connection is available
    grounded_targets: list[str] = []
    for tgt in raw_spec.targets:
        amb = detect_target_ambiguity(tgt, con, exclusions=raw_spec.exclusions)
        ambiguity_list.append(amb)
        if amb.status == AmbiguityStatus.CONFLICT:
            if amb.conflict_detail:
                conflicts_list.append(amb.conflict_detail)
            grounded_targets.append(tgt)
        elif amb.status == AmbiguityStatus.AMBIGUOUS:
            ambiguities_desc.append(
                f"Target '{tgt}' is ambiguous across {len(amb.candidates)} candidates: "
                + ", ".join(c.canonical_id for c in amb.candidates[:3])
            )
            grounded_targets.append(tgt)
        elif amb.status == AmbiguityStatus.ASSUMED:
            if amb.assumption:
                assumptions_list.append(amb.assumption)
            grounded_targets.append(tgt)
        elif amb.status == AmbiguityStatus.UNKNOWN:
            unknowns_list.append(f"Target '{tgt}' does not match any indexed repository symbol or route.")
            grounded_targets.append(tgt)
        else:
            grounded_targets.append(tgt)

    combined_assumptions = tuple(dict.fromkeys(list(raw_spec.assumptions) + assumptions_list))
    combined_ambiguities = tuple(dict.fromkeys(list(raw_spec.ambiguities) + ambiguities_desc))
    combined_unknowns = tuple(dict.fromkeys(list(raw_spec.unknowns) + unknowns_list))
    combined_conflicts = tuple(dict.fromkeys(conflicts_list))

    priority_grounded = [
        tgt for tgt, amb in zip(raw_spec.targets, ambiguity_list, strict=False)
        if amb.status != AmbiguityStatus.UNKNOWN
    ]
    effective_priority_targets = (
        raw_spec.priority_targets
        or (tuple(priority_grounded[:3]) if priority_grounded else tuple(grounded_targets[:3]))
    )

    final_spec = TaskSpec(
        schema_version=raw_spec.schema_version,
        raw_prompt=raw_spec.raw_prompt,
        intent=raw_spec.intent,
        goal=raw_spec.goal,
        targets=tuple(dict.fromkeys(grounded_targets)),
        entities=raw_spec.entities,
        operations=raw_spec.operations,
        constraints=raw_spec.constraints,
        exclusions=raw_spec.exclusions,
        scope_paths=raw_spec.scope_paths,
        scope_modules=raw_spec.scope_modules,
        frameworks=raw_spec.frameworks,
        time_scope=raw_spec.time_scope,
        priority_targets=effective_priority_targets,
        ambiguities=combined_ambiguities,
        assumptions=combined_assumptions,
        unknowns=combined_unknowns,
        conflicts=combined_conflicts,
        confidence="LOW" if (combined_ambiguities or combined_conflicts) else ("MEDIUM" if combined_assumptions else "HIGH"),
    )

    return final_spec, tuple(ambiguity_list)
