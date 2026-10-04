<p align="center">
  <img src="docs/assets/codegraph_logo.jpg" alt="CodeGraph MCP — Deep Deterministic Repository Intelligence for AI Coding Agents" width="500" />
</p>

<h1 align="center">CodeGraph-MCP Engine (v2.1.8)</h1>

<p align="center">
  <strong>Deep deterministic repository intelligence for AI coding agents.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codegraph-engine/2.1.8/"><img src="https://img.shields.io/badge/pypi-codegraph--engine%20v2.1.8-blue.svg" alt="PyPI: codegraph-engine v2.1.8" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB.svg" alt="Python 3.12 | 3.13" /></a>
  <a href="src/codegraph/mcp/server.py"><img src="https://img.shields.io/badge/MCP-14%20default%20%7C%2056%20full%20tools-2ea043.svg" alt="MCP Tools: 14 default | 56 full" /></a>
  <a href="tests/"><img src="https://img.shields.io/badge/pytest-853%20passed-brightgreen.svg" alt="Tests: 853 passed" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="Ruff: 0 errors" /></a>
  <a href="src/codegraph/"><img src="https://img.shields.io/badge/mypy-0%20issues%20(79%20files)-blue.svg" alt="Mypy: strict" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/codegraph-engine/2.1.8/"><strong>PyPI (v2.1.8)</strong></a> •
  <a href="#2-quickstart-30-second-setup"><strong>Quickstart</strong></a> •
  <a href="#1-built-for-aiml-and-backend-heavy-repositories"><strong>Built For</strong></a> •
  <a href="#5-database-intelligence"><strong>Database Intelligence</strong></a> •
  <a href="#6-runtime-intelligence--static-reconciliation"><strong>Runtime Evidence</strong></a> •
  <a href="#8-measured-performance-v216--v217"><strong>Measured Performance</strong></a> •
  <a href="docs/agent-brain.md"><strong>56-Tool Reference</strong></a> •
  <a href="https://github.com/raghurammrsd/CODE_GRAPH_MCP"><strong>GitHub</strong></a>
</p>

```text
The AI reasons.
CodeGraph interrogates the repository.
The evidence stays traceable.
```

**CodeGraph MCP gives AI coding agents an evidence-backed understanding of code, dependencies, databases, and optional runtime observations.**
> **Supported Languages & Frameworks:** First-class **Python** (`FastAPI`, `Flask`, `Django`, `SQLAlchemy`, `Celery`, `pytest`) + **TypeScript / JavaScript** (`.ts`, `.tsx`, `.js`, `.jsx`) & **Express.js** support.

When an AI coding agent works inside a complex Python or full-stack codebase, raw text search forces it to open dozens of files and mentally reconstruct call chains, router prefixes, dependency injection providers, and ORM table mappings inside its context window.

```text
Complex repository
      ↓
AI agent needs architectural & dataflow understanding
      ↓
CodeGraph interrogates the local repository index
      ↓
Compact, cited evidence (symbols, edges, tables, bounded slices)
      ↓
AI reasons and edits with traceable citations
```

### 30-Second Install

```bash
pip install "codegraph-engine[mcp]"
codegraph install
cd your-project
codegraph init
codegraph doctor
```

---

## 1. Built for AI/ML and Backend-Heavy Repositories

CodeGraph is engineered for **AI/ML engineers**, **LLM application developers**, **model/inference engineers**, **backend Python & TypeScript/JS developers**, and **maintainers of large multi-package repositories** where relationships cross module, framework, and database boundaries.

### AI/ML & LLM Engineering Workloads
- **Inference & Model Serving Services**: Trace HTTP/RPC routes (`FastAPI`, `Flask`) into inference handlers, request validators, preprocessing pipelines, model forward calls, postprocessing, and database/cache persistence.
- **Training & Evaluation Pipelines**: Map training entrypoints (`CLI` commands, scripts) to dataset loaders, feature transforms, trainer loops, checkpoint writers, and evaluation metrics.
- **LLM Applications & Tool Registries**: Resolve decorator and call-based tool/agent registries (`@register`, `register_tool`, `ROUTING_MANIFEST`), prompt/context builders, retrieval pipelines, and model provider clients.
- **Experiment & Monorepo Codebases**: Distinguish active source code (`SOURCE`) from generated protobuf/OpenAPI stubs (`GENERATED`), build outputs (`BUILD_ARTIFACT`), and vendor directories (`VENDOR`).

