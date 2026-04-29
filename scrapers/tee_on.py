"""
Tee-On booking system scraper.
Courses: River Oaks, Lorette, Southside, Windsor Park, Larters

Flow (ComboLanding URL):
  1) ComboLanding 방문 → "Public Enter Here" 클릭
  2) WebBookingSearchSteps 폼 채우기 (Date, Time, Holes, Players)
  3) form.submit() → ALTCHA 자동 해결 → WebBookingSearchResults 파싱

Flow (WebBookingSearchSteps URL):
  1) WebBookingSearchSteps 직접 방문 (Public Enter Here 클릭 없이)
  2) 폼 채우기 → 동일

Time format on results page: "10:08AM" (no space before AM/PM)
Price is NOT shown in search results → caller uses fallback_price.
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
        if "WebBookingSearchSteps" not in booking_url:
            pub_link = await page.query_selector("a:has-text('Public Enter Here')")
            if not pub_link:
                log("  [tee_on] 'Public Enter Here' 링크를 찾지 못함")
                return []
            await pub_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(1)

        # 3) Date 검증
        date_value = target_date.strftime("%Y-%m-%d")
        date_options = await page.eval_on_selector_all(
            "select#Date option", "opts => opts.map(o => o.value)"
        )
        if date_value not in date_options:
            log(f"  [tee_on] 날짜 {date_value} 옵션 없음 (가능: {date_options})")
            return []

        # 4) SearchTime 옵션 가져오기 (06:00 부터 cutoff 까지)
        time_options = await page.eval_on_selector_all(
            "select#SearchTime option", "opts => opts.map(o => o.value).filter(v => v)"
        )

        # 5) 반복 검색
        all_slots: dict = {}
        max_iterations = 12  # 최대 12회 (≈ 24개 슬롯 예상)

        for iter_idx, search_time in enumerate(_iter_search_times(time_options, cutoff, max_iterations)):
            new_slots = await _search_once(page, booking_url, date_value, search_time)
            if not new_slots:
                # 첫 시도 실패 시 종료, 그 외엔 그냥 끝
                if iter_idx == 0:
                    log("  [tee_on] 결과 없음")
                break

            added = 0
            for s in new_slots:
                if (s["hour"], s["minute"]) >= cutoff:
                    continue
                key = s["time"]
                if key not in all_slots:
                    all_slots[key] = s
                    added += 1

            if added == 0:
                # 더 이상 새 슬롯 없음 → 종료
                break

        return [
            {"time": s["time"], "price": None, "is_hot_deal": False}
            for s in sorted(all_slots.values(), key=lambda x: x["time"])
        ]

    except Exception as e:
        log(f"  [tee_on] error: {e}")
        return []


def _iter_search_times(time_options: list, cutoff: tuple, max_iter: int):
    """SearchTime 옵션을 30분 간격으로 건너뛰며 yield."""
    cutoff_min = cutoff[0] * 60 + cutoff[1]
    last_yielded = -999
    count = 0
    for opt in time_options:
        try:
            h, m = map(int, opt.split(":"))
        except Exception:
            continue
        cur = h * 60 + m
        if cur >= cutoff_min:
            break
        if cur - last_yielded < 30:
            continue  # 30분 간격으로만
        yield opt
        last_yielded = cur
        count += 1
        if count >= max_iter:
            break


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
        document.getElementById('toggle-1').checked  = true;
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
    """결과 페이지 텍스트에서 슬롯 추출 (검색 폼의 시간 옵션은 제외)."""
    # 검색 폼의 시간 옵션 (06:00, 06:15 등) 제거
    body_filtered = re.sub(r'\b\d{1,2}:\d{2}\s*(?![AaPp][Mm])', '', body)

    slots = []
    seen = set()
    for m in re.finditer(r'\b(\d{1,2}:\d{2}\s*[AaPp][Mm])\b', body_filtered):
        time_str = m.group(1).strip()
        dt = parse_time(time_str)
        if not dt:
            continue
        key = dt.strftime("%H:%M")
        if key in seen:
            continue
        seen.add(key)
        slots.append({
            "time":   key,
            "hour":   dt.hour,
            "minute": dt.minute,
        })
    return slots


