# CodeGraph MCP

> **The AI understands the developer. CodeGraph interrogates the repository.**  
> **The claim comes from the AI; the proof comes from CodeGraph.**

CodeGraph MCP is an open-source, deterministic codebase intelligence server built on the Model Context Protocol (MCP). It is not a conversational AI, a natural-language interpreter, a vector database, or an autonomous agent. 

Antigravity and your AI agents handle natural-language reasoning, intent interpretation, and answer synthesis. CodeGraph interrogates the local repository to deliver deterministic, evidence-backed AST facts, call and import graphs, verified line citations, architecture structure, and Git impact.

---

## Architectural Separation of Responsibilities

```text
USER
  │
  │ natural-language request ("how does authetication wrks in my app?")
  ▼
ANTIGRAVITY / AI
  │
  ├── understands intent and context
  ├── corrects spelling and informal language
  ├── identifies candidate code targets
  ├── resolves conceptual ambiguity
  ├── decomposes complex queries into precise tool invocations
  └── decides which MCP tools to call
  │
  │ precise, deterministic MCP request (e.g., list_routes(), resolve_symbol("authenticate"))
  ▼
CODEGRAPH MCP
  │
  ├── deterministic repository retrieval
  ├── exact symbol and canonical ID resolution
  ├── graph traversal and path tracing
  ├── caller and callee analysis
  ├── route and framework discovery
  ├── architecture and dependency extraction
  ├── Git diff and blast-radius impact analysis
  └── first-class evidence generation
  │
  ▼
STRUCTURED EVIDENCE
  │
  ├── canonical IDs (path::Symbol.method)
  ├── file paths and exact line ranges
  ├── verified relationship edges (CALLS, IMPORTS, HANDLED_BY)
  ├── index generation and freshness state
  └── repository commit hash
  │
  ▼
ANTIGRAVITY / AI
  │
  └── synthesizes the final human-readable answer with verified source citations
  ▼
USER
```

---

## Core Invariants

1. **Deterministic Execution**:
   $$\text{Repository State} + \text{Index Generation} + \text{MCP Request} \Longrightarrow \text{Identical Deterministic Result}$$
   Collections are deterministically sorted; results never change between identical invocations.
2. **Zero Natural-Language Guessing**: CodeGraph never guesses developer intent or infers vague concepts. If a symbol name is ambiguous across files, CodeGraph returns `status: "ambiguous"` with candidate canonical IDs for the AI to choose.
3. **No Hallucinations / UNKNOWN Handling**: Facts are backed by AST analysis and verified references. If a target does not exist or cannot be proven statically, CodeGraph reports `status: "not_found"` or `UNKNOWN`.
4. **Structured Evidence**: Every claim or relation is tied to `{ file, start_line, end_line, type, canonical_id }`.
5. **Completely Local & Resource-Bounded**: Zero LLM API calls, zero external vector databases, zero telemetry. Execution runs inside a strict resource governor with thread and memory bounds.

---

## Minimal Orthogonal 13-Tool MCP API

CodeGraph MCP exposes 13 core interrogation tools under `profile="core"`. Every tool returns structured data, an explicit `status` code (`"ok"`, `"not_found"`, `"ambiguous"`, `"invalid_request"`), index metadata, and verified evidence.

