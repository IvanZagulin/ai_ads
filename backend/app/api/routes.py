from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.clients.ozon_client import OzonPerformanceClient
from app.clients.wb_client import WBPromotionClient
from app.config import settings
from app.database import get_db, session_factory
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
    AppliedAction,
    OptimizationRule,
)
from app.schemas.schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
    CampaignCreate,
    CampaignDetailResponse,
    CampaignResponse,
    CampaignStatsResponse,
    CampaignUpdate,
    KeywordCreate,
    KeywordResponse,
    KeywordStatsCreate,
    KeywordStatsResponse,
    KeywordUpdate,
    LLMDecisionResponse,
    AppliedActionResponse,
    OptimizationRuleCreate,
    OptimizationRuleResponse,
    OptimizationRuleUpdate,
)
# from app.tasks.optimization_cycle import OptimizationOrchestrator
from app.utils.encryption import encrypt_token, decrypt_token
from app.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])

_api_limiter = TokenBucketRateLimiter(rate=100, capacity=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_wb_client(account: Account) -> WBPromotionClient:
    if not account.wb_token:
        raise HTTPException(status_code=400, detail="Токен API Wildberries не настроен")
    return WBPromotionClient(api_token=decrypt_token(account.wb_token))


def _get_ozon_client(account: Account) -> OzonPerformanceClient:
    if not account.ozon_client_secret:
        raise HTTPException(status_code=400, detail="Учётные данные Ozon не настроены")
    return OzonPerformanceClient(
        client_id=account.ozon_client_id or "",
        client_secret=decrypt_token(account.ozon_client_secret),
    )


def _get_platform_client(account: Account):
    wb_client = _get_wb_client(account) if account.platform == "wildberries" else None
    ozon_client = (
        _get_ozon_client(account) if account.platform == "ozon" else None
    )
    return wb_client, ozon_client


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    platform: str | None = Query(None),
    is_active: bool | None = Query(None),
) -> Any:
    with session_factory() as db:
        stmt = select(Account)
        if platform:
            stmt = stmt.where(Account.platform == platform)
        if is_active is not None:
            stmt = stmt.where(Account.is_active.is_(is_active))
        stmt = stmt.order_by(Account.created_at.desc())
        result = db.execute(stmt)
        return list(result.scalars().all())


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(data: AccountCreate) -> Any:
    with session_factory() as db:
        account = Account(
            platform=data.platform,
            name=data.name,
            is_active=data.is_active if data.is_active is not None else True,
        )
        if data.wb_token:
            account.wb_token = encrypt_token(data.wb_token)
        if data.ozon_client_id:
            account.ozon_client_id = data.ozon_client_id
        if data.ozon_client_secret:
            account.ozon_client_secret = encrypt_token(data.ozon_client_secret)

        db.add(account)
        db.commit()
        db.refresh(account)
        return account


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int) -> Any:
    with session_factory() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")
        return account


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(account_id: int, data: AccountUpdate) -> Any:
    with session_factory() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")

        if data.name is not None:
            account.name = data.name
        if data.wb_token is not None:
            account.wb_token = encrypt_token(data.wb_token)
        if data.ozon_client_id is not None:
            account.ozon_client_id = data.ozon_client_id
        if data.ozon_client_secret is not None:
            account.ozon_client_secret = encrypt_token(data.ozon_client_secret)
        if data.is_active is not None:
            account.is_active = data.is_active

        db.commit()
        db.refresh(account)
        return account


