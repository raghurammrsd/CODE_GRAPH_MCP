"""Deep Agent Brain Generator, Relationship Metadata & Automated Documentation Validator (Phase 13).

Derives the three-layer Agent Brain documentation from authoritative code sources:
- `TOOL_CAPABILITY_REGISTRY`, `CAPABILITY_MATRIX`, `MCP_PROFILE_RECOMMENDATIONS` (`agent_capabilities.py`)
- `ALLOWED_EVIDENCE_CLASSES`, `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX` (`evidence_contract.py`)
- `RETRIEVAL_POLICIES` (`retrieval_policy.py`)
- Actual MCP server tool signatures (`mcp/server.py`)
"""
from __future__ import annotations

import inspect
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from codegraph import __version__
from codegraph.agent_capabilities import (
    CAPABILITY_MATRIX,
    MCP_PROFILE_RECOMMENDATIONS,
    TOOL_CAPABILITY_REGISTRY,
    AgentTaskCategory,
    ToolCapabilitySpec,
)
from codegraph.evidence_contract import (
    ALLOWED_EVIDENCE_CLASSES,
    ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX,
)
from codegraph.retrieval_policy import RETRIEVAL_POLICIES


@dataclass(frozen=True)
class RelationshipSemanticsSpec:
    """Authoritative documentation metadata for an actual relationship type in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX`."""

    relationship: str
    meaning: str
    typical_source: str
    typical_target: str
    proves: str
    does_not_prove: str
    common_tool: str
    example: str


