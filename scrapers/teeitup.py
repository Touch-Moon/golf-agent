"""
Tee It Up booking system scraper.
Courses: Kingswood, Maplewood, John Blumberg, Assiniboine, Whispering Winds

Tee It Up (.book.teeitup.com) — React SPA backed by Kenna API
(`phx-api-be-east-1b.kenna.io/v2/tee-times`). 직접 fetch 403이므로 Playwright 필수.
네트워크 응답에서 JSON 인터셉트.

API 응답 구조:
  list[1]
    └─ { dayInfo, teetimes: list[N], courseId, ... }
        └─ teetimes[i]: { teetime: "2026-05-09T14:08:00.000Z" (UTC ISO),
                          rates: [{ greenFeeCart: 7000 (cents),
                                    promotion: { greenFeeCart: 5950 } }],
                          minPlayers, maxPlayers, ... }

⚠️ teetime은 UTC. 위니펙 로컬(CDT/CST)로 변환 필요.
"""
import asyncio
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log

_WPG_TZ = ZoneInfo("America/Winnipeg")


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

    # TeeItUp SPA는 networkidle이 안 떨어짐 (analytics/소켓 ping 지속)
    # → domcontentloaded로 진입한 뒤 sleep 동안 API 응답이 도착할 시간을 주고,
    #   timeout이 떨어져도 이미 캡처된 JSON을 파싱.
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log(f"  [teeitup] goto warn: {e} — proceeding with captured responses")
    await asyncio.sleep(6)

    page.remove_listener("response", handle_response)
    log(f"  [teeitup] captured {len(captured)} JSON responses")

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


def _parse_json(data, cutoff: tuple) -> list:
    """
    Kenna API 응답 구조: list[1] of facility wrappers, each with .teetimes[].
    teetime은 UTC ISO → 위니펙 로컬 변환. 가격은 rates[0].promotion.greenFeeCart
    (없으면 rates[0].greenFeeCart) — 단위는 cents.
    """
    facilities = data if isinstance(data, list) else [data]
    slots = []
    seen = set()

    for facility in facilities:
        if not isinstance(facility, dict):
            continue
        teetimes = (
            facility.get("teetimes") or facility.get("teeTimes")
            or facility.get("times") or facility.get("slots") or []
        )
        for tt in teetimes:
            if not isinstance(tt, dict):
                continue
            time_raw = tt.get("teetime") or tt.get("startTime") or tt.get("time")
            if not time_raw:
                continue
            dt_local = _to_local(time_raw)
            if dt_local is None:
                continue
            if (dt_local.hour, dt_local.minute) >= cutoff:
                continue
            key = dt_local.strftime("%H:%M")
            if key in seen:
                continue
            seen.add(key)

            price = None
            is_hot_deal = False
            rates = tt.get("rates") or []
            if rates and isinstance(rates[0], dict):
                rate = rates[0]
                promo = rate.get("promotion") or {}
                cents = promo.get("greenFeeCart") or rate.get("greenFeeCart")
                if cents:
                    try:
                        price = float(cents) / 100.0
                    except (TypeError, ValueError):
                        price = None
                is_hot_deal = bool(rate.get("showAsHotDeal"))

            slots.append({"time": key, "price": price, "is_hot_deal": is_hot_deal})

    return slots


def _to_local(time_raw) -> datetime | None:
    """ISO UTC 문자열 → America/Winnipeg datetime."""
    if not isinstance(time_raw, str):
        return None
    try:
        # "2026-05-09T14:08:00.000Z" 또는 "...+00:00"
        dt_utc = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        return dt_utc.astimezone(_WPG_TZ)
    except (ValueError, TypeError):
        # HH:MM 등 단순 시간 문자열은 fallback (drift 방지용)
        dt = parse_time(time_raw)
        return dt


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
