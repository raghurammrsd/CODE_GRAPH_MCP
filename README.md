<p align="center">
  <img src="docs/assets/codegraph_logo.jpg" alt="CodeGraph MCP — Deep Deterministic Repository Intelligence for AI Coding Agents" width="500" />
</p>

<h1 align="center">⚡ CodeGraph MCP Engine (v2.2.1)</h1>

<p align="center">
  <strong>Stop AI Hallucinations. Supercharge Your AI Coding Agent with Deterministic Codebase Intelligence.</strong><br>
  <em>The high-performance Model Context Protocol (MCP) server for Claude, Cursor, Antigravity, Cline & Codex.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/codegraph-engine/2.2.1/"><img src="https://img.shields.io/badge/pypi-codegraph--engine%20v2.2.1-blue.svg" alt="PyPI: codegraph-engine v2.2.1" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB.svg" alt="Python 3.12 | 3.13" /></a>
  <a href="src/codegraph/mcp/server.py"><img src="https://img.shields.io/badge/MCP-14%20default%20%7C%2056%20full%20tools-2ea043.svg" alt="MCP Tools: 14 default | 56 full" /></a>
  <a href="tests/"><img src="https://img.shields.io/badge/pytest-861%20passed-brightgreen.svg" alt="Tests: 861 passed" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="Ruff: 0 errors" /></a>
  <a href="src/codegraph/"><img src="https://img.shields.io/badge/mypy-0%20issues%20(80%20files)-blue.svg" alt="Mypy: strict" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/codegraph-engine/2.2.1/"><strong>📦 Install via PyPI</strong></a> •
  <a href="#-why-ai-agents-need-codegraph-mcp"><strong>💡 Why CodeGraph?</strong></a> •
  <a href="#1-whats-new-in-v221"><strong>🚀 What's New in v2.2.1</strong></a> •
  <a href="#2-quickstart-30-second-setup"><strong>⚡ 30s Quickstart</strong></a> •
  <a href="#4-real-world-cli-outputs"><strong>📊 Real Outputs</strong></a> •
  <a href="#9-measured-performance-and-scaling-benchmarks"><strong>📈 Benchmarks</strong></a> •
  <a href="docs/agent-brain.md"><strong>📖 56-Tool Docs</strong></a>
</p>

---

### 🧠 The Problem Every AI Coding Agent Faces

When you ask Cursor, Claude Code, or Antigravity to debug or refactor a production repository, they **grep blindly**, read entire 2,000-line files, miss deep dependency injection trees, hallucinate database table schemas, and burn **80% of their context window** just trying to orient themselves.

### 🚀 What CodeGraph MCP Does

**CodeGraph MCP gives AI agents deterministic architectural vision.** Instead of guessing from messy regex matches, your agent queries CodeGraph for compiler-grade AST relationships, live route mounts, database table lineages, and real runtime traces—all computed locally in `< 5ms`.

```text
       ┌─────────────────────────────────────────────────────────────┐
       │                      YOUR AI CODING AGENT                   │
       │           (Claude Code  •  Cursor  •  Antigravity)          │
       └──────────────────────────────┬──────────────────────────────┘
                                      │  MCP Protocol (stdio / SSE)
                                      ▼
       ┌─────────────────────────────────────────────────────────────┐
       │                   ⚡ CODEGRAPH MCP ENGINE                   │
       ├──────────────────────────────┬──────────────────────────────┤
       │  🔍 AST Code Relationships   │  🛣️  Framework Route Maps   │
       │     (Callers, Callees, D.I.) │     (FastAPI, Django, Flask) │
       ├──────────────────────────────┼──────────────────────────────┤
       │  🗄️ Database Table Lineage   │  ⚡ Zero-Friction Telemetry  │
       │     (SQLAlchemy, Prisma, ORM)│     (HTTP hits, exceptions)  │
       └──────────────────────────────┴──────────────────────────────┘
                                      │
                                      ▼
                   100% Local • Sub-5ms • Zero Hallucination
```

