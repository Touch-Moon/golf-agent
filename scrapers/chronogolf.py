"""
Chronogolf booking system scraper.
Courses: Larters at St. Andrews

Chronogolf은 공개 API 엔드포인트를 가지고 있음.
API: GET /api/v1/clubs/{club_id}/tee_times?date=YYYY-MM-DD
"""
import asyncio
import re
from datetime import date

import requests

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log

# Chronogolf API base
_API_BASE = "https://www.chronogolf.com"


def _extract_club_slug(booking_url: str) -> str | None:
    m = re.search(r"/club/([^/?#]+)", booking_url)
    return m.group(1) if m else None


def _fetch_api(club_slug: str, target_date: date, cutoff: tuple) -> list | None:
    """Chronogolf 공개 API 호출."""
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{_API_BASE}/api/v1/clubs/{club_slug}/tee_times"
    headers = {
        "Accept": "application/json",
        "Referer": f"{_API_BASE}/club/{club_slug}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    params = {"date": date_str, "nb_of_holes": 18, "nb_of_players": 1}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
            return _parse_api_json(resp.json(), cutoff)
        log(f"  [chronogolf] API returned {resp.status_code}")
        return None
    except Exception as e:
        log(f"  [chronogolf] API error: {e}")
        return None


def _parse_api_json(data: dict | list, cutoff: tuple) -> list:
    slots = []
    items = data if isinstance(data, list) else data.get("tee_times", [])
    for item in items:
        time_str = item.get("start_time", item.get("time", ""))
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        # Chronogolf API: price in cents or dollars depending on version
        price = item.get("price", item.get("green_fee", item.get("green_fee_amount")))
        try:
            price = float(price) if price is not None else None
            if price and price > 1000:  # 센트 단위 → 달러
                price = price / 100
        except (TypeError, ValueError):
            price = None
        slot = make_slot(time_str, price)
        if slot:
            slots.append(slot)
    return slots


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    log(f"  [chronogolf] {booking_url}")
    club_slug = _extract_club_slug(booking_url)

    # 1) API 시도
    if club_slug:
        slots = _fetch_api(club_slug, target_date, cutoff)
        if slots is not None:
            return slots

    # 2) Playwright 폴백
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{booking_url}?date={date_str}"
    captured: list[dict] = []

    async def handle_response(response):
        if response.status == 200 and "json" in response.headers.get("content-type", ""):
            if "tee_time" in response.url or "teetime" in response.url.lower():
                try:
                    captured.append(await response.json())
                except Exception:
                    pass

    page.on("response", handle_response)
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"  [chronogolf] goto failed: {e}")
        page.remove_listener("response", handle_response)
        return []
    page.remove_listener("response", handle_response)

    for data in captured:
        slots = _parse_api_json(data, cutoff)
        if slots:
            return slots

    # 3) DOM 폴백
    slots = await _parse_dom(page, cutoff)
    if slots:
        return slots
    return await body_text_fallback(page, cutoff)


async def _parse_dom(page, cutoff: tuple) -> list:
    slots = []
    selectors = [
        ".tee-time-card", "[class*='tee-time']", ".slot",
        "[data-testid*='tee']", "[class*='booking']",
    ]
    for selector in selectors:
        elements = await page.query_selector_all(selector)
        if not elements:
            continue
        for el in elements:
            text = (await el.inner_text()).strip()
            time_match = re.search(r"\b(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\b", text)
            if not time_match:
                continue
            dt = parse_time(time_match.group(1))
            if not dt or (dt.hour, dt.minute) >= cutoff:
                continue
            price_match = re.search(r"\$(\d+(?:\.\d{2})?)", text)
            price = float(price_match.group(1)) if price_match else None
            slot = make_slot(time_match.group(1), price)
            if slot:
                slots.append(slot)
        if slots:
            break
    return slots
