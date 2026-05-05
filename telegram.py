"""
Telegram message sending and date request polling.
"""
import re
import time
from datetime import date, timedelta

import requests
from logger import log

_WEEKDAY_KO = {
    "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3,
    "금요일": 4, "토요일": 5, "일요일": 6,
}


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    MAX_LEN = 4096
    if len(message) <= MAX_LEN:
        chunks = [message]
    else:
        mid = message[:MAX_LEN].rfind("━━━")
        mid = mid if mid != -1 else MAX_LEN - 100
        chunks = [message[:mid], message[mid:]]

    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "parse_mode": "Markdown",
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                log(f"Telegram send failed ({resp.status_code}): {resp.text[:200]}")
                success = False
        except Exception as e:
            log(f"Telegram exception: {e}")
            success = False

    if not success:
        print("=== FALLBACK OUTPUT ===")
        print(message)
    return success


def poll_date_request(bot_token: str, chat_id: str) -> date | None:
    """
    최근 12시간 내 텔레그램 메시지에서 날짜 요청 파싱.
    가장 최근 메시지 우선. 요청 없으면 None.

    지원 형식:
      2026-05-10 / 5월 10일 / 5/10
      오늘 / 내일 / 모레
      이번 주 수요일 / 다음 주 토요일
    """
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"limit": 50, "allowed_updates": ["message"]},
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        log(f"Telegram poll failed: {e}")
        return None

    cutoff = time.time() - 12 * 3600  # 12시간
    today = date.today()

    for update in reversed(data.get("result", [])):
        msg = update.get("message", {})
        if str(msg.get("chat", {}).get("id", "")) != str(chat_id):
            continue
        if msg.get("date", 0) < cutoff:
            break  # reversed이므로 여기서부터는 모두 과거
        text = msg.get("text", "").strip()
        parsed = _parse_date(text, today)
        if parsed and parsed >= today:
            log(f"Telegram 날짜 요청 감지: '{text}' → {parsed}")
            return parsed

    return None


def _parse_date(text: str, today: date) -> date | None:
    # 2026-05-10
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 5월 10일 or 05월 10일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        try:
            return date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    # 5/10 or 05/10
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if m:
        try:
            return date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    # 오늘 / 내일 / 모레
    if "오늘" in text:
        return today
    if "내일" in text:
        return today + timedelta(days=1)
    if "모레" in text:
        return today + timedelta(days=2)

    # 이번 주 X요일 / 다음 주 X요일
    next_week = "다음" in text
    for ko, wd in _WEEKDAY_KO.items():
        if ko in text:
            diff = (wd - today.weekday()) % 7
            if diff == 0 and not next_week:
                return today
            if next_week:
                diff = diff if diff > 0 else 7
                return today + timedelta(days=diff + 7)
            return today + timedelta(days=diff if diff > 0 else 7)

    return None