#### 🔥 Why Developers & AI Agents Love It:
* 🎯 **0.0% Hallucinations**: Every relation is backed by strict static AST proof or explicit `UNKNOWN` flags.
* ⚡ **Lightning Fast (`< 5ms` freshness)**: Instant Git commit fast-path verifies repo freshness in single-digit milliseconds.
* 📉 **65% to 85% Token Reduction**: Agents inspect bounded 50-line semantic slices instead of dumping entire files into the prompt.
* 🛠️ **Zero Configuration Dev Tracing (`codegraph run`)**: Just prefix your dev server (`codegraph run npm run dev`) and watch live HTTP requests and errors link right into the static graph.
* 🔌 **1-Click Agent Setup (`codegraph install`)**: Automatically installs and configures Claude Code, Cursor, Antigravity, and Cline in seconds.

> **Supported Languages & Frameworks:** First-class **Python** (`FastAPI`, `Flask`, `Django`, `SQLAlchemy`, `Celery`, `pytest`) + **TypeScript / JavaScript** (`.ts`, `.tsx`, `.js`, `.jsx`) & **Express.js**.

![CodeGraph MCP v2.2.1 Architecture & Concurrency Pipeline](docs/assets/v22_concurrency_runtime_pipeline.svg)

---

## 1. What's New in v2.2.1

Version `2.2.1` solves the core operational, concurrency, context saturation, and developer friction bottlenecks in the Agent-MCP ecosystem:

| Bottleneck Solved | How It Worked Before | CodeGraph MCP v2.2.1 Solution | Impact |
| :--- | :--- | :--- | :--- |
| **Runtime Telemetry Cold Start** | User had to manually configure OpenTelemetry exporters or Pino JSON log streaming pipelines. | **`codegraph run <command>`**: Transparent 1-line wrapper (`codegraph run npm run dev`, `codegraph run uvicorn main:app`) injecting non-invasive hooks (`NODE_OPTIONS` / `PYTHONSTARTUP`). | **Zero code changes**; streams HTTP route hits, latencies, and exception traces directly into `.codegraph/runtime.sqlite3`. |
| **Database Concurrency (`database is locked`)** | Concurrent agent queries and background indexers could lock the SQLite database and raise crashes. | Enforced permanent **`WAL`** mode, **`synchronous = NORMAL`**, **`busy_timeout = 15000`** (15s), **`cache_size = -64000`** (64MB), and in-memory temporary storage. | Completely eliminates `database is locked` errors during parallel AI interrogation. |
| **Index Freshness Verification Latency** | Full-repository file hash comparisons took seconds before queries on large codebases. | **Instant Git Commit Fast Path**: Validates `git rev-parse HEAD` match + clean `git status --porcelain`. Falls back to `st_mtime < idx_at` stat checks. | Reduces freshness verification from seconds to **`< 5ms`** on clean repositories. |
| **Enterprise Monorepo Context Saturation** | Queries on 40,000-file monorepos could emit 50,000+ tokens for all routes or tables, blowing LLM context windows. | **Bounded Pagination**: Added `limit`, `offset`, `total_count`, and `has_more` to `list_routes` and `get_db_schema`. Added `--limit` / `--offset` to CLI `routes`. | Bounded context token consumption with strict pagination safeguards. |
| **Client Disconnection (`exit status 0xffffffff`)** | Stdio MCP pipe termination caused permanent crash loops in agent IDEs on server updates or restarts. | **Multi-Transport Resiliency**: Added **`--transport sse`** (`--port`, `--host`) to `codegraph serve` and `codegraph mcp serve`. | Enables hot-reconnecting SSE HTTP transport alongside stdio for robust IDE bridges. |

---

## 2. Quickstart (30-Second Setup)

### Step 1: Install the Package

```bash
pip install "codegraph-engine[mcp]"
```

### Step 2: Configure Your AI Coding Agents (`codegraph install`)

CodeGraph MCP includes an interactive, idempotent onboarding installer ([`src/codegraph/installer.py`](src/codegraph/installer.py)) that detects installed AI coding agents (**Claude Code**, **Cursor**, **Antigravity**, **Codex CLI**, **Gemini CLI**, and **Cline**), configures `mcpServers.codegraph`, installs marker-bounded routing instructions (`<!-- CODEGRAPH:START -->` … `<!-- CODEGRAPH:END -->`), and verifies server health:

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