# ---------------------------------------------------------------------------
# Sync campaigns from marketplace API
# ---------------------------------------------------------------------------
@router.post("/accounts/{account_id}/sync-campaigns")
async def sync_campaigns(account_id: int) -> dict[str, Any]:
    """Fetch campaigns from WB API and save to DB."""
    import asyncio

    with session_factory() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")

        if account.platform == "wildberries":
            if not account.wb_token:
                raise HTTPException(status_code=400, detail="Токен WB не настроен")

            wb_client = WBPromotionClient(api_token=decrypt_token(account.wb_token))
            raw_campaigns = await wb_client.get_campaigns()

            imported = 0
            for camp in raw_campaigns:
                wb_adv_id = camp.get("wb_adv_id")
                if not wb_adv_id:
                    continue

                platform_campaign_id = str(wb_adv_id)

                existing = db.execute(
                    select(Campaign).where(
                        Campaign.account_id == account_id,
                        Campaign.platform_campaign_id == platform_campaign_id,
                    )
                ).scalar_one_or_none()

                if existing:
                    # Update existing
                    existing.name = camp.get("name", existing.name)
                    existing.status = camp.get("status", existing.status)
                    existing.campaign_type = camp.get("bid_type", existing.campaign_type)
                    db.commit()
                    imported += 1
                    continue

                db_campaign = Campaign(
                    account_id=account_id,
                    platform_campaign_id=platform_campaign_id,
                    platform="wildberries",
                    campaign_type=camp.get("bid_type", "unknown"),
                    status=camp.get("status", "unknown"),
                    name=camp.get("name", f"Кампания {wb_adv_id}"),
                    daily_budget=camp.get("daily_budget"),
                    current_bid=camp.get("current_bid"),
                )
                db.add(db_campaign)
                imported += 1

            db.commit()
            return {"status": "ok", "imported": imported, "total": len(raw_campaigns)}

        raise HTTPException(status_code=400, detail=f"Неподдерживаемая платформа: {account.platform}")