RELATIONSHIP_SEMANTICS_REGISTRY: dict[str, RelationshipSemanticsSpec] = {
    "CALLS": RelationshipSemanticsSpec(
        relationship="CALLS",
        meaning="Direct executable function, method, or constructor invocation proven by AST or conservative dataflow.",
        typical_source="Function, method, or route handler symbol",
        typical_target="Callee function, method, or class constructor",
        proves="A call expression in the source symbol statically targets the callee symbol.",
        does_not_prove="Does not prove that a conditional runtime branch is taken on a specific input.",
        common_tool="get_callers / get_callees / trace_path",
        example="`AuthService.authenticate` -> `CALLS` (`AST_VERIFIED`) -> `verify_password`",
    ),
    "CALLED_BY": RelationshipSemanticsSpec(
        relationship="CALLED_BY",
        meaning="Inverse of a verified `CALLS` edge (target is invoked by source caller).",
        typical_source="Callee symbol",
        typical_target="Caller symbol",
        proves="The target symbol contains a verified call site invoking the source symbol.",
        does_not_prove="Does not prove runtime execution frequency.",
        common_tool="get_callers / analyze_impact",
        example="`verify_password` -> `CALLED_BY` (`AST_VERIFIED`) -> `AuthService.authenticate`",
    ),
    "POSSIBLE_CALLS": RelationshipSemanticsSpec(
        relationship="POSSIBLE_CALLS",
        meaning="Candidate or dynamically dispatched call edge that is plausible (`POSSIBLE`) or unresolved (`UNKNOWN`).",
        typical_source="Caller symbol using dynamic dispatch, interface, or conditional binding",
        typical_target="Candidate target symbol or `<dynamic_target>`",
        proves="A call site exists where static analysis found a candidate or unresolved dynamic target.",
        does_not_prove="Never proves an authoritative `CALLS` edge without targeted source inspection.",
        common_tool="get_callers / get_callees / get_context",
        example="`dispatch_action` -> `POSSIBLE_CALLS` (`POSSIBLE`) -> `RefundHandler.handle`",
    ),
    "IMPORTS": RelationshipSemanticsSpec(
        relationship="IMPORTS",
        meaning="Module or symbol import statement extracted from syntax tree.",
        typical_source="Importing file or module",
        typical_target="Imported module or symbol",
        proves="The source module contains an explicit import statement for the target.",
        does_not_prove="Does not prove that the imported symbol is called at runtime.",
        common_tool="get_imports / get_dependents",
        example="`src/auth/routes.py` -> `IMPORTS` (`AST_VERIFIED`) -> `src.auth.service.AuthService`",
    ),
    "MOUNTS": RelationshipSemanticsSpec(
        relationship="MOUNTS",
        meaning="Application or parent router mounts a child router or sub-application under a URL prefix.",
        typical_source="Root application or parent router (`app`, `api_router`)",
        typical_target="Mounted sub-router (`auth_router`, `v1_router`)",
        proves="Framework router composition (`include_router`, `register_blueprint`, `app.use`).",
        does_not_prove="Does not prove direct function call semantics (`MOUNTS` is never collapsed into `CALLS`).",
        common_tool="list_routes / get_architecture / trace_path",
        example="`app` -> `MOUNTS` (`FRAMEWORK_VERIFIED`, prefix=`/api/v1`) -> `auth_router`",
    ),
    "ROUTE_HANDLER": RelationshipSemanticsSpec(
        relationship="ROUTE_HANDLER",
        meaning="Framework route decorator or registration binds an HTTP/RPC endpoint to its handler function.",
        typical_source="Router or endpoint declaration",
        typical_target="Handler function or controller method",
        proves="The route is bound to the handler via recognized framework syntax.",
        does_not_prove="Does not prove external reverse-proxy rewrites.",
        common_tool="list_routes / get_context",
        example="`POST /api/v1/auth/login` -> `ROUTE_HANDLER` (`FRAMEWORK_VERIFIED`) -> `login_endpoint`",
    ),
    "HANDLED_BY": RelationshipSemanticsSpec(
        relationship="HANDLED_BY",
        meaning="Canonical endpoint node is handled by the designated route handler symbol.",
        typical_source="HTTP endpoint (`POST /api/v1/auth/login`)",
        typical_target="Handler symbol (`login_endpoint`)",
        proves="Requests matching the route path and HTTP method are routed to the handler.",
        does_not_prove="Does not prove middleware short-circuiting prior to the handler.",
        common_tool="list_routes / trace_path / get_context",
        example="`POST /api/v1/auth/login` -> `HANDLED_BY` (`FRAMEWORK_VERIFIED`) -> `login_endpoint`",
    ),
    "ROUTES_TO": RelationshipSemanticsSpec(
        relationship="ROUTES_TO",
        meaning="URL dispatcher or route table entry routes a path pattern to a view or controller.",
        typical_source="Route table or URL pattern",
        typical_target="View function or class-based view",
        proves="Static URL routing table connects the pattern to the target view.",
        does_not_prove="Does not prove runtime query parameter validation.",
        common_tool="list_routes / trace_path",
        example="`/users/<id>` -> `ROUTES_TO` (`FRAMEWORK_VERIFIED`) -> `UserDetailView`",
    ),
    "REGISTERS": RelationshipSemanticsSpec(
        relationship="REGISTERS",
        meaning="Symbol or module registers a handler, plugin, or key into a registry or handler map.",
        typical_source="Decorator, registration call, or module initializer",
        typical_target="Registered handler symbol or registry container",
        proves="Static registration into a registry object (`@registry.register`, `REGISTRY[k] = fn`).",
        does_not_prove="Never proves a direct `CALLS` edge at registration time.",
        common_tool="get_references / get_context",
        example="`command_registry` -> `REGISTERS` (`DATAFLOW_VERIFIED`) -> `CreateInvoiceHandler`",
    ),
    "REGISTERED_HANDLER": RelationshipSemanticsSpec(
        relationship="REGISTERED_HANDLER",
        meaning="Links a registry key or registry container to the handler symbol registered for it.",
        typical_source="Registry or dispatch key",
        typical_target="Handler function or class",
        proves="The handler is statically associated with the registry entry.",
        does_not_prove="Does not prove when or how often the registry is invoked.",
        common_tool="get_references / get_context",
        example="`payment_registry['stripe']` -> `REGISTERED_HANDLER` (`DATAFLOW_VERIFIED`) -> `StripeGateway`",
    ),
    "DISPATCHES_TO": RelationshipSemanticsSpec(
        relationship="DISPATCHES_TO",
        meaning="Dispatcher function or registry lookup dispatches execution to a registered handler.",
        typical_source="Dispatcher function (`dispatch_command`, `bus.publish`)",
        typical_target="Target handler symbol (or `<dynamic_dispatch>` when key is runtime-only)",
        proves="Dispatch mechanism connects the dispatcher to the registered target(s).",
        does_not_prove="When `evidence_class='POSSIBLE'` or `'UNKNOWN'`, does not guarantee which runtime key is passed.",
        common_tool="trace_path / get_references / get_context",
        example="`dispatch_order_event` -> `DISPATCHES_TO` (`DATAFLOW_VERIFIED`) -> `on_order_created`",
    ),
    "EVENT_LISTENER": RelationshipSemanticsSpec(
        relationship="EVENT_LISTENER",
        meaning="Function or method subscribes to an event channel, signal, or domain event type.",
        typical_source="Event type, signal, or event bus (`OrderCreated`, `user_logged_in`)",
        typical_target="Listener function (`send_receipt_on_order`)",
        proves="Framework or event-bus decorator/subscription binds the listener to the event.",
        does_not_prove="Does not prove synchronous vs asynchronous runtime broker delivery.",
        common_tool="get_references / trace_path / get_context",
        example="`OrderCreated` -> `EVENT_LISTENER` (`FRAMEWORK_VERIFIED`) -> `notify_warehouse`",
    ),
    "TASK_HANDLER": RelationshipSemanticsSpec(
        relationship="TASK_HANDLER",
        meaning="Background task decorator (`@app.task`, `@shared_task`, `@dramatiq.actor`) marks a task entrypoint.",
        typical_source="Task queue / broker decorator or `.delay` / `.apply_async` site",
        typical_target="Task handler function (`send_welcome_email`)",
        proves="The function is registered as an executable background task handler.",
        does_not_prove="Does not prove broker queue availability at runtime.",
        common_tool="trace_path / get_context / get_references",
        example="`celery_app.task` -> `TASK_HANDLER` (`FRAMEWORK_VERIFIED`) -> `send_welcome_email`",
    ),
    "COMMAND_HANDLER": RelationshipSemanticsSpec(
        relationship="COMMAND_HANDLER",
        meaning="CLI or command-bus decorator (`@app.command`, `@click.command`) binds a CLI command to its handler.",
        typical_source="CLI application or command group",
        typical_target="Command handler function",
        proves="CLI command registration in Typer, Click, or argparse.",
        does_not_prove="Does not prove runtime CLI flag values.",
        common_tool="get_context / get_references / trace_path",
        example="`cli_app.command('migrate')` -> `COMMAND_HANDLER` (`FRAMEWORK_VERIFIED`) -> `run_migrations`",
    ),
    "INJECTS": RelationshipSemanticsSpec(
        relationship="INJECTS",
        meaning="Consumer endpoint, class, or function declares an injected dependency parameter (`Depends(provider)`, `@inject`).",
        typical_source="Consumer function/class (`login_endpoint`, `UserController`)",
        typical_target="Dependency provider or token (`get_auth_service`, `AuthService`)",
        proves="The consumer receives the dependency through framework or container injection.",
        does_not_prove="Never implies the consumer directly calls the provider as a normal helper (`INJECTS != CALLS`).",
        common_tool="get_context / get_references / trace_path",
        example="`login_endpoint` -> `INJECTS` (`FRAMEWORK_VERIFIED`) -> `get_auth_service`",
    ),
    "PROVIDES": RelationshipSemanticsSpec(
        relationship="PROVIDES",
        meaning="Dependency provider function or factory constructs/yields a concrete service or resource type.",
        typical_source="Provider function or container binding (`get_auth_service`)",
        typical_target="Provided type or implementation (`AuthService`)",
        proves="The provider supplies instances of the target type to DI consumers.",
        does_not_prove="Does not prove singleton vs request-scoped lifetime unless inspected in source.",
        common_tool="get_context / get_references / trace_path",
        example="`get_auth_service` -> `PROVIDES` (`FRAMEWORK_VERIFIED`) -> `AuthService`",
    ),
    "RESOLVES_DEPENDENCY": RelationshipSemanticsSpec(
        relationship="RESOLVES_DEPENDENCY",
        meaning="DI container or binding map resolves an abstract interface/token to a concrete implementation.",
        typical_source="Interface, protocol, or DI token (`PaymentGateway`)",
        typical_target="Concrete implementation (`StripePaymentGateway`)",
        proves="Container binding (`container.bind`, `app.dependency_overrides`) maps token to implementation.",
        does_not_prove="When multiple conditional bindings exist (`POSSIBLE`), does not prove which env branch is active.",
        common_tool="get_context / get_references / trace_path",
        example="`PaymentGateway` -> `RESOLVES_DEPENDENCY` (`DATAFLOW_VERIFIED`) -> `StripePaymentGateway`",
    ),
    "CONFIGURES": RelationshipSemanticsSpec(
        relationship="CONFIGURES",
        meaning="Settings object, environment config, or module initializer configures a service, router, or container.",
        typical_source="Config class or initializer (`Settings`, `configure_di`)",
        typical_target="Configured component or service",
        proves="Static configuration wiring between config symbols and target components.",
        does_not_prove="Does not expose secret `.env` values (sensitive files are blocked).",
        common_tool="get_context / get_references",
        example="`DatabaseSettings` -> `CONFIGURES` (`DATAFLOW_VERIFIED`) -> `create_engine_pool`",
    ),
    "DI_CYCLE": RelationshipSemanticsSpec(
        relationship="DI_CYCLE",
        meaning="Circular dependency detected across DI providers (`A -> B -> A`).",
        typical_source="Provider symbol participating in cycle",
        typical_target="Provider symbol completing the cycle",
        proves="A static cycle exists in the provider dependency graph.",
        does_not_prove="Does not prove whether lazy runtime resolution breaks the cycle.",
        common_tool="get_context / get_references",
        example="`provide_a` -> `DI_CYCLE` (`DATAFLOW_VERIFIED`) -> `provide_b`",
    ),
    "DEPENDS_ON_PACKAGE": RelationshipSemanticsSpec(
        relationship="DEPENDS_ON_PACKAGE",
        meaning="Manifest-backed workspace package declares a dependency on another workspace package.",
        typical_source="Consumer workspace package (`@acme/api`, `apps/api`)",
        typical_target="Target workspace package (`@acme/auth`, `packages/auth`)",
        proves="Explicit dependency in `package.json`, `pyproject.toml`, `Cargo.toml`, or `go.mod`.",
        does_not_prove="Never inferred from directory names alone without manifest evidence.",
        common_tool="get_architecture / get_context / get_dependents",
        example="`@acme/api` -> `DEPENDS_ON_PACKAGE` (`AST_VERIFIED`) -> `@acme/shared`",
    ),
    "PACKAGE_IMPORTS": RelationshipSemanticsSpec(
        relationship="PACKAGE_IMPORTS",
        meaning="Package-level rollup of source imports targeting another workspace package.",
        typical_source="Source workspace package",
        typical_target="Imported workspace package",
        proves="Files inside the source package import modules owned by the target package.",
        does_not_prove="Does not prove public API stability.",
        common_tool="get_architecture / get_imports",
        example="`packages/orders` -> `PACKAGE_IMPORTS` (`AST_VERIFIED`) -> `packages/shared`",
    ),
    "CROSS_PACKAGE_IMPORT": RelationshipSemanticsSpec(
        relationship="CROSS_PACKAGE_IMPORT",
        meaning="A source file in one workspace package imports a symbol or file across a package boundary.",
        typical_source="Source file in Package A",
        typical_target="Target file/symbol in Package B",
        proves="Cross-package import crossing manifest-verified package boundaries.",
        does_not_prove="Does not prove whether the import violates custom linter rules unless inspected.",
        common_tool="get_imports / get_context",
        example="`apps/web/src/client.ts` -> `CROSS_PACKAGE_IMPORT` (`AST_VERIFIED`) -> `packages/auth/src/index.ts`",
    ),
    "CONTAINS_PACKAGE": RelationshipSemanticsSpec(
        relationship="CONTAINS_PACKAGE",
        meaning="Workspace root or monorepo manifest contains a member workspace package.",
        typical_source="Workspace root",
        typical_target="Member package ID",
        proves="Workspace membership declared by workspace configuration (`pnpm-workspace.yaml`, `package.json`, `pyproject.toml`).",
        does_not_prove="Does not prove inter-package runtime calls.",
        common_tool="get_architecture",
        example="`workspace:root` -> `CONTAINS_PACKAGE` (`AST_VERIFIED`) -> `@acme/auth`",
    ),
    "TESTS": RelationshipSemanticsSpec(
        relationship="TESTS",
        meaning="Test function or test module exercises a production symbol or file.",
        typical_source="Test function (`test_login_flow`)",
        typical_target="Production symbol (`AuthService.authenticate`)",
        proves="Static call, import, fixture, or route link from test to target symbol.",
        does_not_prove="Does not prove that the test passes or covers 100% of branches.",
        common_tool="find_related_tests / get_git_impact / get_context",
        example="`test_login_route_flow` -> `TESTS` (`AST_VERIFIED`) -> `login_endpoint`",
    ),
    "TESTS_SYMBOL": RelationshipSemanticsSpec(
        relationship="TESTS_SYMBOL",
        meaning="Test function directly invokes or asserts against a production function, method, or class.",
        typical_source="Test function",
        typical_target="Production symbol",
        proves="AST-verified call or reference from the test body to the production symbol.",
        does_not_prove="Never fabricated from filename similarity alone.",
        common_tool="find_related_tests / get_context",
        example="`test_charge_card` -> `TESTS_SYMBOL` (`AST_VERIFIED`) -> `BillingService.charge_card`",
    ),
    "TESTS_ROUTE": RelationshipSemanticsSpec(
        relationship="TESTS_ROUTE",
        meaning="Test function sends an HTTP client request (`client.post('/api/v1/auth/login')`) to an indexed route.",
        typical_source="Test function",
        typical_target="Route endpoint or route handler",
        proves="Test client call path matches an indexed framework route.",
        does_not_prove="Does not prove external network integration.",
        common_tool="find_related_tests / get_context",
        example="`test_login_endpoint` -> `TESTS_ROUTE` (`FRAMEWORK_VERIFIED`) -> `POST /api/v1/auth/login`",
    ),
    "TESTS_PROVIDER": RelationshipSemanticsSpec(
        relationship="TESTS_PROVIDER",
        meaning="Test overrides or exercises a DI provider (`app.dependency_overrides[get_db] = ...`).",
        typical_source="Test function or fixture",
        typical_target="DI provider symbol",
        proves="Test explicitly references or overrides the DI provider.",
        does_not_prove="Does not prove production database behavior when provider is mocked.",
        common_tool="find_related_tests / get_context",
        example="`test_profile_with_mock_user` -> `TESTS_PROVIDER` (`FRAMEWORK_VERIFIED`) -> `get_current_user`",
    ),
    "TESTS_EVENT_HANDLER": RelationshipSemanticsSpec(
        relationship="TESTS_EVENT_HANDLER",
        meaning="Test publishes an event or directly invokes an event/task/command handler.",
        typical_source="Test function",
        typical_target="Event listener, task handler, or command handler",
        proves="Static link between test and event/task handler.",
        does_not_prove="Does not prove live message broker delivery.",
        common_tool="find_related_tests / get_context",
        example="`test_order_created_listener` -> `TESTS_EVENT_HANDLER` (`FRAMEWORK_VERIFIED`) -> `on_order_created`",
    ),
    "EXPORTS": RelationshipSemanticsSpec(
        relationship="EXPORTS",
        meaning="Module or package entrypoint explicitly exports a symbol (`__all__`, `export { X }`).",
        typical_source="Module or package index file",
        typical_target="Exported symbol",
        proves="Public export declaration in module AST.",
        does_not_prove="Does not prove external consumption outside the repo.",
        common_tool="get_file / get_symbol",
        example="`packages/auth/src/index.ts` -> `EXPORTS` (`AST_VERIFIED`) -> `AuthClient`",
    ),
    "REEXPORTS": RelationshipSemanticsSpec(
        relationship="REEXPORTS",
        meaning="Barrel file or `__init__.py` re-exports a symbol imported from an internal module.",
        typical_source="Barrel module (`__init__.py`, `index.ts`)",
        typical_target="Original symbol definition",
        proves="Explicit re-export binding across modules.",
        does_not_prove="Does not prove runtime execution.",
        common_tool="resolve_symbol / get_imports",
        example="`src/auth/__init__.py` -> `REEXPORTS` (`AST_VERIFIED`) -> `src/auth/service.py:AuthService`",
    ),
    "EXTENDS": RelationshipSemanticsSpec(
        relationship="EXTENDS",
        meaning="Class or interface inherits from a base class (`class Child(Base)` / `extends`).",
        typical_source="Subclass symbol",
        typical_target="Base class symbol",
        proves="AST-verified class inheritance.",
        does_not_prove="Does not prove dynamic metaclass mutation.",
        common_tool="get_symbol / get_references",
        example="`AdminUser` -> `EXTENDS` (`AST_VERIFIED`) -> `BaseUser`",
    ),
    "IMPLEMENTS": RelationshipSemanticsSpec(
        relationship="IMPLEMENTS",
        meaning="Class implements an interface, protocol, or abstract base class.",
        typical_source="Concrete class symbol",
        typical_target="Interface or Protocol symbol",
        proves="Static `implements` or protocol inheritance relationship.",
        does_not_prove="Does not prove structural duck-typing unless declared.",
        common_tool="get_references / get_context",
        example="`StripeGateway` -> `IMPLEMENTS` (`AST_VERIFIED`) -> `PaymentGateway`",
    ),
    "DEFINES": RelationshipSemanticsSpec(
        relationship="DEFINES",
        meaning="File or parent scope defines a class, function, method, or variable symbol.",
        typical_source="Source file or parent class",
        typical_target="Defined symbol",
        proves="Exact AST declaration coordinates (`file`, `start_line`, `end_line`).",
        does_not_prove="Does not prove who calls the symbol.",
        common_tool="resolve_symbol / get_file / get_symbol",
        example="`src/auth/service.py` -> `DEFINES` (`AST_VERIFIED`) -> `AuthService`",
    ),
    "CONTAINS": RelationshipSemanticsSpec(
        relationship="CONTAINS",
        meaning="Parent class or module scope lexically contains a child method or nested symbol.",
        typical_source="Class or module symbol",
        typical_target="Method or nested function symbol",
        proves="Lexical AST scope containment.",
        does_not_prove="Does not prove call order.",
        common_tool="get_symbol / get_file",
        example="`AuthService` -> `CONTAINS` (`AST_VERIFIED`) -> `AuthService.authenticate`",
    ),
    "RESOLVES_TO": RelationshipSemanticsSpec(
        relationship="RESOLVES_TO",
        meaning="Alias, import binding, or target reference resolves to its canonical symbol definition.",
        typical_source="Local alias or imported reference",
        typical_target="Canonical symbol definition",
        proves="Deterministic name/dataflow resolution to a canonical target.",
        does_not_prove="Does not prove runtime invocation.",
        common_tool="resolve_symbol / get_references",
        example="`auth_svc.authenticate` -> `RESOLVES_TO` (`DATAFLOW_VERIFIED`) -> `AuthService.authenticate`",
    ),
    "BINDS_TO": RelationshipSemanticsSpec(
        relationship="BINDS_TO",
        meaning="Local variable, attribute (`self.repo`), or parameter annotation binds to a concrete type or symbol.",
        typical_source="Variable or attribute (`self.repo`)",
        typical_target="Bound class or symbol (`UserRepository`)",
        proves="Conservative intra-file or constructor dataflow binding.",
        does_not_prove="Does not prove external runtime monkey-patching of the attribute.",
        common_tool="get_context / get_references",
        example="`AuthService.self.repo` -> `BINDS_TO` (`DATAFLOW_VERIFIED`) -> `UserRepository`",
    ),
    "ALIASED_TO": RelationshipSemanticsSpec(
        relationship="ALIASED_TO",
        meaning="Symbol or import is assigned an explicit alias (`import X as Y`, `HandlerAlias = RealHandler`).",
        typical_source="Alias identifier",
        typical_target="Original symbol",
        proves="Static alias assignment in module or function scope.",
        does_not_prove="Does not prove runtime reassignment if mutated dynamically.",
        common_tool="resolve_symbol / get_references",
        example="`LoginHandler` -> `ALIASED_TO` (`AST_VERIFIED`) -> `login_endpoint`",
    ),
    "REFERENCES": RelationshipSemanticsSpec(
        relationship="REFERENCES",
        meaning="Source symbol references another symbol (type annotation, constant read, decorator argument).",
        typical_source="Referencing symbol",
        typical_target="Referenced symbol",
        proves="Static identifier reference in AST.",
        does_not_prove="Does not prove an executable function call (`REFERENCES != CALLS`).",
        common_tool="get_references",
        example="`create_order` -> `REFERENCES` (`AST_VERIFIED`) -> `OrderCreateSchema`",
    ),
    "USES": RelationshipSemanticsSpec(
        relationship="USES",
        meaning="Symbol uses a type, trait, mixin, or configuration constant.",
        typical_source="Consumer symbol",
        typical_target="Used type or constant",
        proves="Static usage in type signature or body.",
        does_not_prove="Does not prove direct call execution.",
        common_tool="get_references / get_context",
        example="`TokenEncoder` -> `USES` (`AST_VERIFIED`) -> `JWT_ALGORITHM`",
    ),
    "DEPENDS_ON": RelationshipSemanticsSpec(
        relationship="DEPENDS_ON",
        meaning="General structural dependency edge between symbols or modules.",
        typical_source="Dependent symbol or module",
        typical_target="Dependency symbol or module",
        proves="Static dependency backed by import, call, or DI evidence.",
        does_not_prove="Check specific relationship subtype (`IMPORTS`, `INJECTS`, `CALLS`) for exact mechanism.",
        common_tool="get_dependents / get_context",
        example="`OrderService` -> `DEPENDS_ON` (`AST_VERIFIED`) -> `InventoryClient`",
    ),
    "UNRESOLVED_REFERENCE": RelationshipSemanticsSpec(
        relationship="UNRESOLVED_REFERENCE",
        meaning="A call, dispatch, or dependency site whose target could not be statically resolved (`UNKNOWN` or `POSSIBLE`).",
        typical_source="Source symbol containing dynamic/unresolved expression",
        typical_target="`<unresolved>` or candidate symbol name",
        proves="A dynamic or unindexed reference exists at the cited file and line.",
        does_not_prove="Never proves that no relationship exists at runtime.",
        common_tool="get_context / get_references",
        example="`PluginLoader.load` -> `UNRESOLVED_REFERENCE` (`UNKNOWN`) -> `<dynamic_getattr>`",
    ),
    "MAPS_TO_TABLE": RelationshipSemanticsSpec(
        relationship="MAPS_TO_TABLE",
        meaning="ORM model class maps to a canonical database table entity.",
        typical_source="ORM model class (`User`, `Product`)",
        typical_target="Canonical database table (`db.postgres.public.users`)",
        proves="Explicit (`__tablename__`, `db_table`, `@@map`) or framework-inferred model-to-table mapping.",
        does_not_prove="Does not prove that the table exists on an external unindexed database server.",
        common_tool="find_db_models / get_db_table / find_db_relationships",
        example="`Product` -> `MAPS_TO_TABLE` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products`",
    ),
    "MAPS_TO_COLUMN": RelationshipSemanticsSpec(
        relationship="MAPS_TO_COLUMN",
        meaning="ORM model attribute or field maps to a database table column.",
        typical_source="ORM model field (`Product.shop_id`)",
        typical_target="Canonical database column (`db.UNKNOWN.UNKNOWN.products.shop_id`)",
        proves="Static ORM column declaration (`Column`, `mapped_column`, `models.Field`, `Field`).",
        does_not_prove="Does not prove runtime column value constraints.",
        common_tool="find_db_columns / get_db_table",
        example="`Product.shop_id` -> `MAPS_TO_COLUMN` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products.shop_id`",
    ),
    "READS_TABLE": RelationshipSemanticsSpec(
        relationship="READS_TABLE",
        meaning="Function, method, or query reads rows from a database table (`SELECT`, `.query()`, `.objects.filter()`, `.findMany()`).",
        typical_source="Function, repository method, or route handler",
        typical_target="Canonical database table (`db.<dialect>.<schema>.<table>`)",
        proves="Static SQL `SELECT` or ORM read query targeting the table (or `RUNTIME_OBSERVED` when seen in runtime traces).",
        does_not_prove="Does not prove runtime cache hits or row counts.",
        common_tool="find_db_readers / find_db_callers / find_db_queries / get_db_table",
        example="`get_product` -> `READS_TABLE` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.products`",
    ),
    "WRITES_TABLE": RelationshipSemanticsSpec(
        relationship="WRITES_TABLE",
        meaning="Function, method, or query mutates rows in a database table (`INSERT`, `UPDATE`, `DELETE`, `.add()`, `.create()`, `.save()`).",
        typical_source="Service, repository method, or route handler",
        typical_target="Canonical database table (`db.<dialect>.<schema>.<table>`)",
        proves="Static SQL mutation or ORM write call targeting the table (or `RUNTIME_OBSERVED` in traces).",
        does_not_prove="Does not prove whether a transaction commits or rolls back at runtime.",
        common_tool="find_db_writers / find_db_callers / find_db_queries / get_db_impact",
        example="`create_order` -> `WRITES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.orders`",
    ),
    "READS_COLUMN": RelationshipSemanticsSpec(
        relationship="READS_COLUMN",
        meaning="Query or function explicitly selects or filters on a specific database column.",
        typical_source="Function or query site",
        typical_target="Canonical database column (`db.<dialect>.<schema>.<table>.<column>`)",
        proves="Column reference in `SELECT` projection, `WHERE` filter, or ORM field access.",
        does_not_prove="Does not prove index utilization at runtime.",
        common_tool="find_db_readers / get_db_impact",
        example="`find_by_email` -> `READS_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`",
    ),
    "WRITES_COLUMN": RelationshipSemanticsSpec(
        relationship="WRITES_COLUMN",
        meaning="Query or function explicitly inserts or updates a specific database column.",
        typical_source="Function or mutation query site",
        typical_target="Canonical database column (`db.<dialect>.<schema>.<table>.<column>`)",
        proves="Column assignment in `INSERT`, `UPDATE ... SET`, or ORM attribute mutation.",
        does_not_prove="Does not expose literal parameter values (redacted for security).",
        common_tool="find_db_writers / get_db_impact",
        example="`update_stock` -> `WRITES_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.inventory.quantity`",
    ),
    "REFERENCES_TABLE": RelationshipSemanticsSpec(
        relationship="REFERENCES_TABLE",
        meaning="Schema constraint, view, or query references a database table.",
        typical_source="Table, view, or symbol",
        typical_target="Referenced database table",
        proves="Static table reference in DDL, view, or ORM declaration.",
        does_not_prove="Does not prove direct row mutation (`REFERENCES_TABLE != WRITES_TABLE`).",
        common_tool="find_db_relationships / get_db_table",
        example="`order_summary_view` -> `REFERENCES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.orders`",
    ),
    "REFERENCES_COLUMN": RelationshipSemanticsSpec(
        relationship="REFERENCES_COLUMN",
        meaning="Constraint, index, or foreign key references a specific database column.",
        typical_source="ForeignKey, Index, or ORM field",
        typical_target="Referenced database column",
        proves="Static column reference in constraint or index definition.",
        does_not_prove="Does not prove runtime cascade execution.",
        common_tool="find_db_relationships / find_db_columns",
        example="`idx_users_email` -> `REFERENCES_COLUMN` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`",
    ),
    "FOREIGN_KEY_TO": RelationshipSemanticsSpec(
        relationship="FOREIGN_KEY_TO",
        meaning="Database column or ORM field declares a foreign-key reference to a target table/column.",
        typical_source="Source column (`db.UNKNOWN.UNKNOWN.orders.user_id`)",
        typical_target="Target column or table (`db.UNKNOWN.UNKNOWN.users.id`)",
        proves="Static `ForeignKey(...)` or SQL `REFERENCES` constraint.",
        does_not_prove="Does not prove whether foreign key checks are enabled in SQLite PRAGMA at runtime.",
        common_tool="find_db_relationships / get_db_table / get_db_schema",
        example="`db.UNKNOWN.UNKNOWN.orders.user_id` -> `FOREIGN_KEY_TO` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.id`",
    ),
    "HAS_PRIMARY_KEY": RelationshipSemanticsSpec(
        relationship="HAS_PRIMARY_KEY",
        meaning="Database table declares a primary-key column or constraint.",
        typical_source="Canonical database table",
        typical_target="Primary key column (`db.<dialect>.<schema>.<table>.<column>`)",
        proves="Static `primary_key=True`, `@id`, or SQL `PRIMARY KEY` declaration.",
        does_not_prove="Does not prove auto-increment sequence values.",
        common_tool="get_db_table / find_db_columns / find_db_relationships",
        example="`db.UNKNOWN.UNKNOWN.users` -> `HAS_PRIMARY_KEY` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.id`",
    ),
    "HAS_INDEX": RelationshipSemanticsSpec(
        relationship="HAS_INDEX",
        meaning="Database table declares a secondary index (`Index(...)`, `index=True`, `CREATE INDEX`, `@@index`).",
        typical_source="Canonical database table",
        typical_target="Index entity or indexed column",
        proves="Static index declaration in ORM model, SQL DDL, or migration.",
        does_not_prove="Does not prove query planner index selection at runtime.",
        common_tool="get_db_table / find_db_relationships",
        example="`db.UNKNOWN.UNKNOWN.users` -> `HAS_INDEX` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`",
    ),
    "HAS_UNIQUE_CONSTRAINT": RelationshipSemanticsSpec(
        relationship="HAS_UNIQUE_CONSTRAINT",
        meaning="Database table or column declares a uniqueness constraint (`unique=True`, `UniqueConstraint`, `UNIQUE`, `@unique`).",
        typical_source="Canonical database table",
        typical_target="Constrained column or constraint entity",
        proves="Static unique constraint in ORM model, SQL schema, or migration.",
        does_not_prove="Does not prove absence of duplicate legacy data prior to migration.",
        common_tool="get_db_table / find_db_columns / find_db_relationships",
        example="`db.UNKNOWN.UNKNOWN.users` -> `HAS_UNIQUE_CONSTRAINT` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users.email`",
    ),
    "HAS_CHECK_CONSTRAINT": RelationshipSemanticsSpec(
        relationship="HAS_CHECK_CONSTRAINT",
        meaning="Database table declares a `CheckConstraint` or SQL `CHECK (...)` expression.",
        typical_source="Canonical database table",
        typical_target="Check constraint entity",
        proves="Static check constraint declaration in ORM or SQL schema.",
        does_not_prove="Does not prove application-level validation.",
        common_tool="get_db_table / find_db_relationships",
        example="`db.UNKNOWN.UNKNOWN.products` -> `HAS_CHECK_CONSTRAINT` (`STATIC_VERIFIED`) -> `check_price_positive`",
    ),
    "MIGRATES_TABLE": RelationshipSemanticsSpec(
        relationship="MIGRATES_TABLE",
        meaning="Database migration file (Alembic, Django migration, Prisma migration, or SQL migration) creates, alters, or drops a table.",
        typical_source="Migration revision or file (`migrations/0001_initial.py`)",
        typical_target="Canonical database table",
        proves="Static migration operation (`op.create_table`, `migrations.CreateModel`, `CREATE TABLE`, `ALTER TABLE`).",
        does_not_prove="Does not prove whether the migration has been applied to a live deployment.",
        common_tool="get_db_table / get_db_schema / get_db_impact",
        example="`migrations/versions/001_init.py` -> `MIGRATES_TABLE` (`STATIC_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.users`",
    ),
    "QUERIES_DATABASE": RelationshipSemanticsSpec(
        relationship="QUERIES_DATABASE",
        meaning="Function or module executes a database query through a session, cursor, or engine.",
        typical_source="Function or method symbol",
        typical_target="Database entity or query target",
        proves="Database execution call (`cursor.execute`, `session.execute`, `conn.fetch`) at the cited lines.",
        does_not_prove="When target table is dynamic, pair with `POSSIBLE_TABLE` or `UNKNOWN_TABLE`.",
        common_tool="find_db_queries / get_runtime_trace",
        example="`run_report` -> `QUERIES_DATABASE` (`AST_VERIFIED`) -> `db.UNKNOWN.UNKNOWN`",
    ),
    "ORM_RELATION": RelationshipSemanticsSpec(
        relationship="ORM_RELATION",
        meaning="ORM model declares a high-level association (`relationship()`, `ForeignKey` relation, `@relation`) to another ORM model.",
        typical_source="Source ORM model (`Product`)",
        typical_target="Target ORM model (`Shop`)",
        proves="Framework-verified one-to-one, one-to-many, or many-to-many model association.",
        does_not_prove="Does not prove eager vs lazy loading behavior unless inspected via `get_file`.",
        common_tool="find_db_relationships / find_db_models / get_db_table",
        example="`Product` -> `ORM_RELATION` (`FRAMEWORK_VERIFIED`) -> `Shop`",
    ),
    "POSSIBLE_TABLE": RelationshipSemanticsSpec(
        relationship="POSSIBLE_TABLE",
        meaning="Query references a candidate database table via conditional logic or partial string interpolation (`evidence_class='POSSIBLE'`).",
        typical_source="Function or query site",
        typical_target="Candidate table name or `db.UNKNOWN.UNKNOWN.<candidate>`",
        proves="Plausible static table candidate that is not statically guaranteed.",
        does_not_prove="Never proves an unconditional `READS_TABLE` or `WRITES_TABLE` edge without source verification.",
        common_tool="find_db_queries / find_db_tables / get_context",
        example="`query_partition` -> `POSSIBLE_TABLE` (`POSSIBLE`) -> `db.UNKNOWN.UNKNOWN.events_archive`",
    ),
    "UNKNOWN_TABLE": RelationshipSemanticsSpec(
        relationship="UNKNOWN_TABLE",
        meaning="Database query executes a dynamically constructed SQL string or table identifier that cannot be statically resolved (`evidence_class='UNKNOWN'`).",
        typical_source="Function executing dynamic SQL",
        typical_target="`db.UNKNOWN.UNKNOWN.UNKNOWN`",
        proves="A database query occurs at the cited location whose target table is statically unresolvable.",
        does_not_prove="Never means no table is accessed; inspect the call site with `get_file` or runtime traces.",
        common_tool="find_db_queries / get_context",
        example="`execute_raw_dynamic` -> `UNKNOWN_TABLE` (`UNKNOWN`) -> `db.UNKNOWN.UNKNOWN.UNKNOWN`",
    ),
    "READS_ENV": RelationshipSemanticsSpec(
        relationship="READS_ENV",
        meaning="Module or function reads an environment variable (`os.getenv`, `os.environ.get`, `process.env`) for database or service configuration.",
        typical_source="File or symbol",
        typical_target="Environment variable name (`env:DATABASE_URL`) — never the secret value",
        proves="Static environment variable lookup by key name.",
        does_not_prove="Never exposes or stores the runtime environment variable's secret value.",
        common_tool="get_db_schema / get_context",
        example="`src/config.py` -> `READS_ENV` (`AST_VERIFIED`) -> `env:DATABASE_URL`",
    ),
    "RENDERS": RelationshipSemanticsSpec(
        relationship="RENDERS",
        meaning="React JSX component renders a child component element (`<ChildComponent ... />`).",
        typical_source="Parent component symbol (`DashboardPage`, `InvoiceTable`)",
        typical_target="Child component symbol (`InvoiceCard`, `Button`)",
        proves="Static JSX component composition tree hierarchy.",
        does_not_prove="Does not prove conditional branch execution at runtime unless inspected.",
        common_tool="find_callers / find_callees / get_references",
        example="`Dashboard` -> `RENDERS` (`AST_VERIFIED`) -> `InvoiceTable`",
    ),
    "USES_HOOK": RelationshipSemanticsSpec(
        relationship="USES_HOOK",
        meaning="React component or custom hook calls a state/lifecycle hook (`useAuth()`, `useInvoices()`).",
        typical_source="Component or custom hook (`UserProfile`, `useOrderDetails`)",
        typical_target="Hook function symbol (`useAuth`, `useQuery`)",
        proves="Component or custom hook lifecycle dependency on target hook.",
        does_not_prove="Does not prove hook return value shape without inspecting hook definition.",
        common_tool="find_callers / get_references / trace_path",
        example="`UserProfile` -> `USES_HOOK` (`FRAMEWORK_VERIFIED`) -> `useAuth`",
    ),
    "IMPORTS_STYLE": RelationshipSemanticsSpec(
        relationship="IMPORTS_STYLE",
        meaning="Component or module imports a CSS/SCSS stylesheet or CSS module (`import styles from './Button.module.css'`).",
        typical_source="Component or page file (`Button.tsx`)",
        typical_target="Stylesheet file (`Button.module.css`, `globals.css`)",
        proves="Component imports style definitions from target stylesheet.",
        does_not_prove="Does not prove all style classes in the file are actively applied.",
        common_tool="find_references / get_file / get_context",
        example="`Button.tsx` -> `IMPORTS_STYLE` (`AST_VERIFIED`) -> `Button.module.css`",
    ),
    "USES_STYLE_CLASS": RelationshipSemanticsSpec(
        relationship="USES_STYLE_CLASS",
        meaning="JSX element or component references a CSS class selector (`className={styles.header}` or `className='btn-primary'`).",
        typical_source="Component or JSX element (`Header.tsx`)",
        typical_target="CSS class symbol (`.header-title`, `.btn-primary`)",
        proves="Component applies the named CSS style class.",
        does_not_prove="Does not prove CSS specificity or cascade overrides.",
        common_tool="find_references / search_code / get_context",
        example="`Header.tsx` -> `USES_STYLE_CLASS` (`FRAMEWORK_VERIFIED`) -> `.header-title`",
    ),
    "FETCHES_ROUTE": RelationshipSemanticsSpec(
        relationship="FETCHES_ROUTE",
        meaning="Frontend component, hook, or API client invokes a backend HTTP route (`fetch('/api/v1/invoices')`, `axios.get(...)`).",
        typical_source="Frontend component or data hook (`useInvoices`, `createInvoiceForm`)",
        typical_target="Backend route endpoint (`POST /api/v1/invoices`, `GET /api/v1/users`)",
        proves="Frontend client-side network request targeting a backend route.",
        does_not_prove="Does not prove backend server availability at runtime.",
        common_tool="find_callers / trace_path / list_routes",
        example="`useInvoices` -> `FETCHES_ROUTE` (`FRAMEWORK_VERIFIED`) -> `GET /api/v1/invoices`",
    ),
    "LOADS_SCRIPT": RelationshipSemanticsSpec(
        relationship="LOADS_SCRIPT",
        meaning="HTML template or page loads a JavaScript/TypeScript script bundle (`<script src='...'>`).",
        typical_source="HTML file (`index.html`)",
        typical_target="Script file (`src/main.tsx`, `bundle.js`)",
        proves="HTML document includes and executes target script.",
        does_not_prove="Does not prove script execution order if async/defer are used.",
        common_tool="find_references / get_file",
        example="`index.html` -> `LOADS_SCRIPT` (`STATIC_VERIFIED`) -> `src/main.tsx`",
    ),
    "LOADS_STYLESHEET": RelationshipSemanticsSpec(
        relationship="LOADS_STYLESHEET",
        meaning="HTML template or page loads an external stylesheet (`<link rel='stylesheet' href='...'>`).",
        typical_source="HTML file (`index.html`)",
        typical_target="Stylesheet file (`src/index.css`, `theme.css`)",
        proves="HTML document links target stylesheet for presentation.",
        does_not_prove="Does not prove runtime CDN stylesheet availability.",
        common_tool="find_references / get_file",
        example="`index.html` -> `LOADS_STYLESHEET` (`STATIC_VERIFIED`) -> `src/index.css`",
    ),
    "MAPS_TO_COLLECTION": RelationshipSemanticsSpec(
        relationship="MAPS_TO_COLLECTION",
        meaning="NoSQL document model (Mongoose model) maps to an underlying MongoDB collection.",
        typical_source="Mongoose model (`InvoiceModel`)",
        typical_target="MongoDB collection (`invoices`)",
        proves="Static mapping between document model and database collection.",
        does_not_prove="Does not prove database schema strictness unless validation options are inspected.",
        common_tool="find_db_tables / find_db_models / get_db_table",
        example="`InvoiceModel` -> `MAPS_TO_COLLECTION` (`FRAMEWORK_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.invoices`",
    ),
    "WRITES_COLLECTION": RelationshipSemanticsSpec(
        relationship="WRITES_COLLECTION",
        meaning="Function or route writes (insert, update, delete) documents to a MongoDB collection.",
        typical_source="Caller symbol or API handler (`createInvoice`)",
        typical_target="MongoDB collection (`invoices`)",
        proves="Write operation (`Model.create`, `Model.updateOne`, `insertOne`) against target collection.",
        does_not_prove="Does not prove transaction commit or replica-set write concern acknowledgment.",
        common_tool="find_db_writers / get_context / trace_path",
        example="`createInvoice` -> `WRITES_COLLECTION` (`AST_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.invoices`",
    ),
    "READS_COLLECTION": RelationshipSemanticsSpec(
        relationship="READS_COLLECTION",
        meaning="Function or route reads (find, aggregate, count) documents from a MongoDB collection.",
        typical_source="Caller symbol or API handler (`listInvoices`)",
        typical_target="MongoDB collection (`invoices`)",
        proves="Read query (`Model.find`, `Model.findOne`, `aggregate`) against target collection.",
        does_not_prove="Does not prove document existence at runtime.",
        common_tool="find_db_readers / get_context / trace_path",
        example="`listInvoices` -> `READS_COLLECTION` (`AST_VERIFIED`) -> `db.UNKNOWN.UNKNOWN.invoices`",
    ),
    "DISPATCHES_TASK": RelationshipSemanticsSpec(
        relationship="DISPATCHES_TASK",
        meaning="Caller function or route dispatches a background task (.delay(), .apply_async(), .send_task()).",
        typical_source="Caller symbol or API handler (`checkout_order`, `register_user`)",
        typical_target="Task handler function (`process_order_payment`, `send_welcome_email`)",
        proves="Background task invocation connects caller to the queued task handler.",
        does_not_prove="Does not prove queue worker status or job execution timing.",
        common_tool="trace_path / find_callees / get_context",
        example="`checkout_order` -> `DISPATCHES_TASK` (`FRAMEWORK_VERIFIED`) -> `process_order_payment`",
    ),
    "TRIGGERS_SIGNAL": RelationshipSemanticsSpec(
        relationship="TRIGGERS_SIGNAL",
        meaning="Model lifecycle action (save, delete) or signal emission triggers a signal receiver.",
        typical_source="Model or lifecycle method (`Customer.save`, `signal.send`)",
        typical_target="Signal receiver function (`on_customer_created`)",
        proves="Django signal linkage connects the model or trigger site to registered receivers.",
        does_not_prove="Does not prove transaction commit before receiver execution.",
        common_tool="trace_path / find_callees / get_context",
        example="`Customer.save` -> `TRIGGERS_SIGNAL` (`FRAMEWORK_VERIFIED`) -> `on_customer_created`",
    ),
    "HANDLES_SIGNAL": RelationshipSemanticsSpec(
        relationship="HANDLES_SIGNAL",
        meaning="Signal receiver function handles lifecycle events or domain signals from a sender model.",
        typical_source="Receiver function (`on_customer_created`)",
        typical_target="Sender model symbol (`Customer`)",
        proves="Receiver function is bound to the sender model via @receiver or signal.connect.",
        does_not_prove="Does not prove receiver handles all signal kwargs.",
        common_tool="find_callers / get_references / get_context",
        example="`on_customer_created` -> `HANDLES_SIGNAL` (`FRAMEWORK_VERIFIED`) -> `Customer`",
    ),
    "RENDERS_TEMPLATE": RelationshipSemanticsSpec(
        relationship="RENDERS_TEMPLATE",
        meaning="View or controller renders an HTML or Jinja template (render_template, TemplateResponse, template_name).",
        typical_source="View handler symbol (`dashboard_view`)",
        typical_target="Template file path (`templates/dashboard.html`)",
        proves="Deterministic linkage between backend view function and frontend HTML template.",
        does_not_prove="Does not prove all template context variables are provided.",
        common_tool="list_routes / get_context / find_callees",
        example="`dashboard_view` -> `RENDERS_TEMPLATE` (`FRAMEWORK_VERIFIED`) -> `templates/dashboard.html`",
    ),
    "DISPATCHES_FORWARD": RelationshipSemanticsSpec(
        relationship="DISPATCHES_FORWARD",
        meaning="Neural network module invocation (model(inputs), self.submodule(x)) dispatches to nn.Module.forward().",
        typical_source="Caller function or model forward pass (`predict`, `Classifier.forward`)",
        typical_target="Submodule or model forward method (`Encoder.forward`, `Linear.forward`)",
        proves="PyTorch __call__ dispatch to forward method on a concrete or resolved module instance.",
        does_not_prove="Does not prove runtime execution if forward hooks or dynamic wrappers abort execution.",
        common_tool="trace_path / find_callees / get_context",
        example="`predict` -> `DISPATCHES_FORWARD` (`AST_VERIFIED`) -> `Classifier.forward`",
    ),
    "TOOL_HANDLER": RelationshipSemanticsSpec(
        relationship="TOOL_HANDLER",
        meaning="Function or method is decorated as an agentic AI tool (@tool, @function_tool, @agent).",
        typical_source="Tool function (`search_web_tool`, `execute_sql`)",
        typical_target="Agent framework registration decorator (`@tool`)",
        proves="Function is registered as a callable tool in an agentic workflow.",
        does_not_prove="Does not prove tool argument schema compatibility with LLM runtime.",
        common_tool="find_references / get_symbol / get_context",
        example="`search_web_tool` -> `TOOL_HANDLER` (`FRAMEWORK_VERIFIED`) -> `@tool`",
    ),
    "PIPELINE_STEP": RelationshipSemanticsSpec(
        relationship="PIPELINE_STEP",
        meaning="Sequential execution link in an AI/ML pipeline or LangChain LCEL chain (prompt | llm | parser).",
        typical_source="Upstream pipeline component or prompt template (`prompt_template`)",
        typical_target="Downstream pipeline component or model runner (`chat_model`)",
        proves="Dataflow pipe composition between execution steps in an AI/ML workflow.",
        does_not_prove="Does not prove runtime type convergence between pipe boundaries.",
        common_tool="trace_path / find_callees / get_context",
        example="`prompt_template` -> `PIPELINE_STEP` (`DATAFLOW_VERIFIED`) -> `chat_model`",
    ),
}


