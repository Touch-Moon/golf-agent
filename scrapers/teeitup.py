"""
Tee It Up booking system scraper.
Courses: John Blumberg Golf Course

Tee It Up (.book.teeitup.com) — React SPA.
직접 fetch 403이므로 Playwright 필수. 네트워크 인터셉트 우선.
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    date_str = target_date.strftime("%Y-%m-%d")
    # Tee It Up SPA는 필터 쿼리(holes/golfers/max)가 있어야 슬롯을 노출함.
    # 필터 없는 bare URL은 빈 상태로 머무름 → 캡처할 JSON 없음.
    url = f"{booking_url.rstrip('/')}?date={date_str}&golfers=4&holes=18&max=999999"
    log(f"  [teeitup] {url}")

    captured: list[dict] = []

    async def handle_response(response):
        if response.status == 200:
            ct = response.headers.get("content-type", "")
            if "json" in ct:
                url_lower = response.url.lower()
                if any(kw in url_lower for kw in ["tee", "slot", "time", "booking", "avail"]):
                    try:
                        captured.append(await response.json())
                    except Exception:
                        pass

    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="networkidle", timeout=35000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"  [teeitup] goto failed: {e}")
        page.remove_listener("response", handle_response)
        return []

    page.remove_listener("response", handle_response)

    # 1) JSON 인터셉트
    for data in captured:
        slots = _parse_json(data, cutoff)
        if slots:
            return slots

    # 2) DOM 파싱 (React SPA)
    slots = await _parse_dom(page, cutoff)
    if slots:
        return slots

    # 3) body 폴백
    return await body_text_fallback(page, cutoff)


def _parse_json(data: dict | list, cutoff: tuple) -> list:
    slots = []
    items = (
        data if isinstance(data, list)
        else data.get("teeTimes", data.get("tee_times", data.get("slots", data.get("times", []))))
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        time_str = item.get("time", item.get("startTime", item.get("start_time", item.get("teeTime", ""))))
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        price = item.get("price", item.get("rate", item.get("green_fee", item.get("greenFee"))))
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        slot = make_slot(time_str, price)
        if slot:
            slots.append(slot)
    return slots


async def _parse_dom(page, cutoff: tuple) -> list:
    slots = []
    selectors = [
        "[class*='tee-time']", "[class*='teetime']", "[class*='TeeTime']",
        "[class*='time-slot']", "[class*='booking']",
        "li[class*='slot']", "div[class*='slot']",
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
