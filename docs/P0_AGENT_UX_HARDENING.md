# CodeGraph MCP — P0 Agent UX Hardening Report

## Executive Summary

The **P0 Agent UX Hardening** release reinforces CodeGraph MCP for autonomous AI-agent consumption without altering the core deterministic repository interrogation architecture.

The core principle remains intact:
> **The AI understands the developer. CodeGraph interrogates the repository.**  
> **The claim comes from the AI; the proof comes from CodeGraph.**

This release eliminates raw Python tracebacks on expected operational failures, enforces consistent CLI repository path defaults (`.` and `-r / --repo`), standardizes a centralized error contract with deterministic next-action recovery guidance, and verifies strict MCP stdio hygiene.

---

## 1. Implemented Changes

1. **Centralized Error System (`src/codegraph/errors.py`)**:
   - Introduced `ErrorCode` enum defining stable, machine-readable error codes.
   - Built `CodeGraphError` base class with `.to_dict()` and `.to_response()` serialization.
   - Implemented specialized exception classes (`SecurityError`, `NotIndexedError`, `IndexStaleError`, `SymbolNotFoundError`, `SymbolAmbiguousError`, `InvalidPathError`, `InvalidArgumentError`, `InvalidDepthError`, etc.) providing structured recovery instructions (`next_action`).

2. **CLI Path Consistency (`src/codegraph/cli.py`)**:
   - Updated all repository commands (`index`, `init`, `status`, `doctor`, `architecture`, `routes`, `privacy`, `serve`, `benchmark`) to accept an optional positional `[PATH]` defaulting to `.` (current working directory), as well as `-r / --repository / --repo`.
   - Guaranteed that `codegraph status` and `codegraph status .` resolve to the exact same repository.
   - Added explicit symbol commands: `codegraph get-symbol SYMBOL` and `codegraph resolve-symbol QUERY`.
   - Wrapped commands so unindexed repositories, non-existent directories, and path traversal attempts emit structured JSON errors without raw Python tracebacks.

3. **Core Interrogation Guards (`src/codegraph/interrogation.py`)**:
   - Added `check_index_available(con, repository)` guard across all 13 core MCP tools, immediately returning an `INDEX_NOT_FOUND` structured error envelope if the repository is unindexed.
   - Structured ambiguous symbol resolutions with both `matches` and `candidates` arrays containing `{ canonical_id, symbol, name, file, kind, line, start_line, end_line }` sorted deterministically without guessing developer intent.
   - Added structured error objects with `next_action` guidance across all failure modes (e.g. `SYMBOL_NOT_FOUND`, `EMPTY_SYMBOL_NAME`, `PATH_OUTSIDE_REPOSITORY`, `INVALID_DEPTH`, `INVALID_ARGUMENT`).

4. **Schema Migration Self-Healing (`src/codegraph/indexing/indexer.py`)**:
   - Bumped `SCHEMA_VERSION = 6` and added automatic migration for the `category` column in `files` table to preserve database compatibility across versions.

---

## 2. CLI Behavior

### Path Consistency
Commands operating on a repository accept:
```bash
codegraph <command> [PATH] [--repo PATH]
```
If no argument is passed, `PATH = .` is assumed.

| Command | Positional Default | Explicit Option | Description |
| :--- | :--- | :--- | :--- |
| `codegraph status [PATH]` | `.` | `-r`, `--repo` | Repository indexing status and freshness |
| `codegraph index [PATH]` | `.` | `-r`, `--repo` | Indexes supported source files |
| `codegraph init [PATH]` | `.` | `-r`, `--repo` | Initializes repository index and schema |
| `codegraph doctor [PATH]` | `.` | `-r`, `--repo` | Integrity, readiness, and resource health |
| `codegraph architecture [PATH]` | `.` | `-r`, `--repo` | High-level module and dependency topology |
| `codegraph routes [PATH]` | `.` | `-r`, `--repo` | Discovered framework route endpoints |
| `codegraph privacy [PATH]` | `.` | `-r`, `--repo` | Boundary check for sensitive leaks |
| `codegraph serve [PATH]` | `.` | `-r`, `--repo` | Runs stdio FastMCP server |

### Explicit Symbol Commands
Commands operating on symbols or queries retain explicit argument semantics:
```bash
codegraph trace <symbol> [--depth 2] [-r <repo>]
codegraph get-symbol <symbol> [-r <repo>]
codegraph resolve-symbol <query> [-r <repo>]
codegraph search <query> [-r <repo>]
codegraph symbols <file_path> [-r <repo>]
codegraph context <task> [-r <repo>]
```

---

## 3. Structured Error Contract

Every expected operational failure produces a canonical JSON response without stack traces:

```json
{
  "status": "error",
  "error": {
    "code": "INDEX_NOT_FOUND",
    "message": "No CodeGraph index exists for this repository.",
    "next_action": {
      "command": "codegraph init",
      "reason": "Initialize the repository before querying it."
    }
  }
}
```

### Stable Error Codes

