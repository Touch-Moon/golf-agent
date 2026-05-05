"""
GolfNow scraper — API 우선, Playwright 폴백.
"""
import asyncio
import re
from datetime import date

import requests

from scrapers.base import parse_time, make_slot
from logger import log

_GOLFNOW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def fetch_api(facility_id: str, slug: str, target_date: date, cutoff: tuple) -> list | None:
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"https://www.golfnow.com/tee-times/facility/{facility_id}-{slug}/search"
    headers = {**_GOLFNOW_HEADERS, "Referer": url}
    # players=4 → 4명 들어갈 수 있는 슬롯만 응답
    params  = {"date": date_str, "time": "all", "players": 4, "holes": 2, "sortby": "Date"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200 and "json" in resp.headers.get("Content-Type", ""):
            return _parse_json(resp.json(), cutoff)
        return None
    except Exception as e:
        log(f"  [golfnow] API failed for {slug}: {e}")
        return None


def _parse_json(data: dict, cutoff: tuple) -> list:
    slots = []
    tee_times = data.get("TeeTimes", data.get("teetimes", []))
    for tt in tee_times:
        time_str = tt.get("Time", tt.get("time", ""))
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        rates = tt.get("Rates", tt.get("rates", [{}]))
        price = None
        for rate in rates:
            p = rate.get("Price", rate.get("price", rate.get("greenFeeWalking")))
            if p is not None:
                price = float(p)
                break
        deal_type = str(tt.get("DealType", tt.get("promotionName", "")))
        slot = make_slot(time_str, price, is_hot_deal="hot" in deal_type.lower())
        if slot:
            slots.append(slot)
    return slots


async def scrape_playwright(page, facility_id: str, slug: str, target_date: date, cutoff: tuple) -> list | None:
    date_str = target_date.strftime("%Y-%m-%d")
    url = (
        f"https://www.golfnow.com/tee-times/facility/{facility_id}-{slug}/search"
        f"#date={date_str}&time=all&players=4&holes=2"
    )
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector(
            "[class*='tee-time'], [class*='TeeTimes'], [data-testid*='teetime']",
            timeout=15000,
        )
    except Exception as e:
        log(f"  [golfnow] Playwright failed for {slug}: {e}")
        return None

    cards = await page.query_selector_all(
        "[class*='tee-time-card'], [class*='rate-row'], .time-meridiem"
    )
    slots = []
    for card in cards:
        time_el  = await card.query_selector("[class*='time'], [class*='Time'], time")
        price_el = await card.query_selector("[class*='price'], [class*='Price'], [class*='cost']")
        if time_el and price_el:
            time_text  = (await time_el.inner_text()).strip()
            price_text = (await price_el.inner_text()).strip()
            dt = parse_time(time_text)
            if dt and (dt.hour, dt.minute) < cutoff:
                try:
                    price_val = float(re.sub(r"[^\d.]", "", price_text))
                    slot = make_slot(time_text, price_val)
                    if slot:
                        slots.append(slot)
                except ValueError:
                    pass
    return slots or None
