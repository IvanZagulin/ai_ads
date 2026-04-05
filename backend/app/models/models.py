from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Account(BaseModel):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    wb_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    ozon_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ozon_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign", back_populates="account", lazy="selectin"
    )


class Campaign(BaseModel):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=False
    )
    platform_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    campaign_type: Mapped[str] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    daily_budget: Mapped[float | None] = mapped_column(Double, nullable=True)
    current_bid: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    account: Mapped["Account"] = relationship("Account", back_populates="campaigns")
    keywords: Mapped[list["Keyword"]] = relationship(
        "Keyword", back_populates="campaign", lazy="selectin"
    )
    stats: Mapped[list["CampaignStats"]] = relationship(
        "CampaignStats", back_populates="campaign", lazy="selectin"
    )
    llm_decisions: Mapped[list["LLMDecision"]] = relationship(
        "LLMDecision", back_populates="campaign", lazy="selectin"
    )


class Keyword(BaseModel):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id"), nullable=False
    )
    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keyword_text: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    current_bid: Mapped[float | None] = mapped_column(Double, nullable=True)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="keywords")
    stats: Mapped[list["KeywordStats"]] = relationship(
        "KeywordStats", back_populates="keyword", lazy="selectin"
    )


class KeywordStats(BaseModel):
    __tablename__ = "keyword_stats"
    __table_args__ = (UniqueConstraint("keyword_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("keywords.id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    ctr: Mapped[float | None] = mapped_column(Double, nullable=True)
    position: Mapped[float | None] = mapped_column(Double, nullable=True)
    cost: Mapped[float | None] = mapped_column(Double, nullable=True)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_impressions_pct: Mapped[float | None] = mapped_column(Double, nullable=True)

    keyword: Mapped["Keyword"] = relationship("Keyword", back_populates="stats")


class CampaignStats(BaseModel):
    __tablename__ = "campaign_stats"
    __table_args__ = (UniqueConstraint("campaign_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    total_impressions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_clicks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_ctr: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    search_share_pct: Mapped[float | None] = mapped_column(Double, nullable=True)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="stats")


class LLMDecision(BaseModel):
    __tablename__ = "llm_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id"), nullable=False
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    llm_response: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(100), default="claude", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    actions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="llm_decisions")
    actions: Mapped[list["AppliedAction"]] = relationship(
        "AppliedAction", back_populates="decision", lazy="selectin"
    )


class AppliedAction(BaseModel):
    __tablename__ = "applied_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_decisions.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metrics_after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    decision: Mapped["LLMDecision"] = relationship("LLMDecision", back_populates="actions")


class OptimizationRule(BaseModel):
    __tablename__ = "optimization_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_description: Mapped[str] = mapped_column(Text, nullable=True)
    rule_params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
