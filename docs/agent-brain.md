# CodeGraph Deep Agent Brain & Operating Manual (v2.2.1)

> **Canonical Reference (`docs/agent-brain.md`)**
> Generated deterministically from `src/codegraph/agent_capabilities.py`, `src/codegraph/evidence_contract.py`, `src/codegraph/retrieval_policy.py`, and `src/codegraph/mcp/server.py`.
> Package: `codegraph-engine` (`v2.2.1`) | CLI: `codegraph` | MCP Command: `codegraph mcp serve`

---

## 1. CodeGraph Mental Model

CodeGraph is a **deterministic, local-first repository intelligence engine** exposed over the Model Context Protocol (MCP).

```
    understand architecture  ->  get_architecture / get_context
               |
        find exact text/file ->  find_symbol / search_code / find_routes
               |
        open targeted source ->  get_file(path, start_line, end_line)
               |
        reason with evidence ->  find_callers / find_callees / trace_path / find_tests
               |
        edit the repository  ->  IDE / editor write tools
```

CodeGraph parses source files into an SQLite-backed symbol, relationship, route, dependency-injection (DI), registry/dispatch, package-boundary, and test-coverage graph (Schema v8), paired with a deterministic literal/text search layer (`search_code`) and bounded source inspection (`get_file`). Every fact returned by CodeGraph carries explicit source coordinates (`file`, `start_line`, `end_line`), a canonical relationship type, and an epistemic `evidence_class`.

---

## 2. Agent Responsibility vs CodeGraph Responsibility

| Dimension | AI Coding Agent Responsibility | CodeGraph Engine Responsibility |
| :--- | :--- | :--- |
| **Intent & Planning** | Understands developer intent, classifies the task category, and selects the smallest sufficient tool via `ROUTING_MANIFEST`. | Normalizes task targets (`TargetResolver`), expands ambiguous generic names (`QueryExpansion`), and applies intent-specific `RetrievalPolicy`. |
| **Interrogation** | Calls targeted MCP tools (`find_symbol`, `search_code`, `find_callers`, `find_callees`, `trace_path`, `find_routes`, `find_tests`, `get_file`, `get_context`, etc.). | Queries AST, framework, dataflow indices, and non-binary text files deterministically in sub-second warm latency. |
| **Epistemic Honesty** | Preserves `UNKNOWN`, `POSSIBLE`, and `AMBIGUOUS` states; never invents graph edges or fabricates coverage from `search_code` text matches. | Enforces `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX` via `RelationshipRecord` fail-closed validation and keeps text search strictly separate from semantic graph edges. |
| **Source Code Inspection** | Uses `get_file(path, start_line, end_line, max_lines)` (or `read_file`) on narrow line ranges when exact implementation statements are needed. | Identifies the exact files and line spans where symbols, calls, routes, DI bindings, and literal strings live. |
| **Code Modification** | Synthesizes the final explanation or edits source files safely. | Never executes repository code, never mutates user source files, and blocks sensitive file reads. |

---

## 3. Repository Intelligence Model

CodeGraph models a repository across eight deterministic intelligence layers:

