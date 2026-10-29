"""朝のまとめ: 区分け・通知・LLMが使えないときの代わりの文。"""

import datetime as dt

from conftest import ev, wait_done

from app import digest, notify


def _add(client, fake, text, event, todos):
    fake.events[text] = event
    fake.todos[text] = todos
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    return client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": p["todos"]}).json()


def test_digest_sections_and_notification(client, fake):
    _add(client, fake, "今日の21時までに請求書を送る", ev("請求書送付", "2026-10-23", "21:00", "締切", True),
         [{"title": "請求書を作る", "due_date": "2026-10-23", "due_time": None, "priority": "high"}])
    _add(client, fake, "来週水曜15時にプレゼン", ev("プレゼン", "2026-10-28", "15:00", "プレゼン"),
         [{"title": "資料を仕上げる", "due_date": "2026-10-26", "due_time": None, "priority": "high"}])
    _add(client, fake, "11月20日に健康診断", ev("健康診断", "2026-11-20", None, "通院"),
         [{"title": "問診票を書く", "due_date": "2026-11-19", "due_time": None, "priority": "medium"}])
    client.post("/api/todos", json={"title": "牛乳を買う", "due_date": "2026-10-21", "priority": "low"})

    assert client.get("/api/digest").json()["missing"] is True
    d = client.post("/api/digest/run").json()
    assert [e["title"] for e in d["events_today"]] == ["請求書送付"]
    assert [t["title"] for t in d["overdue"]] == ["牛乳を買う"]
    assert [t["title"] for t in d["due_today"]] == ["請求書を作る"]
    assert [t["title"] for t in d["this_week"]] == ["資料を仕上げる"]   # 11/19 は7日より先なので入らない
    assert [e["title"] for e in d["events_week"]] == ["プレゼン"]
    assert d["summary"] == "今日は予定が1件です。"
    assert d["suggestions"] == ["来週の資料に目を通す"]

    title, body = notify.sent[-1]
    assert title == "10/23（金）の予定"
    assert "21:00 請求書送付" in body and "今日まで: 牛乳を買う ほか1件" in body

    saved = client.get("/api/digest").json()
    assert saved["due_today"][0]["title"] == "請求書を作る" and saved["created_at"]


def test_digest_without_llm(client, fake):
    fake.advice = None
    d = digest.generate(dt.date(2026, 10, 23))
    assert d["llm_error"] and d["summary"] == "今日の予定は0件です。"
    assert d["suggestions"] == []


def test_notification_can_be_turned_off(client, fake):
    client.put("/api/settings", json={"digest_notify": False})
    notify.sent.clear()
    client.post("/api/digest/run")
    assert notify.sent == []


def test_settings(client, fake):
    assert client.put("/api/settings", json={"digest_time": "6:45"}).json()["digest_time"] == "06:45"
    assert client.put("/api/settings", json={"digest_time": "朝"}).status_code == 400
    m = client.get("/api/meta").json()
    assert "会議" in m["categories"] and m["today"] == "2026-10-23"


def test_advice_prompt_has_weekdays_and_wrong_weekday_is_fixed(client, fake):
    import datetime as dt
    from app import planner, prompts
    base = dt.date(2026, 10, 25)   # 日曜日
    ev = {"title": "学会指導", "start_date": "2026-10-26", "start_time": "10:00", "category": "仕事", "is_deadline": False}
    td = {"title": "報告書作成", "due_date": "2026-10-28", "priority": "high"}
    msg = prompts.advice_messages(base, [], [ev], [td])[-1]["content"]
    assert "今日: 2026年10月25日 日曜日" in msg
    assert "明日・10/26（月） 10:00 学会指導" in msg and "期限 3日後・10/28（水）" in msg
    fake.advice = {"summary": "今日は土曜日で予定が入っておらず、明日の学会指導に向けた準備に集中できる好機です。",
                   "suggestions": ["本日、土曜日のうちに資料を見直す"]}
    a = planner.advise(base, [], [ev], [td])
    assert a["summary"].startswith("今日は日曜日で予定が入っておらず") and "明日の学会指導" in a["summary"]
    assert a["suggestions"] == ["本日、日曜日のうちに資料を見直す"]
    # ほかの日の曜日（「月曜の会議」など）はそのまま
    assert planner.fix_weekday("月曜の会議に備える", base) == "月曜の会議に備える"


def test_holidays_api(client):
    r = client.get("/api/holidays", params={"start": "2026-05-01", "end": "2026-11-30"}).json()
    assert r["2026-05-06"] == "振替休日" and r["2026-09-22"] == "国民の休日" and r["2026-11-03"] == "文化の日"
    assert "2026-05-02" not in r
    assert client.get("/api/holidays", params={"start": "2026-12-01", "end": "2026-01-01"}).status_code == 400