@dataclass(frozen=True)
class ComplexWorkflowExample:
    """Structured specification for one of the 25+ canonical complex workflows in Section 20 / Section 39."""

    workflow_id: int
    title: str
    developer_request: str
    task_classification: str
    why_codegraph: str
    first_tool: str
    arguments: str
    expected_result_interpretation: str
    followup_tool: str
    stop_condition: str
    source_read_fallback: str
    final_evidence_handling: str


COMPLEX_WORKFLOW_EXAMPLES: tuple[ComplexWorkflowExample, ...] = (
    ComplexWorkflowExample(
        workflow_id=1,
        title="Authentication route trace",
        developer_request="Trace how POST /api/v1/auth/login authenticates a user and queries the database.",
        task_classification="TRACE",
        why_codegraph="Route strings may be split across mounted routers (`MOUNTS`), handlers (`HANDLED_BY`), DI providers (`INJECTS`/`PROVIDES`), and services (`CALLS`).",
        first_tool="list_routes",
        arguments='list_routes(method="POST", path="/api/v1/auth/login")',
        expected_result_interpretation="Identify `handler_name` (e.g., `login_endpoint`), `canonical_id`, and `evidence_class='FRAMEWORK_VERIFIED'`.",
        followup_tool='trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)',
        stop_condition="Stop once the ordered hop chain from `POST /api/v1/auth/login` -> `login_endpoint` -> `AuthService.authenticate` -> `UserRepository.find_by_email` is verified.",
        source_read_fallback='Call `read_file(path="src/auth/service.py", start_line=10, end_line=40)` only if password comparison branch details are needed.',
        final_evidence_handling="Cite each hop with its relationship (`HANDLED_BY`, `INJECTS`, `CALLS`) and `evidence_class`.",
    ),
    ComplexWorkflowExample(
        workflow_id=2,
        title="Login handler -> service -> repository",
        developer_request="How does login_endpoint reach UserRepository.find_by_email?",
        task_classification="TRACE",
        why_codegraph="Both endpoint and target symbol names are known, making multi-hop graph path tracing deterministic.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="login_endpoint")',
        expected_result_interpretation="Confirm canonical ID `src/auth/routes.py:login_endpoint` and `ambiguity_state='CLEAR'`.",
        followup_tool='trace_path(from_symbol="login_endpoint", to_symbol="find_by_email", max_depth=4)',
        stop_condition="Stop as soon as `trace_path` returns the verified hop chain connecting the two symbols.",
        source_read_fallback="If any hop is marked `POSSIBLE`, use `read_file` on that hop's `file` and `start_line`.",
        final_evidence_handling="Present the exact hop sequence with file:line coordinates.",
    ),
    ComplexWorkflowExample(
        workflow_id=3,
        title="DI provider resolution",
        developer_request="Which provider supplies AuthService to login_endpoint?",
        task_classification="DEBUG",
        why_codegraph="CodeGraph extracts `INJECTS`, `PROVIDES`, and `RESOLVES_DEPENDENCY` relationships without collapsing them into `CALLS`.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="login_endpoint")',
        expected_result_interpretation="Obtain canonical ID for `login_endpoint`.",
        followup_tool='get_context(query="Which provider supplies AuthService to login_endpoint", intent="DEBUG", max_tokens=4000)',
        stop_condition="Stop when `INJECTS` (`login_endpoint` -> `get_auth_service`) and `PROVIDES` (`get_auth_service` -> `AuthService`) edges are retrieved.",
        source_read_fallback="Call `read_file` on `dependencies.py` only if constructor arguments inside `get_auth_service` need inspection.",
        final_evidence_handling="Distinguish `INJECTS` and `PROVIDES` (`FRAMEWORK_VERIFIED`) from direct `CALLS`.",
    ),
    ComplexWorkflowExample(
        workflow_id=4,
        title="FastAPI dependency chain",
        developer_request="Trace the FastAPI Depends() chain from get_current_active_user down to get_db_session.",
        task_classification="DEBUG",
        why_codegraph="Nested FastAPI `Depends()` parameters form multi-hop `INJECTS` and `PROVIDES` chains across files.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="get_current_active_user")',
        expected_result_interpretation="Confirm canonical definition of `get_current_active_user`.",
        followup_tool='get_context(query="FastAPI dependency chain get_current_active_user to get_db_session", intent="DEBUG", max_tokens=4000)',
        stop_condition="Stop when all nested `INJECTS`/`PROVIDES` hops to `get_db_session` are present in the `ContextPacket`.",
        source_read_fallback="Use `read_file` on `get_current_active_user` lines if HTTPException status codes are needed.",
        final_evidence_handling="Report each nested dependency link with its `FRAMEWORK_VERIFIED` evidence class.",
    ),
    ComplexWorkflowExample(
        workflow_id=5,
        title="Registry handler lookup",
        developer_request="What handlers are registered in command_registry and where does command_registry dispatch?",
        task_classification="RELATIONSHIP",
        why_codegraph="CodeGraph tracks `REGISTERS`, `REGISTERED_HANDLER`, and `DISPATCHES_TO` distinctly from `CALLS`.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="command_registry")',
        expected_result_interpretation="Resolve canonical ID of `command_registry`.",
        followup_tool='get_references(symbol="command_registry")',
        stop_condition="Stop once all `REGISTERS` and `DISPATCHES_TO` edges referencing `command_registry` are listed.",
        source_read_fallback="If any registration is conditional (`POSSIBLE`), read the cited registration lines with `read_file`.",
        final_evidence_handling="Never report `REGISTERS` edges as direct `CALLS`; preserve `REGISTERS` and `DISPATCHES_TO` labels.",
    ),
    ComplexWorkflowExample(
        workflow_id=6,
        title="Event listener discovery",
        developer_request="Which event listeners subscribe to OrderCreated across the repository?",
        task_classification="RELATIONSHIP",
        why_codegraph="Event listeners are decoupled from publishers and connected via `EVENT_LISTENER` edges.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="OrderCreated")',
        expected_result_interpretation="Obtain canonical ID of the `OrderCreated` event symbol.",
        followup_tool='get_references(symbol="OrderCreated")',
        stop_condition="Stop after collecting all `EVENT_LISTENER` and `DISPATCHES_TO` edges tied to `OrderCreated`.",
        source_read_fallback="Use `read_file` on listener spans if side-effect details (e.g., email template) are needed.",
        final_evidence_handling="Cite each listener with `EVENT_LISTENER` and its `evidence_class`.",
    ),
    ComplexWorkflowExample(
        workflow_id=7,
        title="Celery task tracing",
        developer_request="Trace how Celery task send_welcome_email is registered and what SMTP client it calls.",
        task_classification="TRACE",
        why_codegraph="Celery tasks combine `TASK_HANDLER` decorator semantics with downstream `CALLS` edges.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="send_welcome_email")',
        expected_result_interpretation="Locate `send_welcome_email` definition and confirm `TASK_HANDLER` metadata.",
        followup_tool='get_callees(symbol="send_welcome_email")',
        stop_condition="Stop once downstream `CALLS` to the SMTP client symbol are identified.",
        source_read_fallback="Call `read_file` on the task function span if retry/backoff decorator arguments are needed.",
        final_evidence_handling="Report `TASK_HANDLER` (`FRAMEWORK_VERIFIED`) for task registration and `CALLS` (`AST_VERIFIED`) for outgoing calls.",
    ),
    ComplexWorkflowExample(
        workflow_id=8,
        title="CLI command handler lookup",
        developer_request="Which function handles the CLI command `mcp doctor`?",
        task_classification="SYMBOL_LOOKUP",
        why_codegraph="CLI commands decorated with `@app.command` or `@mcp_app.command` produce `COMMAND_HANDLER` and symbol definitions.",
        first_tool="search_symbols",
        arguments='search_symbols(query="mcp_doctor", top_k=10)',
        expected_result_interpretation="Locate the CLI command handler symbol and its file/line coordinates.",
        followup_tool='get_symbol(symbol="src/codegraph/cli.py:mcp_doctor")',
        stop_condition="Stop once the command handler signature, decorators, and callees are identified.",
        source_read_fallback="Use `read_file` on the handler line range if CLI option defaults need inspection.",
        final_evidence_handling="Cite `COMMAND_HANDLER` / `DEFINES` evidence with exact file and line numbers.",
    ),
    ComplexWorkflowExample(
        workflow_id=9,
        title="Related tests discovery",
        developer_request="What tests cover BillingService.charge_card?",
        task_classification="TEST_DISCOVERY",
        why_codegraph="`find_related_tests` uses static call, import, fixture, and route links (`TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`) without lexical guessing.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="BillingService.charge_card")',
        expected_result_interpretation="Confirm canonical ID of `BillingService.charge_card`.",
        followup_tool='find_related_tests(symbol="BillingService.charge_card")',
        stop_condition="Stop when the statically linked test functions and their linking relationships are returned.",
        source_read_fallback="Call `read_file` on a returned test function only if specific assertion values need inspection.",
        final_evidence_handling="Report each test with its specific link type (`TESTS_SYMBOL`, `TESTS_ROUTE`, etc.) and `evidence_class`.",
    ),
    ComplexWorkflowExample(
        workflow_id=10,
        title="Change impact analysis on Git range",
        developer_request="Analyze the blast radius and affected tests for commits between HEAD~1 and HEAD.",
        task_classification="CHANGE_IMPACT",
        why_codegraph="`get_git_impact` maps Git diff hunks to AST symbol spans, downstream callers, workspace packages, and covering tests.",
        first_tool="get_git_impact",
        arguments='get_git_impact(base="HEAD~1", head="HEAD")',
        expected_result_interpretation="Inspect `modified_symbols`, `impacted_callers`, `affected_packages`, and `related_tests`.",
        followup_tool="find_related_tests (only if additional transitive symbol tests are needed)",
        stop_condition="Stop when `get_git_impact` returns the complete modified symbol, caller, package, and test sets.",
        source_read_fallback="Use `read_file` on modified symbol spans if exact diff logic needs line-by-line review.",
        final_evidence_handling="Present modified symbols, affected callers/packages, and static test coverage links.",
    ),
    ComplexWorkflowExample(
        workflow_id=11,
        title="Package dependency inspection",
        developer_request="What workspace packages does @acme/orders depend on in this monorepo?",
        task_classification="PACKAGE",
        why_codegraph="CodeGraph derives `DEPENDS_ON_PACKAGE` and `CROSS_PACKAGE_IMPORT` from actual manifest files (`package.json`, `pyproject.toml`, etc.).",
        first_tool="get_architecture",
        arguments="get_architecture()",
        expected_result_interpretation="Inspect `packages` and `package_dependencies` for `@acme/orders`.",
        followup_tool='get_context(query="workspace package dependencies of @acme/orders", intent="ARCHITECTURE", max_tokens=4000)',
        stop_condition="Stop once direct and bounded transitive `DEPENDS_ON_PACKAGE` edges for `@acme/orders` are identified.",
        source_read_fallback="Read `packages/orders/package.json` via `read_file` only if exact version semver strings are needed.",
        final_evidence_handling="Cite manifest-backed `DEPENDS_ON_PACKAGE` edges; never infer packages from directory names alone.",
    ),
    ComplexWorkflowExample(
        workflow_id=12,
        title="Monorepo architecture overview",
        developer_request="Explain the overall package boundaries, services, and entrypoints of this monorepo.",
        task_classification="ARCHITECTURE",
        why_codegraph="`get_architecture` summarizes manifest-verified packages, entrypoints, routes, and inter-package dependencies in one call.",
        first_tool="get_architecture",
        arguments="get_architecture()",
        expected_result_interpretation="Review `packages`, `package_dependencies`, `entrypoints`, and `routes`.",
        followup_tool='get_context(query="monorepo architecture overview and entrypoints", intent="ARCHITECTURE", max_tokens=4000)',
        stop_condition="Stop after `get_architecture` (and optional `get_context`) provides the package and entrypoint topology.",
        source_read_fallback="Avoid reading dozens of files; only read top-level manifest if workspace globs need manual check.",
        final_evidence_handling="Report manifest-verified packages and entrypoints with their `AST_VERIFIED`/`FRAMEWORK_VERIFIED` evidence.",
    ),
    ComplexWorkflowExample(
        workflow_id=13,
        title="Ambiguous symbol disambiguation",
        developer_request="What calls validate() in the payments module?",
        task_classification="RELATIONSHIP",
        why_codegraph="Generic method names like `validate` often exist in multiple classes; `resolve_symbol` surfaces `AMBIGUOUS` alternatives explicitly.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="validate")',
        expected_result_interpretation="Observe `ambiguity_state='AMBIGUOUS'` and inspect `alternatives` for the candidate in the `payments` module/package.",
        followup_tool='get_callers(symbol="src/payments/validator.py:PaymentValidator.validate")',
        stop_condition="Stop once callers of the disambiguated `canonical_id` are returned (or report ambiguity if context is insufficient).",
        source_read_fallback="Use `read_file` on candidate definitions if module names alone do not disambiguate.",
        final_evidence_handling="Never pick `matches[0]` blindly; state how the canonical symbol was disambiguated.",
    ),
    ComplexWorkflowExample(
        workflow_id=14,
        title="UNKNOWN dynamic dispatch handling",
        developer_request="What function does run_dynamic_hook(hook_name) call?",
        task_classification="RELATIONSHIP",
        why_codegraph="Dynamic `getattr(hooks, hook_name)()` cannot be proven statically and is surfaced as `POSSIBLE_CALLS` / `UNRESOLVED_REFERENCE` with `evidence_class='UNKNOWN'`.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="run_dynamic_hook")',
        expected_result_interpretation="Locate `run_dynamic_hook` canonical ID and line span.",
        followup_tool='get_callees(symbol="run_dynamic_hook")',
        stop_condition="Observe `evidence_class='UNKNOWN'` (or empty static callees with `unknowns` in `get_context`), then perform one targeted `read_file`.",
        source_read_fallback='Call `read_file(path="src/hooks/runner.py", start_line=1, end_line=50)` to inspect the `getattr` dispatch mechanism.',
        final_evidence_handling="State clearly that static analysis returned `UNKNOWN` due to runtime `getattr`; never claim 'run_dynamic_hook calls nothing'.",
    ),
    ComplexWorkflowExample(
        workflow_id=15,
        title="POSSIBLE registry target verification",
        developer_request="Which handler does dispatch_webhook invoke when event_type is conditional?",
        task_classification="TRACE",
        why_codegraph="Conditional or multi-branch registry bindings are labeled `evidence_class='POSSIBLE'` so the agent treats them as leads to verify.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="dispatch_webhook")',
        expected_result_interpretation="Resolve `dispatch_webhook` canonical ID.",
        followup_tool='get_context(query="dispatch_webhook handler targets", intent="TRACE", max_tokens=4000)',
        stop_condition="Identify `DISPATCHES_TO` edges marked `POSSIBLE`, then verify the branch condition via targeted `read_file`.",
        source_read_fallback="Call `read_file` on the cited registration/dispatch lines to check the `if/elif` or dict lookup condition.",
        final_evidence_handling="Report the target as `POSSIBLE` until confirmed by the targeted source read.",
    ),
    ComplexWorkflowExample(
        workflow_id=16,
        title="Generated and bundle code suppression",
        developer_request="Where is UserClient defined? Ignore generated SDKs and minified bundles.",
        task_classification="SYMBOL_LOOKUP",
        why_codegraph="CodeGraph classifies files into `SOURCE`, `TEST`, `GENERATED`, `BUNDLE`, `MINIFIED`, `VENDOR`, and `BUILD_ARTIFACT` and prioritizes authored `SOURCE`.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="UserClient")',
        expected_result_interpretation="Verify that the primary resolved symbol comes from authored `SOURCE` rather than `dist/` or `generated/`.",
        followup_tool='get_file(path="src/client/user_client.ts")',
        stop_condition="Stop once the authored `SOURCE` definition is confirmed.",
        source_read_fallback="Use `read_file` on the authored source file only if implementation lines are needed.",
        final_evidence_handling="Prefer `SOURCE` artifacts; note if duplicate generated/bundle copies were suppressed.",
    ),
    ComplexWorkflowExample(
        workflow_id=17,
        title="Stale index detection and fallback",
        developer_request="After editing src/auth/service.py on disk, check what AuthService.authenticate calls.",
        task_classification="DIAGNOSTIC",
        why_codegraph="`get_repository_status` and tool responses report `freshness='STALE'` when on-disk files have changed since the last index generation.",
        first_tool="get_repository_status",
        arguments="get_repository_status()",
        expected_result_interpretation="Observe `freshness='STALE'` and `modified_files=['src/auth/service.py']`.",
        followup_tool='read_file(path="src/auth/service.py", start_line=1, end_line=100)',
        stop_condition="Stop after verifying the modified file directly with `read_file` (or re-indexing via CLI).",
        source_read_fallback="Always use `read_file` on files listed in `modified_files` when `freshness == 'STALE'`.",
        final_evidence_handling="Do not present stale cached graph edges from modified files as current truth without verifying on-disk lines.",
    ),
    ComplexWorkflowExample(
        workflow_id=18,
        title="Debugging a runtime exception across files",
        developer_request="Debug why PaymentProcessor.capture raises CurrencyMismatchError during checkout.",
        task_classification="DEBUG",
        why_codegraph="`get_context(intent='DEBUG')` gathers the target method, upstream callers, downstream callees, DI providers, and covering tests in one bounded packet.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="PaymentProcessor.capture")',
        expected_result_interpretation="Confirm canonical ID and file:line location of `PaymentProcessor.capture`.",
        followup_tool='get_context(query="Debug CurrencyMismatchError in PaymentProcessor.capture", intent="DEBUG", max_tokens=4000)',
        stop_condition="Stop graph interrogation once `ContextPacket` provides callers (`process_checkout`) and callees; read exact exception line if needed.",
        source_read_fallback="Call `read_file` on the exact line range of `PaymentProcessor.capture` and `process_checkout` where currency is passed.",
        final_evidence_handling="Combine verified caller/callee graph evidence with the exact source lines raising the exception.",
    ),
    ComplexWorkflowExample(
        workflow_id=19,
        title="Refactoring a shared symbol safely",
        developer_request="We want to add a required `tenant_id` parameter to OrderRepository.save. What needs to be updated?",
        task_classification="CHANGE_IMPACT",
        why_codegraph="`analyze_impact` computes direct callers, transitive callers, affected routes, dependent files, and related tests.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="OrderRepository.save")',
        expected_result_interpretation="Confirm canonical ID `OrderRepository.save`.",
        followup_tool='analyze_impact(symbol="OrderRepository.save", max_depth=3)',
        stop_condition="Stop graph traversal once `direct_callers`, `affected_routes`, and `related_tests` are enumerated.",
        source_read_fallback="Use `read_file` on each direct caller's call-site line span to plan the parameter update.",
        final_evidence_handling="List every direct caller, affected route, and test file with exact line coordinates.",
    ),
    ComplexWorkflowExample(
        workflow_id=20,
        title="Finding affected tests before a commit",
        developer_request="Which pytest tests should we run after modifying TokenValidator.verify?",
        task_classification="TEST_DISCOVERY",
        why_codegraph="`find_related_tests` identifies tests linked via `TESTS_SYMBOL`, `TESTS_ROUTE`, or `TESTS_PROVIDER`.",
        first_tool="resolve_symbol",
        arguments='resolve_symbol(symbol="TokenValidator.verify")',
        expected_result_interpretation="Confirm canonical ID of `TokenValidator.verify`.",
        followup_tool='find_related_tests(symbol="TokenValidator.verify", max_results=20)',
        stop_condition="Stop as soon as the linked test functions and files are returned.",
        source_read_fallback="No `read_file` needed unless a test fails and its assertion lines must be inspected.",
        final_evidence_handling="Return the list of test functions and their static evidence classes.",
    ),
    ComplexWorkflowExample(
        workflow_id=21,
        title="Route-to-provider-to-repository trace",
        developer_request="Trace GET /api/v1/users/me through its FastAPI dependency provider to the database repository.",
        task_classification="TRACE",
        why_codegraph="Connects `HANDLED_BY` -> `INJECTS` -> `PROVIDES` -> `CALLS` across multiple files.",
        first_tool="list_routes",
        arguments='list_routes(method="GET", path="/api/v1/users/me")',
        expected_result_interpretation="Identify the route handler symbol (e.g., `get_me_endpoint`).",
        followup_tool='get_context(query="Trace GET /api/v1/users/me handler dependency provider and repository", intent="TRACE", max_tokens=4000)',
        stop_condition="Stop once the route, handler, injected provider (`get_current_user`), and repository call are present in the packet.",
        source_read_fallback="Use `read_file` only if token parsing details inside `get_current_user` are needed.",
        final_evidence_handling="Present the complete chain preserving `HANDLED_BY`, `INJECTS`, `PROVIDES`, and `CALLS`.",
    ),
    ComplexWorkflowExample(
        workflow_id=22,
        title="Architecture explanation for onboarding",
        developer_request="Give a concise architectural overview of this service, its entrypoints, and its core modules.",
        task_classification="ARCHITECTURE",
        why_codegraph="`get_architecture` provides a deterministic structural summary without scanning every file manually.",
        first_tool="get_architecture",
        arguments="get_architecture()",
        expected_result_interpretation="Inspect modules, entrypoints, routes, and package boundaries.",
        followup_tool='list_routes() (if detailed HTTP endpoint inventory is desired)',
        stop_condition="Stop once high-level modules, entrypoints, and routes are summarized.",
        source_read_fallback="Do not read individual implementation files unless asked about a specific module.",
        final_evidence_handling="Summarize the architecture using only AST- and manifest-verified facts.",
    ),
    ComplexWorkflowExample(
        workflow_id=23,
        title="Large repository multi-file feature investigation",
        developer_request="Where is rate limiting implemented and how is it wired into API endpoints?",
        task_classification="MULTI_FILE_INVESTIGATION",
        why_codegraph="Combining `search_symbols` -> `resolve_symbol` -> `get_context` avoids blind grep across hundreds of files.",
        first_tool="search_symbols",
        arguments='search_symbols(query="rate_limit", top_k=10)',
        expected_result_interpretation="Identify the primary rate limiter class/dependency (e.g., `RateLimiter` or `check_rate_limit`).",
        followup_tool='get_context(query="How rate limiting is implemented and wired into API endpoints", intent="UNDERSTAND", max_tokens=4000)',
        stop_condition="Stop when the rate limiter definition, its `INJECTS`/`CALLS` usages on routes, and tests are in the `ContextPacket`.",
        source_read_fallback="Use `read_file` on the rate limiter algorithm lines if token-bucket math details are requested.",
        final_evidence_handling="Cite definition coordinates and route wiring edges (`INJECTS` / `CALLS`).",
    ),
    ComplexWorkflowExample(
        workflow_id=24,
        title="One-file local edit bypass",
        developer_request="Fix a typo in the docstring of format_currency in src/utils/money.py.",
        task_classification="LOCAL_EDIT",
        why_codegraph="CodeGraph is NOT needed for trivial single-file edits where relationships do not matter.",
        first_tool="read_file",
        arguments='read_file(path="src/utils/money.py", start_line=1, end_line=60)',
        expected_result_interpretation="Read the exact docstring lines of `format_currency`.",
        followup_tool="None (apply edit directly)",
        stop_condition="Stop immediately after reading the target lines and applying the edit; make 0 graph calls.",
        source_read_fallback="Direct `read_file` is the primary tool for `LOCAL_EDIT`.",
        final_evidence_handling="Confirm the docstring edit directly in `src/utils/money.py`.",
    ),
    ComplexWorkflowExample(
        workflow_id=25,
        title="MCP unavailable or disconnected fallback",
        developer_request="Find all callers of verify_token when the CodeGraph MCP server is offline.",
        task_classification="RELATIONSHIP",
        why_codegraph="Normally handled by `resolve_symbol` -> `get_callers`, but when MCP is `DISCONNECTED` or `SERVER_FAILED`, safe fallback rules apply.",
        first_tool="read_file",
        arguments='read_file(path="src/auth/tokens.py", start_line=1, end_line=120)',
        expected_result_interpretation="Recognize MCP unavailability (`evaluate_fallback_policy(mcp_state='DISCONNECTED')`), use workspace search/targeted `read_file`.",
        followup_tool="Targeted `read_file` on candidate caller files found via search",
        stop_condition="Stop once candidate call sites are manually inspected in source files.",
        source_read_fallback="Direct search + `read_file` is the required fallback when MCP is disconnected.",
        final_evidence_handling="Explicitly note that results were verified via direct source inspection while CodeGraph MCP was offline.",
    ),
)


