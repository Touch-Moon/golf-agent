"""
Season calculation and target date utilities.
"""
from datetime import date, timedelta


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    first = d + timedelta(days=offset)
    return first + timedelta(weeks=n - 1)


def calc_season(today: date) -> dict:
    year = today.year
    season_start      = nth_weekday_of_month(year, 4, 0, 1)   # 4월 첫째 월요일
    late_season_start = nth_weekday_of_month(year, 10, 0, 3)  # 10월 셋째 월요일
    season_end        = nth_weekday_of_month(year, 11, 0, 2) + timedelta(days=6)  # 11월 둘째 일요일

    return {
        "is_pre_season":    today < season_start,
        "is_normal_season": season_start <= today < late_season_start,
        "is_late_season":   late_season_start <= today <= season_end,
        "is_off_season":    today > season_end,
        "is_pre_april":     today.month in (1, 2, 3),
    }


def get_target_date(today: date) -> date:
    """이번 주 토요일을 반환 (오늘이 토요일이면 오늘, 일요일이면 다음 주 토요일)."""
    days_until_saturday = (5 - today.weekday()) % 7
    return today + timedelta(days=days_until_saturday)
