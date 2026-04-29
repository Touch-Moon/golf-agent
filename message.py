"""
Telegram message builder.
"""
from datetime import date, datetime


def _format_discount(actual: float, fallback: float) -> str:
    if not actual or not fallback or actual >= fallback:
        return ""
    pct = round((fallback - actual) / fallback * 100)
    if pct <= 0:
        return ""
    icon = "🔥" if pct >= 30 else "🏷️"
    return f"-{pct}% {icon}"


SLOTS_MAX_DISPLAY = 8


def _slot_line(slots: list, fallback_price: int | None, cart_mandatory: bool) -> str:
    if not slots:
        return ""
    sorted_slots = sorted(slots, key=lambda x: x["time"])
    shown = sorted_slots[:SLOTS_MAX_DISPLAY]
    times = ", ".join(
        datetime.strptime(s["time"], "%H:%M").strftime("%-I:%M %p")
        for s in shown
    )
    if len(sorted_slots) > SLOTS_MAX_DISPLAY:
        times += f" 외 {len(sorted_slots) - SLOTS_MAX_DISPLAY}개"
    prices = [s["price"] for s in slots if s.get("price")]
    if prices:
        min_price = min(prices)
        disc      = _format_discount(min_price, fallback_price or 0) if fallback_price else ""
        cart_note = " (Cart 포함)" if cart_mandatory else ""
        price_str = f"💰 *${min_price:.0f}/인*{cart_note} {disc}"
    elif fallback_price:
        price_str = f"💰 ~${fallback_price}/인 (참고가)"
    else:
        price_str = ""
    return f"⏱ {times}\n{price_str}" if price_str else f"⏱ {times}"