def _format_tool_reference_section(spec: ToolCapabilitySpec) -> str:
    """Render Section 6 / Section 41 complete tool reference entry for a single tool."""
    req_str = ", ".join(f"`{p}`" for p in spec.required_inputs) if spec.required_inputs else "None"
    opt_str = ", ".join(f"`{p}`" for p in spec.optional_inputs) if spec.optional_inputs else "None"
    rels_str = ", ".join(f"`{r}`" for r in spec.relationship_types_returned) if spec.relationship_types_returned else "None (non-edge output)"
    profs_str = ", ".join(f"`{p}`" for p in spec.profiles)
    fields_str = ", ".join(f"`{f}`" for f in spec.result_fields) if spec.result_fields else "`status`, payload fields"
    use_lines = "\n".join(f"- {u}" for u in spec.useful_situations)
    avoid_lines = "\n".join(f"- {a}" for a in spec.avoid_when)
    mistake_lines = (
        "\n".join(f"- {m}" for m in spec.common_mistakes)
        if spec.common_mistakes
        else "- Calling this tool redundantly when the answer is already in context."
    )

    return f"""### `{spec.tool_name}`

- **Capability**: `{spec.capability}`
- **Profiles**: {profs_str}
- **Task Categories**: {", ".join(f"`{t}`" for t in spec.task_types)}

#### Purpose
{spec.description}

#### Use when
{use_lines}

#### Avoid when
{avoid_lines}

#### Required inputs
{req_str}

#### Optional inputs
{opt_str}

#### Minimal invocation
```python
{spec.minimal_invocation or f"{spec.tool_name}()"}
```

#### Advanced invocation
```python
{spec.advanced_invocation or spec.minimal_invocation or f"{spec.tool_name}()"}
```

#### Result interpretation
- **Output Type**: `{spec.expected_output_type}`
- **Key Fields**: {fields_str}
- **Relationships Emitted**: {rels_str}

#### Evidence meaning
{spec.evidence_guarantees}

#### Non-guarantees
{spec.does_not_prove}

#### Typical follow-up
{spec.typical_followup or "Stop if the question is answered, or perform a targeted `read_file`."}

#### Common mistakes
{mistake_lines}

#### Example
- **Developer request**: "{spec.example_request}"
- **Call**: `{spec.example_call}`
- **Interpretation**: {spec.example_interpretation}
"""


