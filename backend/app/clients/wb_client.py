from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

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

    Confirmed working endpoints (advert-api.wildberries.ru):
    - GET    /adv/v1/promotion/count          — campaign IDs by type/status
    - GET    /api/advert/v2/adverts?ids=...    — campaign details (max 50)
    - POST   /adv/v2/seacat/save-ad            — create campaign
    - GET    /adv/v0/start?id=...              — start campaign
    - GET    /adv/v0/pause?id=...              — pause campaign
    - DELETE /adv/v1/advert/{advertId}          — delete campaign
    - POST   /adv/v0/normquery/list             — search cluster list (returns items with shows/clicks)
    - POST   /adv/v0/normquery/bids             — set cluster bid
    - POST   /adv/v0/normquery/set-minus        — exclude cluster (minus-phrase)
    - GET    /adv/v0/normquery/get-minus        — get minus-clusters
    - GET    /api/advert/v0/bids/recommendations — recommended bids
    - POST   /api/advert/v1/bids/min            — minimal bids

    NOTE: WB advertising API does NOT expose a dedicated statistics/report
    endpoint. Campaign-level stats (views, clicks, cost over time) are not
    available through advert-api.wildberries.ru.
    """

    def __init__(self, api_token: str, base_url: str | None = None):
        self.api_token = api_token
        self.base_url = (base_url or "https://advert-api.wildberries.ru").rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # 1. Get campaign IDs
    # ------------------------------------------------------------------
    async def get_campaign_ids(self) -> list[int]:
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

    # ------------------------------------------------------------------
    # 2. Get campaign details (max 50 IDs per call)
    # ------------------------------------------------------------------
    async def get_campaign_details(self, advert_ids: list[int]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for i in range(0, len(advert_ids), 50):
            chunk = advert_ids[i : i + 50]
            ids_str = ",".join(str(x) for x in chunk)
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

    # ------------------------------------------------------------------
    # Main entry-point
    # ------------------------------------------------------------------
    async def get_campaigns(self) -> list[dict[str, Any]]:
        ids = await self.get_campaign_ids()
        if not ids:
            return []
        return await self.get_campaign_details(ids)

    # ------------------------------------------------------------------
    # Combined: campaigns + clusters (for data collection)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Campaign statistics: POST /adv/v1/normquery/stats
    # ------------------------------------------------------------------
    async def get_campaign_stats(
        self, advert_id: int, nm_id: int, from_date: str, to_date: str
    ) -> list[dict[str, Any]]:
        """Fetch daily cluster-level stats for a campaign.

        Returns list of daily stat dicts:
        [{"date": "2026-01-27", "normQuery": "...", "views": N, "clicks": N,
          "ctr": N, "orders": N, "spend": N, "cpc": N, "cpm": N, "avgPos": N, ...}]
        """
        url = f"{self.base_url}/adv/v1/normquery/stats"
        body = {
            "from": from_date,
            "to": to_date,
            "items": [{"advertId": advert_id, "nmId": nm_id}],
        }

        max_retries = 3
        for attempt in range(max_retries + 1):
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, headers=self._headers(), json=body, timeout=30.0
                )

            if resp.status_code == 200:
                data = resp.json()
                results = []
                items = data.get("items") or []
                for item in items:
                    for day_stat in item.get("dailyStats", []):
                        stat = day_stat.get("stat", {})
                        stat["date"] = day_stat.get("date", "")
                        stat["nmId"] = item.get("nmId")
                        stat["advertId"] = item.get("advertId")
                        results.append(stat)
                return results

            if resp.status_code == 429 and attempt < max_retries:
                import random
                wait = (2 ** attempt) + random.uniform(0, 0.5)
                logger.debug(
                    "get_campaign_stats %d/%d: 429, retry %d in %.1fs",
                    advert_id, nm_id, attempt + 1, wait,
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                if attempt == max_retries:
                    logger.warning(
                        f"get_campaign_stats {advert_id}/{nm_id}: 429 after {max_retries} retries"
                    )
                else:
                    logger.warning(
                        f"get_campaign_stats {advert_id}/{nm_id}: {resp.status_code}, {resp.text[:200]}"
                    )
                return []

        return []
        logger.warning(f"get_campaign_stats {advert_id}/{nm_id}: {resp.status_code}, {resp.text[:200]}")
        return []

    # ------------------------------------------------------------------
    # Combined: campaigns + cluster stats (for data collection)
    # ------------------------------------------------------------------
    async def get_campaigns_with_stats(self, days: int = 30) -> list[dict[str, Any]]:
        """Fetch campaigns with cluster lists and daily stats using parallel requests."""
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

        semaphore = asyncio.Semaphore(3)

        async def fetch_campaign_data(camp: dict) -> dict:
            adv_id = camp.get("wb_adv_id")
            nm_ids = camp.get("nm_ids", [])

            async with semaphore:
                clusters = await self.get_clusters(adv_id)
                camp["clusters"] = clusters

                if nm_ids:
                    nm_id = nm_ids[0]
                    daily_stats = await self.get_campaign_stats(adv_id, nm_id, from_date, to_date)
                    camp["daily_stats"] = daily_stats
                else:
                    camp["daily_stats"] = []

            return camp

        for camp in stats_campaigns:
            await fetch_campaign_data(camp)
            await asyncio.sleep(1.5)

        return campaigns

    # ------------------------------------------------------------------
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
        if placement_types:
            body["placement_types"] = placement_types

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return {"id": resp.json()}
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------
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
            "nm_ids": nm_ids,
            "payment_type": payment_type,
            "placement_types": placement_types,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers(), json=body, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------
    # Clusters: POST /adv/v0/normquery/list
    # ------------------------------------------------------------------
    async def get_clusters(self, advert_id: int) -> list[dict[str, Any]]:
        """Return list of search clusters (normquerys) for a campaign.

        POST /adv/v0/normquery/list returns {"items": [...]} or {"items": null}.
        Each item has shows, clicks, ctr, bid, etc.
        """
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

    # ------------------------------------------------------------------
    # Cluster/keyword stats — stubs (data_collector handles gracefully)
    # ------------------------------------------------------------------
    async def get_cluster_stats(self, campaign_id: int) -> list[dict[str, Any]]:
        """Fetch cluster-level stats for a campaign.
        Not exposed by WB advertising API. Returns empty list.
        """
        return []

    async def get_cluster_bids(self, campaign_id: int) -> list[dict[str, Any]]:
        """Fetch cluster-level bids for a campaign.
        Not exposed by WB advertising API. Returns empty list.
        """
        return []

    # ------------------------------------------------------------------
    # Cluster bid — POST /adv/v0/normquery/bids
    # ------------------------------------------------------------------
    async def set_cluster_bid(self, advert_id: int, cluster_id: int, bid: float) -> dict[str, Any]:
        """Set bid for a specific cluster."""
        url = f"{self.base_url}/adv/v0/normquery/bids"
        body = {"advertId": advert_id, "clusterId": cluster_id, "bid": bid}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self._headers(), json=body, timeout=30.0)
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------
    # Minus clusters — POST /adv/v0/normquery/set-minus
    # ------------------------------------------------------------------
    async def set_minus_cluster(self, advert_id: int, cluster_ids: list[str]) -> dict[str, Any]:
        """Add clusters to minus-list."""
        url = f"{self.base_url}/adv/v0/normquery/set-minus"
        body = {"advertId": advert_id, "ids": cluster_ids}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self._headers(), json=body, timeout=30.0)
        return {"status": resp.status_code, "data": resp.text[:500]}

    # ------------------------------------------------------------------
    # Get minus clusters — GET /adv/v0/normquery/get-minus
    # ------------------------------------------------------------------
    async def get_minus_clusters(self, advert_id: int) -> list[str]:
        """Get list of minus-clusters for a campaign."""
        url = f"{self.base_url}/adv/v0/normquery/get-minus"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"advertId": advert_id}, timeout=15.0
            )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("clusters", [])
        return []

    # ------------------------------------------------------------------
    # Recommended bids — GET /api/advert/v0/bids/recommendations
    # ------------------------------------------------------------------
    async def get_bids_recommendations(self, advert_id: int) -> dict[str, Any]:
        """Get recommended bid changes from WB API."""
        url = f"{self.base_url}/api/advert/v0/bids/recommendations"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"advertId": advert_id}, timeout=30.0
            )
        if resp.status_code == 200:
            return resp.json()
        return {"status": resp.status_code, "error": resp.text[:300]}

    # ------------------------------------------------------------------
    # Start / Pause / Delete
    # ------------------------------------------------------------------
    async def start_campaign(self, advert_id: int) -> int:
        url = f"{self.base_url}/adv/v0/start"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        return resp.status_code

    async def pause_campaign(self, advert_id: int) -> int:
        url = f"{self.base_url}/adv/v0/pause"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers(), params={"id": advert_id}, timeout=30.0
            )
        return resp.status_code

    async def delete_campaign(self, advert_id: int) -> int:
        url = f"{self.base_url}/adv/v1/advert/{advert_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                url, headers=self._headers(), timeout=30.0
            )
        return resp.status_code

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
