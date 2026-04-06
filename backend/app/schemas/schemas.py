from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
class AccountCreate(BaseModel):
    platform: str
    name: str
    wb_token: str | None = None
    ozon_client_id: str | None = None
    ozon_client_secret: str | None = None
    is_active: bool = True


class AccountUpdate(BaseModel):
    name: str | None = None
    wb_token: str | None = None
    ozon_client_id: str | None = None
    ozon_client_secret: str | None = None
    is_active: bool | None = None


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    name: str
    is_active: bool
    wb_token: str | None = None
    ozon_client_id: str | None = None
    ozon_client_secret: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
class CampaignCreate(BaseModel):
    account_id: int
    platform_campaign_id: str | None = None
    platform: str
    campaign_type: str | None = None
    name: str
    daily_budget: float | None = None
    current_bid: float | None = None
    status: str = "active"


class CampaignUpdate(BaseModel):
    name: str | None = None
    daily_budget: float | None = None
    current_bid: float | None = None
    status: str | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    platform_campaign_id: str | None = None
    platform: str
    campaign_type: str | None = None
    status: str
    name: str
    daily_budget: float | None = None
    current_bid: float | None = None
    created_at: datetime
    updated_at: datetime

    # Latest stats (joined from campaign_stats)
    latest_ctr: float | None = None
    latest_cost: float | None = 0.0
    latest_impressions: int = 0
    latest_clicks: int = 0
    latest_orders: int = 0
    ctr_history: list[float] | None = None


class CampaignDetailResponse(CampaignResponse):
    keywords: list["KeywordResponse"] = []
    recent_stats: list["CampaignStatsResponse"] = []
    date_from: str | None = None
    date_to: str | None = None


# ---------------------------------------------------------------------------
# Keyword
# ---------------------------------------------------------------------------
class KeywordCreate(BaseModel):
    campaign_id: int
    cluster_id: str | None = None
    keyword_text: str
    status: str = "active"
    current_bid: float | None = None
    is_managed: bool = True


class KeywordUpdate(BaseModel):
    cluster_id: str | None = None
    keyword_text: str | None = None
    status: str | None = None
    current_bid: float | None = None
    is_managed: bool | None = None


class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    cluster_id: str | None = None
    keyword_text: str
    status: str
    current_bid: float | None = None
    is_managed: bool

    # Aggregated stats (computed in endpoint)
    total_impressions: int = 0
    total_clicks: int = 0
    total_ctr: float | None = None
    total_cost: float | None = None

    # Compatibility: legacy frontend reads kw.stats[0]
    stats: list[dict] = []


# ---------------------------------------------------------------------------
# KeywordStats
# ---------------------------------------------------------------------------
class KeywordStatsCreate(BaseModel):
    keyword_id: int
    date: datetime
    impressions: int = 0
    clicks: int = 0
    ctr: float | None = None
    position: float | None = None
    cost: float | None = None
    orders: int = 0
    unique_impressions_pct: float | None = None


class KeywordStatsUpdate(BaseModel):
    impressions: int | None = None
    clicks: int | None = None
    ctr: float | None = None
    position: float | None = None
    cost: float | None = None
    orders: int | None = None
    unique_impressions_pct: float | None = None


class KeywordStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword_id: int
    date: datetime
    impressions: int
    clicks: int
    ctr: float | None = None
    position: float | None = None
    cost: float | None = None
    orders: int
    unique_impressions_pct: float | None = None


# ---------------------------------------------------------------------------
# CampaignStats
# ---------------------------------------------------------------------------
class CampaignStatsCreate(BaseModel):
    campaign_id: int
    date: datetime
    total_impressions: int = 0
    total_clicks: int = 0
    total_ctr: float | None = None
    total_cost: float | None = None
    total_orders: int = 0
    search_share_pct: float | None = None


class CampaignStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    date: datetime
    total_impressions: int
    total_clicks: int
    total_ctr: float | None = None
    total_cost: float | None = None
    total_orders: int
    search_share_pct: float | None = None


# ---------------------------------------------------------------------------
# LLMDecision
# ---------------------------------------------------------------------------
class LLMDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    prompt_text: str
    llm_response: str
    llm_provider: str
    llm_model: str
    actions_json: dict[str, Any]
    status: str
    created_at: datetime
    actions: list["AppliedActionResponse"] = []


# ---------------------------------------------------------------------------
# AppliedAction
# ---------------------------------------------------------------------------
class AppliedActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    action_type: str
    parameters_json: dict[str, Any]
    metrics_before_json: dict[str, Any] | None = None
    metrics_after_json: dict[str, Any] | None = None
    status: str
    applied_at: datetime | None = None
    result_checked_at: datetime | None = None


# ---------------------------------------------------------------------------
# OptimizationRule
# ---------------------------------------------------------------------------
class OptimizationRuleCreate(BaseModel):
    platform: str
    rule_name: str
    rule_description: str | None = None
    rule_params_json: dict[str, Any]
    is_active: bool = True


class OptimizationRuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_description: str | None = None
    rule_params_json: dict[str, Any] | None = None
    is_active: bool | None = None


class OptimizationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    rule_name: str
    rule_description: str | None = None
    rule_params_json: dict[str, Any]
    is_active: bool


# ---------------------------------------------------------------------------
# LLM Action schemas
# ---------------------------------------------------------------------------
VALID_ACTION_TYPES = {
    "raise_bid",
    "lower_bid",
    "minus_word",
    "increase_budget",
    "create_search_campaign",
    "adjust_price",
}


class LLMAction(BaseModel):
    action_type: str = Field(..., description=f"Must be one of {VALID_ACTION_TYPES}")
    reasoning: str = Field(..., description="Why this action is recommended")
    keyword_id: int | None = None
    keyword_text: str | None = None
    current_value: float | None = None
    new_value: float | None = None
    step_percent: float | None = None
    minus_text: str | None = None
    campaign_id: int | None = None
    budget_change_percent: float | None = None
    parameters: dict[str, Any] = {}

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.action_type not in VALID_ACTION_TYPES:
            errors.append(
                f"Invalid action_type '{self.action_type}'. Must be one of {VALID_ACTION_TYPES}"
            )
        if self.new_value is not None and self.new_value < 0:
            errors.append("new_value cannot be negative")
        if self.current_value is not None and self.current_value < 0:
            errors.append("current_value cannot be negative")
        if self.step_percent is not None and (self.step_percent < 0 or self.step_percent > 20):
            errors.append("step_percent must be between 0 and 20 (max 20% per cycle)")
        if self.budget_change_percent is not None and (
            self.budget_change_percent < 0 or self.budget_change_percent > 30
        ):
            errors.append("budget_change_percent must be between 0 and 30 (max 30%)")
        if self.minus_text and self.action_type == "minus_word":
            pass  # WB-specific, validated at executor level
        return errors
