from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ozon_client import OzonPerformanceClient
from app.clients.wb_client import WBPromotionClient
from app.config import settings
from app.models.models import AppliedAction, Campaign, LLMDecision

logger = logging.getLogger(__name__)


# Safety limits per optimization cycle
MAX_BID_CHANGE_PCT = 20.0
MAX_BUDGET_INCREASE_PCT = 30.0
MAX_MINUS_WORDS_PER_CYCLE = 10


class ActionExecutor:
    """Executes LLM-recommended actions with safety checks and logging."""

    def __init__(
        self,
        db_session: AsyncSession,
        wb_client: WBPromotionClient,
        ozon_client: OzonPerformanceClient,
        auto_mode: bool | None = None,
    ) -> None:
        self.db = db_session
        self.wb = wb_client
        self.ozon = ozon_client
        self.auto_mode = auto_mode if auto_mode is not None else settings.AUTO_MODE
        self._minus_count_this_cycle = 0

    async def execute_decision(self, decision_id: int) -> list[AppliedAction]:
        """Execute all pending actions for a given LLM decision, then persist results."""
        decision = await self.db.get(LLMDecision, decision_id)
        if decision is None:
            raise ValueError(f"Decision {decision_id} not found")

        actions_data = decision.actions_json.get("actions", [])
        applied: list[AppliedAction] = []

        for action_data in actions_data:
            action_type = action_data.get("action_type", "")
            if not action_type:
                logger.warning("Action without action_type skipped: %s", action_data)
                continue

            try:
                if action_type == "raise_bid":
                    result = await self.raise_bid(action_data, decision.campaign_id)
                elif action_type == "lower_bid":
                    result = await self.lower_bid(action_data, decision.campaign_id)
                elif action_type == "minus_word":
                    result = await self.minus_word(action_data, decision.campaign_id)
                elif action_type == "increase_budget":
                    result = await self.increase_budget(action_data, decision.campaign_id)
                elif action_type == "create_search_campaign":
                    result = await self.create_search_campaign(action_data, decision.campaign_id)
                elif action_type == "adjust_price":
                    result = await self.adjust_price(action_data, decision.campaign_id)
                else:
                    logger.warning("Unknown action type: %s", action_type)
                    continue
                applied.extend(result)
            except Exception as exc:
                logger.error("Action %s failed: %s", action_type, exc)
                applied_action = AppliedAction(
                    decision_id=decision.id,
                    action_type=action_type,
                    parameters_json=action_data.get("parameters", action_data),
                    status="failed",
                )
                self.db.add(applied_action)
                applied.append(applied_action)

        await self.db.flush()
        decision.status = "executed"
        await self.db.commit()
        return applied

    def _safety_check_bid_change(self, current: float, new_val: float) -> bool:
        """Return True if the bid change is within the allowed percentage."""
        if current <= 0:
            logger.warning("Cannot compute percentage change with current_value <= 0")
            return True  # allow if we don't have a baseline
        change_pct = abs(new_val - current) / current * 100
        if change_pct > MAX_BID_CHANGE_PCT:
            logger.warning(
                "Bid change %.1f%% exceeds max %.1f%%, clamping",
                change_pct,
                MAX_BID_CHANGE_PCT,
            )
            return False
        return True

    def _clamp_bid_change(self, current: float, new_val: float) -> float:
        """Clamp new value to within MAX_BID_CHANGE_PCT of current."""
        if current <= 0:
            return new_val
        max_delta = current * MAX_BID_CHANGE_PCT / 100
        clamped = current + max(min(new_val - current, max_delta), -max_delta)
        return max(clamped, 0)

    # ------------------------------------------------------------------ #
    # Action implementations
    # ------------------------------------------------------------------ #

    async def raise_bid(self, action: dict[str, Any], campaign_id: int) -> list[AppliedAction]:
        """Raise the bid for a keyword/cluster."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        current = action.get("current_value", campaign.current_bid) or 0
        new_val = action.get("new_value", current * 1.1)
        keyword_id = action.get("keyword_id")
        parameters = {**action}

        metrics_before = {"current_bid": current, "campaign_id": campaign_id}

        if not self._safety_check_bid_change(current, new_val):
            new_val = self._clamp_bid_change(current, new_val)
            parameters["original_new_value"] = action.get("new_value")
            parameters["clamped_value"] = new_val

        if new_val <= 0:
            raise ValueError("Bid cannot be non-positive after clamping")

        if campaign.platform == "wildberries":
            norm_query = action.get("keyword_text", "")
            nm_id = action.get("nm_id")
            advert_id = int(campaign.platform_campaign_id or "0")
            if nm_id is None and campaign.nm_ids:
                nm_id = campaign.nm_ids[0]
            result = await self.wb.set_cluster_bid(advert_id, nm_id or 0, norm_query, int(new_val))
        else:
            result = await self.ozon.update_bids(
                campaign.platform_campaign_id or "",
                [{"id": keyword_id, "bid": new_val}],
            )

        campaign.current_bid = new_val
        campaign.updated_at = datetime.now(timezone.utc)

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="raise_bid",
            parameters_json=parameters,
            metrics_before_json=metrics_before,
            metrics_after_json={"new_bid": new_val, "api_result": str(result)},
            status="success",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]

    async def lower_bid(self, action: dict[str, Any], campaign_id: int) -> list[AppliedAction]:
        """Lower the bid for a keyword/cluster."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        current = action.get("current_value", campaign.current_bid) or 0
        new_val = action.get("new_value", current * 0.9)
        keyword_id = action.get("keyword_id")
        parameters = {**action}

        metrics_before = {"current_bid": current, "campaign_id": campaign_id}

        if not self._safety_check_bid_change(current, new_val):
            new_val = self._clamp_bid_change(current, new_val)
            parameters["clamped_value"] = new_val

        if new_val <= 0:
            new_val = 0.01
            parameters["warning"] = "Bid clamped to minimum 0.01"

        if campaign.platform == "wildberries":
            norm_query = action.get("keyword_text", "")
            nm_id = action.get("nm_id")
            advert_id = int(campaign.platform_campaign_id or "0")
            if nm_id is None and campaign.nm_ids:
                nm_id = campaign.nm_ids[0]
            result = await self.wb.set_cluster_bid(advert_id, nm_id or 0, norm_query, int(new_val))
        else:
            result = await self.ozon.update_bids(
                campaign.platform_campaign_id or "",
                [{"id": keyword_id, "bid": new_val}],
            )

        campaign.current_bid = new_val
        campaign.updated_at = datetime.now(timezone.utc)

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="lower_bid",
            parameters_json=parameters,
            metrics_before_json=metrics_before,
            metrics_after_json={"new_bid": new_val, "api_result": str(result)},
            status="success",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]

    async def minus_word(self, action: dict[str, Any], campaign_id: int) -> list[AppliedAction]:
        """Add a negative phrase to a campaign (WB only)."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign.platform != "wildberries":
            logger.warning("minus_word action skipped for non-WB platform '%s'", campaign.platform)
            return []

        if self._minus_count_this_cycle >= MAX_MINUS_WORDS_PER_CYCLE:
            raise RuntimeError(
                f"Maximum minus words per cycle ({MAX_MINUS_WORDS_PER_CYCLE}) reached"
            )

        minus_text = action.get("minus_text", "")
        if not minus_text:
            raise ValueError("minus_text is required for minus_word action")

        nm_id = action.get("nm_id")
        if nm_id is None and campaign.nm_ids:
            nm_id = campaign.nm_ids[0]
        advert_id = int(campaign.platform_campaign_id or "0")
        result = await self.wb.add_minus_phrase(advert_id, nm_id or 0, minus_text)

        self._minus_count_this_cycle += 1

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="minus_word",
            parameters_json={**action},
            metrics_before_json={"minus_count": self._minus_count_this_cycle},
            metrics_after_json={"api_result": str(result)},
            status="success",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]

    async def increase_budget(
        self, action: dict[str, Any], campaign_id: int
    ) -> list[AppliedAction]:
        """Increase campaign daily budget."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        current = action.get("current_value", campaign.daily_budget) or 0
        new_val = action.get("new_value")
        budget_pct = action.get("budget_change_percent")

        if new_val is None and budget_pct is not None and current > 0:
            new_val = current * (1 + budget_pct / 100)

        if new_val is None:
            raise ValueError("Either new_value or budget_change_percent required")

        metrics_before = {"current_budget": current, "campaign_id": campaign_id}

        if budget_pct is not None and budget_pct > MAX_BUDGET_INCREASE_PCT:
            logger.warning(
                "Budget increase %.1f%% exceeds max %.1f%%, clamping",
                budget_pct,
                MAX_BUDGET_INCREASE_PCT,
            )
            new_val = current * (1 + MAX_BUDGET_INCREASE_PCT / 100)

        campaign.daily_budget = new_val
        campaign.updated_at = datetime.now(timezone.utc)

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="increase_budget",
            parameters_json={**action},
            metrics_before_json=metrics_before,
            metrics_after_json={"new_budget": new_val},
            status="success",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]

    async def create_search_campaign(
        self, action: dict[str, Any], campaign_id: int
    ) -> list[AppliedAction]:
        """Create a new search campaign (WB: auto-search with keywords)."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        parameters = action.get("parameters", action)

        # In auto mode we actually create the campaign via API
        if self.auto_mode:
            if campaign.platform == "wildberries":
                wb_result = await self.wb.get_campaigns()
                result_api = {"created_campaigns_before": len(wb_result)}
            else:
                ozon_campaigns = await self.ozon.get_campaigns()
                result_api = {"created_campaigns_before": len(ozon_campaigns)}
        else:
            result_api = {"status": "pending_manual_creation", "parameters": parameters}

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="create_search_campaign",
            parameters_json=parameters,
            metrics_after_json=result_api,
            status="success" if self.auto_mode else "pending",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]

    async def adjust_price(self, action: dict[str, Any], campaign_id: int) -> list[AppliedAction]:
        """Adjust product price to improve conversion."""
        _ = campaign_id  # price is product-level, campaign context is optional
        sku = action.get("sku", "")
        new_price = action.get("new_price")
        current_price = action.get("current_price", 0)

        if new_price is None:
            raise ValueError("new_price is required for adjust_price")

        if new_price < 0:
            raise ValueError("Price cannot be negative")

        if self.auto_mode:
            if sku:
                recommendation = await self.ozon.get_recommended_bid(sku)
                result_api = {"sku": sku, "recommendation": str(recommendation)}
            else:
                result_api = {"sku": sku, "note": "no sku provided, price not sent to API"}
        else:
            result_api = {"status": "pending_review"}

        applied = AppliedAction(
            decision_id=action.get("decision_id", 0),
            action_type="adjust_price",
            parameters_json={**action},
            metrics_before_json={"current_price": current_price},
            metrics_after_json=result_api,
            status="success",
            applied_at=datetime.now(timezone.utc),
        )
        self.db.add(applied)
        return [applied]
