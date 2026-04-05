"""Tests for ActionExecutor: action execution, safety limits, logging."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

from app.executor.action_executor import (
    ActionExecutor,
    MAX_BID_CHANGE_PCT,
    MAX_BUDGET_INCREASE_PCT,
    MAX_MINUS_WORDS_PER_CYCLE,
)
from app.models.models import Campaign, LLMDecision


class DummySession:
    """Minimal mock for AsyncSession."""

    def __init__(self) -> None:
        self._db: dict[int, object] = {}
        self._next_id = 1
        self.added: list[object] = []

    async def get(self, model_type: type, pk: int) -> object | None:
        return self._db.get(pk)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._db[self._next_id] = obj
            self._next_id += 1

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _make_campaign(
    campaign_id: int = 1,
    platform: str = "wildberries",
    name: str = "Test Campaign",
    current_bid: float | None = 10.0,
    daily_budget: float | None = 100.0,
    platform_campaign_id: str = "12345",
    nm_ids: list[int] | None = None,
) -> Campaign:
    return Campaign(
        id=campaign_id,
        account_id=1,
        platform=platform,
        name=name,
        current_bid=current_bid,
        daily_budget=daily_budget,
        platform_campaign_id=platform_campaign_id,
        status="active",
        campaign_type="search",
        nm_ids=nm_ids or [111111],
    )


def _make_decision(decision_id: int = 1, campaign_id: int = 1, actions: list[dict] | None = None) -> LLMDecision:
    d = LLMDecision(
        id=decision_id,
        campaign_id=campaign_id,
        prompt_text="test prompt",
        llm_response="test response",
        llm_provider="test",
        llm_model="test-model",
        actions_json={"actions": actions or []},
        status="pending",
    )
    return d


@pytest.fixture
def executor() -> ActionExecutor:
    session = DummySession()
    wb_mock = MagicMock()
    ozon_mock = MagicMock()
    return ActionExecutor(
        db_session=session,
        wb_client=wb_mock,
        ozon_client=ozon_mock,
        auto_mode=True,
    )


@pytest.fixture
def executor_semi_auto() -> ActionExecutor:
    session = DummySession()
    wb_mock = MagicMock()
    ozon_mock = MagicMock()
    return ActionExecutor(
        db_session=session,
        wb_client=wb_mock,
        ozon_client=ozon_mock,
        auto_mode=False,
    )


@pytest.mark.asyncio
async def test_raise_bid_within_limits(executor: ActionExecutor) -> None:
    campaign = _make_campaign(campaign_id=1, current_bid=10.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "raise_bid",
        "reasoning": "Good CTR",
        "keyword_id": 42,
        "current_value": 10.0,
        "new_value": 12.0,
        "step_percent": 20.0,
    }

    executor.wb.set_cluster_bid = AsyncMock(return_value={"result": "ok"})

    applied = await executor.raise_bid(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "success"
    assert applied[0].action_type == "raise_bid"
    assert campaign.current_bid == 12.0


@pytest.mark.asyncio
async def test_raise_bid_clamped_to_max_20_percent(executor: ActionExecutor) -> None:
    """Bid increase > 20% should be clamped."""
    campaign = _make_campaign(campaign_id=1, current_bid=100.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "raise_bid",
        "reasoning": "test",
        "current_value": 100.0,
        "new_value": 200.0,  # 100% increase - should be clamped
        "step_percent": 100.0,
        "decision_id": 1,
    }

    executor.wb.set_cluster_bid = AsyncMock(return_value={"result": "ok"})

    applied = await executor.raise_bid(action, campaign_id=1)
    assert len(applied) == 1
    # Should not exceed +20%
    assert campaign.current_bid <= 120.0  # 100 + 20%


@pytest.mark.asyncio
async def test_lower_bid_within_limits(executor: ActionExecutor) -> None:
    campaign = _make_campaign(campaign_id=1, current_bid=10.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "lower_bid",
        "reasoning": "Poor CTR",
        "current_value": 10.0,
        "new_value": 8.5,
        "step_percent": 15.0,
        "decision_id": 1,
    }

    executor.wb.set_cluster_bid = AsyncMock(return_value={"result": "ok"})

    applied = await executor.lower_bid(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "success"
    assert campaign.current_bid == 8.5


@pytest.mark.asyncio
async def test_lower_bid_clamped_to_minimum(executor: ActionExecutor) -> None:
    """Negative resulting bid should be clamped to 0.01."""
    campaign = _make_campaign(campaign_id=1, current_bid=1.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "lower_bid",
        "reasoning": "very bad",
        "current_value": 1.0,
        "new_value": -5.0,
        "decision_id": 1,
    }

    executor.wb.set_cluster_bid = AsyncMock(return_value={"result": "ok"})

    applied = await executor.lower_bid(action, campaign_id=1)
    assert len(applied) == 1
    assert campaign.current_bid == 0.01  # minimum floor


@pytest.mark.asyncio
async def test_minus_word_wildberries(executor: ActionExecutor) -> None:
    """Minus word action on WB should succeed."""
    campaign = _make_campaign(campaign_id=1, platform="wildberries")
    executor.db._db[1] = campaign

    action = {
        "action_type": "minus_word",
        "reasoning": "Irrelevant",
        "campaign_id": 1,
        "minus_text": "-бесплатно",
        "decision_id": 1,
    }

    executor.wb.add_minus_phrase = AsyncMock(return_value={"result": "added"})

    applied = await executor.minus_word(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "success"


@pytest.mark.asyncio
async def test_minus_word_skipped_for_ozon(executor: ActionExecutor) -> None:
    """Minus word should be skipped for non-WB platforms."""
    campaign = _make_campaign(campaign_id=1, platform="ozon")
    executor.db._db[1] = campaign

    action = {
        "action_type": "minus_word",
        "reasoning": "Irrelevant",
        "campaign_id": 1,
        "minus_text": "-cheap",
        "decision_id": 1,
    }

    applied = await executor.minus_word(action, campaign_id=1)
    assert applied == []


@pytest.mark.asyncio
async def test_minus_word_respects_max_per_cycle(executor: ActionExecutor) -> None:
    """Should raise error when max minus words exceeded."""
    campaign = _make_campaign(campaign_id=1, platform="wildberries")
    executor.db._db[1] = campaign

    executor._minus_count_this_cycle = MAX_MINUS_WORDS_PER_CYCLE

    action = {
        "action_type": "minus_word",
        "reasoning": "test",
        "campaign_id": 1,
        "minus_text": "-spam",
        "decision_id": 1,
    }

    with pytest.raises(RuntimeError, match="Maximum minus words"):
        await executor.minus_word(action, campaign_id=1)


@pytest.mark.asyncio
async def test_increase_budget_within_limits(executor: ActionExecutor) -> None:
    campaign = _make_campaign(campaign_id=1, daily_budget=100.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "increase_budget",
        "reasoning": "High ROAS",
        "current_value": 100.0,
        "new_value": 120.0,
        "budget_change_percent": 20.0,
        "decision_id": 1,
    }

    applied = await executor.increase_budget(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "success"
    assert campaign.daily_budget == 120.0


@pytest.mark.asyncio
async def test_increase_budget_clamped_at_30_percent(executor: ActionExecutor) -> None:
    """Budget increase > 30% should be clamped."""
    campaign = _make_campaign(campaign_id=1, daily_budget=100.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "increase_budget",
        "reasoning": "test",
        "current_value": 100.0,
        "budget_change_percent": 50.0,
        "decision_id": 1,
    }

    applied = await executor.increase_budget(action, campaign_id=1)
    assert len(applied) == 1
    assert campaign.daily_budget <= 130.0  # 100 + 30%


@pytest.mark.asyncio
async def test_adjust_price_auto_mode(executor: ActionExecutor) -> None:
    campaign = _make_campaign(campaign_id=1)
    executor.db._db[1] = campaign

    action = {
        "action_type": "adjust_price",
        "reasoning": "Improve conversion",
        "sku": "SKU-001",
        "current_price": 999.0,
        "new_price": 899.0,
        "decision_id": 1,
    }

    executor.ozon.get_recommended_bid = AsyncMock(return_value={"bid": 5.0})

    applied = await executor.adjust_price(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "success"


@pytest.mark.asyncio
async def test_create_search_campaign_semi_auto(executor_semi_auto: ActionExecutor) -> None:
    """In semi-auto mode, campaign creation should be pending."""
    campaign = _make_campaign(campaign_id=1)
    executor_semi_auto.db._db[1] = campaign

    action = {
        "action_type": "create_search_campaign",
        "reasoning": "new opportunity",
        "parameters": {"keywords": ["keyword1", "keyword2"]},
        "decision_id": 1,
    }

    applied = await executor_semi_auto.create_search_campaign(action, campaign_id=1)
    assert len(applied) == 1
    assert applied[0].status == "pending"


@pytest.mark.asyncio
async def test_adjust_price_negative_price_rejected(executor: ActionExecutor) -> None:
    """Negative price should be rejected."""
    campaign = _make_campaign(campaign_id=1)
    executor.db._db[1] = campaign

    action = {
        "action_type": "adjust_price",
        "reasoning": "test",
        "sku": "SKU-001",
        "current_price": 500.0,
        "new_price": -100.0,
        "decision_id": 1,
    }

    with pytest.raises(ValueError, match="cannot be negative"):
        await executor.adjust_price(action, campaign_id=1)


@pytest.mark.asyncio
async def test_metrics_before_after_tracking(executor: ActionExecutor) -> None:
    """Actions should record metrics before and after."""
    campaign = _make_campaign(campaign_id=1, current_bid=10.0)
    executor.db._db[1] = campaign

    action = {
        "action_type": "raise_bid",
        "reasoning": "Good performance",
        "current_value": 10.0,
        "new_value": 11.0,
        "step_percent": 10.0,
        "decision_id": 1,
    }

    executor.wb.set_cluster_bid = AsyncMock(return_value={"result": "ok"})

    applied = await executor.raise_bid(action, campaign_id=1)
    assert applied[0].metrics_before_json == {"current_bid": 10.0, "campaign_id": 1}
    assert "new_bid" in applied[0].metrics_after_json
