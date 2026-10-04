"""Centralized error models, stable error codes, and structured exception handling for CodeGraph MCP.

Principle:
    Expected operational failures must produce machine-readable, deterministic error contracts
    with actionable next-step recovery instructions for AI agents, avoiding raw tracebacks.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable, centralized machine-readable error codes for CodeGraph MCP."""
    INDEX_NOT_FOUND = "INDEX_NOT_FOUND"
    INDEX_STALE = "INDEX_STALE"
    REPOSITORY_NOT_INITIALIZED = "REPOSITORY_NOT_INITIALIZED"
    INVALID_PATH = "INVALID_PATH"
    PATH_OUTSIDE_REPOSITORY = "PATH_OUTSIDE_REPOSITORY"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    SYMBOL_AMBIGUOUS = "SYMBOL_AMBIGUOUS"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    PARSE_FAILURE = "PARSE_FAILURE"
    INVALID_DEPTH = "INVALID_DEPTH"
    INVALID_MODULE = "INVALID_MODULE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    EMPTY_SYMBOL_NAME = "EMPTY_SYMBOL_NAME"
    SENSITIVE_FILE_ACCESS_DENIED = "SENSITIVE_FILE_ACCESS_DENIED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    BINARY_FILE_NOT_READABLE = "BINARY_FILE_NOT_READABLE"
    UNSUPPORTED_AGENT = "UNSUPPORTED_AGENT"
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"
    MODIFIED_FILE_PROTECTED = "MODIFIED_FILE_PROTECTED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class CodeGraphError(Exception):
    """Base error that is safe to display to users and AI agents."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | str = ErrorCode.INTERNAL_ERROR,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code.value if isinstance(code, ErrorCode) else str(code)
        self.next_action = next_action

    def to_dict(self) -> dict[str, Any]:
        """Convert error to machine-readable dictionary representation."""
        data: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.next_action:
            data["next_action"] = self.next_action
        return data

    def to_response(self, status: str = "error") -> dict[str, Any]:
        """Wrap error inside canonical machine-readable response envelope."""
        return {
            "status": status,
            "error": self.to_dict(),
        }


class SecurityError(CodeGraphError):
    """A request attempted to access something outside the repository or a protected file."""

    def __init__(
        self,
        message: str = "Access denied: path is outside repository or sensitive.",
        code: ErrorCode | str = ErrorCode.PATH_OUTSIDE_REPOSITORY,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        if next_action is None:
            next_action = {
                "command": "codegraph status",
                "reason": "Ensure all queried paths reside within the repository root.",
            }
        super().__init__(message, code=code, next_action=next_action)


class NotIndexedError(CodeGraphError):
    """The repository has no usable CodeGraph index."""

    def __init__(
        self,
        message: str = "No CodeGraph index exists for this repository.",
        code: ErrorCode | str = ErrorCode.INDEX_NOT_FOUND,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        if next_action is None:
            next_action = {
                "command": "codegraph init",
                "reason": "Initialize the repository before querying it.",
            }
        super().__init__(message, code=code, next_action=next_action)


class IndexStaleError(CodeGraphError):
    """The repository changed after the current index was generated."""

    def __init__(
        self,
        message: str = "The repository changed after the current index was generated.",
        code: ErrorCode | str = ErrorCode.INDEX_STALE,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        if next_action is None:
            next_action = {
                "command": "codegraph index",
                "reason": "Re-index the repository to update stale evidence.",
            }
        super().__init__(message, code=code, next_action=next_action)


class RepositoryNotInitializedError(CodeGraphError):
    """The repository has not been initialized with CodeGraph configuration."""

    def __init__(
        self,
        message: str = "Repository is not initialized for CodeGraph.",
        code: ErrorCode | str = ErrorCode.REPOSITORY_NOT_INITIALIZED,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        if next_action is None:
            next_action = {
                "command": "codegraph init",
                "reason": "Initialize the repository with CodeGraph schema and metadata.",
            }
        super().__init__(message, code=code, next_action=next_action)


class InvalidPathError(CodeGraphError):
    """A file or directory path is invalid, malformed, or does not exist."""

    def __init__(
        self,
        path: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Invalid or non-existent path: {path}"
        if next_action is None:
            next_action = {
                "command": "codegraph status",
                "reason": "Check repository files and paths.",
            }
        super().__init__(msg, code=ErrorCode.INVALID_PATH, next_action=next_action)


class SymbolNotFoundError(CodeGraphError):
    """A requested symbol cannot be found in the repository index."""

    def __init__(
        self,
        symbol: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"No matching symbol was found for '{symbol}'."
        if next_action is None:
            next_action = {
                "command": f"codegraph search {symbol}",
                "reason": "Search with a broader query term.",
            }
        super().__init__(msg, code=ErrorCode.SYMBOL_NOT_FOUND, next_action=next_action)


class SymbolAmbiguousError(CodeGraphError):
    """Multiple symbols match a short or un-qualified name."""

    def __init__(
        self,
        symbol: str,
        candidates: list[dict[str, Any]],
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Multiple symbols match '{symbol}'. Provide a qualified name or canonical ID."
        if next_action is None:
            next_action = {
                "command": "codegraph resolve <canonical_id>",
                "reason": "Select an explicit canonical ID from candidates.",
            }
        super().__init__(msg, code=ErrorCode.SYMBOL_AMBIGUOUS, next_action=next_action)
        self.candidates = candidates


class InvalidArgumentError(CodeGraphError):
    """An interrogation or CLI argument was missing, empty, or malformed."""

    def __init__(
        self,
        argument: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Invalid or empty argument: {argument}"
        if next_action is None:
            next_action = {
                "command": "codegraph --help",
                "reason": "Inspect accepted command parameters and arguments.",
            }
        super().__init__(msg, code=ErrorCode.INVALID_ARGUMENT, next_action=next_action)


class UnsupportedLanguageError(CodeGraphError):
    """The requested file language is not supported by CodeGraph AST parsers."""

    def __init__(
        self,
        language_or_ext: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Unsupported source language or extension: {language_or_ext}"
        if next_action is None:
            next_action = {
                "command": "codegraph doctor",
                "reason": "Check supported languages (Python, TypeScript, JavaScript).",
            }
        super().__init__(msg, code=ErrorCode.UNSUPPORTED_LANGUAGE, next_action=next_action)


class ParseFailureError(CodeGraphError):
    """A source file failed AST parsing due to syntax errors."""

    def __init__(
        self,
        file_path: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Failed to parse source file due to syntax error: {file_path}"
        if next_action is None:
            next_action = {
                "command": f"python3 -m py_compile {file_path}",
                "reason": "Fix syntax errors in the source file and re-index.",
            }
        super().__init__(msg, code=ErrorCode.PARSE_FAILURE, next_action=next_action)


class InvalidDepthError(CodeGraphError):
    """Graph traversal depth argument is out of bounds (allowed range: 1..5)."""

    def __init__(
        self,
        depth: int,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Invalid graph traversal depth {depth}; allowed range is 1..5."
        if next_action is None:
            next_action = {
                "command": "codegraph trace --depth 2 <symbol>",
                "reason": "Specify a traversal depth between 1 and 5.",
            }
        super().__init__(msg, code=ErrorCode.INVALID_DEPTH, next_action=next_action)


class InvalidModuleError(CodeGraphError):
    """The specified module does not exist or has not been indexed."""

    def __init__(
        self,
        module: str,
        message: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> None:
        msg = message or f"Unknown or unindexed module: '{module}'."
        if next_action is None:
            next_action = {
                "command": "codegraph architecture",
                "reason": "Inspect indexed repository modules.",
            }
        super().__init__(msg, code=ErrorCode.INVALID_MODULE, next_action=next_action)
