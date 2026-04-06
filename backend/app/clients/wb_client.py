from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


# WB API campaign status -> our status
CAMPAIGN_STATUS_MAP = {
    -1: "deleted",
    4: "pending",
    7: "completed",
    8: "cancelled",
    9: "active",
    11: "paused",
}


class WBPromotionClient:
    """Client for Wildberries advertising API.

    Auth: HeaderApiKey passed in "Authorization" header.
    Rate limit: 5 req/sec, 200ms interval (varies per method).

    Full endpoint list (advert-api.wildberries.ru):

    Campaigns:
    - GET    /adv/v1/promotion/count              — campaign IDs by type/status
    - GET    /api/advert/v2/adverts?ids=...        — campaign details (max 50)
    - POST   /adv/v2/seacat/save-ad                — create campaign
    - GET    /adv/v0/start?id=...                  — start campaign (status 4 or 11)
    - GET    /adv/v0/pause?id=...                  — pause campaign (status 9)
    - GET    /adv/v0/stop?id=...                   — stop campaign (status 4, 9, 11)
    - POST   /adv/v0/rename                        — rename campaign
    - GET    /adv/v0/delete?id=...                 — delete campaign (status 4)

    Bids:
    - PATCH  /api/advert/v1/bids                   — update card bids
    - POST   /api/advert/v1/bids/min               — minimal bids
    - GET    /api/advert/v0/bids/recommendations   — recommended bids (nmId + advertId)

    Search clusters (normquery):
    - POST   /adv/v0/normquery/list                — active/inactive cluster list
    - POST   /adv/v0/normquery/get-bids            — cluster bids list
    - POST   /adv/v0/normquery/bids                — set cluster bids (POST = set, DELETE = remove)
    - POST   /adv/v0/normquery/set-minus           — set/remove minus-phrases
    - POST   /adv/v0/normquery/get-minus           — get minus-phrases

    Statistics:
    - POST   /adv/v0/normquery/stats               — cluster stats (aggregate)
    - POST   /adv/v1/normquery/stats               — cluster stats (daily breakdown)
    - GET    /adv/v3/fullstats                     — campaign full stats

    Finances:
    - GET    /adv/v1/balance                        — account balance
    - GET    /adv/v1/budget?id=...                  — campaign budget
    - POST   /adv/v1/budget/deposit?id=...          — deposit campaign budget
    - GET    /adv/v1/upd?from=...&to=...            — expense history
    - GET    /adv/v1/payments?from=...&to=...       — payment history
    """

    def __init__(self, api_token: str, base_url: str | None = None):
        self.api_token = api_token
        self.base_url = (base_url or "https://advert-api.wildberries.ru").rstrip("/")
        self._rate_limiter = TokenBucketRateLimiter(rate=5, capacity=5)

    async def _wait_rate_limit(self):
        await self._rate_limiter.acquire()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # CAMPAIGNS
    # ------------------------------------------------------------------ #

    async def get_campaign_ids(self) -> list[int]:
        """GET /adv/v1/promotion/count — campaign IDs grouped by type/status."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/promotion/count"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers(), timeout=30.0)
        if resp.status_code == 401:
            raise RuntimeError("Неверный токен WB (401)")
        if resp.status_code != 200:
            raise RuntimeError(
                f"WB API error: {resp.status_code}, body={resp.text[:300]}"
            )
        data = resp.json()
        ids: list[int] = []
        for group in data.get("adverts", []):
            for item in group.get("advert_list", []):
                ids.append(item["advertId"])
        return ids

    async def get_campaign_details(self, advert_ids: list[int]) -> list[dict[str, Any]]:
        """GET /api/advert/v2/adverts?ids=... — campaign details (max 50 per call)."""
        results: list[dict[str, Any]] = []
        for i in range(0, len(advert_ids), 50):
            chunk = advert_ids[i : i + 50]
            ids_str = ",".join(str(x) for x in chunk)
            await self._wait_rate_limit()
            url = f"{self.base_url}/api/advert/v2/adverts"
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers=self._headers(),
                    params={"ids": ids_str},
                    timeout=30.0,
                )
            if resp.status_code != 200:
                logger.warning(
                    f"WB details error: {resp.status_code}, {resp.text[:300]}"
                )
                continue
            for c in resp.json().get("adverts", []):
                results.append(self._normalize(c))
        return results

    async def start_campaign(self, advert_id: int) -> int:
        """GET /adv/v0/start?id=... — start campaign (status 4 or 11)."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/start"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        if resp.status_code not in (200, 422):
            logger.warning(f"start_campaign {advert_id}: {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    async def pause_campaign(self, advert_id: int) -> int:
        """GET /adv/v0/pause?id=... — pause campaign (status 9 -> 11)."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/pause"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        if resp.status_code not in (200, 422):
            logger.warning(f"pause_campaign {advert_id}: {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    async def stop_campaign(self, advert_id: int) -> int:
        """GET /adv/v0/stop?id=... — stop campaign (status 4, 9, or 11 -> 7)."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/stop"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        if resp.status_code not in (200, 422):
            logger.warning(f"stop_campaign {advert_id}: {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    async def delete_campaign(self, advert_id: int) -> int:
        """GET /adv/v0/delete?id=... — delete campaign (status 4 only)."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/delete"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        if resp.status_code != 200:
            logger.warning(f"delete_campaign {advert_id}: {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    async def rename_campaign(self, advert_id: int, name: str) -> int:
        """POST /adv/v0/rename — rename campaign."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/rename"
        body = {"advertId": advert_id, "name": name[:100]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code != 200:
            logger.warning(f"rename_campaign {advert_id}: {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    async def update_campaign_bid(
        self, advert_id: int, nm_id: int, placement: str, bid: int
    ) -> dict[str, Any]:
        """PATCH /api/advert/v1/bids — update card bid in a campaign.

        placement: "combined" (unified bid), "search", or "recommendations" (manual bids).
        bid: amount in kopecks.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/api/advert/v1/bids"
        body = {
            "bids": [
                {
                    "advert_id": advert_id,
                    "nm_bids": [{"nm_id": nm_id, placement: bid}],
                }
            ]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------
    # Main entry-point
    # ------------------------------------------------------------------
    async def get_campaigns(self) -> list[dict[str, Any]]:
        ids = await self.get_campaign_ids()
        if not ids:
            return []
        return await self.get_campaign_details(ids)

    # ------------------------------------------------------------------ #
    # STATISTICS
    # ------------------------------------------------------------------ #

    async def get_campaign_fullstats(
        self, campaign_ids: list[int], begin_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """GET /adv/v3/fullstats — campaign-level stats (max 50 IDs)."""
        await self._wait_rate_limit()  # limit: 3/min for this endpoint
        ids_str = ",".join(str(x) for x in campaign_ids[:50])
        url = f"{self.base_url}/adv/v3/fullstats"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=self._headers(),
                params={
                    "ids": ids_str,
                    "beginDate": begin_date,
                    "endDate": end_date,
                },
                timeout=30.0,
            )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"get_campaign_fullstats: {resp.status_code} {resp.text[:200]}")
        return []

    async def get_campaign_stats(
        self, advert_id: int, nm_id: int, from_date: str, to_date: str
    ) -> dict[str, Any]:
        """POST /adv/v1/normquery/stats — campaign aggregate + cluster breakdown.

        Returns one dict per date:
        {
            "date": "2026-04-05",
            "nmId": 123, "advertId": 456,
            # campaign aggregate
            "views": 330, "clicks": 18, "ctr": 5.45, "spend": 136.16, "orders": 0,
            # per-cluster breakdown
            "clusters": [
                {"text": "...", "views": 93, "clicks": 4, "ctr": 4.30, "spend": 39.06},
                ...
            ]
        }
        """
        url = f"{self.base_url}/adv/v1/normquery/stats"
        body = {
            "from": from_date,
            "to": to_date,
            "items": [{"advertId": advert_id, "nmId": nm_id}],
        }
        max_retries = 3
        for attempt in range(max_retries + 1):
            await self._wait_rate_limit()
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, headers=self._headers(), json=body, timeout=30.0
                )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("items") or []:
                    for day_stat in item.get("dailyStats", []):
                        aggr = day_stat.get("stat", {})
                        clusters_raw = day_stat.get("clusterStats", [])
                        cluster_list = []
                        for c in clusters_raw:
                            cluster_list.append({
                                "text": c.get("text", ""),
                                "views": c.get("views", 0),
                                "clicks": c.get("clicks", 0),
                                "ctr": c.get("ctr"),
                                "spend": c.get("spend", 0),
                                "cpc": c.get("cpc"),
                                "cpm": c.get("cpm"),
                                "orders": c.get("orders", 0),
                                "avgPos": c.get("avgPos"),
                            })
                        entry = {
                            "date": day_stat.get("date", ""),
                            "nmId": item.get("nmId"),
                            "advertId": item.get("advertId"),
                            "views": aggr.get("views", 0),
                            "clicks": aggr.get("clicks", 0),
                            "ctr": aggr.get("ctr"),
                            "spend": aggr.get("sum", aggr.get("spend", 0)),
                            "orders": aggr.get("orders", 0),
                            "cpc": aggr.get("cpc"),
                            "cpm": aggr.get("cpm"),
                            "showPercent": aggr.get("showPercent"),
                            "clusters": cluster_list,
                        }
                        results.append(entry)
                return results
            if resp.status_code == 429 and attempt < max_retries:
                import random
                wait = (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(wait)
                continue
            logger.warning(f"get_campaign_stats {advert_id}/{nm_id}: {resp.status_code}")
            return {}
        return {}

    async def get_cluster_stats(
        self, advert_id: int, nm_id: int, from_date: str, to_date: str
    ) -> list[dict[str, Any]]:
        """POST /adv/v0/normquery/stats — aggregated cluster stats (no daily breakdown)."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/stats"
        body = {
            "from": from_date,
            "to": to_date,
            "items": [{"advert_id": advert_id, "nm_id": nm_id}],
        }
        max_retries = 3
        for attempt in range(max_retries + 1):
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, headers=self._headers(), json=body, timeout=30.0
                )
            if resp.status_code == 200:
                data = resp.json()
                all_stats = []
                for s in data.get("stats") or []:
                    for cluster_stat in s.get("stats") or []:
                        cluster_stat["advert_id"] = s.get("advert_id")
                        cluster_stat["nm_id"] = s.get("nm_id")
                        all_stats.append(cluster_stat)
                return all_stats
            if resp.status_code == 429 and attempt < max_retries:
                import random
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
            return []
        return []

    async def get_campaigns_with_stats(self, days: int = 30) -> list[dict[str, Any]]:
        """Fetch campaigns with cluster lists and daily stats."""
        from datetime import date, timedelta

        campaigns = await self.get_campaigns()
        if not campaigns:
            return campaigns

        today = date.today()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        stats_campaigns = [
            c for c in campaigns
            if c.get("status") in ("active", "paused")
            and c.get("wb_adv_id")
            and c.get("nm_ids")
        ]

        for camp in stats_campaigns:
            adv_id = camp.get("wb_adv_id")
            nm_ids = camp.get("nm_ids", [])
            clusters = await self.get_clusters(adv_id)
            camp["clusters"] = clusters

            # Fetch daily stats for each NM (aggregate + cluster breakdown)
            all_daily = {}  # keyed by date
            for nm_id in nm_ids[:5]:
                daily = await self.get_campaign_stats(adv_id, nm_id, from_date, to_date)
                if isinstance(daily, list):
                    for d in daily:
                        dt = d.get("date", "")
                        if dt and dt not in all_daily:
                            all_daily[dt] = d
                        elif dt:
                            # Merge: sum aggregates, merge clusters
                            existing = all_daily[dt]
                            for key in ("views", "clicks", "spend", "orders"):
                                existing[key] = existing.get(key, 0) + d.get(key, 0)
                            existing_cls = {c["text"]: c for c in existing.get("clusters", [])}
                            for c in d.get("clusters", []):
                                txt = c["text"]
                                if txt in existing_cls:
                                    for k in ("views", "clicks", "spend"):
                                        existing_cls[txt][k] = existing_cls[txt].get(k, 0) + c.get(k, 0)
                                else:
                                    existing_cls[txt] = c.copy()
                            existing["clusters"] = list(existing_cls.values())
                await asyncio.sleep(0.3)

            camp["daily_stats"] = list(all_daily.values())
            await asyncio.sleep(0.5)

        return campaigns

    # ------------------------------------------------------------------ #
    # Create campaign: POST /adv/v2/seacat/save-ad
    # ------------------------------------------------------------------
    async def save_ad(
        self,
        *,
        name: str,
        nms: list[int],
        bid_type: str = "manual",
        payment_type: str = "cpm",
        placement_types: list[str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/adv/v2/seacat/save-ad"
        body: dict[str, Any] = {
            "name": name,
            "nms": nms[:50],
            "bid_type": bid_type,
            "payment_type": payment_type,
        }
        if placement_types is not None:
            body["placement_types"] = placement_types
        await self._wait_rate_limit()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return {"id": resp.json()}
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------ #
    # Minimal bids: POST /api/advert/v1/bids/min
    # ------------------------------------------------------------------
    async def get_min_bids(
        self,
        advert_id: int,
        nm_ids: list[int],
        payment_type: str,
        placement_types: list[str],
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/advert/v1/bids/min"
        body = {
            "advert_id": advert_id,
            "nm_ids": nm_ids[:100],
            "payment_type": payment_type,
            "placement_types": placement_types,
        }
        await self._wait_rate_limit()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------ #
    # Items/subjects for campaign creation
    # ------------------------------------------------------------------
    async def get_items(self) -> list[dict[str, Any]]:
        """GET /adv/v1/supplier/subjects — available items for campaigns."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/supplier/subjects"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers(), timeout=30.0)
        if resp.status_code == 200:
            return resp.json()
        return []

    async def get_cards_for_items(self, subject_ids: list[int]) -> list[dict[str, Any]]:
        """POST /adv/v2/supplier/nms — cards for given subject IDs."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v2/supplier/nms"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=subject_ids, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return []

    # ------------------------------------------------------------------ #
    # SEARCH CLUSTERS (normquery)
    # ------------------------------------------------------------------ #

    async def get_clusters(self, advert_id: int) -> list[dict[str, Any]]:
        """POST /adv/v0/normquery/list — active/inactive search clusters.

        Returns clusters that have >= 100 shows. Each item has shows, clicks,
        ctr, is_active flag, etc.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/list"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json={"advertId": advert_id}, timeout=30.0
            )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items")
            if items is not None and isinstance(items, list):
                return items
        return []

    async def get_cluster_bids(
        self, advert_id: int, nm_id: int
    ) -> list[dict[str, Any]]:
        """POST /adv/v0/normquery/get-bids — current cluster bids.

        Returns list of dicts with keys: advert_id, nm_id, norm_query, bid.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/get-bids"
        body = {"items": [{"advert_id": advert_id, "nm_id": nm_id}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json().get("bids", [])
        return []

    async def set_cluster_bids(
        self, bids: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """POST /adv/v0/normquery/bids — set bids for search clusters.

        Each bid dict must have:
        - advert_id: int
        - nm_id: int
        - norm_query: str (the cluster text)
        - bid: int (CPM in rubles per 1000 impressions)
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/bids"
        body = {"bids": bids[:100]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    async def remove_cluster_bids(
        self, bids: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """DELETE /adv/v0/normquery/bids — remove cluster bids.

        Same body format as set_cluster_bids.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/bids"
        body = {"bids": bids[:100]}
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------ #
    # Minus-phrases
    # ------------------------------------------------------------------ #

    async def get_minus_phrases(
        self, advert_id: int, nm_id: int
    ) -> list[str]:
        """POST /adv/v0/normquery/get-minus — get minus-phrases list."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/get-minus"
        body = {"items": [{"advert_id": advert_id, "nm_id": nm_id}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items") or []
            phrases: list[str] = []
            for item in items:
                phrases.extend(item.get("norm_queries") or [])
            return phrases
        return []

    async def set_minus_phrases(
        self, advert_id: int, nm_id: int, norm_queries: list[str]
    ) -> dict[str, Any]:
        """POST /adv/v0/normquery/set-minus — set/remove minus-phrases.

        Sending empty array removes all minus-phrases.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v0/normquery/set-minus"
        body = {
            "advert_id": advert_id,
            "nm_id": nm_id,
            "norm_queries": norm_queries[:1000],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------ #
    # Recommended bids
    # ------------------------------------------------------------------

    async def get_bids_recommendations(
        self, advert_id: int, nm_id: int
    ) -> dict[str, Any]:
        """GET /api/advert/v0/bids/recommendations — recommended bids for cards and clusters.

        Both nmId and advertId are REQUIRED.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/api/advert/v0/bids/recommendations"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=self._headers(),
                params={"nmId": nm_id, "advertId": advert_id},
                timeout=30.0,
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------ #
    # FINANCES
    # ------------------------------------------------------------------ #

    async def get_balance(self) -> dict[str, Any]:
        """GET /adv/v1/balance — account balance, netting, bonuses."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/balance"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers(), timeout=30.0)
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    async def get_campaign_budget(self, campaign_id: int) -> dict[str, Any]:
        """GET /adv/v1/budget?id=... — campaign budget."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/budget"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": campaign_id}, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    async def deposit_campaign_budget(
        self,
        campaign_id: int,
        total_sum: int,
        cashback_sum: int | None = None,
        cashback_percent: int | None = None,
        deposit_type: int = 1,
    ) -> dict[str, Any]:
        """POST /adv/v1/budget/deposit — deposit campaign budget.

        deposit_type: 0 = account, 1 = balance, 3 = bonuses.
        """
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/budget/deposit"
        body: dict[str, Any] = {
            "sum": total_sum,
            "type": deposit_type,
            "return": True,
        }
        if cashback_sum is not None:
            body["cashback_sum"] = cashback_sum
        if cashback_percent is not None:
            body["cashback_percent"] = cashback_percent
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0,
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    async def get_expense_history(
        self, from_date: str, to_date: str
    ) -> list[dict[str, Any]]:
        """GET /adv/v1/upd?from=...&to=... — expense history."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/upd"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=self._headers(),
                params={"from": from_date, "to": to_date},
                timeout=30.0,
            )
        if resp.status_code == 200:
            return resp.json()
        return []

    async def get_payment_history(
        self, from_date: str, to_date: str
    ) -> list[dict[str, Any]]:
        """GET /adv/v1/payments?from=...&to=... — payment history."""
        await self._wait_rate_limit()
        url = f"{self.base_url}/adv/v1/payments"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=self._headers(),
                params={"from": from_date, "to": to_date},
                timeout=30.0,
            )
        if resp.status_code == 200:
            return resp.json()
        return []

    # ------------------------------------------------------------------ #
    # Helper: one-call to get campaigns + set bid for a cluster
    # ------------------------------------------------------------------ #

    async def set_cluster_bid(self, advert_id: int, nm_id: int, norm_query: str, bid: int) -> dict[str, Any]:
        """Set bid for a single cluster via POST /adv/v0/normquery/bids."""
        return await self.set_cluster_bids([
            {"advert_id": advert_id, "nm_id": nm_id, "norm_query": norm_query, "bid": bid}
        ])

    async def add_minus_phrase(self, advert_id: int, nm_id: int, phrase: str) -> dict[str, Any]:
        """Add a minus-phrase. Fetches existing ones first, then sends the merged list."""
        existing = await self.get_minus_phrases(advert_id, nm_id)
        if phrase not in existing:
            existing.append(phrase)
        return await self.set_minus_phrases(advert_id, nm_id, existing)

    # ------------------------------------------------------------------
    # Normalization to our schema
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
        settings_data = raw.get("settings", {})
        ts = raw.get("timestamps", {})
        wb_status_code = raw.get("status", -1)
        bid_type = raw.get("bid_type", "manual")

        # placements
        placements = settings_data.get("placements", {})
        placement_list = []
        if placements.get("search"):
            placement_list.append("search")
        if placements.get("recommendations"):
            placement_list.append("recommendations")

        # nm_ids — extract NM IDs from nm_settings
        nm_settings = raw.get("nm_settings", [])
        nm_ids = [nm.get("nm_id") for nm in nm_settings if nm.get("nm_id")]
        nm_count = len(nm_settings)

        return {
            "wb_adv_id": raw.get("id"),
            "name": settings_data.get("name", ""),
            "wb_status": wb_status_code,
            "status": CAMPAIGN_STATUS_MAP.get(wb_status_code, "unknown"),
            "bid_type": bid_type,
            "payment_type": settings_data.get("payment_type", "cpm"),
            "placement_types": placement_list,
            "nm_ids": nm_ids,
            "nm_count": nm_count,
            "created_at": ts.get("created"),
            "started_at": ts.get("started"),
            "updated_at": ts.get("updated"),
            "deleted_at": ts.get("deleted"),
        }