> **Dynamic Index Hot-Reloading:** If your AI coding agent launches `codegraph mcp serve` before you run `codegraph init`, you do **not** need to restart your IDE or MCP session. As soon as `codegraph init` or `codegraph index` creates or updates `.codegraph.sqlite3`, the running MCP server automatically detects the database on the next tool call and refreshes its in-memory graph cache (`get_repository_status(reload=True, reindex=True)` can also be invoked directly by the agent).

### Step 4: Run With Zero-Friction Telemetry (`codegraph run`)

Wrap your development server transparently to stream real HTTP routes, durations, and uncaught exceptions directly into CodeGraph MCP:

```bash
# Node / Express / Next.js
codegraph run npm run dev

# Python / FastAPI / Uvicorn
codegraph run uvicorn main:app --reload

# Django
codegraph run python manage.py runserver
```

---

## 3. Core Architecture & Mental Model

```mermaid
flowchart TD
    A["AI Coding Agent (Claude, Cursor, Antigravity, Cline)"] --> B["CodeGraph MCP Server (stdio or SSE)"]
    B --> C["Deterministic Repository Intelligence"]

    C --> D["AST Semantic Graph (Callers, Callees, References, DI)"]
    C --> E["Literal & Regex Text Search (search_code)"]
    C --> F["Bounded Source Inspection (get_file)"]
    C --> G["Database Intelligence (Tables, ORM, Migrations, R/W)"]
    C --> H["Zero-Friction Runtime Telemetry (codegraph run)"]

    D --> I["Structured Evidence + Epistemic Labels"]
    E --> I
    F --> I
    G --> I
    H --> I

    I --> J["Context Optimization & Secret Redaction"]
    J --> A
```

### Routing Each Question to the Right Primitive

```text
STRUCTURAL     →  Graph tools (find_symbol, find_callers, find_callees, find_references, find_routes)
TEXTUAL        →  search_code (literal/regex search across Python, HTML/Jinja, JS/TS, CSS, YAML/JSON, SQL)
SOURCE         →  get_file (bounded start_line..end_line source inspection with truncation metadata)
GRAPH          →  Trace tools (trace_path, trace_flow, analyze_impact, get_git_impact)
DATABASE       →  Database tools (get_db_schema, find_db_tables, find_db_readers, find_db_writers, get_db_impact)
RUNTIME        →  Runtime tools (codegraph run, ingest_runtime_traces, get_runtime_trace, reconcile_static_runtime)
EDITING        →  Native agent / IDE editing tools
```

---

## 4. Real-World CLI Outputs

Below are exact, verifiable outputs produced by CodeGraph MCP v2.2.1:

### 1. Zero-Friction Runtime Interceptor (`codegraph run`)

```bash
$ codegraph run python3 -c "print('>> Dev server active on port 8000')"
>> Dev server active on port 8000
```
*HTTP requests, status codes, and exceptions are automatically streamed to `.codegraph/runtime.sqlite3` with child exit codes preserved.*

### 2. Instant Index Freshness Check (`codegraph status`)

```bash
$ codegraph status .
{
  "repository": "/Users/raghuram/Documents/ChatGPT/MCP",
  "freshness": "FRESH",
  "freshness_detail": "Index matches current repository state.",
  "files": 190,
  "chunks": 1965,
  "symbols": 1947,
  "framework_routes": 0,
  "graph_edges": 12712,
  "resource_profile": "BALANCED",
  "pressure_level": "NORMAL",
  "activity_mode": "IDLE",
  "estimated_memory_mb": 43.23,
  "modified_files": [],
  "deleted_files": [],
  "parse_failed_files": []
}
```
*Validated in `< 5ms` via the Git commit diff fast path.*

### 3. Incremental Indexing with 16-Phase Telemetry (`codegraph index --verbose`)

