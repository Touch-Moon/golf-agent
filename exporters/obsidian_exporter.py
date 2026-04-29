"""
Obsidian exporter — 크롤링 결과를 Obsidian vault에 마크다운으로 저장.
방법 1: 직접 파일 쓰기 (로컬 vault)
"""
from datetime import date, datetime
from pathlib import Path
from logger import log

VAULT_PATH = Path("/Users/jin-chulmoon/Documents/Obsidian Vault")
SLOTS_MAX_DISPLAY = 8

STATUS_ICON = {
    "green":  "🟢",
    "red":    "🔴",
    "yellow": "🟡",
    "error":  "⚫",
}


def export(results: list, target_date: date) -> str:
    try:
        VAULT_PATH.mkdir(parents=True, exist_ok=True)
        path = VAULT_PATH / f"{target_date.strftime('%Y-%m-%d')}.md"
        content = _build_markdown(results, target_date)
        path.write_text(content, encoding="utf-8")
        log(f"[obsidian] 저장 완료: {path}")
        return str(path)
    except Exception as e:
        log(f"[obsidian] 저장 실패: {e}")
        return "failed"


def _build_markdown(results: list, target_date: date) -> str:
    green  = [r for r in results if r.get("status") == "green"]
    red    = [r for r in results if r.get("status") == "red"]
    yellow = [r for r in results if r.get("status") == "yellow"]
    error  = [r for r in results if r.get("status") == "error"]

    lines = []

    # YAML frontmatter
    lines += [
        "---",
        f"date: {target_date.strftime('%Y-%m-%d')}",
        f"crawled_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"available: {len(green)}",
        f"total: {len(results)}",
        "tags: [golf, tee-time]",
        "---", "",
    ]

    lines.append(f"# ⛳ {target_date.strftime('%Y-%m-%d')} 티타임 크롤링 결과")
    lines.append(f"> 🟢 예약가능 **{len(green)}**  |  🔴 슬롯없음 **{len(red)}**  |  🟡 접속불가 **{len(yellow)}**  |  ⚫ 오류 **{len(error)}**")
    lines.append("")

    # 전체 코스 요약 테이블
    lines.append("## 전체 코스 요약")
    lines.append("")
    lines.append("| Course | Status | Earliest 2-Team | Earliest Slot | Slots | Booking URL | Cart | Lowest Price | Distance km | Source |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: (
        {"green": 0, "red": 1, "yellow": 2, "error": 3}.get(x.get("status"), 9),
        x.get("distance_km") or 999
    )):
        icon = STATUS_ICON.get(r.get("status", "error"), "⚫")
        prices = [s["price"] for s in r.get("slots", []) if s.get("price")]
        price_str = f"${min(prices):.0f}" if prices else (f"~${r.get('fallback_price')} (참고)" if r.get("fallback_price") else "—")
        sorted_slots = sorted(r.get("slots", []), key=lambda x: x["time"])
        shown = sorted_slots[:SLOTS_MAX_DISPLAY]
        slots_str = ", ".join(s["time"] for s in shown) or "—"
        if len(sorted_slots) > SLOTS_MAX_DISPLAY:
            slots_str += f" 외 {len(sorted_slots) - SLOTS_MAX_DISPLAY}개"
        earliest = r.get("earliest_slot") or "—"
        two_team = r.get("earliest_2team") or "—"
        cart = "✅" if r.get("cart_mandatory") else "—"
        url = f"[예약]({r['booking_url']})" if r.get("booking_url") else "—"
        source = r.get("source", "individual")
        lines.append(f"| {r['name']} | {icon} | {two_team} | {earliest} | {slots_str} | {url} | {cart} | {price_str} | {r.get('distance_km', '?')}km | {source} |")
    lines.append("")

    # 예약 가능 코스 상세
    if green:
        lines.append("## 🟢 예약 가능 — 상세")
        lines.append("")
        for r in sorted(green, key=lambda x: (x.get("slots") or [{}])[0].get("price") or 999):
            lines.append(f"### {r['name']}")
            slots = r.get("slots", [])
            prices = [s["price"] for s in slots if s.get("price")]
            if prices:
                cart = " (카트 포함)" if r.get("cart_mandatory") else ""
                lines.append(f"- 최저가: **${min(prices):.0f}/인**{cart}")
            if slots:
                sorted_d = sorted(slots, key=lambda x: x["time"])
                shown_d = sorted_d[:SLOTS_MAX_DISPLAY]
                times = ", ".join(
                    datetime.strptime(s["time"], "%H:%M").strftime("%-I:%M %p")
                    for s in shown_d
                )
                if len(sorted_d) > SLOTS_MAX_DISPLAY:
                    times += f" 외 {len(sorted_d) - SLOTS_MAX_DISPLAY}개"
                lines.append(f"- 슬롯: {times}")
            if r.get("earliest_slot"):
                lines.append(f"- 가장 이른 슬롯: `{r['earliest_slot']}`")
            if r.get("earliest_2team"):
                lines.append(f"- 2팀 연속: `{r['earliest_2team']}`")
            lines.append(f"- 거리: {r.get('distance_km', '?')}km")
            if r.get("phone"):
                lines.append(f"- 전화: {r['phone']}")
            if r.get("booking_url"):
                lines.append(f"- [예약 페이지]({r['booking_url']})")
            lines.append("")

    # 상태 아이콘 범례
    lines += [
        "---",
        "## 상태 안내",
        "| 아이콘 | 의미 |",
        "|---|---|",
        "| 🟢 | 예약 가능 — 슬롯 확인됨 |",
        "| 🔴 | 슬롯 없음 — 당일이거나 마감 |",
        "| 🟡 | 접속 불가 — 사이트 타임아웃 |",
        "| ⚫ | 수집 오류 — 스크래퍼 파싱 실패 |",
    ]

    return "\n".join(lines)
