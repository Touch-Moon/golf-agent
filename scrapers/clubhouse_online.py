"""
ClubhouseOnline (e3) booking system scraper.
Courses: Rossmere Country Club, St. Boniface Golf Club

ASP.NET WebForms — PublicTeeTimes/TeeSheet(.aspx)
날짜 파라미터: ?date=YYYY-MM-DD
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log


def _dated_url(booking_url: str, target_date: date) -> str:
    date_str = target_date.strftime("%Y-%m-%d")
    sep = "&" if "?" in booking_url else "?"
    return f"{booking_url}{sep}date={date_str}"


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    url = _dated_url(booking_url, target_date)
    log(f"  [clubhouse_online] {url}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        log(f"  [clubhouse_online] goto failed: {e}")
        return []

    slots = await _parse_dom(page, cutoff)
    if slots:
        return slots
    return await body_text_fallback(page, cutoff)


async def _parse_dom(page, cutoff: tuple) -> list:
    slots = []
    # ClubhouseOnline e3 tee sheet selectors
    selectors = [
        ".teeTimeItem",
        ".tee-time-item",
        "tr.teetime",
        "tr[id*='teetime']",
        ".TeeTimeAvailable",
        "[class*='TeeTime']",
        "table#teeSheet tr",
        ".teesheet-row",
    ]
    for selector in selectors:
        rows = await page.query_selector_all(selector)
        if not rows:
            continue
        for row in rows:
            text = (await row.inner_text()).strip()
            time_match = re.search(r"\b(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\b", text)
            if not time_match:
                continue
            dt = parse_time(time_match.group(1))
            if not dt or (dt.hour, dt.minute) >= cutoff:
                continue
            price_match = re.search(r"\$(\d+(?:\.\d{2})?)", text)
            price = float(price_match.group(1)) if price_match else None
            # ClubhouseOnline는 예약 가능한 슬롯만 표시되는 경우가 많음
            # "Book" 또는 "Select" 버튼 존재 여부로 가용성 확인
            book_btn = await row.query_selector("a[href*='book'], button, input[type='submit']")
            if book_btn is None:
                continue
            slot = make_slot(time_match.group(1), price)
            if slot:
                slots.append(slot)
        if slots:
            break
    return slots