1. **Epistemic Symbol & Relationship Graph**: Canonical symbols (`canonical_id`, `qualified_name`, `kind`, `signature`) connected by typed `RelationshipRecord` edges.
2. **Route & Mount Composition**: HTTP/RPC routes (`HANDLED_BY`, `ROUTE_HANDLER`, `ROUTES_TO`) and nested router prefix mounts (`MOUNTS`) across FastAPI, Flask, Django, Express, and NestJS.
3. **Conservative Dataflow & Binding**: Intra-file and constructor attribute bindings (`BINDS_TO`, `RESOLVES_TO`, `ALIASED_TO`).
4. **Registry, Dispatch & Event Intelligence**: Explicit separation of registration (`REGISTERS`, `REGISTERED_HANDLER`), dispatch (`DISPATCHES_TO`), and event subscription (`EVENT_LISTENER`).
5. **Semantic Decorators, Tasks & Commands**: Background tasks (`TASK_HANDLER`) and CLI commands (`COMMAND_HANDLER`).
6. **Dependency Injection & Configuration**: FastAPI `Depends`, `Annotated`, container bindings, and provider factories (`INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, `DI_CYCLE`).
7. **Test Intelligence & Deterministic Change Impact**: Static test links (`TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`) and Git diff blast radius (`get_git_impact`, `analyze_impact`).
8. **Monorepo, Workspace & Artifact Intelligence**: Manifest-backed workspace packages (`DEPENDS_ON_PACKAGE`, `CROSS_PACKAGE_IMPORT`, `PACKAGE_IMPORTS`, `CONTAINS_PACKAGE`) and artifact suppression (`SOURCE` vs `GENERATED`/`BUNDLE`/`MINIFIED`/`VENDOR`).

---

## 4. Evidence Model

CodeGraph enforces nine canonical `evidence_class` values defined in `ALLOWED_EVIDENCE_CLASSES`:

- **`AST_VERIFIED`**: Supported directly by static syntax/AST evidence (e.g., function definition, direct call expression, explicit import statement).
- **`STATIC_VERIFIED`**: Supported directly by static SQL DDL/DML parsing, schema files, or migration scripts (`CREATE TABLE`, `INSERT INTO`, `op.create_table`).
- **`FRAMEWORK_VERIFIED`**: Proven by recognized deterministic framework semantics (e.g., `@router.post('/login')`, `app.include_router(..., prefix='/api/v1')`, `Depends(get_db)`, SQLAlchemy/Django/SQLModel/Prisma ORM mappings, `@celery.task`).
- **`DATAFLOW_VERIFIED`**: Proven by conservative deterministic data-flow analysis (e.g., `self.repo = repo` in `__init__` followed by `self.repo.find_by_email()`, factory return binding `svc = get_inventory_service()` -> `svc.place_order()`, or static dictionary registry assignment `HANDLERS['create'] = handle_create`).
- **`RUNTIME_OBSERVED`**: Observed in an ingested runtime trace (OpenTelemetry JSON, JSONL runtime events, or SQL query logs) with `observation_count`, `first_seen`, `last_seen`, and `runtime_generation`. Never converted into static `AST_VERIFIED` proof.
- **`RUNTIME_UNOBSERVED`**: Static relationship was not observed in the ingested runtime trace sample (`NOT_OBSERVED_AT_RUNTIME`). Never proves that the path cannot execute.
- **`POSSIBLE`**: Plausible static candidate that is not statically guaranteed (e.g., conditional registration inside an `if` branch, dynamic SQL table interpolation `POSSIBLE_TABLE`, multiple interface implementations, or heuristic match).
- **`UNKNOWN`**: Static analysis could not establish the target (e.g., `getattr(module, dynamic_name)()`, `eval()`, opaque SQL string `UNKNOWN_TABLE`, or unresolvable database dialect/schema).
- **`AMBIGUOUS`**: Multiple candidate symbols or database tables match the target name across modules or schemas; requires disambiguation via `alternatives`.

### Non-Negotiable Epistemic Rules
1. **`UNKNOWN != no relationship`**: `UNKNOWN` means static analysis could not prove the target—never claim "there is no relationship" from `UNKNOWN`.
2. **`POSSIBLE != verified`**: Treat `POSSIBLE` as a lead requiring a targeted `get_file` / `read_file` check before stating as fact.
3. **`AMBIGUOUS != choose first candidate`**: When multiple symbols match, inspect `alternatives` and disambiguate by module/package/caller context.
4. **Static vs Runtime Separation**: Never convert `RUNTIME_OBSERVED` into static `AST_VERIFIED` proof, never convert static inference into runtime fact, and never treat `NOT_OBSERVED_AT_RUNTIME` (`RUNTIME_UNOBSERVED`) as proof of dead code.
5. **Fail-Closed Contract**: `CALLS` and `CALLED_BY` can only be `AST_VERIFIED`, `DATAFLOW_VERIFIED`, or `RUNTIME_OBSERVED`. Uncertain call edges must use `POSSIBLE_CALLS` with `POSSIBLE` or `UNKNOWN`.
6. **Text Search != Semantic Edge**: `search_code` text matches across HTML, Jinja, JS, CSS, or config files NEVER create `CALLS`, `REFERENCES`, `IMPORTS`, `ROUTES`, or `DEPENDS_ON_PACKAGE` graph edges.

---

## 5. Relationship Model

CodeGraph enforces the 56 canonical relationship types in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX`. It **never** collapses framework routing, database operations, registry registration, or dependency injection into generic `CALLS` or `DEPENDS_ON`.

#### `ALIASED_TO`
- **Meaning**: Symbol or import is assigned an explicit alias (`import X as Y`, `HandlerAlias = RealHandler`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Alias identifier
- **Typical Target**: Original symbol
- **What It Proves**: Static alias assignment in module or function scope.
- **What It Does Not Prove**: Does not prove runtime reassignment if mutated dynamically.
- **Common Tool**: `resolve_symbol / get_references`
- **Example**: `LoginHandler` -> `ALIASED_TO` (`AST_VERIFIED`) -> `login_endpoint`

#### `BINDS_TO`
- **Meaning**: Local variable, attribute (`self.repo`), or parameter annotation binds to a concrete type or symbol.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Variable or attribute (`self.repo`)
- **Typical Target**: Bound class or symbol (`UserRepository`)
- **What It Proves**: Conservative intra-file or constructor dataflow binding.
- **What It Does Not Prove**: Does not prove external runtime monkey-patching of the attribute.
- **Common Tool**: `get_context / get_references`
- **Example**: `AuthService.self.repo` -> `BINDS_TO` (`DATAFLOW_VERIFIED`) -> `UserRepository`

#### `CALLED_BY`
- **Meaning**: Inverse of a verified `CALLS` edge (target is invoked by source caller).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `RUNTIME_OBSERVED`
- **Typical Source**: Callee symbol
- **Typical Target**: Caller symbol
- **What It Proves**: The target symbol contains a verified call site invoking the source symbol.
- **What It Does Not Prove**: Does not prove runtime execution frequency.
- **Common Tool**: `get_callers / analyze_impact`
- **Example**: `verify_password` -> `CALLED_BY` (`AST_VERIFIED`) -> `AuthService.authenticate`

#### `CALLS`
- **Meaning**: Direct executable function, method, or constructor invocation proven by AST or conservative dataflow.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `RUNTIME_OBSERVED`
- **Typical Source**: Function, method, or route handler symbol
- **Typical Target**: Callee function, method, or class constructor
- **What It Proves**: A call expression in the source symbol statically targets the callee symbol.
- **What It Does Not Prove**: Does not prove that a conditional runtime branch is taken on a specific input.
- **Common Tool**: `get_callers / get_callees / trace_path`
- **Example**: `AuthService.authenticate` -> `CALLS` (`AST_VERIFIED`) -> `verify_password`

#### `COMMAND_HANDLER`
- **Meaning**: CLI or command-bus decorator (`@app.command`, `@click.command`) binds a CLI command to its handler.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: CLI application or command group
- **Typical Target**: Command handler function
- **What It Proves**: CLI command registration in Typer, Click, or argparse.
- **What It Does Not Prove**: Does not prove runtime CLI flag values.
- **Common Tool**: `get_context / get_references / trace_path`
- **Example**: `cli_app.command('migrate')` -> `COMMAND_HANDLER` (`FRAMEWORK_VERIFIED`) -> `run_migrations`

#### `CONFIGURES`
- **Meaning**: Settings object, environment config, or module initializer configures a service, router, or container.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Config class or initializer (`Settings`, `configure_di`)
- **Typical Target**: Configured component or service
- **What It Proves**: Static configuration wiring between config symbols and target components.
- **What It Does Not Prove**: Does not expose secret `.env` values (sensitive files are blocked).
- **Common Tool**: `get_context / get_references`
- **Example**: `DatabaseSettings` -> `CONFIGURES` (`DATAFLOW_VERIFIED`) -> `create_engine_pool`

#### `CONTAINS`
- **Meaning**: Parent class or module scope lexically contains a child method or nested symbol.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Class or module symbol
- **Typical Target**: Method or nested function symbol
- **What It Proves**: Lexical AST scope containment.
- **What It Does Not Prove**: Does not prove call order.
- **Common Tool**: `get_symbol / get_file`
- **Example**: `AuthService` -> `CONTAINS` (`AST_VERIFIED`) -> `AuthService.authenticate`

#### `CONTAINS_PACKAGE`
- **Meaning**: Workspace root or monorepo manifest contains a member workspace package.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`
- **Typical Source**: Workspace root
- **Typical Target**: Member package ID
- **What It Proves**: Workspace membership declared by workspace configuration (`pnpm-workspace.yaml`, `package.json`, `pyproject.toml`).
- **What It Does Not Prove**: Does not prove inter-package runtime calls.
- **Common Tool**: `get_architecture`
- **Example**: `workspace:root` -> `CONTAINS_PACKAGE` (`AST_VERIFIED`) -> `@acme/auth`

#### `CROSS_PACKAGE_IMPORT`
- **Meaning**: A source file in one workspace package imports a symbol or file across a package boundary.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Source file in Package A
- **Typical Target**: Target file/symbol in Package B
- **What It Proves**: Cross-package import crossing manifest-verified package boundaries.
- **What It Does Not Prove**: Does not prove whether the import violates custom linter rules unless inspected.
- **Common Tool**: `get_imports / get_context`
- **Example**: `apps/web/src/client.ts` -> `CROSS_PACKAGE_IMPORT` (`AST_VERIFIED`) -> `packages/auth/src/index.ts`

#### `DEFINES`
- **Meaning**: File or parent scope defines a class, function, method, or variable symbol.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Source file or parent class
- **Typical Target**: Defined symbol
- **What It Proves**: Exact AST declaration coordinates (`file`, `start_line`, `end_line`).
- **What It Does Not Prove**: Does not prove who calls the symbol.
- **Common Tool**: `resolve_symbol / get_file / get_symbol`
- **Example**: `src/auth/service.py` -> `DEFINES` (`AST_VERIFIED`) -> `AuthService`

#### `DEPENDS_ON`
- **Meaning**: General structural dependency edge between symbols or modules.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Dependent symbol or module
- **Typical Target**: Dependency symbol or module
- **What It Proves**: Static dependency backed by import, call, or DI evidence.
- **What It Does Not Prove**: Check specific relationship subtype (`IMPORTS`, `INJECTS`, `CALLS`) for exact mechanism.
- **Common Tool**: `get_dependents / get_context`
- **Example**: `OrderService` -> `DEPENDS_ON` (`AST_VERIFIED`) -> `InventoryClient`

#### `DEPENDS_ON_PACKAGE`
- **Meaning**: Manifest-backed workspace package declares a dependency on another workspace package.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Consumer workspace package (`@acme/api`, `apps/api`)
- **Typical Target**: Target workspace package (`@acme/auth`, `packages/auth`)
- **What It Proves**: Explicit dependency in `package.json`, `pyproject.toml`, `Cargo.toml`, or `go.mod`.
- **What It Does Not Prove**: Never inferred from directory names alone without manifest evidence.
- **Common Tool**: `get_architecture / get_context / get_dependents`
- **Example**: `@acme/api` -> `DEPENDS_ON_PACKAGE` (`AST_VERIFIED`) -> `@acme/shared`

#### `DISPATCHES_TO`
- **Meaning**: Dispatcher function or registry lookup dispatches execution to a registered handler.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `UNKNOWN`
- **Typical Source**: Dispatcher function (`dispatch_command`, `bus.publish`)
- **Typical Target**: Target handler symbol (or `<dynamic_dispatch>` when key is runtime-only)
- **What It Proves**: Dispatch mechanism connects the dispatcher to the registered target(s).
- **What It Does Not Prove**: When `evidence_class='POSSIBLE'` or `'UNKNOWN'`, does not guarantee which runtime key is passed.
- **Common Tool**: `trace_path / get_references / get_context`
- **Example**: `dispatch_order_event` -> `DISPATCHES_TO` (`DATAFLOW_VERIFIED`) -> `on_order_created`

#### `DI_CYCLE`
- **Meaning**: Circular dependency detected across DI providers (`A -> B -> A`).
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Provider symbol participating in cycle
- **Typical Target**: Provider symbol completing the cycle
- **What It Proves**: A static cycle exists in the provider dependency graph.
- **What It Does Not Prove**: Does not prove whether lazy runtime resolution breaks the cycle.
- **Common Tool**: `get_context / get_references`
- **Example**: `provide_a` -> `DI_CYCLE` (`DATAFLOW_VERIFIED`) -> `provide_b`

#### `EVENT_LISTENER`
- **Meaning**: Function or method subscribes to an event channel, signal, or domain event type.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Event type, signal, or event bus (`OrderCreated`, `user_logged_in`)
- **Typical Target**: Listener function (`send_receipt_on_order`)
- **What It Proves**: Framework or event-bus decorator/subscription binds the listener to the event.
- **What It Does Not Prove**: Does not prove synchronous vs asynchronous runtime broker delivery.
- **Common Tool**: `get_references / trace_path / get_context`
- **Example**: `OrderCreated` -> `EVENT_LISTENER` (`FRAMEWORK_VERIFIED`) -> `notify_warehouse`

#### `EXPORTS`
- **Meaning**: Module or package entrypoint explicitly exports a symbol (`__all__`, `export { X }`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`
- **Typical Source**: Module or package index file
- **Typical Target**: Exported symbol
- **What It Proves**: Public export declaration in module AST.
- **What It Does Not Prove**: Does not prove external consumption outside the repo.
- **Common Tool**: `get_file / get_symbol`
- **Example**: `packages/auth/src/index.ts` -> `EXPORTS` (`AST_VERIFIED`) -> `AuthClient`

#### `EXTENDS`
- **Meaning**: Class or interface inherits from a base class (`class Child(Base)` / `extends`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Subclass symbol
- **Typical Target**: Base class symbol
- **What It Proves**: AST-verified class inheritance.
- **What It Does Not Prove**: Does not prove dynamic metaclass mutation.
- **Common Tool**: `get_symbol / get_references`
- **Example**: `AdminUser` -> `EXTENDS` (`AST_VERIFIED`) -> `BaseUser`

#### `FOREIGN_KEY_TO`
- **Meaning**: Database column or ORM field declares a foreign-key reference to a target table/column.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Source column (`db.UNKNOWN.UNKNOWN.orders.user_id`)
- **Typical Target**: Target column or table (`db.UNKNOWN.UNKNOWN.users.id`)
- **What It Proves**: Static `ForeignKey(...)` or SQL `REFERENCES` constraint.
- **What It Does Not Prove**: Does not prove whether foreign key checks are enabled in SQLite PRAGMA at runtime.
- **Common Tool**: `find_db_relationships / get_db_table / get_db_schema`
- **Example**: `db.UNKNOWN.UNKNOWN.orders.user_id` -> `FOREIGN_KEY_TO` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.id`

#### `HANDLED_BY`
- **Meaning**: Canonical endpoint node is handled by the designated route handler symbol.
- **Allowed Evidence Classes**: `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `UNKNOWN`
- **Typical Source**: HTTP endpoint (`POST /api/v1/auth/login`)
- **Typical Target**: Handler symbol (`login_endpoint`)
- **What It Proves**: Requests matching the route path and HTTP method are routed to the handler.
- **What It Does Not Prove**: Does not prove middleware short-circuiting prior to the handler.
- **Common Tool**: `list_routes / trace_path / get_context`
- **Example**: `POST /api/v1/auth/login` -> `HANDLED_BY` (`FRAMEWORK_VERIFIED`) -> `login_endpoint`

#### `HAS_CHECK_CONSTRAINT`
- **Meaning**: Database table declares a `CheckConstraint` or SQL `CHECK (...)` expression.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Canonical database table
- **Typical Target**: Check constraint entity
- **What It Proves**: Static check constraint declaration in ORM or SQL schema.
- **What It Does Not Prove**: Does not prove application-level validation.
- **Common Tool**: `get_db_table / find_db_relationships`
- **Example**: `db.UNKNOWN.UNKNOWN.products` -> `HAS_CHECK_CONSTRAINT` (`STATIC_VERIFIED`) -> `check_price_positive`

#### `HAS_INDEX`
- **Meaning**: Database table declares a secondary index (`Index(...)`, `index=True`, `CREATE INDEX`, `@@index`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Canonical database table
- **Typical Target**: Index entity or indexed column
- **What It Proves**: Static index declaration in ORM model, SQL DDL, or migration.
- **What It Does Not Prove**: Does not prove query planner index selection at runtime.
- **Common Tool**: `get_db_table / find_db_relationships`
- **Example**: `db.UNKNOWN.UNKNOWN.users` -> `HAS_INDEX` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`

#### `HAS_PRIMARY_KEY`
- **Meaning**: Database table declares a primary-key column or constraint.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Canonical database table
- **Typical Target**: Primary key column (`db.<dialect>.<schema>.<table>.<column>`)
- **What It Proves**: Static `primary_key=True`, `@id`, or SQL `PRIMARY KEY` declaration.
- **What It Does Not Prove**: Does not prove auto-increment sequence values.
- **Common Tool**: `get_db_table / find_db_columns / find_db_relationships`
- **Example**: `db.UNKNOWN.UNKNOWN.users` -> `HAS_PRIMARY_KEY` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.id`

#### `HAS_UNIQUE_CONSTRAINT`
- **Meaning**: Database table or column declares a uniqueness constraint (`unique=True`, `UniqueConstraint`, `UNIQUE`, `@unique`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: Canonical database table
- **Typical Target**: Constrained column or constraint entity
- **What It Proves**: Static unique constraint in ORM model, SQL schema, or migration.
- **What It Does Not Prove**: Does not prove absence of duplicate legacy data prior to migration.
- **Common Tool**: `get_db_table / find_db_columns / find_db_relationships`
- **Example**: `db.UNKNOWN.UNKNOWN.users` -> `HAS_UNIQUE_CONSTRAINT` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`

#### `IMPLEMENTS`
- **Meaning**: Class implements an interface, protocol, or abstract base class.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Concrete class symbol
- **Typical Target**: Interface or Protocol symbol
- **What It Proves**: Static `implements` or protocol inheritance relationship.
- **What It Does Not Prove**: Does not prove structural duck-typing unless declared.
- **Common Tool**: `get_references / get_context`
- **Example**: `StripeGateway` -> `IMPLEMENTS` (`AST_VERIFIED`) -> `PaymentGateway`

#### `IMPORTS`
- **Meaning**: Module or symbol import statement extracted from syntax tree.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Importing file or module
- **Typical Target**: Imported module or symbol
- **What It Proves**: The source module contains an explicit import statement for the target.
- **What It Does Not Prove**: Does not prove that the imported symbol is called at runtime.
- **Common Tool**: `get_imports / get_dependents`
- **Example**: `src/auth/routes.py` -> `IMPORTS` (`AST_VERIFIED`) -> `src.auth.service.AuthService`

#### `INJECTS`
- **Meaning**: Consumer endpoint, class, or function declares an injected dependency parameter (`Depends(provider)`, `@inject`).
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Consumer function/class (`login_endpoint`, `UserController`)
- **Typical Target**: Dependency provider or token (`get_auth_service`, `AuthService`)
- **What It Proves**: The consumer receives the dependency through framework or container injection.
- **What It Does Not Prove**: Never implies the consumer directly calls the provider as a normal helper (`INJECTS != CALLS`).
- **Common Tool**: `get_context / get_references / trace_path`
- **Example**: `login_endpoint` -> `INJECTS` (`FRAMEWORK_VERIFIED`) -> `get_auth_service`

#### `MAPS_TO_COLUMN`
- **Meaning**: ORM model attribute or field maps to a database table column.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: ORM model field (`Product.shop_id`)
- **Typical Target**: Canonical database column (`db.UNKNOWN.UNKNOWN.products.shop_id`)
- **What It Proves**: Static ORM column declaration (`Column`, `mapped_column`, `models.Field`, `Field`).
- **What It Does Not Prove**: Does not prove runtime column value constraints.
- **Common Tool**: `find_db_columns / get_db_table`
- **Example**: `Product.shop_id` -> `MAPS_TO_COLUMN` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products.shop_id`

#### `MAPS_TO_TABLE`
- **Meaning**: ORM model class maps to a canonical database table entity.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: ORM model class (`User`, `Product`)
- **Typical Target**: Canonical database table (`db.postgres.public.users`)
- **What It Proves**: Explicit (`__tablename__`, `db_table`, `@@map`) or framework-inferred model-to-table mapping.
- **What It Does Not Prove**: Does not prove that the table exists on an external unindexed database server.
- **Common Tool**: `find_db_models / get_db_table / find_db_relationships`
- **Example**: `Product` -> `MAPS_TO_TABLE` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products`

#### `MIGRATES_TABLE`
- **Meaning**: Database migration file (Alembic, Django migration, Prisma migration, or SQL migration) creates, alters, or drops a table.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Migration revision or file (`migrations/0001_initial.py`)
- **Typical Target**: Canonical database table
- **What It Proves**: Static migration operation (`op.create_table`, `migrations.CreateModel`, `CREATE TABLE`, `ALTER TABLE`).
- **What It Does Not Prove**: Does not prove whether the migration has been applied to a live deployment.
- **Common Tool**: `get_db_table / get_db_schema / get_db_impact`
- **Example**: `migrations/versions/001_init.py` -> `MIGRATES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users`

#### `MOUNTS`
- **Meaning**: Application or parent router mounts a child router or sub-application under a URL prefix.
- **Allowed Evidence Classes**: `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Root application or parent router (`app`, `api_router`)
- **Typical Target**: Mounted sub-router (`auth_router`, `v1_router`)
- **What It Proves**: Framework router composition (`include_router`, `register_blueprint`, `app.use`).
- **What It Does Not Prove**: Does not prove direct function call semantics (`MOUNTS` is never collapsed into `CALLS`).
- **Common Tool**: `list_routes / get_architecture / trace_path`
- **Example**: `app` -> `MOUNTS` (`FRAMEWORK_VERIFIED`, prefix=`/api/v1`) -> `auth_router`

#### `ORM_RELATION`
- **Meaning**: ORM model declares a high-level association (`relationship()`, `ForeignKey` relation, `@relation`) to another ORM model.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Source ORM model (`Product`)
- **Typical Target**: Target ORM model (`Shop`)
- **What It Proves**: Framework-verified one-to-one, one-to-many, or many-to-many model association.
- **What It Does Not Prove**: Does not prove eager vs lazy loading behavior unless inspected via `get_file`.
- **Common Tool**: `find_db_relationships / find_db_models / get_db_table`
- **Example**: `Product` -> `ORM_RELATION` (`FRAMEWORK_VERIFIED`) -> `Shop`

#### `PACKAGE_IMPORTS`
- **Meaning**: Package-level rollup of source imports targeting another workspace package.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Source workspace package
- **Typical Target**: Imported workspace package
- **What It Proves**: Files inside the source package import modules owned by the target package.
- **What It Does Not Prove**: Does not prove public API stability.
- **Common Tool**: `get_architecture / get_imports`
- **Example**: `packages/orders` -> `PACKAGE_IMPORTS` (`AST_VERIFIED`) -> `packages/shared`

#### `POSSIBLE_CALLS`
- **Meaning**: Candidate or dynamically dispatched call edge that is plausible (`POSSIBLE`) or unresolved (`UNKNOWN`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Caller symbol using dynamic dispatch, interface, or conditional binding
- **Typical Target**: Candidate target symbol or `<dynamic_target>`
- **What It Proves**: A call site exists where static analysis found a candidate or unresolved dynamic target.
- **What It Does Not Prove**: Never proves an authoritative `CALLS` edge without targeted source inspection.
- **Common Tool**: `get_callers / get_callees / get_context`
- **Example**: `dispatch_action` -> `POSSIBLE_CALLS` (`POSSIBLE`) -> `RefundHandler.handle`

#### `POSSIBLE_TABLE`
- **Meaning**: Query references a candidate database table via conditional logic or partial string interpolation (`evidence_class='POSSIBLE'`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Function or query site
- **Typical Target**: Candidate table name or `db.UNKNOWN.UNKNOWN.<candidate>`
- **What It Proves**: Plausible static table candidate that is not statically guaranteed.
- **What It Does Not Prove**: Never proves an unconditional `READS_TABLE` or `WRITES_TABLE` edge without source verification.
- **Common Tool**: `find_db_queries / find_db_tables / get_context`
- **Example**: `query_partition` -> `POSSIBLE_TABLE` (`POSSIBLE`) -> `db.UNKNOWN.UNKNOWN.events_archive`

#### `PROVIDES`
- **Meaning**: Dependency provider function or factory constructs/yields a concrete service or resource type.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Provider function or container binding (`get_auth_service`)
- **Typical Target**: Provided type or implementation (`AuthService`)
- **What It Proves**: The provider supplies instances of the target type to DI consumers.
- **What It Does Not Prove**: Does not prove singleton vs request-scoped lifetime unless inspected in source.
- **Common Tool**: `get_context / get_references / trace_path`
- **Example**: `get_auth_service` -> `PROVIDES` (`FRAMEWORK_VERIFIED`) -> `AuthService`

#### `QUERIES_DATABASE`
- **Meaning**: Function or module executes a database query through a session, cursor, or engine.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Function or method symbol
- **Typical Target**: Database entity or query target
- **What It Proves**: Database execution call (`cursor.execute`, `session.execute`, `conn.fetch`) at the cited lines.
- **What It Does Not Prove**: When target table is dynamic, pair with `POSSIBLE_TABLE` or `UNKNOWN_TABLE`.
- **Common Tool**: `find_db_queries / get_runtime_trace`
- **Example**: `run_report` -> `QUERIES_DATABASE` (`AST_VERIFIED`) -> `db.UNKNOWN.UNKNOWN`

#### `READS_COLUMN`
- **Meaning**: Query or function explicitly selects or filters on a specific database column.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `RUNTIME_UNOBSERVED`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Function or query site
- **Typical Target**: Canonical database column (`db.<dialect>.<schema>.<table>.<column>`)
- **What It Proves**: Column reference in `SELECT` projection, `WHERE` filter, or ORM field access.
- **What It Does Not Prove**: Does not prove index utilization at runtime.
- **Common Tool**: `find_db_readers / get_db_impact`
- **Example**: `find_by_email` -> `READS_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`

#### `READS_ENV`
- **Meaning**: Module or function reads an environment variable (`os.getenv`, `os.environ.get`, `process.env`) for database or service configuration.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `STATIC_VERIFIED`
- **Typical Source**: File or symbol
- **Typical Target**: Environment variable name (`env:DATABASE_URL`) — never the secret value
- **What It Proves**: Static environment variable lookup by key name.
- **What It Does Not Prove**: Never exposes or stores the runtime environment variable's secret value.
- **Common Tool**: `get_db_schema / get_context`
- **Example**: `src/config.py` -> `READS_ENV` (`AST_VERIFIED`) -> `env:DATABASE_URL`

#### `READS_TABLE`
- **Meaning**: Function, method, or query reads rows from a database table (`SELECT`, `.query()`, `.objects.filter()`, `.findMany()`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `RUNTIME_UNOBSERVED`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Function, repository method, or route handler
- **Typical Target**: Canonical database table (`db.<dialect>.<schema>.<table>`)
- **What It Proves**: Static SQL `SELECT` or ORM read query targeting the table (or `RUNTIME_OBSERVED` when seen in runtime traces).
- **What It Does Not Prove**: Does not prove runtime cache hits or row counts.
- **Common Tool**: `find_db_readers / find_db_callers / find_db_queries / get_db_table`
- **Example**: `get_product` -> `READS_TABLE` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products`

#### `REEXPORTS`
- **Meaning**: Barrel file or `__init__.py` re-exports a symbol imported from an internal module.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`
- **Typical Source**: Barrel module (`__init__.py`, `index.ts`)
- **Typical Target**: Original symbol definition
- **What It Proves**: Explicit re-export binding across modules.
- **What It Does Not Prove**: Does not prove runtime execution.
- **Common Tool**: `resolve_symbol / get_imports`
- **Example**: `src/auth/__init__.py` -> `REEXPORTS` (`AST_VERIFIED`) -> `src/auth/service.py:AuthService`

#### `REFERENCES`
- **Meaning**: Source symbol references another symbol (type annotation, constant read, decorator argument).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Referencing symbol
- **Typical Target**: Referenced symbol
- **What It Proves**: Static identifier reference in AST.
- **What It Does Not Prove**: Does not prove an executable function call (`REFERENCES != CALLS`).
- **Common Tool**: `get_references`
- **Example**: `create_order` -> `REFERENCES` (`AST_VERIFIED`) -> `OrderCreateSchema`

#### `REFERENCES_COLUMN`
- **Meaning**: Constraint, index, or foreign key references a specific database column.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: ForeignKey, Index, or ORM field
- **Typical Target**: Referenced database column
- **What It Proves**: Static column reference in constraint or index definition.
- **What It Does Not Prove**: Does not prove runtime cascade execution.
- **Common Tool**: `find_db_relationships / find_db_columns`
- **Example**: `idx_users_email` -> `REFERENCES_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`

#### `REFERENCES_TABLE`
- **Meaning**: Schema constraint, view, or query references a database table.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Table, view, or symbol
- **Typical Target**: Referenced database table
- **What It Proves**: Static table reference in DDL, view, or ORM declaration.
- **What It Does Not Prove**: Does not prove direct row mutation (`REFERENCES_TABLE != WRITES_TABLE`).
- **Common Tool**: `find_db_relationships / get_db_table`
- **Example**: `order_summary_view` -> `REFERENCES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.orders`

#### `REGISTERED_HANDLER`
- **Meaning**: Links a registry key or registry container to the handler symbol registered for it.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Registry or dispatch key
- **Typical Target**: Handler function or class
- **What It Proves**: The handler is statically associated with the registry entry.
- **What It Does Not Prove**: Does not prove when or how often the registry is invoked.
- **Common Tool**: `get_references / get_context`
- **Example**: `payment_registry['stripe']` -> `REGISTERED_HANDLER` (`DATAFLOW_VERIFIED`) -> `StripeGateway`

#### `REGISTERS`
- **Meaning**: Symbol or module registers a handler, plugin, or key into a registry or handler map.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Decorator, registration call, or module initializer
- **Typical Target**: Registered handler symbol or registry container
- **What It Proves**: Static registration into a registry object (`@registry.register`, `REGISTRY[k] = fn`).
- **What It Does Not Prove**: Never proves a direct `CALLS` edge at registration time.
- **Common Tool**: `get_references / get_context`
- **Example**: `command_registry` -> `REGISTERS` (`DATAFLOW_VERIFIED`) -> `CreateInvoiceHandler`

#### `RESOLVES_DEPENDENCY`
- **Meaning**: DI container or binding map resolves an abstract interface/token to a concrete implementation.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Interface, protocol, or DI token (`PaymentGateway`)
- **Typical Target**: Concrete implementation (`StripePaymentGateway`)
- **What It Proves**: Container binding (`container.bind`, `app.dependency_overrides`) maps token to implementation.
- **What It Does Not Prove**: When multiple conditional bindings exist (`POSSIBLE`), does not prove which env branch is active.
- **Common Tool**: `get_context / get_references / trace_path`
- **Example**: `PaymentGateway` -> `RESOLVES_DEPENDENCY` (`DATAFLOW_VERIFIED`) -> `StripePaymentGateway`

#### `RESOLVES_TO`
- **Meaning**: Alias, import binding, or target reference resolves to its canonical symbol definition.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Local alias or imported reference
- **Typical Target**: Canonical symbol definition
- **What It Proves**: Deterministic name/dataflow resolution to a canonical target.
- **What It Does Not Prove**: Does not prove runtime invocation.
- **Common Tool**: `resolve_symbol / get_references`
- **Example**: `auth_svc.authenticate` -> `RESOLVES_TO` (`DATAFLOW_VERIFIED`) -> `AuthService.authenticate`

#### `ROUTES_TO`
- **Meaning**: URL dispatcher or route table entry routes a path pattern to a view or controller.
- **Allowed Evidence Classes**: `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `UNKNOWN`
- **Typical Source**: Route table or URL pattern
- **Typical Target**: View function or class-based view
- **What It Proves**: Static URL routing table connects the pattern to the target view.
- **What It Does Not Prove**: Does not prove runtime query parameter validation.
- **Common Tool**: `list_routes / trace_path`
- **Example**: `/users/<id>` -> `ROUTES_TO` (`FRAMEWORK_VERIFIED`) -> `UserDetailView`

#### `ROUTE_HANDLER`
- **Meaning**: Framework route decorator or registration binds an HTTP/RPC endpoint to its handler function.
- **Allowed Evidence Classes**: `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `UNKNOWN`
- **Typical Source**: Router or endpoint declaration
- **Typical Target**: Handler function or controller method
- **What It Proves**: The route is bound to the handler via recognized framework syntax.
- **What It Does Not Prove**: Does not prove external reverse-proxy rewrites.
- **Common Tool**: `list_routes / get_context`
- **Example**: `POST /api/v1/auth/login` -> `ROUTE_HANDLER` (`FRAMEWORK_VERIFIED`) -> `login_endpoint`

#### `TASK_HANDLER`
- **Meaning**: Background task decorator (`@app.task`, `@shared_task`, `@dramatiq.actor`) marks a task entrypoint.
- **Allowed Evidence Classes**: `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Task queue / broker decorator or `.delay` / `.apply_async` site
- **Typical Target**: Task handler function (`send_welcome_email`)
- **What It Proves**: The function is registered as an executable background task handler.
- **What It Does Not Prove**: Does not prove broker queue availability at runtime.
- **Common Tool**: `trace_path / get_context / get_references`
- **Example**: `celery_app.task` -> `TASK_HANDLER` (`FRAMEWORK_VERIFIED`) -> `send_welcome_email`

#### `TESTS`
- **Meaning**: Test function or test module exercises a production symbol or file.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Test function (`test_login_flow`)
- **Typical Target**: Production symbol (`AuthService.authenticate`)
- **What It Proves**: Static call, import, fixture, or route link from test to target symbol.
- **What It Does Not Prove**: Does not prove that the test passes or covers 100% of branches.
- **Common Tool**: `find_related_tests / get_git_impact / get_context`
- **Example**: `test_login_route_flow` -> `TESTS` (`AST_VERIFIED`) -> `login_endpoint`

#### `TESTS_EVENT_HANDLER`
- **Meaning**: Test publishes an event or directly invokes an event/task/command handler.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Test function
- **Typical Target**: Event listener, task handler, or command handler
- **What It Proves**: Static link between test and event/task handler.
- **What It Does Not Prove**: Does not prove live message broker delivery.
- **Common Tool**: `find_related_tests / get_context`
- **Example**: `test_order_created_listener` -> `TESTS_EVENT_HANDLER` (`FRAMEWORK_VERIFIED`) -> `on_order_created`

#### `TESTS_PROVIDER`
- **Meaning**: Test overrides or exercises a DI provider (`app.dependency_overrides[get_db] = ...`).
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Test function or fixture
- **Typical Target**: DI provider symbol
- **What It Proves**: Test explicitly references or overrides the DI provider.
- **What It Does Not Prove**: Does not prove production database behavior when provider is mocked.
- **Common Tool**: `find_related_tests / get_context`
- **Example**: `test_profile_with_mock_user` -> `TESTS_PROVIDER` (`FRAMEWORK_VERIFIED`) -> `get_current_user`

#### `TESTS_ROUTE`
- **Meaning**: Test function sends an HTTP client request (`client.post('/api/v1/auth/login')`) to an indexed route.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Test function
- **Typical Target**: Route endpoint or route handler
- **What It Proves**: Test client call path matches an indexed framework route.
- **What It Does Not Prove**: Does not prove external network integration.
- **Common Tool**: `find_related_tests / get_context`
- **Example**: `test_login_endpoint` -> `TESTS_ROUTE` (`FRAMEWORK_VERIFIED`) -> `POST /api/v1/auth/login`

#### `TESTS_SYMBOL`
- **Meaning**: Test function directly invokes or asserts against a production function, method, or class.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Test function
- **Typical Target**: Production symbol
- **What It Proves**: AST-verified call or reference from the test body to the production symbol.
- **What It Does Not Prove**: Never fabricated from filename similarity alone.
- **Common Tool**: `find_related_tests / get_context`
- **Example**: `test_charge_card` -> `TESTS_SYMBOL` (`AST_VERIFIED`) -> `BillingService.charge_card`

#### `UNKNOWN_TABLE`
- **Meaning**: Database query executes a dynamically constructed SQL string or table identifier that cannot be statically resolved (`evidence_class='UNKNOWN'`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `UNKNOWN`
- **Typical Source**: Function executing dynamic SQL
- **Typical Target**: `db.UNKNOWN.UNKNOWN.UNKNOWN`
- **What It Proves**: A database query occurs at the cited location whose target table is statically unresolvable.
- **What It Does Not Prove**: Never means no table is accessed; inspect the call site with `get_file` or runtime traces.
- **Common Tool**: `find_db_queries / get_context`
- **Example**: `execute_raw_dynamic` -> `UNKNOWN_TABLE` (`UNKNOWN`) -> `db.UNKNOWN.UNKNOWN.UNKNOWN`

#### `UNRESOLVED_REFERENCE`
- **Meaning**: A call, dispatch, or dependency site whose target could not be statically resolved (`UNKNOWN` or `POSSIBLE`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Source symbol containing dynamic/unresolved expression
- **Typical Target**: `<unresolved>` or candidate symbol name
- **What It Proves**: A dynamic or unindexed reference exists at the cited file and line.
- **What It Does Not Prove**: Never proves that no relationship exists at runtime.
- **Common Tool**: `get_context / get_references`
- **Example**: `PluginLoader.load` -> `UNRESOLVED_REFERENCE` (`UNKNOWN`) -> `<dynamic_getattr>`

#### `USES`
- **Meaning**: Symbol uses a type, trait, mixin, or configuration constant.
- **Allowed Evidence Classes**: `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`
- **Typical Source**: Consumer symbol
- **Typical Target**: Used type or constant
- **What It Proves**: Static usage in type signature or body.
- **What It Does Not Prove**: Does not prove direct call execution.
- **Common Tool**: `get_references / get_context`
- **Example**: `TokenEncoder` -> `USES` (`AST_VERIFIED`) -> `JWT_ALGORITHM`

#### `WRITES_COLUMN`
- **Meaning**: Query or function explicitly inserts or updates a specific database column.
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `RUNTIME_UNOBSERVED`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Function or mutation query site
- **Typical Target**: Canonical database column (`db.<dialect>.<schema>.<table>.<column>`)
- **What It Proves**: Column assignment in `INSERT`, `UPDATE ... SET`, or ORM attribute mutation.
- **What It Does Not Prove**: Does not expose literal parameter values (redacted for security).
- **Common Tool**: `find_db_writers / get_db_impact`
- **Example**: `update_stock` -> `WRITES_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.inventory.quantity`

#### `WRITES_TABLE`
- **Meaning**: Function, method, or query mutates rows in a database table (`INSERT`, `UPDATE`, `DELETE`, `.add()`, `.create()`, `.save()`).
- **Allowed Evidence Classes**: `AMBIGUOUS`, `AST_VERIFIED`, `DATAFLOW_VERIFIED`, `FRAMEWORK_VERIFIED`, `POSSIBLE`, `RUNTIME_OBSERVED`, `RUNTIME_UNOBSERVED`, `STATIC_VERIFIED`, `UNKNOWN`
- **Typical Source**: Service, repository method, or route handler
- **Typical Target**: Canonical database table (`db.<dialect>.<schema>.<table>`)
- **What It Proves**: Static SQL mutation or ORM write call targeting the table (or `RUNTIME_OBSERVED` in traces).
- **What It Does Not Prove**: Does not prove whether a transaction commits or rolls back at runtime.
- **Common Tool**: `find_db_writers / find_db_callers / find_db_queries / get_db_impact`
- **Example**: `create_order` -> `WRITES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.orders`


---

## 6. Task Classification & Routing Manifest

CodeGraph classifies developer requests into 13 canonical `AgentTaskCategory` values and provides a deterministic `ROUTING_MANIFEST`:

| Category | Use CodeGraph? | Primary Tool | Recommended Sequence | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `LOCAL_EDIT` | `False` | None (bypass CodeGraph) | `read_file` | Single-file local edits (typos, formatting, local variable renames) do not require cross-file graph queries. |
| `SYMBOL_LOOKUP` | `True` | `resolve_symbol` | `resolve_symbol` -> `get_symbol` | Use resolve_symbol, find_symbol, or search_symbols to locate canonical symbol definitions without blind grep. |
| `RELATIONSHIP` | `True` | `get_callers` | `resolve_symbol` -> `get_callers` | Use find_callers/get_callers, find_callees/get_callees, or find_references/get_references to retrieve AST/framework-verified relationships. |
| `TRACE` | `True` | `trace_path` | `list_routes` -> `resolve_symbol` -> `trace_path` | Use trace_path (or find_routes/list_routes -> resolve_symbol -> trace_path) to prove multi-hop execution chains. |
| `DEBUG` | `True` | `get_context` | `resolve_symbol` -> `get_context` | Use get_context (intent='DEBUG') to gather target, callers, callees, DI providers, and related tests in one bounded packet. |
| `CHANGE_IMPACT` | `True` | `get_git_impact` | `resolve_symbol` -> `get_git_impact` | Use get_git_impact or analyze_impact to deterministically compute affected callers, packages, and tests. |
| `TEST_DISCOVERY` | `True` | `find_related_tests` | `resolve_symbol` -> `find_related_tests` | Use find_tests/find_related_tests or get_context(intent='TEST') to locate statically linked test functions. |
| `ROUTE_DISCOVERY` | `True` | `list_routes` | `list_routes` -> `resolve_symbol` | Use find_routes/list_routes to discover HTTP endpoints, mounted router prefixes, and handler symbols. |
| `DIAGNOSTIC` | `True` | `get_repository_status` | `get_repository_status` | Use get_repository_status to check index freshness, symbol counts, and database health. |
| `ARCHITECTURE` | `True` | `get_architecture` | `get_architecture` -> `get_context` | Use get_architecture to inspect module boundaries, entrypoints, and workspace package dependencies. |
| `PACKAGE` | `True` | `get_context` | `get_architecture` -> `get_context` | Use get_architecture and get_context to inspect manifest-backed workspace packages and DEPENDS_ON_PACKAGE edges. |
| `MULTI_FILE_INVESTIGATION` | `True` | `get_context` | `search_symbols` -> `resolve_symbol` -> `get_context` | Use get_context, search_code, or targeted graph tools first to avoid blind multi-file reading. |
| `EXPLANATION` | `True` | `get_context` | `resolve_symbol` -> `get_context` | Use get_context (intent='EXPLAIN' or 'UNDERSTAND') to retrieve verified definitions and dependencies. |

### Deterministic `ROUTING_MANIFEST`
- `symbol_definition` -> `find_symbol`
- `symbol_details` -> `get_symbol`
- `text_or_template_search` -> `search_code`
- `file_inspection` -> `get_file`
- `callers` -> `find_callers`
- `callees` -> `find_callees`
- `references` -> `find_references`
- `routes` -> `find_routes`
- `tests` -> `find_tests`
- `execution_trace` -> `trace_path`
- `architecture` -> `get_architecture`
- `task_context` -> `get_context`
- `git_impact` -> `get_git_impact`

---

## 7. Decision Tree

Use this deterministic decision tree before invoking any tool:

1. **Developer asks: "Change this one local variable / Fix a typo in a docstring in a known file."**
   - **Classification**: `LOCAL_EDIT`
   - **Decision**: Bypass CodeGraph -> use `get_file` / `read_file` / editor tools directly.
   - **Why**: Single-file local edits do not depend on cross-file relationships; calling graph tools wastes tokens and latency.
2. **Developer asks: "Where is symbol X defined?"**
   - **Classification**: `SYMBOL_LOOKUP`
   - **Decision**: Call `find_symbol(symbol="X")` (or `resolve_symbol(symbol="X")`), then `get_symbol(symbol=...)` if signature/decorators are needed.
   - **Why**: Grounds `X` into a canonical symbol ID and surfaces any homonym ambiguity immediately.
3. **Developer asks: "Where does literal text, button label, HTML id, or template string Y appear?"**
   - **Classification**: `text_or_template_search`
   - **Decision**: Call `search_code(query="Y")` -> `get_file(path=..., start_line=..., end_line=...)`.
   - **Why**: Searches `.py`, `.html`, `.jinja`, `.jinja2`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, `.json`, `.yaml`, `.yml`, and `.md` files deterministically without polluting the semantic graph.
4. **Developer asks: "What calls X?" or "What does X call?"**
   - **Classification**: `RELATIONSHIP`
   - **Decision**: Call `find_callers(symbol="X")` or `find_callees(symbol="X")` (`get_callers` and `get_callees` are also supported).
   - **Why**: Returns AST- and dataflow-verified call edges (`CALLS`) distinct from lexical text matches.
5. **Developer asks: "Which route handles `/api/v1/auth/login` and how does it reach the database?"**
   - **Classification**: `ROUTE_DISCOVERY` / `TRACE`
   - **Decision**: Call `find_routes(path="/api/v1/auth/login")` (or `list_routes`) -> `trace_path(from_symbol=..., to_symbol=...)` (or `get_context(query=..., intent="TRACE")`).
   - **Why**: Composes mounted router prefixes (`MOUNTS`) with `HANDLED_BY`, `INJECTS`, and `CALLS`.
6. **Developer asks: "Why does this fail?" or "How does this dependency get injected?"**
   - **Classification**: `DEBUG`
   - **Decision**: Call `get_context(query=..., intent="DEBUG")`, followed by targeted `get_file(path, start_line, end_line)` on specific lines if needed.
   - **Why**: Compiles target symbol, callers, callees, DI providers (`INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`), and covering tests in one token-bounded packet.
7. **Developer asks: "What breaks if we change X?" or "What is the impact of recent commits?"**
   - **Classification**: `CHANGE_IMPACT`
   - **Decision**: Call `get_git_impact(base="HEAD~1", head="HEAD")` (for Git diffs) or `analyze_impact(symbol=...)` (for symbol edits).
   - **Why**: Computes downstream callers, affected routes, affected packages, and covering tests deterministically.
8. **Developer asks: "What tests cover X?"**
   - **Classification**: `TEST_DISCOVERY`
   - **Decision**: Call `find_tests(symbol="X")` (or `find_related_tests(symbol="X")`).
   - **Why**: Links tests via static call, import, fixture, or route invocation (`TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`).
9. **Developer asks: "How is the whole system or monorepo structured?"**
   - **Classification**: `ARCHITECTURE` / `PACKAGE`
   - **Decision**: Call `get_architecture()` -> `get_context(query=..., intent="ARCHITECTURE")`.
   - **Why**: Extracts manifest-backed workspace packages (`DEPENDS_ON_PACKAGE`), entrypoints, and module boundaries without dumping the entire repository.

---

## 8. Symbol Resolution

Always ground bare symbol names with `find_symbol(symbol=...)` or `resolve_symbol(symbol=...)` before querying relationships when exact canonical identity is unknown (`canonical_id` and `name` are also accepted as explicit compatibility aliases).

- **Resolution Order (`TargetResolver`)**:
  1. Exact `canonical_id` (`CANONICAL_ID`, `HIGH` confidence)
  2. Exact `qualified_name` (`EXACT_QUALIFIED`, `HIGH` confidence)
  3. Exact route path or endpoint ID (`ROUTE_MATCH`, `HIGH` confidence)
  4. `module.symbol` resolution (`MODULE_SYMBOL`, `HIGH`/`MEDIUM` confidence)
  5. `Class.method` resolution (`CLASS_METHOD`, `HIGH` confidence)
  6. Exact filename match (`FILENAME`, `HIGH` confidence)
  7. Short name match (`LEXICAL`: `MEDIUM` if unique, `AMBIGUOUS` / `LOW` if multiple definitions exist)
  8. No match (`UNKNOWN`)
- **Rule**: Once you have a `canonical_id` in the current turn, pass that identifier via `symbol=...` (or `canonical_id=...`) directly to `find_callers`, `find_callees`, `find_references`, or `get_symbol`. Never call `resolve_symbol` repeatedly for the same symbol.

---

## 9. Search / Discovery (`find_symbol` vs `search_code`)

CodeGraph provides two distinct discovery layers that must never be conflated:

1. **Semantic Symbol Discovery (`find_symbol(symbol)` / `search_symbols(query, top_k=20)`)**:
   - Searches indexed AST symbol declarations (`class`, `function`, `method`, `interface`).
   - Use when looking for where a Python/TS/JS/Go/Rust symbol or identifier is defined.
2. **Repository Text Search (`search_code(query, path_filter=None, file_types=None, include_tests=True, include_configs=True, max_results=20)`)**:
   - Searches literal text, exact phrases, identifiers, route strings, HTML ids/classes, UI button text, Jinja template blocks, CSS selectors, config keys, and markdown across `.py`, `.html`, `.jinja`, `.jinja2`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, `.json`, `.yaml`, `.yml`, and `.md` files.
   - Respects sensitive-file exclusions, binary exclusions, `.gitignore`/`.codegraphignore`, and artifact policies.
   - Returns deterministic results (`path`, `line`, `matched_text`, `snippet`, `category`, `score`, `reason`) ordered by `(-score, path, line)`.
- **Strict Separation Rule**: `search_code` is for literal/text discovery only. It never creates semantic graph edges (`CALLS`, `REFERENCES`, `IMPORTS`, `ROUTES`, `DEPENDS_ON_PACKAGE`) and never pollutes `get_context` graph relationships.

---

## 10. Symbol & File Inspection (`get_symbol` & `get_file`)

- **`get_symbol(symbol=...)`** (or `canonical_id=...`): Inspects a symbol's declaration metadata (`canonical_id`, `qualified_name`, `kind`, `signature`, `decorators`, `file`, `start_line`, `end_line`, `snippet`) without reading the entire file.
- **`get_file(path=..., start_line=None, end_line=None, max_lines=200, include_content=False)`**:
  - Opens a file's AST symbol outline AND/OR reads a bounded line range (`start_line`..`end_line`, capped by `max_lines`) across any readable repository text file (`.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, `.md`).
  - Returns `path`, `start_line`, `end_line`, `content`, `truncated: bool`, and `category` (`SOURCE`, `TEST`, `CONFIG`, etc.).

---

## 11. References

Use `get_references(symbol=...)` or `find_references(symbol=...)` (alias `canonical_id=...`) to find structured references to a symbol across the repository:
- `get_references` returns references with explicit `relationship` (`CALLS`, `IMPORTS`, `REGISTERS`, `DISPATCHES_TO`, `EVENT_LISTENER`, `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `REFERENCES`) and `evidence_class`.

---

## 12. Callers / Callees

- **`find_callers(symbol=...)` / `get_callers(symbol=...)`** (alias `canonical_id=...`): Returns upstream symbols that call `symbol`.
- **`find_callees(symbol=...)` / `get_callees(symbol=...)`** (alias `canonical_id=...`): Returns downstream symbols called by `symbol`.
- **Symmetric Factory & Dataflow Resolution**:
  - Forward (`find_callees`, `get_callees`), reverse (`find_callers`, `get_callers`), and path (`trace_path`) traversal share the same conservative dataflow and factory resolution engine. When a caller invokes `svc = get_inventory_service()` and calls `svc.place_order()`, both forward and reverse traversal agree on `CALLS` (`DATAFLOW_VERIFIED`, `confidence="HIGH"`).
- **Epistemic Distinction**:
  - `relationship="CALLS"` with `evidence_class="AST_VERIFIED"` or `"DATAFLOW_VERIFIED"` proves a static call site.
  - `relationship="POSSIBLE_CALLS"` with `evidence_class="POSSIBLE"` or `"UNKNOWN"` indicates a candidate or dynamic call site that requires source verification via `get_file` / `read_file`.

---

## 13. Graph Tracing

- **`trace_path(from_symbol=..., to_symbol=..., max_depth=5)`**: Computes deterministic shortest/ranked relationship paths connecting `from_symbol` to `to_symbol`. Traverses `HANDLED_BY`, `MOUNTS`, `CALLS`, `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `DISPATCHES_TO`, `TASK_HANDLER`, `COMMAND_HANDLER`, and `EVENT_LISTENER`.
- **`trace_flow(symbol=..., depth=2, callers=True, callees=False, both=False)`** (and alias `trace_call`): Explores directional call trees from a single symbol when only one endpoint is known.
- **`get_call_graph(symbol=..., depth=2, max_results=100)`**: Computes the bounded local call neighborhood subgraph around `symbol`.

---

## 14. Routes / Frameworks

Use `find_routes(framework=None, method=None, path=None)` (or `list_routes`) to interrogate web/RPC entrypoints:
- Supported frameworks include FastAPI, Flask, Django, Express, and NestJS.
- **Mount Composition (`MOUNTS`)**: When `app.include_router(auth_router, prefix="/api/v1")` mounts a router whose route is `@router.post("/auth/login")`, CodeGraph composes the full path `/api/v1/auth/login` (`FRAMEWORK_VERIFIED`) and links the router via `MOUNTS` and the endpoint via `HANDLED_BY` / `ROUTE_HANDLER`.
- Never grep for full URL paths in repositories that compose router prefixes; always call `find_routes` / `list_routes` first.

---

## 15. Registries

CodeGraph models handler registries and plugin tables explicitly:
- **`REGISTERS`**: Emitted when a decorator (`@registry.register("key")`) or assignment (`REGISTRY["key"] = Handler`) registers a symbol into a registry.
- **`REGISTERED_HANDLER`**: Connects the registry or key to the registered handler symbol.
- **Rule**: Never convert `REGISTERS` into `CALLS`. Registration records that a handler was added to a registry; invocation occurs only at dispatch sites (`DISPATCHES_TO`).
- **Overwrite & Conditional Behavior**:
  - If a registry key is conditionally registered (`if settings.USE_V2:`), CodeGraph assigns `evidence_class="POSSIBLE"`.
  - If multiple handlers register the same key or overwrite it, CodeGraph preserves all candidates and marks ambiguity rather than silently dropping earlier registrations.

---

## 16. Dispatch

- **`DISPATCHES_TO`**: Emitted when a dispatcher function looks up a handler in a known registry (`registry.dispatch(key)`, `HANDLERS[kind]()`) and invokes it.
- **Known Static Key**: Marked `FRAMEWORK_VERIFIED` or `DATAFLOW_VERIFIED`.
- **Ambiguous / Multiple Candidate Handlers**: Marked `POSSIBLE` with candidate targets preserved.
- **Dynamic Runtime Key (`getattr`, opaque variable)**: Marked `UNKNOWN` (`UNRESOLVED_REFERENCE` / `POSSIBLE_CALLS`) so the agent knows static analysis reached a dynamic boundary.

---

## 17. Events

- **`EVENT_LISTENER`**: Emitted when a function or method subscribes to an event bus, signal, or event class (`@bus.on(OrderCreated)`, `signal.connect(handler)`).
- Use `get_references(symbol="<EventName>")` or `get_context(query=..., intent="TRACE")` to discover all listeners subscribed to an event.

---

## 18. Tasks

- **`TASK_HANDLER`**: Emitted for background task declarations (`@app.task`, `@shared_task`, `@dramatiq.actor`).
- When tracing `.delay(...)` or `.apply_async(...)` calls, CodeGraph links the task invocation to the `TASK_HANDLER` symbol with `FRAMEWORK_VERIFIED` evidence.

---

## 19. Commands

- **`COMMAND_HANDLER`**: Emitted for CLI command decorators (`@app.command()`, `@click.command()`).
- Use `search_symbols` or `get_context` to locate the `COMMAND_HANDLER` and trace its downstream service calls.

---

## 20. Dependency Injection (DI)

CodeGraph models Dependency Injection through four dedicated relationship types—**never** collapsing DI into `CALLS`:

1. **`INJECTS`**: Consumer endpoint/class declares a dependency (`login_endpoint` -> `INJECTS` -> `get_auth_service`).
2. **`PROVIDES`**: Provider function or factory returns/yields the service type (`get_auth_service` -> `PROVIDES` -> `AuthService`).
3. **`RESOLVES_DEPENDENCY`**: Container or override binds an interface/token to a concrete implementation (`PaymentGateway` -> `RESOLVES_DEPENDENCY` -> `StripeGateway`).
4. **`CONFIGURES`**: Configuration symbol wires settings into a provider or container (`AuthConfig` -> `CONFIGURES` -> `get_auth_service`).

### Canonical DI Chain Example
```
POST /api/v1/auth/login
  --[HANDLED_BY (FRAMEWORK_VERIFIED)]--> login_endpoint
  --[INJECTS (FRAMEWORK_VERIFIED)]-----> get_auth_service
  --[PROVIDES (FRAMEWORK_VERIFIED)]----> AuthService
  --[BINDS_TO (DATAFLOW_VERIFIED)]-----> UserRepository
  --[CALLS (AST_VERIFIED)]-------------> UserRepository.find_by_email
```

- **FastAPI `Depends` & `Annotated`**: Both `svc: AuthService = Depends(get_auth_service)` and `Annotated[AuthService, Depends(get_auth_service)]` emit `INJECTS` and `PROVIDES`.
- **Router & App Dependencies**: `APIRouter(dependencies=[Depends(verify_api_key)])` attaches `INJECTS` edges at the router/route level.
- **Multiple Providers / Ambiguity**: When multiple providers can satisfy the same token (e.g., prod vs test container bindings), CodeGraph marks the binding `POSSIBLE` or `AMBIGUOUS`.
- **Cycles (`DI_CYCLE`)**: Circular provider dependencies (`A -> B -> A`) emit `DI_CYCLE` so debugging tools surface the cycle immediately.

---

## 21. Providers

When investigating a provider symbol (such as `get_db`, `get_current_user`, or a container factory):
- Call `resolve_symbol` -> `get_references(symbol=...)` or `get_context(query=..., intent="DEBUG")` to see:
  - What type the provider `PROVIDES`.
  - Which endpoints/services `INJECTS` the provider.
  - Which tests override or exercise the provider via `TESTS_PROVIDER`.

---

## 22. Package / Workspace Intelligence

CodeGraph detects monorepo and workspace boundaries strictly from **manifest evidence** (`package.json`, `pnpm-workspace.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`)—**never** from directory names like `apps/`, `packages/`, or `services/` alone.

- **Traversal Order**:
  `target package` -> `direct package dependencies (DEPENDS_ON_PACKAGE)` -> `bounded transitive dependencies (max_package_depth)`.
- **Key Concepts**:
  - **Owning Package**: The nearest manifest-backed package containing a file.
  - **Package ID & Type**: Canonical package identifier (e.g., `@acme/auth`) and manifest type (`npm`, `python`, `cargo`, `go`).
  - **Cross-Package Imports (`CROSS_PACKAGE_IMPORT`, `PACKAGE_IMPORTS`)**: Proven when a file in Package A imports a file/symbol owned by Package B.
  - **Unresolved External Dependency**: Third-party imports outside the workspace are recorded as external imports and never confused with internal workspace packages.

---

## 23. Tests

CodeGraph links tests to production symbols via `find_tests(symbol=...)` (and `find_related_tests(symbol=...)`) across five verified relationship types:
- `TESTS`: General verified test-to-symbol coverage link.
- `TESTS_SYMBOL`: Direct AST call or reference from a test function to a production symbol.
- `TESTS_ROUTE`: Test client request (`client.get("/api/...")`) matching an indexed route.
- `TESTS_PROVIDER`: Test fixture or dependency override targeting a DI provider.
- `TESTS_EVENT_HANDLER`: Test exercising an event listener, task handler, or command handler.

> **Hard Rule**: CodeGraph never fabricates test coverage from lexical filename similarity alone when static call/import/route/fixture evidence is absent.

---

## 24. Change Impact

Use `get_git_impact(base="HEAD~1", head="HEAD")` (for Git commit ranges) or `analyze_impact(symbol=..., max_depth=3)` (for planned symbol edits):
- Computes modified symbols, direct and transitive callers, affected routes, affected workspace packages, and covering tests.
- Combine `analyze_impact` with `find_tests` / `find_related_tests` before refactoring any public method signature.

---

## 25. Architecture

Use `get_architecture()` as the first tool for macro-level questions:
- Returns indexed modules, manifest-backed workspace packages, `DEPENDS_ON_PACKAGE` edges, entrypoints, and framework routes.
- Do not dump all files with `get_project_structure()` or read dozens of files when `get_architecture()` answers the structural question in one call.

---

## 26. Debugging

For bug investigations (`AgentTaskCategory.DEBUG`):
1. Ground the failing symbol or endpoint via `find_symbol` / `resolve_symbol` (or `find_routes` / `list_routes`).
2. Call `get_context(query=..., intent="DEBUG", max_tokens=4000)` to assemble the target definition, callers, callees, error paths, DI bindings, and related tests.
3. Call `get_file(path, start_line, end_line)` (or `read_file`) on the exact line range where the fault occurs to inspect statement-level logic.

---

## 27. Context Compilation

`get_context` compiles a token-bounded, coverage-optimized `ContextPacket`:

```
Repository -> Candidate Facts -> Task-Aware Filtering (RetrievalPolicy)
  -> Relationship-Aware Ranking -> Redundancy Elimination
  -> Coverage-Aware Selection -> ContextPacket
```

### Intent-Specific Retrieval Policies (`RETRIEVAL_POLICIES`)

| Intent | Max Depth | Preferred Coverage Flow | Allowed Relationships (Sample) |
| :--- | :--- | :--- | :--- |
| `ARCHITECTURE` | `1` | ENTRYPOINT -> SERVICE -> DATA -> EXTERNAL | `COMMAND_HANDLER`, `CONFIGURES`, `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `HANDLED_BY`, `IMPORTS`, ... |
| `CHANGE` | `3` | TARGET -> HANDLER -> SERVICE -> DATA -> TEST | `CALLED_BY`, `CALLS`, `COMMAND_HANDLER`, `CONFIGURES`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `DISPATCHES_TO`, ... |
| `DEBUG` | `3` | TARGET -> EXECUTION_PATH -> ERROR_PATH -> TEST | `CALLED_BY`, `CALLS`, `COMMAND_HANDLER`, `CONFIGURES`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `DISPATCHES_TO`, ... |
| `EXPLAIN` | `2` | TARGET -> DEFINITIONS -> DEPENDENCIES -> CALLERS_CALLEES | `CALLS`, `COMMAND_HANDLER`, `CONFIGURES`, `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `DISPATCHES_TO`, ... |
| `IMPACT` | `3` | TARGET -> CALLERS -> DEPENDENTS -> TEST | `CALLED_BY`, `CALLS`, `COMMAND_HANDLER`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `DISPATCHES_TO`, `EVENT_LISTENER`, `HANDLED_BY`, ... |
| `REFACTOR` | `2` | TARGET -> DEFINITIONS -> CALLERS_CALLEES -> TEST | `CALLS`, `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `EXTENDS`, `IMPLEMENTS`, `IMPORTS`, ... |
| `REVIEW` | `2` | TARGET -> HANDLER -> SERVICE -> TEST | `CALLED_BY`, `CALLS`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `HANDLED_BY`, `IMPORTS`, `INJECTS`, `POSSIBLE_CALLS`, ... |
| `TEST` | `2` | TEST -> TARGET -> DEFINITIONS -> DEPENDENCIES | `CALLS`, `COMMAND_HANDLER`, `DEFINES`, `DEPENDS_ON`, `EVENT_LISTENER`, `HANDLED_BY`, `IMPORTS`, `INJECTS`, ... |
| `TRACE` | `4` | ENTRYPOINT -> HANDLER -> SERVICE -> DATA -> TEST | `CALLS`, `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `DISPATCHES_TO`, `HANDLED_BY`, `IMPORTS`, `INJECTS`, ... |
| `UNDERSTAND` | `2` | TARGET -> DEFINITIONS -> DEPENDENCIES -> CALLERS_CALLEES | `CALLS`, `COMMAND_HANDLER`, `CONFIGURES`, `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `DEPENDS_ON_PACKAGE`, `DISPATCHES_TO`, ... |

- **Hard Invariants & Output Boundaries of `get_context`**:
  - Primary input is `query` (`task` is also supported as a string or `TaskSpec` dict alias).
  - Enforces strict output boundaries BEFORE MCP serialization: `max_tokens` (default `4000`, hard cap `20000`), `max_files` (default `15`, hard cap `30`), and `max_lines` (default `500`, hard cap `1500`).
  - Returns explicit budget metadata: `selected_tokens`, `candidate_tokens`, `selected_files`, `selected_lines`, `coverage_score`, and `truncated`.
  - Preserves `unknowns` and `ambiguities` explicitly—never drops uncertainty to save tokens.
  - Compresses duplicate `(source, target, relationship)` edges into a single record with `occurrence_count` and `supporting_locations`.
  - Enforces hierarchical exclusions (`TaskSpec.exclusions`).

---

## 28. Artifact Handling

CodeGraph classifies every file into an `ArtifactType`:
- **`SOURCE`**: Authored production source code (prioritized by default).
- **`TEST`**: Test suites and fixtures (included for test/debug/impact intents).
- **`CONFIG`**: Configuration and manifest files.
- **`GENERATED`**: Code-generated files (OpenAPI clients, protobufs, migrations)—suppressed by default unless requested.
- **`BUILD_ARTIFACT`**: Compiled outputs (`dist/`, `build/`, `.next/`).
- **`BUNDLE`** / **`MINIFIED`**: Webpack/Rollup/esbuild bundles and `.min.js` files.
- **`VENDOR`**: Third-party vendor trees (`vendor/`, `third_party/`).
- **`BINARY`** / **`UNKNOWN`**: Non-text or unrecognized files (never read by `get_file` or `read_file`).

**Agent Rule**: Always prefer authored `SOURCE` symbols over `GENERATED`, `BUNDLE`, `MINIFIED`, or `VENDOR` copies.

---

## 29. Source Reads (`get_file` & `read_file`)

- **Division of Labor**:
  - **CodeGraph** tells you **WHERE** symbols and literal strings live and **HOW** symbols relate across files (`file`, `start_line`, `end_line`, `relationship`, `evidence_class`).
  - **`get_file(path, start_line, end_line, max_lines)`** (or `read_file(path, start_line, end_line)`) tells you **EXACTLY** what implementation statements or template lines exist inside those lines.
- **Policy**:
  1. Never invent implementation details from graph edges alone.
  2. Use CodeGraph (`find_symbol`, `search_code`, `find_routes`, `get_context`) first to narrow a 500-file repository down to the 1–2 relevant files and exact line spans.
  3. Call `get_file(path, start_line=..., end_line=..., max_lines=200)` with bounded ranges across `.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, or `.md`.
  4. Never attempt to read `.env`, private keys (`id_rsa`, `.pem`), or credentials—CodeGraph blocks sensitive paths with `SecurityError`.

---

## 30. `UNKNOWN` Handling Workflow

When a CodeGraph tool returns `evidence_class="UNKNOWN"` or an entry in `unknowns`:
1. **Understand what could not be proven**: Read the `reason` field (e.g., dynamic `getattr`, `eval`, unindexed external call).
2. **Never claim absence**: Do **not** state "X does not call Y" or "no relationship exists." `UNKNOWN` means static analysis could not establish the relationship.
3. **Perform a targeted source read**: Call `get_file(path, start_line, end_line)` (or `read_file`) on the cited call site to inspect how the dynamic target is constructed.
4. **Preserve uncertainty**: If the target depends on runtime input or external configuration, report the relationship as statically `UNKNOWN` and explain the runtime condition.

---

## 31. `POSSIBLE` Handling Workflow

When a CodeGraph tool returns `evidence_class="POSSIBLE"` or `relationship="POSSIBLE_CALLS"`:
1. **Treat as a lead, not a proven fact**: Do not present `POSSIBLE` edges as `AST_VERIFIED` truth.
2. **Inspect supporting locations**: Check `file`, `start_line`, and `reason`.
3. **Verify with `get_file` / `read_file`**: Read the cited lines to confirm whether the conditional binding, interface implementation, or registry target applies to the user's scenario.
4. **Upgrade or reject**: Only make a definitive claim after source verification confirms the behavior.

---

## 32. `AMBIGUOUS` Handling Workflow

When `resolve_symbol`, `find_symbol`, `compile_task`, or `get_context` returns `ambiguity_state="AMBIGUOUS"`:
1. **Inspect `alternatives`**: Examine all candidate symbols returned in `alternatives` / `matches`.
2. **Compare `canonical_id` and `file`**: Check which workspace package and module each candidate belongs to.
3. **Check caller/route context**: If the prompt mentions a route, package, or caller, match the candidate in that scope.
4. **Never pick `candidates[0]` arbitrarily**: Only select a candidate when contextual evidence disambiguates it; otherwise report the ambiguity or ask the user to clarify.

---

## 33. Stale Index Handling

CodeGraph tracks repository index freshness via `generation` and `freshness` (`FRESH` vs `STALE`):
- **How to check**: Inspect the `freshness` field in `get_repository_status()`, `get_context()`, or interrogation tool outputs.
- **When `freshness == "STALE"`**:
  - One or more files on disk (`modified_files` / `deleted_files`) have changed since the index was built.
  - Do **not** present cached graph relationships from modified files as current truth.
  - Either verify the modified files directly with `get_file` / `read_file` or refresh the index (`codegraph index`).

---

## 34. MCP Profiles

CodeGraph supports six deterministic tool profiles (`codegraph mcp serve --profile <profile>`), including the focused 14-tool `agent` profile (`DISCOVERY`: `find_symbol`, `search_code`, `find_references`, `find_callers`, `find_callees`, `find_tests`, `find_routes`; `DETAILS`: `get_symbol`, `get_file`, `get_context`, `get_architecture`, `get_git_impact`; `GRAPH`: `trace_path`, `trace_flow`):

| Profile | Tool Count | Recommended Use Case | Included Tools |
| :--- | :--- | :--- | :--- |
| `agent` | `14` | Focused AI coding agent workflow across discovery, file inspection, context synthesis, and graph tracing | `find_callees`, `find_callers`, `find_references`, `find_routes`, `find_symbol`, `find_tests`, `get_architecture`, `get_context`, `get_file`, `get_git_impact`, `get_symbol`, `search_code`, `trace_flow`, `trace_path` |
| `core` | `13` | Simple symbol lookup, relationship queries, and low-overhead interrogation sessions | `get_architecture`, `get_callees`, `get_callers`, `get_dependents`, `get_file`, `get_git_impact`, `get_imports`, `get_references`, `get_symbol`, `list_routes`, `resolve_symbol`, `search_symbols`, `trace_path` |
| `graph` | `17` | Tracing, change-impact, test discovery, and architecture sessions | `analyze_impact`, `find_related_tests`, `get_architecture`, `get_call_graph`, `get_callees`, `get_callers`, `get_context`, `get_dependents`, `get_file`, `get_git_impact`, `get_imports`, `get_references`, `get_symbol`, `list_routes`, `resolve_symbol`, `search_symbols`, `trace_path` |
| `minimal` | `21` | Context-heavy coding sessions needing core interrogation plus get_context and read_file | `compile_task`, `find_symbol`, `get_architecture`, `get_callees`, `get_callers`, `get_context`, `get_dependents`, `get_file`, `get_git_impact`, `get_imports`, `get_references`, `get_repository_status`, `get_resource_status`, `get_symbol`, `list_routes`, `read_file`, `resolve_symbol`, `search_code`, `search_symbols`, `trace_path`, `verify_evidence` |
| `developer` | `34` | Full interactive development with impact analysis, test linking, and git history | `analyze_change_impact`, `analyze_impact`, `compile_task`, `find_callees`, `find_callers`, `find_references`, `find_related_tests`, `find_symbol`, `get_architecture`, `get_call_graph`, `get_callees`, `get_callers`, `get_context`, `get_dependents`, `get_evidence`, `get_file`, `get_file_history`, `get_git_impact`, `get_graph`, `get_imports`, `get_recent_changes`, `get_references`, `get_repository_status`, `get_resource_status`, `get_symbol`, `list_routes`, `plan_retrieval`, `read_file`, `resolve_symbol`, `search_code`, `search_symbols`, `trace_call`, `trace_path`, `verify_evidence` |
| `full` | `56` | Complete diagnostic, database intelligence, runtime reconciliation, benchmark, and repository administration sessions | `analyze_change_impact`, `analyze_impact`, `compile_task`, `find_callees`, `find_callers`, `find_db_callers`, `find_db_columns`, `find_db_models`, `find_db_queries`, `find_db_readers`, `find_db_relationships`, `find_db_tables`, `find_db_writers`, `find_references`, `find_related_tests`, `find_routes`, `find_symbol`, `find_tests`, `get_architecture`, `get_call_graph`, `get_callees`, `get_callers`, `get_context`, `get_db_impact`, `get_db_schema`, `get_db_table`, `get_dependencies`, `get_dependency_graph`, `get_dependents`, `get_evidence`, `get_file`, `get_file_history`, `get_file_symbols`, `get_git_impact`, `get_graph`, `get_imports`, `get_project_structure`, `get_recent_changes`, `get_references`, `get_repository_status`, `get_resource_status`, `get_runtime_trace`, `get_symbol`, `ingest_runtime_traces`, `list_routes`, `plan_retrieval`, `read_file`, `reconcile_static_runtime`, `resolve_symbol`, `search_code`, `search_memory`, `search_symbols`, `trace_call`, `trace_flow`, `trace_path`, `verify_evidence` |

---

## 35. Fallback Behavior

CodeGraph defines deterministic fallback rules (`evaluate_fallback_policy` in `src/codegraph/agent_capabilities.py`):

| Condition | Epistemic Status | Fallback Allowed? | Required Agent Action |
| :--- | :--- | :--- | :--- |
| MCP `DISCONNECTED` / `SERVER_FAILED` | `DISCONNECTED` | `True` | Use direct repository search and `read_file`; verify claims manually. |
| Index `freshness == "STALE"` | `STALE` | `True` | Verify modified files with `get_file` / `read_file` or re-index before relying on stale edges. |
| `ambiguity_state == "AMBIGUOUS"` | `AMBIGUOUS` | `True` | Inspect `alternatives` and disambiguate by module/package; never guess `matches[0]`. |
| `evidence_class == "UNKNOWN"` | `UNKNOWN` | `True` | Treat as unprovable statically (NOT "no relationship"); inspect call site with `get_file` / `read_file`. |
| `evidence_class == "POSSIBLE"` | `POSSIBLE` | `True` | Report as candidate lead and confirm via targeted `get_file` / `read_file`. |
| `AST_VERIFIED` / `FRAMEWORK_VERIFIED` / `DATAFLOW_VERIFIED` | `VERIFIED` | `False` | Rely on verified CodeGraph evidence; use `get_file` / `read_file` only if statement-level details are needed. |

---

## 36. Error Handling

- **Invalid Arguments (`ValueError`)**: Raised when required inputs (e.g., `query`, `symbol`, `task`) are empty or conflicting aliases (`symbol` vs `canonical_id`, `query` vs `task`) disagree. Fix the argument and retry once.
- **Sensitive Path Blocked (`SecurityError`)**: Raised when attempting to read `.env`, `.pem`, `id_rsa`, credentials, or paths outside the repository root. Never attempt to bypass security boundaries.
- **Symbol Not Found (`status="not_found"` / `UNKNOWN`)**: Do not retry `resolve_symbol` with the exact same spelling; call `search_symbols(query=...)` or `search_code(query=...)` with a broader stem.

---

## 37. Anti-Patterns

Never commit any of the following 14 anti-patterns:

1. **Using CodeGraph for trivial one-line edits (`LOCAL_EDIT`)**: Calling `get_context` or `resolve_symbol` just to fix a typo in an already-known file.
2. **Calling all tools indiscriminately**: Invoking 6+ CodeGraph tools when `find_symbol` -> `find_callers` or a single `get_context` call suffices.
3. **Repeated symbol resolution**: Calling `resolve_symbol(symbol="X")` multiple times after `canonical_id` is already known.
4. **Reading the entire repository first**: Calling `get_file` / `read_file` across 10+ files before asking CodeGraph for symbol locations, text matches, or relationships.
5. **Treating `UNKNOWN` as absent**: Claiming "Function A does not call Function B" when CodeGraph reported `UNKNOWN` due to dynamic dispatch.
6. **Treating `POSSIBLE` as verified**: Reporting a `POSSIBLE` edge as a guaranteed `AST_VERIFIED` fact without reading the cited lines.
7. **Choosing the first ambiguous candidate (`matches[0]`)**: Arbitrarily picking the first match when `ambiguity_state == "AMBIGUOUS"`.
8. **Treating `REGISTERS` as `CALLS`**: Claiming a module calls a handler merely because it registers the handler into a dictionary or decorator registry.
9. **Treating DI (`INJECTS` / `PROVIDES`) as `CALLS`**: Confusing framework dependency injection with direct function invocation.
10. **Trusting a `STALE` index**: Presenting cached relationships from files modified on disk without checking `get_file` / `read_file` or re-indexing.
11. **Trusting generated/bundle matches over authored source**: Citing `dist/bundle.js` or generated client code when authored `SOURCE` exists.
12. **Ignoring package boundaries**: Inferring monorepo packages from folder names (`apps/`, `packages/`) without checking `DEPENDS_ON_PACKAGE` manifest evidence.
13. **Continuing graph traversal after sufficient evidence**: Expanding further hops after the question is already answered with verified evidence.
14. **Using lexical similarity (`search_code`) as causal proof**: Claiming a test covers a symbol or a function calls another based solely on matching words in `search_code`.

---

## 38. Tool Sequences (Tool Chain Playbook)

Every tool chain has an explicit **STOP condition**:

1. **SYMBOL LOOKUP**:
   `find_symbol` / `resolve_symbol` (or `search_symbols` if partial) -> `get_symbol` (if signature/decorators needed) -> **STOP** once canonical file, line span, and signature are known.
2. **TEXT / TEMPLATE / UI DISCOVERY**:
   `search_code(query=...)` -> `get_file(path=..., start_line=..., end_line=...)` -> **STOP** once the target template/config/text lines are inspected.
3. **CALLERS**:
   `find_symbol` -> `find_callers` (or `get_callers`) -> **STOP** once verified callers are listed (use `get_file` only if call-site arguments need inspection).
4. **CALLEES**:
   `find_symbol` -> `find_callees` (or `get_callees`) -> **STOP** once outgoing calls are listed.
5. **TRACE**:
   `find_routes` / `list_routes` (if starting from HTTP endpoint) -> `find_symbol` -> `trace_path` -> `get_context(intent="TRACE")` (only if broader hop context is needed) -> targeted `get_file` (only if branch conditions matter) -> **STOP**.
6. **DEBUG**:
   `find_symbol` -> `get_context(intent="DEBUG")` -> targeted `get_file(path, start_line, end_line)` on fault line span -> **STOP**.
7. **CHANGE IMPACT**:
   `find_symbol` -> `analyze_impact` (or `get_git_impact` for commit diffs) -> `find_tests` / `find_related_tests` -> targeted `get_file` on direct callers to update -> **STOP**.
8. **DEPENDENCY INJECTION (DI)**:
   `find_symbol` -> `get_context(intent="DEBUG")` (or `get_references`) -> inspect `INJECTS` -> `PROVIDES` -> `RESOLVES_DEPENDENCY` -> `find_tests` (`TESTS_PROVIDER`) -> **STOP**.
9. **ARCHITECTURE & PACKAGES**:
   `get_architecture` -> `get_context(intent="ARCHITECTURE")` (or `get_imports` / `get_dependents` for specific package) -> **STOP**.
10. **TEST DISCOVERY**:
    `find_symbol` -> `find_tests` / `find_related_tests` -> **STOP** once covering test functions and `TESTS_*` evidence classes are returned.

---

## 39. Complex Workflows (25 Canonical End-to-End Playbooks)

### Workflow 1: Authentication route trace
- **Developer request**: "Trace how POST /api/v1/auth/login authenticates a user and queries the database."
- **Task classification**: `TRACE`
- **Why CodeGraph is appropriate**: Route strings may be split across mounted routers (`MOUNTS`), handlers (`HANDLED_BY`), DI providers (`INJECTS`/`PROVIDES`), and services (`CALLS`).
- **First tool**: `list_routes`
- **Arguments**: `list_routes(method="POST", path="/api/v1/auth/login")`
- **Expected result interpretation**: Identify `handler_name` (e.g., `login_endpoint`), `canonical_id`, and `evidence_class='FRAMEWORK_VERIFIED'`.
- **Follow-up tool**: `trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)`
- **Stop condition**: Stop once the ordered hop chain from `POST /api/v1/auth/login` -> `login_endpoint` -> `AuthService.authenticate` -> `UserRepository.find_by_email` is verified.
- **Source-read fallback**: Call `read_file(path="src/auth/service.py", start_line=10, end_line=40)` only if password comparison branch details are needed.
- **Final evidence handling**: Cite each hop with its relationship (`HANDLED_BY`, `INJECTS`, `CALLS`) and `evidence_class`.

### Workflow 2: Login handler -> service -> repository
- **Developer request**: "How does login_endpoint reach UserRepository.find_by_email?"
- **Task classification**: `TRACE`
- **Why CodeGraph is appropriate**: Both endpoint and target symbol names are known, making multi-hop graph path tracing deterministic.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="login_endpoint")`
- **Expected result interpretation**: Confirm canonical ID `src/auth/routes.py:login_endpoint` and `ambiguity_state='CLEAR'`.
- **Follow-up tool**: `trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)`
- **Stop condition**: Stop as soon as `trace_path` returns the verified hop chain connecting the two symbols.
- **Source-read fallback**: If any hop is marked `POSSIBLE`, use `read_file` on that hop's `file` and `start_line`.
- **Final evidence handling**: Present the exact hop sequence with file:line coordinates.

### Workflow 3: DI provider resolution
- **Developer request**: "Which provider supplies AuthService to login_endpoint?"
- **Task classification**: `DEBUG`
- **Why CodeGraph is appropriate**: CodeGraph extracts `INJECTS`, `PROVIDES`, and `RESOLVES_DEPENDENCY` relationships without collapsing them into `CALLS`.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="login_endpoint")`
- **Expected result interpretation**: Obtain canonical ID for `login_endpoint`.
- **Follow-up tool**: `get_context(query="Which provider supplies AuthService to login_endpoint", intent="DEBUG", max_tokens=4000)`
- **Stop condition**: Stop when `INJECTS` (`login_endpoint` -> `get_auth_service`) and `PROVIDES` (`get_auth_service` -> `AuthService`) edges are retrieved.
- **Source-read fallback**: Call `read_file` on `dependencies.py` only if constructor arguments inside `get_auth_service` need inspection.
- **Final evidence handling**: Distinguish `INJECTS` and `PROVIDES` (`FRAMEWORK_VERIFIED`) from direct `CALLS`.

### Workflow 4: FastAPI dependency chain
- **Developer request**: "Trace the FastAPI Depends() chain from get_current_active_user down to get_db_session."
- **Task classification**: `DEBUG`
- **Why CodeGraph is appropriate**: Nested FastAPI `Depends()` parameters form multi-hop `INJECTS` and `PROVIDES` chains across files.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="get_current_active_user")`
- **Expected result interpretation**: Confirm canonical definition of `get_current_active_user`.
- **Follow-up tool**: `get_context(query="FastAPI dependency chain get_current_active_user to get_db_session", intent="DEBUG", max_tokens=4000)`
- **Stop condition**: Stop when all nested `INJECTS`/`PROVIDES` hops to `get_db_session` are present in the `ContextPacket`.
- **Source-read fallback**: Use `read_file` on `get_current_active_user` lines if HTTPException status codes are needed.
- **Final evidence handling**: Report each nested dependency link with its `FRAMEWORK_VERIFIED` evidence class.

### Workflow 5: Registry handler lookup
- **Developer request**: "What handlers are registered in command_registry and where does command_registry dispatch?"
- **Task classification**: `RELATIONSHIP`
- **Why CodeGraph is appropriate**: CodeGraph tracks `REGISTERS`, `REGISTERED_HANDLER`, and `DISPATCHES_TO` distinctly from `CALLS`.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="command_registry")`
- **Expected result interpretation**: Resolve canonical ID of `command_registry`.
- **Follow-up tool**: `get_references(symbol="command_registry")`
- **Stop condition**: Stop once all `REGISTERS` and `DISPATCHES_TO` edges referencing `command_registry` are listed.
- **Source-read fallback**: If any registration is conditional (`POSSIBLE`), read the cited registration lines with `read_file`.
- **Final evidence handling**: Never report `REGISTERS` edges as direct `CALLS`; preserve `REGISTERS` and `DISPATCHES_TO` labels.

### Workflow 6: Event listener discovery
- **Developer request**: "Which event listeners subscribe to OrderCreated across the repository?"
- **Task classification**: `RELATIONSHIP`
- **Why CodeGraph is appropriate**: Event listeners are decoupled from publishers and connected via `EVENT_LISTENER` edges.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="OrderCreated")`
- **Expected result interpretation**: Obtain canonical ID of the `OrderCreated` event symbol.
- **Follow-up tool**: `get_references(symbol="OrderCreated")`
- **Stop condition**: Stop after collecting all `EVENT_LISTENER` and `DISPATCHES_TO` edges tied to `OrderCreated`.
- **Source-read fallback**: Use `read_file` on listener spans if side-effect details (e.g., email template) are needed.
- **Final evidence handling**: Cite each listener with `EVENT_LISTENER` and its `evidence_class`.

### Workflow 7: Celery task tracing
- **Developer request**: "Trace how Celery task send_welcome_email is registered and what SMTP client it calls."
- **Task classification**: `TRACE`
- **Why CodeGraph is appropriate**: Celery tasks combine `TASK_HANDLER` decorator semantics with downstream `CALLS` edges.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="send_welcome_email")`
- **Expected result interpretation**: Locate `send_welcome_email` definition and confirm `TASK_HANDLER` metadata.
- **Follow-up tool**: `get_callees(symbol="send_welcome_email")`
- **Stop condition**: Stop once downstream `CALLS` to the SMTP client symbol are identified.
- **Source-read fallback**: Call `read_file` on the task function span if retry/backoff decorator arguments are needed.
- **Final evidence handling**: Report `TASK_HANDLER` (`FRAMEWORK_VERIFIED`) for task registration and `CALLS` (`AST_VERIFIED`) for outgoing calls.

### Workflow 8: CLI command handler lookup
- **Developer request**: "Which function handles the CLI command `mcp doctor`?"
- **Task classification**: `SYMBOL_LOOKUP`
- **Why CodeGraph is appropriate**: CLI commands decorated with `@app.command` or `@mcp_app.command` produce `COMMAND_HANDLER` and symbol definitions.
- **First tool**: `search_symbols`
- **Arguments**: `search_symbols(query="mcp_doctor", top_k=10)`
- **Expected result interpretation**: Locate the CLI command handler symbol and its file/line coordinates.
- **Follow-up tool**: `get_symbol(symbol="src/codegraph/cli.py:mcp_doctor")`
- **Stop condition**: Stop once the command handler signature, decorators, and callees are identified.
- **Source-read fallback**: Use `read_file` on the handler line range if CLI option defaults need inspection.
- **Final evidence handling**: Cite `COMMAND_HANDLER` / `DEFINES` evidence with exact file and line numbers.

### Workflow 9: Related tests discovery
- **Developer request**: "What tests cover BillingService.charge_card?"
- **Task classification**: `TEST_DISCOVERY`
- **Why CodeGraph is appropriate**: `find_related_tests` uses static call, import, fixture, and route links (`TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`) without lexical guessing.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="BillingService.charge_card")`
- **Expected result interpretation**: Confirm canonical ID of `BillingService.charge_card`.
- **Follow-up tool**: `find_related_tests(symbol="BillingService.charge_card")`
- **Stop condition**: Stop when the statically linked test functions and their linking relationships are returned.
- **Source-read fallback**: Call `read_file` on a returned test function only if specific assertion values need inspection.
- **Final evidence handling**: Report each test with its specific link type (`TESTS_SYMBOL`, `TESTS_ROUTE`, etc.) and `evidence_class`.

### Workflow 10: Change impact analysis on Git range
- **Developer request**: "Analyze the blast radius and affected tests for commits between HEAD~1 and HEAD."
- **Task classification**: `CHANGE_IMPACT`
- **Why CodeGraph is appropriate**: `get_git_impact` maps Git diff hunks to AST symbol spans, downstream callers, workspace packages, and covering tests.
- **First tool**: `get_git_impact`
- **Arguments**: `get_git_impact(base="HEAD~1", head="HEAD")`
- **Expected result interpretation**: Inspect `modified_symbols`, `impacted_callers`, `affected_packages`, and `related_tests`.
- **Follow-up tool**: `find_related_tests (only if additional transitive symbol tests are needed)`
- **Stop condition**: Stop when `get_git_impact` returns the complete modified symbol, caller, package, and test sets.
- **Source-read fallback**: Use `read_file` on modified symbol spans if exact diff logic needs line-by-line review.
- **Final evidence handling**: Present modified symbols, affected callers/packages, and static test coverage links.

### Workflow 11: Package dependency inspection
- **Developer request**: "What workspace packages does @acme/orders depend on in this monorepo?"
- **Task classification**: `PACKAGE`
- **Why CodeGraph is appropriate**: CodeGraph derives `DEPENDS_ON_PACKAGE` and `CROSS_PACKAGE_IMPORT` from actual manifest files (`package.json`, `pyproject.toml`, etc.).
- **First tool**: `get_architecture`
- **Arguments**: `get_architecture()`
- **Expected result interpretation**: Inspect `packages` and `package_dependencies` for `@acme/orders`.
- **Follow-up tool**: `get_context(query="workspace package dependencies of @acme/orders", intent="ARCHITECTURE", max_tokens=4000)`
- **Stop condition**: Stop once direct and bounded transitive `DEPENDS_ON_PACKAGE` edges for `@acme/orders` are identified.
- **Source-read fallback**: Read `packages/orders/package.json` via `read_file` only if exact version semver strings are needed.
- **Final evidence handling**: Cite manifest-backed `DEPENDS_ON_PACKAGE` edges; never infer packages from directory names alone.

### Workflow 12: Monorepo architecture overview
- **Developer request**: "Explain the overall package boundaries, services, and entrypoints of this monorepo."
- **Task classification**: `ARCHITECTURE`
- **Why CodeGraph is appropriate**: `get_architecture` summarizes manifest-verified packages, entrypoints, routes, and inter-package dependencies in one call.
- **First tool**: `get_architecture`
- **Arguments**: `get_architecture()`
- **Expected result interpretation**: Review `packages`, `package_dependencies`, `entrypoints`, and `routes`.
- **Follow-up tool**: `get_context(query="monorepo architecture overview and entrypoints", intent="ARCHITECTURE", max_tokens=4000)`
- **Stop condition**: Stop after `get_architecture` (and optional `get_context`) provides the package and entrypoint topology.
- **Source-read fallback**: Avoid reading dozens of files; only read top-level manifest if workspace globs need manual check.
- **Final evidence handling**: Report manifest-verified packages and entrypoints with their `AST_VERIFIED`/`FRAMEWORK_VERIFIED` evidence.

### Workflow 13: Ambiguous symbol disambiguation
- **Developer request**: "What calls validate() in the payments module?"
- **Task classification**: `RELATIONSHIP`
- **Why CodeGraph is appropriate**: Generic method names like `validate` often exist in multiple classes; `resolve_symbol` surfaces `AMBIGUOUS` alternatives explicitly.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="validate")`
- **Expected result interpretation**: Observe `ambiguity_state='AMBIGUOUS'` and inspect `alternatives` for the candidate in the `payments` module/package.
- **Follow-up tool**: `get_callers(symbol="src/payments/validator.py:PaymentValidator.validate")`
- **Stop condition**: Stop once callers of the disambiguated `canonical_id` are returned (or report ambiguity if context is insufficient).
- **Source-read fallback**: Use `read_file` on candidate definitions if module names alone do not disambiguate.
- **Final evidence handling**: Never pick `matches[0]` blindly; state how the canonical symbol was disambiguated.

### Workflow 14: UNKNOWN dynamic dispatch handling
- **Developer request**: "What function does run_dynamic_hook(hook_name) call?"
- **Task classification**: `RELATIONSHIP`
- **Why CodeGraph is appropriate**: Dynamic `getattr(hooks, hook_name)()` cannot be proven statically and is surfaced as `POSSIBLE_CALLS` / `UNRESOLVED_REFERENCE` with `evidence_class='UNKNOWN'`.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="run_dynamic_hook")`
- **Expected result interpretation**: Locate `run_dynamic_hook` canonical ID and line span.
- **Follow-up tool**: `get_callees(symbol="run_dynamic_hook")`
- **Stop condition**: Observe `evidence_class='UNKNOWN'` (or empty static callees with `unknowns` in `get_context`), then perform one targeted `read_file`.
- **Source-read fallback**: Call `read_file(path="src/hooks/runner.py", start_line=1, end_line=50)` to inspect the `getattr` dispatch mechanism.
- **Final evidence handling**: State clearly that static analysis returned `UNKNOWN` due to runtime `getattr`; never claim 'run_dynamic_hook calls nothing'.

### Workflow 15: POSSIBLE registry target verification
- **Developer request**: "Which handler does dispatch_webhook invoke when event_type is conditional?"
- **Task classification**: `TRACE`
- **Why CodeGraph is appropriate**: Conditional or multi-branch registry bindings are labeled `evidence_class='POSSIBLE'` so the agent treats them as leads to verify.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="dispatch_webhook")`
- **Expected result interpretation**: Resolve `dispatch_webhook` canonical ID.
- **Follow-up tool**: `get_context(query="dispatch_webhook handler targets", intent="TRACE", max_tokens=4000)`
- **Stop condition**: Identify `DISPATCHES_TO` edges marked `POSSIBLE`, then verify the branch condition via targeted `read_file`.
- **Source-read fallback**: Call `read_file` on the cited registration/dispatch lines to check the `if/elif` or dict lookup condition.
- **Final evidence handling**: Report the target as `POSSIBLE` until confirmed by the targeted source read.

### Workflow 16: Generated and bundle code suppression
- **Developer request**: "Where is UserClient defined? Ignore generated SDKs and minified bundles."
- **Task classification**: `SYMBOL_LOOKUP`
- **Why CodeGraph is appropriate**: CodeGraph classifies files into `SOURCE`, `TEST`, `GENERATED`, `BUNDLE`, `MINIFIED`, `VENDOR`, and `BUILD_ARTIFACT` and prioritizes authored `SOURCE`.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="UserClient")`
- **Expected result interpretation**: Verify that the primary resolved symbol comes from authored `SOURCE` rather than `dist/` or `generated/`.
- **Follow-up tool**: `get_file(path="src/client/user_client.ts")`
- **Stop condition**: Stop once the authored `SOURCE` definition is confirmed.
- **Source-read fallback**: Use `read_file` on the authored source file only if implementation lines are needed.
- **Final evidence handling**: Prefer `SOURCE` artifacts; note if duplicate generated/bundle copies were suppressed.

### Workflow 17: Stale index detection and fallback
- **Developer request**: "After editing src/auth/service.py on disk, check what AuthService.authenticate calls."
- **Task classification**: `DIAGNOSTIC`
- **Why CodeGraph is appropriate**: `get_repository_status` and tool responses report `freshness='STALE'` when on-disk files have changed since the last index generation.
- **First tool**: `get_repository_status`
- **Arguments**: `get_repository_status()`
- **Expected result interpretation**: Observe `freshness='STALE'` and `modified_files=['src/auth/service.py']`.
- **Follow-up tool**: `read_file(path="src/auth/service.py", start_line=1, end_line=100)`
- **Stop condition**: Stop after verifying the modified file directly with `read_file` (or re-indexing via CLI).
- **Source-read fallback**: Always use `read_file` on files listed in `modified_files` when `freshness == 'STALE'`.
- **Final evidence handling**: Do not present stale cached graph edges from modified files as current truth without verifying on-disk lines.

### Workflow 18: Debugging a runtime exception across files
- **Developer request**: "Debug why PaymentProcessor.capture raises CurrencyMismatchError during checkout."
- **Task classification**: `DEBUG`
- **Why CodeGraph is appropriate**: `get_context(intent='DEBUG')` gathers the target method, upstream callers, downstream callees, DI providers, and covering tests in one bounded packet.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="PaymentProcessor.capture")`
- **Expected result interpretation**: Confirm canonical ID and file:line location of `PaymentProcessor.capture`.
- **Follow-up tool**: `get_context(query="Debug CurrencyMismatchError in PaymentProcessor.capture", intent="DEBUG", max_tokens=4000)`
- **Stop condition**: Stop graph interrogation once `ContextPacket` provides callers (`process_checkout`) and callees; read exact exception line if needed.
- **Source-read fallback**: Call `read_file` on the exact line range of `PaymentProcessor.capture` and `process_checkout` where currency is passed.
- **Final evidence handling**: Combine verified caller/callee graph evidence with the exact source lines raising the exception.

### Workflow 19: Refactoring a shared symbol safely
- **Developer request**: "We want to add a required `tenant_id` parameter to OrderRepository.save. What needs to be updated?"
- **Task classification**: `CHANGE_IMPACT`
- **Why CodeGraph is appropriate**: `analyze_impact` computes direct callers, transitive callers, affected routes, dependent files, and related tests.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="OrderRepository.save")`
- **Expected result interpretation**: Confirm canonical ID `OrderRepository.save`.
- **Follow-up tool**: `analyze_impact(symbol="OrderRepository.save", max_depth=3)`
- **Stop condition**: Stop graph traversal once `direct_callers`, `affected_routes`, and `related_tests` are enumerated.
- **Source-read fallback**: Use `read_file` on each direct caller's call-site line span to plan the parameter update.
- **Final evidence handling**: List every direct caller, affected route, and test file with exact line coordinates.

### Workflow 20: Finding affected tests before a commit
- **Developer request**: "Which pytest tests should we run after modifying TokenValidator.verify?"
- **Task classification**: `TEST_DISCOVERY`
- **Why CodeGraph is appropriate**: `find_related_tests` identifies tests linked via `TESTS_SYMBOL`, `TESTS_ROUTE`, or `TESTS_PROVIDER`.
- **First tool**: `resolve_symbol`
- **Arguments**: `resolve_symbol(symbol="TokenValidator.verify")`
- **Expected result interpretation**: Confirm canonical ID of `TokenValidator.verify`.
- **Follow-up tool**: `find_related_tests(symbol="TokenValidator.verify", max_results=20)`
- **Stop condition**: Stop as soon as the linked test functions and files are returned.
- **Source-read fallback**: No `read_file` needed unless a test fails and its assertion lines must be inspected.
- **Final evidence handling**: Return the list of test functions and their static evidence classes.

### Workflow 21: Route-to-provider-to-repository trace
- **Developer request**: "Trace GET /api/v1/users/me through its FastAPI dependency provider to the database repository."
- **Task classification**: `TRACE`
- **Why CodeGraph is appropriate**: Connects `HANDLED_BY` -> `INJECTS` -> `PROVIDES` -> `CALLS` across multiple files.
- **First tool**: `list_routes`
- **Arguments**: `list_routes(method="GET", path="/api/v1/users/me")`
- **Expected result interpretation**: Identify the route handler symbol (e.g., `get_me_endpoint`).
- **Follow-up tool**: `get_context(query="Trace GET /api/v1/users/me handler dependency provider and repository", intent="TRACE", max_tokens=4000)`
- **Stop condition**: Stop once the route, handler, injected provider (`get_current_user`), and repository call are present in the packet.
- **Source-read fallback**: Use `read_file` only if token parsing details inside `get_current_user` are needed.
- **Final evidence handling**: Present the complete chain preserving `HANDLED_BY`, `INJECTS`, `PROVIDES`, and `CALLS`.

### Workflow 22: Architecture explanation for onboarding
- **Developer request**: "Give a concise architectural overview of this service, its entrypoints, and its core modules."
- **Task classification**: `ARCHITECTURE`
- **Why CodeGraph is appropriate**: `get_architecture` provides a deterministic structural summary without scanning every file manually.
- **First tool**: `get_architecture`
- **Arguments**: `get_architecture()`
- **Expected result interpretation**: Inspect modules, entrypoints, routes, and package boundaries.
- **Follow-up tool**: `list_routes() (if detailed HTTP endpoint inventory is desired)`
- **Stop condition**: Stop once high-level modules, entrypoints, and routes are summarized.
- **Source-read fallback**: Do not read individual implementation files unless asked about a specific module.
- **Final evidence handling**: Summarize the architecture using only AST- and manifest-verified facts.

### Workflow 23: Large repository multi-file feature investigation
- **Developer request**: "Where is rate limiting implemented and how is it wired into API endpoints?"
- **Task classification**: `MULTI_FILE_INVESTIGATION`
- **Why CodeGraph is appropriate**: Combining `search_symbols` -> `resolve_symbol` -> `get_context` avoids blind grep across hundreds of files.
- **First tool**: `search_symbols`
- **Arguments**: `search_symbols(query="rate_limit", top_k=10)`
- **Expected result interpretation**: Identify the primary rate limiter class/dependency (e.g., `RateLimiter` or `check_rate_limit`).
- **Follow-up tool**: `get_context(query="How rate limiting is implemented and wired into API endpoints", intent="UNDERSTAND", max_tokens=4000)`
- **Stop condition**: Stop when the rate limiter definition, its `INJECTS`/`CALLS` usages on routes, and tests are in the `ContextPacket`.
- **Source-read fallback**: Use `read_file` on the rate limiter algorithm lines if token-bucket math details are requested.
- **Final evidence handling**: Cite definition coordinates and route wiring edges (`INJECTS` / `CALLS`).

### Workflow 24: One-file local edit bypass
- **Developer request**: "Fix a typo in the docstring of format_currency in src/utils/money.py."
- **Task classification**: `LOCAL_EDIT`
- **Why CodeGraph is appropriate**: CodeGraph is NOT needed for trivial single-file edits where relationships do not matter.
- **First tool**: `read_file`
- **Arguments**: `read_file(path="src/utils/money.py", start_line=1, end_line=60)`
- **Expected result interpretation**: Read the exact docstring lines of `format_currency`.
- **Follow-up tool**: `None (apply edit directly)`
- **Stop condition**: Stop immediately after reading the target lines and applying the edit; make 0 graph calls.
- **Source-read fallback**: Direct `read_file` is the primary tool for `LOCAL_EDIT`.
- **Final evidence handling**: Confirm the docstring edit directly in `src/utils/money.py`.

### Workflow 25: MCP unavailable or disconnected fallback
- **Developer request**: "Find all callers of verify_token when the CodeGraph MCP server is offline."
- **Task classification**: `RELATIONSHIP`
- **Why CodeGraph is appropriate**: Normally handled by `resolve_symbol` -> `get_callers`, but when MCP is `DISCONNECTED` or `SERVER_FAILED`, safe fallback rules apply.
- **First tool**: `read_file`
- **Arguments**: `read_file(path="src/auth/tokens.py", start_line=1, end_line=120)`
- **Expected result interpretation**: Recognize MCP unavailability (`evaluate_fallback_policy(mcp_state='DISCONNECTED')`), use workspace search/targeted `read_file`.
- **Follow-up tool**: `Targeted `read_file` on candidate caller files found via search`
- **Stop condition**: Stop once candidate call sites are manually inspected in source files.
- **Source-read fallback**: Direct search + `read_file` is the required fallback when MCP is disconnected.
- **Final evidence handling**: Explicitly note that results were verified via direct source inspection while CodeGraph MCP was offline.


---

## 40. Troubleshooting

| Symptom / Diagnostic Issue | Root Cause | Resolution |
| :--- | :--- | :--- |
| `codegraph mcp doctor` reports `COMMAND_NOT_FOUND` | The `codegraph` binary is not on the environment `PATH` used by the IDE/agent. | Install the wheel (`pip install codegraph-engine`) or point `mcpServers.codegraph.command` to the venv's `codegraph` executable. |
| `get_repository_status` reports `files_indexed: 0` | Repository has not been indexed yet. | Run `codegraph index` in the repository root. |
| `freshness` is `"STALE"` | Source files were edited or deleted after the last index run. | Run `codegraph index` or use `get_file` / `read_file` on `modified_files`. |
| `resolve_symbol` / `find_symbol` returns `ambiguity_state="AMBIGUOUS"` | Multiple symbols share the same short name across modules/packages. | Pass the qualified name (`module.Class.method`) or select the matching `canonical_id` from `alternatives`. |
| `get_file` / `read_file` raises `SecurityError` | Requested path is outside the repository, is a sensitive credential file (`.env`, `.pem`), or exceeds `max_read_bytes`. | Do not read sensitive or out-of-tree files; inspect safe source files only. |
| Route not found in `search_code` | Route path is composed across `include_router(..., prefix=...)` mounts. | Use `find_routes()` / `list_routes()` which composes `MOUNTS` prefixes deterministically. |

---

## 41. Complete Tool Reference (All 56 Exposed MCP Tools)

### `analyze_change_impact`

- **Capability**: `git_range_change_impact`
- **Profiles**: `developer`, `full`
- **Task Categories**: `CHANGE_IMPACT`, `TEST_DISCOVERY`

#### Purpose
Analyze changed files, modified symbols, downstream callers, and related tests between Git refs `since` and `until`. Use for commit-range impact analysis when `since`/`until` parameter naming is preferred. Does not execute tests at runtime.

#### Use when
- Analyzing blast radius of commits between `since` and `until`

#### Avoid when
- Analyzing impact of a hypothetical edit not yet in Git (use analyze_impact instead)

#### Required inputs
None

#### Optional inputs
`since`, `until`

#### Minimal invocation
```python
analyze_change_impact()
```

#### Advanced invocation
```python
analyze_change_impact(since="HEAD~2", until="HEAD")
```

#### Result interpretation
- **Output Type**: `ChangeImpactReport`
- **Key Fields**: `changed_files`, `modified_symbols`, `callers`, `related_tests`
- **Relationships Emitted**: `CALLS`, `TESTS`, `IMPORTS`

#### Evidence meaning
Git diff mapped to indexed symbols, callers, and related tests.

#### Non-guarantees
Does not prove runtime test pass/fail status.

#### Typical follow-up
find_related_tests or read_file

#### Common mistakes
- Calling both get_git_impact and analyze_change_impact on the same commit range

#### Example
- **Developer request**: "Analyze change impact between HEAD~2 and HEAD."
- **Call**: `analyze_change_impact(since="HEAD~2", until="HEAD")`
- **Interpretation**: Inspect modified_symbols, downstream callers, and related_tests.

### `analyze_impact`

- **Capability**: `symbol_blast_radius`
- **Profiles**: `graph`, `developer`, `full`
- **Task Categories**: `CHANGE_IMPACT`, `TEST_DISCOVERY`

#### Purpose
Compute downstream callers, dependents, affected routes, and related tests if a symbol (`symbol`; `canonical_id` supported as alias) is modified. Use before refactoring or changing a function/class signature. Does not prove runtime failure without inspecting call sites.

#### Use when
- Evaluating blast radius of a signature or behavior change to a symbol

#### Avoid when
- Adding a brand-new standalone helper with no existing callers

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `max_depth`

#### Minimal invocation
```python
analyze_impact(symbol="DatabasePool.acquire")
```

#### Advanced invocation
```python
analyze_impact(symbol="DatabasePool.acquire", max_depth=4)
```

#### Result interpretation
- **Output Type**: `SymbolImpactResult`
- **Key Fields**: `symbol`, `direct_callers`, `transitive_callers`, `dependent_files`, `affected_routes`, `related_tests`
- **Relationships Emitted**: `CALLS`, `CALLED_BY`, `IMPORTS`, `HANDLED_BY`, `TESTS`, `DEPENDS_ON_PACKAGE`

#### Evidence meaning
Multi-hop reverse dependency traversal with hop distances and evidence classes.

#### Non-guarantees
Does not prove dynamic string-based reflection consumers.

#### Typical follow-up
find_related_tests or read_file on direct_callers

#### Common mistakes
- Modifying a public signature without checking direct_callers and affected_routes

#### Example
- **Developer request**: "What breaks if we change DatabasePool.acquire?"
- **Call**: `analyze_impact(symbol="DatabasePool.acquire", max_depth=3)`
- **Interpretation**: Review direct_callers, transitive_callers, affected_routes, and related_tests.

### `compile_task`

- **Capability**: `task_normalization_and_planning`
- **Profiles**: `minimal`, `developer`, `full`
- **Task Categories**: `MULTI_FILE_INVESTIGATION`, `DEBUG`, `TRACE`

#### Purpose
Normalize a developer question or task (`query`; `task` supported as string or TaskSpec dict alias) into a structured `TaskSpec`, ground targets against the index, detect ambiguities, and build a `RetrievalPlan`. Use before get_context when you want to inspect target resolution and ambiguity candidates prior to context retrieval. Does not retrieve source code snippets.

#### Use when
- Pre-checking whether task targets are ambiguous before compiling a full ContextPacket

#### Avoid when
- A direct call to get_context or resolve_symbol is sufficient

#### Required inputs
`query`

#### Optional inputs
`task`, `max_tokens`, `resource_mode`

#### Minimal invocation
```python
compile_task(query="Trace login route to database")
```

#### Advanced invocation
```python
compile_task(query="Debug AuthService", max_tokens=15000, resource_mode="CONSERVATIVE")
```

#### Result interpretation
- **Output Type**: `CompiledTaskPlan`
- **Key Fields**: `task_spec`, `ambiguity`, `ambiguities`, `entry_points`, `retrieval_plan`, `recommended_next_step`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Deterministic TaskSpec, ambiguity list, candidate entrypoints, and RetrievalPlan.

#### Non-guarantees
Does not return symbol bodies or relationship edges until get_context is called.

#### Typical follow-up
get_context(query=..., plan=retrieval_plan)

#### Common mistakes
- Stopping after compile_task without calling get_context to retrieve actual evidence

#### Example
- **Developer request**: "Compile a retrieval plan for debugging AuthService."
- **Call**: `compile_task(query="Debug AuthService")`
- **Interpretation**: Check ambiguities and entry_points, then pass the query or plan to get_context.

### `find_callees`

- **Capability**: `direct_callee_query`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `DEBUG`

#### Purpose
Find functions and methods called by the specified symbol (`symbol`; `canonical_id` supported as alias) up to `max_results`. Use instead of reading multiple files manually when answering 'what does X call?'. Does not resolve opaque runtime callbacks; preserves POSSIBLE and UNKNOWN evidence classes.

#### Use when
- Answering 'What does function X call?' with a bounded result list

#### Avoid when
- Single-file local edits

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `max_results`

#### Minimal invocation
```python
find_callees(symbol="place_order")
```

#### Advanced invocation
```python
find_callees(symbol="login_endpoint", max_results=30)
```

#### Result interpretation
- **Output Type**: `CalleeEdgeList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`

#### Evidence meaning
Outgoing call edges with target, confidence, evidence_class, and line numbers.

#### Non-guarantees
Does not prove external service behavior or dynamic eval calls.

#### Typical follow-up
get_symbol or get_file on target callees

#### Common mistakes
- Treating POSSIBLE_CALLS as guaranteed execution

#### Example
- **Developer request**: "What does place_order call?"
- **Call**: `find_callees(symbol="place_order", max_results=20)`
- **Interpretation**: Inspect each outgoing call edge's target and evidence_class.

### `find_callers`

- **Capability**: `direct_caller_query`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `DEBUG`

#### Purpose
Find functions and methods that call the specified symbol (`symbol`; `canonical_id` supported as alias) up to `max_results`. Use instead of grep or search_code when answering 'who calls X?'. Does not prove runtime execution of conditional branches; preserves POSSIBLE and UNKNOWN evidence classes.

#### Use when
- Answering 'Who calls function X?' with a bounded result list

#### Avoid when
- Single-file local edits

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `max_results`

#### Minimal invocation
```python
find_callers(symbol="place_order")
```

#### Advanced invocation
```python
find_callers(symbol="verify_password", max_results=50)
```

#### Result interpretation
- **Output Type**: `CallerEdgeList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`

#### Evidence meaning
Graph edges with relationship, confidence, evidence_class, and call-site coordinates.

#### Non-guarantees
Does not prove runtime execution or dynamic reflection calls.

#### Typical follow-up
get_file or trace_path

#### Common mistakes
- Ignoring evidence_class on POSSIBLE_CALLS rows

#### Example
- **Developer request**: "Who calls place_order?"
- **Call**: `find_callers(symbol="place_order", max_results=20)`
- **Interpretation**: Inspect each caller's source symbol, file, line, and evidence_class.

### `find_db_callers`

- **Capability**: `database_caller_discovery`
- **Profiles**: `full`
- **Task Categories**: `RELATIONSHIP`, `TRACE`, `CHANGE_IMPACT`

#### Purpose
Find all functions, methods, and upstream HTTP routes (`HANDLED_BY`) that read from or write to a database table. Use instead of grep when asking which code or route reaches a table. Returns direct accessors, upstream routes, relationships (`READS_TABLE`, `WRITES_TABLE`), and evidence classes. Does not prove runtime query frequency.

#### Use when
- Answering 'Which route or service accesses the products table?'

#### Avoid when
- You only want write mutations (prefer find_db_writers) or only reads (prefer find_db_readers)

#### Required inputs
`table`

#### Optional inputs
None

#### Minimal invocation
```python
find_db_callers(table="products")
```

#### Advanced invocation
```python
find_db_callers(table="products")
```

#### Result interpretation
- **Output Type**: `DatabaseCallersResult`
- **Key Fields**: `status`, `table`, `direct_accessors`, `upstream_routes`, `count`
- **Relationships Emitted**: `READS_TABLE`, `WRITES_TABLE`, `CALLS`, `HANDLED_BY`, `POSSIBLE_TABLE`

#### Evidence meaning
Direct table readers/writers plus transitive upstream callers and HTTP route entrypoints.

#### Non-guarantees
Does not prove runtime execution frequency unless paired with get_runtime_trace.

#### Typical follow-up
trace_path or get_file on the accessor symbol

#### Common mistakes
- Grepping for table names in route files when routes call services that call repositories

#### Example
- **Developer request**: "Which routes and functions access the products table?"
- **Call**: `find_db_callers(table="products")`
- **Interpretation**: Inspect direct_accessors and upstream_routes for symbol, relationship, and file:start_line.

### `find_db_columns`

- **Capability**: `database_column_discovery`
- **Profiles**: `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `RELATIONSHIP`, `CHANGE_IMPACT`

