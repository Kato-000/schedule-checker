"""Googleカレンダーの自動同期の間隔（設定で選ぶ）。"""

import datetime as dt

from app import db, scheduler


def T(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


def test_interval_api(client):
    assert client.get("/api/google").json()["sync_interval"] == "15m"
    r = client.put("/api/google", json={"sync_interval": "daily"})
    assert r.status_code == 200 and r.json()["sync_interval"] == "daily"
    assert client.put("/api/google", json={"sync_interval": "2m"}).status_code == 400


def test_next_run_intervals(fake):
    now = T("2026-10-25 12:00")
    assert scheduler.google_next_run("15m", None, now, True) == T("2026-10-25 12:01")
    assert scheduler.google_next_run("1h", T("2026-10-25 11:30"), now, False) == T("2026-10-25 12:30")
    assert scheduler.google_next_run("6h", T("2026-10-24 01:00"), now, True) == T("2026-10-25 12:01")   # 過ぎていればすぐ
    assert scheduler.google_next_run("manual", None, now, True) is None


def test_next_run_daily_before_digest(fake):
    db.set_setting("digest_time", "07:00")
    assert scheduler.google_daily_time() == (6, 50)
    # 朝の前なら今日の6:50
    assert scheduler.google_next_run("daily", T("2026-10-24 06:50"), T("2026-10-25 05:00"), True) == T("2026-10-25 06:50")
    # 起動が6:50を過ぎていて今日まだ同期していない → すぐ1回
    assert scheduler.google_next_run("daily", T("2026-10-24 06:50"), T("2026-10-25 12:00"), True) == T("2026-10-25 12:01")
    # 今日もう同期済みなら明日の6:50
    assert scheduler.google_next_run("daily", T("2026-10-25 06:50"), T("2026-10-25 12:00"), True) == T("2026-10-26 06:50")
    assert scheduler.google_next_run("daily", None, T("2026-10-25 12:00"), False) == T("2026-10-26 06:50")
    # 朝のまとめが0:05なら前日の23:55
    db.set_setting("digest_time", "00:05")
    assert scheduler.google_daily_time() == (23, 55)