```bash
$ codegraph index --verbose
Phase: Repository Scan
190 / 190 files | 100% | elapsed: 0.09s | rate: 128,203 files/min | memory: 42 MB
Phase: Post-Processing
190 / 190 files | 100% | elapsed: 0.62s | rate: 18,273 files/min | memory: 67 MB
Phase: Symbol Resolution
190 / 190 files | 100% | elapsed: 0.80s | rate: 14,311 files/min | memory: 91 MB
Phase: Relationship Resolution
190 / 190 files | 100% | elapsed: 1.49s | rate: 7,648 files/min | memory: 116 MB
Phase: Database Analysis
190 / 190 files | 100% | elapsed: 1.77s | rate: 6,424 files/min | memory: 120 MB
Phase: Final Commit & Checkpoint
190 / 190 files | 100% | elapsed: 2.59s | rate: 4,396 files/min | memory: 141 MB

Summary: elapsed=2.595s peak_rss=141.0MB max_wal=9.44MB final_wal=0.00MB commits=15 checkpoints=15
  [repository_scan] 88.1ms files=190 items=190 writes=0
  [ast_parsing] 154.7ms files=13 items=3322 writes=0
  [database_analysis] 283.9ms files=13 items=1631 writes=0
  [symbol_resolution] 52.5ms files=190 items=5854 writes=0
  [relationship_resolution] 694.0ms files=190 items=32806 writes=0
  [sqlite_writes] 1146.4ms files=13 items=50206 writes=50208
scanned=190 indexed=13 unchanged=177 removed=0
```

### 4. Bounded Monorepo Route Discovery (`codegraph routes --limit 3`)

```bash
$ codegraph routes --limit 3
Found 3 route(s):
  [GET] /api/v1/health -> health_check (src/app/api.py:14) [fastapi]
  [POST] /api/v1/orders -> create_order (src/app/orders.py:42) [fastapi]
  [GET] /api/v1/users/{id} -> get_user (src/app/users.py:88) [fastapi]
```

### 5. Safe Background Process Termination (`codegraph stop --json`)

```bash
$ codegraph stop --json
{
  "status": "ok",
  "stopped_count": 0,
  "stale_cleaned_count": 0,
  "processes": []
}
```

---

## 5. AI/ML & Backend Architecture Examples

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

**What CodeGraph MCP structurally proves**:
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

**What CodeGraph MCP structurally proves**:
- `find_callees(symbol="TrainingPipeline.run")` enumerates every stage of the pipeline with exact file and line ranges.
- `find_tests(symbol="Evaluator.compute_metrics")` locates the unit and regression tests covering metric calculation.
- When a transform or model class is dynamically instantiated from a YAML string (`getattr(models, cfg.arch)`), CodeGraph MCP explicitly records `POSSIBLE_CALLS` (`POSSIBLE`) or `UNRESOLVED_REFERENCE` (`UNKNOWN`) rather than fabricating a false static call edge.

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

**What CodeGraph MCP structurally proves**:
- Tracks decorator and call-based registrations (`@tool_registry.register("search_orders")`) via `REGISTERS` and `REGISTERED_HANDLER` edges.
- Tracks environment variable dependencies (`os.getenv("OPENAI_API_KEY")`) as `READS_ENV` edges with the variable name only—never indexing or exposing secret values.

---

## 6. Database Intelligence

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

## 7. Zero-Friction Runtime Intelligence & Static Reconciliation

Static analysis proves what **can** happen structurally; runtime telemetry records what **was observed** during execution. CodeGraph MCP v2.2.1 brings them together transparently:

```text
STATIC GRAPH (AST + Framework + Dataflow + DB)
                   +
RUNTIME OBSERVATION (codegraph run / OTel JSON / JSONL / SQL Logs)
                   ↓
       reconcile_static_runtime()
```

### Reconciliation Outcomes ([`ReconciliationStatus`](src/codegraph/runtime/models.py))

| Reconciliation Status | Static Graph | Runtime Trace | Meaning |
| :--- | :---: | :---: | :--- |
| **`CONFIRMED_RUNTIME_PATH`** | Present | Observed | Static relationship is structurally proven **and** observed executing in ingested traces. |
| **`NOT_OBSERVED_AT_RUNTIME`** | Present | Not observed | Statically valid edge was not exercised in the recorded trace sample. |
| **`RUNTIME_ONLY_OBSERVED`** | Dynamic / `UNKNOWN` | Observed | Executed at runtime (e.g., plugin hook, `getattr`, dynamic SQL) where static analysis was `UNKNOWN`. |
| **`STATIC_RUNTIME_CONFLICT`** | Target A | Target B | Runtime execution dispatched to a different target than static resolution (e.g., dependency override). |