def render_deep_agent_brain() -> str:
    """Render `docs/agent-brain.md` (Layer 3 Deep Agent Operating Manual) from code-derived registries."""
    # Build task classification table from CAPABILITY_MATRIX
    task_rows: list[str] = []
    for cat in AgentTaskCategory:
        rule = CAPABILITY_MATRIX[cat]
        seq_str = " -> ".join(f"`{s}`" for s in rule.recommended_sequence)
        primary_str = f"`{rule.primary_tool}`" if rule.primary_tool else "None (bypass CodeGraph)"
        task_rows.append(
            f"| `{cat.value}` | `{rule.should_use_codegraph}` | {primary_str} | {seq_str} | {rule.rationale} |"
        )
    task_table = "\n".join(task_rows)

    # Build retrieval policies table from RETRIEVAL_POLICIES
    policy_rows: list[str] = []
    for intent_name, pol in sorted(RETRIEVAL_POLICIES.items()):
        valid_rels = sorted(r for r in pol.allowed_relationship_types if r in ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX)
        rels_preview = ", ".join(f"`{r}`" for r in valid_rels[:8])
        if len(valid_rels) > 8:
            rels_preview += ", ..."
        flow_str = " -> ".join(pol.preferred_flow)
        policy_rows.append(
            f"| `{intent_name}` | `{pol.max_graph_depth}` | {flow_str} | {rels_preview} |"
        )
    policy_table = "\n".join(policy_rows)

    # Build relationship vocabulary section from ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX
    rel_sections: list[str] = []
    for rel_name in sorted(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX.keys()):
        allowed_ev = ", ".join(f"`{e}`" for e in sorted(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX[rel_name]))
        sem = RELATIONSHIP_SEMANTICS_REGISTRY[rel_name]
        rel_sections.append(
            f"#### `{rel_name}`\n"
            f"- **Meaning**: {sem.meaning}\n"
            f"- **Allowed Evidence Classes**: {allowed_ev}\n"
            f"- **Typical Source**: {sem.typical_source}\n"
            f"- **Typical Target**: {sem.typical_target}\n"
            f"- **What It Proves**: {sem.proves}\n"
            f"- **What It Does Not Prove**: {sem.does_not_prove}\n"
            f"- **Common Tool**: `{sem.common_tool}`\n"
            f"- **Example**: {sem.example}\n"
        )
    relationships_block = "\n".join(rel_sections)

    # Build MCP profiles table from MCP_PROFILE_RECOMMENDATIONS
    profile_rows: list[str] = []
    for prof_name in ("agent", "core", "graph", "minimal", "developer", "full"):
        pinfo = MCP_PROFILE_RECOMMENDATIONS[prof_name]
        tools_list = ", ".join(f"`{t}`" for t in pinfo["included_tools"])  # type: ignore[attr-defined]
        profile_rows.append(
            f"| `{prof_name}` | `{pinfo['tool_count']}` | {pinfo['recommended_for']} | {tools_list} |"
        )
    profiles_table = "\n".join(profile_rows)

    # Build 25 Complex Workflows section
    workflow_blocks: list[str] = []
    for wf in COMPLEX_WORKFLOW_EXAMPLES:
        workflow_blocks.append(
            f"### Workflow {wf.workflow_id}: {wf.title}\n"
            f"- **Developer request**: \"{wf.developer_request}\"\n"
            f"- **Task classification**: `{wf.task_classification}`\n"
            f"- **Why CodeGraph is appropriate**: {wf.why_codegraph}\n"
            f"- **First tool**: `{wf.first_tool}`\n"
            f"- **Arguments**: `{wf.arguments}`\n"
            f"- **Expected result interpretation**: {wf.expected_result_interpretation}\n"
            f"- **Follow-up tool**: `{wf.followup_tool}`\n"
            f"- **Stop condition**: {wf.stop_condition}\n"
            f"- **Source-read fallback**: {wf.source_read_fallback}\n"
            f"- **Final evidence handling**: {wf.final_evidence_handling}\n"
        )
    workflows_section = "\n".join(workflow_blocks)

    # Build Complete Tool Reference section
    tool_ref_blocks: list[str] = []
    for spec in sorted(TOOL_CAPABILITY_REGISTRY, key=lambda s: s.tool_name):
        tool_ref_blocks.append(_format_tool_reference_section(spec))
    complete_tool_reference = "\n".join(tool_ref_blocks)

    return f"""# CodeGraph Deep Agent Brain & Operating Manual (v{__version__})

> **Canonical Reference (`docs/agent-brain.md`)**
> Generated deterministically from `src/codegraph/agent_capabilities.py`, `src/codegraph/evidence_contract.py`, `src/codegraph/retrieval_policy.py`, and `src/codegraph/mcp/server.py`.
> Package: `codegraph-engine` (`v{__version__}`) | CLI: `codegraph` | MCP Command: `codegraph mcp serve`

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

CodeGraph enforces the {len(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX)} canonical relationship types in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX`. It **never** collapses framework routing, database operations, registry registration, or dependency injection into generic `CALLS` or `DEPENDS_ON`.

{relationships_block}

---

## 6. Task Classification & Routing Manifest

CodeGraph classifies developer requests into 13 canonical `AgentTaskCategory` values and provides a deterministic `ROUTING_MANIFEST`:

| Category | Use CodeGraph? | Primary Tool | Recommended Sequence | Rationale |
| :--- | :--- | :--- | :--- | :--- |
{task_table}

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
{policy_table}

- **Hard Invariants & Output Boundaries of `get_context`**:
  - Primary input is `query` (`task` is also supported as a string or `TaskSpec` dict alias).
  - Enforces strict output boundaries BEFORE MCP serialization: `max_tokens` (default `4000`, hard cap `20000`), `max_files` (default `25`, hard cap `40`), and `max_lines` (default `500`, hard cap `1500`).
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
{profiles_table}

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

{workflows_section}

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

## 41. Complete Tool Reference (All {len(TOOL_CAPABILITY_REGISTRY)} Exposed MCP Tools)

{complete_tool_reference}
"""


