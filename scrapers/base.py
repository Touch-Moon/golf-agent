"""
Shared Playwright utilities and slot parsing helpers used by all scrapers.
"""
import re
from datetime import datetime


def parse_time(time_str: str) -> datetime | None:
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(time_str.strip(), fmt)
        except ValueError:
            continue
    try:
        if "T" in time_str:
            return datetime.fromisoformat(time_str)
    except ValueError:
        pass
    return None


def within_cutoff(time_str: str, cutoff: tuple) -> bool:
    dt = parse_time(time_str)
    if not dt:
        return False
    return (dt.hour, dt.minute) < cutoff


def make_slot(time_str: str, price: float | None, is_hot_deal: bool = False) -> dict:
    dt = parse_time(time_str)
    if not dt:
        return None
    return {
        "time":        dt.strftime("%H:%M"),
        "price":       price,
        "is_hot_deal": is_hot_deal,
    }


def extract_price(text: str) -> float | None:
    m = re.search(r"\$(\d+(?:\.\d{2})?)", text)
    return float(m.group(1)) if m else None


def extract_time(text: str) -> str | None:
    m = re.search(r"\b(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\b", text)
    return m.group(1) if m else None


async def body_text_fallback(page, cutoff: tuple) -> list:
    """Last-resort: scan entire body text for time+price patterns."""
    slots = []
    try:
        body = await page.inner_text("body")
        for m in re.finditer(r"(\d{1,2}:\d{2}\s*[AaPp][Mm]).*?\$(\d+(?:\.\d{2})?)", body):
            slot = make_slot(m.group(1), float(m.group(2)))
            if slot and within_cutoff(slot["time"], cutoff):
                slots.append(slot)
    except Exception:
        pass
    return slots
