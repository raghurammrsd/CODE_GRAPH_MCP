from __future__ import annotations

import fnmatch
from pathlib import Path
from urllib.parse import unquote

from codegraph.errors import SecurityError

DEFAULT_SENSITIVE_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa", "credentials.*", "secrets.*",
    "service-account*.json", ".aws/*", ".ssh/*",
)


def is_sensitive(relative_path: Path, patterns: tuple[str, ...] = DEFAULT_SENSITIVE_PATTERNS) -> bool:
    value = relative_path.as_posix()
    name = relative_path.name
    return any(fnmatch.fnmatch(value, p) or fnmatch.fnmatch(name, p) for p in patterns)


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
