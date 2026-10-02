"""Benchmark suite evaluating real-world corpus tasks.

Measures planning, retrieval, ranking, and compilation performance across:
1. Authentication service explanation
2. Trace HTTP route (POST /api/v1/auth/login)
3. Recent changes & git blast radius
4. Impact analysis for core symbol
5. Related test finding
6. High-level architecture compilation
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.graph import analyze_impact, find_related_tests
from codegraph.indexing import Indexer


def _create_benchmark_repo(root: Path) -> None:
    """Create a realistic multi-tier application repository."""
    # 1. Routes
    (root / "routes.py").write_text(
        """from auth_service import AuthService
from database import get_db

# @app.post("/api/v1/auth/login")
def login_endpoint(email: str, password_hash: str):
    db = get_db()
    service = AuthService(db)
    return service.authenticate(email, password_hash)

# @app.get("/api/v1/users/me")
def current_user_endpoint(token: str):
    service = AuthService(get_db())
    return service.verify_session(token)
""",
        encoding="utf-8",
    )

    # 2. Service
    (root / "auth_service.py").write_text(
        """from database import DatabaseSession
from models import User

class AuthService:
    def __init__(self, db: DatabaseSession):
        self.db = db

    def authenticate(self, email: str, password_hash: str) -> bool:
        user = self.db.find_user_by_email(email)
        if not user:
            return False
        return user.verify_password(password_hash)

    def verify_session(self, token: str) -> User | None:
        return self.db.find_user_by_token(token)
""",
        encoding="utf-8",
    )

    # 3. Models
    (root / "models.py").write_text(
        """class User:
    def __init__(self, user_id: str, email: str, secret: str):
        self.user_id = user_id
        self.email = email
        self.secret = secret

    def verify_password(self, password_hash: str) -> bool:
        return self.secret == password_hash
""",
        encoding="utf-8",
    )

    # 4. Database
    (root / "database.py").write_text(
        """from models import User

class DatabaseSession:
    def __init__(self):
        self._store = {}

    def find_user_by_email(self, email: str) -> User | None:
        return self._store.get(email)

    def find_user_by_token(self, token: str) -> User | None:
        return None

def get_db() -> DatabaseSession:
    return DatabaseSession()
""",
        encoding="utf-8",
    )

    # 5. Tests
    (root / "test_auth.py").write_text(
        """from auth_service import AuthService
from database import DatabaseSession

def test_auth_success():
    db = DatabaseSession()
    service = AuthService(db)
    assert service is not None

def test_auth_failure():
    db = DatabaseSession()
    service = AuthService(db)
    assert service.authenticate("test@example.com", "wrong") is False
""",
        encoding="utf-8",
    )


def run_task_benchmarks() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _create_benchmark_repo(repo)

        t_index_start = time.perf_counter()
        indexer = Indexer(repo)
        indexer.index()
        index_ms = (time.perf_counter() - t_index_start) * 1000.0

        results: dict[str, Any] = {
            "indexing_ms": round(index_ms, 2),
            "tasks": {},
        }

        with indexer.session() as con:
            # Task 1: Auth Explanation
            t0 = time.perf_counter()
            packet_auth = get_context(
                con=con,
                repository=repo,
                task="Explain AuthService authentication and password verification",
                intent="explain",
                max_tokens=4000,
                explain=True,
            )
            auth_ms = (time.perf_counter() - t0) * 1000.0
            results["tasks"]["auth_explain"] = {
                "latency_ms": round(auth_ms, 2),
                "selected_tokens": packet_auth.selected_token_estimate,
                "candidate_tokens": packet_auth.candidate_token_estimate,
                "reduction_pct": packet_auth.context_reduction_pct,
                "symbols_count": len(packet_auth.symbols),
            }

            # Task 2: Trace Endpoint
            t0 = time.perf_counter()
            packet_trace = get_context(
                con=con,
                repository=repo,
                task="Trace POST /api/v1/auth/login flow to database lookup",
                intent="trace",
                max_tokens=6000,
                explain=True,
            )
            trace_ms = (time.perf_counter() - t0) * 1000.0
            results["tasks"]["trace_endpoint"] = {
                "latency_ms": round(trace_ms, 2),
                "selected_tokens": packet_trace.selected_token_estimate,
                "relationships_count": len(packet_trace.relationships),
                "files_count": len(packet_trace.selected_files),
            }

            # Task 3: Impact Analysis
            t0 = time.perf_counter()
            impact = analyze_impact(con, "authenticate", max_depth=3)
            impact_ms = (time.perf_counter() - t0) * 1000.0
            affected_syms = impact.get("affected_symbols", [])
            affected_fls = impact.get("affected_files", [])
            results["tasks"]["impact_analysis"] = {
                "latency_ms": round(impact_ms, 2),
                "affected_symbols_count": len(affected_syms) if isinstance(affected_syms, list) else 0,
                "affected_files_count": len(affected_fls) if isinstance(affected_fls, list) else 0,
            }

            # Task 4: Related Test Finding
            t0 = time.perf_counter()
            tests = find_related_tests(con, "AuthService", max_results=10)
            tests_ms = (time.perf_counter() - t0) * 1000.0
            results["tasks"]["related_tests"] = {
                "latency_ms": round(tests_ms, 2),
                "tests_found": len(tests),
            }

            # Task 5: Architecture Context
            t0 = time.perf_counter()
            packet_arch = get_context(
                con=con,
                repository=repo,
                task="High-level architecture and subsystem boundaries",
                intent="architecture",
                mode="DEEP",
                max_tokens=10000,
            )
            arch_ms = (time.perf_counter() - t0) * 1000.0
            results["tasks"]["architecture"] = {
                "latency_ms": round(arch_ms, 2),
                "architecture_elements": len(packet_arch.architecture),
                "selected_tokens": packet_arch.selected_token_estimate,
            }

        return results


if __name__ == "__main__":
    import json

    res = run_task_benchmarks()
    print(json.dumps(res, indent=2))