def render_tool_capabilities_summary() -> str:
    """Render `agent-rules/tool-capabilities-summary.md` (Section 24 compact capability summary)."""
    return f"""# CodeGraph MCP — Tool Capabilities Summary (v{__version__})

> Compact task-to-tool routing table derived from `src/codegraph/agent_capabilities.py` (`ROUTING_MANIFEST`) and `src/codegraph/evidence_contract.py`.

## Task Routing & Evidence Expectations

| Task / Domain | Preferred First Tool | Common Follow-Up Tool(s) | Evidence Expectations & Relationship Types |
| :--- | :--- | :--- | :--- |
| **`LOCAL_EDIT`** (Single-file typo / local variable) | `get_file` / `read_file` (Bypass CodeGraph) | Apply edit directly | Direct on-disk source lines; 0 graph calls needed. |
| **`SYMBOL_LOOKUP`** (Where is X defined?) | `find_symbol` / `resolve_symbol` | `get_symbol` -> `get_file` | `DEFINES`, `CONTAINS`, `RESOLVES_TO` (`AST_VERIFIED`) + explicit `AMBIGUOUS` alternatives. |
| **`TEXT / TEMPLATE SEARCH`** (Literal text, HTML id, UI label) | `search_code` | `get_file(path, start_line, end_line)` | Deterministic text match across `.py`, `.html`, `.jinja`, `.js`, `.ts`, `.css`, `.yaml`, `.json`, `.md` (never emits semantic edges). |
| **`FILE_INSPECTION`** (Show lines N..M of a file) | `get_file(path, start_line, end_line)` | `find_symbol` / `find_callers` | Bounded source lines (`content`, `truncated`, `category`) + AST symbol outline. |
| **`CALLERS / CALLEES`** (Who calls X / What does X call?) | `find_callers` / `find_callees` | `get_callers` / `get_callees` | `CALLS` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`) vs `POSSIBLE_CALLS` (`POSSIBLE`, `UNKNOWN`). |
| **`TRACE`** (End-to-end execution path) | `find_routes` / `find_symbol` | `trace_path` -> `get_context(intent="TRACE")` | Ordered hop chain (`HANDLED_BY`, `MOUNTS`, `INJECTS`, `PROVIDES`, `DISPATCHES_TO`, `CALLS`) + uncertainty preservation. |
| **`ROUTE_DISCOVERY`** (HTTP/RPC endpoints & mounts) | `find_routes` / `list_routes` | `find_symbol` -> `trace_path` | Composed route paths via `MOUNTS`, `HANDLED_BY`, `ROUTE_HANDLER`, `ROUTES_TO` (`FRAMEWORK_VERIFIED`). |
| **`DI`** (Dependency Injection & Providers) | `find_symbol` / `resolve_symbol` | `get_context(intent="DEBUG")` / `get_references` | `INJECTS`, `PROVIDES`, `RESOLVES_DEPENDENCY`, `CONFIGURES`, `DI_CYCLE` (never collapsed into `CALLS`). |
| **`REGISTRY / DISPATCH`** (Plugin & handler maps) | `find_symbol` / `resolve_symbol` | `get_references` / `get_context` | `REGISTERS`, `REGISTERED_HANDLER`, `DISPATCHES_TO` (`AST_VERIFIED`, `DATAFLOW_VERIFIED`, `POSSIBLE`, `UNKNOWN`). |
| **`EVENTS / TASKS / COMMANDS`** | `find_symbol` / `resolve_symbol` | `get_references` / `trace_path` | `EVENT_LISTENER`, `TASK_HANDLER`, `COMMAND_HANDLER` (`FRAMEWORK_VERIFIED`, `DATAFLOW_VERIFIED`). |
| **`TEST_DISCOVERY`** (What tests cover X?) | `find_tests` / `find_related_tests` | `get_file(path, start_line, end_line)` | `TESTS`, `TESTS_SYMBOL`, `TESTS_ROUTE`, `TESTS_PROVIDER`, `TESTS_EVENT_HANDLER` (never fabricated from lexical similarity). |
| **`CHANGE_IMPACT`** (Blast radius & Git diff impact) | `get_git_impact` / `analyze_impact` | `find_tests` -> `get_file` | Modified symbols, downstream `CALLS`/`IMPORTS`, affected `DEPENDS_ON_PACKAGE`, and covering `TESTS`. |
| **`PACKAGE`** (Monorepo & workspace boundaries) | `get_architecture` | `get_context(intent="ARCHITECTURE")` / `get_dependents` | Manifest-backed `DEPENDS_ON_PACKAGE`, `PACKAGE_IMPORTS`, `CROSS_PACKAGE_IMPORT`, `CONTAINS_PACKAGE`. |
| **`ARCHITECTURE`** (System & module overview) | `get_architecture` | `get_context(intent="ARCHITECTURE")` | Modules, workspace packages, entrypoints, and routes. |
| **`DATABASE`** (Tables, columns, ORM models, queries, impact) | `find_db_tables` / `get_db_table` | `find_db_callers` / `find_db_writers` / `get_db_impact` | `MAPS_TO_TABLE`, `MAPS_TO_COLUMN`, `READS_TABLE`, `WRITES_TABLE`, `FOREIGN_KEY_TO`, `MIGRATES_TABLE`, `POSSIBLE_TABLE`, `UNKNOWN_TABLE`. |
| **`RUNTIME`** (Traces & static-vs-runtime reconciliation) | `get_runtime_trace` / `reconcile_static_runtime` | `ingest_runtime_traces` -> `get_file` | `RUNTIME_OBSERVED` vs `RUNTIME_UNOBSERVED` (`CONFIRMED_RUNTIME_PATH`, `STATIC_RUNTIME_CONFLICT`, `NOT_OBSERVED_AT_RUNTIME`, `RUNTIME_ONLY_OBSERVED`). |
| **`DEBUG`** (Bug & exception investigation) | `get_context(intent="DEBUG")` | `get_file(path, start_line, end_line)` | Bounded `ContextPacket` (target + callers + callees + DI + database + runtime + tests) followed by targeted `get_file`. |
| **`DIAGNOSTIC`** (Index freshness & health) | `get_repository_status` | `get_resource_status` / `verify_evidence` | Index `generation`, `freshness` (`FRESH` vs `STALE`), `modified_files`, and SHA-256 evidence verification. |

## Epistemic Status Quick Reference

| Evidence / State | Meaning | Required Agent Behavior |
| :--- | :--- | :--- |
| **`AST_VERIFIED`** | Proven directly by syntax tree | Rely on relationship as verified static fact. |
| **`STATIC_VERIFIED`** | Proven by static SQL DDL/DML or migration parsing | Rely on table/column/query/migration relationship as verified static fact. |
| **`FRAMEWORK_VERIFIED`** | Proven by deterministic framework rules | Rely on route/ORM/DI/task/event relationship as verified framework fact. |
| **`DATAFLOW_VERIFIED`** | Proven by conservative local/container binding | Rely on resolved target as verified dataflow fact. |
| **`RUNTIME_OBSERVED`** | Observed in an ingested runtime trace (`observation_count >= 1`) | Treat as verified runtime execution fact; never promote to static `AST_VERIFIED` proof. |
| **`RUNTIME_UNOBSERVED`** | Not observed in the ingested runtime trace sample | Never claim the static path is dead code or impossible at runtime. |
| **`POSSIBLE`** | Plausible candidate, not statically guaranteed | Treat as lead; verify with targeted `get_file` / `read_file` before claiming as fact. |
| **`UNKNOWN`** | Static analysis could not prove target | **Never** claim "no relationship exists"; inspect call site with `get_file` / `read_file`. |
| **`AMBIGUOUS`** | Multiple symbols or tables match the target name | Inspect `alternatives` and disambiguate by module/package/schema; never pick `matches[0]` blindly. |
| **`STALE`** | Disk files changed since index generation | Verify `modified_files` with `get_file` / `read_file` or re-index (`codegraph index`). |
"""


