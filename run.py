#!/usr/bin/env python3
"""
Golf Tee Time Agent — v4 (modular)
매주 화요일 오전 위니펙 근처 골프장 티타임을 크롤링하고 Telegram으로 전송.
결과는 웹앱 /api/crawl-import 에도 POST하여 Supabase DB에 저장.

Usage:
  python3 run.py                # 정상 실행
  python3 run.py --dry-run      # Telegram 전송 없이 출력만
  python3 run.py 두팀이야        # 2팀 연속 슬롯 모드
"""

import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.async_api import async_playwright

import config as cfg
from season import calc_season, get_target_date
from logger import log, write_logs
from telegram import send_telegram, poll_date_request
from webapp import import_to_webapp
from message import build_message
from scrapers import SCRAPERS
from scrapers import golfnow
from exporters import notion_exporter, csv_backup, obsidian_exporter

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
API_SECRET_KEY     = os.getenv("API_SECRET_KEY", "")
WEBAPP_URL         = os.getenv("WEBAPP_URL", "https://good-morning-golf.vercel.app")
NOTION_TOKEN       = os.getenv("NOTION_TOKEN", "")

# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def parse_team_count(msg: str) -> int:
    patterns = [
        (r"(한|1)\s*팀|one\s*team", 1),
        (r"(두|2)\s*팀|two\s*teams?", 2),
        (r"(세|3)\s*팀|three\s*teams?", 3),
        (r"(네|4)\s*팀|four\s*teams?", 4),
        (r"(\d+)\s*팀|(\d+)\s*teams?", None),
    ]
    for pattern, value in patterns:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            if value is not None:
                return value
            return int(m.group(1) or m.group(2))
    return 1


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9가-힣]", " ", s.lower())).strip()


def is_duplicate(name_a: str, name_b: str) -> bool:
    a, b = normalize_name(name_a), normalize_name(name_b)
    return a == b or a in b or b in a


def slot_status(slots: list) -> str:
    if not slots:
        return "red"
    if any(s["time"] < "12:00" for s in slots):
        return "green"
    return "afternoon"