#### Purpose
Find database columns, data types, nullability, primary keys, and foreign keys across tables and ORM models. Use instead of grep when locating where a table column is defined or mapped (`MAPS_TO_COLUMN`, `HAS_PRIMARY_KEY`, `FOREIGN_KEY_TO`). Returns column definitions and source coordinates. Does not inspect live database catalogs.

#### Use when
- Answering 'What columns exist in bills?' or 'Where is column total_amount defined?'

#### Avoid when
- You already called get_db_table(table=...) which includes all columns for that table

#### Required inputs
None

#### Optional inputs
`table`, `column`

#### Minimal invocation
```python
find_db_columns(table="bills")
```

#### Advanced invocation
```python
find_db_columns(table="bills", column="total_amount")
```

#### Result interpretation
- **Output Type**: `DatabaseColumnListResult`
- **Key Fields**: `status`, `columns`, `count`
- **Relationships Emitted**: `MAPS_TO_COLUMN`, `HAS_PRIMARY_KEY`, `FOREIGN_KEY_TO`, `HAS_UNIQUE_CONSTRAINT`

#### Evidence meaning
ORM field-to-column mappings and SQL/migration column definitions with file:line evidence.

#### Non-guarantees
Does not prove live database column values or runtime constraint violations.

#### Typical follow-up
find_db_writers, find_db_readers, or get_db_impact

