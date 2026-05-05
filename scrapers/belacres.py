"""
Bel Acres Golf and Country Club — Playwright + FlareSolverr CF bypass.

Cloudflare Bot Fight Mode blocks direct API calls and Playwright by default.
Strategy: FlareSolverr (nodriver Chrome) solves CF challenge → cf_clearance cookie.
Inject that cookie into the shared Playwright browser → Angular SPA loads normally →
intercept TeeTimes API response (same pattern as cps_golf.py for Bridges).

This avoids the componentid header problem entirely: Angular sets it automatically.
"""
import asyncio
import os
import time
import requests as std_requests
from datetime import date

from logger import log
from scrapers.base import parse_time, make_slot

_BASE = "https://belacres.cps.golf"
_BOOKING_PAGE = _BASE + "/onlineresweb/search-teetime"
_FLARESOLVERR = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")

_MONTH_NAMES = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    log(f"  [belacres] FlareSolverr at {_FLARESOLVERR}")

    # Step 1: FlareSolverr → cf_clearance cookie + User-Agent
    solution = None
    for attempt in range(1, 4):
        try:
            fs_resp = std_requests.post(
                _FLARESOLVERR,
                json={"cmd": "request.get", "url": _BASE + "/", "maxTimeout": 60000},
                timeout=90,
            )
            fs_resp.raise_for_status()
            body = fs_resp.json()
            if body.get("status") == "ok":
                solution = body["solution"]
                break
            log(f"  [belacres] FlareSolverr attempt {attempt}: {body.get('status')}")
        except Exception as e:
            log(f"  [belacres] FlareSolverr attempt {attempt} error: {e}")
        if attempt < 3:
            time.sleep(10)

    if solution is None:
        log(f"  [belacres] FlareSolverr unavailable — 0 slots")
        return []

    cf_cookies = solution.get("cookies", [])
    user_agent = solution.get("userAgent", "")
    log(f"  [belacres] CF bypass OK — {len(cf_cookies)} cookies")

    # Step 2: Inject CF cookies + User-Agent into shared Playwright browser
    cookies_to_add = []
    for c in cf_cookies:
        domain = c.get("domain", ".belacres.cps.golf")
        if not domain.startswith("."):
            domain = "." + domain
        cookies_to_add.append({
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/"),
        })
    if cookies_to_add:
        await page.context.add_cookies(cookies_to_add)
    if user_agent:
        await page.set_extra_http_headers({"User-Agent": user_agent})

    # Step 3: Intercept TeeTimes API response
    captured = []

    async def on_response(resp):
        if "TeeTimes" in resp.url and resp.status == 200:
            log(f"  [belacres] TeeTimes intercepted ({resp.status})")
            try:
                captured.append(await resp.json())
            except Exception:
                pass

    page.on("response", on_response)

    # Step 4: Navigate — CF should accept cf_clearance from same IP
    try:
        await page.goto(_BOOKING_PAGE, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        log(f"  [belacres] goto warn: {e}")

    await asyncio.sleep(5)

    current_url = page.url
    if "challenge" in current_url or "cloudflare" in current_url.lower():
        log(f"  [belacres] CF rechallenge detected — cookie injection insufficient")
        page.remove_listener("response", on_response)
        return []

    log(f"  [belacres] page loaded: {current_url[:80]}")

    # Step 5: Click target date in calendar (same logic as cps_golf.py)
    clicked = await _select_calendar_date(page, target_date)
    log(f"  [belacres] calendar {'clicked' if clicked else 'click failed'}: {target_date}")

    # Wait for TeeTimes response (default date fires 1 response; after click, another)
    target_count = 2 if clicked else 1
    for _ in range(20):
        if len(captured) >= target_count:
            break
        await asyncio.sleep(1)

    page.remove_listener("response", on_response)
    log(f"  [belacres] {len(captured)} TeeTimes response(s) captured")

    if not captured:
        return []
    return _parse(captured[-1], cutoff)


async def _select_calendar_date(page, target_date: date) -> bool:
    """Click target_date in CPS Golf Angular calendar. Same logic as cps_golf.py."""
    for _ in range(3):
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
            return False

        # Advance to next month
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


def _parse(data: dict, cutoff: tuple) -> list:
    slots = []
    seen = set()
    for item in data.get("content", []):
        start = item.get("startTime", "")
        if not start:
            continue
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
            p = (prices[0].get("displayPrice")
                 or prices[0].get("taxInclusivePrice")
                 or prices[0].get("price"))
            try:
                price = float(p) if p is not None else None
            except (TypeError, ValueError):
                price = None

        slot = make_slot(time_part, price)
        if slot:
            slots.append(slot)
    return slots
