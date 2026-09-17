"""Unit tests for AdjustableSemaphore / Semaphore manager."""

import os
import threading
import time

from backend.core.semaphore import AdjustableSemaphore, Semaphore


def test_adjustable_semaphore_limits_concurrency():
    sem = AdjustableSemaphore(2)
    active = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal active, peak
        assert sem.acquire(timeout=2.0)
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        sem.release()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak <= 2


def test_semaphore_context_manager_and_stats():
    Semaphore.adjust_limit("unit_test_key", 1)
    with Semaphore("unit_test_key", max_concurrent=1):
        stats = Semaphore.get_stats("unit_test_key")
        assert stats["limit"] == 1
        assert stats["active_threads"] == 1
    stats_after = Semaphore.get_stats("unit_test_key")
    assert stats_after["active_threads"] == 0
    assert stats_after["total_calls"] >= 1


def test_group_max_parallel_env_parse():
    raw = os.getenv("GROUP_MAX_PARALLEL", "3")
    assert max(1, int(raw)) >= 1
