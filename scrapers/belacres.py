"""
Bel Acres Golf and Country Club — CPS Golf API via FlareSolverr CF bypass.

Cloudflare Bot Fight Mode on belacres.cps.golf blocks RegisterTransactionId POST
even inside Playwright. Fix: FlareSolverr (nodriver-based headless Chrome) solves
the CF JS challenge and returns cf_clearance + User-Agent. Subsequent API calls
from the same IP with those credentials bypass CF.

API flow:
  1. FlareSolverr GET https://belacres.cps.golf/ → cf_clearance cookie + UA
  2. POST /identityapi/myconnect/token/short → Bearer token
  3. POST /onlineres/.../RegisterTransactionId → transactionId
  4. GET  /onlineres/.../TeeTimes → slots
"""
import os
import time
import uuid
import requests
from datetime import date

from scrapers.base import parse_time, make_slot
from logger import log

_BASE = "https://belacres.cps.golf"
_WEB_SITE_ID = "b73559ce-2c3a-41f8-ac53-08da31cff8d4"
_COURSE_ID = 1
_FLARESOLVERR = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    log(f"  [belacres] FlareSolverr at {_FLARESOLVERR}")

    # FlareSolverr may still be initializing — retry up to 3×
    solution = None
    for attempt in range(1, 4):
        try:
            fs_resp = requests.post(
                _FLARESOLVERR,
                json={"cmd": "request.get", "url": _BASE + "/", "maxTimeout": 60000},
                timeout=90,
            )
            fs_resp.raise_for_status()
            body = fs_resp.json()
            if body.get("status") == "ok":
                solution = body["solution"]
                break
            log(f"  [belacres] FlareSolverr attempt {attempt}: status={body.get('status')}")
        except Exception as e:
            log(f"  [belacres] FlareSolverr attempt {attempt} error: {e}")
        if attempt < 3:
            time.sleep(10)

    if solution is None:
        log(f"  [belacres] FlareSolverr unavailable — 0 slots")
        return []

    cf_cookies = {c["name"]: c["value"] for c in solution.get("cookies", [])}
    user_agent = solution.get("userAgent", "Mozilla/5.0")
    log(f"  [belacres] CF bypass OK — {len(cf_cookies)} cookies")

    headers_base = {
        "User-Agent": user_agent,
        "Origin": _BASE,
        "Referer": _BASE + "/onlineresweb/search-teetime",
        "client-id": "onlineresweb",
    }

    # Step 2: token (multipart/form-data)
    try:
        tok_resp = requests.post(
            f"{_BASE}/identityapi/myconnect/token/short",
            files={
                "client_id": (None, "onlinereswebshortlived"),
                "scope": (None, "onlineresweb"),
            },
            headers={**headers_base, "x-requestid": str(uuid.uuid4())},
            cookies=cf_cookies,
            timeout=20,
        )
        tok_data = tok_resp.json()
        token = tok_data.get("access_token")
        if not token:
            log(f"  [belacres] token missing — {tok_resp.status_code}: {tok_resp.text[:120]}")
            return []
        log(f"  [belacres] token OK ({tok_resp.status_code})")
    except Exception as e:
        log(f"  [belacres] token error: {e}")
        return []

    auth_headers = {
        **headers_base,
        "Authorization": f"Bearer {token}",
        "x-requestid": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Step 3: RegisterTransactionId
    try:
        tx_resp = requests.post(
            f"{_BASE}/onlineres/onlineapi/api/v1/onlinereservation/RegisterTransactionId",
            params={"webSiteId": _WEB_SITE_ID},
            headers=auth_headers,
            cookies=cf_cookies,
            timeout=20,
        )
        if tx_resp.status_code != 200:
            log(f"  [belacres] RegisterTransactionId {tx_resp.status_code}: {tx_resp.text[:120]}")
            return []
        tx_id = tx_resp.text.strip().strip('"')
        log(f"  [belacres] tx_id={tx_id[:12]}…")
    except Exception as e:
        log(f"  [belacres] RegisterTransactionId error: {e}")
        return []

    # Step 4: TeeTimes
    date_str = target_date.strftime("%Y-%m-%dT00:00:00")
    try:
        tt_resp = requests.get(
            f"{_BASE}/onlineres/onlineapi/api/v1/onlinereservation/TeeTimes",
            params={
                "webSiteId": _WEB_SITE_ID,
                "searchDate": date_str,
                "numberOfPlayers": 4,
                "numberOfHoles": 18,
                "courseIds": _COURSE_ID,
                "transactionId": tx_id,
            },
            headers=auth_headers,
            cookies=cf_cookies,
            timeout=20,
        )
        log(f"  [belacres] TeeTimes {tt_resp.status_code}")
        if tt_resp.status_code != 200:
            log(f"  [belacres] TeeTimes body: {tt_resp.text[:200]}")
            return []
        return _parse(tt_resp.json(), cutoff)
    except Exception as e:
        log(f"  [belacres] TeeTimes error: {e}")
        return []


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