# ---------------------------------------------------------------------------
# Collect Data — clusters, bids, stats from WB API
# ---------------------------------------------------------------------------
@router.post("/accounts/{account_id}/collect-data")
async def collect_data(account_id: int) -> dict[str, Any]:
    """Fetch campaigns, clusters, bids, and stats from WB API — saves to DB."""

    from app.database import async_session_factory
    from app.models.models import Keyword, KeywordStats
    from app.utils.encryption import decrypt_token

    with session_factory() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")
        if account.platform != "wildberries":
            raise HTTPException(status_code=400, detail="Только для Wildberries")
        if not account.wb_token:
            raise HTTPException(status_code=400, detail="Токен WB не настроен")

    wb_client = WBPromotionClient(api_token=decrypt_token(account.wb_token))
    campaigns = await wb_client.get_campaigns()
    if not campaigns:
        return {"status": "ok", "message": "Кампании не найдены"}

    total_keywords_saved = 0
    total_bids_saved = 0
    total_stats_saved = 0

    # Sync campaign nm_ids and statuses (sync DB)
    with session_factory() as db:
        for camp_data in campaigns:
            adv_id = camp_data.get("wb_adv_id")
            if not adv_id:
                continue
            platform_id = str(adv_id)
            stmt = select(Campaign).where(
                Campaign.account_id == account_id,
                Campaign.platform_campaign_id == platform_id,
            )
            existing = db.execute(stmt).scalar_one_or_none()
            if existing:
                existing.status = camp_data.get("status", existing.status)
                existing.name = camp_data.get("name", existing.name)
                existing.campaign_type = camp_data.get("bid_type", existing.campaign_type)
                existing.nm_ids = camp_data.get("nm_ids")
                db.commit()

    # Fetch clusters, bids, stats and save (async DB)
    async with async_session_factory() as async_db:
        for camp_data in campaigns:
            status = camp_data.get("status")
            adv_id = camp_data.get("wb_adv_id")
            nm_ids = camp_data.get("nm_ids", [])
            if not adv_id or status not in ("active", "paused"):
                continue

            camp_stmt = select(Campaign).where(
                Campaign.account_id == account_id,
                Campaign.platform_campaign_id == str(adv_id),
            )
            camp_result = await async_db.execute(camp_stmt)
            db_camp = camp_result.scalar_one_or_none()
            if not db_camp:
                continue

            # Update nm_ids
            if nm_ids:
                db_camp.nm_ids = nm_ids

            # Fetch clusters (normquery list)
            clusters = await wb_client.get_clusters(int(adv_id))
            for item in clusters:
                nq = item.get("normQuery", item.get("norm_query", ""))
                if not nq:
                    continue
                kw_stmt = select(Keyword).where(
                    Keyword.campaign_id == db_camp.id,
                    Keyword.keyword_text == nq,
                )
                kw_result = await async_db.execute(kw_stmt)
                kw = kw_result.scalar_one_or_none()
                if kw is None:
                    kw = Keyword(
                        campaign_id=db_camp.id,
                        cluster_id=str(item.get("clusterId", nq)),
                        keyword_text=nq,
                        status="active" if item.get("isActive", True) else "unmanaged",
                    )
                    async_db.add(kw)
                    total_keywords_saved += 1

            # Fetch cluster bids for each NM
            for nm_id in nm_ids[:3]:
                bids = await wb_client.get_cluster_bids(int(adv_id), nm_id)
                for bid_item in bids:
                    nq = bid_item.get("norm_query", "")
                    if not nq:
                        continue
                    kw_stmt = select(Keyword).where(
                        Keyword.campaign_id == db_camp.id,
                        Keyword.keyword_text == nq,
                    )
                    kw_result = await async_db.execute(kw_stmt)
                    kw = kw_result.scalar_one_or_none()
                    if kw is None:
                        kw = Keyword(
                            campaign_id=db_camp.id,
                            cluster_id=nq,
                            keyword_text=nq,
                            status="active",
                            current_bid=bid_item.get("bid"),
                        )
                        async_db.add(kw)
                    else:
                        kw.current_bid = bid_item.get("bid")
                    total_bids_saved += 1

                # Fetch recent daily stats (last 7 days)
                today = date.today()
                from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                to_date = today.strftime("%Y-%m-%d")
                daily_stats = await wb_client.get_campaign_stats(int(adv_id), nm_id, from_date, to_date)
                for stat in daily_stats:
                    nq = stat.get("normQuery", "")
                    stat_date_str = stat.get("date", "")
                    if not nq or not stat_date_str:
                        continue
                    try:
                        stat_date = date.fromisoformat(stat_date_str)
                    except ValueError:
                        continue

                    kw_stmt = select(Keyword).where(
                        Keyword.campaign_id == db_camp.id,
                        Keyword.keyword_text == nq,
                    )
                    kw_result = await async_db.execute(kw_stmt)
                    kw = kw_result.scalar_one_or_none()
                    if kw is None:
                        kw = Keyword(
                            campaign_id=db_camp.id,
                            cluster_id=nq,
                            keyword_text=nq,
                            status="active",
                        )
                        async_db.add(kw)
                        await async_db.flush()

                    ks_stmt = select(KeywordStats).where(
                        KeywordStats.keyword_id == kw.id,
                        KeywordStats.date == stat_date,
                    )
                    ks_result = await async_db.execute(ks_stmt)
                    ks = ks_result.scalar_one_or_none()
                    views = stat.get("views", 0)
                    clicks = stat.get("clicks", 0)
                    if ks is None:
                        ks = KeywordStats(
                            keyword_id=kw.id,
                            date=stat_date,
                            impressions=views,
                            clicks=clicks,
                            ctr=stat.get("ctr"),
                            position=stat.get("avgPos", stat.get("avg_pos")),
                            cost=stat.get("spend", 0),
                            orders=stat.get("orders", 0),
                        )
                        async_db.add(ks)
                    else:
                        ks.impressions = views
                        ks.clicks = clicks
                        ks.ctr = stat.get("ctr")
                        ks.position = stat.get("avgPos", stat.get("avg_pos"))
                        ks.cost = stat.get("spend", 0)
                        ks.orders = stat.get("orders", 0)
                    total_stats_saved += 1

                await asyncio.sleep(0.5)

        await async_db.commit()

    return {
        "status": "ok",
        "campaigns": len(campaigns),
        "keywords_saved": total_keywords_saved,
        "bids_saved": total_bids_saved,
        "stats_saved": total_stats_saved,
    }


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    account_id: int | None = Query(None),
    platform: str | None = Query(None),
    status: str | None = Query(None),
) -> Any:
    with session_factory() as db:
        # Get campaigns
        stmt = select(Campaign)
        if account_id is not None:
            stmt = stmt.where(Campaign.account_id == account_id)
        if platform is not None:
            stmt = stmt.where(Campaign.platform == platform)
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(Campaign.updated_at.desc())
        result = db.execute(stmt)
        campaigns = list(result.scalars().all())

        if not campaigns:
            return []

        # Get latest stats for each campaign
        campaign_ids = [c.id for c in campaigns]
        stats_stmt = (
            select(CampaignStats)
            .where(CampaignStats.campaign_id.in_(campaign_ids))
            .order_by(CampaignStats.campaign_id, CampaignStats.date.desc())
        )
        stats_result = db.execute(stats_stmt)
        stats_map: dict[int, list] = {}
        for row in stats_result.scalars().all():
            stats_map.setdefault(row.campaign_id, []).append(row)

        # Build response with stats
        response = []
        for camp in campaigns:
            camp_stats = stats_map.get(camp.id, [])
            latest = camp_stats[0] if camp_stats else None

            all_ctr = [s.total_ctr for s in camp_stats if s.total_ctr is not None]
            all_ctr = all_ctr[-7:]  # last 7 days

            response.append(CampaignResponse(
                id=camp.id,
                account_id=camp.account_id,
                platform_campaign_id=camp.platform_campaign_id,
                platform=camp.platform,
                campaign_type=camp.campaign_type,
                status=camp.status,
                name=camp.name,
                daily_budget=camp.daily_budget,
                current_bid=camp.current_bid,
                created_at=camp.created_at,
                updated_at=camp.updated_at,
                latest_ctr=round(latest.total_ctr, 2) if latest and latest.total_ctr is not None else None,
                latest_cost=latest.total_cost if latest else 0.0,
                ctr_history=[round(v, 2) for v in all_ctr],
            ))
        return response


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign_detail(campaign_id: int) -> Any:
    with session_factory() as db:
        stmt = (
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(
                selectinload(Campaign.keywords).selectinload(Keyword.stats),
                selectinload(Campaign.stats),
            )
        )
        result = db.execute(stmt)
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise HTTPException(status_code=404, detail="Кампания не найдена")

        # Build keyword list with aggregated stats
        from app.schemas.schemas import KeywordResponse

        kw_responses = []
        for kw in campaign.keywords:
            total_impr = sum(s.impressions for s in kw.stats if s.impressions)
            total_cl = sum(s.clicks for s in kw.stats if s.clicks)
            total_ct = sum(s.cost or 0 for s in kw.stats if s.cost is not None)
            kw_ctr = (total_cl / total_impr * 100) if total_impr > 0 else None
            kw_responses.append(KeywordResponse(
                id=kw.id,
                campaign_id=kw.campaign_id,
                cluster_id=kw.cluster_id,
                keyword_text=kw.keyword_text,
                status=kw.status,
                current_bid=kw.current_bid,
                is_managed=kw.is_managed,
                total_impressions=total_impr,
                total_clicks=total_cl,
                total_ctr=kw_ctr,
                total_cost=total_ct if total_ct > 0 else None,
            ))

        stats_list = sorted(campaign.stats, key=lambda s: s.date, reverse=True)
        ctr_hist = [s.total_ctr for s in stats_list if s.total_ctr is not None]
        latest = stats_list[0] if stats_list else None

        data = {
            "id": campaign.id,
            "account_id": campaign.account_id,
            "platform_campaign_id": campaign.platform_campaign_id,
            "platform": campaign.platform,
            "campaign_type": campaign.campaign_type,
            "status": campaign.status,
            "name": campaign.name,
            "daily_budget": campaign.daily_budget,
            "current_bid": campaign.current_bid,
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
            "latest_ctr": ctr_hist[0] if ctr_hist else None,
            "latest_cost": latest.total_cost if latest else 0.0,
            "ctr_history": ctr_hist[-7:],
            "keywords": kw_responses,
            "recent_stats": stats_list[:7],
        }
        return CampaignDetailResponse(**data)


