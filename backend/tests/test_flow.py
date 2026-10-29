"""入力 → 案 → 承認 → 保存 → 次回の手本、の一連の流れ。"""

from conftest import ev, wait_done

from app import examples, planner, store
from app.dates import today


def test_proposal_approve_and_learn(client, fake):
    text = "来週水曜15時に〇〇社でプレゼン"
    fake.events[text] = ev("〇〇社でプレゼン", "2026-10-28", "15:00", "プレゼン", location="〇〇社")
    fake.todos[text] = [
        {"title": "資料を仕上げる", "due_date": "2026-10-26", "due_time": None, "priority": "high"},
        {"title": "機材を確認する", "due_date": "2026-10-28", "due_time": "15:30", "priority": "medium"},
    ]
    r = client.post("/api/proposals", json={"text": text})
    assert r.status_code == 200 and r.json()["status"] == "reading"
    p = wait_done(client, r.json()["id"])
    assert p["status"] == "pending"
    assert p["event"]["start_date"] == "2026-10-28"
    # 開始(15:00)より後の時刻は、プログラム側で開始30分前に直る
    assert p["todos"][1]["due_time"] == "14:30"
    assert client.get("/api/today").json()["pending_count"] == 1

    # 1件削除・1件追加して承認 → 修正ありとして記録される
    todos = [p["todos"][0], {"title": "名刺を補充する", "due_date": "2026-10-27", "priority": "low"}]
    r = client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": todos})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edited"] is True
    assert body["diff"]["todos_removed"] == ["機材を確認する"]
    assert body["diff"]["todos_added"] == ["名刺を補充する"]
    assert len(body["event"]["todos"]) == 2

    events = client.get("/api/events", params={"start": "2026-10-26", "end": "2026-11-01"}).json()
    assert [e["title"] for e in events] == ["〇〇社でプレゼン"]
    assert client.get("/api/today").json()["pending_count"] == 0

    # 承認した内容が、次の似た予定の手本になる（相対表記で）
    own = examples.own_examples()
    assert own[0]["todos"][0] == {"title": "資料を仕上げる", "days_before": 2, "priority": "high"}

    text2 = "11月10日 13時から社内で発表"
    fake.events[text2] = ev("社内発表", "2026-11-10", "13:00", "プレゼン")
    fake.todos[text2] = []
    p2 = wait_done(client, client.post("/api/proposals", json={"text": text2}).json()["id"])
    prompt = fake.last_todo_prompt()
    assert "ユーザーの手本" in prompt and text in prompt
    assert any(e["source"] == "own" for e in p2["examples"])


def test_reject_and_already_decided(client, fake):
    text = "明日10時から歯医者"
    fake.events[text] = ev("歯医者", "2026-10-24", "10:00", "通院")
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    assert client.post(f"/api/proposals/{p['id']}/reject").json()["status"] == "rejected"
    r = client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []})
    assert r.status_code == 400


def test_past_date_is_retried(client, fake):
    text = "次の木曜15時からオンライン面接"
    fake.events[text] = [ev("面接", "2026-10-22", "15:00", "会議"), ev("面接", "2026-10-29", "15:00", "会議")]
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    assert p["event"]["start_date"] == "2026-10-29"
    assert p["questions"] == []


def test_past_date_unfixed_goes_to_question(client, fake):
    text = "次の木曜に面接"
    fake.events[text] = [ev("面接", "2026-10-22", None, "会議")]
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    assert "past_date" in p["warnings"]
    assert "過去" in p["questions"][0]


def test_llm_failures(client, fake):
    fake.fail_event = True
    p = wait_done(client, client.post("/api/proposals", json={"text": "明日会議"}).json()["id"])
    assert p["status"] == "error" and "Ollama" in p["error"]

    fake.fail_event, fake.fail_todos = False, True
    fake.events["明後日会議"] = ev("会議", "2026-10-25", None, "会議")
    p = wait_done(client, client.post("/api/proposals", json={"text": "明後日会議"}).json()["id"])
    # 予定は読めているので承認はできる
    assert p["status"] == "pending" and p["todos"] == [] and "Todo" in p["error"]


def test_redraft_after_editing_date(client, fake):
    text = "月末までに経費精算"
    fake.events[text] = ev("経費精算", "2026-10-31", None, "手続き", True)
    fake.todos[text] = [{"title": "領収書を集める", "due_date": "2026-10-30", "due_time": None, "priority": "high"}]
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    new_ev = dict(p["event"], start_date="2026-10-27")
    client.post(f"/api/proposals/{p['id']}/redraft", json={"event": new_ev})
    p = wait_done(client, p["id"])
    assert p["event"]["start_date"] == "2026-10-27"
    # 予定日より後の期限は、予定日に収まる
    assert p["todos"][0]["due_date"] == "2026-10-27"


def test_validation_errors(client, fake):
    assert client.post("/api/proposals", json={"text": "  "}).status_code == 400
    text = "明日10時に会議"
    fake.events[text] = ev("会議", "2026-10-24", "10:00", "会議")
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    bad = dict(p["event"], start_date="")
    assert client.post(f"/api/proposals/{p['id']}/approve", json={"event": bad, "todos": []}).status_code == 400
    bad = dict(p["event"], start_time="25:99")
    assert client.post(f"/api/proposals/{p['id']}/approve", json={"event": bad, "todos": []}).status_code == 400
    r = client.post(f"/api/proposals/{p['id']}/approve",
                    json={"event": p["event"], "todos": [{"title": "資料", "due_date": ""}]})
    assert r.status_code == 400


