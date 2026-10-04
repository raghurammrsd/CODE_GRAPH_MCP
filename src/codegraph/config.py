from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Runtime settings. Environment values deliberately never include API keys."""

    repository: Path | None = None
    db_path: Path | None = None
    max_file_size: int = Field(default=1_000_000, ge=1)
    max_read_bytes: int = Field(default=256_000, ge=1024)
    max_results: int = Field(default=10, ge=1, le=100)
    max_context: int = Field(default=20_000, ge=100)
    max_tool_calls: int = Field(default=12, ge=1)
    exclude: tuple[str, ...] = ()
    resource_profile: str = "BALANCED"
    max_interactive_workers: int = Field(default=2, ge=1)
    max_background_workers: int = Field(default=1, ge=0)
    max_memory_mb: int = Field(default=1024, ge=128)
    max_graph_nodes: int = Field(default=300, ge=10)
    max_graph_edges: int = Field(default=1200, ge=10)
    max_git_commits: int = Field(default=15, ge=1)
    background_indexing: bool = True
    debounce_ms: int = Field(default=500, ge=50)

    @classmethod
    def from_env(cls) -> Settings:
        repo = os.getenv("CODEGRAPH_REPOSITORY")
        db = os.getenv("CODEGRAPH_DB_PATH")
        return cls(
            repository=Path(repo) if repo else None,
            db_path=Path(db) if db else None,
            max_file_size=int(os.getenv("CODEGRAPH_MAX_FILE_SIZE", "1000000")),
            max_read_bytes=int(os.getenv("CODEGRAPH_MAX_READ_BYTES", "256000")),
            max_context=int(os.getenv("CODEGRAPH_MAX_CONTEXT", "20000")),
            max_tool_calls=int(os.getenv("CODEGRAPH_MAX_TOOL_CALLS", "12")),
            resource_profile=os.getenv("CODEGRAPH_RESOURCE_PROFILE", "BALANCED"),
            max_memory_mb=int(os.getenv("CODEGRAPH_MAX_MEMORY_MB", "1024")),
            background_indexing=os.getenv("CODEGRAPH_BACKGROUND_INDEXING", "true").lower() in ("true", "1"),
            debounce_ms=int(os.getenv("CODEGRAPH_DEBOUNCE_MS", "500")),
        )