#### Common mistakes
- Assuming ORM attribute name always equals SQL column name without checking MAPS_TO_COLUMN

#### Example
- **Developer request**: "What columns exist in the bills table?"
- **Call**: `find_db_columns(table="bills")`
- **Interpretation**: Inspect each column's canonical_id, data_type, is_primary_key, foreign_key_target, and file:start_line.

### `find_db_models`

- **Capability**: `database_orm_model_discovery`
- **Profiles**: `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `ARCHITECTURE`

#### Purpose
Find ORM models (SQLAlchemy, Flask-SQLAlchemy, Django ORM, SQLModel, Prisma) and their `MAPS_TO_TABLE` mappings. Use when asking which model class maps to a database table or vice versa. Returns model name, table, canonical ID, and `FRAMEWORK_VERIFIED` evidence. Does not import or execute application model modules.

#### Use when
- Finding which ORM class maps to table 'products' or listing all ORM models in the repository

#### Avoid when
- Repository uses only raw SQL with no ORM layer

#### Required inputs
None

#### Optional inputs
`model`, `table`

#### Minimal invocation
```python
find_db_models()
```

#### Advanced invocation
```python
find_db_models(table="products")
```

#### Result interpretation
- **Output Type**: `DatabaseModelListResult`
- **Key Fields**: `status`, `models`, `count`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `ORM_RELATION`

#### Evidence meaning
Framework-verified ORM model declarations and table mappings.

#### Non-guarantees
Does not execute dynamic metaclass table name generators.

#### Typical follow-up
get_db_table or find_symbol

#### Common mistakes
- Guessing pluralized table names instead of checking MAPS_TO_TABLE via find_db_models

#### Example
- **Developer request**: "Which ORM model maps to the products table?"
- **Call**: `find_db_models(table="products")`
- **Interpretation**: Read name, table_name, framework, file, and start_line from the matched model entry.

### `find_db_queries`

- **Capability**: `database_query_discovery`
- **Profiles**: `full`
- **Task Categories**: `RELATIONSHIP`, `DEBUG`, `TRACE`

#### Purpose
Find database queries (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) across ORM calls, query builders, and raw SQL strings. Use when asking which queries touch a table or what SQL a function executes. Returns `READS_TABLE`, `WRITES_TABLE`, `POSSIBLE_TABLE`, or `UNKNOWN_TABLE` with redacted snippets. Never exposes SQL literal secret parameters.

#### Use when
- Listing all SELECT/INSERT/UPDATE/DELETE operations targeting a table or inside a service function

#### Avoid when
- Looking for general Python function callers unrelated to database persistence

#### Required inputs
None

#### Optional inputs
`table`, `symbol`, `operation`

#### Minimal invocation
```python
find_db_queries(table="orders")
```

#### Advanced invocation
```python
find_db_queries(table="orders", operation="INSERT")
```

#### Result interpretation
- **Output Type**: `DatabaseQueryListResult`
- **Key Fields**: `status`, `queries`, `count`
- **Relationships Emitted**: `READS_TABLE`, `WRITES_TABLE`, `READS_COLUMN`, `WRITES_COLUMN`, `POSSIBLE_TABLE`, `UNKNOWN_TABLE`, `QUERIES_DATABASE`

#### Evidence meaning
AST- and framework-verified query operations with normalized/redacted SQL snippets and uncertainty preservation.

#### Non-guarantees
Does not execute SQL queries or prove query execution plans.

#### Typical follow-up
get_file on the query file:start_line or find_db_callers

#### Common mistakes
- Treating dynamic string-interpolated SQL (`POSSIBLE_TABLE`/`UNKNOWN_TABLE`) as guaranteed static table proof

#### Example
- **Developer request**: "What database queries run against the orders table?"
- **Call**: `find_db_queries(table="orders")`
- **Interpretation**: Inspect operation, relationship, source_symbol, columns, evidence_class, and redacted snippet.

### `find_db_readers`

- **Capability**: `database_reader_discovery`
- **Profiles**: `full`
- **Task Categories**: `RELATIONSHIP`, `TRACE`

#### Purpose
Find all symbols and queries that read (`SELECT`, `.query()`, `.objects.filter()`, `.findMany()`) from a database table or column (`READS_TABLE`, `READS_COLUMN`). Use when tracing where table data is consumed across services and views. Returns reader symbols, operations, and evidence classes. Does not prove runtime cache hits.

#### Use when
- Answering 'What code reads from users or reads column email?'

#### Avoid when
- Looking only for INSERT/UPDATE/DELETE mutations (use find_db_writers)

#### Required inputs
None

#### Optional inputs
`table`, `column`

#### Minimal invocation
```python
find_db_readers(table="users")
```

#### Advanced invocation
```python
find_db_readers(table="users", column="email")
```

#### Result interpretation
- **Output Type**: `DatabaseReadersResult`
- **Key Fields**: `status`, `readers`, `count`
- **Relationships Emitted**: `READS_TABLE`, `READS_COLUMN`, `POSSIBLE_TABLE`

#### Evidence meaning
Verified SELECT and ORM read query sites with file and line spans.

#### Non-guarantees
Does not prove whether results are served from an in-memory cache at runtime.

#### Typical follow-up
get_file on the reader symbol or get_db_impact

#### Common mistakes
- Assuming a function that imports a model always reads from its table without checking READS_TABLE

#### Example
- **Developer request**: "Which functions read from the users table?"
- **Call**: `find_db_readers(table="users")`
- **Interpretation**: Inspect readers for symbol, table, columns, evidence_class, and file:start_line.

### `find_db_relationships`

- **Capability**: `database_relationship_discovery`
- **Profiles**: `full`
- **Task Categories**: `RELATIONSHIP`, `ARCHITECTURE`

#### Purpose
Find database schema and ORM relationships (`FOREIGN_KEY_TO`, `ORM_RELATION`, `MAPS_TO_TABLE`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `MIGRATES_TABLE`). Use when inspecting foreign keys, table joins, or model associations. Preserves explicit database relationship types and never collapses them into generic `DEPENDS_ON`.

#### Use when
- Answering 'What foreign keys or ORM relationships exist for orders?'

#### Avoid when
- Looking for function-to-function call edges (use find_callers/find_callees)

#### Required inputs
None

#### Optional inputs
`table`

#### Minimal invocation
```python
find_db_relationships()
```

#### Advanced invocation
```python
find_db_relationships(table="orders")
```

#### Result interpretation
- **Output Type**: `DatabaseRelationshipsResult`
- **Key Fields**: `status`, `relationships`, `count`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `FOREIGN_KEY_TO`, `ORM_RELATION`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `HAS_UNIQUE_CONSTRAINT`, `HAS_CHECK_CONSTRAINT`, `MIGRATES_TABLE`

#### Evidence meaning
Explicit schema and ORM relationship edges with canonical source/target IDs and source coordinates.

#### Non-guarantees
Does not prove unindexed database triggers on external servers.

#### Typical follow-up
get_db_table or get_db_impact

#### Common mistakes
- Collapsing FOREIGN_KEY_TO or ORM_RELATION into generic DEPENDS_ON edges

#### Example
- **Developer request**: "What foreign key and ORM relationships exist on the orders table?"
- **Call**: `find_db_relationships(table="orders")`
- **Interpretation**: Inspect source, target, relationship (e.g. FOREIGN_KEY_TO, ORM_RELATION), and evidence_class.

### `find_db_tables`

- **Capability**: `database_table_discovery`
- **Profiles**: `full`
- **Task Categories**: `ARCHITECTURE`, `SYMBOL_LOOKUP`, `MULTI_FILE_INVESTIGATION`

#### Purpose
Find database tables discovered across ORM models, raw SQL queries, and migrations. Use instead of grep when asking which database tables exist in this repository. Returns canonical IDs (`db.<dialect>.<schema>.<table>`), columns, ORM models, and evidence classes (`FRAMEWORK_VERIFIED`, `STATIC_VERIFIED`, `POSSIBLE`, `UNKNOWN`). Does not connect to live databases or execute SQL.

#### Use when
- Answering 'Which database tables exist in this repository?'
- Discovering canonical table IDs before calling get_db_table or find_db_callers

#### Avoid when
- Working on a repository with zero database, ORM, or SQL usage

#### Required inputs
None

#### Optional inputs
`table`, `dialect`, `schema`

#### Minimal invocation
```python
find_db_tables()
```

#### Advanced invocation
```python
find_db_tables(table="products", dialect="postgres")
```

#### Result interpretation
- **Output Type**: `DatabaseTableListResult`
- **Key Fields**: `status`, `tables`, `count`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `READS_TABLE`, `WRITES_TABLE`, `MIGRATES_TABLE`, `POSSIBLE_TABLE`, `UNKNOWN_TABLE`

#### Evidence meaning
Static ORM, SQL, and migration table definitions with canonical IDs and explicit dialect/schema uncertainty.

#### Non-guarantees
Does not inspect live production database catalogs or unindexed external schemas.

#### Typical follow-up
get_db_table, find_db_callers, or find_db_writers

#### Common mistakes
- Grepping for CREATE TABLE when tables are defined via SQLAlchemy/Django/Prisma ORM models

#### Example
- **Developer request**: "Which database tables exist in this repository?"
- **Call**: `find_db_tables()`
- **Interpretation**: Inspect tables list for canonical_id, table_name, dialect, orm_models, and evidence_class.

### `find_db_writers`

- **Capability**: `database_writer_discovery`
- **Profiles**: `full`
- **Task Categories**: `RELATIONSHIP`, `DEBUG`, `CHANGE_IMPACT`

#### Purpose
Find all symbols and queries that write (`INSERT`, `UPDATE`, `DELETE`) to a database table or column (`WRITES_TABLE`, `WRITES_COLUMN`). Use when investigating data mutations, state changes, or write blast radius. Returns writer symbols, operations, file:line citations, and redacted snippets. Does not execute database transactions.

#### Use when
- Answering 'Which service writes to the products table or updates inventory.quantity?'

#### Avoid when
- Investigating read-only SELECT queries (use find_db_readers)

#### Required inputs
None

#### Optional inputs
`table`, `column`

#### Minimal invocation
```python
find_db_writers(table="products")
```

#### Advanced invocation
```python
find_db_writers(table="inventory", column="quantity")
```

#### Result interpretation
- **Output Type**: `DatabaseWritersResult`
- **Key Fields**: `status`, `writers`, `count`
- **Relationships Emitted**: `WRITES_TABLE`, `WRITES_COLUMN`

#### Evidence meaning
Verified INSERT/UPDATE/DELETE and ORM mutation call sites with source coordinates.

#### Non-guarantees
Does not prove whether a database transaction commits or rolls back at runtime.

#### Typical follow-up
find_callers on the writer symbol or get_file on the mutation lines

#### Common mistakes
- Confusing read queries with write mutations when debugging corrupted state

#### Example
- **Developer request**: "Which functions write to the products table?"
- **Call**: `find_db_writers(table="products")`
- **Interpretation**: Inspect writers for symbol, operation (INSERT/UPDATE/DELETE), columns, file, and start_line.

### `find_references`

- **Capability**: `textual_chunk_references`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `MULTI_FILE_INVESTIGATION`

#### Purpose
Find textual occurrences and references of a symbol name (`symbol`; `name` and `canonical_id` supported as aliases) across indexed code chunks. Use when locating references or mentions of an identifier across files. Does not prove semantic call edges; use get_references when full relationship classification is required.

#### Use when
- Finding all code chunks referencing an identifier across the repository

#### Avoid when
- Searching for arbitrary non-symbol UI text in HTML templates (use search_code instead)

#### Required inputs
`symbol`

#### Optional inputs
`name`, `canonical_id`

#### Minimal invocation
```python
find_references(symbol="parse_bill")
```

#### Advanced invocation
```python
find_references(symbol="FEATURE_FLAG_X")
```

#### Result interpretation
- **Output Type**: `ChunkReferenceList`
- **Key Fields**: `file`, `symbol`, `start_line`, `end_line`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Lexical substring matches inside indexed code chunks.

#### Non-guarantees
Does not prove AST-verified call or reference semantics.

#### Typical follow-up
get_file on matched chunks to verify context

#### Common mistakes
- Treating find_references chunk hits as verified CALLS edges

#### Example
- **Developer request**: "Find all references to parse_bill."
- **Call**: `find_references(symbol="parse_bill")`
- **Interpretation**: Inspect matched files and line ranges as reference sites.

### `find_related_tests`

- **Capability**: `test_discovery`
- **Profiles**: `graph`, `developer`, `full`
- **Task Categories**: `TEST_DISCOVERY`, `CHANGE_IMPACT`, `DEBUG`

#### Purpose
Return test files and test functions statically linked to a target symbol (`symbol`; `canonical_id` supported as alias) via direct calls, imports, fixtures, or route invocation. Use when answering 'Which tests cover symbol X?' before or after a code change. Never fabricates coverage from lexical similarity alone.

#### Use when
- Selecting the exact pytest/jest test functions to run after modifying a symbol

#### Avoid when
- Editing documentation or comments with no behavioral impact

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `max_results`

#### Minimal invocation
```python
find_related_tests(symbol="AuthService.authenticate")
```

#### Advanced invocation
```python
find_related_tests(symbol="login_endpoint", max_results=20)
```

#### Result interpretation
- **Output Type**: `RelatedTestsResult`
- **Key Fields**: `test_symbol`, `file`, `start_line`, `end_line`, `relationship`, `evidence_class`, `confidence`, `reason`
- **Relationships Emitted**: `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`, `CALLS`, `IMPORTS`

#### Evidence meaning
AST/fixture/route-verified links from test functions to target symbols.

#### Non-guarantees
Does not prove runtime line coverage percentage or assertion completeness.

#### Typical follow-up
read_file on the test function if test assertions need inspection

#### Common mistakes
- Assuming empty results mean no dynamic integration test exists if tests invoke external URLs via env vars

#### Example
- **Developer request**: "Which tests cover BillingService.charge_card?"
- **Call**: `find_related_tests(symbol="BillingService.charge_card")`
- **Interpretation**: Inspect each returned test symbol, its file path, and the linking relationship (e.g., TESTS_SYMBOL, TESTS_ROUTE).

### `find_routes`

- **Capability**: `route_discovery`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `ROUTE_DISCOVERY`, `TRACE`, `ARCHITECTURE`

#### Purpose
Find HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols across FastAPI, Flask, Django, Express, and NestJS. Use instead of grep when locating API endpoints or route handlers. Does not prove runtime middleware authentication unless traced via trace_path or get_context.

#### Use when
- Answering 'Where is /api/scan-bill handled?'
- Discovering API entrypoints before calling trace_path to the database or service layer

#### Avoid when
- Working on a pure library or CLI module with no web routes

#### Required inputs
None

#### Optional inputs
`framework`, `method`, `path`

#### Minimal invocation
```python
find_routes()
```

#### Advanced invocation
```python
find_routes(method="POST", path="/api/scan-bill")
```

#### Result interpretation
- **Output Type**: `RouteListResult`
- **Key Fields**: `status`, `routes`, `route_path`, `http_method`, `handler_name`, `canonical_id`, `framework`, `file`, `line`, `evidence_class`
- **Relationships Emitted**: `HANDLED_BY`, `ROUTE_HANDLER`, `MOUNTS`, `ROUTES_TO`

#### Evidence meaning
Framework-verified route paths, HTTP methods, composed mount prefixes, and handler canonical IDs.

#### Non-guarantees
Does not prove external API gateway or reverse-proxy rewrite rules outside the repository.

#### Typical follow-up
trace_path, find_callees, or get_file on the matched handler

#### Common mistakes
- Grepping for route path strings that are split across router prefix mounts instead of calling find_routes

#### Example
- **Developer request**: "Where is /api/scan-bill handled?"
- **Call**: `find_routes(path="/api/scan-bill")`
- **Interpretation**: Read handler_name, canonical_id, and file:line from the matched route entry.

### `find_symbol`

- **Capability**: `exact_symbol_lookup`
- **Profiles**: `agent`, `minimal`, `developer`, `full`
- **Task Categories**: `SYMBOL_LOOKUP`

#### Purpose
Find function, method, or class definitions by exact short name or qualified name (`symbol`; `name` and `canonical_id` supported as aliases). Use instead of grep when locating where a class, function, or method is defined. Does not return callers, callees, or ambiguity alternatives like resolve_symbol.

#### Use when
- Quickly listing all definitions matching an exact symbol name

#### Avoid when
- Searching for literal UI strings or HTML template text (use search_code instead)

#### Required inputs
`symbol`

#### Optional inputs
`name`, `canonical_id`

#### Minimal invocation
```python
find_symbol(symbol="AuthService")
```

#### Advanced invocation
```python
find_symbol(symbol="src.auth.service.AuthService")
```

#### Result interpretation
- **Output Type**: `SymbolLocationList`
- **Key Fields**: `symbol`, `kind`, `file`, `start_line`, `end_line`
- **Relationships Emitted**: `DEFINES`

#### Evidence meaning
AST-indexed symbol rows matching name or qualified_name.

#### Non-guarantees
Does not disambiguate routes or compute call relationships.

#### Typical follow-up
get_symbol, get_file, or find_callers

#### Common mistakes
- Using find_symbol with partial substrings (use search_symbols or search_code for partial matching)

#### Example
- **Developer request**: "Where is InventoryService defined?"
- **Call**: `find_symbol(symbol="InventoryService")`
- **Interpretation**: Inspect file and start_line..end_line for each definition.

### `find_tests`

- **Capability**: `test_discovery`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `TEST_DISCOVERY`, `CHANGE_IMPACT`, `DEBUG`

#### Purpose
Find test files and test functions statically linked to a target symbol (`symbol`; `canonical_id` supported as alias) via direct calls, imports, fixtures, or route invocation. Use instead of grep when answering 'what tests cover symbol X?'. Does not execute tests at runtime and never fabricates coverage from lexical similarity alone.

#### Use when
- Selecting the exact pytest/jest test functions to run after modifying a symbol
- Answering 'What tests cover parse_bill?' with verified test links

#### Avoid when
- Editing documentation or comments with no behavioral impact

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `max_results`

#### Minimal invocation
```python
find_tests(symbol="parse_bill")
```

#### Advanced invocation
```python
find_tests(symbol="AuthService.authenticate", max_results=20)
```

#### Result interpretation
- **Output Type**: `RelatedTestsResult`
- **Key Fields**: `test_symbol`, `file`, `start_line`, `end_line`, `relationship`, `evidence_class`, `confidence`, `reason`
- **Relationships Emitted**: `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`, `CALLS`, `IMPORTS`

#### Evidence meaning
AST/fixture/route-verified links from test functions to target symbols.

#### Non-guarantees
Does not prove runtime line coverage percentage or assertion completeness.

#### Typical follow-up
get_file on the test function if test assertions need inspection

#### Common mistakes
- Guessing test coverage from filename similarity instead of calling find_tests

#### Example
- **Developer request**: "What tests cover parse_bill?"
- **Call**: `find_tests(symbol="parse_bill")`
- **Interpretation**: Inspect each returned test symbol, its file path, and the linking relationship (e.g., TESTS_SYMBOL, TESTS_ROUTE).

### `get_architecture`

- **Capability**: `architecture_overview`
- **Profiles**: `agent`, `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `ARCHITECTURE`, `PACKAGE`, `EXPLANATION`

