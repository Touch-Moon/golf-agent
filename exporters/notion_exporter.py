"""
Notion 크롤링 결과 exporter.
Database ID: d059a4b4-ac30-4ee6-806c-9f2190cdb435
Page: ⛳ Golf Booking > 크롤링 결과

동작:
  - 같은 날짜 + 코스 이름 페이지가 있으면 업데이트 (upsert)
  - 없으면 새 페이지 생성
  - NOTION_TOKEN 환경변수 필요
"""
import os
import uuid
import requests
from datetime import date
from logger import log

DATABASE_ID    = "d059a4b4-ac30-4ee6-806c-9f2190cdb435"
COLLECTION_ID  = "328cbce9-928f-44c6-955e-3d4596e0e8be"
DATE_PROP_ID   = "vHj`"   # Notion 내부 property ID
STATUS_PROP_ID = "wP_Z"   # Status

# 뷰 컬럼 표시 순서 (2026-04-25 뷰 기준)
TABLE_PROPERTIES = [
    {"visible": True, "property": "title"},   # Course
    {"visible": True, "property": "wP_Z"},    # Status
    {"visible": True, "property": "zpMz"},    # Earliest 2-Team
    {"visible": True, "property": "Unjx"},    # Earliest Slot
    {"visible": True, "property": "ENP="},    # Slots
    {"visible": True, "property": "AlXw"},    # Booking URL
    {"visible": True, "property": "vHj`"},    # Date
    {"visible": True, "property": "f:ZU"},    # Cart Mandatory
    {"visible": True, "property": "SzrE"},    # Lowest Price
    {"visible": True, "property": "b>KV"},    # Discount %
    {"visible": True, "property": "uW:t"},    # Distance km
    {"visible": True, "property": "FB=h"},    # Source
]
_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _status_label(status: str) -> str:
    return {
        "green":  "🟢 green",
        "red":    "🔴 red",
        "yellow": "🟡 yellow",
        "error":  "⚫ error",
    }.get(status, "⚫ error")


SLOTS_MAX_DISPLAY = 8


def _build_properties(r: dict, target_date: date) -> dict:
    sorted_slots = sorted(r.get("slots", []), key=lambda s: s["time"])
    shown = sorted_slots[:SLOTS_MAX_DISPLAY]
    slots_str = ", ".join(s["time"] for s in shown)
    if len(sorted_slots) > SLOTS_MAX_DISPLAY:
        slots_str += f" 외 {len(sorted_slots) - SLOTS_MAX_DISPLAY}개"
    lowest = r.get("lowest_price") or _calc_lowest(r)

    props = {
        "Course": {"title": [{"text": {"content": r["name"]}}]},
        "Date":   {"date": {"start": target_date.strftime("%Y-%m-%d")}},
        "Status": {"select": {"name": _status_label(r.get("status", "yellow"))}},
        "Slots":  {"rich_text": [{"text": {"content": slots_str or "—"}}]},
        "Distance km": {"number": r.get("distance_km")},
        "Cart Mandatory": {"checkbox": bool(r.get("cart_mandatory"))},
        "Source": {"select": {"name": r.get("source", "individual")}},
        "Earliest Slot":  {"rich_text": [{"text": {"content": r.get("earliest_slot") or "—"}}]},
        "Earliest 2-Team": {"rich_text": [{"text": {"content": r.get("earliest_2team") or "—"}}]},
    }
    if lowest is not None:
        props["Lowest Price"] = {"number": lowest}
    if r.get("discount_pct"):
        props["Discount %"] = {"number": r["discount_pct"]}
    if r.get("booking_url"):
        props["Booking URL"] = {"url": r["booking_url"]}
    return props



