from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from app.clients.base_client import BaseAPIClient

logger = logging.getLogger(__name__)


class OzonPerformanceClient(BaseAPIClient):
    """Client for Ozon Performance advertising API."""

    BASE_URL = "https://api-performance.ozon.ru"

    # Ozon API daily limits
    DAILY_REQUEST_LIMIT = 100000
    DAILY_REPORT_DOWNLOAD_LIMIT = 1000

    # Time before expiry to proactively refresh (seconds)
    REFRESH_WINDOW = 120  # 2 minutes

    def __init__(self, client_id: str, client_secret: str) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            rate_limit=10.0,
            max_retries=3,
            retry_delay=1.0,
            timeout=60.0,
        )
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._refresh_token: str | None = None
        self._daily_request_count = 0
        self._daily_download_count = 0
        self._request_date: datetime | None = None

    def _reset_daily_counts_if_new_day(self) -> None:
        now = datetime.now(timezone.utc)
        if self._request_date is None or self._request_date.date() != now.date():
            self._daily_request_count = 0
            self._daily_download_count = 0
            self._request_date = now

    async def _perform_oauth(self) -> dict[str, Any]:
        """Perform OAuth2 authorization code or client credentials flow."""
        resp = await httpx.AsyncClient(timeout=30.0).post(
            "https://api-performance.ozon.ru/v1/authorization/code/token",
            json={
                "client_id": self._client_id,
                "grant_type": "client_credentials",
            },
            headers={"Client-Id": self._client_id, "Client-Secret": self._client_secret},
        )
        resp.raise_for_status()
        return resp.json()

    async def _refresh_token_if_needed(self) -> None:
        """Refresh access token if expired or about to expire."""
        if self._token_expires_at is None:
            await self.authenticate()
            return

        now = datetime.now(timezone.utc)
        if now >= self._token_expires_at - timedelta(seconds=self.REFRESH_WINDOW):
            logger.info("Ozon access token expiring soon, refreshing...")
            await self.authenticate()

    async def authenticate(self) -> None:
        """Authenticate with Ozon API and store tokens."""
        try:
            token_data = await self._perform_oauth()
        except httpx.HTTPStatusError as exc:
            logger.error("Ozon authentication failed: %s", exc.response.text)
            raise

        self._access_token = token_data.get("access_token")
        self._refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self.set_header("Authorization", f"Bearer {self._access_token}")
        logger.info("Successfully authenticated with Ozon API")

    def _ensure_ready(self) -> None:
        self._reset_daily_counts_if_new_day()
        if self._daily_request_count >= self.DAILY_REQUEST_LIMIT:
            raise RuntimeError("Ozon daily API request limit reached")

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._ensure_ready()
        await self._refresh_token_if_needed()
        self._daily_request_count += 1
        return await super().request(method, path, params=params, json=json, headers=headers)

    # ------------------------------------------------------------------ #
    # Campaign endpoints
    # ------------------------------------------------------------------ #

    async def get_campaigns(self) -> list[dict[str, Any]]:
        """List all advertising campaigns."""
        all_campaigns: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            resp = await self.post(
                "/v1/campaign/list",
                json={"offset": offset, "limit": limit},
            )
            data = resp.json()
            campaigns = data.get("campaigns", [])
            all_campaigns.extend(campaigns)

            total = data.get("total", 0)
            if offset + limit >= total or len(campaigns) < limit:
                break
            offset += limit

        return all_campaigns

    async def update_bids(self, campaign_id: str, bids: list[dict[str, Any]]) -> dict[str, Any]:
        """Update bids for a campaign.

        WARNING: Ozon uses replace-all semantics. The caller must first
        get_current_bids(), merge with the changes, and then send the
        complete set.
        """
        resp = await self.post(
            f"/v1/campaign/{campaign_id}/bids",
            json={"bids": bids},
        )
        return resp.json()

    async def get_recommended_bid(self, sku: str) -> dict[str, Any]:
        """Get recommended bid for a specific SKU."""
        resp = await self.post(
            "/v1/bid/recommendation",
            json={"sku": sku},
        )
        return resp.json()

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        """Get campaign statistics."""
        resp = await self.post(
            "/v1/analytics/campaign",
            json={"campaign_id": campaign_id},
        )
        return resp.json()

    # ------------------------------------------------------------------ #
    # Report Manager (async report model)
    # ------------------------------------------------------------------ #

    async def create_report(self, report_type: str, params: dict[str, Any]) -> str:
        """Create an async report and return its task_id."""
        resp = await self.post(
            "/v1/report/create",
            json={"type": report_type, "params": params},
        )
        data = resp.json()
        return data.get("task_id", data.get("report_id", ""))

    async def get_report_status(self, task_id: str) -> dict[str, Any]:
        """Check status of an async report."""
        resp = await self.get(f"/v1/report/{task_id}")
        return resp.json()

    async def wait_for_report(
        self, task_id: str, poll_interval: float = 5.0, max_wait: float = 300.0
    ) -> str:
        """Poll until report is ready. Returns download URL."""
        start = asyncio.get_event_loop().time()
        while True:
            status_data = await self.get_report_status(task_id)
            state = status_data.get("status", status_data.get("state", ""))

            if state in ("ready", "completed", "success"):
                return status_data.get("download_url", status_data.get("url", ""))

            if state in ("failed", "error"):
                raise RuntimeError(f"Report generation failed: {status_data}")

            if asyncio.get_event_loop().time() - start > max_wait:
                raise TimeoutError(f"Report not ready after {max_wait}s")

            await asyncio.sleep(poll_interval)

    async def download_report_csv(self, download_url: str) -> pd.DataFrame:
        """Download and parse a CSV report into a DataFrame."""
        if self._daily_download_count >= self.DAILY_REPORT_DOWNLOAD_LIMIT:
            raise RuntimeError("Ozon daily report download limit reached")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            self._daily_download_count += 1

        csv_text = resp.text
        df = pd.read_csv(io.StringIO(csv_text))
        return df

    async def get_report_data(
        self, report_type: str, params: dict[str, Any]
    ) -> pd.DataFrame:
        """End-to-end: create, wait, download, return DataFrame."""
        task_id = await self.create_report(report_type, params)
        download_url = await self.wait_for_report(task_id)
        return await self.download_report_csv(download_url)