def validate_agent_documentation(repo_root: Path | None = None) -> dict[str, object]:
    """Automated documentation validator (Section 25).

    Verifies that:
    1. Every tool in `TOOL_CAPABILITY_REGISTRY` and documented in `docs/agent-brain.md`,
       `.agents/skills/codegraph/SKILL.md`, and `agent-rules/` exists in `create_server(profile='full')`.
    2. Every documented parameter (`required_inputs` + `optional_inputs`) exists in the actual MCP tool signature.
    3. Every documented relationship exists in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX`.
    4. Every documented evidence class exists in `ALLOWED_EVIDENCE_CLASSES`.
    5. Every documented profile exists in `MCP_PROFILE_RECOMMENDATIONS`.
    6. Command names (`codegraph mcp serve`, `codegraph mcp doctor`, `codegraph mcp capabilities`,
       `codegraph mcp rules`) and package name (`codegraph-engine`) are current with zero stale names.
    7. All 41 required sections and 25+ complex workflows exist in `docs/agent-brain.md`.
    8. All 10 steps and required matrices exist in `.agents/skills/codegraph/SKILL.md`.
    """
    from codegraph.agent_rules import render_agent_rules, render_antigravity_skill
    from codegraph.mcp.server import create_server

    errors: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        srv = create_server(Path(tmp), profile="full")
        mcp_tools: dict[str, object] = getattr(srv._tool_manager, "_tools", {})

    actual_tool_names = set(mcp_tools.keys())
    registry_tool_names = {spec.tool_name for spec in TOOL_CAPABILITY_REGISTRY}

    # 1. Exact tool set parity between MCP server and TOOL_CAPABILITY_REGISTRY
    if actual_tool_names != registry_tool_names:
        missing_in_reg = sorted(actual_tool_names - registry_tool_names)
        extra_in_reg = sorted(registry_tool_names - actual_tool_names)
        errors.append(
            f"Tool set mismatch: missing_in_registry={missing_in_reg}, extra_in_registry={extra_in_reg}"
        )

    # 2. Exact parameter parity for every tool
    for spec in TOOL_CAPABILITY_REGISTRY:
        tool_obj = mcp_tools.get(spec.tool_name)
        if tool_obj is None:
            errors.append(f"Tool '{spec.tool_name}' not found in MCP server")
            continue
        fn = getattr(tool_obj, "fn", None)
        if fn is None:
            errors.append(f"Tool '{spec.tool_name}' has no underlying function")
            continue
        sig_params = set(inspect.signature(fn).parameters.keys())
        doc_params = set(spec.required_inputs) | set(spec.optional_inputs)
        if sig_params != doc_params:
            errors.append(
                f"Parameter mismatch on '{spec.tool_name}': documented={sorted(doc_params)} vs actual={sorted(sig_params)}"
            )
        # Check relationship types returned by tool
        for rel in spec.relationship_types_returned:
            if rel not in ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX:
                errors.append(f"Tool '{spec.tool_name}' documents unknown relationship '{rel}'")
        # Check profiles
        for prof in spec.profiles:
            if prof not in MCP_PROFILE_RECOMMENDATIONS:
                errors.append(f"Tool '{spec.tool_name}' documents unknown profile '{prof}'")

    # 3. Relationship semantics registry parity with ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX
    if set(RELATIONSHIP_SEMANTICS_REGISTRY.keys()) != set(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX.keys()):
        diff1 = sorted(set(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX.keys()) - set(RELATIONSHIP_SEMANTICS_REGISTRY.keys()))
        diff2 = sorted(set(RELATIONSHIP_SEMANTICS_REGISTRY.keys()) - set(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX.keys()))
        errors.append(f"Relationship semantics registry mismatch: missing={diff1}, extra={diff2}")

    # 4. Inspect rendered documentation texts
    brain_text = render_deep_agent_brain()
    skill_text = render_antigravity_skill()
    summary_text = render_tool_capabilities_summary()
    rules_text = render_agent_rules("antigravity")

    # Verify all 39 tools have a dedicated `### \`<tool_name>\`` heading in docs/agent-brain.md
    for tname in sorted(actual_tool_names):
        if f"### `{tname}`" not in brain_text:
            errors.append(f"docs/agent-brain.md is missing tool reference section for '{tname}'")

    # Verify no invented `### \`<tool>\`` headings in Section 41 of docs/agent-brain.md
    sec41_split = brain_text.split("## 41. Complete Tool Reference", 1)
    if len(sec41_split) != 2:
        errors.append("docs/agent-brain.md is missing '## 41. Complete Tool Reference'")
    else:
        documented_tool_headings = re.findall(r"^### `([a-z0-9_]+)`", sec41_split[1], flags=re.MULTILINE)
        for doc_t in documented_tool_headings:
            if doc_t not in actual_tool_names:
                errors.append(f"docs/agent-brain.md documents non-existent tool '{doc_t}'")

    # Verify all 41 numbered sections exist in docs/agent-brain.md
    for sec_num in range(1, 42):
        if not re.search(rf"^## {sec_num}\.\s+", brain_text, flags=re.MULTILINE):
            errors.append(f"docs/agent-brain.md is missing required Section {sec_num}")

    # Verify at least 25 complex workflows exist in docs/agent-brain.md
    workflow_headings = re.findall(r"^### Workflow (\d+):", brain_text, flags=re.MULTILINE)
    if len(workflow_headings) < 25:
        errors.append(f"docs/agent-brain.md has only {len(workflow_headings)} workflows (expected >= 25)")

    # Verify all 5 canonical evidence classes are documented
    for ev_cls in ALLOWED_EVIDENCE_CLASSES:
        for label, txt in (("agent-brain.md", brain_text), ("SKILL.md", skill_text), ("tool-capabilities-summary.md", summary_text)):
            if ev_cls not in txt:
                errors.append(f"Evidence class '{ev_cls}' missing from {label}")

    # Verify all 5 MCP profiles are documented
    for prof_name in MCP_PROFILE_RECOMMENDATIONS:
        if f"`{prof_name}`" not in brain_text:
            errors.append(f"MCP profile '{prof_name}' missing from docs/agent-brain.md")

    # Verify SKILL.md contains STEP 1 .. STEP 10 and required matrices
    for step_idx in range(1, 11):
        if f"STEP {step_idx}" not in skill_text:
            errors.append(f"SKILL.md is missing 'STEP {step_idx}'")
    for req_heading in (
        "## When to activate",
        "## When NOT to activate",
        "## Tool selection matrix",
        "## Evidence matrix",
        "## Relationship matrix",
        "## Common workflows",
        "## Failure/fallback workflow",
        "## Stop conditions",
    ):
        if req_heading not in skill_text:
            errors.append(f"SKILL.md is missing required heading '{req_heading}'")

    # Verify compact rules remain concise (2 KB .. 6 KB)
    if not (1500 <= len(rules_text) < 6000):
        errors.append(f"Compact agent rule length {len(rules_text)} outside bounds [1500, 6000)")

    # Verify current package and CLI command names and absence of stale names
    stale_terms = (
        "codegraph-mcp-server",
        "mcp-codegraph",
        "codegraph serve-mcp",
        "get_symbol_details",
        "find_all_callers",
        "search_repository",
    )
    for doc_name, txt in (
        ("agent-brain.md", brain_text),
        ("SKILL.md", skill_text),
        ("tool-capabilities-summary.md", summary_text),
        ("rules", rules_text),
    ):
        for stale in stale_terms:
            if stale in txt:
                errors.append(f"Stale identifier '{stale}' found in {doc_name}")

    # If repo_root is provided, verify on-disk files match generated content
    if repo_root is not None:
        disk_checks = {
            "docs/agent-brain.md": brain_text,
            ".agents/skills/codegraph/SKILL.md": skill_text,
            "agent-rules/tool-capabilities-summary.md": summary_text,
            ".agents/rules/codegraph.md": render_agent_rules("antigravity"),
            "agent-rules/AGENTS.md": render_agent_rules("agents"),
            "agent-rules/GEMINI.md": render_agent_rules("gemini"),
            "agent-rules/claude.md": render_agent_rules("claude"),
            "agent-rules/cursor.md": render_agent_rules("cursor"),
            "agent-rules/codex.md": render_agent_rules("codex"),
            "agent-rules/cline.md": render_agent_rules("cline"),
            "agent-rules/antigravity.md": render_agent_rules("antigravity"),
        }
        for rel_path, expected_content in disk_checks.items():
            fpath = repo_root / rel_path
            if not fpath.exists():
                errors.append(f"Required output file '{rel_path}' is missing on disk")
            else:
                actual_disk = fpath.read_text(encoding="utf-8")
                if actual_disk != expected_content:
                    errors.append(f"On-disk file '{rel_path}' is out of sync with canonical generator")

    return {
        "valid": len(errors) == 0,
        "tools_documented": len(actual_tool_names),
        "task_categories_documented": len(AgentTaskCategory),
        "relationships_documented": len(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX),
        "evidence_classes_documented": len(ALLOWED_EVIDENCE_CLASSES),
        "workflows_documented": len(COMPLEX_WORKFLOW_EXAMPLES),
        "profiles_documented": len(MCP_PROFILE_RECOMMENDATIONS),
        "errors": errors,
    }
