"""Repository-scoped refactor transaction manager and atomic rollback engine."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

from codegraph.errors import SecurityError
from codegraph.refactor.models import (
    RefactorPlan,
    RefactorResult,
    RefactorRisk,
    RefactorStatus,
)
from codegraph.security.paths import is_sensitive_path, safe_path


class RefactorLockError(Exception):
    """Raised when repository refactoring lock cannot be acquired."""


class RefactorLock:
    """Repository-scoped file lock for atomic refactor operations."""

    def __init__(self, repository: Path, timeout_seconds: float = 5.0) -> None:
        self.repository = repository
        self.lock_dir = repository / ".codegraph"
        self.lock_file = self.lock_dir / "refactor.lock"
        self.timeout_seconds = timeout_seconds
        self._fd: int | None = None

    def __enter__(self) -> RefactorLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    def acquire(self) -> None:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                if fcntl is not None:
                    self._fd = os.open(
                        str(self.lock_file),
                        os.O_RDWR | os.O_CREAT | os.O_TRUNC,
                        0o644,
                    )
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    self._fd = os.open(
                        str(self.lock_file),
                        os.O_RDWR | os.O_CREAT | os.O_EXCL,
                        0o644,
                    )
                # Write current PID into lock file
                os.write(self._fd, f"{os.getpid()}:{datetime.now(UTC).isoformat()}".encode())
                return
            except (OSError, BlockingIOError) as err:
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None
                if time.time() - start >= self.timeout_seconds:
                    raise RefactorLockError(
                        f"CONCURRENT_REFACTOR_IN_PROGRESS: Could not acquire refactor lock for {self.repository} "
                        f"within {self.timeout_seconds}s."
                    ) from err
                time.sleep(0.05)

    def release(self) -> None:
        if self._fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except OSError:
                pass


def compute_sha256(content: str | bytes) -> str:
    """Compute deterministic SHA-256 hash."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def get_manifests_dir(repository: Path) -> Path:
    """Get or create the transaction manifests storage directory."""
    manifests_dir = repository / ".codegraph" / "refactor_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    return manifests_dir


def write_manifest(repository: Path, manifest_data: dict[str, Any]) -> Path:
    """Write a persistent transaction manifest."""
    manifests_dir = get_manifests_dir(repository)
    manifest_path = manifests_dir / f"{manifest_data['transaction_id']}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    return manifest_path


def read_manifest(repository: Path, transaction_id: str) -> dict[str, Any] | None:
    """Read a transaction manifest by ID."""
    manifests_dir = get_manifests_dir(repository)
    manifest_path = manifests_dir / f"{transaction_id}.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return None
    except Exception:
        return None


