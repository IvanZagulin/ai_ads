from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from celery import group
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.ozon_client import OzonPerformanceClient
from app.clients.wb_client import WBPromotionClient
from app.config import settings
from app.database import async_session_factory
from app.executor.action_executor import ActionExecutor
from app.llm.analyzer import LLMAnalyzer
from app.llm.client import LLMClient
from app.models.models import (
    Account,
    Campaign,
    CampaignStats,
    Keyword,
    KeywordStats,
    LLMDecision,
    OptimizationRule,
)
from app.tasks.celery_app import celery_app
from app.utils.encryption import decrypt_token

logger = logging.getLogger(__name__)


class OptimizationOrchestrator:
    """Orchestrates one complete optimization cycle: gather data -> LLM analyze -> execute."""

    # Max concurrent LLM calls (avoid rate limits)
    SEMAPHORE = asyncio.Semaphore(10)

    def __init__(self) -> None:
        self.llm_analyzer = LLMAnalyzer(llm_client=LLMClient())
        self._wb_clients: dict[int, WBPromotionClient] = {}
        self._ozon_clients: dict[int, OzonPerformanceClient] = {}

    async def _get_api_clients(
        self, account: Account
    ) -> tuple[WBPromotionClient | None, OzonPerformanceClient | None]:
        """Get cached or new API clients for an account."""
        wb_client = self._wb_clients.get(account.id)
        ozon_client = self._ozon_clients.get(account.id)

        if wb_client is None and account.platform == "wildberries" and account.wb_token:
            token = decrypt_token(account.wb_token)
            wb_client = WBPromotionClient(api_token=token)
            self._wb_clients[account.id] = wb_client

        if ozon_client is None and account.platform == "ozon" and account.ozon_client_secret:
            secret = decrypt_token(account.ozon_client_secret)
            ozon_client = OzonPerformanceClient(
                client_id=account.ozon_client_id or "",
                client_secret=secret,
            )
            self._ozon_clients[account.id] = ozon_client

        return wb_client, ozon_client

    async def _gather_campaign_context(
        self, session: AsyncSession, campaign: Campaign
    ) -> dict[str, Any]:
        """Build a rich context dict for a single campaign."""
        context: dict[str, Any] = {
            "id": campaign.id,
            "name": campaign.name,
            "platform": campaign.platform,
            "campaign_type": campaign.campaign_type,
            "status": campaign.status,
            "daily_budget": campaign.daily_budget,
            "current_bid": campaign.current_bid,
            "platform_campaign_id": campaign.platform_campaign_id,
        }

        recent_stats_stmt = (
            select(CampaignStats)
            .where(CampaignStats.campaign_id == campaign.id)
            .order_by(CampaignStats.date.desc())
            .limit(14)
        )
        stats_result = await session.execute(recent_stats_stmt)
        stats_records = list(stats_result.scalars().all())

        context["recent_stats"] = [
            {
                "date": s.date.isoformat(),
                "impressions": s.total_impressions,
                "clicks": s.total_clicks,
                "ctr": s.total_ctr,
                "cost": s.total_cost,
                "orders": s.total_orders,
                "search_share_pct": s.search_share_pct,
            }
            for s in reversed(stats_records)
        ]

        keywords_stmt = select(Keyword).where(Keyword.campaign_id == campaign.id)
        kw_result = await session.execute(keywords_stmt)
        keywords = list(kw_result.scalars().all())

        context["keywords"] = []
        for kw in keywords:
            kw_stats_stmt = (
                select(KeywordStats)
                .where(KeywordStats.keyword_id == kw.id)
                .order_by(KeywordStats.date.desc())
                .limit(7)
            )
            kw_stats_result = await session.execute(kw_stats_stmt)
            kw_stats = list(kw_stats_result.scalars().all())

            context["keywords"].append({
                "id": kw.id,
                "text": kw.keyword_text,
                "current_bid": kw.current_bid,
                "status": kw.status,
                "recent_stats": [
                    {
                        "date": s.date.isoformat(),
                        "impressions": s.impressions,
                        "clicks": s.clicks,
                        "ctr": s.ctr,
                        "position": s.position,
                        "cost": s.cost,
                        "orders": s.orders,
                    }
                    for s in reversed(kw_stats)
                ],
            })

        return context

    async def _get_active_rules(self, session: AsyncSession, platform: str) -> list[dict[str, Any]]:
        """Fetch active optimization rules for a platform."""
        stmt = select(OptimizationRule).where(
            OptimizationRule.platform == platform,
            OptimizationRule.is_active.is_(True),
        )
        result = await session.execute(stmt)
        rules = list(result.scalars().all())
        return [
            {
                "rule_name": r.rule_name,
                "rule_description": r.rule_description,
                "rule_params_json": r.rule_params_json,
            }
            for r in rules
        ]

    async def _get_decision_history(
        self, session: AsyncSession, campaign_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Fetch recent LLM decision history for a campaign."""
        stmt = (
            select(LLMDecision)
            .where(LLMDecision.campaign_id == campaign_id)
            .order_by(LLMDecision.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        decisions = list(result.scalars().all())

        history: list[dict[str, Any]] = []
        for d in decisions:
            actions_info = []
            for action in d.actions:
                actions_info.append({
                    "action_type": action.action_type,
                    "parameters": action.parameters_json,
                    "status": action.status,
                    "metrics_after": action.metrics_after_json,
                })
            history.append({
                "decision_id": d.id,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
                "actions": actions_info,
            })
        return history

    async def _save_llm_decision(
        self,
        session: AsyncSession,
        campaign_id: int,
        prompt_text: str,
        llm_response: dict[str, Any],
        actions: list[dict[str, Any]],
    ) -> LLMDecision:
        """Persist an LLM decision to the database."""
        decision = LLMDecision(
            campaign_id=campaign_id,
            prompt_text=prompt_text,
            llm_response=str(llm_response),
            llm_provider="claude",
            llm_model=settings.CLAUDE_MODEL,
            actions_json={"actions": actions},
            status="executed" if settings.AUTO_MODE else "pending",
        )
        session.add(decision)
        await session.flush()
        return decision

    async def _process_single_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Process one campaign with its own isolated DB session and semaphore."""
        async with self.SEMAPHORE:
            async with async_session_factory() as session:
                try:
                    campaign = await session.get(Campaign, campaign_id)
                    if campaign is None:
                        return {"status": "skipped", "campaign_id": campaign_id, "reason": "campaign not found"}

                    account = await session.get(Account, campaign.account_id)
                    if account is None:
                        return {"status": "skipped", "campaign_id": campaign_id, "reason": "account not found"}

                    wb_client, ozon_client = await self._get_api_clients(account)
                    context = await self._gather_campaign_context(session, campaign)
                    rules = await self._get_active_rules(session, campaign.platform)
                    history = await self._get_decision_history(session, campaign.id)

                    actions = await self.llm_analyzer.analyze_campaign(
                        campaign_data=context,
                        rules=rules,
                        history=history,
                        platform=campaign.platform,
                    )

                    if not actions:
                        return {"status": "no_actions", "campaign_id": campaign_id}

                    decision = await self._save_llm_decision(
                        session, campaign.id, str(context), {"actions": actions}, actions
                    )
                    await session.commit()

                    if settings.AUTO_MODE and actions:
                        executor = ActionExecutor(
                            db_session=session,
                            wb_client=wb_client or WBPromotionClient(api_token=""),
                            ozon_client=ozon_client or OzonPerformanceClient(client_id="", client_secret=""),
                            auto_mode=True,
                        )
                        applied_actions = await executor.execute_decision(decision.id)
                        await session.commit()
                        return {
                            "status": "executed",
                            "campaign_id": campaign.id,
                            "decision_id": decision.id,
                            "actions_count": len(actions),
                            "applied_count": len(applied_actions),
                        }
                    else:
                        return {
                            "status": "pending_review",
                            "campaign_id": campaign.id,
                            "decision_id": decision.id,
                            "actions_count": len(actions),
                        }
                except Exception as exc:
                    logger.error(
                        "Optimization failed for campaign %d: %s", campaign_id, exc
                    )
                    return {"status": "error", "campaign_id": campaign_id, "error": str(exc)}

    async def run_single_campaign(
        self, session: AsyncSession, campaign: Campaign
    ) -> dict[str, Any]:
        """Run the full optimization pipeline for a single campaign."""
        account = await session.get(Account, campaign.account_id)
        if account is None:
            return {"status": "skipped", "reason": "account not found"}

        wb_client, ozon_client = await self._get_api_clients(account)

        context = await self._gather_campaign_context(session, campaign)
        rules = await self._get_active_rules(session, campaign.platform)
        history = await self._get_decision_history(session, campaign.id)

        actions = await self.llm_analyzer.analyze_campaign(
            campaign_data=context,
            rules=rules,
            history=history,
            platform=campaign.platform,
        )

        if not actions:
            return {"status": "no_actions", "campaign_id": campaign.id}

        decision = await self._save_llm_decision(
            session, campaign.id, str(context), {"actions": actions}, actions
        )

        if settings.AUTO_MODE and actions:
            executor = ActionExecutor(
                db_session=session,
                wb_client=wb_client or WBPromotionClient(api_token=""),
                ozon_client=ozon_client or OzonPerformanceClient(client_id="", client_secret=""),
                auto_mode=True,
            )
            applied_actions = await executor.execute_decision(decision.id)
            return {
                "status": "executed",
                "campaign_id": campaign.id,
                "decision_id": decision.id,
                "actions_count": len(actions),
                "applied_count": len(applied_actions),
            }
        else:
            return {
                "status": "pending_review",
                "campaign_id": campaign.id,
                "decision_id": decision.id,
                "actions_count": len(actions),
            }

    async def run_full_cycle(self) -> dict[str, Any]:
        """Run optimization for all active campaigns across all accounts, in parallel."""
        logger.info("Starting full optimization cycle")

        # First, collect all active campaign IDs
        async with async_session_factory() as session:
            campaigns_stmt = (
                select(Campaign.id).where(Campaign.status == "active")
            )
            campaigns_result = await session.execute(campaigns_stmt)
            campaign_ids = [row[0] for row in campaigns_result.all()]

        logger.info("Found %d active campaigns to optimize", len(campaign_ids))

        if not campaign_ids:
            logger.info("No active campaigns found")
            return {}

        # Process all campaigns in parallel with their own sessions and semaphore
        tasks = [
            self._process_single_campaign(cid)
            for cid in campaign_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed: list[dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append({
                    "status": "error",
                    "campaign_id": campaign_ids[i],
                    "error": str(r),
                })
            else:
                processed.append(r)

        logger.info("Optimization cycle complete: %d campaigns processed", len(campaign_ids))
        return {"campaigns": processed}


@celery_app.task(name="app.tasks.optimization_cycle.run_optimization_cycle")
async def run_optimization_cycle() -> dict[str, Any]:
    """Celery task: run the full optimization cycle."""
    orchestrator = OptimizationOrchestrator()
    return await orchestrator.run_full_cycle()
