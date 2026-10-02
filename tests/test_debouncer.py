from __future__ import annotations

import time

from codegraph.resources import FileChangeDebouncer


def test_file_debouncer_coalesces_rapid_events() -> None:
    debouncer = FileChangeDebouncer(debounce_ms=50)
    triggered_batches: list[set[str]] = []

    def on_batch(paths: set[str]) -> None:
        triggered_batches.append(paths)

    debouncer.start(on_batch)
    try:
        # Simulate editor saving 3 times rapidly
        debouncer.record_change("src/app.py")
        debouncer.record_change("src/app.py")
        debouncer.record_change("src/utils.py")

        # Wait for debounce window to fire
        time.sleep(0.15)

        assert len(triggered_batches) == 1
        assert triggered_batches[0] == {"src/app.py", "src/utils.py"}
    finally:
        debouncer.stop()


def test_file_debouncer_flush() -> None:
    debouncer = FileChangeDebouncer(debounce_ms=500)
    debouncer.record_change("file1.py")
    debouncer.record_change("file2.py")

    flushed = debouncer.flush()
    assert flushed == {"file1.py", "file2.py"}
    assert debouncer.flush() == set()