#### Purpose
Return structural repository overview including modules, workspace packages (`DEPENDS_ON_PACKAGE`), entrypoints, and layer relationships. Use for high-level architecture, monorepo package boundary, and onboarding questions. Does not replace symbol-level evidence for specific bug fixes.

#### Use when
- Understanding overall system structure, entrypoints, and monorepo package dependencies

#### Avoid when
- Fixing a localized bug in a single already-known function

#### Required inputs
None

#### Optional inputs
None

#### Minimal invocation
```python
get_architecture()
```

#### Advanced invocation
```python
get_architecture()
```

#### Result interpretation
- **Output Type**: `ArchitectureOverviewResult`
- **Key Fields**: `status`, `modules`, `packages`, `package_dependencies`, `entrypoints`, `routes`, `summary`
- **Relationships Emitted**: `IMPORTS`, `DEPENDS_ON_PACKAGE`, `CONTAINS_PACKAGE`, `MOUNTS`, `HANDLED_BY`

#### Evidence meaning
Manifest-backed workspace packages and AST-verified module dependency counts.

#### Non-guarantees
Does not infer package boundaries from directory names without manifest evidence.

#### Typical follow-up
get_context(intent='ARCHITECTURE') or get_imports/get_dependents

#### Common mistakes
- Inferring package boundaries from folder names like apps/ or packages/ when get_architecture shows no manifest