| Tool | Purpose | Key Inputs | Key Output Fields |
| :--- | :--- | :--- | :--- |
| `resolve_symbol` | Ground an exact or qualified symbol name | `name: str` | `status`, `symbol` (canonical ID, file, line), `candidates` (if ambiguous) |
| `search_symbols` | Deterministic token search over non-generated symbols | `query: str`, `top_k: int` | `status`, `results` (canonical ID, kind, score), `count` |
| `get_symbol` | Retrieve authoritative AST details for a canonical symbol | `canonical_id: str` | `status`, `symbol` (kind, signature, docstring, lines, decorators, parent, children) |
| `get_file` | Structural AST representation of an indexed file | `path: str`, `include_content: bool` | `status`, `file`, `hash`, `size`, `classes`, `functions`, `imports`, `routes` |
| `get_references` | Return verified call sites and references | `canonical_id: str` | `status`, `references` (file, start_line, end_line, type) |
| `get_callers` | Return functions and methods that call the target | `canonical_id: str` | `status`, `callers` (caller canonical ID, file, line, call site) |
| `get_callees` | Return functions and methods called by the target | `canonical_id: str` | `status`, `callees` (resolved, unresolved, and external calls) |
| `trace_path` | Deterministic BFS execution path between two symbols | `source_symbol: str`, `target_symbol: str`, `max_depth: int` | `status`, `path` (steps with from/to symbols, relationship, evidence), `reachable` |
| `get_imports` | Return imports for a file or canonical symbol | `file: str \| None`, `canonical_id: str \| None` | `status`, `imports` (module, imported_name, alias, line, evidence) |
| `get_dependents` | Reverse dependency query (files/symbols depending on target) | `canonical_id: str \| None`, `file: str \| None` | `status`, `dependents` (source, relationship, evidence) |
| `list_routes` | Discovered framework routes (FastAPI, Flask, Django, Express) | `framework: str \| None`, `method: str \| None`, `path: str \| None` | `status`, `routes` (method, route_path, framework, handler_name, canonical_id) |
| `get_architecture` | High-level repository structural overview | _none_ | `status`, `languages`, `directories`, `entrypoints`, `routes`, `dependencies` |
| `get_git_impact` | Git diff blast-radius impact analysis | `base: str`, `head: str` | `status`, `changed_files`, `modified_symbols`, `affected_callers`, `affected_callees`, `affected_routes` |

---

## Response Envelope & Evidence Format

Every response adheres to a predictable structure:

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
      "type": "DEFINES",
      "canonical_id": "src/auth/service.py::AuthService.authenticate"
    }
  ],
  "index": {
    "generation": 1,
    "created_at": "2026-10-01T12:00:00Z",
    "freshness": "FRESH"
  },
  "repository": {
    "commit": "a1b2c3d"
  }
}
```

### Ambiguous Resolution Example

When a query matches multiple symbols across different modules, CodeGraph will never guess:

```json
{
  "status": "ambiguous",
  "symbol": null,
  "candidates": [
    {
      "canonical_id": "src/admin/views.py::duplicate_helper",
      "file": "src/admin/views.py",
      "line": 15
    },
    {
      "canonical_id": "src/auth/views.py::duplicate_helper",
      "file": "src/auth/views.py",
      "line": 18
    }
  ],
  "message": "Multiple symbols match 'duplicate_helper'. Provide a qualified name or canonical ID."
}
```

---

## End-to-End Walkthrough

### 1. Developer asks:
> *"how does authetication wrks in my app?"*

### 2. Antigravity / AI decomposes the request:
- Recognizes query about authentication flows and routing.
- Calls `list_routes(path="auth")` to locate entrypoints.
- Calls `resolve_symbol("authenticate")` to identify the service handler.
- Calls `trace_path(source_symbol="src/auth/views.py::login_view", target_symbol="src/auth/service.py::AuthService.authenticate")`.
- Calls `get_callees(canonical_id="src/auth/service.py::AuthService.authenticate")`.

### 3. CodeGraph interrogates the repository:
- Returns exact route definitions (`POST /api/v1/auth/login` handled by `src/auth/views.py::login_view`).
- Proves BFS execution path from `login_view` $\to$ `AuthService.authenticate` with line evidence.
- Lists callees (`verify_password`, `create_jwt_token`, `log_audit_event`) with file citations.

### 4. Antigravity / AI synthesizes the answer:
> "Authentication in your application begins at the `POST /api/v1/auth/login` endpoint handled by [`login_view`](file:///src/auth/views.py#L25). It invokes [`AuthService.authenticate`](file:///src/auth/service.py#L42), which validates credentials via [`verify_password`](file:///src/auth/crypto.py#L12) and generates a JWT token via [`create_jwt_token`](file:///src/auth/token.py#L55)."

---

## Installation & Usage

```bash
pip install 'codegraph-engine[mcp]'
```

### Configure in MCP Client (Claude Desktop, Cursor, Gemini)

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["serve", "-r", "/path/to/your/repo", "--profile", "core"]
    }
  }
}
```

