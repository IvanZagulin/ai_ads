"""Tests for WBPromotionClient: request formation, error handling, retry logic, rate limiting."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.wb_client import WBPromotionClient
from app.utils.rate_limiter import TokenBucketRateLimiter


@pytest.fixture
def wb_client() -> WBPromotionClient:
    """Create a WB client with mock token."""
    return WBPromotionClient(api_token="test-wb-token-12345")


@pytest.mark.asyncio
async def test_wb_client_sends_correct_auth_header(wb_client: WBPromotionClient) -> None:
    """Verify the authorization header is set correctly."""
    assert wb_client._default_headers.get("Authorization") == "test-wb-token-12345"


@pytest.mark.asyncio
async def test_get_campaigns_response(wb_client: WBPromotionClient) -> None:
    """Test get_campaigns handles a successful response."""
    mock_campaigns = [
        {"id": 1, "name": "Campaign A", "status": "active"},
        {"id": 2, "name": "Campaign B", "status": "paused"},
    ]
    mock_response = MagicMock()
    mock_response.json.return_value = {"advertisement": mock_campaigns}
    mock_response.raise_for_status = MagicMock()

    wb_client.client = AsyncMock()
    wb_client.client.request = AsyncMock(return_value=mock_response)
    # Bypass rate limiter
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.get_campaigns()
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["name"] == "Campaign B"


@pytest.mark.asyncio
async def test_get_campaigns_array_response(wb_client: WBPromotionClient) -> None:
    """Test get_campaigns handles a direct array response."""
    mock_campaigns = [{"id": 1}, {"id": 2}]
    mock_response = MagicMock()
    mock_response.json.return_value = mock_campaigns
    mock_response.raise_for_status = MagicMock()

    wb_client.client = AsyncMock()
    wb_client.client.request = AsyncMock(return_value=mock_response)
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.get_campaigns()
    assert len(result) == 2
    assert result[0] == {"id": 1}


@pytest.mark.asyncio
async def test_get_campaigns_empty_response(wb_client: WBPromotionClient) -> None:
    """Test get_campaigns handles empty response."""
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()

    wb_client.client = AsyncMock()
    wb_client.client.request = AsyncMock(return_value=mock_response)
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.get_campaigns()
    assert result == []


@pytest.mark.asyncio
async def test_rate_limiter_limits_requests() -> None:
    """Test that rate limiter enforces request spacing."""
    limiter = TokenBucketRateLimiter(rate=2.0, capacity=2)
    # Should be able to acquire 2 immediately
    await limiter.acquire()
    await limiter.acquire()
    # Third one should require waiting
    start = asyncio.get_event_loop().time()
    await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed > 0.2  # should have waited for a new token


@pytest.mark.asyncio
async def test_wb_client_retry_on_429(wb_client: WBPromotionClient) -> None:
    """Test that 429 responses trigger retries."""
    call_count = 0

    async def mock_request(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        if call_count <= 2:
            mock_resp.status_code = 429
            mock_resp.headers = {"Retry-After": "0.1"}
            mock_resp.url = "http://test/adv/v0/promotionadslist"
            return mock_resp
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"advertisement": [{"id": 1}]}
        return mock_resp

    wb_client.client = AsyncMock()
    wb_client.client.request = mock_request
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.get_campaigns()
    assert call_count == 3  # 2 failures + 1 success
    assert len(result) == 1


@pytest.mark.asyncio
async def test_wb_client_retry_on_500(wb_client: WBPromotionClient) -> None:
    """Test that 500 responses trigger retries with exponential backoff."""
    call_count = 0

    async def mock_request(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        if call_count <= 2:
            mock_resp.status_code = 500
            mock_resp.headers = {}
            mock_resp.url = "http://test/adv/v0/campaigns/info"
            return mock_resp
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"id": 99}]
        return mock_resp

    wb_client.client = AsyncMock()
    wb_client.client.request = mock_request
    wb_client._rate_limiter.acquire = AsyncMock()
    # Speed up retries for test
    wb_client.retry_delay = 0.05

    result = await wb_client.get("/adv/v0/campaigns/info", params={"ids": "99"})
    assert call_count == 3


@pytest.mark.asyncio
async def test_wb_client_raises_after_max_retries(wb_client: WBPromotionClient) -> None:
    """Test that client raises error after all retries are exhausted."""
    wb_client.max_retries = 1
    wb_client.retry_delay = 0.05

    async def mock_request(**kwargs: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.headers = {}
        mock_resp.url = "http://test/"
        return mock_resp

    wb_client.client = AsyncMock()
    wb_client.client.request = mock_request
    wb_client._rate_limiter.acquire = AsyncMock()

    with pytest.raises(RuntimeError, match="All.*retries exhausted"):
        await wb_client.get("/adv/v0/some-endpoint")


@pytest.mark.asyncio
async def test_wb_client_raises_on_401_immediately(wb_client: WBPromotionClient) -> None:
    """Test that 401 is not retried and raises immediately."""
    wb_client.retry_delay = 0.05

    mock_resp = httpx.Response(
        status_code=401,
        request=httpx.Request("GET", "https://test/"),
        text="Unauthorized",
    )

    async def mock_request(**kwargs: object) -> httpx.Response:
        return mock_resp

    wb_client.client = AsyncMock()
    wb_client.client.request = mock_request
    wb_client._rate_limiter.acquire = AsyncMock()

    with pytest.raises(httpx.HTTPStatusError):
        await wb_client.get("/adv/v0/protected")


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_set_cluster_bid_request(mock_post, wb_client: WBPromotionClient) -> None:
    """Test that set_cluster_bid sends correct JSON payload matching WB API spec."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": "ok"}
    mock_post.return_value = mock_response
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.set_cluster_bid(
        advert_id=1825035, nm_id=983512347, norm_query="книга фэнтези", bid=700
    )
    assert result == {"result": "ok"}
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"] == {
        "bids": [{
            "advert_id": 1825035,
            "nm_id": 983512347,
            "norm_query": "книга фэнтези",
            "bid": 700,
        }]
    }


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_add_minus_phrase_request(mock_post, wb_client: WBPromotionClient) -> None:
    """Test that add_minus_phrase sends correct payload matching WB API spec."""
    # First call: get_minus_phrases returns existing
    existing_response = MagicMock()
    existing_response.status_code = 200
    existing_response.json.return_value = {"items": [{"advert_id": 42, "nm_id": 1, "norm_queries": ["-старый"]}]}
    # Second call: set_minus_phrases
    set_response = MagicMock()
    set_response.status_code = 200
    set_response.json.return_value = {"result": "ok"}
    mock_post.side_effect = [existing_response, set_response]
    wb_client._rate_limiter.acquire = AsyncMock()

    result = await wb_client.add_minus_phrase(42, 1, "-плохой")
    assert result == {"result": "ok"}
    # Second POST was set-minus
    set_call = mock_post.call_args_list[1][1]
    assert "norm_queries" in set_call["json"]
    assert "-плохой" in set_call["json"]["norm_queries"]
