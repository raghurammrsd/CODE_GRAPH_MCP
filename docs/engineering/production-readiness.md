# CodeGraph MCP Production Readiness & Release Control (v2.1)

## 1. Executive Summary & Baseline State
- **Current Architecture Version**: 2.1 (Task-Aware Retrieval Engine)
- **Frozen Verified Baseline (v2.0)**:
  - 220 unit & property tests passing
  - Ruff: 0 errors
  - Mypy (strict / --ignore-missing-imports): 0 issues across `src/` and `benchmarks/`
  - Benchmark (50 tasks × 10 categories):
    - Unsupported claims: 0.0%
    - FACT correctness: 100.0%
    - UNKNOWN correctness: 98.0%
    - AMBIGUITY correctness: 100.0%
    - STALE handling: Verified
    - Symbol recall: ~52-54%
    - Task coverage: ~77-80%
    - Average context size: ~542 tokens (65% reduction ratio)
    - Average retrieval latency: ~25 ms

## 2. Completed v2.1 Architectural Elements
- **TargetResolver (`src/codegraph/target_resolver.py`)**: First-class target resolution with deterministic priority (canonical ID, exact qualified symbol, route, class.method, filename, unique lexical match, ambiguity detection).
- **RetrievalPolicy (`src/codegraph/retrieval_policy.py`)**: Intent-specific retrieval policies (TRACE, UNDERSTAND, DEBUG, IMPACT, REVIEW, ARCHITECTURE, CHANGE, REFACTOR, TEST, EXPLAIN) with explicit allowed relationship sets and preferred coverage flow.
- **QueryExpansion (`src/codegraph/query_expansion.py`)**: Elimination of bare generic terms (`get`, `post`, `run`, `login`) in favor of qualified expansions (`AdminDashboardView.get`, `AuthService.login`).
- **ConstraintGuard (`src/codegraph/constraints.py`)**: Hierarchical, path-component, and canonical identity hard constraint filtering.
- **Diagnostic Infrastructure (`benchmarks/diagnostics/task_diagnostics.py`)**: Granular per-task false negative (FN) and false positive (FP) causal classification.

## 3. Incomplete / Hardening Phases
1. **Search Subsystem Exact API**: Provide explicit exact symbol, qualified, canonical, and route search methods.
2. **Unified Constraint Propagation**: Replace heuristic string checks with `ConstraintGuard` throughout candidate generation, graph traversal, ranking, budget optimization, and final ContextPacket serialization.
3. **Deterministic Traversal Ordering**: Ensure graph roots and BFS traversals are strictly ordered by grounded priority rather than nondeterministic set iterations.
4. **Epistemic Relationship Preservation**: Maintain distinct semantics for verified `CALLS` vs inferred `POSSIBLE_CALLS`.
5. **Database & CLI Doctor**: Add `codegraph doctor --database` schema and integrity audit.
6. **Package & Wheel Verification**: Validate clean build and installation into a fresh virtual environment.

## 4. Final Release Acceptance Gates
- **Code Quality**: Ruff 0 errors, Mypy 0 errors, 100% test pass rate across all suites.
- **Safety Invariant**: Zero exclusion violations across any channel in final ContextPacket.
- **Trust Integrity**: Unsupported claims <= 1.0%, FACT >= 98%, UNKNOWN >= 95%, AMBIGUITY >= 90%, STALE handling verified.
- **Determinism**: Identical candidate ranking and ContextPacket outputs across repeated runs.
- **Packaging**: Clean distribution build with no cached files or local databases, verified pip install.
