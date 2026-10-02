"""Reproducible, dependency-free performance smoke benchmark.

Run: PYTHONPATH=src python benchmarks/benchmark.py examples/demo-repository
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.search import search


def measured(label: str, action: object) -> None:
    start = time.perf_counter()
    result = action()  # type: ignore[operator]
    elapsed = (time.perf_counter() - start) * 1000
    print(f"{label}: {elapsed:.2f}ms {result}")


def main(repository: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="codegraph-benchmark-") as temporary:
        copied = Path(temporary) / "repository"
        shutil.copytree(repository, copied, ignore=shutil.ignore_patterns(".codegraph.sqlite3"))
        indexer = Indexer(copied)
        measured("cold index", indexer.index)
        measured("incremental index", indexer.index)
        with indexer.connect() as con:
            measured("search", lambda: len(search(con, "login")))
            measured("symbol lookup", lambda: con.execute("SELECT count(*) FROM symbols").fetchone()[0])


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
