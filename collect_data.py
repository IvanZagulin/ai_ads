"""Run inside backend container to collect WB data."""
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select
from app.database import async_session_factory
from app.models.models import Account, Campaign, Keyword, KeywordStats
from app.clients.wb_client import WBPromotionClient
from app.utils.encryption import decrypt_token

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("collect")


async def main():
    async with async_session_factory() as session:
        account = (await session.execute(select(Account).where(Account.id == 1))).scalar_one_or_none()
        if not account:
            logger.error("Account 1 not found")
            return
        logger.info("Account: %s platform=%s", account.name, account.platform)

        token = decrypt_token(account.wb_token)
        wb = WBPromotionClient(api_token=token)
        # Conservative rate limit (WB: 10 stats req/min)
        wb._rate_limiter.rate = 0.5
        wb._rate_limiter.capacity = 3

        campaigns = await wb.get_campaigns()
        logger.info("Got %d campaigns from WB", len(campaigns))
        if not campaigns:
            logger.warning("No campaigns found")
            return

        # Sync campaigns
        for cd in campaigns:
            adv_id = cd.get("wb_adv_id")
            if not adv_id:
                continue
            pid = str(adv_id)
            c = (await session.execute(select(Campaign).where(
                Campaign.account_id == 1,
                Campaign.platform_campaign_id == pid,
            ))).scalar_one_or_none()
            if c:
                c.status = cd.get("status", c.status)
                c.name = cd.get("name", c.name)
                c.campaign_type = cd.get("bid_type", c.campaign_type)
                c.nm_ids = cd.get("nm_ids")
                await session.flush()
                logger.info("  Campaign %s: status=%s, nm_ids=%s", pid, c.status, c.nm_ids and len(c.nm_ids))

        await session.commit()
        logger.info("Campaigns synced")

        total_kw = 0
        total_bids = 0
        total_stats = 0

        for cd in campaigns:
            status = cd.get("status")
            adv_id = cd.get("wb_adv_id")
            nm_ids = cd.get("nm_ids", [])

            if not adv_id or status not in ("active", "paused"):
                continue

            db_camp = (await session.execute(select(Campaign).where(
                Campaign.account_id == 1,
                Campaign.platform_campaign_id == str(adv_id),
            ))).scalar_one_or_none()
            if not db_camp:
                continue

            logger.info("  Campaign %s: fetching clusters...", cd.get("name", ""))
            clusters = await wb.get_clusters(int(adv_id))
            logger.info("    Clusters: %d", len(clusters))

            for item in clusters:
                nq = item.get("normQuery", item.get("norm_query", ""))
                if not nq:
                    continue
                kw = (await session.execute(select(Keyword).where(
                    Keyword.campaign_id == db_camp.id,
                    Keyword.keyword_text == nq,
                ))).scalar_one_or_none()
                if not kw:
                    kw = Keyword(
                        campaign_id=db_camp.id,
                        cluster_id=str(item.get("clusterId", nq)),
                        keyword_text=nq,
                        status="active" if item.get("isActive", True) else "unmanaged",
                    )
                    session.add(kw)
                    total_kw += 1
                    await session.flush()

            for nm_id in nm_ids[:3]:
                logger.info("    NM %d: fetching bids...", nm_id)
                bids = await wb.get_cluster_bids(int(adv_id), nm_id)
                for bid_item in bids:
                    nq = bid_item.get("norm_query", "")
                    if not nq:
                        continue
                    kw = (await session.execute(select(Keyword).where(
                        Keyword.campaign_id == db_camp.id,
                        Keyword.keyword_text == nq,
                    ))).scalar_one_or_none()
                    if not kw:
                        kw = Keyword(
                            campaign_id=db_camp.id,
                            cluster_id=nq,
                            keyword_text=nq,
                            status="active",
                            current_bid=bid_item.get("bid"),
                        )
                        session.add(kw)
                        await session.flush()
                    else:
                        kw.current_bid = bid_item.get("bid")
                    total_bids += 1

                today = date.today()
                from_d = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                to_d = today.strftime("%Y-%m-%d")
                logger.info("    NM %d: fetching stats...", nm_id)
                stats = await wb.get_campaign_stats(int(adv_id), nm_id, from_d, to_d)
                logger.info("    Stats: %d records", len(stats))

                for stat in stats:
                    nq = stat.get("normQuery", "")
                    sd = stat.get("date", "")
                    if not nq or not sd:
                        continue
                    try:
                        stat_date = date.fromisoformat(sd)
                    except ValueError:
                        continue
                    kw = (await session.execute(select(Keyword).where(
                        Keyword.campaign_id == db_camp.id,
                        Keyword.keyword_text == nq,
                    ))).scalar_one_or_none()
                    if not kw:
                        kw = Keyword(
                            campaign_id=db_camp.id,
                            cluster_id=nq,
                            keyword_text=nq,
                            status="active",
                        )
                        session.add(kw)
                        await session.flush()

                    ks = (await session.execute(select(KeywordStats).where(
                        KeywordStats.keyword_id == kw.id,
                        KeywordStats.date == stat_date,
                    ))).scalar_one_or_none()
                    views = stat.get("views", 0)
                    clicks = stat.get("clicks", 0)
                    if not ks:
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
                        session.add(ks)
                    else:
                        ks.impressions = views
                        ks.clicks = clicks
                        ks.ctr = stat.get("ctr")
                        ks.position = stat.get("avgPos", stat.get("avg_pos"))
                        ks.cost = stat.get("spend", 0)
                        ks.orders = stat.get("orders", 0)
                    total_stats += 1

                await asyncio.sleep(6)  # WB stats limit: 10/min

            await session.commit()

        logger.info("DONE: keywords=%d, bids=%d, stats=%d", total_kw, total_bids, total_stats)
        print(f"RESULT: {total_kw} keywords, {total_bids} bids, {total_stats} stats records")


if __name__ == "__main__":
    asyncio.run(main())