### Backend-Heavy Python, TypeScript/JS & Service Architectures
- **Web Frameworks**: **FastAPI**, **Flask**, **Django**, and **Express.js** route registration (`ROUTE_HANDLER`, `HANDLED_BY`, `ROUTES_TO`) and nested router prefix composition (`MOUNTS` via `include_router`, `register_blueprint`, `app.use`).
- **Multi-Language Full-Stack Indexing**: Deep **Python** AST & dataflow analysis alongside **TypeScript** (`.ts`, `.tsx`) and **JavaScript** (`.js`, `.jsx`) symbol, import, call, and **Express.js** route extraction.
- **Dependency Injection & Event Systems**: FastAPI `Depends(...)` (`INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `DI_CYCLE`), event buses (`EVENT_LISTENER`, `DISPATCHES_TO`), and **Celery** background task queues (`TASK_HANDLER`).
- **Persistence & ORM Layers**: **SQLAlchemy**, **Django ORM**, **SQLModel**, **Prisma**, **Alembic**, **Django Migrations**, and raw **SQL** (`PostgreSQL`, `MySQL`, `SQLite`) table/column read-write analysis.
- **Test Suites**: Link **pytest** and `unittest` test functions and fixtures directly to the symbols, routes, DI providers, and event handlers they verify (`TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`).

---

## 2. Quickstart (30-Second Setup)

### Step 1: Install the Package

```bash
pip install "codegraph-engine[mcp]"
```

### Step 2: Configure Your AI Coding Agents (`codegraph install`)

CodeGraph-MCP includes an interactive, idempotent onboarding installer ([`src/codegraph/installer.py`](src/codegraph/installer.py)) that detects installed AI coding agents (**Claude Code**, **Cursor**, **Antigravity**, **Codex CLI**, **Gemini CLI**, and **Cline**), configures `mcpServers.codegraph`, installs marker-bounded routing instructions (`<!-- CODEGRAPH:START -->` … `<!-- CODEGRAPH:END -->`), and verifies MCP server startup:

```bash
# Interactive setup (detects installed agents, previews planned changes, asks confirmation)
codegraph install

# Non-interactive setup for all detected agents in the current project
codegraph install --yes --target auto --location local

# Preview exact file modifications without writing anything
codegraph install --dry-run
```

### Step 3: Initialize & Verify Your Project Index

```bash
cd your-project
codegraph init
codegraph status
codegraph doctor
```

> **Dynamic Index Hot-Reloading:** If your AI coding agent launches `codegraph mcp serve` before you run `codegraph init`, you do **not** need to restart your IDE or MCP session. As soon as `codegraph init` or `codegraph index` creates or updates `.codegraph.sqlite3`, the running MCP server automatically detects the updated database on the next tool call and refreshes its in-memory graph cache (`get_repository_status(reload=True, reindex=True)` can also be invoked directly by the agent).

### Managing Installation, Process & Project Index Lifecycle

CodeGraph cleanly separates agent configuration, process lifecycle, and project index files:

| Command | Scope | What It Does |
| :--- | :--- | :--- |
| `codegraph install` | Agent configuration | Configures MCP server + marker-managed rules/skills for selected AI agents (ASCII-safe on Windows `cp1252`). |
| `codegraph init` | Project repository | Initializes `.codegraph.sqlite3` and indexes the current repository (hot-reloaded automatically by running MCP servers). |
| `codegraph index` | Project repository | Incrementally indexes modified files (`--verbose`, `--quiet`, `--json`). |
| `codegraph stop` | Process lifecycle | Safely stops running CodeGraph-owned MCP background processes (`--all`, `--repo`, `--json`) and releases file locks. |
| `codegraph doctor --processes` | Process lifecycle | Lists active CodeGraph MCP processes, parent PIDs, orphan status, and cleans stale PID files. |
| `codegraph uninstall` | Agent configuration | Stops active workspace MCP processes and removes CodeGraph-managed MCP entries and instruction blocks. |
| `codegraph uninit` | Project repository | Removes only `.codegraph.sqlite3` and `.codegraph/` in the project (never touches source code or Git history). |

### Safe Upgrading on Windows (`WinError 32` Prevention)

On Windows, running `pip install --upgrade codegraph-engine` while an IDE or agent still holds `codegraph.exe` open can trigger `WinError 32`. Before upgrading on Windows, run:

```bash
codegraph stop --all
pip install --upgrade "codegraph-engine[mcp]"
```

---

## 3. Core Workflow & Architecture

```mermaid
flowchart TD
    A["AI Coding Agent"] --> B["CodeGraph MCP"]
    B --> C["Repository Intelligence"]

    C --> D["Semantic Graph"]
    C --> E["Text Search (search_code)"]
    C --> F["Source Inspection (get_file)"]
    C --> G["Database Intelligence"]
    C --> H["Runtime Observation"]

    D --> I["Structured Evidence + Epistemic Labels"]
    E --> I
    F --> I
    G --> I
    H --> I

    I --> J["Context Optimization + Secret Redaction"]
    J --> A
```

### Routing Each Question to the Right Primitive

```text
STRUCTURAL     →  Graph tools (find_symbol, find_callers, find_callees, find_references, find_routes)
TEXTUAL        →  search_code (literal/regex search across Python, HTML/Jinja, JS/TS, CSS, YAML/JSON, SQL)
SOURCE         →  get_file (bounded start_line..end_line source inspection with truncation metadata)
GRAPH          →  Trace tools (trace_path, trace_flow, analyze_impact, get_git_impact)
DATABASE       →  Database tools (get_db_schema, find_db_tables, find_db_readers, find_db_writers, get_db_impact)
RUNTIME        →  Runtime/reconciliation tools (ingest_runtime_traces, get_runtime_trace, reconcile_static_runtime)
EDITING        →  Native agent / IDE editing tools
```

---

## 4. AI/ML & Backend Architecture Examples

### Example 1: Model Inference Service Flow

```text
POST /v1/predict (FastAPI Route)
      ↓  HANDLED_BY (FRAMEWORK_VERIFIED)
predict_endpoint (Handler)
      ↓  INJECTS (DATAFLOW_VERIFIED)
get_inference_service (DI Provider)
      ↓  CALLS (AST_VERIFIED)
InferenceService.run_inference
      ├──►CALLS (AST_VERIFIED) ──► FeaturePreprocessor.transform
      ├──►CALLS (AST_VERIFIED) ──► FraudClassifier.forward
      ├──►CALLS (AST_VERIFIED) ──► ScorePostprocessor.calibrate
      └──►CALLS (AST_VERIFIED) ──► PredictionRepository.log_prediction
                                        ↓  WRITES_TABLE (AST_VERIFIED)
                                   db:table:postgresql.public.prediction_logs
```

**What CodeGraph-MCP structurally proves**:
- `find_routes(path="/v1/predict")` resolves composed router prefixes (`MOUNTS`) to `predict_endpoint`.
- `trace_path(from_symbol="predict_endpoint", to_symbol="log_prediction")` proves the multi-hop execution chain across DI injection, preprocessing, model execution, and persistence.
- `get_db_impact(symbol="InferenceService.run_inference")` identifies downstream writes to `prediction_logs`.

### Example 2: Training & Evaluation Pipeline

```text
train_cli (CLI Command Handler)
      ↓  COMMAND_HANDLER (FRAMEWORK_VERIFIED)
TrainingPipeline.run
      ├──►CALLS (AST_VERIFIED) ──► DatasetBuilder.load_splits
      ├──►CALLS (AST_VERIFIED) ──► TokenizerTransform.encode_batch
      ├──►CALLS (AST_VERIFIED) ──► Trainer.fit_epoch
      ├──►CALLS (AST_VERIFIED) ──► CheckpointManager.save_weights
      └──►CALLS (AST_VERIFIED) ──► Evaluator.compute_metrics
```

**What CodeGraph-MCP structurally proves**:
- `find_callees(symbol="TrainingPipeline.run")` enumerates every stage of the pipeline with exact file and line ranges.
- `find_tests(symbol="Evaluator.compute_metrics")` locates the unit and regression tests covering metric calculation.
- When a transform or model class is dynamically instantiated from a YAML string (`getattr(models, cfg.arch)`), CodeGraph explicitly records `POSSIBLE_CALLS` (`POSSIBLE`) or `UNRESOLVED_REFERENCE` (`UNKNOWN`) rather than fabricating a false static call edge.

### Example 3: LLM Agent & Tool Registry

```text
POST /api/chat (LLM Endpoint)
      ↓  HANDLED_BY (FRAMEWORK_VERIFIED)
chat_handler
      ↓  CALLS (AST_VERIFIED)
AgentRunner.execute_step
      ├──►REGISTERS / REGISTERED_HANDLER ──► ToolRegistry ("search_orders", "refund_order")
      ├──►CALLS (AST_VERIFIED)           ──► ContextBuilder.compile
      ├──►READS_TABLE (AST_VERIFIED)     ──► db:table:postgresql.public.conversations
      └──►CALLS (AST_VERIFIED)           ──► ModelProviderClient.generate
```

**What CodeGraph-MCP structurally proves**:
- Tracks decorator and call-based registrations (`@tool_registry.register("search_orders")`) via `REGISTERS` and `REGISTERED_HANDLER` edges.
- Tracks environment variable dependencies (`os.getenv("OPENAI_API_KEY")`) as `READS_ENV` edges with the variable name only—never indexing or exposing secret values.

### Example 4: Full-Stack Feature Investigation (Dundoo Bill Scanner)

Validated end-to-end in [`src/codegraph/tool_selection_eval.py`](src/codegraph/tool_selection_eval.py) (`run_dundoo_bill_scanner_e2e_eval()`):

```text
Developer Prompt: "Wire up AI bill scanning next to the Manual Entry button"
   │
   ├── 1. get_architecture()                                  → Maps app/, templates/, static/js/, tests/
   ├── 2. search_code(query="Add Manual Entry")               → Matches templates/bills.html:6
   ├── 3. get_file(path="templates/bills.html", 1..12)        → Reads bounded 12-line HTML slice
   ├── 4. find_routes(path="/api/scan-bill")                  → Resolves POST /api/scan-bill → scan_bill_endpoint
   ├── 5. find_symbol(symbol="parse_bill")                    → Grounds app/bill_scanner.py::parse_bill
   ├── 6. get_file(path="app/bill_scanner.py", 1..20)         → Reads parse_bill() and normalize_line_items()
   ├── 7. find_callers(symbol="parse_bill")                   → Confirms scan_bill_endpoint calls parse_bill
   └── 8. find_tests(symbol="parse_bill")                     → Finds test_parse_bill_calculates_total
```

---

## 5. Database Intelligence

[`src/codegraph/database/`](src/codegraph/database/) provides static schema, ORM model, migration, and query extraction across **SQLAlchemy**, **Django ORM**, **SQLModel**, **Prisma** (`.prisma`), **Alembic**, **Django Migrations**, and **Raw SQL** (`PostgreSQL`, `MySQL`, `SQLite`).

```text
POST /orders
      ↓  HANDLED_BY (FRAMEWORK_VERIFIED)
OrderService.create_order
      ↓  CALLS (AST_VERIFIED)
OrderRepository.insert_order
      ↓  WRITES_TABLE (AST_VERIFIED)
db:table:postgresql.public.orders
      ↓  FOREIGN_KEY_TO (AST_VERIFIED)
orders.user_id ──► users.id
```

### Capabilities Exposed by the 11 Database MCP Tools
- **Table & Column Discovery** (`get_db_schema`, `get_db_table`, `find_db_tables`, `find_db_columns`): Extract tables, column types, nullability, defaults, primary keys (`HAS_PRIMARY_KEY`), indexes (`HAS_INDEX`), unique/check constraints, and foreign keys (`FOREIGN_KEY_TO`).
- **ORM Mapping** (`find_db_models`): Map SQLAlchemy `__tablename__`, Django `models.Model` (`Meta.db_table`), SQLModel `table=True`, and Prisma `model` blocks via `MAPS_TO_TABLE` and `MAPS_TO_COLUMN`.
- **Readers, Writers & Callers** (`find_db_readers`, `find_db_writers`, `find_db_callers`, `find_db_queries`): Identify every function or method that executes `SELECT` (`READS_TABLE`) or `INSERT` / `UPDATE` / `DELETE` / `.add()` / `.save()` (`WRITES_TABLE`) against a table.
- **Migration Lineage & Schema Blast Radius** (`find_db_relationships`, `get_db_impact`): Track Alembic (`op.create_table`, `op.add_column`) and Django (`migrations.CreateModel`, `migrations.AddField`) operations (`MIGRATES_TABLE`) and compute bidirectional code $\leftrightarrow$ database impact.

---

## 6. Runtime Intelligence & Static Reconciliation

Static analysis proves what **can** happen structurally; runtime telemetry records what **was observed** during a specific execution window. [`src/codegraph/runtime/`](src/codegraph/runtime/) combines both without conflating them:

```text
STATIC GRAPH (AST + Framework + Dataflow + DB)
                   +
OPTIONAL RUNTIME OBSERVATION (OTel JSON / JSONL Events / SQL Logs)
                   ↓
      reconcile_static_runtime()
```

### Reconciliation Outcomes ([`ReconciliationStatus`](src/codegraph/runtime/models.py))

| Reconciliation Status | Static Graph | Runtime Trace | Meaning |
| :--- | :---: | :---: | :--- |
| **`CONFIRMED_RUNTIME_PATH`** | Present | Observed | Static relationship is structurally proven **and** observed executing in ingested traces. |
| **`NOT_OBSERVED_AT_RUNTIME`** | Present | Not observed | Statically valid edge was not exercised in the ingested trace sample. |
| **`RUNTIME_ONLY_OBSERVED`** | Dynamic / `UNKNOWN` | Observed | Executed at runtime (e.g., plugin hook, `getattr`, dynamic SQL) where static analysis remained `UNKNOWN`. |
| **`STATIC_RUNTIME_CONFLICT`** | Target A | Target B | Runtime execution dispatched to a different target than static resolution (e.g., dependency override or subclass). |

### Epistemic Rules for Runtime Evidence
1. **Runtime Telemetry Is Opt-In & Observational**: CodeGraph never instruments or executes your code automatically. Traces are ingested only when you call `ingest_runtime_traces` on OpenTelemetry JSON, structured JSONL, or SQL log files.
2. **`NOT_OBSERVED_AT_RUNTIME` Does Not Mean Dead Code**: It only means the code path was not triggered during the recorded trace window (for example, an error handler, admin route, or periodic job).
3. **Runtime Observations Never Overwrite Static Proof**: Runtime spans are stored with `evidence_class="RUNTIME_OBSERVED"` and kept distinct from `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, and `DATAFLOW_VERIFIED` static edges.

---

## 7. Epistemic Trust & Evidence Contract

CodeGraph enforces a fail-closed evidence contract ([`src/codegraph/evidence_contract.py`](src/codegraph/evidence_contract.py)) across all **51 canonical relationship types** and **9 evidence classes**. CodeGraph prefers **explicit uncertainty** over **fabricated certainty**:

```text
Dynamically resolved target (getattr(handler, action_name)())
      ↓
UNRESOLVED_REFERENCE / POSSIBLE_CALLS (status = "UNKNOWN" | "POSSIBLE")
(Never fabricated into a verified CALLS edge)
```

### Current Evidence Vocabulary (`src/codegraph/evidence_contract.py`)

| Epistemic Status | Allowed Evidence Classes | What It Means |
| :--- | :--- | :--- |
| **`FACT`** | `AST_VERIFIED`, `STATIC_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED` | Proven directly from syntax tree, framework decorator/router semantics, or conservative local dataflow. |
| **`RUNTIME_OBSERVED`** | `RUNTIME_OBSERVED` | Observed in user-supplied OpenTelemetry, JSONL, or SQL query logs (`hit_count`, `p50_ms`, `p95_ms`). |
| **`POSSIBLE`** | `POSSIBLE` | Plausible candidate relationship (`POSSIBLE_CALLS`, `POSSIBLE_TABLE`) requiring source inspection before mutation. |
| **`AMBIGUOUS`** | `AMBIGUOUS` | Multiple symbols or database tables match the bare identifier across modules or dialects; returns sorted `candidates`. |
| **`UNKNOWN`** | `UNKNOWN`, `RUNTIME_UNOBSERVED` | Target cannot be statically proven (dynamic reflection, external unindexed dependency, or `reason="resolution_budget_exceeded"`). |
| **`CONFLICT`** | Static vs. Runtime / Multi-Source | Static analysis and runtime observation (or competing definitions) disagree. |

---

## 8. Measured Performance (`v2.1.6` → `v2.1.7`)

### Methodology
All indexing measurements below were recorded using [`benchmarks/run_v217_indexing_benchmark.py`](benchmarks/run_v217_indexing_benchmark.py) on the **same machine** (macOS `arm64`, Python `3.13`), **same repository fixtures**, and **same 16-phase telemetry harness**, comparing `v2.1.6` ([`benchmarks/reports/v217_before_metrics.json`](benchmarks/reports/v217_before_metrics.json)) against `v2.1.7` ([`benchmarks/reports/v217_after_metrics.json`](benchmarks/reports/v217_after_metrics.json)).

### 4-Tier Scaling Summary (`54` → `2,504` Files)

| Workload Tier | Files | Symbols | Graph Edges | `v2.1.6` Total | `v2.1.7` Total | Improvement | `v2.1.7` Peak RSS | Peak WAL (`v2.1.6` → `v2.1.7`) | Final WAL |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: |
| **Small** | `54` | `115` | `398` | `0.527 s` | `0.325 s` | **38.3% faster (`1.62x`)** | `46.25 MB` | `0.990 MB → 1.544 MB` | `0.0 MB` |
| **Medium** | `304` | `615` | `2,248` | `2.564 s` | `1.613 s` | **37.1% faster (`1.59x`)** | `62.67 MB` | `5.610 MB → 4.098 MB` | `0.0 MB` |
| **Large** | `1,004` | `2,015` | `7,428` | `8.730 s` | `5.296 s` | **39.3% faster (`1.65x`)** | `103.44 MB` | `19.300 MB → 5.033 MB` | `0.0 MB` |
| **Stress** | `2,504` | `5,015` | `18,528` | `21.983 s` | `13.395 s` | **39.1% faster (`1.64x`)** | `180.89 MB` | `46.980 MB → 6.628 MB` | `0.0 MB` |

### Stress Tier (`2,504` Files) Phase Breakdown

| Phase / Metric | `v2.1.6` Baseline | `v2.1.7` Release | Measured Improvement |
| :--- | ---: | ---: | :--- |
| **Total Indexing Time** | `21.983 s` | `13.395 s` | **39.1% faster (`1.64x`)** |
| **Database Intelligence Pass** | `4.818 s` | `0.832 s` | **82.7% faster (`5.79x`)** |
| **Post-Processing Phase** | `13.770 s` | `7.056 s` | **48.8% faster (`1.95x`)** |
| **Symbol Resolution Phase** | `3.133 s` | `1.107 s` | **64.7% faster (`2.83x`)** |
| **Single-File Incremental Update** | `4.408 s` | `2.063 s` | **53.2% faster (`2.14x`)** |
| **Throughput (`files/sec`)** | `113.9 files/s` | `186.9 files/s` | **`+64.1%` throughput** |
| **Peak SQLite WAL Size** | `46.980 MB` | `6.628 MB` | **85.9% reduction (`7.09x` smaller)** |
| **Final SQLite WAL Size** | `0.000 MB` | `0.000 MB` | **100% reclaimed (`TRUNCATE`)** |
| **Indexed Symbols / Graph Edges** | `5,015` / `18,528` | `5,015` / `18,528` | **100% exact parity** |

![CodeGraph — Measured Large-Repository Scaling](docs/assets/large_repo_scaling.svg)

---

## 9. Large-Repository Stress Testing: Home Assistant Core

Home Assistant Core is a large, complex public Python repository used as a real-world stress case for CodeGraph's indexing and post-processing pipeline.

### 1. External Large-Repository Stress Observation (Pre-`v2.1.7`)
During external stress testing on a Home Assistant Core checkout (`~28,573` files), pre-`v2.1.7` indexing exhibited:
- Sustained single-core CPU usage (`~99%`) dominated by late post-processing
- Process memory peaking around `~1.1 GB` RSS before dropping
- Uncheckpointed `.codegraph/index.db-wal` growth reaching `~922 MB` because indexing held a single uncommitted transaction across all files and post-processing edges

### 2. Reproducible Benchmark Fixture & Root-Cause Fixes (`v2.1.7`)
To profile and verify fixes deterministically in CI, [`benchmarks/run_v217_indexing_benchmark.py`](benchmarks/run_v217_indexing_benchmark.py) provisions a 4-tier Home Assistant-architecture fixture (`homeassistant/core`, `homeassistant/helpers`, `homeassistant/components/recorder` SQLAlchemy models/queries, `500` component domains, and `pytest` fixture suites; `2,504` files, `5,015` symbols, `18,528` edges):
- **Streaming & Token-Gated Database Pass**: Replaced the in-memory `file_contents` map and 8-per-file AST parses with streaming reads, fast token pre-filters (`has_potential_database_activity`, `has_potential_orm_models`), and a single shared `ast.AST` parse per candidate file (`4.818s → 0.832s`).
- **Pre-Indexed Binding & Symbol Resolution**: Replaced four $O(N_{\text{bindings}} \times N_{\text{symbols}})$ linear scans in [`src/codegraph/resolver.py`](src/codegraph/resolver.py) with pre-indexed maps and `@lru_cache(maxsize=65536)` on `normalize_module` (`3.133s → 1.107s`).
- **Chunked SQLite Commits & `TRUNCATE` Checkpoints**: Added composite indexes (`idx_imports_source_line`, `idx_calls_source_line`), bounded commit batches (`500` files / `10,000` edges), and `PRAGMA wal_checkpoint(TRUNCATE)` (`46.980 MB → 6.628 MB` peak WAL; `0.0 MB` final WAL).
- **Safe `Ctrl+C` Cancellation & Resume**: Interrupting `codegraph index` rolls back only the active batch, preserves committed batches, marks `resolution_dirty="1"`, and resumes cleanly on the next run.

---

## 10. Context Efficiency & Internal Agent Evaluation

### 50-Task Context Compilation Benchmark ([`benchmarks/baselines/v2_0_verified.json`](benchmarks/baselines/v2_0_verified.json))

Rather than claiming a single universal token reduction percentage across all possible prompts, CodeGraph records candidate-vs-selected token metrics on every `get_context` call:

| Benchmark Metric | Measured Value | Source Artifact |
| :--- | ---: | :--- |
| **Evaluated Tasks** | `50 tasks` across `10 categories` | [`benchmarks/baselines/v2_0_verified.json`](benchmarks/baselines/v2_0_verified.json) |
| **Average Selected Tokens** | `542.0 tokens` | [`benchmarks/baselines/v2_0_verified.json`](benchmarks/baselines/v2_0_verified.json) |
| **Average Candidate-to-Selected Reduction Ratio** | `65.0%` (`0.65`) | [`benchmarks/baselines/v2_0_verified.json`](benchmarks/baselines/v2_0_verified.json) |
| **Compression at `budget = 200 tokens`** | `85.6%` reduction | [`benchmarks/baselines/context_baseline.json`](benchmarks/baselines/context_baseline.json) |
| **Compression at `budget = 600 tokens`** | `56.3%` reduction | [`benchmarks/baselines/context_baseline.json`](benchmarks/baselines/context_baseline.json) |
| **Cold vs. Warm `get_context` Latency (`p50`)** | `20.0 ms` cold → `0.67 ms` warm (`30.0x`) | [`benchmarks/baselines/context_baseline.json`](benchmarks/baselines/context_baseline.json) |
| **Single-Tool Query Latency (Indexed SQLite)** | `1 ms – 15 ms` | Local SQLite B-tree / FTS5 lookup |
| **FACT / UNKNOWN / AMBIGUITY Correctness** | `100.0%` / `98.0%` / `100.0%` | [`benchmarks/baselines/v2_0_verified.json`](benchmarks/baselines/v2_0_verified.json) |

### Results from the 32-Task Internal Evaluation ([`src/codegraph/tool_selection_eval.py`](src/codegraph/tool_selection_eval.py))

The table below reports results from the **32-task internal evaluation harness** (`run_tool_selection_ab_benchmark()`) comparing Mode A (unassisted `grep` + full-file reading without CodeGraph routing rules) against Mode B (CodeGraph MCP + agent routing rules) on the same 32 tasks:

| Metric (32-Task Internal Evaluation) | Mode A (Without CodeGraph) | Mode B (With CodeGraph MCP) | Measured Improvement |
| :--- | ---: | ---: | :--- |
| **Total Tool Calls (32 Tasks)** | `164 calls` (`~5.1 / task`) | `71 calls` (`~2.2 / task`) | **`-93 calls (-56.7% fewer tool calls)`** |
| **Direct Full-File Reads** | `161 full-file reads` | `7 bounded slice reads` | **`-154 file reads (-95.7% fewer file reads)`** |
| **Context Tokens per Task** | `3,000 – 12,000+ tokens` (full files) | `~542 tokens` avg (`get_context`) | **`65.0% – 85.6% token reduction`** |
| **Query Latency (`p50`)** | Hundreds of ms (multi-step `grep` + reads) | `20.0 ms` cold / `0.67 ms` warm (`30.0x`) | **Sub-20ms indexed lookup** |
| **First-Tool Selection Accuracy** | `9.38%` | `100.0%` | **`+90.62%`** |
| **Unsupported Claims (Hallucinated Edges)** | `11 (34.38%)` | `0 (0.00%)` | **`-11 claims (0% unsupported)`** |
| **Task Accuracy** | `59.84%` | `100.0%` | **`+40.16%`** |
| **12-Prompt Natural-Language Routing Eval** | — | `12 / 12 (100.0%)` | **`12/12 on this evaluation set`** |

![CodeGraph — Measured Context & Exploration Efficiency](docs/assets/performance_comparison.svg)

---

## 11. Where CodeGraph Fits

CodeGraph is designed to work **alongside** your editor's language server (LSP), `ripgrep`, and structural AST tools.

Legend: `✓` supported • `◐` partial / workflow-dependent • `—` not established by cited documentation

| Capability | CodeGraph MCP (`v2.1.7`) | Editor LSP [1] | Structural AST (`ast-grep`) [2] | Lexical Search (`ripgrep`) [3] | Remote Code Search (`Sourcegraph MCP`) [4] |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Local-First & Offline Operation** | ✓ | ✓ | ✓ | ✓ | — |
| **Native MCP Server for AI Agents** | ✓ (14 default / 56 full) | — | ◐ | — | ✓ |
| **Semantic Symbol Graph (Callers / Callees)** | ✓ | ◐ (Position-based) | ◐ (Pattern-based) | — | ✓ (SCIP) |
| **Framework Route, Mount & DI Graph** | ✓ (`FastAPI`/`Flask`/`Django`/`Express`) | — | ◐ (Custom YAML rules) | — | — |
| **Database Schema, ORM, Migration & Table R/W** | ✓ (11 DB tools) | — | — | — | — |
| **Opt-In Runtime Trace Ingestion & Reconciliation** | ✓ (OTel / JSONL / SQL) | — | — | — | — |
| **Explicit Epistemic States (`FACT`/`POSSIBLE`/`UNKNOWN`)** | ✓ | — | — | — | — |
| **Literal Text Search Across HTML/JS/CSS/Config** | ✓ (`search_code`) | — | — | ✓ | ✓ |
| **Interactive Editor Hover, Completions & Diagnostics** | — | ✓ | ✓ (Lint/Rewrite) | — | — |
| **Multi-Repository Enterprise Cloud Search** | — | — | — | — | ✓ |

![Repository Retrieval Approaches — Capability Comparison](docs/assets/capability_heatmap.svg)

For the complete multi-tool comparison and official references ([1] [LSP Specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/current/), [2] [`ast-grep`](https://ast-grep.github.io/), [3] [`ripgrep`](https://github.com/BurntSushi/ripgrep), [4] [Sourcegraph MCP](https://sourcegraph.com/docs/api/mcp), [5] [Colby McHenry CodeGraph](https://github.com/colbymchenry/codegraph), [6] [GitHub Code Navigation](https://docs.github.com/en/repositories/working-with-files/using-files/navigating-code-on-github)), see [`docs/tool-comparison.md`](docs/tool-comparison.md).

---

## 12. Security, Privacy & Redaction Boundaries

CodeGraph runs **100% locally** (`stdio` MCP + local `.codegraph.sqlite3`), never executes repository code during indexing, and enforces strict file-access and redaction boundaries ([`src/codegraph/security/paths.py`](src/codegraph/security/paths.py), [`src/codegraph/security/redaction.py`](src/codegraph/security/redaction.py)).

### `BLOCKED` vs. `REDACTED` Behavior

| Security Boundary | Enforcement Mode | Exact Behavior |
| :--- | :---: | :--- |
| **Sensitive Files** (`.env`, `.env.*`, `*.pem`, `*.key`, `*.crt`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `kubeconfig*`, `.npmrc`, `.pypirc`, `.netrc`, `.git/credentials`, `credentials*`, `secrets.*`, `*secret*.json/yaml`, `service-account*`, `.aws/*`, `.ssh/*`, `.gnupg/*`, `.kube/*`, `.docker/config.json`, `*.sqlite*`, `*.db`) | **`BLOCKED`** | Excluded from indexing and FTS; direct inspection via `get_file` or `read_file` is rejected with `SENSITIVE_FILE_ACCESS_DENIED`. |
| **Path Traversal & Symlink Escapes** (`../`, URL-encoded `%2e%2e`, null bytes, external symlinks) | **`BLOCKED`** | Canonical path check in `resolve_within_repo()` raises `SecurityError(ErrorCode.PATH_OUTSIDE_REPOSITORY)`. |
| **Binary Files** (`.pyc`, `.so`, `.dylib`, `.dll`, `.exe`, images, archives, PDFs, fonts, or NUL-byte files) | **`BLOCKED`** | Classified as `BINARY` and skipped during indexing and text search. |
| **Environment Variable Reads in Code** (`os.getenv("DATABASE_URL")`, `os.environ["OPENAI_API_KEY"]`) | **Metadata Only** | Records `READS_ENV` with the **variable name only**; never reads `.env` or runtime environment values. |
| **Database Connection Strings** (`postgresql://user:pass@host:5432/prod`) | **`REDACTED`** | Preserves dialect and database name while sanitizing credentials to `postgresql://[REDACTED]@[REDACTED]/prod`. |
| **API Keys, Bearer Tokens, JWTs & Private Keys** (`sk-...`, `ghp_...`, `AKIA...`, `AIza...`, `xoxb-...`, `eyJ...`, `-----BEGIN ... PRIVATE KEY-----`) | **`REDACTED`** | Replaced with `[REDACTED_SECRET]`, `Bearer [REDACTED]`, or `[REDACTED_PRIVATE_KEY]` before FTS indexing, `search_code`, `get_file`, `get_context`, or MCP responses. |
| **Runtime HTTP Headers & SQL Query Literals** (`authorization`, `cookie`, `set-cookie`, `x-api-key`, `WHERE password = '...'`) | **`REDACTED`** | Sensitive runtime keys and SQL literals are scrubbed (`[REDACTED]` / `?`) during `ingest_runtime_traces`. |

Run `codegraph privacy .` at any time to audit the local SQLite database and verify that no sensitive files or unredacted secrets are stored.

---

## 13. MCP Tooling & Profiles (14 Default / 56 Full)

By default, `create_server()` exposes the **14-tool `agent` profile** so AI coding agents receive a focused, non-overlapping tool surface. All 56 tools are available under `--profile full`.

### Default `agent` Profile (14 High-Signal Tools)

| Category | Tool | Purpose |
| :--- | :--- | :--- |
| **Discovery (7)** | `find_symbol` | Locate a symbol definition by short, qualified, or canonical name (`symbol=...`). |
| | `search_code` | Literal or regex search across Python, JS/TS, HTML/Jinja, CSS, YAML/JSON, Markdown, and SQL. |
| | `find_references` | Find verified AST reference, import, and registration sites for a symbol. |
| | `find_callers` | Find functions, methods, or route handlers that call the target symbol (`CALLS`, `POSSIBLE_CALLS`). |
| | `find_callees` | Find functions, methods, or constructors called by the target symbol. |
| | `find_tests` | Find `pytest` / `unittest` test functions covering a symbol, route, DI provider, or event handler. |
| | `find_routes` | Discover FastAPI, Flask, Django, and Express HTTP routes with composed mount prefixes. |
| **Details & Context (5)** | `get_symbol` | Retrieve signature, decorators, docstring, line range, and methods for a symbol. |
| | `get_file` | Read bounded line ranges (`start_line`, `end_line`, `max_lines`) and AST symbol outline of a file. |
| | `get_context` | Compile a token-budgeted, task-aware context packet (`query`, `intent`, `max_tokens`). |
| | `get_architecture` | Summarize repository languages, layers, packages, entrypoints, routes, and database entities. |
| | `get_git_impact` | Compute blast-radius impact (`changed_files`, `affected_callers`, `affected_routes`, `tests`) for a Git diff. |
| **Graph Tracing (2)** | `trace_path` | Find the shortest verified execution path between `from_symbol` and `to_symbol`. |
| | `trace_flow` | Trace upstream callers and downstream callees around `symbol` up to `depth`. |

### All 6 Implemented MCP Profiles ([`src/codegraph/agent_capabilities.py`](src/codegraph/agent_capabilities.py))

| Profile | Tool Count | Description |
| :--- | :---: | :--- |
| **`agent`** *(default in `create_server`)* | **14** | High-signal discovery, bounded file inspection, context synthesis, and path tracing. |
| **`core`** | **13** | Lightweight symbol lookup, callers/callees, imports/dependents, routes, and architecture. |
| **`graph`** | **17** | Call-graph traversal, blast-radius impact (`analyze_impact`), and test discovery. |
| **`minimal`** | **21** | Core interrogation plus `get_context`, `search_code`, `read_file`, and `verify_evidence`. |
| **`developer`** | **34** | Interactive development with Git history (`get_file_history`, `get_recent_changes`) and retrieval planning. |
| **`full`** | **56** | Complete capability surface including **11 Database tools** (`get_db_schema`, `get_db_table`, `find_db_tables`, `find_db_columns`, `find_db_models`, `find_db_queries`, `find_db_readers`, `find_db_writers`, `find_db_callers`, `find_db_relationships`, `get_db_impact`) and **3 Runtime tools** (`ingest_runtime_traces`, `get_runtime_trace`, `reconcile_static_runtime`). |

See [`docs/agent-brain.md`](docs/agent-brain.md) and [`agent-rules/tool-capabilities-summary.md`](agent-rules/tool-capabilities-summary.md) for the complete 56-tool reference.

---

## 14. CLI Reference

Every command below is verified against [`src/codegraph/cli.py`](src/codegraph/cli.py):

```bash
# Agent Onboarding & Uninstall
codegraph install                                          # Interactive agent detection & setup
codegraph install --yes --target auto --location local     # Non-interactive local setup
codegraph install --print-config claude                    # Print MCP JSON + rules for an agent
codegraph install --dry-run                                # Preview planned file changes
codegraph uninstall --dry-run                              # Preview removal of CodeGraph agent blocks
codegraph uninstall --yes                                  # Remove CodeGraph agent integrations

# Repository Initialization & Indexing
codegraph init .                                           # Initialize and index repository
codegraph index . --verbose                                # Incremental index with 16-phase telemetry
codegraph index . --json                                   # Output structured JSON phase telemetry
codegraph uninit --dry-run                                 # Preview removal of .codegraph.sqlite3

# Process Lifecycle & Upgrade Lock Safety
codegraph stop                                             # Safely stop CodeGraph MCP server for current repo
codegraph stop --all                                       # Stop all CodeGraph-owned MCP processes across repos
codegraph stop --repo /path/to/repo --json                 # Stop MCP processes for a specific repo (JSON output)
codegraph doctor --processes                               # Inspect active MCP processes, parent PIDs, & stale locks

# Health, Integrity & Privacy Diagnostics
codegraph status .                                         # Show index freshness and graph counts
codegraph doctor . --database --resources                  # Verify SQLite integrity, FKs, FTS, and memory
codegraph privacy .                                        # Verify zero sensitive files indexed
codegraph version                                          # Print CodeGraph version (2.1.7)

# Code, Graph & Context Interrogation
codegraph search "authenticate" -r .                       # Search indexed symbols and chunks
codegraph symbols src/codegraph/cli.py -r .                # List extracted symbols in a file
codegraph get-symbol Indexer -r .                          # Get AST details for a symbol
codegraph resolve-symbol resolve_Repository -r .           # Ground symbol or return ambiguous candidates
codegraph resolve Indexer -r .                             # Resolve symbol with callers and callees
codegraph trace Indexer -d 2 -r .                          # Trace callers and callees up to depth 2
codegraph graph -r .                                       # Summarize graph nodes and edges
codegraph routes -r .                                      # List discovered HTTP routes
codegraph imports src/codegraph/cli.py -r .                # List file/module imports
codegraph dependents src/codegraph/cli.py -r .             # List reverse dependents
codegraph architecture -r .                                # Summarize repository architecture
codegraph debug "trace authentication flow" -r .           # Return facts and debugging hypotheses
codegraph task "trace /api/v1/auth/login"                  # Normalize prompt into a TaskSpec
codegraph plan "trace /api/v1/auth/login" -r .             # Build deterministic RetrievalPlan
codegraph context "trace /api/v1/auth/login" -r .          # Compile token-budgeted ContextPacket
codegraph explain-context "trace /api/v1/auth/login" -r .  # ContextPacket with budget rejection reasons
codegraph memory list -r .                                 # Inspect repository-scoped notes
codegraph benchmark -r .                                   # Run deterministic benchmark suite

# MCP Server Subcommands
codegraph mcp serve .                                      # Start stdio MCP server (with parent/EOF lifecycle guard)
codegraph mcp serve . --profile full                       # Start stdio MCP server with all 56 tools
codegraph mcp stop                                         # Alias for codegraph stop
codegraph mcp kill                                         # Alias for codegraph stop (1s graceful timeout)
codegraph mcp doctor .                                     # End-to-end MCP startup & query check
codegraph mcp config-check .                               # Read-only MCP config validation
codegraph mcp capabilities                                 # Print machine-readable capability manifest
codegraph mcp rules --agent claude                         # Render agent rules for a specific agent
```

---

## 15. Honest Limitations

1. **Dynamic Metaprogramming & Reflection**: Calls constructed dynamically (`getattr(obj, dynamic_name)()`, `eval`, `exec`, `importlib.import_module(var)`, or runtime monkey-patching) cannot be proven statically. CodeGraph intentionally records these as `UNKNOWN` (`UNRESOLVED_REFERENCE` or `POSSIBLE_CALLS`) rather than inventing edges.
2. **Bounded Wildcard & Re-Export Chains**: To guarantee termination on pathological repositories with circular `from x import *` chains, resolution halts at `max_reexport_depth=16` (`max_wildcard_expansions=64`) and emits `UNKNOWN` with `reason="resolution_budget_exceeded"`.
3. **Python-First Depth vs. JS/TS Secondary Support**: Python receives deep AST, decorator, local dataflow (`LocalBindingResolver`), FastAPI/Flask/Django route, and SQLAlchemy/Django/SQLModel/Alembic analysis. JavaScript/TypeScript supports functions, classes, imports, calls, Express routes, and Prisma schemas, without full TypeScript compiler type evaluation.
4. **Opt-In Runtime Telemetry Scope**: Runtime edges (`RUNTIME_OBSERVED`) reflect only the trace files you explicitly ingest. Unobserved paths (`NOT_OBSERVED_AT_RUNTIME`) are not dead code.
5. **Very Large Pathological Repositories**: While `v2.1.7` reduces indexing time by `39.1%` and caps WAL size via chunked commits, initial cold indexing on repositories with tens of thousands of files still requires proportional CPU and disk I/O time (subsequent runs are incremental).

---

## 16. Documentation Map

- **Deep Agent Brain & 56-Tool Reference**: [`docs/agent-brain.md`](docs/agent-brain.md)
- **Compact Tool Capabilities Summary**: [`agent-rules/tool-capabilities-summary.md`](agent-rules/tool-capabilities-summary.md)
- **Detailed Multi-Tool Capability Comparison**: [`docs/tool-comparison.md`](docs/tool-comparison.md)
- **Antigravity Skill (`SKILL.md`)**: [`.agents/skills/codegraph/SKILL.md`](.agents/skills/codegraph/SKILL.md)
- **Agent Rule Packs (`Claude`, `Cursor`, `Antigravity`, `Codex`, `Gemini`, `Cline`)**: [`agent-rules/README.md`](agent-rules/README.md) & [`agent-rules/AGENTS.md`](agent-rules/AGENTS.md)
- **Engineering & Production Readiness**: [`docs/engineering/production-readiness.md`](docs/engineering/production-readiness.md)
- **Reproducible `v2.1.7` Benchmark Script & Artifacts**: [`benchmarks/run_v217_indexing_benchmark.py`](benchmarks/run_v217_indexing_benchmark.py), [`benchmarks/reports/v217_before_metrics.json`](benchmarks/reports/v217_before_metrics.json), [`benchmarks/reports/v217_after_metrics.json`](benchmarks/reports/v217_after_metrics.json)
- **Changelog**: [`CHANGELOG.md`](CHANGELOG.md)

---

## 17. Contributing & License

```bash
git clone https://github.com/raghurammrsd/CODE_GRAPH_MCP.git
cd CODE_GRAPH_MCP
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp,system]"

python3 -m ruff check .
python3 -m mypy src/
python3 -m pytest -q
```

Licensed under the [MIT License](LICENSE).
