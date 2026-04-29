"""
Telegram message sending.
"""
import requests
from logger import log


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
