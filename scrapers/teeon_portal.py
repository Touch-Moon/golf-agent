"""
TeeOn Portal scraper (admin.teeon.com/portal/).
Courses: Oakwood Golf Course

React SPA. 페이지 로드 시 /api/2024-04/guest/tee-time 호출을 네트워크 인터셉트.
가격은 표시 안 함 (display_online_pricing=0) → fallback_price 사용.
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{booking_url.rstrip('/')}?date={date_str}"
    log(f"  [teeon_portal] {url}")

    captured: list[list] = []

    async def handle_response(response):
        if response.status == 200 and "json" in response.headers.get("content-type", ""):
            if "tee-time" in response.url.lower():
                try:
                    captured.append(await response.json())
                except Exception:
                    pass

    page.on("response", handle_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await asyncio.sleep(4)
    except Exception as e:
        log(f"  [teeon_portal] goto failed: {e}")
        page.remove_listener("response", handle_response)
        return []
    page.remove_listener("response", handle_response)

    # 1) JSON 인터셉트
    for data in captured:
        slots = _parse_tee_times(data, cutoff)
        if slots:
            log(f"  [teeon_portal] 인터셉트 성공: {len(slots)}개")
            return slots

    # 2) body 폴백
    return await body_text_fallback(page, cutoff)


def _parse_tee_times(data: list, cutoff: tuple) -> list:
    if not isinstance(data, list):
        return []
    slots = []
    for item in data:
        if not isinstance(item, dict):
            continue
        time_str = item.get("start_time", "")
        if not time_str:
            continue
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        slot = make_slot(time_str, None)
        if slot:
            slots.append(slot)
    return slots
