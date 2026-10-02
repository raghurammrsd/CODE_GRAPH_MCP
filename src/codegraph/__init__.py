"""CodeGraph MCP: local, evidence-backed codebase intelligence."""

__version__ = "2.1.3"
from codegraph.errors import (
    CodeGraphError,
    ErrorCode,
    IndexStaleError,
    InvalidArgumentError,
    InvalidDepthError,
    InvalidModuleError,
    InvalidPathError,
    NotIndexedError,
    ParseFailureError,
    RepositoryNotInitializedError,
    SecurityError,
    SymbolAmbiguousError,
    SymbolNotFoundError,
    UnsupportedLanguageError,
)

__all__ = [
    "__version__",
    "CodeGraphError",
    "ErrorCode",
    "IndexStaleError",
    "InvalidArgumentError",
    "InvalidDepthError",
    "InvalidModuleError",
    "InvalidPathError",
    "NotIndexedError",
    "ParseFailureError",
    "RepositoryNotInitializedError",
    "SecurityError",
    "SymbolAmbiguousError",
    "SymbolNotFoundError",
    "UnsupportedLanguageError",
]