### Epistemic Rules for Runtime Evidence
1. **Runtime Telemetry Is Non-Invasive**: `codegraph run` uses standard environment variable hooks (`NODE_OPTIONS`, `PYTHONSTARTUP`). You never modify application source code.
2. **`NOT_OBSERVED_AT_RUNTIME` Does Not Mean Dead Code**: It only indicates that the code path was not triggered during the recorded trace window (such as an error branch or periodic batch job).
3. **Runtime Observations Never Overwrite Static Proof**: Runtime spans are recorded with `evidence_class="RUNTIME_OBSERVED"` and strictly distinguished from `AST_VERIFIED` and `FRAMEWORK_VERIFIED` static edges.

---

## 8. Epistemic Trust & Evidence Contract

CodeGraph MCP enforces a fail-closed evidence contract ([`src/codegraph/evidence_contract.py`](src/codegraph/evidence_contract.py)) across all **51 canonical relationship types** and **9 evidence classes**. CodeGraph MCP prefers **explicit uncertainty** over **fabricated certainty**:

```text
Dynamically resolved target (getattr(handler, action_name)())
      ↓
UNRESOLVED_REFERENCE / POSSIBLE_CALLS (status = "UNKNOWN" | "POSSIBLE")
(Never fabricated into a verified CALLS edge)
```

| Epistemic Status | Allowed Evidence Classes | What It Means |
| :--- | :--- | :--- |
| **`FACT`** | `AST_VERIFIED`, `STATIC_VERIFIED`, `FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED` | Proven directly from syntax tree, framework decorator/router semantics, or conservative local dataflow. |
| **`RUNTIME_OBSERVED`** | `RUNTIME_OBSERVED` | Observed in traces captured by `codegraph run` or ingested OTel/JSONL/SQL logs (`hit_count`, `duration_ms`). |
| **`POSSIBLE`** | `POSSIBLE` | Plausible candidate relationship (`POSSIBLE_CALLS`, `POSSIBLE_TABLE`) requiring source inspection before mutation. |
| **`AMBIGUOUS`** | `AMBIGUOUS` | Multiple symbols or database tables match the bare identifier across modules or dialects; returns sorted `candidates`. |
| **`UNKNOWN`** | `UNKNOWN`, `RUNTIME_UNOBSERVED` | Target cannot be statically proven (dynamic reflection, external dependency, or `reason="resolution_budget_exceeded"`). |
| **`CONFLICT`** | Static vs. Runtime / Multi-Source | Static analysis and runtime observation (or competing definitions) disagree. |

---

## 9. Measured Performance and Scaling Benchmarks

### 4-Tier Scaling Summary (`54` → `2,504` Files)

Recorded using [`benchmarks/run_v217_indexing_benchmark.py`](benchmarks/run_v217_indexing_benchmark.py) on macOS `arm64`, Python `3.13` with permanent SQLite WAL concurrency:

| Workload Tier | Files | Symbols | Graph Edges | Baseline Total | v2.2.1 Total | Improvement | Peak RSS | Peak WAL | Final WAL |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: |
| **Small** | `54` | `115` | `398` | `0.527 s` | `0.325 s` | **38.3% faster (`1.62x`)** | `46.25 MB` | `1.544 MB` | `0.0 MB` |
| **Medium** | `304` | `615` | `2,248` | `2.564 s` | `1.613 s` | **37.1% faster (`1.59x`)** | `62.67 MB` | `4.098 MB` | `0.0 MB` |
| **Large** | `1,004` | `2,015` | `7,428` | `8.730 s` | `5.296 s` | **39.3% faster (`1.65x`)** | `103.44 MB` | `5.033 MB` | `0.0 MB` |
| **Stress** | `2,504` | `5,015` | `18,528` | `21.983 s` | `13.395 s` | **39.1% faster (`1.64x`)** | `180.89 MB` | `6.628 MB` | `0.0 MB` |

### Stress Tier (`2,504` Files) Phase Breakdown