def commit_refactor_transaction(
    repository: Path,
    plan: RefactorPlan,
    modified_buffers: dict[str, str],
) -> RefactorResult:
    """Atomically commit all modified file buffers to disk with full rollback manifest.
    
    Invariants:
    1. Repository-scoped lock acquired.
    2. All original file hashes re-validated against plan.
    3. Safe path and boundary validation enforced.
    4. Modified contents written to sibling temporary files.
    5. Atomic replacement using os.replace().
    6. Rollback manifest persisted.
    """
    repo_root = repository.resolve()
    temp_files_created: list[Path] = []
    original_contents: dict[str, str] = {}
    replacement_hashes: dict[str, str] = {}

    try:
        with RefactorLock(repo_root):
            # 1. Precondition check: verify file existence, safety, and unchanged hashes
            for rel_path in plan.files:
                if is_sensitive_path(rel_path):
                    return RefactorResult(
                        status=RefactorStatus.BLOCKED,
                        target_symbol=plan.target_symbol,
                        new_name=plan.new_name,
                        risk=RefactorRisk.HIGH,
                        errors=[f"SENSITIVE_FILE_ACCESS_DENIED: File '{rel_path}' is sensitive."],
                    )
                
                try:
                    abs_path = safe_path(repo_root, rel_path)
                except SecurityError as sec_err:
                    return RefactorResult(
                        status=RefactorStatus.BLOCKED,
                        target_symbol=plan.target_symbol,
                        new_name=plan.new_name,
                        risk=RefactorRisk.HIGH,
                        errors=[f"SECURITY_ERROR: {sec_err}"],
                    )

                if not abs_path.exists() or not abs_path.is_file():
                    return RefactorResult(
                        status=RefactorStatus.ERROR,
                        target_symbol=plan.target_symbol,
                        new_name=plan.new_name,
                        risk=RefactorRisk.HIGH,
                        errors=[f"FILE_NOT_FOUND: Target file '{rel_path}' does not exist on disk."],
                    )

                current_bytes = abs_path.read_bytes()
                current_hash = hashlib.sha256(current_bytes).hexdigest()
                expected_hash = plan.original_file_hashes.get(rel_path)

                if expected_hash and current_hash != expected_hash:
                    return RefactorResult(
                        status=RefactorStatus.ERROR,
                        target_symbol=plan.target_symbol,
                        new_name=plan.new_name,
                        risk=RefactorRisk.HIGH,
                        errors=[
                            f"FILE_CHANGED_SINCE_PLAN: File '{rel_path}' has been modified externally since plan generation. Please re-plan."
                        ],
                    )

                try:
                    original_contents[rel_path] = current_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    original_contents[rel_path] = current_bytes.decode("latin1")

            # 2. Stage all modifications to sibling temporary files
            for rel_path in plan.files:
                abs_path = safe_path(repo_root, rel_path)
                parent_dir = abs_path.parent
                temp_file = parent_dir / f".tmp_cg_refactor_{plan.transaction_id}_{abs_path.name}"
                temp_files_created.append(temp_file)

                new_text = modified_buffers[rel_path]
                replacement_hashes[rel_path] = compute_sha256(new_text)

                # Write content to sibling temp file preserving exact line endings
                temp_file.write_bytes(new_text.encode("utf-8"))

                # Preserve original permissions
                try:
                    shutil.copymode(abs_path, temp_file)
                except OSError:
                    pass

            # 3. All temp files written successfully — atomically replace original files
            for rel_path in plan.files:
                abs_path = safe_path(repo_root, rel_path)
                temp_file = abs_path.parent / f".tmp_cg_refactor_{plan.transaction_id}_{abs_path.name}"
                os.replace(temp_file, abs_path)

            # 4. Save transaction manifest
            manifest = {
                "transaction_id": plan.transaction_id,
                "target_symbol": plan.target_symbol,
                "new_name": plan.new_name,
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "APPLIED",
                "files": plan.files,
                "original_hashes": plan.original_file_hashes,
                "replacement_hashes": replacement_hashes,
                "original_contents": original_contents,
                "spans_count": len(plan.spans),
            }
            write_manifest(repo_root, manifest)

            return RefactorResult(
                status=RefactorStatus.APPLIED,
                target_symbol=plan.target_symbol,
                new_name=plan.new_name,
                risk=plan.risk,
                uncertainty_reasons=plan.uncertainty_reasons,
                files_changed=len(plan.files),
                symbols_changed=1,
                spans_count=len(plan.spans),
                tests_affected=plan.affected_tests,
                routes_affected=plan.affected_routes,
                db_affected=plan.affected_db_relationships,
                rollback_id=plan.transaction_id,
            )

    except RefactorLockError as lock_err:
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=plan.target_symbol,
            new_name=plan.new_name,
            risk=RefactorRisk.HIGH,
            errors=[str(lock_err)],
        )
    except Exception as exc:
        # Clean up any leftover temp files
        for tmp in temp_files_created:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return RefactorResult(
            status=RefactorStatus.ERROR,
            target_symbol=plan.target_symbol,
            new_name=plan.new_name,
            risk=RefactorRisk.HIGH,
            errors=[f"TRANSACTION_FAILED: {exc}"],
        )


