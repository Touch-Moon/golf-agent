"""
Tee It Up booking system scraper — DIRECT Kenna API (브라우저 불필요).
Courses: Kingswood, Maplewood, John Blumberg, Assiniboine, Whispering Winds

핵심 발견(2026-06): Kenna API는 `x-be-alias: {slug}` 헤더 하나만 있으면
Playwright 없이 직접 JSON 호출이 된다. (헤더 누락 시 "x-be-alias is required" 403/400)

흐름:
  1) GET https://phx-api-be-east-1b.kenna.io/alias/{slug}/facilities   → facility id
  2) GET https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=YYYY-MM-DD&facilityIds={id}
        → { ... , teetimes: [...] }
  두 호출 모두 헤더 `x-be-alias: {slug}` 필요.

teetime은 UTC ISO → America/Winnipeg 변환. 가격은 rates[0].(promotion.)greenFeeCart (cents).
slug 은 booking_url 서브도메인에서 추출. API 실패(네트워크/구조 변경) 시 Playwright 폴백.
"""
import asyncio
import re
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from scrapers.base import parse_time, make_slot, body_text_fallback
from logger import log

_WPG_TZ = ZoneInfo("America/Winnipeg")
_KENNA = "https://phx-api-be-east-1b.kenna.io"
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def _slug_from_url(booking_url: str) -> str:
    """https://kingswood-golf-country-club.book.teeitup.com/ → kingswood-golf-country-club"""
    host = urlparse(booking_url).netloc
    if not host:
        return ""
    return host.split(".book.teeitup.com")[0].split(".")[0]


def _fetch_api(slug: str, target_date: date):
    """Kenna API 직접 호출 (블로킹). 성공 시 tee-times JSON, 실패 시 None."""
    headers = {**_BASE_HEADERS, "x-be-alias": slug}
    try:
        # 1) slug → facility id(s)
        fr = requests.get(f"{_KENNA}/alias/{slug}/facilities", headers=headers, timeout=15)
        fr.raise_for_status()
        facilities = fr.json()
        if not isinstance(facilities, list) or not facilities:
            log(f"  [teeitup] no facilities for slug={slug}")
            return None
        fac_ids = ",".join(str(f.get("id")) for f in facilities if f.get("id"))
        if not fac_ids:
            return None

        # 2) tee-times
        date_str = target_date.strftime("%Y-%m-%d")
        tr = requests.get(
            f"{_KENNA}/v2/tee-times",
            params={"date": date_str, "facilityIds": fac_ids},
            headers=headers,
            timeout=20,
        )
        tr.raise_for_status()
        return tr.json()
    except Exception as e:
        log(f"  [teeitup] direct API error (slug={slug}): {e}")
        return None


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    """
    1순위: Kenna API 직접 호출(브라우저 불필요, 빠르고 안정적).
    2순위: API 실패 시 Playwright 폴백(구조 변경 대비).
    page 인자는 폴백 때만 사용(호출부 호환 유지).
    """
    slug = _slug_from_url(booking_url)

    if slug:
        log(f"  [teeitup] direct API slug={slug} date={target_date}")
        data = await asyncio.to_thread(_fetch_api, slug, target_date)
        if data is not None:
            slots = _parse_json(data, cutoff)
            log(f"  [teeitup] API → {len(slots)} slots")
            return slots  # API 성공이면 결과 그대로(0개여도 진짜 0개)

    # API 실패(slug 추출 실패/네트워크/구조 변경) → 기존 Playwright 경로
    log(f"  [teeitup] API unavailable → Playwright fallback")
    return await _scrape_playwright(page, booking_url, target_date, cutoff)


# ─────────────────────────────────────────────────────────────────────────────
# JSON 파서 (기존 로직 유지 — 직접 API/인터셉트 응답 동일 구조)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_json(data, cutoff: tuple) -> list:
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
    if not isinstance(time_raw, str):
        return None
    try:
        dt_utc = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        return dt_utc.astimezone(_WPG_TZ)
    except (ValueError, TypeError):
        return parse_time(time_raw)


# ─────────────────────────────────────────────────────────────────────────────
# Playwright 폴백 (기존 로직)
# ─────────────────────────────────────────────────────────────────────────────
async def _scrape_playwright(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{booking_url.rstrip('/')}?date={date_str}&golfers=4&holes=18&max=999999"
    log(f"  [teeitup] (fallback) {url}")

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
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log(f"  [teeitup] goto warn: {e} — proceeding with captured responses")
    await asyncio.sleep(6)
    page.remove_listener("response", handle_response)
    log(f"  [teeitup] (fallback) captured {len(captured)} JSON responses")

    for data in captured:
        slots = _parse_json(data, cutoff)
        if slots:
            return slots

    slots = await _parse_dom(page, cutoff)
    if slots:
        return slots
    return await body_text_fallback(page, cutoff)


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
