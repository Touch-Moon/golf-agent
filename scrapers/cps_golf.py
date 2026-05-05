"""
CPS Golf booking system scraper.
Courses: Bridges Golf Course

CPS Golf (.cps.golf domain) — Angular SPA. TeeTimes 데이터는 비동기 API로 로드됨.
실제 API: /onlineres/onlineapi/api/v1/onlinereservation/TeeTimes?searchDate=...

주의: SPA는 URL의 Date= 파라미터를 무시함. 날짜는 캘린더 클릭으로만 변경됨.
"""
import asyncio
from datetime import date

from scrapers.base import parse_time, make_slot
from logger import log

_MONTH_NAMES = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12,
}


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    # Angular SPA는 URL의 Date= 파라미터를 무시 → base URL만 사용
    log(f"  [cps_golf] {booking_url}")

    captured: list = []

    async def on_response(resp):
        if "RegisterTransaction" in resp.url or "TeeTimes" in resp.url:
            req_headers = resp.request.headers
            snippet = resp.url.split('?')[0].split('/')[-1]
            log(f"  [cps_golf] {snippet} status={resp.status} componentid={req_headers.get('componentid','—')} client-id={req_headers.get('client-id','—')}")
        if "TeeTimes" in resp.url and resp.status == 200:
            try:
                captured.append(await resp.json())
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(booking_url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log(f"  [cps_golf] goto failed: {e}")
        page.remove_listener("response", on_response)
        return []

    # 초기 렌더링 대기 (default 날짜 API 호출 포함)
    await asyncio.sleep(4)

    # 캘린더에서 target_date 클릭
    clicked = await _select_calendar_date(page, target_date)
    if clicked:
        log(f"  [cps_golf] Calendar clicked: {target_date}")
    else:
        log(f"  [cps_golf] Calendar click failed — falling back to default date data")

    # 날짜 클릭 후 새 API 응답 대기 (최대 20초)
    expected_count = 2 if clicked else 1
    for _ in range(20):
        if len(captured) >= expected_count:
            break
        await asyncio.sleep(1)

    page.remove_listener("response", on_response)

    if not captured:
        log(f"  [cps_golf] TeeTimes API 응답 없음")
        return []

    # 마지막 캡처 = 날짜 클릭 후 응답 (클릭 성공 시)
    return _parse_teetimes(captured[-1], cutoff)


async def _select_calendar_date(page, target_date: date) -> bool:
    """
    CPS Golf Angular 캘린더에서 target_date 클릭.
    필요 시 달 이동 (최대 3회). 성공 시 True.
    """
    for _ in range(3):
        # 현재 표시 달/년 파싱 ("May 2026" 형식 텍스트 노드 탐색)
        displayed_month, displayed_year = None, None
        try:
            month_text = await page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT
                    );
                    let node;
                    while ((node = walker.nextNode())) {
                        const t = node.textContent.trim();
                        if (/^[A-Z][a-z]+ \\d{4}$/.test(t)) return t;
                    }
                    return null;
                }
            """)
            if month_text:
                parts = month_text.split()
                displayed_month = _MONTH_NAMES.get(parts[0])
                displayed_year = int(parts[1])
        except Exception:
            pass

        # 표시 달 == target 달이면 날짜 클릭 시도
        if displayed_month is None or (
            displayed_month == target_date.month and displayed_year == target_date.year
        ):
            day_str = str(target_date.day)
            spans = await page.query_selector_all("span.day-background-upper")
            for span in spans:
                cls = await span.get_attribute("class") or ""
                txt = (await span.inner_text()).strip()
                if (
                    txt == day_str
                    and "is-visible" in cls
                    and "is-disabled" not in cls
                    and "is-prev-month" not in cls
                    and "is-next-month" not in cls
                ):
                    await span.click()
                    return True
            return False  # 해당 날짜 없음 (disabled 또는 범위 밖)

        # target 달이 뒤면 다음 달로 이동
        buttons = await page.query_selector_all("button.mat-raised-button")
        moved = False
        for btn in buttons:
            txt = (await btn.inner_text()).strip()
            cls = await btn.get_attribute("class") or ""
            if ">" in txt and "mat-button-disabled" not in cls:
                await btn.click()
                await asyncio.sleep(1)
                moved = True
                break
        if not moved:
            break

    return False


def _parse_teetimes(data: dict, cutoff: tuple) -> list:
    slots = []
    seen = set()
    for item in data.get("content", []):
        start = item.get("startTime", "")
        if not start:
            continue
        # ISO datetime: "2026-05-09T08:21:00" → "08:21"
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
