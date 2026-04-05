from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.utils.rate_limiter import TokenBucketRateLimiter

T = TypeVar("T")

logger = logging.getLogger(__name__)


class BaseAPIClient:
    """Async HTTP client with rate limiting and automatic retry."""

    def __init__(
        self,
        base_url: str,
        rate_limit: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._rate_limiter = TokenBucketRateLimiter(rate=rate_limit, capacity=int(rate_limit * 2))
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._timeout = timeout
        self._default_headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._default_headers,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _execute_with_retry(
        self,
        request_func: Callable[[int], Awaitable[httpx.Response]],
        status_forcelist: set[int] | None = None,
    ) -> httpx.Response:
        status_forcelist = status_forcelist or {429, 500, 502, 503, 504}

        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                await self._rate_limiter.acquire()
                response = await request_func(attempt)

                if response.status_code in status_forcelist:
                    wait_time = self.retry_delay * (2 ** attempt)
                    if "Retry-After" in response.headers:
                        try:
                            wait_time = float(response.headers["Retry-After"])
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "Received %s from %s (attempt %d/%d), retrying in %.1fs",
                        response.status_code,
                        response.url,
                        attempt + 1,
                        self.max_retries + 1,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exception = exc
                wait_time = self.retry_delay * (2 ** attempt)
                logger.warning(
                    "Network error on attempt %d/%d: %s, retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in status_forcelist:
                    last_exception = exc
                    wait_time = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    raise

        raise RuntimeError(
            f"All {self.max_retries + 1} retries exhausted. "
            f"Last error: {last_exception or 'unknown'}"
        )

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        req_headers = {**self._default_headers, **(headers or {})}

        async def _do(attempt: int) -> httpx.Response:
            return await self.client.request(
                method=method,
                url=url,
                params=params,
                json=json,
                headers=req_headers,
            )

        return await self._execute_with_retry(_do)

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("POST", path, json=json, headers=headers)

    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("PUT", path, json=json, headers=headers)

    @client.setter
    def client(self, value: httpx.AsyncClient) -> None:
        self._client = value

    def set_header(self, key: str, value: str) -> None:
        self._default_headers[key] = value
