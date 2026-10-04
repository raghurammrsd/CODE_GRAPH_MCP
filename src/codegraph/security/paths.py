from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from urllib.parse import unquote

from codegraph.errors import ErrorCode, SecurityError

DEFAULT_MAX_READ_BYTES = 256_000

DEFAULT_SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "id_dsa",
    "id_dsa.*",
    "kubeconfig",
    "*kubeconfig*",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git/config",
    "*/.git/config",
    ".git/credentials",
    "*/.git/credentials",
    ".git-credentials",
    "credentials",
    "credentials*",
    "*.credentials",
    "secrets.*",
    "*secret*.json",
    "*secret*.yaml",
    "*secret*.yml",
    "service-account*",
    "service_account*",
    ".aws/*",
    "*/.aws/*",
    ".ssh/*",
    "*/.ssh/*",
    ".gnupg/*",
    "*/.gnupg/*",
    ".kube/*",
    "*/.kube/*",
    ".docker/config.json",
    "*/.docker/config.json",
    "*docker*credential*",
    "docker-credentials*",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
)

_SENSITIVE_DIRS: frozenset[str] = frozenset({
    ".aws",
    ".ssh",
    ".gnupg",
    ".kube",
})

_DEFAULT_SENSITIVE_REGEX = re.compile(
    "|".join(f"(?:{fnmatch.translate(p.lower())})" for p in DEFAULT_SENSITIVE_PATTERNS)
)


def is_sensitive_path(
    relative_path: str | Path,
    patterns: tuple[str, ...] = DEFAULT_SENSITIVE_PATTERNS,
) -> bool:
    """Authoritative check for sensitive credentials, private keys, and secret configs."""
    raw = str(relative_path).replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    p_obj = Path(raw)
    value = p_obj.as_posix()
    value_lower = value.lower()
    name = p_obj.name
    name_lower = name.lower()

    parts_lower = {part.lower() for part in p_obj.parts}
    if parts_lower & _SENSITIVE_DIRS:
        return True

    if value_lower in (".git/config", ".git/credentials") or value_lower.endswith(("/.git/config", "/.git/credentials")):
        return True
    if value_lower == ".docker/config.json" or value_lower.endswith("/.docker/config.json"):
        return True

    if patterns is DEFAULT_SENSITIVE_PATTERNS or patterns == DEFAULT_SENSITIVE_PATTERNS:
        return bool(
            _DEFAULT_SENSITIVE_REGEX.match(value_lower)
            or _DEFAULT_SENSITIVE_REGEX.match(name_lower)
        )

    return any(
        fnmatch.fnmatch(value, p)
        or fnmatch.fnmatch(value_lower, p.lower())
        or fnmatch.fnmatch(name, p)
        or fnmatch.fnmatch(name_lower, p.lower())
        for p in patterns
    )


def is_sensitive(
    relative_path: str | Path,
    patterns: tuple[str, ...] = DEFAULT_SENSITIVE_PATTERNS,
) -> bool:
    """Alias for `is_sensitive_path` maintained for backward compatibility."""
    return is_sensitive_path(relative_path, patterns=patterns)


def safe_path(repository: Path, requested: str | Path) -> Path:
    """Resolve a repo-relative path and reject traversal and symlink escapes."""
    root = repository.resolve(strict=True)
    raw_value = unquote(str(requested))
    if "\x00" in raw_value:
        raise SecurityError("null bytes are not allowed in paths")
    raw = Path(raw_value)
    if raw.is_absolute():
        raise SecurityError("absolute paths are not allowed")
    candidate = (root / raw).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SecurityError("path escapes the configured repository") from exc
    return candidate


def safe_read_text(
    repository: Path,
    requested: str | Path,
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> tuple[Path, str, str]:
    """Safely validate and read a repository file with path-traversal, sensitive-path,
    binary-file, and size-cap enforcement BEFORE reading full contents into memory.

    Returns:
        (resolved_path, relative_posix_path, text_content)
    """
    resolved = safe_path(repository, requested)
    root = repository.resolve(strict=True)
    relative = resolved.relative_to(root)
    rel_posix = relative.as_posix()

    if is_sensitive_path(relative) or is_sensitive_path( str(requested) ):
        raise SecurityError(
            f"sensitive files cannot be read: '{rel_posix}'",
            code=ErrorCode.SENSITIVE_FILE_ACCESS_DENIED,
        )

    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"File does not exist: '{rel_posix}'")

    file_size = resolved.stat().st_size
    if file_size > max_read_bytes:
        raise SecurityError(
            f"File '{rel_posix}' size ({file_size} bytes) exceeds max_read_bytes limit ({max_read_bytes} bytes).",
            code=ErrorCode.FILE_TOO_LARGE,
        )

    with resolved.open("rb") as fh:
        raw_bytes = fh.read(max_read_bytes + 1)

    if len(raw_bytes) > max_read_bytes:
        raise SecurityError(
            f"File '{rel_posix}' exceeds max_read_bytes limit ({max_read_bytes} bytes).",
            code=ErrorCode.FILE_TOO_LARGE,
        )

    if b"\x00" in raw_bytes[:8192]:
        raise SecurityError(
            f"Binary file '{rel_posix}' cannot be read as text.",
            code=ErrorCode.BINARY_FILE_NOT_READABLE,
        )

    from .redaction import redact_secrets

    decoded = raw_bytes.decode("utf-8", errors="replace")
    return resolved, rel_posix, redact_secrets(decoded)
