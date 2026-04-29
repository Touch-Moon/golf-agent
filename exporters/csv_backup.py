"""
CSV 백업 — 크롤링 결과를 ~/golf-agent/backup/YYYY-MM-DD.csv 에 저장.
"""
import csv
from datetime import date
from pathlib import Path

BACKUP_DIR = Path(__file__).parent.parent / "backup"
BACKUP_DIR.mkdir(exist_ok=True)

FIELDNAMES = [
    "date", "course", "status", "slots",
    "lowest_price", "discount_pct", "distance_km",
    "cart_mandatory", "source", "booking_url",
    "earliest_slot", "earliest_2team",
]


def export(results: list, target_date: date) -> Path:
    """결과 리스트를 CSV로 저장하고 파일 경로를 반환."""
    path = BACKUP_DIR / f"{target_date.strftime('%Y-%m-%d')}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in results:
            slots_str = ", ".join(s["time"] for s in r.get("slots", []))
            writer.writerow({
                "date":          target_date.strftime("%Y-%m-%d"),
                "course":        r.get("name", ""),
                "status":        r.get("status", ""),
                "slots":         slots_str,
                "lowest_price":  r.get("lowest_price") or _calc_lowest(r),
                "discount_pct":  r.get("discount_pct", 0),
                "distance_km":   r.get("distance_km", ""),
                "cart_mandatory": "Y" if r.get("cart_mandatory") else "N",
                "source":        r.get("source", ""),
                "booking_url":   r.get("booking_url", ""),
                "earliest_slot":  r.get("earliest_slot") or "",
                "earliest_2team": r.get("earliest_2team") or "",
            })

    return path


def _calc_lowest(r: dict) -> float | None:
    prices = [s["price"] for s in r.get("slots", []) if s.get("price")]
    return min(prices) if prices else None
