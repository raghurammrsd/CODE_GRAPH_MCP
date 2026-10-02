from __future__ import annotations

import concurrent.futures
import time

from codegraph.resources import RequestCoalescer


def test_request_coalescer_single_execution() -> None:
    coalescer = RequestCoalescer()
    call_count = 0

    def slow_work() -> str:
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        return "result_value"

    # Launch 5 concurrent calls with the same key
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(coalescer.coalesce, "query_key_1", slow_work) for _ in range(5)]
        results = [f.result() for f in futures]

    assert all(r == "result_value" for r in results)
    # The expensive computation must have executed only once!
    assert call_count == 1
    stats = coalescer.stats()
    assert stats["coalesced_requests"] >= 1


def test_request_coalescer_different_keys() -> None:
    coalescer = RequestCoalescer()
    call_count = 0

    def work(key: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"res_{key}"

    r1 = coalescer.coalesce("key_A", lambda: work("A"))
    r2 = coalescer.coalesce("key_B", lambda: work("B"))

    assert r1 == "res_A"
    assert r2 == "res_B"
    assert call_count == 2