def _create_dated_view(token_v2: str, target_date: date) -> bool:
    """
    NOTION_TOKEN_V2 (사용자 세션 쿠키)를 사용해 날짜 이름의 새 뷰를 자동 생성.
    쿠키 발급: notion.so 로그인 → DevTools → Application → Cookies → token_v2 복사
    쿠키 만료 시 (≈1년) 갱신 필요.
    """
    if not token_v2:
        return False

    date_str = target_date.strftime("%Y-%m-%d")
    headers = {
        "Cookie": f"token_v2={token_v2}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        # 1) 데이터베이스 블록 조회 (view_ids + space_id 추출)
        resp = requests.post(
            "https://www.notion.so/api/v3/syncRecordValues",
            headers=headers,
            json={"requests": [{"pointer": {"table": "block", "id": DATABASE_ID}, "version": -1}]},
            timeout=10,
        )
        if resp.status_code != 200:
            log(f"  [notion] DB 조회 실패 ({resp.status_code}) — token_v2 만료 가능")
            return False
        rec = resp.json().get("recordMap", {}).get("block", {}).get(DATABASE_ID, {})
        space_id = rec.get("spaceId")
        view_ids = rec.get("value", {}).get("value", {}).get("view_ids", [])
        if not space_id:
            log(f"  [notion] space_id 추출 실패")
            return False

        # 2) 기존 뷰 이름 확인 (중복 방지)
        if view_ids:
            v_resp = requests.post(
                "https://www.notion.so/api/v3/syncRecordValues",
                headers=headers,
                json={"requests": [{"pointer": {"table": "collection_view", "id": vid}, "version": -1} for vid in view_ids]},
                timeout=10,
            )
            v_recs = v_resp.json().get("recordMap", {}).get("collection_view", {})
            existing_names = {v.get("value", {}).get("value", {}).get("name") for v in v_recs.values()}
            if date_str in existing_names:
                log(f"  [notion] 뷰 '{date_str}' 이미 존재 — 스킵")
                return True

        # 3) 새 뷰 생성
        view_id = str(uuid.uuid4())
        operations = [
            {
                "pointer": {"table": "collection_view", "id": view_id, "spaceId": space_id},
                "command": "set",
                "path": [],
                "args": {
                    "id": view_id,
                    "version": 1,
                    "type": "table",
                    "name": date_str,
                    "format": {
                        "table_wrap": True,
                        "table_properties": TABLE_PROPERTIES,
                    },
                    "query2": {
                        "filter": {
                            "operator": "and",
                            "filters": [{
                                "property": DATE_PROP_ID,
                                "filter": {
                                    "operator": "date_is",
                                    "value": {"type": "exact", "value": {"type": "date", "start_date": date_str}},
                                },
                            }],
                        },
                        "sort": [{"property": STATUS_PROP_ID, "direction": "ascending"}],
                    },
                    "parent_id": DATABASE_ID,
                    "parent_table": "block",
                    "alive": True,
                },
            },
            {
                "pointer": {"table": "block", "id": DATABASE_ID, "spaceId": space_id},
                "command": "listBefore",
                "path": ["view_ids"],
                "args": {"id": view_id},
            },
        ]
        resp = requests.post(
            "https://www.notion.so/api/v3/saveTransactionsFanout",
            headers=headers,
            json={
                "requestId": str(uuid.uuid4()),
                "transactions": [{"id": str(uuid.uuid4()), "spaceId": space_id, "operations": operations}],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log(f"  [notion] 뷰 생성 완료: {date_str}")
            return True
        log(f"  [notion] 뷰 생성 실패 ({resp.status_code}): {resp.text[:300]}")
        return False
    except Exception as e:
        log(f"  [notion] 뷰 생성 오류: {e}")
        return False


def _ensure_db_columns(token: str) -> None:
    """Earliest Slot / Earliest 2-Team 컬럼이 없으면 DB 스키마에 추가."""
    try:
        requests.patch(
            f"{_API}/databases/{DATABASE_ID}",
            headers=_headers(token),
            json={"properties": {
                "Earliest Slot":   {"rich_text": {}},
                "Earliest 2-Team": {"rich_text": {}},
            }},
            timeout=10,
        )
    except Exception as e:
        log(f"  [notion] ensure_db_columns error: {e}")


def _calc_lowest(r: dict) -> float | None:
    prices = [s["price"] for s in r.get("slots", []) if s.get("price")]
    return min(prices) if prices else None


def _find_existing(token: str, course_name: str, target_date: date) -> str | None:
    """같은 날짜 + 코스 이름의 기존 페이지 ID 반환. 없으면 None."""
    date_str = target_date.strftime("%Y-%m-%d")
    payload = {
        "filter": {
            "and": [
                {"property": "Date",   "date":  {"equals": date_str}},
                {"property": "Course", "title": {"equals": course_name}},
            ]
        },
        "page_size": 1,
    }
    try:
        resp = requests.post(
            f"{_API}/databases/{DATABASE_ID}/query",
            headers=_headers(token),
            json=payload,
            timeout=10,
        )
        data = resp.json()
        results = data.get("results", [])
        return results[0]["id"] if results else None
    except Exception as e:
        log(f"  [notion] find_existing error: {e}")
        return None


def _create_page(token: str, properties: dict) -> bool:
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
    }
    try:
        resp = requests.post(f"{_API}/pages", headers=_headers(token), json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        log(f"  [notion] create_page error: {e}")
        return False


def _update_page(token: str, page_id: str, properties: dict) -> bool:
    try:
        resp = requests.patch(
            f"{_API}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": properties},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log(f"  [notion] update_page error: {e}")
        return False


def export(results: list, target_date: date, token: str) -> str:
    """
    크롤링 결과를 Notion DB에 저장.
    - 같은 날짜 + 코스 기존 레코드 있으면 최신 데이터로 업데이트
    - 없으면 새 페이지 생성 (매주 새 날짜 = 히스토리 누적)
    반환값: "success (N created, M updated)" 또는 "failed"
    """
    if not token:
        log("[notion] NOTION_TOKEN not set — skipping")
        return "skipped"

    _ensure_db_columns(token)

    # 사용자 세션 쿠키가 있으면 날짜 이름 뷰 자동 생성
    token_v2 = os.getenv("NOTION_TOKEN_V2", "").strip()
    if token_v2:
        _create_dated_view(token_v2, target_date)

    created = updated = failed = 0

    for r in results:
        try:
            props = _build_properties(r, target_date)
            existing_id = _find_existing(token, r["name"], target_date)
            if existing_id:
                ok = _update_page(token, existing_id, props)
                if ok:
                    updated += 1
                else:
                    failed += 1
            else:
                ok = _create_page(token, props)
                if ok:
                    created += 1
                else:
                    failed += 1
        except Exception as e:
            log(f"  [notion] error for {r.get('name')}: {e}")
            failed += 1

    summary = f"success ({created} created, {updated} updated)"
    if failed:
        summary += f", {failed} failed"
    log(f"[notion] {summary}")
    return summary