### CLI Inspection

```bash
# Index repository
codegraph index ./my-repo

# Search symbols
codegraph search "authenticate" -r ./my-repo

# Trace execution path
codegraph trace "login_view" -r ./my-repo

# Benchmark verification
codegraph benchmark -r ./my-repo
```

---

## AI Agent Usage

AI agents querying CodeGraph MCP should follow this deterministic lifecycle:

1. **Initialize repository if required**: Execute `codegraph init` or verify index status.
2. **Check freshness**: Verify `index.freshness == "FRESH"`. If stale, execute `codegraph index`.
3. **Resolve symbols**: Use `resolve_symbol` or `codegraph resolve-symbol <name>` before querying graphs.
4. **Query relationships**: Use `get_callers`, `get_callees`, or `trace_path` with canonical IDs.
5. **Use returned evidence**: Cite source file and exact line spans from `{ file, start_line, end_line, type, canonical_id }`.
6. **Handle UNKNOWN explicitly**: If a target is not found, report UNKNOWN rather than hallucinating facts.
7. **Handle AMBIGUOUS explicitly**: When multiple candidates match, present the candidates or request qualification. Never guess.
8. **Never infer unsupported repository facts**: Only make assertions backed by static AST evidence.

---

## CLI Path Defaults & Invocation

All repository inspection commands support optional repository paths defaulting to the current directory (`.`):

```bash
codegraph <command> [PATH] [--repo PATH]
```

Examples:
```bash
# Equivalent commands resolving to the current directory:
codegraph status
codegraph status .
codegraph status -r .
codegraph status --repo .

# Indexing:
codegraph index
codegraph index .
codegraph index /path/to/repo

# Explicit symbol commands:
codegraph get-symbol AuthService
codegraph resolve-symbol duplicate_action
codegraph trace AuthService -d 2
codegraph search "authenticate"
```

---

## Machine-Readable Error Contract & Stable Error Codes

Expected operational failures emit structured JSON without raw Python tracebacks. Every error includes actionable agent recovery instructions:

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

| Code | Meaning | Agent Next Action |
| :--- | :--- | :--- |
| `INDEX_NOT_FOUND` | Repository has not been indexed | `codegraph init` |
| `INDEX_STALE` | Repository modified after last indexing | `codegraph index` |
| `REPOSITORY_NOT_INITIALIZED` | Missing CodeGraph configuration | `codegraph init` |
| `INVALID_PATH` | Non-existent or invalid directory path | Check directory path |
| `PATH_OUTSIDE_REPOSITORY` | Path traversal attempt blocked | Keep paths within repo root |
| `SYMBOL_NOT_FOUND` | Symbol does not exist in AST index | `codegraph search <query>` |
| `SYMBOL_AMBIGUOUS` | Multiple candidates match query | `codegraph resolve <canonical_id>` |
| `INVALID_ARGUMENT` | Missing or empty required argument | Check command syntax |
| `INVALID_DEPTH` | Traversal depth outside 1..5 range | Clamped to 1..5 |
| `SENSITIVE_FILE_ACCESS_DENIED` | File is protected (e.g. `.env`) | Check privacy boundaries |
| `PARSE_FAILURE` | File contains syntax errors | Fix syntax and re-index |
| `UNSUPPORTED_LANGUAGE` | Language parser not supported | Check `codegraph doctor` |

---

## Verification & Release Gates

All releases are verified against rigorous gates:

- **Ruff**: 0 lint errors
- **Mypy**: 0 issues under strict typing
- **Pytest**: 344 unit, integration, and contract tests passing
- **Benchmarks**: 50 tasks across 10 categories:
  - Unsupported Claims: 0.0%
  - FACT Correctness: 100.0%
  - UNKNOWN Correctness: 98.0%
  - AMBIGUITY Correctness: 100.0%
  - STALE Handling: Verified

---

## License

MIT