| Error Code | Trigger Condition | Deterministic Agent Recovery |
| :--- | :--- | :--- |
| `INDEX_NOT_FOUND` | Repository has not been indexed | Execute `codegraph init` |
| `INDEX_STALE` | Repository modified after index generation | Execute `codegraph index` |
| `REPOSITORY_NOT_INITIALIZED` | Missing database or configuration | Execute `codegraph init` |
| `INVALID_PATH` | Non-existent or invalid directory path | Check directory existence |
| `PATH_OUTSIDE_REPOSITORY` | Path traversal attempt (e.g. `../../etc/passwd`) | Confine path to repository |
| `SYMBOL_NOT_FOUND` | Requested symbol does not exist in AST index | Search with broader term |
| `SYMBOL_AMBIGUOUS` | Multiple symbols match short name | Select candidate canonical ID |
| `INVALID_ARGUMENT` | Missing or empty required parameter | Check command arguments |
| `INVALID_DEPTH` | Traversal depth outside 1..5 range | Clamp to 1..5 range |
| `SENSITIVE_FILE_ACCESS_DENIED` | Attempted read of sensitive file (`.env`) | Review privacy boundaries |
| `PARSE_FAILURE` | Source file contains syntax errors | Fix syntax and re-index |
| `UNSUPPORTED_LANGUAGE` | Language not supported by AST parser | Inspect `codegraph doctor` |
| `INTERNAL_ERROR` | Unhandled operational exception | Check logs on stderr |

---

## 4. Unified MCP Response Envelope

All 13 core MCP interrogation tools adhere to a structured, deterministic envelope:

```json
{
  "status": "ok",
  "symbol": {
    "canonical_id": "src/auth/service.py::AuthService.authenticate",
    "name": "authenticate",
    "kind": "METHOD",
    "file": "src/auth/service.py",
    "start_line": 42,
    "end_line": 68
  },
  "evidence": [
    {
      "file": "src/auth/service.py",
      "start_line": 42,
      "end_line": 68,
      "type": "definition",
      "canonical_id": "src/auth/service.py::AuthService.authenticate"
    }
  ],
  "index": {
    "generation": 2,
    "created_at": "2026-10-01T12:00:00Z",
    "freshness": "FRESH"
  },
  "repository": {
    "commit": "a1b2c3d"
  }
}
```

### Ambiguous Candidate Presentation
When a symbol name matches multiple candidates:
```json
{
  "status": "ambiguous",
  "query": "duplicate_action",
  "error": {
    "code": "SYMBOL_AMBIGUOUS",
    "message": "Multiple symbols match 'duplicate_action'. Provide a qualified name or canonical ID.",
    "next_action": {
      "command": "codegraph resolve <canonical_id>",
      "reason": "Select an explicit canonical ID from candidates."
    }
  },
  "candidates": [
    {
      "canonical_id": "src/admin/views.py::duplicate_action",
      "symbol": "duplicate_action",
      "file": "src/admin/views.py",
      "line": 2
    },
    {
      "canonical_id": "src/auth/views.py::duplicate_action",
      "symbol": "duplicate_action",
      "file": "src/auth/views.py",
      "line": 8
    }
  ]
}
```
CodeGraph never guesses which candidate the developer intended.

---

## 5. Freshness Behavior

Freshness tracking distinguishes four explicit lifecycle states:
- `FRESH`: AST index is fully synchronized with current file digests and commit SHA.
- `PARTIALLY_STALE`: Localized source modifications exist; safe read queries report stale evidence without blocking.
- `STALE`: Significant repository changes have occurred; re-indexing is recommended.
- `UNKNOWN`: Repository is unindexed or empty.

---

## 6. Security Validation

- **Path Traversal Protection**: Any path outside the repository boundary (e.g. `../../etc/passwd`, `/etc/shadow`) is intercepted by `safe_path` and returned as `PATH_OUTSIDE_REPOSITORY` with 0 traceback leakage.
- **Sensitive File Protection**: Access to sensitive files (`.env`, secrets, private keys) is rejected with `SENSITIVE_FILE_ACCESS_DENIED`.
- **Zero Remote Execution**: No network calls, telemetry, or remote code execution.

---

## 7. Verification & Quality Gates

### Test Suite
- **Existing Tests**: 330 passed.
- **New Tests Added**: 14 tests in `tests/test_agent_ux_hardening.py`.
- **Total Passing Tests**: 344 passed, 0 failures.

### Linters & Type Checking
- **Ruff**: 0 errors.
- **Mypy `src/` (strict)**: 0 issues across 55 source files.
- **Mypy `tests/`**: 0 issues across test suites.
- **Mypy `benchmarks/`**: 0 issues across 37 benchmark source files.

### Benchmark Regression Evaluation (50 Tasks × 10 Categories)
- **Symbol Recall**: 58.7% (Baseline: ~52%)
- **Relationship Recall**: 46.0%
- **Task Coverage**: 79.5% (Baseline: ~77–79%)
- **FACT Correctness**: 100.0% (Target: $\ge 98.0\%$)
- **Unsupported Claims**: 0.0% (Target: $\le 1.0\%$)
- **UNKNOWN Correctness**: 98.0% (Target: $\ge 95.0\%$)
- **AMBIGUITY Correctness**: 100.0% (Target: $\ge 90.0\%$)
- **STALE Handling**: Verified
- **Regression Gate**: **PASSED**

---

## 8. Known Limitations & Deferred P1 Work

- **Output Formatting**: YAML and Markdown output flags (`--format yaml`, `--format markdown`) are deferred to P1 to avoid unmeasured token bloat.
- **Normalized Identifier Matching**: Identifier case normalization (`health_check` $\to$ `HealthCheck`) is deferred to P1 to prevent premature heuristic complexity.
- **Extended Route Frameworks**: Rails, Django REST Framework viewsets, and Spring controllers will be expanded in future releases.
