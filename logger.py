"""
Logging utilities — console + file output.
"""
import json
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_lines: list[str] = []


def log(msg: str) -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_lines.append(line)


def write_logs(target_date: date, results: list, stats: dict) -> None:
    date_str = target_date.strftime("%Y-%m-%d")

    log_path = LOG_DIR / "run_log.txt"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Run complete.\n")
        f.write(f"Target date: {target_date.strftime('%A, %B %d')}\n")
        f.write(f"Individual courses checked: {stats.get('individual_checked', 0)}\n")
        f.write(f"GolfNow courses found: {stats.get('golfnow_found', 0)}\n")
        f.write(f"GolfNow duplicates removed: {stats.get('golfnow_dupes', 0)}\n")
        f.write(f"Courses with slots: {stats.get('with_slots', 0)}\n")
        f.write(f"Scrape failures: {stats.get('failures', 'none')}\n")
        f.write(f"Bridges coupon: {stats.get('bridges_coupon', 'n/a')}\n")
        f.write(f"Telegram: {stats.get('telegram', 'unknown')}\n")
        f.write(f"WebApp import: {stats.get('webapp_import', 'skipped')}\n")
        f.write("---\n")

    json_path = LOG_DIR / f"run_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"target_date": date_str, "results": results, "stats": stats},
            f, ensure_ascii=False, indent=2,
        )

    log(f"Logs saved → {log_path.name}, {json_path.name}")