#### Example
- **Developer request**: "How is this monorepo structured and what are the workspace packages?"
- **Call**: `get_architecture()`
- **Interpretation**: Inspect packages, package_dependencies, and entrypoints for manifest-verified boundaries.

### `get_call_graph`

- **Capability**: `neighborhood_call_graph`
- **Profiles**: `graph`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `TRACE`, `ARCHITECTURE`

#### Purpose
Compute the multi-hop call graph rooted at `symbol` (`canonical_id` supported as alias) up to `depth` and `max_results`. Use when exploring the multi-hop call neighborhood around a central service or controller. Does not prove runtime reachability for specific inputs.

#### Use when
- Mapping 2-hop or 3-hop call neighborhoods around a core function

#### Avoid when
- You only need direct 1-hop callers (use get_callers) or a path between two known endpoints (use trace_path)

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `depth`, `max_results`

#### Minimal invocation
```python
get_call_graph(symbol="AuthService.authenticate")
```

#### Advanced invocation
```python
get_call_graph(symbol="AuthService.authenticate", depth=3, max_results=50)
```

#### Result interpretation
- **Output Type**: `CallGraphEdgeList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `depth`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`, `DISPATCHES_TO`, `HANDLED_BY`

#### Evidence meaning
Bounded multi-hop subgraph edges with hop depth and evidence metadata.

#### Non-guarantees
Does not prove that every branch in the call graph executes on a single request.

#### Typical follow-up
trace_path or read_file

#### Common mistakes
- Requesting large depth values when depth=2 already captures the relevant neighborhood

#### Example
- **Developer request**: "Show the 2-hop call graph around AuthService.authenticate."
- **Call**: `get_call_graph(symbol="AuthService.authenticate", depth=2, max_results=50)`
- **Interpretation**: Inspect the returned edges by hop depth and relationship type.

### `get_callees`

- **Capability**: `callee_relationship`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `TRACE`, `DEBUG`, `EXPLANATION`

#### Purpose
Return symbols called or invoked by the specified symbol with evidence_class classification. Primary input: `symbol` (also accepts `canonical_id` as a compatibility alias using the exact same resolution path). Use to inspect downstream dependencies invoked by a function or handler. Does not resolve dynamic callbacks passed as opaque runtime arguments.

#### Use when
- Answering 'What does function X call?' without manually reading every imported module
- Following execution downstream from an endpoint or task handler

#### Avoid when
- The function body is 5 lines long and already visible in context

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`

#### Minimal invocation
```python
get_callees(symbol="process_checkout")
```

#### Advanced invocation
```python
get_callees(canonical_id="src/orders/service.py:process_checkout")
```

#### Result interpretation
- **Output Type**: `CalleeListResult`
- **Key Fields**: `status`, `canonical_id`, `callees`, `target`, `relationship`, `evidence_class`, `confidence`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`, `INJECTS`, `RESOLVES_DEPENDENCY`

#### Evidence meaning
AST/dataflow-verified outgoing calls with exact call-site line numbers.

#### Non-guarantees
Does not prove external network calls or dynamically constructed strings.

#### Typical follow-up
get_symbol or trace_path on downstream targets

#### Common mistakes
- Assuming POSSIBLE_CALLS edges are guaranteed to execute on every code path

#### Example
- **Developer request**: "What does process_checkout call downstream?"
- **Call**: `get_callees(symbol="process_checkout")`
- **Interpretation**: Read each outgoing edge in callees along with its target, relationship, and evidence_class.

### `get_callers`

- **Capability**: `caller_relationship`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `TRACE`, `DEBUG`, `CHANGE_IMPACT`

#### Purpose
Return statically verified callers of a symbol with confidence and evidence_class. Primary input: `symbol` (also accepts `canonical_id` as a compatibility alias using the exact same resolution path). Use for multi-file call-relationship and upstream impact questions. Does not prove runtime dispatch unless evidence_class indicates framework/dataflow verification.

#### Use when
- Answering 'What calls function X?' across the repository
- Tracing upstream callers during debugging or change-impact analysis

#### Avoid when
- Single-file local edit where call relationships do not matter

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`

#### Minimal invocation
```python
get_callers(symbol="verify_password")
```

#### Advanced invocation
```python
get_callers(canonical_id="src/auth/security.py:verify_password")
```

#### Result interpretation
- **Output Type**: `CallerListResult`
- **Key Fields**: `status`, `canonical_id`, `callers`, `source`, `relationship`, `evidence_class`, `confidence`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`, `DISPATCHES_TO`, `HANDLED_BY`

#### Evidence meaning
Call-site file, line, source caller symbol, and RelationshipEvidenceClass.

#### Non-guarantees
Does not prove dead-code reachability at runtime or reflective eval/getattr calls.

#### Typical follow-up
stop if callers list answers the question, or read_file on specific call sites

#### Common mistakes
- Claiming 'nothing calls X' when dynamic dispatch edges are marked UNKNOWN
- Passing an ambiguous bare name without calling resolve_symbol first

#### Example
- **Developer request**: "What calls verify_password across the codebase?"
- **Call**: `get_callers(symbol="verify_password")`
- **Interpretation**: Inspect callers list; verified callers carry relationship='CALLS' and evidence_class='AST_VERIFIED' or 'DATAFLOW_VERIFIED'.

### `get_context`

- **Capability**: `bounded_repository_context`
- **Profiles**: `agent`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `DEBUG`, `TRACE`, `CHANGE_IMPACT`, `MULTI_FILE_INVESTIGATION`, `ARCHITECTURE`, `EXPLANATION`, `TEST_DISCOVERY`, `PACKAGE`

#### Purpose
Compile a token-bounded, coverage-optimized ContextPacket containing verified symbols, compressed relationships, routes, DI providers, packages, and related tests. Primary input: `query` (natural-language question, symbol, or task description; `task` is also supported as a compatibility alias for string or structured TaskSpec dict). Budget controls: `max_tokens` (default 4000, hard cap 20000), `max_files` (default 15, hard cap 30), `max_lines` (default 500, hard cap 1500). Preserves UNKNOWN, POSSIBLE, and AMBIGUOUS states explicitly. Does not return full raw files; use targeted get_file or read_file only if exact omitted lines are needed afterward.

#### Use when
- Investigating a bug, route flow, DI chain, or multi-file feature in one bounded call
- Gathering target symbol + callers + callees + related tests + package context within a strict token/file/line budget

#### Avoid when
- Trivial one-file edit where the exact lines are already known

#### Required inputs
`query`

#### Optional inputs
`task`, `intent`, `max_tokens`, `max_files`, `max_lines`, `top_k`, `plan`, `mode`, `explain`, `resource_mode`

#### Minimal invocation
```python
get_context(query="Debug authentication failure in login_endpoint")
```

#### Advanced invocation
```python
get_context(query="Trace DI chain for get_current_user", intent="DEBUG", max_tokens=4000, max_files=15, max_lines=500, explain=True)
```

#### Result interpretation
- **Output Type**: `ContextPacket`
- **Key Fields**: `symbols`, `relationships`, `routes`, `tests`, `packages`, `unknowns`, `conflicts`, `uncertainties`, `freshness`, `selected_tokens`, `candidate_tokens`, `selected_files`, `selected_lines`, `coverage_score`, `truncated`, `candidate_token_estimate`, `selected_token_estimate`, `context_reduction_pct`, `coverage`
- **Relationships Emitted**: `CALLS`, `POSSIBLE_CALLS`, `IMPORTS`, `HANDLED_BY`, `MOUNTS`, `REGISTERS`, `DISPATCHES_TO`, `EVENT_LISTENER`, `TASK_HANDLER`, `COMMAND_HANDLER`, `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, `DEPENDS_ON_PACKAGE`, `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER`

#### Evidence meaning
Bounded source snippets, compressed relationships with supporting_locations, coverage_score, budget metadata (selected_tokens, candidate_tokens, selected_files, selected_lines, truncated), and explicit UNKNOWN/POSSIBLE/AMBIGUOUS preservation.

#### Non-guarantees
Does not execute code or fabricate edges for unresolvable dynamic dispatch.

#### Typical follow-up
get_file on specific line ranges if implementation details outside snippets are required

#### Common mistakes
- Calling get_context multiple times with identical arguments instead of reading the returned ContextPacket
- Ignoring the unknowns, conflicts, uncertainties, and truncated fields in the ContextPacket

#### Example
- **Developer request**: "How does UserRepository get injected into UserController and what tests cover it?"
- **Call**: `get_context(query="How does UserRepository get injected into UserController", intent="DEBUG", max_tokens=4000)`
- **Interpretation**: Inspect symbols, INJECTS/PROVIDES relationships, tests, selected_tokens/coverage_score/truncated, and any unknowns/conflicts/uncertainties.

### `get_db_impact`

- **Capability**: `database_change_impact`
- **Profiles**: `full`
- **Task Categories**: `CHANGE_IMPACT`, `TEST_DISCOVERY`, `DEBUG`

#### Purpose
Compute bidirectional Code <-> Database change impact for a table or column, returning affected ORM models, readers, writers, upstream HTTP routes, migrations, and statically linked tests. Use before renaming or altering a database table or column. Does not execute database migrations or tests.

#### Use when
- Answering 'What breaks if I rename or drop column shop_id on products?'

#### Avoid when
- Analyzing impact of a pure non-database helper function (use analyze_impact)

#### Required inputs
None

#### Optional inputs
`table`, `column`

#### Minimal invocation
```python
get_db_impact(table="products")
```

#### Advanced invocation
```python
get_db_impact(table="products", column="shop_id")
```

#### Result interpretation
- **Output Type**: `DatabaseImpactResult`
- **Key Fields**: `status`, `table`, `column`, `affected_models`, `affected_readers`, `affected_writers`, `affected_routes`, `affected_migrations`, `affected_tests`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `READS_TABLE`, `WRITES_TABLE`, `READS_COLUMN`, `WRITES_COLUMN`, `FOREIGN_KEY_TO`, `MIGRATES_TABLE`, `TESTS`

#### Evidence meaning
Bidirectional impact across ORM models, queries, service callers, HTTP routes, migrations, and tests.

#### Non-guarantees
Does not prove runtime migration locking or production table size.

#### Typical follow-up
get_file on affected models/writers and find_tests

#### Common mistakes
- Renaming a database column in an ORM model without checking raw SQL readers/writers via get_db_impact

#### Example
- **Developer request**: "What code, routes, and tests are impacted if products.shop_id changes?"
- **Call**: `get_db_impact(table="products", column="shop_id")`
- **Interpretation**: Inspect affected_models, affected_readers, affected_writers, affected_routes, affected_migrations, and affected_tests.

### `get_db_schema`

- **Capability**: `database_schema_overview`
- **Profiles**: `full`
- **Task Categories**: `ARCHITECTURE`, `EXPLANATION`

#### Purpose
Return a repository-wide database schema summary including all discovered tables, columns, ORM models, foreign keys, and migrations. Use for database architecture overviews or schema audits. Preserves `UNKNOWN` dialect and schema when not statically provable and never guesses database names.

#### Use when
- Understanding the complete data model, tables, foreign keys, and migration history of a repository

#### Avoid when
- Only one known table needs inspection (prefer get_db_table)

#### Required inputs
None

#### Optional inputs
`dialect`, `schema`

#### Minimal invocation
```python
get_db_schema()
```

#### Advanced invocation
```python
get_db_schema(dialect="postgres", schema="public")
```

#### Result interpretation
- **Output Type**: `DatabaseSchemaOverviewResult`
- **Key Fields**: `status`, `dialects`, `schemas`, `tables`, `orm_models`, `foreign_keys`, `migrations`, `env_variables`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `FOREIGN_KEY_TO`, `ORM_RELATION`, `MIGRATES_TABLE`, `READS_ENV`

#### Evidence meaning
Repository-wide database topology with explicit dialect/schema uncertainty and redacted env metadata.

#### Non-guarantees
Does not connect to external database servers or read `.env` secret values.

#### Typical follow-up
get_db_table on specific tables of interest

#### Common mistakes
- Assuming postgres/public when the repository only uses generic ORM declarations (`UNKNOWN` dialect/schema)

#### Example
- **Developer request**: "Give me an overview of the entire database schema and foreign keys in this repo."
- **Call**: `get_db_schema()`
- **Interpretation**: Inspect tables, orm_models, foreign_keys, migrations, and env_variables.

### `get_db_table`

- **Capability**: `database_table_details`
- **Profiles**: `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `ARCHITECTURE`, `DEBUG`

#### Purpose
Return complete structural details for a database table including columns, primary keys, foreign keys, indexes, constraints, ORM models, readers, writers, migrations, and upstream routes. Use when inspecting a specific table's schema and code usage in one call. Does not query live database servers.

#### Use when
- Inspecting everything known about a database table (columns, models, readers, writers, routes, migrations)

#### Avoid when
- Table name is unknown (call find_db_tables first)

#### Required inputs
`table`

#### Optional inputs
None

#### Minimal invocation
```python
get_db_table(table="products")
```

#### Advanced invocation
```python
get_db_table(table="products")
```

