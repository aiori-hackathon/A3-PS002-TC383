"""Tiny in-memory failure limiter (per process). Counts failures in a sliding window; once the limit is
reached the caller is blocked until old failures age out. Global, not per client: behind a proxy the client
address cannot be trusted, so this protects the ledger and the password at the cost of a short lockout."""
import threading
import time
from collections import deque


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: float):
        self.max, self.window = max_failures, window_seconds
        self._hits: deque = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float):
        while self._hits and now - self._hits[0] > self.window:
            self._hits.popleft()

    def blocked(self) -> bool:
        with self._lock:
            self._prune(time.monotonic())
            return len(self._hits) >= self.max

    def record(self):
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._hits.append(now)
