"""東証(TSE)の営業日判定。
- 平日（月〜金）
- 国民の祝日（jpholiday）
- 年末年始（12/31, 1/1〜1/3）
これらを除いた日は営業日扱い。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import jpholiday

JST = timezone(timedelta(hours=9))


def is_tse_holiday(d: date) -> bool:
    """営業日でないなら True。"""
    # 土日
    if d.weekday() >= 5:
        return True
    # 国民の祝日
    if jpholiday.is_holiday(d):
        return True
    # 年末年始 (12/31, 1/1, 1/2, 1/3)
    if (d.month, d.day) in {(12, 31), (1, 1), (1, 2), (1, 3)}:
        return True
    return False


def today_jst() -> date:
    return datetime.now(JST).date()


def reason(d: date) -> str:
    if d.weekday() >= 5:
        return ["月", "火", "水", "木", "金", "土", "日"][d.weekday()] + "曜日"
    name = jpholiday.is_holiday_name(d)
    if name:
        return f"祝日({name})"
    if (d.month, d.day) in {(12, 31), (1, 1), (1, 2), (1, 3)}:
        return "年末年始"
    return "営業日"


if __name__ == "__main__":
    t = today_jst()
    print(f"今日 {t} → {'休場' if is_tse_holiday(t) else '営業日'} ({reason(t)})")
    # 直近10日テスト
    for i in range(10):
        d = t + timedelta(days=i)
        flag = "休場" if is_tse_holiday(d) else "営業"
        print(f"  {d} {flag} ({reason(d)})")