def find_consecutive_slots(slots: list, team_count: int, course_name: str) -> list:
    from scrapers.base import parse_time
    if team_count <= 1 or len(slots) < team_count:
        return []
    interval = cfg.TEE_INTERVAL_MINUTES.get(course_name, cfg.TEE_INTERVAL_MINUTES["_default"])
    sorted_slots = sorted(slots, key=lambda s: s["time"])
    groups = []
    for i in range(len(sorted_slots) - team_count + 1):
        group = [sorted_slots[i]]
        valid = True
        for j in range(1, team_count):
            t_prev = parse_time(sorted_slots[i + j - 1]["time"])
            t_curr = parse_time(sorted_slots[i + j]["time"])
            if not t_prev or not t_curr:
                valid = False; break
            diff = abs((t_curr - t_prev).seconds // 60)
            if abs(diff - interval) > 2:
                valid = False; break
            group.append(sorted_slots[i + j])
        if valid:
            groups.append(group)
    return groups

# ─────────────────────────────────────────────
# 코스 크롤링
# ─────────────────────────────────────────────

async def crawl_individual(page, course: dict, target: date) -> dict:
    name   = course["name"]
    system = course["system"]
    log(f"Crawling [{system}]: {name}")

    scrape_fn = SCRAPERS.get(system)
    if not scrape_fn:
        log(f"  ⚠️  No scraper for system '{system}'")
        return _error_result(course)

    for attempt in range(2):
        if attempt > 0:
            log(f"  Retrying {name}...")
            await asyncio.sleep(5)
        try:
            slots = await scrape_fn(page, course["booking_url"], target, cfg.ALL_DAY_CUTOFF)
            return {
                "name":              name,
                "source":            "individual",
                "status":            slot_status(slots),
                "slots":             slots,
                "fallback_price":    course.get("fallback_price"),
                "distance_km":       course.get("distance_km"),
                "phone":             course.get("phone"),
                "booking_url":       course.get("booking_url"),
                "cart_mandatory":    course.get("cart_mandatory", False),
                "consecutive_slots": [],
                "earliest_slot":     None,
                "earliest_2team":    None,
            }
        except Exception as e:
            if attempt == 0:
                log(f"  First attempt failed: {e}")
                continue
            log(f"  All attempts failed: {e}")
    return _error_result(course)


def _error_result(course: dict) -> dict:
    return {
        "name":           course["name"],
        "source":         "individual",
        "status":         "error",
        "slots":          [],
        "fallback_price": course.get("fallback_price"),
        "distance_km":    course.get("distance_km"),
        "phone":          course.get("phone"),
        "booking_url":    course.get("booking_url"),
        "cart_mandatory": course.get("cart_mandatory", False),
        "consecutive_slots": [],
    }


async def crawl_golfnow(page, individual_results: list, target: date) -> tuple[list, int, int]:
    results    = []
    gn_count   = 0
    dupe_count = 0

    for key, gn in cfg.GOLFNOW_COURSES.items():
        if any(is_duplicate(gn["name"], r["name"]) for r in individual_results):
            dupe_count += 1
            log(f"GolfNow duplicate (skip): {gn['name']}")
            continue

        log(f"GolfNow: {gn['name']}")
        slots = golfnow.fetch_api(gn["facility_id"], gn["slug"], target, cfg.ALL_DAY_CUTOFF)
        if slots is None:
            slots = await golfnow.scrape_playwright(page, gn["facility_id"], gn["slug"], target, cfg.ALL_DAY_CUTOFF)
        if not slots:
            slots = []

        results.append({
            "name":           gn["name"],
            "source":         "golfnow",
            "status":         "green" if slots else "red",
            "slots":          slots,
            "fallback_price": gn.get("fallback_price"),
            "distance_km":    gn.get("distance_km"),
            "phone":          gn.get("phone"),
            "booking_url":    f"https://www.golfnow.com/tee-times/facility/{gn['facility_id']}-{gn['slug']}/search",
            "cart_mandatory": False,
            "consecutive_slots": [],
            "earliest_slot":  None,
            "earliest_2team": None,
        })
        gn_count += 1
        await asyncio.sleep(2)

    return results, gn_count, dupe_count


async def check_homepage_status(page, course: dict) -> dict:
    import re as _re
    try:
        await page.goto(course.get("homepage", ""), wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        body = (await page.inner_text("body")).lower()
        found_open   = any(kw in body for kw in cfg.OPEN_KEYWORDS)
        found_closed = any(kw in body for kw in cfg.CLOSED_KEYWORDS)
        if found_closed:
            status, note = "closed", "홈페이지에서 시즌 종료 확인"
        elif found_open:
            status, note = "open", "홈페이지에서 영업 중 확인"
        else:
            status, note = "unknown", "홈페이지 상태 불명확"
        return {"name": course["name"], "distance_km": course.get("distance_km"),
                "status": status, "note": note, "phone": course.get("phone"),
                "homepage": course.get("homepage")}
    except Exception as e:
        return {"name": course["name"], "distance_km": course.get("distance_km"),
                "status": "unknown", "note": f"접속 실패: {e}",
                "phone": course.get("phone"), "homepage": course.get("homepage")}


async def check_bridges_coupon(page) -> str | None:
    try:
        await page.goto(
            "https://www.bridgesgolfcourse.com/golf/discounted-golf-rounds/",
            wait_until="domcontentloaded", timeout=20000,
        )
        body = (await page.inner_text("body")).lower()
        if "sold out" in body:
            return "sold_out"
        if "prepaid" in body or "5 round" in body or "10 round" in body:
            return "available"
        return None
    except Exception as e:
        log(f"Bridges coupon check failed: {e}")
        return None

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def main():
    args       = sys.argv[1:]
    dry_run    = "--dry-run" in args
    args       = [a for a in args if a != "--dry-run"]
    team_count = parse_team_count(" ".join(args))

    if not dry_run:
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
            print("ERROR: TELEGRAM_BOT_TOKEN not set. Use --dry-run to test.")
            sys.exit(1)
        if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "your_chat_id_here":
            print("ERROR: TELEGRAM_CHAT_ID not set.")
            sys.exit(1)

    if dry_run:
        log("=== DRY RUN MODE — Telegram will NOT be sent ===")

    today  = date.today()
    season = calc_season(today)

    # 텔레그램 자동 알림: 월요일 오전 자동 실행 시에만 전송
    # workflow_dispatch(봇 /scrape 또는 수동 트리거)일 경우 항상 전송
    GITHUB_EVENT  = os.getenv("GITHUB_EVENT_NAME", "")
    is_manual     = GITHUB_EVENT == "workflow_dispatch"
    is_monday     = today.weekday() == 0
    should_notify = is_monday or is_manual

    # 텔레그램에서 특정 날짜 요청 확인 (없으면 이번 주 토요일)
    requested_date = None
    if not dry_run and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        requested_date = poll_date_request(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    target = requested_date if requested_date else get_target_date(today)
    if requested_date:
        log(f"Telegram 요청 날짜 사용: {target}")

    log(f"Golf Agent v4 | Today={today} | Target={target} | Teams={team_count}")
    log(f"Season: {season}")

    if season["is_pre_season"] or season["is_off_season"]:
        msg = (
            "⛄ *골프 시즌이 아닙니다*\n"
            "📅 마니토바 골프 시즌: 4월 첫째 주 ~ 11월 둘째 주\n"
            "🔜 다음 시즌 개장 예정: 4월 첫째 주"
        )
        if dry_run:
            print(msg)
        elif should_notify:
            send_telegram(msg, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        log("Off-season. Exiting.")
        sys.exit(0)

    results: list = []
    stats: dict   = {"failures": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # ── 개별 코스 크롤링 (병렬) ──
        # 순차 → asyncio.gather. 코스마다 독립 context(Playwright 동시 실행).
        # 직접 API 코스(teeitup/cps)는 page 미사용 → 즉시 끝나고 슬롯 반환.
        # anti-bot 회피: 전역 동시성 + 도메인별 동시성 제한.
        log("=== Individual courses (parallel) ===")
        GLOBAL_CONCURRENCY = 10      # 전체 동시 코스 수
        PER_HOST_DEFAULT = 3         # 같은 도메인 기본 동시 수
        # tee-on.com 은 6개 코스가 공유 → 6 동시 허용(한 배치). Tee-On은 SaaS라 부하 견딤.
        PER_HOST_OVERRIDE = {"www.tee-on.com": 6}
        global_sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        host_sems: dict[str, asyncio.Semaphore] = {}

        async def crawl_one(course: dict) -> dict:
            host = urlparse(course.get("booking_url", "") or "").netloc or course["name"]
            limit = PER_HOST_OVERRIDE.get(host, PER_HOST_DEFAULT)
            hsem = host_sems.setdefault(host, asyncio.Semaphore(limit))
            async with global_sem, hsem:
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                pg = await ctx.new_page()
                try:
                    return await crawl_individual(pg, course, target)
                finally:
                    await ctx.close()

        individual_results = list(
            await asyncio.gather(*(crawl_one(c) for c in cfg.INDIVIDUAL_COURSES))
        )
        for r in individual_results:
            if r.get("status") in ("error", "yellow"):
                stats["failures"].append(r["name"])
        stats["individual_checked"] = len(individual_results)
        results.extend(individual_results)

        # ── GolfNow ──
        log("=== GolfNow ===")
        gn_results, gn_count, dupe_count = await crawl_golfnow(page, individual_results, target)
        results.extend(gn_results)
        stats["golfnow_found"] = gn_count
        stats["golfnow_dupes"] = dupe_count

        # ── Late Season 홈페이지 확인 ──
        late_results = None
        if season["is_late_season"]:
            log("=== Late season homepage check ===")
            late_results = []
            for course in cfg.INDIVIDUAL_COURSES:
                existing = next((r for r in results if r["name"] == course["name"]), None)
                if existing and existing["status"] == "green":
                    continue
                r = await check_homepage_status(page, course)
                late_results.append(r)
                await asyncio.sleep(1)

        # ── Bridges 쿠폰 ──
        bridges_coupon = None
        if season["is_pre_april"]:
            log("=== Bridges coupon check ===")
            bridges_coupon = await check_bridges_coupon(page)
            stats["bridges_coupon"] = bridges_coupon or "not_found"
        else:
            stats["bridges_coupon"] = "n/a"

        await browser.close()

    # ── 연속 슬롯 계산 (항상 2팀 기준으로 계산) ──
    for r in results:
        if r.get("slots"):
            sorted_slots = sorted(r["slots"], key=lambda s: s["time"])
            r["earliest_slot"] = sorted_slots[0]["time"]
            groups_2 = find_consecutive_slots(r["slots"], 2, r["name"])
            r["consecutive_slots"] = [
                [{"time": s["time"]} for s in grp]
                for grp in groups_2
            ]
            r["earliest_2team"] = (
                groups_2[0][0]["time"] + " + " + groups_2[0][1]["time"]
                if groups_2 else None
            )
    # 2팀 초과 모드: consecutive_slots를 요청된 팀 수로 재계산
    if team_count > 2:
        for r in results:
            if r.get("slots"):
                groups = find_consecutive_slots(r["slots"], team_count, r["name"])
                r["consecutive_slots"] = [
                    [{"time": s["time"]} for s in grp]
                    for grp in groups
                ]

    stats["with_slots"] = sum(1 for r in results if r.get("status") == "green")
    stats["failures"]   = ", ".join(stats["failures"]) if stats["failures"] else "none"

    # ── 메시지 빌드 + 전송 ──
    message = build_message(results, target, team_count, late_results, bridges_coupon)

    if dry_run:
        print("\n" + "=" * 60)
        print(message)
        print("=" * 60 + "\n")
        stats["telegram"] = "dry_run"
    elif should_notify:
        ok = send_telegram(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        stats["telegram"] = "success" if ok else "FAILED"
    else:
        log(f"Telegram skipped (not Monday, trigger={GITHUB_EVENT or 'schedule'})")
        stats["telegram"] = f"skipped (not Monday)"

    # ── 웹앱 import ──
    stats["webapp_import"] = import_to_webapp(target, results, WEBAPP_URL, API_SECRET_KEY)

    # ── Notion export ──
    stats["notion_export"] = notion_exporter.export(results, target, NOTION_TOKEN)

    # ── Obsidian export ──
    stats["obsidian_export"] = obsidian_exporter.export(results, target)

    # ── CSV 백업 ──
    csv_path = csv_backup.export(results, target)
    stats["csv_backup"] = str(csv_path)
    log(f"CSV 백업 저장: {csv_path}")

    write_logs(target, results, stats)
    log("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