#### Result interpretation
- **Output Type**: `DatabaseTableDetailResult`
- **Key Fields**: `status`, `table`, `canonical_id`, `dialect`, `schema`, `columns`, `primary_keys`, `foreign_keys`, `indexes`, `orm_models`, `readers`, `writers`, `migrations`, `upstream_routes`
- **Relationships Emitted**: `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `READS_TABLE`, `WRITES_TABLE`, `FOREIGN_KEY_TO`, `HAS_PRIMARY_KEY`, `HAS_INDEX`, `MIGRATES_TABLE`, `ORM_RELATION`

#### Evidence meaning
Consolidated static schema, ORM mapping, reader/writer, route, and migration evidence for the table.

#### Non-guarantees
Does not return live table row counts or production data rows.

#### Typical follow-up
get_db_impact or get_file on model/migration files

#### Common mistakes
- Reading multiple migration files manually before calling get_db_table

#### Example
- **Developer request**: "Show me the schema, models, readers, and writers for the products table."
- **Call**: `get_db_table(table="products")`
- **Interpretation**: Inspect columns, primary_keys, foreign_keys, orm_models, readers, writers, and upstream_routes.

### `get_dependencies`

- **Capability**: `raw_import_table_dump`
- **Profiles**: `full`
- **Task Categories**: `ARCHITECTURE`, `PACKAGE`

#### Purpose
List up to 500 raw parser-extracted `(source_path, imported)` rows from the imports table. Use for bulk inspection of raw import statements across the repository. Does not resolve workspace package boundaries; prefer get_imports or get_architecture.

#### Use when
- Auditing raw import strings across the repository

#### Avoid when
- Inspecting imports of a single file (prefer get_imports)

#### Required inputs
None

#### Optional inputs
None

#### Minimal invocation
```python
get_dependencies()
```

#### Advanced invocation
```python
get_dependencies()
```

#### Result interpretation
- **Output Type**: `RawImportRowList`
- **Key Fields**: `source_path`, `imported`
- **Relationships Emitted**: `IMPORTS`

#### Evidence meaning
AST-extracted import strings per source file.

#### Non-guarantees
Does not prove installed third-party package versions.

#### Typical follow-up
get_imports

#### Common mistakes
- Using get_dependencies when get_imports(file=...) is much more targeted

#### Example
- **Developer request**: "List raw import statements across indexed files."
- **Call**: `get_dependencies()`
- **Interpretation**: Inspect source_path and imported module names.

### `get_dependency_graph`

- **Capability**: `module_dependency_graph`
- **Profiles**: `full`
- **Task Categories**: `ARCHITECTURE`, `PACKAGE`

#### Purpose
Return module-level `IMPORTS` graph edges across the repository or filtered to `file_path`. Use when inspecting raw module-to-module import topology. Does not prove symbol-level call invocation; prefer get_imports or get_dependents for targeted queries.

#### Use when
- Inspecting module import edges for a specific file or across a small repository

#### Avoid when
- Querying a single file's imports (prefer get_imports)

#### Required inputs
None

#### Optional inputs
`file_path`

#### Minimal invocation
```python
get_dependency_graph(file_path="src/auth/service.py")
```

#### Advanced invocation
```python
get_dependency_graph()
```

#### Result interpretation
- **Output Type**: `DependencyGraphEdgeList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence`
- **Relationships Emitted**: `IMPORTS`

#### Evidence meaning
AST-extracted module IMPORTS edges with source, target, and confidence.

#### Non-guarantees
Does not prove whether imported symbols are called.

#### Typical follow-up
get_architecture or get_dependents

#### Common mistakes
- Calling get_dependency_graph() without file_path when only one module's imports are needed

#### Example
- **Developer request**: "Show import graph edges originating from src/auth/service.py."
- **Call**: `get_dependency_graph(file_path="src/auth/service.py")`
- **Interpretation**: Inspect each IMPORTS edge from source to target module.

### `get_dependents`

- **Capability**: `reverse_dependency_inspection`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `CHANGE_IMPACT`, `RELATIONSHIP`, `PACKAGE`, `ARCHITECTURE`

#### Purpose
Return files, symbols, and packages that import or depend on the target symbol or file (`symbol` or `file`; `canonical_id` and `path` supported as aliases). Use for blast-radius, change-impact, and package boundary analysis. Does not prove runtime failure without checking test and caller evidence.

#### Use when
- Determining which modules or packages break if a shared symbol or file signature changes

#### Avoid when
- Editing a private helper that is never exported or referenced outside one function

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `file`, `path`

#### Minimal invocation
```python
get_dependents(symbol="UserRepository")
```

#### Advanced invocation
```python
get_dependents(file="src/auth/repository.py")
```

#### Result interpretation
- **Output Type**: `DependentsResult`
- **Key Fields**: `status`, `dependents`, `source`, `target`, `relationship`, `evidence_class`, `file`
- **Relationships Emitted**: `IMPORTS`, `CALLS`, `DEPENDS_ON_PACKAGE`, `TESTS`

#### Evidence meaning
Verified reverse import and call edges pointing to the target.

#### Non-guarantees
Does not prove unindexed external repository consumers.

#### Typical follow-up
find_related_tests or analyze_impact

#### Common mistakes
- Confusing forward imports (get_imports) with reverse dependents (get_dependents)

#### Example
- **Developer request**: "Which modules depend on src/auth/repository.py?"
- **Call**: `get_dependents(file="src/auth/repository.py")`
- **Interpretation**: Review the dependents list to see all upstream files and symbols importing the module.

### `get_evidence`

- **Capability**: `file_evidence_extraction`
- **Profiles**: `developer`, `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `EXPLANATION`

#### Purpose
Return bounded source-derived `Evidence` citations (`file`, `start_line`, `end_line`, `symbol`, `snippet`, `content_hash`) for a non-sensitive file or symbol. Use when constructing hash-verifiable code citations. Blocks sensitive files and does not compute cross-file callers.

#### Use when
- Fetching verifiable evidence snippets for a symbol inside a known file

#### Avoid when
- Reading arbitrary line ranges (use read_file) or sensitive files (blocked)

#### Required inputs
`path`

#### Optional inputs
`symbol`

#### Minimal invocation
```python
get_evidence(path="src/auth/service.py")
```

#### Advanced invocation
```python
get_evidence(path="src/auth/service.py", symbol="AuthService.authenticate")
```

#### Result interpretation
- **Output Type**: `EvidenceCitationList`
- **Key Fields**: `file`, `start_line`, `end_line`, `symbol`, `snippet`, `content_hash`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Indexed chunk snippets paired with SHA-256 content hashes and line coordinates.

#### Non-guarantees
Does not compute cross-file relationship edges.

#### Typical follow-up
verify_evidence

#### Common mistakes
- Requesting evidence on sensitive files such as .env (raises SecurityError)

#### Example
- **Developer request**: "Get verifiable evidence chunks for AuthService.authenticate in src/auth/service.py."
- **Call**: `get_evidence(path="src/auth/service.py", symbol="AuthService.authenticate")`
- **Interpretation**: Inspect snippet, start_line..end_line, and content_hash.

### `get_file`

- **Capability**: `file_structure_inspection`
- **Profiles**: `agent`, `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `LOCAL_EDIT`, `SYMBOL_LOOKUP`, `DEBUG`, `EXPLANATION`

#### Purpose
Open and inspect a repository file's structural AST outline or a bounded line range (`path`, `start_line`, `end_line`, `max_lines`). Use after `search_code`, `find_symbol`, or `find_routes` identifies a target file and line span across Python, HTML, Jinja, JS, TS, CSS, YAML, JSON, or Markdown. Blocks path traversal, binary files, and sensitive files; does not prove cross-file callers.

#### Use when
- Opening a targeted line range (`start_line`, `end_line`) of a Python, HTML, Jinja, JS, CSS, or config file
- Reviewing the symbols and imports inside a module before editing

#### Avoid when
- Reading an entire huge file without `start_line`/`end_line` bounds

#### Required inputs
`path`

#### Optional inputs
`start_line`, `end_line`, `max_lines`, `include_content`

#### Minimal invocation
```python
get_file(path="src/auth/service.py", start_line=1, end_line=80)
```

#### Advanced invocation
```python
get_file(path="templates/dashboard.html", start_line=40, end_line=110, max_lines=200)
```

#### Result interpretation
- **Output Type**: `FileStructureResult`
- **Key Fields**: `status`, `path`, `file`, `start_line`, `end_line`, `content`, `truncated`, `category`, `file_category`, `artifact_type`, `symbols`, `imports`, `freshness`
- **Relationships Emitted**: `DEFINES`, `IMPORTS`

#### Evidence meaning
Bounded on-disk source lines (`start_line`..`end_line`, `truncated`) plus parser-extracted symbols and imports.

#### Non-guarantees
Does not prove reverse dependents across the repository.

#### Typical follow-up
perform targeted code edit or call find_callers/find_callees on discovered symbols

#### Common mistakes
- Setting include_content=True on huge files instead of passing start_line and end_line

#### Example
- **Developer request**: "Show lines 40 to 110 of templates/dashboard.html."
- **Call**: `get_file(path="templates/dashboard.html", start_line=40, end_line=110)`
- **Interpretation**: Inspect `content`, `start_line`, `end_line`, and `truncated` for the requested file range.

### `get_file_history`

- **Capability**: `git_file_commit_history`
- **Profiles**: `developer`, `full`
- **Task Categories**: `DEBUG`, `CHANGE_IMPACT`

#### Purpose
Return recent Git commits touching a specific repository file (`path`, up to `n` commits). Use when investigating when and why a specific file was recently modified. Does not return full commit diffs or cross-file dependency impact.

#### Use when
- Checking recent commit history on a buggy file

#### Avoid when
- Static symbol relationships or current source code are sufficient

#### Required inputs
`path`

#### Optional inputs
`n`

#### Minimal invocation
```python
get_file_history(path="src/auth/service.py")
```

#### Advanced invocation
```python
get_file_history(path="src/auth/service.py", n=5)
```

#### Result interpretation
- **Output Type**: `FileCommitHistoryList`
- **Key Fields**: `commit`, `author`, `date`, `subject`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Commit hashes, authors, timestamps, and commit subjects touching `path`.

#### Non-guarantees
Does not prove which specific symbol inside the file caused a regression.

#### Typical follow-up
get_git_impact(base=commit, head='HEAD')

#### Common mistakes
- Passing an absolute path outside the repository

#### Example
- **Developer request**: "Show the last 5 commits touching src/auth/service.py."
- **Call**: `get_file_history(path="src/auth/service.py", n=5)`
- **Interpretation**: Inspect the commit hashes and subjects to identify relevant recent changes.

### `get_file_symbols`

- **Capability**: `file_symbol_table`
- **Profiles**: `full`
- **Task Categories**: `SYMBOL_LOOKUP`

#### Purpose
List extracted symbols (`symbol`, `kind`, `start_line`, `end_line`) in a single repository-relative file. Use for a lightweight symbol table of one file when imports and artifact metadata are not needed. Does not return cross-file relationships; prefer get_file for full file outline.

#### Use when
- Listing symbol names and line ranges inside a single file

#### Avoid when
- You also need file imports and artifact classification (prefer get_file)

#### Required inputs
`path`

#### Optional inputs
None

#### Minimal invocation
```python
get_file_symbols(path="src/auth/service.py")
```

#### Advanced invocation
```python
get_file_symbols(path="src/auth/routes.py")
```

#### Result interpretation
- **Output Type**: `FileSymbolRowList`
- **Key Fields**: `symbol`, `kind`, `start_line`, `end_line`
- **Relationships Emitted**: `DEFINES`

#### Evidence meaning
AST-extracted symbol names, kinds, and line spans within `path`.

#### Non-guarantees
Does not return file imports or callers.

#### Typical follow-up
get_symbol or read_file

#### Common mistakes
- Passing a symbol name instead of a file path

#### Example
- **Developer request**: "List all symbols defined in src/auth/service.py."
- **Call**: `get_file_symbols(path="src/auth/service.py")`
- **Interpretation**: Inspect each symbol's qualified name, kind, and line span.

### `get_git_impact`

- **Capability**: `change_impact_analysis`
- **Profiles**: `agent`, `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `CHANGE_IMPACT`, `TEST_DISCOVERY`, `DEBUG`

#### Purpose
Compute deterministic change impact between Git refs (`base`..`head`), including modified symbols, downstream callers, affected packages, and covering tests. Use for PR review, regression analysis, and pre-commit blast-radius checks. Does not execute tests; reports static test-to-symbol coverage edges.

#### Use when
- Finding affected callers, packages, and tests after recent commits or before a refactor

#### Avoid when
- No Git history is relevant and you only need to look up a single symbol definition

#### Required inputs
None

#### Optional inputs
`base`, `head`

#### Minimal invocation
```python
get_git_impact()
```

#### Advanced invocation
```python
get_git_impact(base="HEAD~3", head="HEAD")
```

#### Result interpretation
- **Output Type**: `GitImpactResult`
- **Key Fields**: `status`, `base`, `head`, `changed_files`, `modified_symbols`, `impacted_callers`, `affected_packages`, `related_tests`
- **Relationships Emitted**: `CALLS`, `TESTS`, `TESTS_SYMBOL`, `DEPENDS_ON_PACKAGE`, `IMPORTS`

#### Evidence meaning
Git diff line mapping intersected with AST symbol spans and graph dependents.

#### Non-guarantees
Does not prove whether tests pass or fail at runtime.

#### Typical follow-up
find_tests or get_file on modified symbols

#### Common mistakes
- Assuming get_git_impact runs pytest; it computes static impact and test selection

#### Example
- **Developer request**: "What symbols, packages, and tests are impacted by the latest commit?"
- **Call**: `get_git_impact(base="HEAD~1", head="HEAD")`
- **Interpretation**: Inspect modified_symbols, impacted_callers, affected_packages, and related_tests.

### `get_graph`

- **Capability**: `structural_graph_edges`
- **Profiles**: `developer`, `full`
- **Task Categories**: `ARCHITECTURE`, `DIAGNOSTIC`

#### Purpose
Return up to `limit` (1..500) parser-confirmed definition and import graph edges with evidence metadata. Use for inspecting raw structural `DEFINES` and `IMPORTS` edges in small repositories or diagnostics. Does not replace targeted relationship tools like get_callers or trace_path.

#### Use when
- Sampling raw structural graph edges during diagnostics

#### Avoid when
- Answering targeted symbol or route questions (use get_callers, trace_path, or get_context)

#### Required inputs
None

#### Optional inputs
`limit`

#### Minimal invocation
```python
get_graph()
```

#### Advanced invocation
```python
get_graph(limit=100)
```

#### Result interpretation
- **Output Type**: `GraphEdgeList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `file`, `line`
- **Relationships Emitted**: `DEFINES`, `IMPORTS`

#### Evidence meaning
Validated structural edges with source, target, relationship, and confidence.

#### Non-guarantees
Does not return task-ranked context or multi-hop traces.

#### Typical follow-up
get_architecture

#### Common mistakes
- Dumping get_graph(limit=500) instead of querying the specific symbol with get_callers/get_references

#### Example
- **Developer request**: "Sample the first 50 structural edges in the graph."
- **Call**: `get_graph(limit=50)`
- **Interpretation**: Inspect source, target, and relationship for each edge.

### `get_imports`

- **Capability**: `module_import_inspection`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `ARCHITECTURE`, `PACKAGE`

#### Purpose
Return parser-extracted module and symbol imports for a file or symbol (`file` or `symbol`; `canonical_id` and `path` supported as aliases). Use for forward dependency and package boundary questions. Does not return reverse importers (use get_dependents for reverse dependencies).

#### Use when
- Inspecting what modules or workspace packages a file depends on

#### Avoid when
- Finding what files import this module (use get_dependents instead)

#### Required inputs
`file`

#### Optional inputs
`symbol`, `canonical_id`, `path`

#### Minimal invocation
```python
get_imports(file="src/auth/routes.py")
```

#### Advanced invocation
```python
get_imports(symbol="src/auth/routes.py:login_endpoint")
```

#### Result interpretation
- **Output Type**: `ImportsResult`
- **Key Fields**: `status`, `file`, `imports`, `source`, `target`, `relationship`, `evidence_class`
- **Relationships Emitted**: `IMPORTS`, `DEPENDS_ON_PACKAGE`, `CROSS_PACKAGE_IMPORT`

#### Evidence meaning
AST-verified import statements and resolved internal module paths.

#### Non-guarantees
Does not prove whether an imported symbol is actually invoked at runtime.

#### Typical follow-up
get_dependents or get_architecture

#### Common mistakes
- Using get_imports when looking for reverse dependents (use get_dependents)

#### Example
- **Developer request**: "What modules does src/auth/routes.py import?"
- **Call**: `get_imports(file="src/auth/routes.py")`
- **Interpretation**: Inspect the imports list for internal module paths and cross-package imports.

### `get_project_structure`

- **Capability**: `indexed_file_list`
- **Profiles**: `full`
- **Task Categories**: `ARCHITECTURE`

#### Purpose
Return up to 500 indexed repository-relative source file paths in deterministic sorted order. Use for a flat inventory of indexed files when exploring a small project. Does not return package dependency graphs or entrypoints (prefer get_architecture).

#### Use when
- Listing indexed file paths in a small repository

#### Avoid when
- Understanding architecture, entrypoints, or monorepo packages (prefer get_architecture)

#### Required inputs
None

#### Optional inputs
None

#### Minimal invocation
```python
get_project_structure()
```

#### Advanced invocation
```python
get_project_structure()
```

#### Result interpretation
- **Output Type**: `IndexedFilePathList`
- **Key Fields**: `path`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Sorted list of non-sensitive indexed file paths.

#### Non-guarantees
Does not prove package ownership or module relationships.

#### Typical follow-up
get_file or get_architecture

#### Common mistakes
- Calling get_project_structure instead of get_architecture for architectural questions

#### Example
- **Developer request**: "List all indexed file paths in the repository."
- **Call**: `get_project_structure()`
- **Interpretation**: Inspect the returned list of relative POSIX file paths.

### `get_recent_changes`

- **Capability**: `git_diff_file_list`
- **Profiles**: `developer`, `full`
- **Task Categories**: `CHANGE_IMPACT`, `DEBUG`

#### Purpose
Return repository files modified between two Git refs (`since`..`until`) in a read-only sandboxed query. Use when reviewing recent commits or identifying which files changed before running impact analysis. Does not compute downstream symbol callers; use get_git_impact for symbol-level blast radius.

#### Use when
- Listing files touched in the last N commits during debugging or code review

#### Avoid when
- You need symbol-level callers and affected tests (prefer get_git_impact)

#### Required inputs
None

#### Optional inputs
`since`, `until`

#### Minimal invocation
```python
get_recent_changes()
```

#### Advanced invocation
```python
get_recent_changes(since="HEAD~5", until="HEAD")
```

#### Result interpretation
- **Output Type**: `GitChangedFilesList`
- **Key Fields**: `path`, `status`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Git diff status and relative file paths between refs.

#### Non-guarantees
Does not compute symbol-level callers or covering tests (use get_git_impact).

#### Typical follow-up
get_git_impact or get_file

#### Common mistakes
- Calling get_recent_changes and manually reading every changed file instead of calling get_git_impact

#### Example
- **Developer request**: "Which files changed in the last 5 commits?"
- **Call**: `get_recent_changes(since="HEAD~5", until="HEAD")`
- **Interpretation**: Inspect each changed file's path and change status.

### `get_references`

- **Capability**: `reference_relationship`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `RELATIONSHIP`, `CHANGE_IMPACT`, `DEBUG`

#### Purpose
Return verified and candidate references to a symbol across the repository with evidence_class labels. Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). Use for cross-file reference, registration, dispatch, or DI binding lookup. Does not guarantee dynamic reflection targets when evidence_class is UNKNOWN or POSSIBLE.

#### Use when
- Finding all usages, registrations, or DI bindings of a symbol across files
- Checking if a symbol is referenced before refactoring or deleting it

#### Avoid when
- Purely local variable rename inside a single function scope

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `name`

#### Minimal invocation
```python
get_references(symbol="command_registry")
```

#### Advanced invocation
```python
get_references(canonical_id="src/dispatch/registry.py:command_registry")
```

#### Result interpretation
- **Output Type**: `ReferenceListResult`
- **Key Fields**: `status`, `canonical_id`, `references`, `relationship`, `evidence_class`, `confidence`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `IMPORTS`, `REGISTERS`, `DISPATCHES_TO`, `EVENT_LISTENER`, `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `REFERENCES`

#### Evidence meaning
Source-backed reference locations with explicit confidence and evidence_class.

#### Non-guarantees
Does not prove runtime execution order or unindexed external consumers.

#### Typical follow-up
read_file on specific reference sites or get_context

#### Common mistakes
- Treating REGISTERS or INJECTS references as direct CALLS edges
- Treating POSSIBLE references as verified facts without source confirmation

#### Example
- **Developer request**: "Where is command_registry referenced or populated?"
- **Call**: `get_references(symbol="command_registry")`
- **Interpretation**: Check each reference item's relationship (e.g., REGISTERS, DISPATCHES_TO) and evidence_class.

### `get_repository_status`

- **Capability**: `index_status_and_freshness`
- **Profiles**: `minimal`, `developer`, `full`
- **Task Categories**: `DIAGNOSTIC`

#### Purpose
Return repository indexing status, generation counter, freshness state (`FRESH` or `STALE`), symbol counts, and modified/deleted file lists. Use to check whether the index is fresh before trusting cached graph facts after disk edits. Does not re-index the repository automatically.

#### Use when
- Checking if freshness is FRESH or STALE after editing files
- Inspecting total indexed files, symbols, graph_edges, and framework_routes

#### Avoid when
- Normal read-only queries when freshness is already included in tool responses

#### Required inputs
None

#### Optional inputs
None

#### Minimal invocation
```python
get_repository_status()
```

#### Advanced invocation
```python
get_repository_status()
```

#### Result interpretation
- **Output Type**: `RepositoryStatusReport`
- **Key Fields**: `repository`, `generation`, `freshness`, `freshness_detail`, `files_indexed`, `symbols_indexed`, `graph_edges`, `framework_routes`, `modified_files`, `deleted_files`, `parse_failed_files`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
On-disk mtime/hash comparison against indexed file records.

#### Non-guarantees
Does not prove external git remote state.

#### Typical follow-up
read_file on modified_files if freshness is STALE

#### Common mistakes
- Presenting cached graph edges from modified_files as current truth when freshness == 'STALE'

#### Example
- **Developer request**: "Is the CodeGraph index fresh and how many symbols are indexed?"
- **Call**: `get_repository_status()`
- **Interpretation**: Check freshness ('FRESH' vs 'STALE'), symbols_indexed, and modified_files.

### `get_resource_status`

- **Capability**: `resource_governor_diagnostics`
- **Profiles**: `minimal`, `developer`, `full`
- **Task Categories**: `DIAGNOSTIC`

#### Purpose
Return current resource governor state including memory usage, pressure level, concurrency limits, and activity mode. Use for diagnosing server resource pressure or throttling behavior. Does not inspect repository source code or symbols.

#### Use when
- Checking if the MCP server is under memory pressure or running in CONSERVATIVE mode

#### Avoid when
- Answering normal code navigation or relationship questions

#### Required inputs
None

#### Optional inputs
None

#### Minimal invocation
```python
get_resource_status()
```

#### Advanced invocation
```python
get_resource_status()
```

#### Result interpretation
- **Output Type**: `ResourceGovernorState`
- **Key Fields**: `mode`, `pressure`, `rss_mb`, `active_tasks`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Live process memory and governor concurrency telemetry.

#### Non-guarantees
Does not report symbol index freshness (use get_repository_status for index freshness).

#### Typical follow-up
get_repository_status

#### Common mistakes
- Confusing get_resource_status (memory/CPU governor) with get_repository_status (index freshness/symbol counts)

#### Example
- **Developer request**: "Check current resource governor pressure and memory mode."
- **Call**: `get_resource_status()`
- **Interpretation**: Inspect mode, pressure, and rss_mb.

### `get_runtime_trace`

- **Capability**: `runtime_trace_interrogation`
- **Profiles**: `full`
- **Task Categories**: `TRACE`, `DEBUG`

#### Purpose
Retrieve aggregated runtime execution edges (`RUNTIME_OBSERVED`) and reverse maps (`table -> runtime writers/readers`, `route -> runtime tables`) with `observation_count`, `first_seen`, `last_seen`, and `runtime_generation`. Use when asking what actually happened at runtime. Does not treat unobserved paths as impossible.

#### Use when
- Answering 'What happened at runtime when /api/scan-bill ran?' or 'Which runtime queries wrote to bills?'

#### Avoid when
- No runtime traces have been ingested into the repository index

#### Required inputs
None

#### Optional inputs
`route`, `symbol`, `table`

#### Minimal invocation
```python
get_runtime_trace()
```

#### Advanced invocation
```python
get_runtime_trace(route="/api/scan-bill", table="bills")
```

#### Result interpretation
- **Output Type**: `RuntimeTraceResult`
- **Key Fields**: `status`, `edges`, `observations`, `reverse_maps`, `count`
- **Relationships Emitted**: `CALLS`, `HANDLED_BY`, `READS_TABLE`, `WRITES_TABLE`, `QUERIES_DATABASE`

#### Evidence meaning
Aggregated RUNTIME_OBSERVED edges with observation counts, timestamps, and sanitized SQL templates.

#### Non-guarantees
Does not prove that unobserved static branches cannot execute under other inputs.

#### Typical follow-up
reconcile_static_runtime or get_file

#### Common mistakes
- Claiming a branch is dead code merely because observation_count is 0 in a single trace sample

