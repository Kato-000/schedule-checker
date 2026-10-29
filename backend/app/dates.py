"""日付まわり。曜日や月末の計算はLLMにさせず、ここで済ませる。"""

from __future__ import annotations

import datetime as dt
import os

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


def today() -> dt.date:
    """今日の日付。テストや動作確認では環境変数 SC_TODAY=YYYY-MM-DD で固定できる。"""
    fixed = os.environ.get("SC_TODAY")
    return dt.date.fromisoformat(fixed) if fixed else dt.date.today()


def parse_date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def norm_time(s) -> str | None:
    """'9:30' / '09:30:00' → '09:30'。読めなければ None。"""
    if not s:
        return None
    try:
        h, m = str(s).split(":")[:2]
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except ValueError:
        pass
    return None


def to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def from_minutes(n: int) -> str:
    n = max(0, min(23 * 60 + 59, n))
    return f"{n // 60:02d}:{n % 60:02d}"


def d_ja(d: dt.date) -> str:
    return f"{d.isoformat()}（{WEEKDAYS_JA[d.weekday()]}）"


def month_end(y: int, m: int) -> dt.date:
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def quick_ref(base: dt.date, weeks: int = 5) -> str:
    """LLMに渡す日付の早見表。"""
    lines = [f"今日: {d_ja(base)}",
             f"明日: {d_ja(base + dt.timedelta(1))}",
             f"明後日: {d_ja(base + dt.timedelta(2))}"]
    for wd in range(7):
        ahead = (wd - base.weekday()) % 7 or 7  # 今日より後の最初のその曜日
        lines.append(f"次の{WEEKDAYS_JA[wd]}曜: {d_ja(base + dt.timedelta(ahead))}")

    monday = base - dt.timedelta(days=base.weekday())
    lines += ["", "曜日別（今週 / 来週 / 再来週）:"]
    for wd in range(7):
        ds = [monday + dt.timedelta(weeks=w, days=wd) for w in range(3)]
        lines.append(f"{WEEKDAYS_JA[wd]}曜: 今週 {ds[0].isoformat()} / 来週 {ds[1].isoformat()}"
                     f" / 再来週 {ds[2].isoformat()}")

    this_sun = base + dt.timedelta(6 - base.weekday())
    nm_y, nm_m = (base.year + (base.month == 12), base.month % 12 + 1)
    lines += [
        "",
        f"今週末（今週の日曜）: {d_ja(this_sun)}",
        f"来週末（来週の日曜）: {d_ja(this_sun + dt.timedelta(7))}",
        f"今月: {base.month}月 / 来月: {nm_m}月",
        f"月末・今月中: {d_ja(month_end(base.year, base.month))}",
        f"来月末: {d_ja(month_end(nm_y, nm_m))}",
        f"年内・年末: {d_ja(dt.date(base.year, 12, 31))}",
        "",
        "カレンダー（週は月曜始まり）:",
    ]
    for w in range(weeks):
        start = monday + dt.timedelta(weeks=w)
        label = {0: "今週", 1: "来週", 2: "再来週"}.get(w, f"{w}週後")
        cells = " ".join(f"{(start + dt.timedelta(i)).isoformat()}({WEEKDAYS_JA[i]})" for i in range(7))
        lines.append(f"{label}: {cells}")
    return "\n".join(lines)


def holidays(start: dt.date, end: dt.date) -> dict[str, str]:
    """日本の祝日（振替休日・国民の休日を含む）。PCの中で計算し、通信はしない。
    部品（jpholiday）が入っていなければ空。"""
    try:
        import jpholiday
    except ImportError:
        return {}
    out = {}
    for d, name in jpholiday.between(start, end):
        out[d.isoformat()] = "振替休日" if "振替休日" in name else name
    return out
