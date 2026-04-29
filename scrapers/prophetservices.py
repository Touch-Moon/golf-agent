"""
ProphetServices booking system scraper.
Courses: Quarry Oaks Golf Course

ProphetServices (secure.east.prophetservices.com) — ASP.NET 사이트.
직접 검색 URL: /Home/nIndex?CourseId=2,3,1&Date=YYYY-M-D&Time=AnyTime&Player=4&Hole=Any
결과 페이지에 시간/가격이 텍스트로 노출됨 (시간 단위 옆에 $XX.XX 가격).
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time, make_slot
from logger import log


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    # 직접 검색 URL 구성 (날짜는 zero-padding 없음)
    base = booking_url.rstrip("/").split("/Home/")[0]  # 베이스 도메인만 추출
    date_param = f"{target_date.year}-{target_date.month}-{target_date.day}"
    url = f"{base}/Home/nIndex?CourseId=2,3,1&Date={date_param}&Time=AnyTime&Player=99&Hole=Any"
    log(f"  [prophetservices] {url}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        log(f"  [prophetservices] goto failed: {e}")
        return []

    body = await page.inner_text("body")
    return _parse_body(body, cutoff)


def _parse_body(body: str, cutoff: tuple) -> list:
    """
    body 안의 시간 + 가격 페어를 추출.
    패턴: "9:06 AM | $76.00 | Cart Price Included | ..."
    """
    slots = []
    seen = set()
    pattern = re.compile(
        r"(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*[|\s]*\$?(\d+(?:\.\d{2})?)?",
        re.IGNORECASE,
    )
    for m in pattern.finditer(body):
        time_str = m.group(1).strip()
        price_str = m.group(2)
        dt = parse_time(time_str)
        if not dt or (dt.hour, dt.minute) >= cutoff:
            continue
        key = dt.strftime("%H:%M")
        if key in seen:
            continue
        seen.add(key)
        slot = make_slot(time_str, None)
        if not slot:
            continue
        if price_str:
            try:
                slot["price"] = float(price_str)
            except ValueError:
                pass
        slots.append(slot)
    return slots
