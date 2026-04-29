"""
CPS Golf booking system scraper.
Courses: Bridges Golf Course

CPS Golf (.cps.golf domain) — Angular SPA. TeeTimes 데이터는 비동기 API로 로드됨.
실제 API: /onlineres/onlineapi/api/v1/onlinereservation/TeeTimes?searchDate=...
"""
import asyncio
from datetime import date

from scrapers.base import parse_time, make_slot
from logger import log


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    date_str = target_date.strftime("%Y-%m-%d")
    sep = "&" if "?" in booking_url else "?"
    url = f"{booking_url}{sep}Date={date_str}"
    log(f"  [cps_golf] {url}")

    captured: list = []

    async def on_response(resp):
        if "TeeTimes" in resp.url and resp.status == 200:
            try:
                captured.append(await resp.json())
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log(f"  [cps_golf] goto failed: {e}")
        page.remove_listener("response", on_response)
        return []

    # SPA 가 TeeTimes API 호출할 때까지 대기 (최대 25초)
    for _ in range(25):
        if captured:
            break
        await asyncio.sleep(1)

    page.remove_listener("response", on_response)

    if not captured:
        log(f"  [cps_golf] TeeTimes API 응답 없음")
        return []

    return _parse_teetimes(captured[0], cutoff)


def _parse_teetimes(data: dict, cutoff: tuple) -> list:
    slots = []
    seen = set()
    for item in data.get("content", []):
        start = item.get("startTime", "")
        if not start:
            continue
        # ISO datetime: "2026-05-02T08:21:00" → "08:21"
        time_part = start.split("T")[1][:5] if "T" in start else start
        dt = parse_time(time_part)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        if time_part in seen:
            continue
        seen.add(time_part)

        prices = item.get("shItemPrices", [])
        price = None
        if prices:
            p = prices[0].get("displayPrice") or prices[0].get("taxInclusivePrice") or prices[0].get("price")
            try:
                price = float(p) if p is not None else None
            except (TypeError, ValueError):
                price = None

        slot = make_slot(time_part, price)
        if slot:
            slots.append(slot)
    return slots