| Phase / Metric | Legacy Baseline | v2.2.1 Release | Measured Improvement |
| :--- | ---: | ---: | :--- |
| **Total Indexing Time** | `21.983 s` | `13.395 s` | **39.1% faster (`1.64x`)** |
| **Database Intelligence Pass** | `4.818 s` | `0.832 s` | **82.7% faster (`5.79x`)** |
| **Post-Processing Phase** | `13.770 s` | `7.056 s` | **48.8% faster (`1.95x`)** |
| **Symbol Resolution Phase** | `3.133 s` | `1.107 s` | **64.7% faster (`2.83x`)** |
| **Single-File Incremental Update** | `4.408 s` | `2.063 s` | **53.2% faster (`2.14x`)** |
| **Throughput (`files/sec`)** | `113.9 files/s` | `186.9 files/s` | **`+64.1%` throughput** |
| **Peak SQLite WAL Size** | `46.980 MB` | `6.628 MB` | **85.9% reduction (`7.09x` smaller)** |
| **Final SQLite WAL Size** | `0.000 MB` | `0.000 MB` | **100% reclaimed (`TRUNCATE`)** |

![CodeGraph MCP — Measured Large-Repository Scaling](docs/assets/large_repo_scaling.svg)

### 50-Task Production Benchmark Results (`v2.2.1`)

Evaluated across 50 production tasks and 10 categories via [`benchmarks/run_v21_eval.py`](benchmarks/run_v21_eval.py):

| Production Benchmark Metric | Measured Result | Production Target | Status |
| :--- | :---: | :---: | :---: |
| **Task Coverage** | **88.0%** | $\ge 80.0\%$ | **PASS** |
| **Symbol Recall** | **61.9%** | $\ge 50.0\%$ | **PASS** |
| **FACT Correctness** | **100.0%** | $\ge 98.0\%$ | **PASS** |
| **Unsupported Claim Rate (Hallucinations)** | **0.0%** | $\le 1.0\%$ | **PASS** |
| **UNKNOWN Correctness** | **98.0%** | $\ge 95.0\%$ | **PASS** |
| **AMBIGUITY Correctness** | **100.0%** | $\ge 90.0\%$ | **PASS** |
| **Average Context Payload** | **510 tokens** | $\le 1,000$ tokens | **PASS** |
| **Average Context Latency** | **40.52 ms** | $\le 100$ ms | **PASS** |
| **Token Reduction vs Full-File Extraction** | **41.8%** | $\ge 35.0\%$ | **PASS** |

### 32-Task A/B Exploration Evaluation ([`src/codegraph/tool_selection_eval.py`](src/codegraph/tool_selection_eval.py))

| Metric (32-Task Evaluation Suite) | Mode A (Unassisted Grep & File Reads) | Mode B (CodeGraph MCP) | Measured Improvement |
| :--- | ---: | ---: | :--- |
| **Total Tool Calls (32 Tasks)** | `164 calls` (`~5.1 / task`) | `71 calls` (`~2.2 / task`) | **`-56.7% fewer tool calls`** |
| **Direct Full-File Reads** | `161 full-file reads` | `7 bounded slice reads` | **`-95.7% fewer file reads`** |
| **Context Tokens per Task** | `3,000 – 12,000+ tokens` | `~510 tokens` avg | **`65.0% – 85.6% token reduction`** |
| **Query Latency (`p50`)** | Hundreds of ms (multi-step `grep`) | `20.0 ms` cold / `0.67 ms` warm | **Sub-20ms indexed lookup** |
| **First-Tool Selection Accuracy** | `9.38%` | `100.0%` | **`+90.62%`** |
| **Unsupported Claims (Hallucinated Edges)** | `11 (34.38%)` | `0 (0.00%)` | **`0% unsupported claims`** |
| **Task Accuracy** | `59.84%` | `100.0%` | **`+40.16%`** |

![CodeGraph MCP — Measured Context & Exploration Efficiency](docs/assets/performance_comparison.svg)

---

## 10. Where CodeGraph MCP Fits

CodeGraph MCP works **alongside** your editor's language server (LSP), `ripgrep`, and structural AST tools:

Legend: `✓` supported • `◐` partial / workflow-dependent • `—` not supported

