"""予定に結びつかないTodo（入力欄の「Todo」）と、期限なしのTodo。"""

import sqlite3

from conftest import ev, wait_done

from app import config, db


def test_quick_todo_with_due(client, fake):
    fake.single["金曜までに見積もりを提出、急ぎ"] = {
        "title": "見積もりを提出", "due_date": "2026-10-30", "due_time": None, "priority": "high"}
    r = client.post("/api/todos/quick", json={"text": "金曜までに見積もりを提出、急ぎ"})
    assert r.status_code == 200, r.text
    body = r.json()
    t = body["todo"]
    assert t["title"] == "見積もりを提出" and t["due_date"] == "2026-10-30" and t["priority"] == "high"
    assert t["event_id"] is None and body["llm_error"] is None
    assert client.get("/api/proposals").json() == [] or all(p["status"] != "pending" for p in client.get("/api/proposals").json())
    v = client.get("/api/today").json()
    assert [x["title"] for x in v["this_week"]] == ["見積もりを提出"]
    # 早見表を渡している
    assert "日付の早見表" in fake.calls[-1][0][1]["content"]


def test_quick_todo_without_due_goes_to_no_due(client, fake):
    r = client.post("/api/todos/quick", json={"text": "牛乳を買う"})
    t = r.json()["todo"]
    assert t["due_date"] is None and t["due_time"] is None
    v = client.get("/api/today").json()
    assert [x["title"] for x in v["no_due"]] == ["牛乳を買う"]
    assert not v["overdue"] and not v["due_today"] and not v["this_week"]
    # 完了すると「今日完了」に入り、期限なしの欄から消える
    client.patch(f"/api/todos/{t['id']}", json={"status": "done"})
    v = client.get("/api/today").json()
    assert v["no_due"] == [] and [x["title"] for x in v["done_today"]] == ["牛乳を買う"]


def test_time_only_means_today(client, fake):
    fake.single["15時までに電話"] = {"title": "電話", "due_date": None, "due_time": "15:00", "priority": "medium"}
    t = client.post("/api/todos/quick", json={"text": "15時までに電話"}).json()["todo"]
    assert t["due_date"] == "2026-10-23" and t["due_time"] == "15:00"


def test_past_date_is_retried_then_clamped(client, fake):
    fake.single["月曜までに書類"] = [
        {"title": "書類", "due_date": "2026-10-19", "due_time": None, "priority": "medium"},
        {"title": "書類", "due_date": "2026-10-26", "due_time": None, "priority": "medium"}]
    t = client.post("/api/todos/quick", json={"text": "月曜までに書類"}).json()["todo"]
    assert t["due_date"] == "2026-10-26"
    fake.single["水曜までに返事"] = {"title": "返事", "due_date": "2026-10-21", "due_time": None, "priority": "medium"}
    r = client.post("/api/todos/quick", json={"text": "水曜までに返事"}).json()
    assert r["todo"]["due_date"] == "2026-10-23" and "past_date" in r["warnings"]


def test_llm_down_still_registers(client, fake):
    fake.fail_single = True
    r = client.post("/api/todos/quick", json={"text": "部屋の電球を替える"}).json()
    assert r["todo"]["title"] == "部屋の電球を替える" and r["todo"]["due_date"] is None
    assert "接続できません" in r["llm_error"]


def test_empty_rejected(client):
    assert client.post("/api/todos/quick", json={"text": "  "}).status_code == 400


def test_edit_and_clear_due(client, fake):
    t = client.post("/api/todos", json={"title": "本を返す", "due_date": "2026-10-25"}).json()
    r = client.patch(f"/api/todos/{t['id']}", json={"due_date": None, "priority": "low", "title": "図書館に本を返す"})
    assert r.status_code == 200 and r.json()["due_date"] is None and r.json()["title"] == "図書館に本を返す"
    r = client.patch(f"/api/todos/{t['id']}", json={"due_date": "2026-11-02", "due_time": "10:00"})
    assert r.json()["due_date"] == "2026-11-02" and r.json()["due_time"] == "10:00"
    assert client.patch(f"/api/todos/{t['id']}", json={"due_date": "あした"}).status_code == 400


def test_event_todo_still_needs_due(client, fake):
    text = "10/28 15時 会議"
    fake.events[text] = ev("会議", "2026-10-28", "15:00", "会議")
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    eid = client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []}).json()["event"]["id"]
    r = client.post("/api/todos", json={"title": "資料", "event_id": eid})
    assert r.status_code == 400
    t = client.post("/api/todos", json={"title": "資料", "event_id": eid, "due_date": "2026-10-27"}).json()
    assert client.patch(f"/api/todos/{t['id']}", json={"due_date": None}).status_code == 400


def test_digest_lists_no_due(client, fake):
    client.post("/api/todos/quick", json={"text": "牛乳を買う"})
    d = client.post("/api/digest/run").json()
    assert [t["title"] for t in d["no_due"]] == ["牛乳を買う"]
    advice_prompt = [m for m, s in fake.calls if "suggestions" in s["properties"]][-1][-1]["content"]
    assert "牛乳を買う（期限なし）" in advice_prompt


