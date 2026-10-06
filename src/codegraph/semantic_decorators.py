"""Semantic Decorator & Task/Command Framework Intelligence for CodeGraph.

Recognizes explicit, deterministic decorator-driven registrations:
  - Celery / task systems: @celery.task, @app.task, @shared_task -> TASK_HANDLER
  - Click / CLI commands: @click.command, @click.group, @command -> COMMAND_HANDLER
  - Django signals / event systems: @receiver, @event, @listener -> EVENT_LISTENER
  - General registry decorators: @registry.register -> REGISTERS

Invariants:
  - TASK_HANDLER != CALLS
  - COMMAND_HANDLER != CALLS
  - EVENT_LISTENER != CALLS
  - REGISTERS != CALLS
  - Unknown decorators remain ordinary AST metadata only.
  - Dynamic arguments produce UNKNOWN/POSSIBLE findings without fake canonical IDs.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from codegraph.epistemic import RelationshipEvidenceClass

if TYPE_CHECKING:
    from codegraph.binding_resolver import LocalBindingResolver
    from codegraph.indexing.models import ImportRef


@dataclass(frozen=True)
class SemanticDecoratorSpec:
    framework: str
    semantic_role: str  # TASK_HANDLER | COMMAND_HANDLER | EVENT_LISTENER | REGISTERS
    patterns: tuple[str, ...]


# Canonical registry of recognized semantic framework decorators
_RECOGNIZED_DECORATOR_SPECS: tuple[SemanticDecoratorSpec, ...] = (
    SemanticDecoratorSpec(
        framework="celery",
        semantic_role="TASK_HANDLER",
        patterns=("celery.task", "celery.shared_task", "shared_task", "app.task"),
    ),
    SemanticDecoratorSpec(
        framework="django",
        semantic_role="EVENT_LISTENER",
        patterns=("django.dispatch.receiver", "receiver"),
    ),
    SemanticDecoratorSpec(
        framework="click",
        semantic_role="COMMAND_HANDLER",
        patterns=("click.command", "click.group", "command", "group"),
    ),
    SemanticDecoratorSpec(
        framework="typer",
        semantic_role="COMMAND_HANDLER",
        patterns=("app.command",),
    ),
    SemanticDecoratorSpec(
        framework="di",
        semantic_role="INJECTS",
        patterns=("inject", "inject.inject", "di.inject"),
    ),
    SemanticDecoratorSpec(
        framework="di",
        semantic_role="PROVIDES",
        patterns=("provide", "di.provide", "provider", "singleton", "di.singleton"),
    ),
    SemanticDecoratorSpec(
        framework="langchain",
        semantic_role="TOOL_HANDLER",
        patterns=("tool", "langchain.tools.tool", "langchain_core.tools.tool", "agents.tool"),
    ),
    SemanticDecoratorSpec(
        framework="llama_index",
        semantic_role="TOOL_HANDLER",
        patterns=("function_tool", "llama_index.core.tools.function_tool"),
    ),
    SemanticDecoratorSpec(
        framework="ray",
        semantic_role="TASK_HANDLER",
        patterns=("ray.remote", "remote"),
    ),
    SemanticDecoratorSpec(
        framework="prefect",
        semantic_role="TASK_HANDLER",
        patterns=("prefect.task", "prefect.flow", "task", "flow"),
    ),
    SemanticDecoratorSpec(
        framework="zenml",
        semantic_role="TASK_HANDLER",
        patterns=("step", "pipeline"),
    ),
)


@dataclass(frozen=True)
class SemanticDecoratorDetection:
    decorator_expr: str
    target_name: str
    target_canonical_id: str
    file_path: str
    line: int
    semantic_role: str  # TASK_HANDLER | COMMAND_HANDLER | EVENT_LISTENER | REGISTERS
    framework: str
    metadata: dict[str, object] = field(default_factory=dict)
    is_conditional: bool = False
    is_dynamic_arg: bool = False
    reason: str | None = None
    evidence_class: RelationshipEvidenceClass = RelationshipEvidenceClass.FRAMEWORK_VERIFIED


def analyze_symbol_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    file_path: str,
    target_canonical_id: str,
    imports: list[ImportRef],
    binding_resolver: LocalBindingResolver | None = None,
    conditional_depth: int = 0,
) -> list[SemanticDecoratorDetection]:
    """Analyze decorators on a function or class AST node and extract recognized semantic decorators."""
    detections: list[SemanticDecoratorDetection] = []
    is_cond = conditional_depth > 0

    # Build local import map for quick grounded lookup
    import_map: dict[str, tuple[str, str | None]] = {}
    for imp in imports:
        loc = imp.local_name or imp.alias or imp.name or ""
        mod = imp.imported_module or imp.module
        orig = imp.imported_name or imp.name
        if loc:
            import_map[loc] = (mod, orig)

    for d in node.decorator_list:
        args_nodes: list[ast.expr] = []
        kw_nodes: list[ast.keyword] = []
        if isinstance(d, ast.Call):
            func_node = d.func
            args_nodes = d.args
            kw_nodes = d.keywords
        else:
            func_node = d

        raw_expr = ast.unparse(func_node) if hasattr(ast, "unparse") else ""
        if not raw_expr:
            continue

        # 1. Ground the decorator identifier
        grounded_name: str | None = None
        matched_spec: SemanticDecoratorSpec | None = None
        evidence_class = RelationshipEvidenceClass.FRAMEWORK_VERIFIED

        # Check direct qualified pattern
        for spec in _RECOGNIZED_DECORATOR_SPECS:
            if raw_expr in spec.patterns:
                # If qualified (e.g. celery.task, click.command, app.task)
                if "." in raw_expr:
                    base = raw_expr.split(".")[0]
                    # Verify base is imported or standard framework name
                    if base in import_map or base in ("app", "celery", "click", "django", "typer", "di", "inject", "ray", "langchain", "llama_index", "prefect", "zenml"):
                        grounded_name = raw_expr
                        matched_spec = spec
                        break
                else:
                    # Bare name (e.g. shared_task, receiver, command, inject, provide, singleton, tool)
                    # Verify it was imported from the framework or known pattern
                    if raw_expr in import_map:
                        imp_mod, imp_orig = import_map[raw_expr]
                        orig_or_raw = imp_orig or raw_expr
                        if spec.framework in imp_mod.lower() or orig_or_raw in spec.patterns:
                            grounded_name = f"{imp_mod}.{orig_or_raw}"
                            matched_spec = spec
                            break
                    elif raw_expr in ("inject", "provide", "singleton", "receiver", "tool", "function_tool", "remote", "step", "flow"):
                        grounded_name = raw_expr
                        matched_spec = spec
                        break

        # Check local alias via LocalBindingResolver (e.g. task = celery.task; @task)
        if not matched_spec and binding_resolver and "." not in raw_expr:
            alias_target, alias_ev, _rsn = binding_resolver.resolve(
                file_path=file_path,
                name=raw_expr,
                use_line=node.lineno,
            )
            if alias_target and alias_ev == RelationshipEvidenceClass.DATAFLOW_VERIFIED:
                for spec in _RECOGNIZED_DECORATOR_SPECS:
                    for pat in spec.patterns:
                        if pat in alias_target or alias_target.endswith(pat):
                            grounded_name = alias_target
                            matched_spec = spec
                            evidence_class = RelationshipEvidenceClass.DATAFLOW_VERIFIED
                            break
                    if matched_spec:
                        break

        # Check general registry decorator: @registry.register or @command_registry.register
        if not matched_spec and "." in raw_expr:
            base_part, attr_part = raw_expr.rsplit(".", 1)
            if attr_part == "register":
                base_lower = base_part.lower()
                if (
                    base_lower == "registry"
                    or base_lower.endswith("_registry")
                    or base_lower.endswith("registry")
                ):
                    grounded_name = raw_expr
                    matched_spec = SemanticDecoratorSpec(
                        framework="registry",
                        semantic_role="REGISTERS",
                        patterns=(raw_expr,),
                    )
                    evidence_class = RelationshipEvidenceClass.DATAFLOW_VERIFIED

        # If not recognized, ignore: leave as ordinary AST metadata only
        if not matched_spec or not grounded_name:
            continue

        # 2. Extract static arguments and detect dynamic arguments
        metadata: dict[str, object] = {}
        is_dynamic_arg = False
        dyn_reason: str | None = None

        if isinstance(func_node, ast.Call):
            is_dynamic_arg = True
            dyn_reason = "unsupported_decorator_factory"

        if matched_spec.semantic_role == "EVENT_LISTENER":
            # Extract events from args (e.g. @receiver(UserCreated) or @receiver([E1, E2]))
            event_names: list[str] = []
            for arg in args_nodes:
                if isinstance(arg, ast.Name):
                    event_names.append(arg.id)
                elif isinstance(arg, ast.Attribute) and hasattr(ast, "unparse"):
                    base_expr = ast.unparse(arg.value) if hasattr(ast, "unparse") else ""
                    if base_expr.lower() in ("config", "settings", "setting", "env", "environ", "os"):
                        is_dynamic_arg = True
                        dyn_reason = "dynamic_event_name"
                    else:
                        event_names.append(ast.unparse(arg))
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    event_names.append(arg.value)
                elif isinstance(arg, ast.Call):
                    is_dynamic_arg = True
                    dyn_reason = "unsupported_decorator_factory"
                elif isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if isinstance(elt, ast.Name):
                            event_names.append(elt.id)
                        elif isinstance(elt, ast.Attribute) and hasattr(ast, "unparse"):
                            base_expr = ast.unparse(elt.value) if hasattr(ast, "unparse") else ""
                            if base_expr.lower() in ("config", "settings", "setting", "env", "environ", "os"):
                                is_dynamic_arg = True
                                dyn_reason = "dynamic_event_name"
                            else:
                                event_names.append(ast.unparse(elt))
                        elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            event_names.append(elt.value)
                        elif isinstance(elt, ast.Call):
                            is_dynamic_arg = True
                            dyn_reason = "unsupported_decorator_factory"
                        else:
                            is_dynamic_arg = True
                            dyn_reason = "dynamic_event_name"
                else:
                    is_dynamic_arg = True
                    dyn_reason = "dynamic_event_name"
            if event_names:
                metadata["events"] = event_names
            for kw in kw_nodes:
                if kw.arg == "sender":
                    if isinstance(kw.value, (ast.Name, ast.Attribute)) and hasattr(ast, "unparse"):
                        metadata["sender"] = ast.unparse(kw.value)
                    elif isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        metadata["sender"] = kw.value.value

        elif matched_spec.semantic_role == "COMMAND_HANDLER":
            # Extract command name
            cmd_name: str | None = None
            if args_nodes:
                if isinstance(args_nodes[0], ast.Constant) and isinstance(args_nodes[0].value, str):
                    cmd_name = args_nodes[0].value
                elif isinstance(args_nodes[0], ast.Call):
                    is_dynamic_arg = True
                    dyn_reason = "unsupported_decorator_factory"
                else:
                    is_dynamic_arg = True
                    dyn_reason = "dynamic_command_name"
            for kw in kw_nodes:
                if kw.arg == "name":
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        cmd_name = kw.value.value
                    elif isinstance(kw.value, ast.Call):
                        is_dynamic_arg = True
                        dyn_reason = "unsupported_decorator_factory"
                    else:
                        is_dynamic_arg = True
                        dyn_reason = "dynamic_command_name"
            if cmd_name:
                metadata["command"] = cmd_name

        elif matched_spec.semantic_role == "TASK_HANDLER":
            # Extract task name
            task_name: str | None = None
            for kw in kw_nodes:
                if kw.arg == "name":
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        task_name = kw.value.value
                    elif isinstance(kw.value, ast.Call):
                        is_dynamic_arg = True
                        dyn_reason = "unsupported_decorator_factory"
                    else:
                        is_dynamic_arg = True
                        dyn_reason = "dynamic_task_name"
            if task_name:
                metadata["task_name"] = task_name

        elif matched_spec.semantic_role == "REGISTERS":
            # Extract registry key if provided: @registry.register("key")
            if args_nodes:
                if isinstance(args_nodes[0], ast.Constant) and isinstance(args_nodes[0].value, str):
                    metadata["registry_key"] = args_nodes[0].value
                elif isinstance(args_nodes[0], ast.Call):
                    is_dynamic_arg = True
                    dyn_reason = "unsupported_decorator_factory"
                else:
                    is_dynamic_arg = True
                    dyn_reason = "dynamic_registry_key"

        elif matched_spec.semantic_role == "PROVIDES":
            iface_name: str | None = None
            if args_nodes:
                if isinstance(args_nodes[0], (ast.Name, ast.Attribute)) and hasattr(ast, "unparse"):
                    iface_name = ast.unparse(args_nodes[0])
                elif isinstance(args_nodes[0], ast.Call):
                    is_dynamic_arg = True
                    dyn_reason = "unsupported_decorator_factory"
                else:
                    is_dynamic_arg = True
                    dyn_reason = "dynamic_provider"
            elif isinstance(node, ast.ClassDef) and node.bases and hasattr(ast, "unparse"):
                base0 = node.bases[0]
                if isinstance(base0, (ast.Name, ast.Attribute)):
                    iface_name = ast.unparse(base0)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns and hasattr(ast, "unparse"):
                if isinstance(node.returns, (ast.Name, ast.Attribute)):
                    iface_name = ast.unparse(node.returns)
            if not iface_name and not is_dynamic_arg:
                iface_name = node.name
            if iface_name:
                metadata["interface"] = iface_name

        metadata["evidence_class"] = evidence_class.value

        detections.append(
            SemanticDecoratorDetection(
                decorator_expr=raw_expr,
                target_name=node.name,
                target_canonical_id=target_canonical_id,
                file_path=file_path,
                line=node.lineno,
                semantic_role=matched_spec.semantic_role,
                framework=matched_spec.framework,
                metadata=metadata,
                is_conditional=is_cond,
                is_dynamic_arg=is_dynamic_arg,
                reason=dyn_reason,
                evidence_class=evidence_class,
            )
        )

    return detections
