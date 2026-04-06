from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.ozon_client import OzonPerformanceClient
from app.clients.wb_client import WBPromotionClient
from app.config import settings
from app.database import async_session_factory
from app.models.models import Account, Campaign, CampaignStats, Keyword, KeywordStats
from app.tasks.celery_app import celery_app
from app.utils.encryption import decrypt_token

logger = logging.getLogger(__name__)


async def _get_active_accounts() -> list[Account]:
    """Fetch all active accounts from the database."""
    async with async_session_factory() as session:
        result = await session.execute(select(Account).where(Account.is_active.is_(True)))
        return list(result.scalars().all())


async def _get_account_clients(
    account: Account,
) -> tuple[WBPromotionClient | None, OzonPerformanceClient | None]:
    """Initialize the appropriate API clients for an account."""
    wb_client: WBPromotionClient | None = None
    ozon_client: OzonPerformanceClient | None = None

    if account.platform == "wildberries" and account.wb_token:
        token = decrypt_token(account.wb_token)
        wb_client = WBPromotionClient(api_token=token)

    if account.platform == "ozon" and account.ozon_client_secret:
        secret = decrypt_token(account.ozon_client_secret)
        ozon_client = OzonPerformanceClient(
            client_id=account.ozon_client_id or "",
            client_secret=secret,
        )

    return wb_client, ozon_client


@celery_app.task(bind=True, name="app.tasks.data_collector.collect_wb_data")
async def collect_wb_data(self, account_id: int) -> dict[str, Any]:
    """Fetch all Wildberries campaign data and save to DB."""
    logger.info("Collecting WB data for account %d", account_id)

    async with async_session_factory() as session:
        account = await session.get(Account, account_id)
        if account is None or account.platform != "wildberries":
            return {"status": "skipped", "reason": "account not found or not WB"}

        wb_client, _ = await _get_account_clients(account)
        if wb_client is None:
            return {"status": "error", "reason": "no WB token"}

        try:
            campaigns_raw = await wb_client.get_campaigns_with_stats()
            saved_campaigns = 0
            saved_stats = 0
            saved_keywords = 0

            for camp_data in campaigns_raw:
                campaign = await _find_or_create_wb_campaign(session, account.id, camp_data)
                if campaign is None:
                    continue

                # Process daily stats from /adv/v1/normquery/stats
                daily_stats = camp_data.get("daily_stats", [])
                for day_entry in daily_stats:
                    stat_date_str = day_entry.get("date", "")
                    if not stat_date_str:
                        continue
                    try:
                        stat_date = date.fromisoformat(stat_date_str)
                    except ValueError:
                        continue

                    # Upsert campaign-level daily stats (aggregate of all clusters)
                    await _upsert_campaign_stats(session, campaign, stat_date, {
                        "views": day_entry.get("views", 0),
                        "clicks": day_entry.get("clicks", 0),
                        "sum": day_entry.get("spend", 0),
                        "orders": day_entry.get("orders", 0),
                        "ctr": day_entry.get("ctr"),
                    })
                    saved_stats += 1

                    # Upsert keyword/cluster-level stats from cluster breakdown
                    for cluster in day_entry.get("clusters", []):
                        cluster_text = cluster.get("text", "")
                        if not cluster_text:
                            continue
                        kw = await _upsert_keyword(session, campaign, {
                            "text": cluster_text,
                            "cluster_id": cluster_text,
                        })
                        await _upsert_keyword_stats(session, kw, stat_date, {
                            "views": cluster.get("views", 0),
                            "clicks": cluster.get("clicks", 0),
                            "ctr": cluster.get("ctr"),
                            "orders": cluster.get("orders", 0),
                            "sum": cluster.get("spend", 0),
                            "avgPosition": cluster.get("avgPos"),
                        })
                        saved_keywords += 1

                saved_campaigns += 1

            await session.commit()
            return {
                "status": "success",
                "account_id": account_id,
                "campaigns_saved": saved_campaigns,
                "stats_saved": saved_stats,
                "keywords_saved": saved_keywords,
            }

        except Exception as exc:
            await session.rollback()
            logger.error("WB data collection failed for account %d: %s", account_id, exc)
            raise


async def _find_or_create_wb_campaign(
    session: AsyncSession, account_id: int, data: dict[str, Any]
) -> Campaign | None:
    """Find existing WB campaign by wb_adv_id (platform ID) or create new one.

    Returns None if platform_id cannot be extracted.
    """
    platform_id = data.get("wb_adv_id") or data.get("advertId") or data.get("id")
    if not platform_id:
        return None
    platform_id = str(platform_id)

    stmt = select(Campaign).where(
        Campaign.account_id == account_id,
        Campaign.platform_campaign_id == platform_id,
    )
    result = await session.execute(stmt)
    campaign = result.scalar_one_or_none()

    if campaign is None:
        campaign = Campaign(
            account_id=account_id,
            platform_campaign_id=platform_id,
            platform="wildberries",
            campaign_type=data.get("type", "search"),
            status=data.get("status", "active"),
            name=data.get("name", f"WB Campaign {platform_id}"),
            daily_budget=data.get("dailyBudget") or data.get("budget"),
            current_bid=data.get("price") or data.get("bid"),
        )
        session.add(campaign)
    else:
        campaign.status = data.get("status", campaign.status)
        campaign.name = data.get("name", campaign.name)
        campaign.updated_at = datetime.now(timezone.utc)

    await session.flush()
    return campaign


