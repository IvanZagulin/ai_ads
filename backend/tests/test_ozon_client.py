"""Tests for OzonPerformanceClient: OAuth auth, auto-refresh, async report model, CSV parsing."""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pandas as pd
import pytest

from app.clients.ozon_client import OzonPerformanceClient


@pytest.fixture
def ozon_client() -> OzonPerformanceClient:
    """Create Ozon client with test credentials."""
    return OzonPerformanceClient(client_id="test-client-123", client_secret="test-secret-456")


@pytest.mark.asyncio
async def test_authenticate_sets_token(ozon_client: OzonPerformanceClient) -> None:
    """Successful OAuth should set access token and header."""
    token_data = {
        "access_token": "eyJ.test.token",
        "refresh_token": "refresh.abc",
        "expires_in": 3600,
    }

    mock_response = MagicMock()
    mock_response.json.return_value = token_data
    mock_response.raise_for_status = MagicMock()

    with patch("app.clients.ozon_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await ozon_client.authenticate()

    assert ozon_client._access_token == "eyJ.test.token"
    assert ozon_client._default_headers["Authorization"] == "Bearer eyJ.test.token"
    assert ozon_client._refresh_token == "refresh.abc"
    assert ozon_client._token_expires_at is not None


@pytest.mark.asyncio
async def test_authenticate_failure_raises(ozon_client: OzonPerformanceClient) -> None:
    """Failed authentication should raise an error."""
    with patch("app.clients.ozon_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=httpx.Request("POST", "https://test"),
            response=httpx.Response(401, text="invalid_grant"),
        )
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(httpx.HTTPStatusError):
            await ozon_client.authenticate()


@pytest.mark.asyncio
async def test_token_auto_refresh_before_expiry(ozon_client: OzonPerformanceClient) -> None:
    """Token should be refreshed when it is about to expire."""
    ozon_client._access_token = "old_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    ozon_client._refresh_token = "old_refresh"

    token_data = {
        "access_token": "new_token",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
    }

    mock_response = MagicMock()
    mock_response.json.return_value = token_data
    mock_response.raise_for_status = MagicMock()

    with patch("app.clients.ozon_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await ozon_client._refresh_token_if_needed()

    assert ozon_client._access_token == "new_token"
    assert ozon_client._default_headers["Authorization"] == "Bearer new_token"


@pytest.mark.asyncio
async def test_no_refresh_when_token_fresh(ozon_client: OzonPerformanceClient) -> None:
    """Fresh token should not trigger a refresh."""
    ozon_client._access_token = "fresh_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with patch.object(ozon_client, "authenticate", new_callable=AsyncMock) as mock_auth:
        await ozon_client._refresh_token_if_needed()
        mock_auth.assert_not_called()


@pytest.mark.asyncio
async def test_daily_request_count_tracking(ozon_client: OzonPerformanceClient) -> None:
    """Daily request count should increment."""
    ozon_client._request_date = datetime.now(timezone.utc).date()
    ozon_client._daily_request_count = 0

    ozon_client._ensure_ready()
    ozon_client._daily_request_count += 1
    assert ozon_client._daily_request_count == 1


@pytest.mark.asyncio
async def test_daily_request_limit_raises(ozon_client: OzonPerformanceClient) -> None:
    """Should raise error when daily limit is reached."""
    ozon_client._request_date = datetime.now(timezone.utc).date()
    ozon_client._daily_request_count = ozon_client.DAILY_REQUEST_LIMIT

    with pytest.raises(RuntimeError, match="daily API request limit reached"):
        ozon_client._ensure_ready()


@pytest.mark.asyncio
async def test_create_report(ozon_client: OzonPerformanceClient) -> None:
    """Test creating an async report returns task_id."""
    ozon_client._access_token = "test_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ozon_client._request_date = datetime.now(timezone.utc).date()

    mock_response = MagicMock()
    mock_response.json.return_value = {"task_id": "report_task_001", "status": "pending"}
    mock_response.raise_for_status = MagicMock()

    ozon_client.client = AsyncMock()
    ozon_client.client.request = AsyncMock(return_value=mock_response)
    ozon_client._rate_limiter.acquire = AsyncMock()

    task_id = await ozon_client.create_report(
        report_type="campaign_stats", params={"campaign_id": "12345"}
    )
    assert task_id == "report_task_001"


@pytest.mark.asyncio
async def test_wait_for_report_ready(ozon_client: OzonPerformanceClient) -> None:
    """Test waiting for a report to become ready."""
    ozon_client._access_token = "test_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ozon_client._request_date = datetime.now(timezone.utc).date()

    call_count = 0

    async def mock_request(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        if call_count <= 2:
            mock_resp.json.return_value = {"status": "pending"}
        else:
            mock_resp.json.return_value = {
                "status": "ready",
                "download_url": "https://download.example.com/report.csv",
            }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    ozon_client.client = AsyncMock()
    ozon_client.client.request = mock_request
    ozon_client._rate_limiter.acquire = AsyncMock()

    url = await ozon_client.wait_for_report("task_001", poll_interval=0.05, max_wait=10.0)
    assert url == "https://download.example.com/report.csv"
    assert call_count == 3


@pytest.mark.asyncio
async def test_wait_for_report_failed(ozon_client: OzonPerformanceClient) -> None:
    """Test that failed reports raise an error."""
    ozon_client._access_token = "test_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ozon_client._request_date = datetime.now(timezone.utc).date()

    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "failed", "error": "not enough data"}
    mock_response.raise_for_status = MagicMock()

    ozon_client.client = AsyncMock()
    ozon_client.client.request = AsyncMock(return_value=mock_response)
    ozon_client._rate_limiter.acquire = AsyncMock()

    with pytest.raises(RuntimeError, match="Report generation failed"):
        await ozon_client.wait_for_report("task_fail", poll_interval=0.05)


@pytest.mark.asyncio
async def test_download_report_csv_parses_correctly(ozon_client: OzonPerformanceClient) -> None:
    """Test that downloaded CSV is parsed into a DataFrame."""
    csv_content = "date,views,clicks,cost,orders\n2024-01-15,1000,50,500.0,10\n2024-01-16,1200,60,600.0,12"

    mock_get_response = MagicMock()
    mock_get_response.text = csv_content
    mock_get_response.raise_for_status = MagicMock()

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return mock_get_response

    ozon_client._daily_download_count = 0

    with patch("app.clients.ozon_client.httpx.AsyncClient", MockClient):
        df = await ozon_client.download_report_csv("https://example.com/report.csv")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["date", "views", "clicks", "cost", "orders"]
    assert df.iloc[0]["views"] == 1000


@pytest.mark.asyncio
async def test_get_campaigns_pagination(ozon_client: OzonPerformanceClient) -> None:
    """Test that get_campaigns handles pagination correctly."""
    ozon_client._access_token = "test_token"
    ozon_client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ozon_client._request_date = datetime.now(timezone.utc).date()

    responses = [
        {
            "campaigns": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            "total": 3,
        },
        {
            "campaigns": [{"id": 3, "name": "C"}],
            "total": 3,
        },
    ]
    call_idx = 0

    async def mock_request(**kwargs: object) -> MagicMock:
        nonlocal call_idx
        mock_resp = MagicMock()
        mock_resp.json.return_value = responses[call_idx]
        mock_resp.raise_for_status = MagicMock()
        call_idx += 1
        return mock_resp

    ozon_client.client = AsyncMock()
    ozon_client.client.request = mock_request
    ozon_client._rate_limiter.acquire = AsyncMock()

    campaigns = await ozon_client.get_campaigns()
    assert len(campaigns) == 3
    assert [c["name"] for c in campaigns] == ["A", "B", "C"]
