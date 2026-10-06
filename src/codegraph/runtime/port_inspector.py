"""Localhost Port and Process Inspector for Multi-Service Architectures.

Deterministically detects, fingerprints, and attributes running localhost services:
1. Port <-> PID mapping via lsof / netstat / /proc.
2. Process CWD and command-line attribution to workspace packages.
3. Static port inference from docker-compose.yml, package.json, and .env.
4. Framework fingerprinting (Next.js, Vite, FastAPI, NestJS, Express, PostgreSQL, MongoDB).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceEndpoint:
    port: int
    host: str = "localhost"
    pid: int | None = None
    service_name: str = "unknown"
    framework: str = "unknown"
    process_cwd: str = ""
    relative_repo_path: str = ""
    command: str = ""
    is_live: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "host": self.host,
            "pid": self.pid,
            "service_name": self.service_name,
            "framework": self.framework,
            "process_cwd": self.process_cwd,
            "relative_repo_path": self.relative_repo_path,
            "command": self.command,
            "is_live": self.is_live,
            "attributes": dict(self.attributes),
        }


def _infer_framework_from_cmd(cmd: str) -> str:
    cmd_lower = cmd.lower()
    if "next" in cmd_lower:
        return "Next.js"
    if "vite" in cmd_lower:
        return "Vite"
    if "uvicorn" in cmd_lower or "fastapi" in cmd_lower:
        return "FastAPI"
    if "nest" in cmd_lower:
        return "NestJS"
    if "express" in cmd_lower or "node" in cmd_lower:
        return "Node/Express"
    if "postgres" in cmd_lower:
        return "PostgreSQL"
    if "mongod" in cmd_lower or "mongo" in cmd_lower:
        return "MongoDB"
    if "redis" in cmd_lower:
        return "Redis"
    if "celery" in cmd_lower:
        return "Celery"
    return "GenericService"


def _infer_service_name_from_path(repo_root: Path, cwd_path: Path, framework: str) -> str:
    try:
        rel = cwd_path.relative_to(repo_root)
        parts = rel.parts
        if parts:
            if parts[0] in ("apps", "packages", "services") and len(parts) > 1:
                return parts[1]
            return parts[-1]
    except Exception:
        pass
    return framework.lower().replace(".", "").replace("/", "-")


def discover_static_configured_ports(repo_root: Path) -> dict[int, ServiceEndpoint]:
    """Scan docker-compose, package.json, and .env files with in-memory TTL caching."""
    global _STATIC_PORT_CACHE
    root_key = str(repo_root)
    now = time.monotonic()
    if root_key in _STATIC_PORT_CACHE:
        last_t, cached_map = _STATIC_PORT_CACHE[root_key]
        if now - last_t < _PORT_CACHE_TTL_SEC:
            return cached_map

    results: dict[int, ServiceEndpoint] = {}

    # 1. docker-compose.yml / compose.yaml
    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"):
        compose_file = repo_root / compose_name
        if compose_file.exists():
            try:
                content = compose_file.read_text(encoding="utf-8", errors="replace")
                # match ports: - "3000:3000" or - 8000:8000
                for m in re.finditer(r"""['"]?(\d{2,5}):(\d{2,5})['"]?""", content):
                    host_port = int(m.group(1))
                    results[host_port] = ServiceEndpoint(
                        port=host_port,
                        service_name=f"docker-service-{host_port}",
                        framework="DockerContainer",
                        relative_repo_path=str(compose_file.relative_to(repo_root)),
                        is_live=False,
                    )
            except Exception:
                pass

    # 2. package.json scripts (e.g. -p 3000, PORT=4000)
    for pkg_file in repo_root.glob("**/package.json"):
        if "node_modules" in pkg_file.parts:
            continue
        try:
            content = pkg_file.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"""(?:PORT\s*=\s*|-p\s+|--port\s+)(\d{2,5})""", content):
                port_num = int(m.group(1))
                rel_dir = pkg_file.parent.relative_to(repo_root)
                s_name = pkg_file.parent.name or "web"
                results[port_num] = ServiceEndpoint(
                    port=port_num,
                    service_name=s_name,
                    framework="Node/Web",
                    relative_repo_path=str(rel_dir),
                    is_live=False,
                )
        except Exception:
            pass

    # 3. .env files
    for env_file in (repo_root / ".env", repo_root / ".env.development", repo_root / ".env.local"):
        if env_file.exists():
            try:
                content = env_file.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r"""^\s*(?:PORT|SERVER_PORT|API_PORT)\s*=\s*(\d{2,5})""", content, re.MULTILINE):
                    port_num = int(m.group(1))
                    results[port_num] = ServiceEndpoint(
                        port=port_num,
                        service_name="env-service",
                        framework="ConfiguredService",
                        relative_repo_path=str(env_file.relative_to(repo_root)),
                        is_live=False,
                    )
            except Exception:
                pass

    _STATIC_PORT_CACHE[root_key] = (now, results)
    return results