def build_message(
    results: list,
    target_date: date,
    team_count: int,
    late_season_results: list | None,
    bridges_coupon: str | None,
) -> str:
    date_str = target_date.strftime("%A, %B %d")
    header = f"🏌️ *이번 주 토요일 골프 티타임*\n📅 {date_str}"
    if team_count >= 2:
        header += f"\n👥 {team_count}팀 모드"

    lines = [header, ""]

    green  = [r for r in results if r.get("status") == "green"]
    red    = [r for r in results if r.get("status") == "red"]
    yellow = [r for r in results if r.get("status") == "yellow"]
    error  = [r for r in results if r.get("status") == "error"]

    # 팀 모드 — 연속 슬롯 우선
    if team_count >= 2:
        multi_ok = [r for r in green if r.get("consecutive_slots")]
        single   = [r for r in green if not r.get("consecutive_slots")]
        if multi_ok:
            lines.append(f"━━━━━━━━━━━━━━━\n✅ *{team_count}팀 연속 가능한 코스*\n")
            for r in multi_ok:
                grp = r["consecutive_slots"][0]
                times_str = " + ".join(
                    datetime.strptime(s["time"], "%H:%M").strftime("%-I:%M %p") for s in grp
                )
                lines.append(f"🟢 *{r['name']}* (~{r.get('distance_km', '?')}km)")
                lines.append(f"👥 {times_str} — 연속 {team_count}슬롯 확보!")
                sl = _slot_line(r["slots"], r.get("fallback_price"), r.get("cart_mandatory", False))
                if sl:
                    lines.append(sl)
                if r.get("phone"):
                    lines.append(f"📞 {r['phone']}")
                if r.get("booking_url"):
                    lines.append(f"🌐 [온라인 예약]({r['booking_url']})")
                lines.append("")
        else:
            lines.append(f"⚠️ 연속 {team_count}슬롯 가능한 코스가 없습니다.\n")

        green = single if single else []

    # 슬롯 있는 코스
    for r in sorted(green, key=lambda x: (x.get("slots") or [{}])[0].get("price") or x.get("fallback_price") or 999):
        icon = "⛳" if r.get("cart_mandatory") else "🟢"
        lines.append(f"━━━━━━━━━━━━━━━\n{icon} *{r['name']}* (~{r.get('distance_km', '?')}km)")
        sl = _slot_line(r["slots"], r.get("fallback_price"), r.get("cart_mandatory", False))
        if sl:
            lines.append(sl)
        if r.get("phone"):
            lines.append(f"📞 {r['phone']}")
        if r.get("booking_url"):
            lines.append(f"🌐 [온라인 예약]({r['booking_url']})")
        lines.append("")

    # 슬롯 없는 코스
    for r in red:
        lines.append(f"🔴 *{r['name']}* (~{r.get('distance_km', '?')}km) — 예약 가능한 슬롯 없음")
        if r.get("phone"):
            lines.append(f"  📞 {r['phone']}")
        if r.get("booking_url"):
            lines.append(f"  🌐 [예약 페이지]({r['booking_url']})")

    # 접속 불가 (timeout)
    for r in yellow:
        fp     = r.get("fallback_price")
        fp_str = f" (참고가: ~${fp}/인)" if fp else ""
        lines.append(f"🟡 *{r['name']}* (~{r.get('distance_km', '?')}km) — 접속 불가{fp_str}")
        if r.get("phone"):
            lines.append(f"  📞 {r['phone']}")

    # 수집 오류 (스크래퍼/파싱 에러)
    for r in error:
        lines.append(f"⚫ *{r['name']}* (~{r.get('distance_km', '?')}km) — 데이터 수집 오류")
        if r.get("phone"):
            lines.append(f"  📞 {r['phone']}")

    # 가격순 요약
    priced = [
        (r["name"], r["slots"][0].get("price") or r.get("fallback_price"), r.get("phone", ""))
        for r in results if r.get("status") == "green" and r.get("slots")
    ]
    priced.sort(key=lambda x: x[1] or 999)
    if priced:
        lines.append("\n━━━━━━━━━━━━━━━\n📊 *가격순 요약*")
        for i, (name, price, phone) in enumerate(priced[:10], 1):
            price_str = f"${price:.0f}/인" if price else "가격 미확인"
            lines.append(f"{i}. {name} — {price_str}" + (f" | 📞 {phone}" if phone else ""))

    # Late Season 홈페이지 결과
    if late_season_results:
        lines.append("\n━━━━━━━━━━━━━━━\n🍂 *시즌 마감 임박 — 홈페이지 확인 결과*\n")
        for r in late_season_results:
            if r["status"] == "closed":
                lines.append(f"⚫ *{r['name']}* — 시즌 종료 확인")
            elif r["status"] == "open":
                lines.append(f"🟠 *{r['name']}* (~{r.get('distance_km', '?')}km) — 홈페이지 영업 중")
                lines.append(f"  ☎️ 전화 예약 필요 | 📞 {r.get('phone', '전화번호 없음')}")
                if r.get("homepage"):
                    lines.append(f"  🔗 {r['homepage']}")
            else:
                lines.append(f"🟡 *{r['name']}* — 상태 불명확, 직접 확인 권장")
                if r.get("homepage"):
                    lines.append(f"  🔗 {r['homepage']}")

    # Bridges 쿠폰
    if bridges_coupon == "available":
        lines.append("\n━━━━━━━━━━━━━━━\n🎟️ *Bridges 시즌 전 특가 안내*")
        lines.append("📦 Prepaid Golf Card — 연간 최고 딜!")
        lines.append("• 5라운드 $339 → 1라운드당 *$67.80*")
        lines.append("• 10라운드 $678 | 15라운드 $1,017 | 20라운드 $1,356")
        lines.append("• Cart + 드라이빙레인지 포함")
        lines.append("• ⏰ 판매 마감: 4월 30일 (또는 매진 시 조기 종료)")
        lines.append("• ⚠️ 매년 매진됨 — 서두르세요!")
        lines.append("👉 https://www.bridgesgolfcourse.com/golf/discounted-golf-rounds/")
    elif bridges_coupon == "sold_out":
        lines.append("\n🎟️ Bridges Prepaid Card — ❌ 매진 (Sold Out)")

    lines.append("\n💬 예약할 골프장을 선택해주세요.")

    lines.append(
        "\n━━━━━━━━━━━━━━━\n"
        "ℹ️ *상태 안내*\n"
        "🟢 예약 가능 — 슬롯 확인됨\n"
        "🔴 슬롯 없음 — 조건 내 예약 불가\n"
        "🟡 접속 불가 — 사이트 타임아웃\n"
        "⚫ 수집 오류 — 파싱/크롤링 실패"
    )

    return "\n".join(lines)
