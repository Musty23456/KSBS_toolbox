"""
Per-user sliding-window rate limiter for AI endpoints.

In-process, like the existing global limiter in app/main.py: fine for a
single instance; use a shared store (e.g. Redis) behind the same interface
for multi-instance deployments.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.ai.errors import AIRateLimitedError


class SlidingWindowLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(self.window - (now - hits[0])) + 1)
                raise AIRateLimitedError(retry_after=retry_after)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


ai_limiter = SlidingWindowLimiter()