_PORT_CACHE: tuple[float, list[ServiceEndpoint]] = (0.0, [])
_STATIC_PORT_CACHE: dict[str, tuple[float, dict[int, ServiceEndpoint]]] = {}
_PORT_CACHE_TTL_SEC = 5.0


def discover_live_listening_ports(repo_root: Path | None = None) -> list[ServiceEndpoint]:
    """Inspect active OS listening ports on localhost with 5-second TTL cache (Zero-CPU idle)."""
    global _PORT_CACHE
    now = time.monotonic()
    last_time, cached_endpoints = _PORT_CACHE
    if now - last_time < _PORT_CACHE_TTL_SEC and cached_endpoints:
        return cached_endpoints

    endpoints: list[ServiceEndpoint] = []
    seen_ports: set[int] = set()

    lsof_bin = shutil.which("lsof")
    if lsof_bin:
        try:
            # lsof -iTCP -sTCP:LISTEN -n -P
            proc = subprocess.run(
                [lsof_bin, "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 9:
                        cmd = parts[0]
                        pid_str = parts[1]
                        addr_str = parts[8]
                        # address format: *:3000, 127.0.0.1:8000, [::1]:5432
                        m = re.search(r":(\d+)$", addr_str)
                        if m:
                            port = int(m.group(1))
                            if port in seen_ports:
                                continue
                            seen_ports.add(port)
                            pid = int(pid_str) if pid_str.isdigit() else None
                            cwd_str = ""
                            rel_repo = ""
                            if pid:
                                cwd_str = _get_process_cwd(pid)
                                if repo_root and cwd_str:
                                    try:
                                        rel_repo = str(Path(cwd_str).relative_to(repo_root))
                                    except Exception:
                                        rel_repo = ""
                            framework = _infer_framework_from_cmd(cmd)
                            svc_name = (
                                _infer_service_name_from_path(repo_root, Path(cwd_str), framework)
                                if repo_root and cwd_str
                                else cmd
                            )
                            endpoints.append(
                                ServiceEndpoint(
                                    port=port,
                                    pid=pid,
                                    service_name=svc_name,
                                    framework=framework,
                                    process_cwd=cwd_str,
                                    relative_repo_path=rel_repo,
                                    command=cmd,
                                    is_live=True,
                                )
                            )
        except Exception:
            pass

    _PORT_CACHE = (now, endpoints)
    return endpoints


def _get_process_cwd(pid: int) -> str:
    """Get process working directory securely across macOS and Linux."""
    # 1. Linux /proc/<pid>/cwd
    proc_cwd = Path(f"/proc/{pid}/cwd")
    if proc_cwd.exists():
        try:
            return str(proc_cwd.resolve())
        except Exception:
            pass

    # 2. macOS lsof -p <pid> | grep cwd
    lsof_bin = shutil.which("lsof")
    if lsof_bin:
        try:
            proc = subprocess.run(
                [lsof_bin, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("n"):
                    return line[1:].strip()
        except Exception:
            pass
    return ""


def resolve_port_to_service(
    port: int,
    repo_root: Path,
    live_endpoints: list[ServiceEndpoint] | None = None,
) -> ServiceEndpoint:
    """Identify the exact service, package, and framework for a given localhost port."""
    if live_endpoints is None:
        live_endpoints = discover_live_listening_ports(repo_root)

    for ep in live_endpoints:
        if ep.port == port:
            return ep

    static_map = discover_static_configured_ports(repo_root)
    if port in static_map:
        return static_map[port]

    # Common standard ports fallback
    standard_defaults: dict[int, tuple[str, str]] = {
        3000: ("frontend", "Next.js/React"),
        5173: ("frontend", "Vite"),
        8000: ("backend-api", "FastAPI/Django"),
        4000: ("backend-api", "NestJS/Express"),
        5000: ("backend-api", "Flask/Express"),
        5432: ("database", "PostgreSQL"),
        27017: ("database", "MongoDB"),
        6379: ("cache", "Redis"),
        3306: ("database", "MySQL"),
    }
    if port in standard_defaults:
        s_name, fw = standard_defaults[port]
        return ServiceEndpoint(
            port=port,
            service_name=s_name,
            framework=fw,
            is_live=False,
        )

    return ServiceEndpoint(
        port=port,
        service_name=f"service-{port}",
        framework="Unknown",
        is_live=False,
    )
