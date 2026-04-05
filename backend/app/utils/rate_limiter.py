from __future__ import annotations

import asyncio
import time
import logging

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Async-safe token bucket rate limiter.

    Tokens are added at a fixed `rate` (tokens/second) up to `capacity`.
    Each `acquire()` call consumes one token. If no tokens are available,
    the caller is suspended until one becomes available.
    """

    def __init__(self, rate: float = 10.0, capacity: int = 20) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self.rate
        if added > 0:
            self._tokens = min(self.capacity, self._tokens + added)
            self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens, waiting if necessary."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                # Calculate wait time for enough tokens
                deficit = tokens - self._tokens
                wait_time = deficit / self.rate

            logger.debug("Rate limiter: waiting %.3fs for %d token(s)", wait_time, int(tokens))
            await asyncio.sleep(wait_time)

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting. Returns True if successful."""
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """Current approximate number of available tokens (not thread-safe)."""
        self._refill()
        return self._tokens