def rollback_refactor(repository: Path, transaction_id: str) -> RefactorResult:
    """Atomically rollback an applied refactoring transaction.
    
    Invariants:
    1. Repository-scoped lock acquired.
    2. Manifest must exist and be in APPLIED status.
    3. Current file hashes must match expected post-refactor hashes.
       If any file has changed externally, rollback is BLOCKED.
    4. Restores original contents atomically using os.replace().
    """
    repo_root = repository.resolve()

    manifest = read_manifest(repo_root, transaction_id)
    if not manifest:
        return RefactorResult(
            status=RefactorStatus.ERROR,
            target_symbol="",
            new_name="",
            risk=RefactorRisk.HIGH,
            errors=[f"ROLLBACK_MANIFEST_NOT_FOUND: No transaction manifest found for '{transaction_id}'."],
        )

    if manifest.get("status") == "ROLLED_BACK":
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=manifest.get("target_symbol", ""),
            new_name=manifest.get("new_name", ""),
            risk=RefactorRisk.LOW,
            errors=[f"TRANSACTION_ALREADY_ROLLED_BACK: Transaction '{transaction_id}' was already rolled back."],
        )

    files = manifest.get("files", [])
    replacement_hashes = manifest.get("replacement_hashes", {})
    original_contents = manifest.get("original_contents", {})

    temp_files_created: list[Path] = []

    try:
        with RefactorLock(repo_root):
            # 1. Verify that current file hashes match expected replacement hashes
            for rel_path in files:
                abs_path = safe_path(repo_root, rel_path)
                if not abs_path.exists():
                    return RefactorResult(
                        status=RefactorStatus.ERROR,
                        target_symbol=manifest.get("target_symbol", ""),
                        new_name=manifest.get("new_name", ""),
                        risk=RefactorRisk.HIGH,
                        errors=[f"FILE_NOT_FOUND_FOR_ROLLBACK: Target file '{rel_path}' no longer exists on disk."],
                    )

                current_hash = compute_sha256(abs_path.read_bytes())
                expected_hash = replacement_hashes.get(rel_path)

                if expected_hash and current_hash != expected_hash:
                    return RefactorResult(
                        status=RefactorStatus.BLOCKED,
                        target_symbol=manifest.get("target_symbol", ""),
                        new_name=manifest.get("new_name", ""),
                        risk=RefactorRisk.HIGH,
                        errors=[
                            f"ROLLBACK_BLOCKED_EXTERNAL_MODIFICATION: File '{rel_path}' was modified externally after the refactor was applied. "
                            f"Rollback cannot safely overwrite subsequent changes."
                        ],
                    )

            # 2. Stage original contents to sibling temporary files
            for rel_path in files:
                abs_path = safe_path(repo_root, rel_path)
                temp_file = abs_path.parent / f".tmp_cg_rollback_{transaction_id}_{abs_path.name}"
                temp_files_created.append(temp_file)

                orig_text = original_contents.get(rel_path, "")
                temp_file.write_bytes(orig_text.encode("utf-8"))
                try:
                    shutil.copymode(abs_path, temp_file)
                except OSError:
                    pass

            # 3. Atomically restore original files
            for rel_path in files:
                abs_path = safe_path(repo_root, rel_path)
                temp_file = abs_path.parent / f".tmp_cg_rollback_{transaction_id}_{abs_path.name}"
                os.replace(temp_file, abs_path)

            # 4. Mark manifest as ROLLED_BACK
            manifest["status"] = "ROLLED_BACK"
            manifest["rolled_back_at"] = datetime.now(UTC).isoformat()
            write_manifest(repo_root, manifest)

            return RefactorResult(
                status=RefactorStatus.ROLLED_BACK,
                target_symbol=manifest.get("target_symbol", ""),
                new_name=manifest.get("new_name", ""),
                risk=RefactorRisk.LOW,
                files_changed=len(files),
                symbols_changed=1,
                spans_count=manifest.get("spans_count", 0),
                rollback_id=transaction_id,
            )

    except RefactorLockError as lock_err:
        return RefactorResult(
            status=RefactorStatus.BLOCKED,
            target_symbol=manifest.get("target_symbol", ""),
            new_name=manifest.get("new_name", ""),
            risk=RefactorRisk.HIGH,
            errors=[str(lock_err)],
        )
    except Exception as exc:
        for tmp in temp_files_created:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return RefactorResult(
            status=RefactorStatus.ERROR,
            target_symbol=manifest.get("target_symbol", ""),
            new_name=manifest.get("new_name", ""),
            risk=RefactorRisk.HIGH,
            errors=[f"ROLLBACK_FAILED: {exc}"],
        )
