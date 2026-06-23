"""
CPS Golf (.cps.golf) — DIRECT API (브라우저 불필요).
Courses: Bridges, Bel Acres (둘 다 동일 흐름).

핵심 발견 (2026-06 실측):
  단명 토큰을 시크릿 없이 발급받고, 최소 헤더 + transactionId 만으로 TeeTimes JSON 직접 호출 가능.
  Bel Acres 의 Cloudflare 는 curl_cffi 의 브라우저 임퍼소네이트(TLS 지문 위장)로 우회 시도.

흐름:
  1) POST https://{host}/identityapi/myconnect/token/short
        form: grant_type=client_credentials, client_id=onlinereswebshortlived
        → { access_token }   (시크릿 불필요, 수명 ~10분)
  2) POST https://{host}/onlineres/onlineapi/api/v1/onlinereservation/RegisterTransactionId?transactionId={uuid}
        json: {"transactionId": uuid}   → "true"
  3) GET  .../onlinereservation/TeeTimes?searchDate={Day Mon DD YYYY}&courseIds=1&transactionId={uuid}&holes=18&...
        → { content: [ {startTime, shItemPrices:[{displayPrice}], ...}, ... ] }

필수 헤더(최소): Authorization, client-id:onlineresweb, X-TerminalId:3, x-requestid:{uuid},
                 x-componentid:1, x-siteid:1, x-productid:1, x-moduleid:7, Accept
(x-websiteid / x-timezone* 는 불필요 — 실측 확인)
"""
import asyncio
import uuid as _uuid
from datetime import date
from urllib.parse import urlparse

from curl_cffi import requests as creq

from logger import log


def _host(booking_url: str) -> str:
    return urlparse(booking_url).netloc  # e.g. bridgesgccan.cps.golf / belacres.cps.golf


def _fetch(host: str, target_date: date, cutoff: tuple) -> list:
    base = f"https://{host}"
    api = base + "/onlineres/onlineapi/api/v1/onlinereservation"
    # impersonate="chrome" → 실제 크롬 TLS/헤더 지문 → Cloudflare Bot Fight Mode 우회 시도
    s = creq.Session(impersonate="chrome", timeout=25)
    try:
        # 1) 단명 토큰 (시크릿 불필요)
        tr = s.post(
            base + "/identityapi/myconnect/token/short",
            data={"grant_type": "client_credentials", "client_id": "onlinereswebshortlived"},
        )
        tok = (tr.json() or {}).get("access_token")
        if not tok:
            log(f"  [cps_golf] no token ({tr.status_code}) {host}")
            return []

        tid = str(_uuid.uuid4())
        headers = {
            "Authorization": "Bearer " + tok,
            "client-id": "onlineresweb",
            "X-TerminalId": "3",
            "x-requestid": str(_uuid.uuid4()),
            "x-componentid": "1",
            "x-siteid": "1",
            "x-productid": "1",
            "x-moduleid": "7",
            "Accept": "application/json, text/plain, */*",
        }

        # 2) 트랜잭션 등록
        s.post(
            f"{api}/RegisterTransactionId",
            params={"transactionId": tid},
            json={"transactionId": tid},
            headers=headers,
        )

        # 3) 티타임
        date_str = target_date.strftime("%a %b %d %Y")  # "Sat Jun 27 2026"
        params = {
            "searchDate": date_str, "holes": "18", "numberOfPlayer": "0",
            "courseIds": "1", "searchTimeType": "0", "transactionId": tid,
            "teeOffTimeMin": "0", "teeOffTimeMax": "23", "isChangeTeeOffTime": "true",
            "teeSheetSearchView": "5", "classCode": "R", "defaultOnlineRate": "N",
            "isUseCapacityPricing": "false", "memberStoreId": "1", "searchType": "1",
        }
        rr = s.get(f"{api}/TeeTimes", params=params, headers=headers)
        if rr.status_code != 200:
            log(f"  [cps_golf] TeeTimes {rr.status_code} {host}")
            return []
        data = rr.json()
        content = data if isinstance(data, list) else (data.get("content") or [])
        return _parse(content, cutoff)
    except Exception as e:
        log(f"  [cps_golf] direct API error ({host}): {e}")
        return []
    finally:
        try:
            s.close()
        except Exception:
            pass


def _parse(content, cutoff: tuple) -> list:
    slots = []
    seen = set()
    for tt in content or []:
        if not isinstance(tt, dict):
            continue
        st = tt.get("startTime") or tt.get("StartTime")
        if not st or "T" not in st:
            continue
        hm = st.split("T")[1][:5]  # "2026-06-27T07:00:00" → "07:00"
        try:
            h, m = int(hm[:2]), int(hm[3:5])
        except (ValueError, IndexError):
            continue
        if (h, m) >= cutoff:
            continue
        if hm in seen:
            continue
        seen.add(hm)

        price = None
        prices = tt.get("shItemPrices") or []
        if prices and isinstance(prices[0], dict):
            p = prices[0].get("displayPrice")
            if p is None:
                p = prices[0].get("price")
            if p is not None:
                try:
                    price = round(float(p))
                except (TypeError, ValueError):
                    price = None
        slots.append({"time": hm, "price": price, "is_hot_deal": False})

    slots.sort(key=lambda x: x["time"])
    return slots


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    """page 인자는 호출부 호환용(미사용). 모든 처리는 직접 API."""
    host = _host(booking_url)
    log(f"  [cps_golf] direct API {host} {target_date}")
    slots = await asyncio.to_thread(_fetch, host, target_date, cutoff)
    log(f"  [cps_golf] → {len(slots)} slots")
    return slots
