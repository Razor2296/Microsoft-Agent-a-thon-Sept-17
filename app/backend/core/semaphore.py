from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Import modules from the standard library
from functools import wraps
from typing import Any

from backend.core.libraries import get_assistant_logger

# Get logger for semaphore
logger = get_assistant_logger("semaphore")

# Class to adjust the semaphore limit.
class AdjustableSemaphore:
    """
    A custom semaphore implementation using a Condition variable
    that supports dynamically changing the concurrency limit at runtime.
    """
    # Function to initialize an AdjustableSemaphore.
    def __init__(self, limit: int):
        """ Initialize an AdjustableSemaphore. """
        self.limit = limit
        self.active_count = 0
        self.waiting_count = 0
        self.cond = threading.Condition()

    # Function to acquire the semaphore.
    def acquire(self, timeout: float | None = None) -> bool:
        """
        Acquire the semaphore, blocking if the active count has reached the limit.
        Returns True if acquired successfully, False if timed out.
        """
        with self.cond:
            self.waiting_count += 1
            start_time = time.time()
            try:
                while self.active_count >= self.limit:
                    if timeout is not None:
                        elapsed = time.time() - start_time
                        remaining = timeout - elapsed
                        if remaining <= 0:
                            logger.warning("AdjustableSemaphore: acquire timed out immediately.")
                            return False
                        if not self.cond.wait(remaining):
                            logger.warning(f"AdjustableSemaphore: acquire timed out after waiting {elapsed:.4f}s.")
                            return False
                    else:
                        self.cond.wait()
                self.active_count += 1
                return True
            finally:
                self.waiting_count -= 1

    # Function to release the semaphore.
    def release(self):
        """Release the semaphore, notifying waiting threads."""
        with self.cond:
            if self.active_count > 0:
                self.active_count -= 1
            self.cond.notify_all()

    # Function to set the limit of the semaphore.
    def set_limit(self, new_limit: int):
        """Dynamically adjust the concurrency limit and notify waiting threads."""
        with self.cond:
            logger.info(f"AdjustableSemaphore: limit adjusted from {self.limit} to {new_limit}.")
            self.limit = new_limit
            self.cond.notify_all()

# Class to manage semaphores.
class Semaphore:
    """
    A thread-safe semaphore manager that limits concurrent execution of functions
    across all threads, with statistics tracking and dynamic limit adjustments.
    """
    # Dictionary to store semaphores.
    _semaphores: dict[str, AdjustableSemaphore] = {}
    # Dictionary to store statistics.
    _stats: dict[str, dict[str, Any]] = {}
    # Lock to ensure thread safety.
    _lock = threading.Lock()

    # Function to initialize a Semaphore.
    def __init__(self, key: str, max_concurrent: int = 1, timeout: float | None = None):
        """
        Initialize a Semaphore instance for context manager usage.

        Args:
            key: A unique string identifier for this semaphore context.
            max_concurrent: The maximum number of concurrent executions allowed if not already created.
            timeout: Optional time in seconds to wait before raising TimeoutError.
        """
        self.key = key
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = self._get_or_create_semaphore(key, max_concurrent)
        self._acquired = False
        self._acquire_start_time = 0.0
        self._exec_start_time = 0.0

    # Class method to get or create a semaphore.
    @classmethod
    def _get_or_create_semaphore(cls, key: str, max_concurrent: int) -> AdjustableSemaphore:
        """Get or create a semaphore for the given key."""
        with cls._lock:
            if key not in cls._semaphores:
                cls._semaphores[key] = AdjustableSemaphore(max_concurrent)
                cls._stats[key] = {
                    "total_calls": 0,
                    "total_failures": 0,
                    "total_wait_time": 0.0,
                    "total_exec_time": 0.0,
                }
            return cls._semaphores[key]

    # Function to enter the semaphore context.
    def __enter__(self):
        """
        Acquire the semaphore, blocking if the active count has reached the limit.
        Returns True if acquired successfully, False if timed out.
        """
        self._acquire_start_time = time.time()
        acquired = self.semaphore.acquire(timeout=self.timeout)
        wait_time = time.time() - self._acquire_start_time

        # Update statistics.
        with self._lock:
            self._stats[self.key]["total_wait_time"] += wait_time
            self._stats[self.key]["total_calls"] += 1

        # Raise TimeoutError if the semaphore was not acquired.
        if not acquired:
            with self._lock:
                self._stats[self.key]["total_failures"] += 1
            raise TimeoutError(f"Failed to acquire semaphore '{self.key}' within {self.timeout} seconds.")

        # Set the acquired flag and record the execution start time.
        self._acquired = True
        self._exec_start_time = time.time()
        return self

    # Function to exit the semaphore context.
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._acquired:
            exec_time = time.time() - self._exec_start_time
            with self._lock:
                self._stats[self.key]["total_exec_time"] += exec_time
                if exc_type is not None:
                    self._stats[self.key]["total_failures"] += 1

            self.semaphore.release()
            self._acquired = False

    # Class method to limit the concurrency of a function.
    @classmethod
    def limit(cls, max_concurrent: int = 1, name: str | None = None, timeout: float | None = None):
        """
        Decorator to limit the concurrency of the decorated function.

        Args:
            max_concurrent: Maximum threads allowed to execute this function concurrently.
            name: Custom unique name for the function. Defaults to fully qualified function name.
            timeout: Optional time in seconds to wait before raising TimeoutError.
        """
        # Decorator to limit the concurrency of the decorated function.
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            # Get the key for the function.
            key = name or f"{func.__module__}.{func.__qualname__}"

            # Wrapper function to limit the concurrency of the decorated function.
            @wraps(func)
            def wrapper(*args, **kwargs):
                with cls(key, max_concurrent=max_concurrent, timeout=timeout):
                    return func(*args, **kwargs)
            return wrapper
        return decorator

    # Function to get the statistics of a function.
    @classmethod
    def get_stats(cls, key: str | None = None) -> dict[str, Any]:
        """ Get concurrency statistics for a specific function/key or all functions. """
        with cls._lock:
            if key:
                if key not in cls._stats:
                    return {}
                sem = cls._semaphores[key]
                stats = cls._stats[key].copy()
                stats.update({
                    "active_threads": sem.active_count,
                    "waiting_threads": sem.waiting_count,
                    "limit": sem.limit
                })
                return stats
            else:
                # Dictionary to store all statistics.
                all_stats = {}
                # For each key.
                for k, sem in cls._semaphores.items():
                    stats = cls._stats[k].copy()
                    stats.update({
                        "active_threads": sem.active_count,
                        "waiting_threads": sem.waiting_count,
                        "limit": sem.limit
                    })
                    all_stats[k] = stats
                return all_stats

    # Function to adjust the limit of a semaphore.
    @classmethod
    def adjust_limit(cls, key: str, new_limit: int):
        """
        Dynamically adjust the concurrency limit for a specific function/key.
        """
        with cls._lock:
            if key in cls._semaphores:
                cls._semaphores[key].set_limit(new_limit)
                logger.info(f"Adjusted semaphore limit for '{key}' to {new_limit}.")
            else:
                # Create a new registry entry if it doesn't exist
                cls._semaphores[key] = AdjustableSemaphore(new_limit)
                cls._stats[key] = {
                    "total_calls": 0,
                    "total_failures": 0,
                    "total_wait_time": 0.0,
                    "total_exec_time": 0.0,
                }
                logger.info(f"Initialized new semaphore registry for '{key}' with limit {new_limit}.")