def test_migration_makes_due_optional(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
    CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, start_date TEXT NOT NULL,
        start_time TEXT, end_date TEXT, end_time TEXT, location TEXT, category TEXT NOT NULL DEFAULT '私用',
        is_deadline INTEGER NOT NULL DEFAULT 0, memo TEXT, source TEXT NOT NULL DEFAULT 'local',
        google_event_id TEXT, local_only INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
    CREATE TABLE todos (id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, title TEXT NOT NULL, due_date TEXT NOT NULL,
        due_time TEXT, priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'open',
        completed_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
    INSERT INTO events(title, start_date) VALUES ('会議', '2026-10-28');
    INSERT INTO todos(event_id, title, due_date, priority) VALUES (1, '資料', '2026-10-27', 'high');
    INSERT INTO todos(event_id, title, due_date) VALUES (NULL, '単独', '2026-10-24');
    """)
    old.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db()
    with db.connect() as c:
        notnull = {r[1]: r[3] for r in c.execute("PRAGMA table_info(todos)")}
        assert notnull["due_date"] == 0
        rows = [dict(r) for r in c.execute("SELECT id, event_id, title, due_date, priority FROM todos ORDER BY id")]
        assert rows == [{"id": 1, "event_id": 1, "title": "資料", "due_date": "2026-10-27", "priority": "high"},
                        {"id": 2, "event_id": None, "title": "単独", "due_date": "2026-10-24", "priority": "medium"}]
        c.execute("INSERT INTO todos(title) VALUES ('期限なし')")
        # 予定を消すとTodoも消える（外部キーが生きている）
        c.execute("DELETE FROM events WHERE id = 1")
        assert c.execute("SELECT count(*) FROM todos WHERE event_id = 1").fetchone()[0] == 0
        assert [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'idx_todos%'")] == ["idx_todos_due"]
    db.init_db()   # 2回目は何もしない


# ---- 承認待ちに入るTodoの案（音声入力で「Todo」を選んでいるとき） ----
def test_todo_proposal_from_voice(client, fake):
    fake.single["明日までに牛乳を買う"] = {"title": "牛乳を買う", "due_date": "2026-10-24", "due_time": None,
                                     "priority": "medium"}
    r = client.post("/api/proposals", json={"text": "明日までに牛乳を買う", "kind": "todo", "source": "voice"})
    assert r.status_code == 200, r.text
    p = wait_done(client, r.json()["id"])
    assert p["kind"] == "todo" and p["source"] == "voice" and p["status"] == "pending" and p["event"] is None
    assert p["todos"] == [{"title": "牛乳を買う", "due_date": "2026-10-24", "due_time": None, "priority": "medium"}]
    assert client.get("/api/today").json()["pending_count"] == 1
    # 承認するまではTodoにならない
    assert client.get("/api/today").json()["due_today"] == []
    # Todoの案は作り直しできない
    assert client.post(f"/api/proposals/{p['id']}/redraft", json={"event": {}}).status_code == 400
    todo = dict(p["todos"][0], due_date=None, priority="low")
    r = client.post(f"/api/proposals/{p['id']}/approve", json={"todos": [todo]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edited"] is True and body["todos"][0]["event_id"] is None and body["todos"][0]["due_date"] is None
    v = client.get("/api/today").json()
    assert [t["title"] for t in v["no_due"]] == ["牛乳を買う"] and v["pending_count"] == 0
    # 手本（feedback）には入らない
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_todo_proposal_when_llm_down(client, fake):
    fake.fail_single = True
    p = wait_done(client, client.post("/api/proposals", json={"text": "電球を替える", "kind": "todo"}).json()["id"])
    assert p["status"] == "pending" and "読み取れませんでした" in p["error"]
    assert p["todos"][0]["title"] == "電球を替える" and p["todos"][0]["due_date"] is None
    r = client.post(f"/api/proposals/{p['id']}/approve", json={"todos": p["todos"]})
    assert r.status_code == 200 and r.json()["edited"] is False


def test_todo_proposal_reject_and_bad_kind(client, fake):
    p = wait_done(client, client.post("/api/proposals", json={"text": "本を返す", "kind": "todo"}).json()["id"])
    assert client.post(f"/api/proposals/{p['id']}/approve", json={"todos": [{"title": " "}]}).status_code == 400
    assert client.post(f"/api/proposals/{p['id']}/reject").status_code == 200
    assert client.get("/api/today").json()["pending_count"] == 0
    assert client.post("/api/proposals", json={"text": "x", "kind": "memo"}).status_code == 400
    assert client.post("/api/proposals", json={"text": "x", "source": "fax"}).status_code == 400


def test_voice_event_proposal_marked(client, fake):
    p = client.post("/api/proposals", json={"text": "来週水曜15時から歯医者", "source": "voice"}).json()
    p = wait_done(client, p["id"])
    assert p["kind"] == "new" and p["source"] == "voice" and p["event"] is not None


def test_resume_unfinished_todo_proposal(client, fake):
    from app import jobs, store
    p = store.create_proposal("洗剤を買う", kind="todo")
    assert jobs.resume_unfinished() == 1
    assert wait_done(client, p["id"])["status"] == "pending"