def test_todo_and_event_crud(client, fake):
    text = "明日10時に会議"
    fake.events[text] = ev("会議", "2026-10-24", "10:00", "会議")
    fake.todos[text] = [{"title": "議題をまとめる", "due_date": "2026-10-23", "due_time": None, "priority": "high"}]
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    e = client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": p["todos"]}).json()["event"]
    tid = e["todos"][0]["id"]

    v = client.get("/api/today").json()
    assert [t["title"] for t in v["due_today"]] == ["議題をまとめる"]

    t = client.patch(f"/api/todos/{tid}", json={"status": "done"}).json()
    assert t["status"] == "done" and t["completed_at"]
    v = client.get("/api/today").json()
    assert v["due_today"] == [] and len(v["done_today"]) == 1
    assert client.patch(f"/api/todos/{tid}", json={"status": "open"}).json()["completed_at"] is None

    # 予定と関係ないTodo
    t2 = client.post("/api/todos", json={"title": "牛乳を買う", "due_date": "2026-10-22"}).json()
    assert t2["event_id"] is None
    assert [t["title"] for t in client.get("/api/today").json()["overdue"]] == ["牛乳を買う"]

    e2 = client.patch(f"/api/events/{e['id']}", json={"start_time": "11:00", "memo": "会議室A"}).json()
    assert e2["start_time"] == "11:00" and e2["memo"] == "会議室A"
    client.delete(f"/api/events/{e['id']}")
    assert client.get(f"/api/events/{e['id']}").status_code == 404
    assert client.get(f"/api/todos/{tid}").status_code == 404
    assert all(t["id"] != tid for t in client.get("/api/todos").json())


def test_multi_day_event_shows_in_range(client, fake):
    text = "来週火曜から木曜まで大阪出張"
    fake.events[text] = ev("大阪出張", "2026-10-27", None, "出張", end_date="2026-10-29", location="大阪")
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []})
    assert len(client.get("/api/events", params={"start": "2026-10-28", "end": "2026-10-28"}).json()) == 1
    assert client.get("/api/events", params={"start": "2026-10-30", "end": "2026-10-31"}).json() == []


def test_normalize_todos_rules():
    base = today()
    event = {"start_date": "2026-10-28", "start_time": "15:00"}
    out = planner.normalize_todos([
        {"title": "A", "due_date": "2026-11-05", "priority": "high"},          # 予定より後 → 予定日
        {"title": "B", "due_date": "2026-10-01", "priority": "urgent"},        # 過去 → 今日、優先度は medium
        {"title": "C", "due_date": "2026-10-28", "due_time": "16:00"},         # 開始より後 → 14:30
        {"title": "A", "due_date": "2026-10-27"},                              # 重複
        {"title": " ", "due_date": "2026-10-27"},                              # 空
    ], event, base)
    assert [(t["title"], t["due_date"], t["due_time"], t["priority"]) for t in out] == [
        ("A", "2026-10-28", None, "high"),
        ("B", "2026-10-23", None, "medium"),
        ("C", "2026-10-28", "14:30", "medium"),
    ]


def test_to_relative():
    rel = examples.to_relative({"start_date": "2026-11-07", "start_time": "11:00"}, [
        {"title": "新札", "due_date": "2026-10-31", "priority": "high"},
        {"title": "出発", "due_date": "2026-11-07", "due_time": "09:30", "priority": "medium"},
        {"title": "前夜", "due_date": "2026-11-06", "due_time": "21:00", "priority": "low"},
    ])
    assert rel == [
        {"title": "新札", "days_before": 7, "priority": "high"},
        {"title": "出発", "days_before": 0, "priority": "medium", "minutes_before_start": 90},
        {"title": "前夜", "days_before": 1, "priority": "low", "time": "21:00"},
    ]


def test_seed_examples_replaced_by_own(fake):
    event = {"title": "結婚式", "category": "行事"}
    chosen = examples.select_examples(event, "友人の結婚式")
    assert chosen[0]["source"] == "seed" and "結婚式" in chosen[0]["text"]
    assert chosen[0]["reference"] is False

    # 同じ種類の自分の手本が3件たまると、その種類では初期手本を使わない
    for i in range(3):
        p = store.create_proposal(f"同窓会{i}")
        store.update_proposal(p["id"], status="pending",
                              event={"title": "同窓会", "start_date": "2026-11-20", "category": "行事"}, todos=[])
        store.approve_proposal(p["id"], {"title": "同窓会", "start_date": "2026-11-20", "category": "行事"},
                               [{"title": "会費を用意", "due_date": "2026-11-19"}])
    chosen = examples.select_examples(event, "友人の結婚式")
    assert chosen and all(c["source"] == "own" for c in chosen)
    assert all(c["reference"] for c in chosen)   # 内容が違うので「参考」扱い


def test_resume_unfinished_after_restart(client, fake):
    from app import jobs
    fake.events["明日10時に会議"] = ev("会議", "2026-10-24", "10:00", "会議")
    # 読み取り中のまま止まった案と、Todo作成中のまま止まった案を作る
    a = store.create_proposal("明日10時に会議")
    b = store.create_proposal("明日10時に会議")
    store.update_proposal(b["id"], status="drafting_todos", event=ev("会議", "2026-10-24", "10:00", "会議"))
    assert jobs.resume_unfinished() == 2
    assert wait_done(client, a["id"])["status"] == "pending"
    assert wait_done(client, b["id"])["status"] == "pending"
