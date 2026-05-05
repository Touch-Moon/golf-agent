"""
Tee-On booking system scraper.
Courses: River Oaks, Lorette, Southside, Windsor Park, Larters

Flow A (ComboLanding → WebBookingSearchSteps):
  1) ComboLanding 방문 → "Public Enter Here" 클릭
  2) WebBookingSearchSteps 폼 채우기 (Date, Time, Holes, Players)
  3) form.submit() → WebBookingSearchResults 파싱

Flow B (ComboLanding → WebBookingAllTimesLanding):
  1) ComboLanding 방문 → "Public Enter Here" 클릭
  2) 날짜 탭 클릭 + "18 Holes" 탭 클릭
  3) 페이지 바디 텍스트에서 시간 파싱

Flow C (WebBookingSearchSteps URL):
  1) WebBookingSearchSteps 직접 방문 (Public Enter Here 클릭 없이)
  2) 폼 채우기 → 동일

Results page format: "9:16AM\n$56.70\nGF S/S/H"
각 검색은 2개씩 반환 → 마지막 슬롯 직후 시간으로 다음 검색.
"""
import asyncio
import re
from datetime import date

from scrapers.base import parse_time
from logger import log


async def scrape(page, booking_url: str, target_date: date, cutoff: tuple) -> list:
    """
    booking_url = ComboLanding URL (e.g. ?CourseCode=STHS&FromCourseWebsite=true)
    Returns list of slot dicts. Price will be None (use fallback_price from config).

    Tee-On은 한 번에 2개만 반환하므로 SearchTime 을 늘려가며 반복 검색.
    최대 16개 슬롯 또는 cutoff 도달 시 중단.
    """
    log(f"  [tee_on] {booking_url}")

    try:
        # 1) 랜딩 페이지 방문
        await page.goto(booking_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(1)

        # 2) "Public Enter Here" 클릭 (ComboLanding URL에서만 필요)
        if "WebBookingSearchSteps" not in booking_url and "WebBookingAllTimesLanding" not in booking_url:
            pub_link = await page.query_selector("a:has-text('Public Enter Here')")
            if not pub_link:
                log("  [tee_on] 'Public Enter Here' 링크를 찾지 못함")
                return []
            await pub_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(1)

        # 3) WebBookingAllTimesLanding 감지 → 별도 파싱 흐름
        if "WebBookingAllTimesLanding" in page.url:
            return await _scrape_all_times_landing(page, target_date, cutoff)

        # 5) Date 검증
        date_value = target_date.strftime("%Y-%m-%d")
        date_options = await page.eval_on_selector_all(
            "select#Date option", "opts => opts.map(o => o.value)"
        )
        if date_value not in date_options:
            log(f"  [tee_on] 날짜 {date_value} 옵션 없음 (가능: {date_options})")
            return []

        # 6) SearchTime 옵션 가져오기
        time_options = await page.eval_on_selector_all(
            "select#SearchTime option", "opts => opts.map(o => o.value).filter(v => v)"
        )

        # 7) 반복 검색 — 마지막 발견 슬롯 직후 시간으로 점프
        all_slots: dict = {}
        cutoff_min = cutoff[0] * 60 + cutoff[1]
        search_from_min = 0  # 처음엔 가장 이른 옵션부터
        empty_streak = 0     # 연속 빈 응답 카운트 (gap-skipping용)

        for iter_idx in range(80):  # 안전 상한 (gap skip 여유 확보)
            search_time = _pick_search_time(time_options, search_from_min, cutoff_min)
            if not search_time:
                break

            new_slots = await _search_once(page, booking_url, date_value, search_time)
            if not new_slots:
                if iter_idx == 0:
                    log("  [tee_on] 결과 없음")
                    break
                # 빈 응답 = 알고리즘이 SearchTime drop-down 옵션 간격에 걸려
                # 직후 슬롯을 놓쳤거나, 그 시간대만 일시적으로 가용 슬롯이 없는 상태.
                # +30분 점프 후 두 번까지 더 시도하고 그래도 빈 응답이면 종료.
                empty_streak += 1
                if empty_streak >= 2:
                    break
                search_from_min += 30
                continue
            empty_streak = 0

            any_new = False
            latest_min = search_from_min
            for s in new_slots:
                if (s["hour"], s["minute"]) >= cutoff:
                    continue
                key = s["time"]
                if key not in all_slots:
                    all_slots[key] = s
                    any_new = True
                slot_min = s["hour"] * 60 + s["minute"]
                if slot_min > latest_min:
                    latest_min = slot_min

            # 다음 검색은 마지막 슬롯 직후. 새 슬롯 없으면 +30분 점프해 다음 가용 시간대로.
            if any_new:
                search_from_min = latest_min + 8
            else:
                search_from_min = max(latest_min, search_from_min) + 30
                empty_streak += 1
                if empty_streak >= 2:
                    break

        return [
            {"time": s["time"], "price": s.get("price"), "is_hot_deal": False}
            for s in sorted(all_slots.values(), key=lambda x: x["time"])
        ]

    except Exception as e:
        log(f"  [tee_on] error: {e}")
        return []


def _pick_search_time(time_options: list, from_min: int, cutoff_min: int) -> str | None:
    """from_min 이후 가장 가까운 SearchTime 옵션 반환."""
    for opt in time_options:
        try:
            h, m = map(int, opt.split(":"))
        except Exception:
            continue
        cur = h * 60 + m
        if cur >= cutoff_min:
            break
        if cur >= from_min:
            return opt
    return None


async def _search_once(page, booking_url: str, date_value: str, search_time: str) -> list:
    """한 번의 검색 → 최대 2~4개 슬롯 반환."""
    # 검색 페이지로 돌아가서 다시 폼 채우기
    if "WebBookingSearchSteps" not in page.url and "ComboLanding" not in page.url:
        await page.goto(booking_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(0.5)
        pub_link = await page.query_selector("a:has-text('Public Enter Here')")
        if pub_link:
            await pub_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(0.5)
    elif "WebBookingSearchSteps" not in page.url:
        await page.goto(booking_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(0.5)
        pub_link = await page.query_selector("a:has-text('Public Enter Here')")
        if pub_link:
            await pub_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(0.5)

    try:
        await page.select_option("select#Date", date_value)
        await page.select_option("select#SearchTime", search_time)
    except Exception:
        # 검색 결과 페이지에 있으면 새로 검색 페이지로 이동
        await page.goto(booking_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(0.5)
        pub_link = await page.query_selector("a:has-text('Public Enter Here')")
        if pub_link:
            await pub_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(0.5)
        await page.select_option("select#Date", date_value)
        await page.select_option("select#SearchTime", search_time)

    await page.evaluate("""
        document.getElementById('toggle-18').checked = true;
        document.getElementById('toggle-4').checked  = true;
        document.getElementById('form').submit();
    """)

    for _ in range(5):
        await asyncio.sleep(3)
        body = await page.inner_text("body")
        if "timed out" in body.lower() or "too many" in body.lower():
            log("  [tee_on] 세션 만료 / rate-limit")
            return []
        if re.search(r'\d{1,2}:\d{2}\s*[AaPp][Mm]', body):
            return _parse_results(body)
    return []


def _parse_results(body: str) -> list:
    """결과 페이지 텍스트에서 시간 + 가격 추출."""
    # 검색 폼의 시간 옵션 (07:00, 07:15 등 HH:MM without AM/PM) 제거
    body_filtered = re.sub(r'\b\d{1,2}:\d{2}\s*(?![AaPp][Mm])', '', body)

    slots = []
    seen = set()
    # 시간 매치 후 100자 이내에서 가격($XX.XX) 탐색
    for m in re.finditer(r'\b(\d{1,2}:\d{2}\s*[AaPp][Mm])\b', body_filtered):
        time_str = m.group(1).strip()
        dt = parse_time(time_str)
        if not dt:
            continue
        key = dt.strftime("%H:%M")
        if key in seen:
            continue
        seen.add(key)

        # 이 시간 직후 100자 안에서 가격 찾기
        after = body_filtered[m.end(): m.end() + 100]
        price_m = re.search(r'\$(\d+(?:\.\d{2})?)', after)
        price = float(price_m.group(1)) if price_m else None

        slots.append({
            "time":   key,
            "hour":   dt.hour,
            "minute": dt.minute,
            "price":  price,
        })
    return slots


async def _scrape_all_times_landing(page, target_date: date, cutoff: tuple) -> list:
    """
    WebBookingAllTimesLanding 인터페이스 파싱.
    날짜 탭(changeDate) + '18 Holes' 필터 클릭 후 body 텍스트에서 시간 파싱.
    """
    date_str = target_date.strftime("%Y-%m-%d")
    log(f"  [tee_on:AllTimes] {date_str}")

    # "18 Holes" 탭 먼저 클릭
    holes_link = await page.query_selector("a:has-text('18 Holes')")
    if holes_link:
        await holes_link.click()
        await page.wait_for_load_state("networkidle", timeout=10000)
        await asyncio.sleep(1)
        log("  [tee_on:AllTimes] '18 Holes' clicked")
    else:
        log("  [tee_on:AllTimes] '18 Holes' tab not found — continuing")

    # 날짜 탭 클릭 — changeDate('YYYY-MM-DD') 형식
    date_link = await page.query_selector(f"a[href*=\"changeDate('{date_str}')\"]")
    if date_link:
        await date_link.click()
        await page.wait_for_load_state("networkidle", timeout=10000)
        await asyncio.sleep(1)
        log(f"  [tee_on:AllTimes] date tab {date_str} clicked")
    else:
        log(f"  [tee_on:AllTimes] date tab {date_str} not found — using default date")

    body = await page.inner_text("body")
    raw = _parse_results(body)

    slots = [
        {"time": s["time"], "price": s.get("price"), "is_hot_deal": False}
        for s in raw
        if (s["hour"], s["minute"]) < cutoff
    ]
    log(f"  [tee_on:AllTimes] {len(slots)} slots within cutoff")
    return slots


