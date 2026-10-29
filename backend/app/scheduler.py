"""定時処理。毎朝のまとめを設定の時刻に作る。
PCを再起動した日に時刻を過ぎていて、まだ作っていなければ起動時に作る。"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db, digest, jobs
from .dates import norm_time, today

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
JOB_ID = "morning_digest"


def _digest_job() -> None:
    # LLMの処理と順番に並べる（GPUは1つ）
    jobs.submit(digest.generate).result()


def _google_job() -> None:
    from . import google_sync
    if google_sync.mode() != "off":
        google_sync.submit_sync().result()


def _leave_job() -> None:
    from . import travel
    travel.leave_reminders()


def _time() -> tuple[int, int]:
    t = norm_time(db.get_settings().get("digest_time")) or "07:00"
    h, m = t.split(":")
    return int(h), int(m)


def start() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler()  # PCのローカル時刻
    h, m = _time()
    _scheduler.add_job(_digest_job, "cron", hour=h, minute=m, id=JOB_ID,
                       misfire_grace_time=3600, coalesce=True)
    # Googleカレンダーとの同期（連携がOFFなら何もしない）。間隔は設定で選ぶ
    _schedule_google(startup=True)
    # 家を出る時刻の通知（経路を調べた予定だけ。通信はしない）
    _scheduler.add_job(_leave_job, "interval", minutes=1, id="leave_reminder", coalesce=True, max_instances=1)
    _scheduler.start()
    log.info("朝のまとめ: 毎日 %02d:%02d", h, m)
    _catch_up()


def _catch_up() -> None:
    h, m = _time()
    now = dt.datetime.now()
    if now.time() >= dt.time(h, m) and digest.get(today()) is None:
        log.info("今日の朝のまとめがまだないので作成します")
        jobs.submit(digest.generate)


def reschedule() -> None:
    if not _scheduler:
        return
    h, m = _time()
    _scheduler.reschedule_job(JOB_ID, trigger="cron", hour=h, minute=m)
    log.info("朝のまとめの時刻を %02d:%02d に変更", h, m)
    _schedule_google()   # 1日1回の同期は朝のまとめの前なので合わせて動かす


def google_daily_time() -> tuple[int, int]:
    """1日1回の同期の時刻 = 朝のまとめの少し前（まとめにGoogleの予定が入るように）"""
    h, m = _time()
    t = dt.datetime(2000, 1, 2, h, m) - dt.timedelta(minutes=config.GOOGLE_DAILY_BEFORE_DIGEST_MIN)
    return t.hour, t.minute


def google_next_run(interval: str, last: dt.datetime | None, now: dt.datetime, startup: bool) -> dt.datetime | None:
    """自動同期の次の時刻（テストしやすいよう計算だけ分けてある）。None なら自動では同期しない。"""
    soon = now + dt.timedelta(minutes=1)
    minutes = config.GOOGLE_SYNC_INTERVALS.get(interval)
    if minutes:
        if last is None:
            return soon
        return max(soon, last + dt.timedelta(minutes=minutes))
    if interval == "daily":
        h, m = google_daily_time()
        today_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # 起動したとき、今日の時刻を過ぎていてまだ今日同期していなければ、すぐ1回
        if startup and now >= today_at and (last is None or last < today_at):
            return soon
        return today_at if now < today_at else today_at + dt.timedelta(days=1)
    return None


def _schedule_google(startup: bool = False) -> None:
    if not _scheduler:
        return
    from . import google_sync
    if _scheduler.get_job("google_sync"):
        _scheduler.remove_job("google_sync")
    interval = google_sync.sync_interval()
    nxt = google_next_run(interval, google_sync.last_sync_time(), dt.datetime.now(), startup)
    if nxt is None:
        log.info("Googleカレンダー: 自動では同期しません（「今すぐ同期」と、こちらで予定を変えたときだけ）")
        return
    minutes = config.GOOGLE_SYNC_INTERVALS.get(interval)
    if minutes:
        _scheduler.add_job(_google_job, "interval", minutes=minutes, id="google_sync", next_run_time=nxt,
                           coalesce=True, max_instances=1)
    else:
        h, m = google_daily_time()
        _scheduler.add_job(_google_job, "cron", hour=h, minute=m, id="google_sync", next_run_time=nxt,
                           misfire_grace_time=3600, coalesce=True, max_instances=1)
    log.info("Googleカレンダー: 次の自動同期 %s（%s）", nxt.strftime("%m/%d %H:%M"), interval)


def reschedule_google() -> None:
    _schedule_google()


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
