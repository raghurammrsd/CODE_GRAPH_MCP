"""Deterministic 16-phase indexing telemetry, memory tracking, and progress formatting (v2.1.7)."""
from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

INDEXING_PHASES: tuple[tuple[str, str], ...] = (
    ("repository_scan", "Repository Scan"),
    ("file_classification", "File Classification"),
    ("file_reading", "File Reading"),
    ("ast_parsing", "AST Parsing"),
    ("symbol_extraction", "Symbol Extraction"),
    ("import_extraction", "Import Extraction"),
    ("framework_analysis", "Framework Analysis"),
    ("database_analysis", "Database Analysis"),
    ("graph_edge_creation", "Graph Edge Creation"),
    ("symbol_resolution", "Symbol Resolution"),
    ("relationship_resolution", "Relationship Resolution"),
    ("ranking_index_building", "Ranking/Index Building"),
    ("sqlite_writes", "SQLite Writes"),
    ("fts_updates", "FTS Updates"),
    ("post_processing", "Post-Processing"),
    ("final_commit_checkpoint", "Final Commit/Checkpoint"),
)

PHASE_LABELS: dict[str, str] = dict(INDEXING_PHASES)


def get_process_rss_mb() -> float:
    """Return current/peak RSS in megabytes safely across macOS, Linux, and Windows."""
    try:
        import resource as res_mod

        if res_mod is None:
            return 0.0
        usage = res_mod.getrusage(res_mod.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return round(usage / (1024.0 * 1024.0), 2)
        return round(usage / 1024.0, 2)
    except Exception:
        return 0.0


def format_duration_concise(seconds: float) -> str:
    """Format elapsed seconds as e.g. '4m 12s' or '1.42s'."""
    if seconds >= 60.0:
        mins = int(seconds // 60)
        secs = int(round(seconds % 60))
        return f"{mins}m {secs:02d}s"
    return f"{seconds:.2f}s"


def format_progress_block(
    phase: str,
    completed_files: int,
    total_files: int,
    elapsed_seconds: float,
    *,
    memory_mb: float | None = None,
) -> str:
    """Render a concise multi-line progress block suitable for CLI display."""
    label = PHASE_LABELS.get(phase, phase)
    total = max(1, total_files)
    pct = min(100, int(round((completed_files / total) * 100)))
    rate_per_min = int(round((completed_files / max(0.001, elapsed_seconds)) * 60.0))
    mem_val = int(round(memory_mb if memory_mb is not None else get_process_rss_mb()))
    return (
        f"Phase: {label}\n"
        f"{completed_files:,} / {total_files:,} files\n"
        f"{pct}%\n"
        f"elapsed: {format_duration_concise(elapsed_seconds)}\n"
        f"rate: {rate_per_min:,} files/min\n"
        f"memory: {mem_val} MB"
    )


@dataclass
class PhaseMetrics:
    """Telemetry counters and timing for a single indexing pipeline phase."""

    phase: str
    label: str
    elapsed_seconds: float = 0.0
    files_processed: int = 0
    items_processed: int = 0
    memory_mb: float = 0.0
    errors: int = 0
    skips: int = 0
    db_writes: int = 0

    @property
    def errors_skips(self) -> int:
        return self.errors + self.skips

    @errors_skips.setter
    def errors_skips(self, value: int) -> None:
        self.skips = max(0, value - self.errors)

    @property
    def throughput_per_sec(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        basis = self.items_processed if self.items_processed > 0 else self.files_processed
        return round(basis / self.elapsed_seconds, 2)

    @property
    def files_per_min(self) -> float:
        if self.elapsed_seconds <= 0.0:
            return 0.0
        return round((self.files_processed / self.elapsed_seconds) * 60.0, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "label": self.label,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "files_processed": self.files_processed,
            "items_processed": self.items_processed,
            "throughput_per_sec": self.throughput_per_sec,
            "memory_mb": round(self.memory_mb, 2),
            "errors": self.errors,
            "skips": self.skips,
            "errors_skips": self.errors + self.skips,
            "db_writes": self.db_writes,
        }


@dataclass
class IndexingTelemetry:
    """Complete 16-phase deterministic telemetry for an indexing pass."""

    phases: dict[str, PhaseMetrics] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)
    total_elapsed_seconds: float = 0.0
    scanned_files: int = 0
    indexed_files: int = 0
    unchanged_files: int = 0
    removed_files: int = 0
    parse_failed_files: int = 0
    symbols_count: int = 0
    edges_count: int = 0
    rss_before_mb: float = 0.0
    post_parse_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    steady_state_rss_mb: float = 0.0
    peak_wal_bytes: int = 0
    final_wal_bytes: int = 0
    final_db_bytes: int = 0
    commit_batches: int = 0
    checkpoints: int = 0
    interrupted: bool = False
    interrupted_phase: str | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        rss = get_process_rss_mb()
        if self.rss_before_mb == 0.0:
            self.rss_before_mb = rss
        if self.peak_rss_mb == 0.0:
            self.peak_rss_mb = rss
        for key, label in INDEXING_PHASES:
            if key not in self.phases:
                self.phases[key] = PhaseMetrics(phase=key, label=label)

    @property
    def batch_commits(self) -> int:
        return self.commit_batches

    @batch_commits.setter
    def batch_commits(self, value: int) -> None:
        self.commit_batches = value

    @property
    def wal_checkpoints(self) -> int:
        return self.checkpoints

    @wal_checkpoints.setter
    def wal_checkpoints(self, value: int) -> None:
        self.checkpoints = value

    @property
    def max_wal_size_mb(self) -> float:
        return round(self.peak_wal_bytes / (1024.0 * 1024.0), 3)

    @property
    def final_wal_size_mb(self) -> float:
        return round(self.final_wal_bytes / (1024.0 * 1024.0), 3)

    @contextmanager
    def phase(self, name: str) -> Iterator[PhaseMetrics]:
        """Time a phase and update its memory snapshot upon exit."""
        if name not in self.phases:
            self.phases[name] = PhaseMetrics(phase=name, label=PHASE_LABELS.get(name, name))
        metrics = self.phases[name]
        t0 = time.perf_counter()
        try:
            yield metrics
        except BaseException:
            if self.interrupted_phase is None:
                self.interrupted_phase = name
            raise
        finally:
            metrics.elapsed_seconds += time.perf_counter() - t0
            rss = get_process_rss_mb()
            metrics.memory_mb = max(metrics.memory_mb, rss)
            if rss > self.peak_rss_mb:
                self.peak_rss_mb = rss

    def record(
        self,
        phase: str,
        elapsed: float = 0.0,
        files: int = 0,
        items: int = 0,
        errors: int = 0,
        skips: int = 0,
        db_writes: int = 0,
        update_memory: bool = False,
        *,
        files_processed: int = 0,
        items_processed: int = 0,
        errors_skips: int = 0,
    ) -> None:
        """Accumulate metrics for a given phase."""
        if phase not in self.phases:
            self.phases[phase] = PhaseMetrics(phase=phase, label=PHASE_LABELS.get(phase, phase))
        m = self.phases[phase]
        m.elapsed_seconds += elapsed
        m.files_processed += files + files_processed
        m.items_processed += items + items_processed
        m.errors += errors
        m.skips += skips + errors_skips
        m.db_writes += db_writes
        if update_memory or m.memory_mb == 0.0:
            rss = get_process_rss_mb()
            m.memory_mb = max(m.memory_mb, rss)
            if rss > self.peak_rss_mb:
                self.peak_rss_mb = rss

    def observe_wal(self, db_path: Path) -> None:
        """Sample the SQLite WAL file size and update peak_wal_bytes."""
        wal_path = Path(f"{db_path}-wal")
        try:
            if wal_path.exists():
                sz = wal_path.stat().st_size
                if sz > self.peak_wal_bytes:
                    self.peak_wal_bytes = sz
                self.final_wal_bytes = sz
            else:
                self.final_wal_bytes = 0
        except OSError:
            pass

    def finish(self, db_path: Path | None = None) -> None:
        """Finalize total elapsed time, steady-state RSS, and final DB/WAL sizes."""
        self.total_elapsed_seconds = time.perf_counter() - self.started_at
        rss = get_process_rss_mb()
        self.steady_state_rss_mb = rss
        if rss > self.peak_rss_mb:
            self.peak_rss_mb = rss
        if db_path is not None:
            self.observe_wal(db_path)
            try:
                if db_path.exists():
                    self.final_db_bytes = db_path.stat().st_size
            except OSError:
                pass

    @property
    def slowest_phase(self) -> str:
        candidates = [
            k for k in self.phases if k != "post_processing" and self.phases[k].elapsed_seconds > 0
        ]
        if not candidates:
            return "repository_scan"
        return max(candidates, key=lambda k: self.phases[k].elapsed_seconds)

    def format_progress_block(
        self,
        phase: str,
        completed_files: int,
        total_files: int,
        elapsed_seconds: float,
    ) -> str:
        """Render a concise multi-line progress block suitable for CLI display."""
        return format_progress_block(
            phase,
            completed_files,
            total_files,
            elapsed_seconds,
            memory_mb=max(self.peak_rss_mb, get_process_rss_mb()),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_elapsed_seconds": round(self.total_elapsed_seconds, 4),
            "scanned_files": self.scanned_files,
            "indexed_files": self.indexed_files,
            "unchanged_files": self.unchanged_files,
            "removed_files": self.removed_files,
            "parse_failed_files": self.parse_failed_files,
            "symbols_count": self.symbols_count,
            "edges_count": self.edges_count,
            "files_per_sec": round(self.scanned_files / max(0.0001, self.total_elapsed_seconds), 2),
            "symbols_per_sec": round(self.symbols_count / max(0.0001, self.total_elapsed_seconds), 2),
            "edges_per_sec": round(self.edges_count / max(0.0001, self.total_elapsed_seconds), 2),
            "rss_before_mb": round(self.rss_before_mb, 2),
            "post_parse_rss_mb": round(self.post_parse_rss_mb, 2),
            "peak_rss_mb": round(self.peak_rss_mb, 2),
            "steady_state_rss_mb": round(self.steady_state_rss_mb, 2),
            "peak_wal_mb": round(self.peak_wal_bytes / (1024.0 * 1024.0), 3),
            "final_wal_mb": round(self.final_wal_bytes / (1024.0 * 1024.0), 3),
            "final_db_mb": round(self.final_db_bytes / (1024.0 * 1024.0), 3),
            "commit_batches": self.commit_batches,
            "checkpoints": self.checkpoints,
            "slowest_phase": self.slowest_phase,
            "interrupted": self.interrupted,
            "interrupted_phase": self.interrupted_phase,
            "warnings": list(self.warnings),
            "phases": {k: self.phases[k].as_dict() for k, _ in INDEXING_PHASES},
        }
