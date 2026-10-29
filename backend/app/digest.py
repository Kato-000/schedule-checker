"""朝のまとめ。区分けはプログラムで機械的に行い、LLMは「ひとこと」と「やったほうがいいこと」だけ。"""

from __future__ import annotations

import datetime as dt
import logging

from . import db, notify, planner, store
from .dates import WEEKDAYS_JA, today

log = logging.getLogger(__name__)


def build(day: dt.date | None = None, use_llm: bool = True) -> dict:
    day = day or today()
    v = store.today_view(day)
    week = store.list_events(day + dt.timedelta(days=1), day + dt.timedelta(days=7))
    content = {
        "date": v["date"],
        "events_today": v["events"],
        "overdue": v["overdue"],          # 期限切れ（本日までに含めて赤で表示）
        "due_today": v["due_today"],      # 本日まで・本日やること
        "this_week": v["this_week"],      # 今週中（7日以内）
        "no_due": v.get("no_due", []),    # 期限なし
        "events_week": week,              # この1週間の予定
        "summary": "",
        "suggestions": [],                # やったほうがいいこと（LLM）
        "llm_error": None,
    }
    if use_llm:
        try:
            a = planner.advise(day, v["events"], week, v["overdue"] + v["due_today"] + v["this_week"]
                             + v.get("no_due", [])[:10])
            content["summary"], content["suggestions"] = a["summary"], a["suggestions"]
        except Exception as e:  # noqa: BLE001 - LLMが使えなくても一覧は出す
            log.warning("朝のまとめのLLM部分に失敗: %s", e)
            content["llm_error"] = str(e)
    if not content["summary"]:
        content["summary"] = fallback_summary(content)
    return content


def fallback_summary(c: dict) -> str:
    parts = [f"今日の予定は{len(c['events_today'])}件"]
    n = len(c["due_today"])
    if n:
        parts.append(f"今日が期限のTodoが{n}件")
    if c["overdue"]:
        parts.append(f"期限切れが{len(c['overdue'])}件")
    return "、".join(parts) + "です。"


def generate(day: dt.date | None = None, send_notification: bool = True) -> dict:
    day = day or today()
    content = build(day)
    with db.connect() as c:
        c.execute("INSERT INTO digests(date, content_json) VALUES (?, ?) "
                  "ON CONFLICT(date) DO UPDATE SET content_json = excluded.content_json, "
                  "created_at = datetime('now','localtime')", (day.isoformat(), db.dumps(content)))
    if send_notification and db.get_settings().get("digest_notify", "1") == "1":
        notify.send(title(content), notification_body(content))
    return content


def get(day: dt.date | None = None) -> dict | None:
    day = day or today()
    with db.connect() as c:
        r = c.execute("SELECT content_json, created_at FROM digests WHERE date = ?", (day.isoformat(),)).fetchone()
    if not r:
        return None
    content = db.loads(r["content_json"], {})
    content["created_at"] = r["created_at"]
    return content


def title(c: dict) -> str:
    d = dt.date.fromisoformat(c["date"])
    return f"{d.month}/{d.day}（{WEEKDAYS_JA[d.weekday()]}）の予定"


def notification_body(c: dict) -> str:
    lines = [c["summary"]]
    for e in c["events_today"][:3]:
        t = e["start_time"] or "終日"
        tr = e.get("travel") or {}
        leave = f"（{tr['depart_at'][11:16]}に出発）" if tr.get("depart_at") else ""
        lines.append(f"・{t} {e['title']}{leave}")
    urgent = c["overdue"] + c["due_today"]
    if urgent:
        lines.append(f"今日まで: {urgent[0]['title']}" + (f" ほか{len(urgent) - 1}件" if len(urgent) > 1 else ""))
    return "\n".join(lines)
