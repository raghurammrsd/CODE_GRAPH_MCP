"""Hierarchical route composition engine for CodeGraph.

Composes declared framework routes across router mounting hierarchies:
1. FastAPI: include_router(...), nested prefixes, APIRouter definitions & aliases
2. Flask: register_blueprint(...), url_prefix composition, Blueprint definitions
3. Django: path(..., include(...)), multi-file urlpatterns composition
4. Express: app.use(...), router.use(...), nested router mounts

Architectural Invariants:
1. Deterministic and collision-free endpoint IDs.
2. Route composition produces FRAMEWORK_VERIFIED relationships only when statically proven.
3. Router mounting is NEVER represented as CALLS.
4. Exact source evidence is preserved for every mount and composed route.
5. Idempotent on repeated indexing; handles incremental route changes and file removals cleanly.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from codegraph.frameworks import (
    RouteDetection,
    RouterDefinition,
    RouterMountDetection,
    join_route_prefixes,
    normalize_route_path,
)
from codegraph.indexing.models import ImportRef


@dataclass(frozen=True)
class MountPathStep:
    prefix: str
    evidence: str
    file_path: str
    line: int
    parent_node: tuple[str, str]
    child_node: tuple[str, str]


@dataclass(frozen=True)
class ComposedMountEdge:
    parent_canonical_id: str
    child_canonical_id: str
    file_path: str
    line: int
    evidence: str
    framework: str


def _resolve_child_file_and_router(
    mount: RouterMountDetection,
    imports_by_file: dict[str, list[ImportRef]],
    known_files: set[str],
) -> tuple[str | None, str]:
    """Deterministically resolve a child router expression to its (target_file, target_router_name)."""
    child_expr = mount.child_router.strip("'\"")
    source_file = mount.file_path
    framework = mount.framework
    file_imports = imports_by_file.get(source_file, [])

    # 1. Match against imports in the mounting file
    for imp in file_imports:
        if imp.local_name == child_expr or imp.alias == child_expr:
            imported_mod = imp.imported_module
            imported_name = imp.imported_name or "router"

            # Express: relative or module path (e.g. './routes/users')
            if framework == "express":
                source_dir = posixpath.dirname(source_file)
                candidate_base = posixpath.normpath(posixpath.join(source_dir, imported_mod))
                candidates = [
                    f"{candidate_base}.ts",
                    f"{candidate_base}.js",
                    f"{candidate_base}/index.ts",
                    f"{candidate_base}/index.js",
                    candidate_base,
                ]
                for c in candidates:
                    norm_c = c.replace("\\", "/").lstrip("./")
                    if norm_c in known_files:
                        return norm_c, "router"
                    for kf in known_files:
                        if kf == norm_c or kf.endswith(f"/{norm_c}") or norm_c.endswith(f"/{kf}"):
                            return kf, "router"

            # Python: fastapi, flask, django
            else:
                if imported_mod.startswith("."):
                    # Relative import
                    dots = len(imported_mod) - len(imported_mod.lstrip("."))
                    curr_dir = Path(source_file).parent
                    for _ in range(dots - 1):
                        curr_dir = curr_dir.parent
                    rem = imported_mod.lstrip(".")
                    rel_sub = rem.replace(".", "/") if rem else ""
                    base_cand = curr_dir / rel_sub if rel_sub else curr_dir
                    candidates = [
                        f"{base_cand}.py",
                        f"{base_cand}/__init__.py",
                    ]
                else:
                    # Absolute import
                    mod_path = imported_mod.replace(".", "/")
                    candidates = [
                        f"{mod_path}.py",
                        f"src/{mod_path}.py",
                        f"{mod_path}/__init__.py",
                        f"src/{mod_path}/__init__.py",
                    ]

                for c in candidates:
                    norm_c = c.replace("\\", "/").lstrip("./")
                    if norm_c in known_files:
                        target_r = "urlpatterns" if framework == "django" else (imported_name if imported_name and imported_name != "*" else "router")
                        return norm_c, target_r
                    for kf in known_files:
                        if kf.endswith(norm_c) or norm_c.endswith(kf):
                            target_r = "urlpatterns" if framework == "django" else (imported_name if imported_name and imported_name != "*" else "router")
                            return kf, target_r

    # 2. Django string module name e.g. "myapp.urls"
    if framework == "django":
        clean_mod = child_expr.replace(".", "/")
        for c in (f"{clean_mod}.py", f"src/{clean_mod}.py", f"{clean_mod}/__init__.py"):
            norm_c = c.replace("\\", "/").lstrip("./")
            if norm_c in known_files:
                return norm_c, "urlpatterns"
            for kf in known_files:
                if kf.endswith(norm_c):
                    return kf, "urlpatterns"

    # 3. Same-file router reference
    return source_file, child_expr


def compose_routes(
    raw_routes: list[RouteDetection],
    mounts: list[RouterMountDetection],
    router_defs: list[RouterDefinition],
    imports: list[ImportRef],
    known_files: set[str],
) -> tuple[list[RouteDetection], list[ComposedMountEdge]]:
    """Hierarchically compose framework routes across router mounting hierarchies.

    Returns:
      (composed_routes, mount_edges)
    """
    imports_by_file: dict[str, list[ImportRef]] = {}
    for imp in imports:
        imports_by_file.setdefault(imp.source_file, []).append(imp)

    # 1. Base prefixes defined on routers (e.g. APIRouter(prefix="/items"), Blueprint(..., url_prefix="/auth"))
    base_prefixes: dict[tuple[str, str], tuple[str, str, int]] = {}
    for r_def in router_defs:
        if r_def.prefix:
            base_prefixes[(r_def.file_path, r_def.router_name)] = (
                r_def.prefix,
                r_def.evidence,
                r_def.line,
            )

    # 2. Group raw routes by (file_path, router_name)
    # Also index by file_path alone for routers whose local names might match default or single routers
    routes_by_node: dict[tuple[str, str], list[RouteDetection]] = {}
    routes_by_file: dict[str, list[RouteDetection]] = {}
    for rt in raw_routes:
        r_name = rt.router_name or "router"
        routes_by_node.setdefault((rt.file_path, r_name), []).append(rt)
        routes_by_file.setdefault(rt.file_path, []).append(rt)

    # 3. Resolve mount edges: parent_node -> child_node
    # parent_node: (mount.file_path, mount.parent_router)
    # child_node: (target_file, target_router_name)
    mount_edges: list[tuple[tuple[str, str], tuple[str, str], MountPathStep]] = []
    verified_mount_graph_edges: list[ComposedMountEdge] = []

    for m in mounts:
        target_file, target_router = _resolve_child_file_and_router(m, imports_by_file, known_files)
        if not target_file:
            continue

        parent_node = (m.file_path, m.parent_router)
        child_node = (target_file, target_router)

        step = MountPathStep(
            prefix=m.prefix,
            evidence=m.evidence,
            file_path=m.file_path,
            line=m.line,
            parent_node=parent_node,
            child_node=child_node,
        )
        mount_edges.append((parent_node, child_node, step))

        parent_canon = f"{m.file_path}::{m.parent_router}"
        child_canon = f"{target_file}::{target_router}"
        verified_mount_graph_edges.append(
            ComposedMountEdge(
                parent_canonical_id=parent_canon,
                child_canonical_id=child_canon,
                file_path=m.file_path,
                line=m.line,
                evidence=m.evidence,
                framework=m.framework,
            )
        )

    # Build adjacency maps
    incoming_edges: dict[tuple[str, str], list[MountPathStep]] = {}
    outgoing_edges: dict[tuple[str, str], list[MountPathStep]] = {}
    for parent_node, child_node, step in mount_edges:
        outgoing_edges.setdefault(parent_node, []).append(step)
        incoming_edges.setdefault(child_node, []).append(step)

    # 4. Find all paths reaching each router node
    # A path is a list of MountPathStep from an unparented root to the node.
    # If a node has incoming mounts, we compute all paths from roots to that node using DFS.
    paths_to_node: dict[tuple[str, str], list[list[MountPathStep]]] = {}

    def get_paths(node: tuple[str, str], visited: set[tuple[str, str]]) -> list[list[MountPathStep]]:
        if node in visited:
            return []
        in_steps = incoming_edges.get(node, [])
        if not in_steps:
            return [[]]

        all_paths: list[list[MountPathStep]] = []
        visited.add(node)
        for step in in_steps:
            parent_paths = get_paths(step.parent_node, visited.copy())
            for pp in parent_paths:
                all_paths.append(pp + [step])
        return all_paths

    for _, child_node, _ in mount_edges:
        if child_node not in paths_to_node:
            paths_to_node[child_node] = get_paths(child_node, set())

    # 5. Compose routes
    composed_routes: list[RouteDetection] = []
    seen_endpoint_ids: set[str] = set()

    # Track which nodes had routes successfully composed via mounts
    mounted_nodes: set[tuple[str, str]] = set()

    for node, paths in paths_to_node.items():
        node_file, node_router = node
        # Find matching routes for this node
        node_routes = routes_by_node.get(node, [])
        if not node_routes:
            # Fallback: if node_file has routes and there's only one router used in that file
            file_rts = routes_by_file.get(node_file, [])
            distinct_routers = {r.router_name for r in file_rts if r.router_name}
            if len(distinct_routers) <= 1:
                node_routes = file_rts

        if not node_routes:
            continue

        mounted_nodes.add(node)
        base_prefix, _, _ = base_prefixes.get(node, ("", "", 0))

        for path in paths:
            mount_prefix = join_route_prefixes(*[s.prefix for s in path])
            mount_evidence_chain = " -> ".join([f"{s.evidence} ({s.file_path}:{s.line})" for s in path])

            for rt in node_routes:
                composed_path = join_route_prefixes(mount_prefix, base_prefix, rt.route_path)
                composed_norm = normalize_route_path(composed_path, rt.framework)
                composed_ev = f"{rt.evidence}; mounted via {mount_evidence_chain}"
                if base_prefix:
                    composed_ev += f" (base prefix '{base_prefix}')"

                # Generate endpoint_id and ensure deterministic collision avoidance
                clean_path = rt.file_path.replace("\\", "/").strip().lstrip("./") or "root"
                handler_part = f"#{rt.handler_name}" if rt.handler_name else ""
                fw_part = f":{rt.framework}" if rt.framework else ""
                base_ep_id = f"API_ENDPOINT{fw_part}:{clean_path}:{rt.line}:{rt.http_method} {composed_norm}{handler_part}"

                final_ep_id = base_ep_id
                counter = 1
                while final_ep_id in seen_endpoint_ids:
                    final_ep_id = f"{base_ep_id}#m{counter}"
                    counter += 1
                seen_endpoint_ids.add(final_ep_id)

                composed_routes.append(
                    RouteDetection(
                        framework=rt.framework,
                        http_method=rt.http_method,
                        route_path=composed_path,
                        normalized_route=composed_norm,
                        handler_name=rt.handler_name,
                        handler_canonical_id=rt.handler_canonical_id,
                        file_path=rt.file_path,
                        line=rt.line,
                        column=rt.column,
                        confidence=rt.confidence,
                        resolution_status="RESOLVED",
                        evidence=composed_ev,
                        module=rt.module,
                        endpoint_id_override=final_ep_id,
                        router_name=rt.router_name,
                    )
                )

    # 6. Unmounted / standalone routes (or direct app routes with no parent mounts)
    for (f_path, r_name), node_routes in routes_by_node.items():
        if (f_path, r_name) in mounted_nodes:
            continue
        # Also check if the whole file was handled by a mount
        if any(mn[0] == f_path for mn in mounted_nodes):
            continue

        base_prefix, _, _ = base_prefixes.get((f_path, r_name), ("", "", 0))
        for rt in node_routes:
            if base_prefix:
                composed_path = join_route_prefixes(base_prefix, rt.route_path)
                composed_norm = normalize_route_path(composed_path, rt.framework)
                composed_ev = f"{rt.evidence} (base prefix '{base_prefix}')"
            else:
                composed_path = rt.route_path
                composed_norm = rt.normalized_route
                composed_ev = rt.evidence

            # Use default deterministic endpoint_id
            final_ep_id = rt.endpoint_id
            if base_prefix:
                clean_path = rt.file_path.replace("\\", "/").strip().lstrip("./") or "root"
                handler_part = f"#{rt.handler_name}" if rt.handler_name else ""
                fw_part = f":{rt.framework}" if rt.framework else ""
                final_ep_id = f"API_ENDPOINT{fw_part}:{clean_path}:{rt.line}:{rt.http_method} {composed_norm}{handler_part}"

            counter = 1
            cand_ep = final_ep_id
            while cand_ep in seen_endpoint_ids:
                cand_ep = f"{final_ep_id}#u{counter}"
                counter += 1
            seen_endpoint_ids.add(cand_ep)

            composed_routes.append(
                RouteDetection(
                    framework=rt.framework,
                    http_method=rt.http_method,
                    route_path=composed_path,
                    normalized_route=composed_norm,
                    handler_name=rt.handler_name,
                    handler_canonical_id=rt.handler_canonical_id,
                    file_path=rt.file_path,
                    line=rt.line,
                    column=rt.column,
                    confidence=rt.confidence,
                    resolution_status="RESOLVED",
                    evidence=composed_ev,
                    module=rt.module,
                    endpoint_id_override=cand_ep if cand_ep != rt.endpoint_id else None,
                    router_name=rt.router_name,
                )
            )

    return composed_routes, verified_mount_graph_edges
