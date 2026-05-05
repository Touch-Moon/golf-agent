"""
ClubhouseOnline (Jonas Club Software / Kentico) PublicTeeTimes scraper.
Courses: Rossmere Country Club, St. Boniface Golf Club

ASP.NET WebForms (Kentico CMS). URL의 ?date= 파라미터는 무시됨 — 페이지 상단의
day-of-week 탭을 클릭해야 함 (`__doPostBack` 트리거).

날짜 탭 텍스트 형식: "Sat\nMay 9" → 정규화 후 "SatMay 9" 또는 "Sat May 9"로 매칭.
탭 클릭 후 슬롯이 row 단위로 렌더링됨. 가격은 노출되지 않음 — fallback_price 사용.
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time, make_slot
from logger import log

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    log(f"  [clubhouse_online] {booking_url}")

    try:
        await page.goto(booking_url, timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"  [clubhouse_online] goto failed: {e}")
        return []

    # 날짜 탭 텍스트: "Sat May 9" — Playwright text 매칭은 공백 자유로움
    day = _DAY_NAMES[target_date.weekday()]
    month = _MONTH_NAMES[target_date.month - 1]
    tab_text = f"{day} {month} {target_date.day}"
    tab_pattern = re.compile(rf"{day}\s*{month}\s*{target_date.day}\b", re.I)

    try:
        await page.click(f"text=/{day}\\s*{month}\\s*{target_date.day}\\b/i", timeout=8000)
        log(f"  [clubhouse_online] date tab clicked: {tab_text}")
    except Exception as e:
        log(f"  [clubhouse_online] date tab '{tab_text}' click failed: {e}")
        return []

    # __doPostBack은 XHR — 응답 후 DOM 갱신 대기
    await asyncio.sleep(4)

    body = await page.inner_text("body")
    if "no tee times available" in body.lower():
        log(f"  [clubhouse_online] no public tee times on {target_date}")
        return []

    return _parse_body(body, cutoff)


def _parse_body(body: str, cutoff: tuple) -> list:
    """body 텍스트에서 'HH:MM AM/PM' 패턴 추출."""
    slots = []
    seen = set()
    for m in re.finditer(r"\b(\d{1,2}:\d{2}\s*[AaPp][Mm])\b", body):
        time_str = m.group(1).strip()
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        key = dt.strftime("%H:%M")
        if key in seen:
            continue
        seen.add(key)

        # 가격은 ClubhouseOnline 공개 시트에 노출 안 됨 → fallback_price 사용
        slot = make_slot(time_str, None)
        if slot:
            slots.append(slot)
    return slots