async def _upsert_campaign_stats(
    session: AsyncSession, campaign: Campaign, stats_date: date, data: dict[str, Any]
) -> None:
    """Insert or update campaign daily stats."""
    stmt = select(CampaignStats).where(
        CampaignStats.campaign_id == campaign.id,
        CampaignStats.date == stats_date,
    )
    result = await session.execute(stmt)
    stats = result.scalar_one_or_none()

    total_impressions = int(data.get("views", 0))
    total_clicks = int(data.get("clicks", 0))
    total_cost = float(data.get("sum", 0))
    total_orders = int(data.get("orders", 0))
    total_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else None
    search_share = float(data.get("showPercent", 0)) or None

    if stats is None:
        stats = CampaignStats(
            campaign_id=campaign.id,
            date=stats_date,
            total_impressions=total_impressions,
            total_clicks=total_clicks,
            total_ctr=total_ctr,
            total_cost=total_cost,
            total_orders=total_orders,
            search_share_pct=search_share,
        )
        session.add(stats)
    else:
        stats.total_impressions = total_impressions
        stats.total_clicks = total_clicks
        stats.total_ctr = total_ctr
        stats.total_cost = total_cost
        stats.total_orders = total_orders
        stats.search_share_pct = search_share

    await session.flush()


async def _fetch_cluster_data(wb_client: WBPromotionClient, campaign: Campaign) -> list[dict[str, Any]]:
    """Fetch cluster/keyword data for a campaign."""
    try:
        platform_id = int(campaign.platform_campaign_id or "0")
        if platform_id > 0:
            return await wb_client.get_cluster_stats(platform_id)
    except Exception as exc:
        logger.warning("Failed to fetch cluster stats for campaign %d: %s", campaign.id, exc)
    return []


async def _upsert_keyword(
    session: AsyncSession, campaign: Campaign, data: dict[str, Any]
) -> Keyword:
    """Insert or update a keyword record."""
    kw_text = data.get("text", data.get("keyword", "")).strip()
    cluster_id = data.get("id") or data.get("clusterId")

    if not kw_text:
        kw_text = f"cluster_{cluster_id}"

    stmt = select(Keyword).where(
        Keyword.campaign_id == campaign.id,
        Keyword.keyword_text == kw_text,
    )
    result = await session.execute(stmt)
    kw = result.scalar_one_or_none()

    current_bid = data.get("bid") or data.get("currentBid", campaign.current_bid)
    if isinstance(current_bid, Decimal):
        current_bid = float(current_bid)

    if kw is None:
        kw = Keyword(
            campaign_id=campaign.id,
            cluster_id=str(cluster_id) if cluster_id else None,
            keyword_text=kw_text,
            current_bid=current_bid,
        )
        session.add(kw)
    else:
        kw.current_bid = current_bid
        kw.status = "active"

    await session.flush()
    return kw


async def _upsert_keyword_stats(
    session: AsyncSession, keyword: Keyword, stats_date: date, data: dict[str, Any]
) -> None:
    """Insert or update keyword daily stats."""
    stmt = select(KeywordStats).where(
        KeywordStats.keyword_id == keyword.id,
        KeywordStats.date == stats_date,
    )
    result = await session.execute(stmt)
    stats = result.scalar_one_or_none()

    impressions = int(data.get("views", 0))
    clicks = int(data.get("clicks", data.get("translates", 0)))
    ctr = (clicks / impressions * 100) if impressions > 0 else None
    position = float(data.get("avgPosition", data.get("position", 0))) or None
    cost = float(data.get("sum", 0))
    orders = int(data.get("orders", 0))
    unique_pct = float(data.get("showPercent", data.get("unique_impressions_pct", 0))) or None

    if stats is None:
        stats = KeywordStats(
            keyword_id=keyword.id,
            date=stats_date,
            impressions=impressions,
            clicks=clicks,
            ctr=ctr,
            position=position,
            cost=cost,
            orders=orders,
            unique_impressions_pct=unique_pct,
        )
        session.add(stats)
    else:
        stats.impressions = impressions
        stats.clicks = clicks
        stats.ctr = ctr
        stats.position = position
        stats.cost = cost
        stats.orders = orders
        stats.unique_impressions_pct = unique_pct

    await session.flush()


