"""Repository architecture intelligence with structured node/edge graph projection.

Returns a structured view of the repository: entry points, endpoints, controllers,
services, models, APIs, tests, config, and framework integration edges.

All results are source-derived — no fictional architecture is generated.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_ENTRY_PATTERNS = re.compile(
    r"(^|[_/])(main|app|server|index|wsgi|asgi|manage|run)\.(py|js|ts)$",
    re.IGNORECASE,
)
_TEST_PATTERNS = re.compile(
    r"(^|[_/])test[_s]?[_/]|test[_s]?\.(py|js|ts)$|spec\.(py|js|ts)$",
    re.IGNORECASE,
)
_MODEL_PATTERNS = re.compile(
    r"(^|[_/])(model|schema|entity|orm|db)\.(py|js|ts)$|models?(\.py|\.ts|\.js|/)$",
    re.IGNORECASE,
)
_CONFIG_PATTERNS = re.compile(
    r"(^|[_/])(config|settings|conf|env)\.(py|js|ts)$",
    re.IGNORECASE,
)
_API_PATTERNS = re.compile(
    r"(^|[_/])(api|routes?|views?|controllers?|handlers?)\.(py|js|ts)$|/api/",
    re.IGNORECASE,
)
_REPO_PATTERNS = re.compile(
    r"(^|[_/])(repo|repository|store|dao)\.(py|js|ts)$",
    re.IGNORECASE,
)
_SERVICE_PATTERNS = re.compile(
    r"(^|[_/])(service|svc|manager|provider)\.(py|js|ts)$",
    re.IGNORECASE,
)
_INTEGRATION_PATTERNS = re.compile(
    r"(database|redis|celery|kafka|rabbitmq|s3|stripe|twilio|sendgrid|oauth|jwt|openai)",
    re.IGNORECASE,
)

_FRAMEWORK_IMPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    "flask": re.compile(r"^flask(?:\.|$)", re.IGNORECASE),
    "fastapi": re.compile(r"^fastapi(?:\.|$)", re.IGNORECASE),
    "django": re.compile(r"^django(?:\.|$)", re.IGNORECASE),
    "express": re.compile(r"^express(?:\/|$)", re.IGNORECASE),
    "nextjs": re.compile(r"^next(?:\/|$)", re.IGNORECASE),
    "tornado": re.compile(r"^tornado(?:\.|$)", re.IGNORECASE),
    "aiohttp": re.compile(r"^aiohttp(?:\.|$)", re.IGNORECASE),
    "starlette": re.compile(r"^starlette(?:\.|$)", re.IGNORECASE),
}

_MANIFEST_NAMES = (
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "setup.py",
    "setup.cfg",
    "Pipfile",
)


def detect_frameworks(
    con: sqlite3.Connection,
    repository: Path,
) -> list[str]:
    """Detect application frameworks using routes, AST imports, and bounded manifest discovery."""
    detected: set[str] = set()

    # 1. Concrete routes registered in database
    try:
        fw_rows = con.execute("SELECT DISTINCT framework FROM framework_routes").fetchall()
        for r in fw_rows:
            if r[0]:
                detected.add(str(r[0]).lower())
    except sqlite3.OperationalError:
        pass

    # 2. AST imports from indexed source files
    try:
        imp_rows = con.execute("SELECT DISTINCT module FROM imports WHERE module != ''").fetchall()
        for r in imp_rows:
            mod = str(r[0]).strip()
            for fw, pat in _FRAMEWORK_IMPORT_PATTERNS.items():
                if pat.search(mod):
                    detected.add(fw)
    except sqlite3.OperationalError:
        pass

    # 3. Bounded recursive manifest discovery (depth <= 3)
    try:
        root = repository.resolve()
        dirs_to_check: list[Path] = [root]

        def _subdirs(d: Path) -> list[Path]:
            res: list[Path] = []
            try:
                for entry in d.iterdir():
                    if entry.is_dir() and not entry.name.startswith(".") and entry.name != "node_modules":
                        res.append(entry)
            except OSError:
                pass
            return res

        level1 = _subdirs(root)
        dirs_to_check.extend(level1)
        for d1 in level1:
            level2 = _subdirs(d1)
            dirs_to_check.extend(level2)

        for d in dirs_to_check:
            try:
                for item in d.iterdir():
                    if not item.is_file():
                        continue
                    nm = item.name.lower()
                    if nm in _MANIFEST_NAMES or (nm.startswith("requirements") and nm.endswith(".txt")):
                        text = item.read_text(encoding="utf-8", errors="replace").lower()
                        for fw in ("flask", "fastapi", "django", "express", "tornado", "aiohttp", "starlette"):
                            if re.search(rf"(?:^|[^\w-]){fw}(?:[^\w-]|$)", text):
                                detected.add(fw)
                        if "next" in text and ("\"next\"" in text or "'next'" in text or "nextjs" in text):
                            detected.add("nextjs")
            except OSError:
                pass
    except Exception:
        pass

    return sorted(detected)


def get_architecture(
    con: sqlite3.Connection,
    repository: Path,
    max_per_category: int = 20,
) -> dict[str, object]:
    """Return a structured, source-derived architecture overview with nodes and edges."""
    files: list[str] = [
        r[0] for r in con.execute("SELECT path FROM files WHERE status='ok' ORDER BY path LIMIT 500")
    ]

    entry_points = [f for f in files if _ENTRY_PATTERNS.search(f)]
    test_files = [f for f in files if _TEST_PATTERNS.search(f)]
    model_files = [f for f in files if _MODEL_PATTERNS.search(f)]
    config_files = [f for f in files if _CONFIG_PATTERNS.search(f)]
    api_files = [f for f in files if _API_PATTERNS.search(f)]
    repo_files = [f for f in files if _REPO_PATTERNS.search(f)]
    service_files = [f for f in files if _SERVICE_PATTERNS.search(f)]

    # Integration hints from imports
    integrations: list[str] = []
    try:
        imp_rows = con.execute("SELECT DISTINCT module FROM imports LIMIT 500").fetchall()
        for row in imp_rows:
            m = _INTEGRATION_PATTERNS.search(row[0])
            if m:
                integrations.append(m.group(0).lower())
    except sqlite3.OperationalError:
        pass

    # Top-level classes
    class_rows = con.execute(
        "SELECT canonical_id, qualified_name, path, kind FROM symbols WHERE kind='class' LIMIT 100"
    ).fetchall()
    classes = [
        {"name": r["qualified_name"], "canonical_id": r["canonical_id"], "file": r["path"]}
        for r in class_rows
    ]

    # Concrete framework routes
    endpoints: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []

    try:
        route_rows = con.execute(
            "SELECT endpoint_id, framework, http_method, route_path, normalized_route, "
            "handler_name, handler_canonical_id, file_path, line, evidence, confidence "
            "FROM framework_routes LIMIT 100"
        ).fetchall()
        for rr in route_rows:
            ep = {
                "endpoint_id": rr["endpoint_id"],
                "framework": rr["framework"],
                "http_method": rr["http_method"],
                "route_path": rr["route_path"],
                "normalized_route": rr["normalized_route"],
                "handler_name": rr["handler_name"],
                "handler_canonical_id": rr["handler_canonical_id"],
                "file": rr["file_path"],
                "line": rr["line"],
                "evidence": rr["evidence"],
                "confidence": rr["confidence"],
            }
            endpoints.append(ep)
            nodes.append(
                {
                    "id": rr["endpoint_id"],
                    "name": f"{rr['http_method']} {rr['normalized_route']}",
                    "layer": "endpoint",
                    "file": rr["file_path"],
                    "line": rr["line"],
                    "confidence": rr["confidence"],
                }
            )
            if rr["handler_canonical_id"]:
                edges.append(
                    {
                        "source": rr["endpoint_id"],
                        "target": rr["handler_canonical_id"],
                        "relationship": "HANDLED_BY",
                        "confidence": rr["confidence"],
                        "evidence": rr["evidence"],
                    }
                )
    except sqlite3.OperationalError:
        pass

    # Frameworks
    frameworks = detect_frameworks(con, repository)

    # Top-level modules
    modules: list[str] = []
    try:
        mod_rows = con.execute(
            "SELECT DISTINCT module FROM symbols WHERE module != '' ORDER BY module LIMIT 20"
        ).fetchall()
        modules = [r[0] for r in mod_rows]
    except sqlite3.OperationalError:
        pass

    # Dependencies summary
    dependencies: list[dict[str, object]] = []
    try:
        dep_rows = con.execute(
            "SELECT module, count(*) AS c FROM imports GROUP BY module ORDER BY c DESC LIMIT 20"
        ).fetchall()
        dependencies = [{"module": r[0], "count": r[1]} for r in dep_rows]
    except sqlite3.OperationalError:
        pass

    # Generated artifacts
    generated_files: list[str] = []
    try:
        gen_rows = con.execute("SELECT path FROM files WHERE category='GENERATED' ORDER BY path LIMIT 20").fetchall()
        generated_files = [r[0] for r in gen_rows]
    except sqlite3.OperationalError:
        pass

    # Test summary with test framework detection
    from codegraph.indexing.test_framework import detect_test_framework
    test_framework, tests_present, test_evidence = detect_test_framework(con, repository)
    test_summary = {
        "framework": test_framework.value,
        "tests_present": tests_present,
        "evidence": test_evidence,
        "test_files_count": len(test_files),
        "test_files": test_files[:max_per_category],
    }

    # Route summary
    route_summary = {
        "total_routes": len(endpoints),
        "frameworks": frameworks,
        "methods": {
            m: len([e for e in endpoints if e.get("http_method") == m])
            for m in sorted({str(e.get("http_method", "")) for e in endpoints if e.get("http_method")})
        },
    }

    # Data / model summary
    data_model_summary = {
        "model_files": model_files[:max_per_category],
        "model_classes": [c["name"] for c in classes[:max_per_category]],
        "total_classes": len(classes),
    }

    # Module count by language
    lang_counts: dict[str, int] = {}
    for r in con.execute("SELECT language, count(*) AS n FROM files GROUP BY language"):
        lang_counts[r["language"]] = r["n"]

    total_symbols = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
    total_files = len(files)

    return {
        "source": "deterministic — parser-extracted from repository index",
        "repository": str(repository),
        "summary": {
            "total_files": total_files,
            "total_symbols": total_symbols,
            "total_endpoints": len(endpoints),
            "languages": lang_counts,
        },
        "languages": lang_counts,
        "frameworks": frameworks,
        "entry_points": entry_points[:max_per_category],
        "top_level_modules": modules,
        "dependency_summary": dependencies,
        "route_summary": route_summary,
        "test_summary": test_summary,
        "data_model_summary": data_model_summary,
        "external_services": sorted(set(integrations))[:max_per_category],
        "generated_artifact_summary": {
            "count": len(generated_files),
            "files": generated_files,
        },
        "endpoints": endpoints[:max_per_category],
        "services": service_files[:max_per_category],
        "repositories": repo_files[:max_per_category],
        "models": model_files[:max_per_category],
        "apis": api_files[:max_per_category],
        "tests": test_files[:max_per_category],
        "config": config_files[:max_per_category],
        "classes": classes[:max_per_category],
        "external_integrations": sorted(set(integrations))[:max_per_category],
        "architecture_nodes": nodes[:max_per_category * 2],
        "architecture_edges": edges[:max_per_category * 2],
        "note": (
            "Architecture is inferred from source declarations, routes, and import patterns. "
            "Framework endpoints are verified from AST route registrations."
        ),
    }