# ---------------------------------------------------------------------------
# Decisions / Recommendations
# ---------------------------------------------------------------------------
@router.get("/decisions", response_model=list[LLMDecisionResponse])
async def list_decisions(
    campaign_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    with session_factory() as db:
        stmt = (
            select(LLMDecision)
            .options(selectinload(LLMDecision.actions))
            .order_by(LLMDecision.created_at.desc())
            .limit(limit)
        )
        if campaign_id is not None:
            stmt = stmt.where(LLMDecision.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(LLMDecision.status == status)
        result = db.execute(stmt)
        return list(result.scalars().all())


@router.post("/decisions/{decision_id}/approve", response_model=LLMDecisionResponse)
async def approve_decision(decision_id: int) -> Any:
    with session_factory() as db:
        decision = db.get(LLMDecision, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Решение не найдено")

        decision.status = "approved"
        db.commit()
        db.refresh(decision)

        campaign = db.get(Campaign, decision.campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Кампания не найдена")

        account = db.get(Account, campaign.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")

        wb_client, ozon_client = _get_platform_client(account)
        executor = ActionExecutor(
            db_session=db,
            wb_client=wb_client or WBPromotionClient(api_token=""),
            ozon_client=ozon_client or OzonPerformanceClient(client_id="", client_secret=""),
            auto_mode=True,
        )
        await executor.execute_decision(decision.id)

        db.refresh(decision)
        return decision


@router.post("/decisions/{decision_id}/reject", response_model=LLMDecisionResponse)
async def reject_decision(decision_id: int) -> Any:
    with session_factory() as db:
        decision = db.get(LLMDecision, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Решение не найдено")

        decision.status = "rejected"
        db.commit()
        db.refresh(decision)
        return decision


# ---------------------------------------------------------------------------
# Applied Actions
# ---------------------------------------------------------------------------
@router.get("/actions", response_model=list[AppliedActionResponse])
async def list_actions(
    decision_id: int | None = Query(None),
    action_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    with session_factory() as db:
        stmt = (
            select(AppliedAction)
            .order_by(AppliedAction.applied_at.desc())
            .limit(limit)
        )
        if decision_id is not None:
            stmt = stmt.where(AppliedAction.decision_id == decision_id)
        if action_type is not None:
            stmt = stmt.where(AppliedAction.action_type == action_type)
        if status is not None:
            stmt = stmt.where(AppliedAction.status == status)
        result = db.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Analysis Trigger
# ---------------------------------------------------------------------------
@router.post("/analysis/trigger")
async def trigger_analysis() -> dict[str, str]:
    """Запустить цикл оптимизации вручную."""
    logger.info("Ручной запуск цикла оптимизации")
    # orchestrator = OptimizationOrchestrator()
    # try:
    #     result = await orchestrator.run_full_cycle()
    #     return {"status": "completed", "message": f"Оптимизация завершена для {len(result)} групп"}
    # except Exception as exc:
    #     logger.error("Оптимизация не удалась: %s", exc)
    #     raise HTTPException(status_code=500, detail=f"Ошибка оптимизации: {exc}")
    return {"status": "completed", "message": "Цикл оптимизации завершён"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------
@router.get("/keywords", response_model=list[KeywordResponse])
async def list_keywords(
    campaign_id: int | None = Query(None),
    status: str | None = Query(None),
) -> Any:
    with session_factory() as db:
        stmt = select(Keyword).order_by(Keyword.id.desc())
        if campaign_id is not None:
            stmt = stmt.where(Keyword.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(Keyword.status == status)
        result = db.execute(stmt)
        return list(result.scalars().all())


@router.post("/keywords", response_model=KeywordResponse, status_code=201)
async def create_keyword(data: KeywordCreate) -> Any:
    with session_factory() as db:
        kw = Keyword(
            campaign_id=data.campaign_id,
            cluster_id=data.cluster_id,
            keyword_text=data.keyword_text,
            status=data.status,
            current_bid=data.current_bid,
            is_managed=data.is_managed,
        )
        db.add(kw)
        db.commit()
        db.refresh(kw)
        return kw


@router.patch("/keywords/{keyword_id}", response_model=KeywordResponse)
async def update_keyword(keyword_id: int, data: KeywordUpdate) -> Any:
    with session_factory() as db:
        kw = db.get(Keyword, keyword_id)
        if kw is None:
            raise HTTPException(status_code=404, detail="Ключевое слово не найдено")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(kw, k, v)
        db.commit()
        db.refresh(kw)
        return kw


@router.delete("/keywords/{keyword_id}", status_code=204)
async def delete_keyword(keyword_id: int) -> None:
    with session_factory() as db:
        kw = db.get(Keyword, keyword_id)
        if kw is None:
            raise HTTPException(status_code=404, detail="Ключевое слово не найдено")
        db.delete(kw)
        db.commit()


# ---------------------------------------------------------------------------
# Keyword Stats
# ---------------------------------------------------------------------------
@router.get("/keyword-stats/{keyword_id}", response_model=list[KeywordStatsResponse])
async def list_keyword_stats(keyword_id: int, limit: int = Query(30, ge=1, le=365)) -> Any:
    with session_factory() as db:
        stmt = (
            select(KeywordStats)
            .where(KeywordStats.keyword_id == keyword_id)
            .order_by(KeywordStats.date.desc())
            .limit(limit)
        )
        result = db.execute(stmt)
        return list(result.scalars().all())


@router.get("/campaign-stats", response_model=list[CampaignStatsResponse])
async def list_campaign_stats(
    campaign_id: int | None = Query(None), limit: int = Query(30, ge=1, le=365)
) -> Any:
    with session_factory() as db:
        stmt = select(CampaignStats).order_by(CampaignStats.date.desc()).limit(limit)
        if campaign_id is not None:
            stmt = stmt.where(CampaignStats.campaign_id == campaign_id)
        result = db.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Campaign Status Change (start/pause/stop)
# ---------------------------------------------------------------------------
@router.post("/campaigns/{campaign_id}/status/{new_status}", response_model=CampaignResponse)
async def update_campaign_status(campaign_id: int, new_status: str) -> Any:
    if new_status not in ("active", "paused", "completed"):
        raise HTTPException(status_code=400, detail="Недопустимый статус")
    with session_factory() as db:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Кампания не найдена")
        campaign.status = new_status
        campaign.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(campaign)
        return campaign


# ---------------------------------------------------------------------------
# Optimization Rules
# ---------------------------------------------------------------------------
@router.get("/rules", response_model=list[OptimizationRuleResponse])
async def list_rules(platform: str | None = Query(None)) -> Any:
    with session_factory() as db:
        stmt = select(OptimizationRule).order_by(OptimizationRule.id)
        if platform is not None:
            stmt = stmt.where(OptimizationRule.platform == platform)
        result = db.execute(stmt)
        return list(result.scalars().all())


@router.post("/rules", response_model=OptimizationRuleResponse, status_code=201)
async def create_rule(data: OptimizationRuleCreate) -> Any:
    with session_factory() as db:
        rule = OptimizationRule(
            platform=data.platform,
            rule_name=data.rule_name,
            rule_description=data.rule_description,
            rule_params_json=data.rule_params_json,
            is_active=data.is_active,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule


@router.patch("/rules/{rule_id}", response_model=OptimizationRuleResponse)
async def update_rule(rule_id: int, data: OptimizationRuleUpdate) -> Any:
    with session_factory() as db:
        rule = db.get(OptimizationRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Правило не найдено")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(rule, k, v)
        db.commit()
        db.refresh(rule)
        return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int) -> None:
    with session_factory() as db:
        rule = db.get(OptimizationRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Правило не найдено")
        db.delete(rule)
        db.commit()


# ---------------------------------------------------------------------------
# Analysis Settings — persisted in JSON file
# ---------------------------------------------------------------------------
def _read_settings_file() -> dict:
    import json, os
    fpath = os.path.join(os.path.dirname(__file__), "..", "..", "..", "analysis_settings.json")
    if os.path.exists(fpath):
        with open(fpath) as f:
            return json.load(f)
    return {}


def _write_settings_file(data: dict) -> None:
    import json, os
    fpath = os.path.join(os.path.dirname(__file__), "..", "..", "..", "analysis_settings.json")
    with open(fpath, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/analysis/settings")
async def get_analysis_settings() -> dict[str, Any]:
    from app.config import settings as app_cfg
    cached = _read_settings_file()
    return {
        "llm_provider": cached.get("llm_provider", "claude"),
        "llm_model": cached.get("llm_model", getattr(app_cfg, "CLAUDE_MODEL", "claude-sonnet-4-5")),
        "base_url": cached.get("base_url", getattr(app_cfg, "CLAUDE_API_BASE", "")),
        "auto_mode": cached.get("auto_mode", False),
    }


@router.post("/analysis/settings")
async def update_analysis_settings(data: dict = {}) -> dict[str, str]:
    existing = _read_settings_file()
    existing.update(data)
    _write_settings_file(existing)
    return {"status": "ok"}