#### Example
- **Developer request**: "What happened at runtime when /api/scan-bill executed?"
- **Call**: `get_runtime_trace(route="/api/scan-bill")`
- **Interpretation**: Inspect edges (`evidence_class='RUNTIME_OBSERVED'`), observation_count, and reverse_maps.

### `get_symbol`

- **Capability**: `symbol_inspection`
- **Profiles**: `agent`, `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `EXPLANATION`

#### Purpose
Return authoritative signature, kind, parent scope, decorators, and bounded source snippet for a symbol. Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). Use when you have a symbol name or canonical_id and need its declaration metadata. Does not traverse multi-hop call graphs.

#### Use when
- Inspecting a symbol's signature, return type, and decorators without reading the entire file

#### Avoid when
- Tracing multi-hop execution flows (use trace_path or get_context instead)

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `name`

#### Minimal invocation
```python
get_symbol(symbol="AuthService.authenticate")
```

#### Advanced invocation
```python
get_symbol(canonical_id="src/auth/service.py:AuthService.authenticate")
```

#### Result interpretation
- **Output Type**: `SymbolDetailResult`
- **Key Fields**: `status`, `canonical_id`, `qualified_name`, `kind`, `signature`, `decorators`, `file`, `start_line`, `end_line`, `snippet`
- **Relationships Emitted**: `DEFINES`, `CONTAINS`

#### Evidence meaning
AST-verified symbol signature, decorators, and exact line span.

#### Non-guarantees
Does not prove downstream impact or callers outside the symbol body.

#### Typical follow-up
get_file (if full method body beyond snippet is needed) or find_callees

#### Common mistakes
- Calling get_symbol when multi-file callers/callees are needed (use find_callers or get_context)

#### Example
- **Developer request**: "What is the exact signature and decorator list of login_endpoint?"
- **Call**: `get_symbol(symbol="login_endpoint")`
- **Interpretation**: Read signature, decorators, and start_line..end_line from the returned declaration record.

### `ingest_runtime_traces`

- **Capability**: `runtime_trace_ingestion`
- **Profiles**: `full`
- **Task Categories**: `TRACE`, `DEBUG`, `DIAGNOSTIC`

#### Purpose
Ingest optional runtime observation traces (OpenTelemetry JSON, structured JSON/JSONL events, or SQL query logs) into CodeGraph's `RUNTIME_OBSERVED` layer. Use when grounding static analysis with recorded runtime traces. Automatically strips headers/cookies/bodies, redacts SQL bind parameters and secrets, and never converts runtime observations into static `AST_VERIFIED` proof.

#### Use when
- Loading recorded OpenTelemetry spans, JSONL runtime events, or SQL logs before calling get_runtime_trace or reconcile_static_runtime

#### Avoid when
- No runtime trace file or payload is available (static tools work without runtime data)

#### Required inputs
None

#### Optional inputs
`source_path`, `format`, `payload`, `max_events`, `sample_rate`

#### Minimal invocation
```python
ingest_runtime_traces(source_path="traces/otel.json")
```

#### Advanced invocation
```python
ingest_runtime_traces(source_path="traces/events.jsonl", format="jsonl", max_events=1000, sample_rate=1.0)
```

#### Result interpretation
- **Output Type**: `RuntimeIngestResult`
- **Key Fields**: `status`, `runtime_generation`, `events_ingested`, `edges_recorded`, `redacted_fields`
- **Relationships Emitted**: `CALLS`, `HANDLED_BY`, `READS_TABLE`, `WRITES_TABLE`, `QUERIES_DATABASE`

#### Evidence meaning
Sanitized RUNTIME_OBSERVED edges with observation_count, first_seen, last_seen, and runtime_generation.

#### Non-guarantees
Never proves static AST_VERIFIED relationships and never launches or instruments the user application.

#### Typical follow-up
get_runtime_trace or reconcile_static_runtime

#### Common mistakes
- Treating RUNTIME_OBSERVED edges as static AST_VERIFIED proof

#### Example
- **Developer request**: "Ingest the OpenTelemetry trace file traces/scan_bill.json."
- **Call**: `ingest_runtime_traces(source_path="traces/scan_bill.json")`
- **Interpretation**: Confirm status=='ok', events_ingested, and runtime_generation.

### `list_routes`

- **Capability**: `route_discovery`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `ROUTE_DISCOVERY`, `TRACE`, `ARCHITECTURE`

#### Purpose
Return HTTP/RPC framework routes, mounted router prefixes (`MOUNTS`), methods, and handler symbols. Use when locating API endpoints, route handlers, or mounted sub-applications (FastAPI, Flask, Django, Express, NestJS). Does not prove runtime middleware authentication unless traced via get_context or trace_path.

#### Use when
- Answering 'Which route handles /api/v1/auth/login?'
- Listing all API entrypoints in a service before tracing a request flow

#### Avoid when
- Working on a pure library or CLI module with no web routes

#### Required inputs
None

#### Optional inputs
`framework`, `method`, `path`

#### Minimal invocation
```python
list_routes()
```

#### Advanced invocation
```python
list_routes(method="POST", path="/api/v1/auth/login")
```

#### Result interpretation
- **Output Type**: `RouteListResult`
- **Key Fields**: `status`, `routes`, `route_path`, `http_method`, `handler_name`, `canonical_id`, `framework`, `file`, `line`, `evidence_class`
- **Relationships Emitted**: `HANDLED_BY`, `ROUTE_HANDLER`, `MOUNTS`, `ROUTES_TO`

#### Evidence meaning
Framework-verified route paths, HTTP methods, composed mount prefixes, and handler canonical IDs.

#### Non-guarantees
Does not prove external API gateway or reverse-proxy rewrite rules outside the repository.

#### Typical follow-up
resolve_symbol, trace_path, or get_context(intent='TRACE')

#### Common mistakes
- Grepping for route path strings that are split across router prefix mounts instead of calling list_routes

#### Example
- **Developer request**: "Which handler serves POST /api/v1/auth/login?"
- **Call**: `list_routes(method="POST", path="/api/v1/auth/login")`
- **Interpretation**: Read handler_name, canonical_id, and file:line from the matched route entry.

### `plan_retrieval`

- **Capability**: `retrieval_plan_preview`
- **Profiles**: `developer`, `full`
- **Task Categories**: `MULTI_FILE_INVESTIGATION`, `DIAGNOSTIC`

#### Purpose
Construct a deterministic `RetrievalPlan` for a question or task (`query`; `task` supported as alias) without executing graph or source retrieval. Use to inspect planned retrieval steps, token budgets, and query expansions. Does not return code snippets or relationship edges.

#### Use when
- Inspecting how CodeGraph plans to allocate token budget for a complex query

#### Avoid when
- Normal interactive tasks where get_context can be called directly

#### Required inputs
`query`

#### Optional inputs
`task`, `max_tokens`, `resource_mode`

#### Minimal invocation
```python
plan_retrieval(query="Explain payment processing flow")
```

#### Advanced invocation
```python
plan_retrieval(query="Explain payment flow", max_tokens=10000, resource_mode="BALANCED")
```

#### Result interpretation
- **Output Type**: `RetrievalPlanDict`
- **Key Fields**: `intent`, `steps`, `token_budget`, `expanded_queries`, `ambiguities`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Deterministic step list, token budget allocation, and expanded queries.

#### Non-guarantees
Does not execute retrieval or prove symbol relationships.

#### Typical follow-up
get_context

#### Common mistakes
- Calling both plan_retrieval and compile_task redundantly before get_context

#### Example
- **Developer request**: "Preview the retrieval plan for tracing payment processing."
- **Call**: `plan_retrieval(query="Trace payment processing")`
- **Interpretation**: Inspect steps and expanded_queries, then invoke get_context.

### `read_file`

- **Capability**: `targeted_source_read`
- **Profiles**: `minimal`, `developer`, `full`
- **Task Categories**: `LOCAL_EDIT`, `DEBUG`, `EXPLANATION`

#### Purpose
Read a bounded line range (1..500 lines) of a non-sensitive repository file. Use AFTER CodeGraph tools identify the exact file and line span, or directly for trivial single-file edits. Blocks path traversal and sensitive credential files. Does not compute cross-file relationships.

#### Use when
- Inspecting exact implementation lines inside a symbol span identified by CodeGraph
- Performing a simple single-file edit

#### Avoid when
- Scanning dozens of files blindly instead of calling resolve_symbol or get_context first

#### Required inputs
`path`

#### Optional inputs
`start_line`, `end_line`

#### Minimal invocation
```python
read_file(path="src/auth/service.py", start_line=1, end_line=60)
```

#### Advanced invocation
```python
read_file(path="src/auth/service.py", start_line=40, end_line=95)
```

#### Result interpretation
- **Output Type**: `FileContentSlice`
- **Key Fields**: `file`, `start_line`, `end_line`, `content`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Exact on-disk source lines within repository privacy boundaries.

#### Non-guarantees
Does not compute cross-file callers, DI bindings, or test links.

#### Typical follow-up
perform code edit or synthesize final answer

#### Common mistakes
- Requesting >500 lines or attempting to read .env / secret key files (blocked by security policy)

#### Example
- **Developer request**: "Read lines 10 to 45 of src/auth/service.py."
- **Call**: `read_file(path="src/auth/service.py", start_line=10, end_line=45)`
- **Interpretation**: Inspect exact implementation statements in content for the requested line span.

### `reconcile_static_runtime`

- **Capability**: `static_runtime_reconciliation`
- **Profiles**: `full`
- **Task Categories**: `DEBUG`, `TRACE`, `DIAGNOSTIC`

#### Purpose
Reconcile static repository edges against ingested runtime observations, classifying edges into `CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`, `NOT_OBSERVED_AT_RUNTIME`, and `RUNTIME_ONLY_OBSERVED`. Use when comparing static code analysis with runtime behavior. Never treats `NOT_OBSERVED_AT_RUNTIME` as proof that a path cannot execute.

#### Use when
- Answering 'Where do static and runtime paths differ?' or 'Which dynamic calls were observed only at runtime?'

#### Avoid when
- Only static analysis is needed and no runtime traces have been ingested

#### Required inputs
None

#### Optional inputs
`symbol`, `route`, `table`

#### Minimal invocation
```python
reconcile_static_runtime()
```

#### Advanced invocation
```python
reconcile_static_runtime(route="/api/scan-bill", table="bills")
```

#### Result interpretation
- **Output Type**: `StaticRuntimeReconciliationResult`
- **Key Fields**: `status`, `confirmed_runtime_paths`, `static_runtime_conflicts`, `not_observed_at_runtime`, `runtime_only_observed`, `summary`
- **Relationships Emitted**: `CALLS`, `HANDLED_BY`, `READS_TABLE`, `WRITES_TABLE`, `POSSIBLE_CALLS`, `POSSIBLE_TABLE`

#### Evidence meaning
Explicit four-bucket reconciliation preserving both static evidence classes and RUNTIME_OBSERVED / RUNTIME_UNOBSERVED states.

#### Non-guarantees
Never overwrites static AST_VERIFIED edges and never treats NOT_OBSERVED_AT_RUNTIME as dead-code proof.

#### Typical follow-up
get_file on runtime_only_observed or static_runtime_conflicts locations

#### Common mistakes
- Deleting code in NOT_OBSERVED_AT_RUNTIME without checking if it handles rare error or admin paths

#### Example
- **Developer request**: "Where does the runtime behavior of /api/scan-bill differ from static analysis?"
- **Call**: `reconcile_static_runtime(route="/api/scan-bill")`
- **Interpretation**: Inspect confirmed_runtime_paths, static_runtime_conflicts, not_observed_at_runtime, and runtime_only_observed.

### `resolve_symbol`

- **Capability**: `symbol_resolution`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `RELATIONSHIP`, `DEBUG`, `CHANGE_IMPACT`, `TRACE`

#### Purpose
Resolve a symbol name, qualified name, canonical ID, or route into its canonical repository identity and file/line location. Use as the first step before relationship queries when exact symbol identity is unknown or potentially ambiguous. Primary input: `symbol` (also accepts `canonical_id` or `name` as compatibility aliases). Returns canonical_id, ambiguity_state, and candidate alternatives. Does not prove runtime execution or dynamic monkey-patching.

#### Use when
- Locating where a class, function, or method is canonically defined
- Disambiguating homonymous symbols across multiple modules or packages
- Grounding a symbol name into a canonical_id before calling get_callers or trace_path

#### Avoid when
- Purely local single-file text edit where the file and line are already open
- Repeatedly resolving the same canonical_id already returned in the current session

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `name`

#### Minimal invocation
```python
resolve_symbol(symbol="AuthService")
```

#### Advanced invocation
```python
resolve_symbol(symbol="src.auth.service.AuthService.authenticate")
```

#### Result interpretation
- **Output Type**: `SymbolResolutionResult`
- **Key Fields**: `status`, `canonical_id`, `qualified_name`, `file`, `start_line`, `end_line`, `ambiguity_state`, `matches`, `alternatives`
- **Relationships Emitted**: `DEFINES`, `RESOLVES_TO`

#### Evidence meaning
AST-verified symbol definition coordinates and explicit AMBIGUOUS/UNKNOWN states.

#### Non-guarantees
Does not prove runtime call edges or dynamic attribute injection.

#### Typical follow-up
get_callers, get_callees, get_references, trace_path, or get_context

#### Common mistakes
- Calling resolve_symbol repeatedly in a loop for the same symbol
- Choosing matches[0] blindly when ambiguity_state is AMBIGUOUS

#### Example
- **Developer request**: "Where is AuthService defined?"
- **Call**: `resolve_symbol(symbol="AuthService")`
- **Interpretation**: Inspect canonical_id, file, and start_line..end_line; if ambiguity_state == 'AMBIGUOUS', compare alternatives by module/package.

### `search_code`

- **Capability**: `lexical_code_search`
- **Profiles**: `agent`, `minimal`, `developer`, `full`
- **Task Categories**: `MULTI_FILE_INVESTIGATION`, `DEBUG`

#### Purpose
Search literal text, HTML/Jinja template IDs, UI strings, CSS selectors, config keys, or route paths across readable repository files and indexed code chunks. Use instead of grep when searching for exact text, button labels, or template strings. Does not prove semantic call, import, or route relationships; never creates semantic graph edges from text matches.

#### Use when
- Locating UI button labels, HTML/Jinja template IDs, CSS selectors, error message strings, SQL fragments, or configuration keys

#### Avoid when
- Answering who calls a function or what a module imports (use find_callers, get_callers, or get_imports)

#### Required inputs
`query`

#### Optional inputs
`top_k`, `path_filter`, `file_types`, `include_tests`, `include_configs`, `max_results`

#### Minimal invocation
```python
search_code(query="Add Manual Entry")
```

#### Advanced invocation
```python
search_code(query="Add Manual Entry", file_types=["html", "jinja2"], max_results=10)
```

#### Result interpretation
- **Output Type**: `CodeChunkSearchResult`
- **Key Fields**: `path`, `file`, `line`, `start_line`, `end_line`, `matched_text`, `snippet`, `category`, `file_category`, `match_type`, `symbol`, `score`, `reason`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Ranked source and text matches with file path, exact line number, matched_text, snippet, match_type, and file_category.

#### Non-guarantees
Does not prove module import graphs or caller/callee relationships; never creates semantic edges.

#### Typical follow-up
get_file on the matched path and line range, or find_symbol on enclosing symbol

#### Common mistakes
- Using search_code instead of find_callers/get_callers for structural symbol relationship queries

#### Example
- **Developer request**: "Where is the 'Add Manual Entry' button in HTML?"
- **Call**: `search_code(query="Add Manual Entry", top_k=10)`
- **Interpretation**: Inspect the matched `path`, `line`, `matched_text`, and `snippet`, then open the surrounding lines with `get_file`.

### `search_memory`

- **Capability**: `local_memory_lookup`
- **Profiles**: `full`
- **Task Categories**: `EXPLANATION`

#### Purpose
Search local SQLite repository memory notes by keyword up to `limit` (1..100). Use only to recall previously stored local session notes. Never overrides current AST or source-file evidence; does not prove current repository state.

#### Use when
- Looking up user-saved architectural notes in local memory

#### Avoid when
- Verifying actual code relationships (always use AST/graph tools instead)

#### Required inputs
`query`

#### Optional inputs
`limit`

#### Minimal invocation
```python
search_memory(query="auth")
```

#### Advanced invocation
```python
search_memory(query="deployment", limit=10)
```

#### Result interpretation
- **Output Type**: `MemoryNoteList`
- **Key Fields**: `key`, `value`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Local key-value notes stored in the repository memory table.

#### Non-guarantees
Never proves current code structure; source code and AST evidence always take precedence.

#### Typical follow-up
resolve_symbol or get_context to verify against current source

#### Common mistakes
- Trusting stale memory notes over current AST evidence

#### Example
- **Developer request**: "Search saved memory notes for 'auth'."
- **Call**: `search_memory(query="auth", limit=10)`
- **Interpretation**: Treat returned notes as auxiliary context subordinate to live source evidence.

### `search_symbols`

- **Capability**: `symbol_discovery`
- **Profiles**: `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `SYMBOL_LOOKUP`, `MULTI_FILE_INVESTIGATION`, `EXPLANATION`

#### Purpose
Search indexed repository symbols by partial name or keyword with ranked relevance. Use when exact symbol spelling is unknown and you need candidate symbol definitions. Returns ranked symbol definitions with file paths and line spans. Does not return module import graphs or call relationships.

#### Use when
- Finding where a feature or domain concept is defined across the codebase
- Discovering candidate symbols before calling resolve_symbol or get_context

#### Avoid when
- Discovering module imports or reverse dependencies (use get_imports or get_dependents instead)
- Editing a single known file locally

#### Required inputs
`query`

#### Optional inputs
`top_k`

#### Minimal invocation
```python
search_symbols(query="authenticate")
```

#### Advanced invocation
```python
search_symbols(query="token validator", top_k=10)
```

#### Result interpretation
- **Output Type**: `SymbolSearchResult`
- **Key Fields**: `status`, `query`, `results`, `canonical_id`, `qualified_name`, `kind`, `file`, `start_line`, `end_line`
- **Relationships Emitted**: `DEFINES`

#### Evidence meaning
AST-extracted symbol declarations with source file and line numbers.

#### Non-guarantees
Does not prove who calls or imports the matched symbols.

#### Typical follow-up
resolve_symbol or get_context

#### Common mistakes
- Treating lexical symbol search matches as proof of causal call relationships
- Using search_symbols to check module imports instead of get_imports

#### Example
- **Developer request**: "Find symbols related to password verification."
- **Call**: `search_symbols(query="verify_password", top_k=10)`
- **Interpretation**: Select the matching symbol definition and pass its symbol or canonical_id to get_callers or get_context.

### `trace_call`

- **Capability**: `directional_call_traversal`
- **Profiles**: `developer`, `full`
- **Task Categories**: `TRACE`, `RELATIONSHIP`

#### Purpose
Traverse callers, callees, or both from a single `symbol` (`canonical_id` supported as alias) up to `depth` with confidence and relationship labels. Use when exploring upstream and/or downstream call trees from one symbol without a known second endpoint. Does not prove runtime branch execution.

#### Use when
- Tracing 2 hops of upstream callers (`callers=True`) or downstream callees (`callees=True`) from one symbol

#### Avoid when
- Both start and target symbols are known (prefer trace_path)

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `depth`, `callers`, `callees`, `both`

#### Minimal invocation
```python
trace_call(symbol="verify_password", depth=2, callers=True)
```

#### Advanced invocation
```python
trace_call(symbol="AuthService.authenticate", depth=2, both=True)
```

#### Result interpretation
- **Output Type**: `DirectionalCallTraceList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `depth`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `CALLED_BY`, `POSSIBLE_CALLS`

#### Evidence meaning
Directional multi-hop call traversal with hop depth and confidence.

#### Non-guarantees
Does not prove runtime reachability under specific input conditions.

#### Typical follow-up
read_file on specific hops

#### Common mistakes
- Using trace_call when trace_path(from_symbol, to_symbol) would directly connect two known symbols

#### Example
- **Developer request**: "Trace 2 hops of upstream callers for verify_password."
- **Call**: `trace_call(symbol="verify_password", depth=2, callers=True)`
- **Interpretation**: Inspect each hop's source, target, depth, and evidence_class.

### `trace_flow`

- **Capability**: `bidirectional_flow_tracing`
- **Profiles**: `agent`, `developer`, `full`
- **Task Categories**: `TRACE`, `RELATIONSHIP`

#### Purpose
Trace multi-hop upstream callers and downstream callees around a single symbol (`symbol`; `canonical_id` supported as alias) up to `depth`. Use when exploring bidirectional execution flow around a function or handler without a known second endpoint. Does not prove runtime branch execution; use trace_path when both endpoints are known.

#### Use when
- Exploring upstream callers and downstream callees around a single symbol in one call

#### Avoid when
- Both start and target symbols are known (prefer trace_path)

#### Required inputs
`symbol`

#### Optional inputs
`canonical_id`, `depth`, `callers`, `callees`, `both`

#### Minimal invocation
```python
trace_flow(symbol="place_order", depth=2)
```

#### Advanced invocation
```python
trace_flow(symbol="AuthService.authenticate", depth=2, both=True)
```

#### Result interpretation
- **Output Type**: `DirectionalCallTraceList`
- **Key Fields**: `source`, `target`, `relationship`, `confidence`, `evidence_class`, `depth`, `file`, `start_line`
- **Relationships Emitted**: `CALLS`, `CALLED_BY`, `POSSIBLE_CALLS`

#### Evidence meaning
Bidirectional multi-hop call traversal with hop depth, confidence, and evidence_class.

#### Non-guarantees
Does not prove runtime reachability under specific input conditions.

#### Typical follow-up
get_file on specific hops

#### Common mistakes
- Using trace_flow when trace_path(from_symbol, to_symbol) would directly connect two known symbols

#### Example
- **Developer request**: "Trace the upstream and downstream call flow around place_order."
- **Call**: `trace_flow(symbol="place_order", depth=2)`
- **Interpretation**: Inspect each hop's source, target, depth, and evidence_class.

### `trace_path`

- **Capability**: `execution_path_tracing`
- **Profiles**: `agent`, `core`, `graph`, `minimal`, `developer`, `full`
- **Task Categories**: `TRACE`, `DEBUG`, `RELATIONSHIP`

#### Purpose
Compute deterministic multi-hop relationship paths between two symbols (`from_symbol` -> `to_symbol`). Use when tracing how an entrypoint, route, or caller reaches a downstream service or database function. Returns ordered hop edges with relationship types and evidence classes. Does not prove runtime branch conditions along the path.

#### Use when
- Proving how an HTTP endpoint or CLI command reaches a downstream repository or helper
- Connecting two symbols across multiple intermediate modules

#### Avoid when
- Only a single symbol is known and you want general context (use get_context instead)

#### Required inputs
`from_symbol`, `to_symbol`

#### Optional inputs
`start_symbol`, `target_symbol`, `source_symbol`, `max_depth`

#### Minimal invocation
```python
trace_path(from_symbol="login_endpoint", to_symbol="find_by_email")
```

#### Advanced invocation
```python
trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=5)
```

#### Result interpretation
- **Output Type**: `PathTraceResult`
- **Key Fields**: `status`, `from_symbol`, `to_symbol`, `path`, `paths`, `hops`, `evidence_class`, `confidence`
- **Relationships Emitted**: `CALLS`, `HANDLED_BY`, `MOUNTS`, `DISPATCHES_TO`, `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `TASK_HANDLER`, `COMMAND_HANDLER`, `EVENT_LISTENER`

#### Evidence meaning
Ordered multi-hop chain where every hop carries file, line, and evidence_class.

#### Non-guarantees
Does not prove that a conditional runtime branch is taken for a specific input payload.

#### Typical follow-up
get_file on specific hop lines if branch logic must be verified

#### Common mistakes
- Treating an empty path at max_depth=2 as proof of no connection without checking higher depth or dynamic dispatch

#### Example
- **Developer request**: "How does login_endpoint reach UserRepository.find_by_email?"
- **Call**: `trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)`
- **Interpretation**: Inspect the ordered hops in path/paths and verify each hop's relationship and evidence_class.

### `verify_evidence`

- **Capability**: `evidence_hash_verification`
- **Profiles**: `minimal`, `developer`, `full`
- **Task Categories**: `DIAGNOSTIC`, `DEBUG`

#### Purpose
Verify that a cited evidence span (`file_path`, `start_line`, `end_line`) exists on disk, matches `expected_hash`, and is not stale. Use to validate whether previously retrieved evidence is still current after repository edits. Does not re-index modified files.

#### Use when
- Confirming a cited snippet has not drifted on disk before applying a patch

#### Avoid when
- Freshly retrieved evidence in a read-only session where no files were modified

#### Required inputs
`file_path`, `start_line`, `end_line`

#### Optional inputs
`expected_hash`, `symbol`

#### Minimal invocation
```python
verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20)
```

#### Advanced invocation
```python
verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20, symbol="AuthService")
```

#### Result interpretation
- **Output Type**: `EvidenceVerificationResult`
- **Key Fields**: `valid`, `file`, `start_line`, `end_line`, `reason`, `current_hash`
- **Relationships Emitted**: None (non-edge output)

#### Evidence meaning
Cryptographic hash and line-bound check against current on-disk file content.

#### Non-guarantees
Does not prove semantic correctness of the code inside the span.

#### Typical follow-up
read_file if valid is False

#### Common mistakes
- Continuing to rely on a snippet when verify_evidence returns valid=False

#### Example
- **Developer request**: "Verify that lines 1..20 of src/auth/service.py are still valid."
- **Call**: `verify_evidence(file_path="src/auth/service.py", start_line=1, end_line=20)`
- **Interpretation**: Check valid boolean and reason field.