@celery_app.task(bind=True, name="app.tasks.data_collector.collect_ozon_data")
async def collect_ozon_data(self, account_id: int) -> dict[str, Any]:
    """Fetch all Ozon campaign data using async report model and save to DB."""
    logger.info("Collecting Ozon data for account %d", account_id)

    async with async_session_factory() as session:
        account = await session.get(Account, account_id)
        if account is None or account.platform != "ozon":
            return {"status": "skipped", "reason": "account not found or not Ozon"}

        _, ozon_client = await _get_account_clients(account)
        if ozon_client is None:
            return {"status": "error", "reason": "no Ozon credentials"}

        try:
            raw_campaigns = await ozon_client.get_campaigns()
            saved_campaigns = 0
            saved_stats = 0

            for camp_data in raw_campaigns:
                camp = await _find_or_create_ozon_campaign(session, account.id, camp_data)

                try:
                    report_df = await ozon_client.get_report_data(
                        report_type="campaign_stats",
                        params={"campaign_id": camp_data.get("id", "")},
                    )
                    for _, row in report_df.iterrows():
                        stats_date_str = str(row.get("date", date.today()))
                        if isinstance(stats_date_str, str):
                            try:
                                stats_date = datetime.strptime(stats_date_str, "%Y-%m-%d").date()
                            except ValueError:
                                stats_date = date.today()
                        else:
                            stats_date = stats_date_str

                        stats_row = {
                            "views": int(row.get("views", 0)),
                            "clicks": int(row.get("clicks", 0)),
                            "sum": float(row.get("cost", 0)),
                            "orders": int(row.get("orders", 0)),
                        }
                        await _upsert_campaign_stats(session, camp, stats_date, stats_row)
                        saved_stats += 1
                except Exception as exc:
                    logger.warning("Failed to collect stats for Ozon campaign %d: %s", camp.id, exc)

                saved_campaigns += 1

            await session.commit()
            return {
                "status": "success",
                "account_id": account_id,
                "campaigns_saved": saved_campaigns,
                "stats_saved": saved_stats,
            }

        except Exception as exc:
            await session.rollback()
            logger.error("Ozon data collection failed for account %d: %s", account_id, exc)
            raise


async def _find_or_create_ozon_campaign(
    session: AsyncSession, account_id: int, data: dict[str, Any]
) -> Campaign:
    """Find existing Ozon campaign or create new."""
    platform_id = str(data.get("id", ""))

    stmt = select(Campaign).where(
        Campaign.account_id == account_id,
        Campaign.platform_campaign_id == platform_id,
    )
    result = await session.execute(stmt)
    campaign = result.scalar_one_or_none()

    if campaign is None:
        campaign = Campaign(
            account_id=account_id,
            platform_campaign_id=platform_id,
            platform="ozon",
            campaign_type=data.get("type", "search"),
            status=data.get("status", "active"),
            name=data.get("name", f"Ozon Campaign {platform_id}"),
            daily_budget=data.get("dailyBudget") or data.get("budget"),
            current_bid=data.get("price") or data.get("bid"),
        )
        session.add(campaign)
    else:
        campaign.status = data.get("status", campaign.status)
        campaign.name = data.get("name", campaign.name)
        campaign.updated_at = datetime.now(timezone.utc)

    await session.flush()
    return campaign


@celery_app.task(name="app.tasks.data_collector.collect_all_data")
async def collect_all_data() -> dict[str, Any]:
    """Run data collection for all active accounts."""
    logger.info("Starting full data collection for all active accounts")
    results: dict[str, Any] = {}

    accounts = await _get_active_accounts()

    for account in accounts:
        try:
            if account.platform == "wildberries":
                result = await collect_wb_data(account.id)
            elif account.platform == "ozon":
                result = await collect_ozon_data(account.id)
            else:
                result = {"status": "skipped", "reason": f"unknown platform: {account.platform}"}

            results[f"{account.platform}:{account.id}"] = result
        except Exception as exc:
            results[f"{account.platform}:{account.id}"] = {"status": "error", "error": str(exc)}

    logger.info("Full data collection complete: %d accounts processed", len(results))
    return results


@celery_app.task(name="app.tasks.data_collector.collect_wb_data_all_accounts")
async def collect_wb_data_all_accounts() -> dict[str, Any]:
    """Collect WB data for all active WB accounts."""
    results: dict[str, Any] = {}
    accounts = await _get_active_accounts()

    for account in accounts:
        if account.platform == "wildberries":
            results[str(account.id)] = await collect_wb_data(account.id)

    return results


@celery_app.task(name="app.tasks.data_collector.collect_ozon_data_all_accounts")
async def collect_ozon_data_all_accounts() -> dict[str, Any]:
    """Collect Ozon data for all active Ozon accounts."""
    results: dict[str, Any] = {}
    accounts = await _get_active_accounts()

    for account in accounts:
        if account.platform == "ozon":
            results[str(account.id)] = await collect_ozon_data(account.id)

    return results