| Capability | CodeGraph MCP (`v2.2.1`) | Editor LSP | Structural AST (`ast-grep`) | Lexical Search (`ripgrep`) | Remote Code Search (`Sourcegraph`) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **100% Local-First & Offline Operation** | ✓ | ✓ | ✓ | ✓ | — |
| **Native MCP Server for AI Agents** | ✓ (14 default / 56 full) | — | ◐ | — | ✓ |
| **Multi-Transport Support (stdio + SSE HTTP)** | ✓ | — | — | — | ◐ |
| **Zero-Friction Runtime Interceptor (`codegraph run`)** | ✓ | — | — | — | — |
| **Semantic Symbol Graph (Callers / Callees)** | ✓ | ◐ (Position-based) | ◐ (Pattern-based) | — | ✓ (SCIP) |
| **Framework Route, Mount & DI Graph** | ✓ (`FastAPI`/`Flask`/`Django`/`Express`) | — | ◐ (Custom rules) | — | — |
| **Database Schema, ORM, Migration & Table R/W** | ✓ (11 DB tools) | — | — | — | — |
| **Opt-In Runtime Ingestion & Reconciliation** | ✓ (OTel / JSONL / SQL) | — | — | — | — |
| **Explicit Epistemic States (`FACT`/`UNKNOWN`)** | ✓ | — | — | — | — |
| **Literal Text Search Across HTML/JS/CSS/Config** | ✓ (`search_code`) | — | — | ✓ | ✓ |
| **Interactive Editor Hover & Diagnostics** | — | ✓ | ✓ (Lint/Rewrite) | — | — |

![Repository Retrieval Approaches — Capability Comparison](docs/assets/capability_heatmap.svg)

---

## 11. Security, Privacy & Redaction Boundaries

CodeGraph MCP runs **100% locally** (`stdio` / `sse` MCP + local `.codegraph.sqlite3`), never executes repository code during indexing, and enforces strict file-access and redaction boundaries ([`src/codegraph/security/paths.py`](src/codegraph/security/paths.py), [`src/codegraph/security/redaction.py`](src/codegraph/security/redaction.py)):

| Security Boundary | Enforcement Mode | Exact Behavior |
| :--- | :---: | :--- |
| **Sensitive Files** (`.env`, `*.pem`, `*.key`, `*.crt`, `id_rsa*`, `kubeconfig*`, `.npmrc`, `.pypirc`, `*secret*.json`) | **`BLOCKED`** | Excluded from indexing and FTS; direct inspection via `get_file` or `read_file` is rejected with `SENSITIVE_FILE_ACCESS_DENIED`. |
| **Path Traversal & Symlinks** (`../`, `%2e%2e`, null bytes, external symlinks) | **`BLOCKED`** | Canonical path check in `resolve_within_repo()` raises `SecurityError(ErrorCode.PATH_OUTSIDE_REPOSITORY)`. |
| **Binary Files** (`.pyc`, `.so`, `.dylib`, `.dll`, `.exe`, images, archives, PDFs) | **`BLOCKED`** | Classified as `BINARY` and skipped during indexing and text search. |
| **Environment Variable Reads in Code** (`os.getenv("DATABASE_URL")`) | **Metadata Only** | Records `READS_ENV` with the **variable name only**; never reads `.env` or runtime environment values. |
| **Database Connection Strings** (`postgresql://user:pass@host:5432/prod`) | **`REDACTED`** | Preserves dialect and database name while sanitizing credentials to `postgresql://[REDACTED]@[REDACTED]/prod`. |
| **API Keys, Bearer Tokens, JWTs & Private Keys** (`sk-...`, `ghp_...`, `AKIA...`) | **`REDACTED`** | Replaced with `[REDACTED_SECRET]` or `[REDACTED_PRIVATE_KEY]` before indexing, search, or MCP output. |
| **Runtime HTTP Headers & SQL Literals** (`authorization`, `cookie`, `WHERE password = '...'`) | **`REDACTED`** | Sensitive runtime keys and SQL literals are scrubbed (`[REDACTED]` / `?`) during `ingest_runtime_traces`. |

Run `codegraph privacy .` at any time to audit the local database and verify that no sensitive files or unredacted secrets are stored.

---

## 12. MCP Tooling & Profiles (14 Default / 56 Full)

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

---

## 13. Complete CLI Reference

