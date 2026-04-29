"""
Web app API import — POST crawl results to /api/crawl-import.
"""
import requests
from datetime import date
from logger import log


def import_to_webapp(target_date: date, results: list, webapp_url: str, api_secret: str) -> str:
    if not api_secret or not webapp_url:
        log("WEBAPP_URL or API_SECRET_KEY not set — skipping web import")
        return "skipped"

    courses_payload = []
    for r in results:
        if r.get("source") == "golfnow":
            continue  # GolfNow 코스는 DB 이름 매칭 불확실 → 스킵
        slots = [
            {
                "time": s["time"],
                "price": s.get("price") or r.get("fallback_price") or 0,
                "is_hot_deal": s.get("is_hot_deal", False),
            }
            for s in r.get("slots", [])
        ]
        lowest = min((s["price"] for s in slots if s["price"]), default=None)
        courses_payload.append({
            "name":              r["name"],
            "status":            r.get("status", "yellow"),
            "slots":             slots,
            "lowest_price":      lowest,
            "discount_pct":      0,
            "consecutive_slots": r.get("consecutive_slots", []),
        })

    try:
        resp = requests.post(
            f"{webapp_url}/api/crawl-import",
            headers={"Authorization": f"Bearer {api_secret}"},
            json={"crawl_date": target_date.strftime("%Y-%m-%d"), "courses": courses_payload},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            log(f"WebApp import OK — imported={data.get('imported')}, poll_created={data.get('poll_created')}")
            return "success"
        log(f"WebApp import failed ({resp.status_code}): {resp.text[:200]}")
        return "failed"
    except Exception as e:
        log(f"WebApp import exception: {e}")
        return "failed"