Verified against [`src/codegraph/cli.py`](src/codegraph/cli.py):

```bash
# Agent Onboarding & Uninstall
codegraph install                                          # Interactive agent detection & setup
codegraph install --yes --target auto --location local     # Non-interactive local setup
codegraph install --print-config claude                    # Print MCP JSON + rules for an agent
codegraph install --dry-run                                # Preview planned file changes
codegraph uninstall --yes                                  # Remove CodeGraph MCP agent integrations

# Zero-Friction Runtime Interceptor (v2.2.1)
codegraph run npm run dev                                  # Wrap Node/Express/Next.js dev server
codegraph run uvicorn main:app --reload                    # Wrap FastAPI/ASGI dev server
codegraph run python manage.py runserver                   # Wrap Django dev server
codegraph run --sample-rate 0.5 npm test                   # Sample 50% of captured traces

# Repository Initialization & Indexing
codegraph init .                                           # Initialize and index repository
codegraph index . --verbose                                # Incremental index with 16-phase telemetry
codegraph index . --json                                   # Output structured JSON phase telemetry
codegraph uninit --dry-run                                 # Preview removal of .codegraph.sqlite3

# Process Lifecycle & Upgrade Lock Safety
codegraph stop                                             # Safely stop CodeGraph MCP server for current repo
codegraph stop --all                                       # Stop all CodeGraph-owned MCP processes across repos
codegraph doctor --processes                               # Inspect active MCP processes & parent PIDs

# Health, Integrity & Freshness Diagnostics
codegraph status .                                         # Show index freshness (sub-50ms Git fast path)
codegraph doctor . --database --processes                  # Verify SQLite integrity, FKs, FTS, and memory
codegraph privacy .                                        # Verify zero sensitive files indexed
codegraph version                                          # Print CodeGraph MCP version (2.2.1)

# Code, Graph, Routes & Context Interrogation
codegraph search "authenticate" -r .                       # Search indexed symbols and text chunks
codegraph symbols src/codegraph/cli.py -r .                # List extracted symbols in a file
codegraph get-symbol Indexer -r .                          # Get AST details for a symbol
codegraph resolve-symbol resolve_Repository -r .           # Ground symbol or return candidates
codegraph trace Indexer -d 2 -r .                          # Trace callers and callees up to depth 2
codegraph routes -r . --limit 25 --offset 0                # List routes with bounded pagination
codegraph architecture -r .                                # Summarize repository architecture
codegraph context "trace /api/v1/auth/login" -r .          # Compile token-budgeted ContextPacket

# MCP Server Subcommands
codegraph serve .                                          # Start stdio MCP server (14 default tools)
codegraph serve . --profile full                           # Start stdio MCP server with all 56 tools
codegraph serve . --transport sse --port 8765              # Start SSE HTTP server on port 8765
codegraph mcp serve . --transport sse                      # Alias for SSE MCP server
codegraph mcp stop                                         # Stop active MCP processes
```

---

## 14. Documentation Map

- **Deep Agent Brain & 56-Tool Reference**: [`docs/agent-brain.md`](docs/agent-brain.md)
- **Compact Tool Capabilities Summary**: [`agent-rules/tool-capabilities-summary.md`](agent-rules/tool-capabilities-summary.md)
- **Detailed Multi-Tool Capability Comparison**: [`docs/tool-comparison.md`](docs/tool-comparison.md)
- **Antigravity Skill (`SKILL.md`)**: [`.agents/skills/codegraph/SKILL.md`](.agents/skills/codegraph/SKILL.md)
- **Agent Rule Packs (`Claude`, `Cursor`, `Antigravity`, `Codex`, `Gemini`, `Cline`)**: [`agent-rules/README.md`](agent-rules/README.md) & [`agent-rules/AGENTS.md`](agent-rules/AGENTS.md)
- **Engineering & Production Readiness**: [`docs/engineering/production-readiness.md`](docs/engineering/production-readiness.md)
- **Reproducible Scaling Benchmark Script**: [`benchmarks/run_v217_indexing_benchmark.py`](benchmarks/run_v217_indexing_benchmark.py)
- **Changelog**: [`CHANGELOG.md`](CHANGELOG.md)

---

## 15. Contributing & License

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
