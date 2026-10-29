"""自分ルール: 初期ルール、修正からのルール案、確認して有効化、Todo作成への反映。"""

import time

from conftest import ev, wait_done

from app import config, rules


def _approve_with_edit(client, fake, i):
    text = f"定例会議{i}"
    fake.events[text] = ev("定例会議", "2026-10-28", "14:00", "会議")
    fake.todos[text] = [{"title": "議事録を作る", "due_date": "2026-10-27", "priority": "medium"},
                        {"title": "議題を確認する", "due_date": "2026-10-27", "priority": "high"}]
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    # 毎回「議事録」を消す
    client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": [p["todos"][1]]})


def test_seed_rules_and_manual_rules(client, fake):
    r = client.get("/api/rules").json()
    seed = [x for x in r["rules"] if x["source"] == "seed"]
    assert len(seed) == 5 and all(x["status"] == "active" for x in seed)
    client.post("/api/rules", json={"text": "会議の準備は前日だけでよい", "category": "会議"})
    client.post("/api/rules", json={"text": "全体に効くルール", "category": "全般"})
    assert client.post("/api/rules", json={"text": "  "}).status_code == 400
    assert client.post("/api/rules", json={"text": "x", "category": "宇宙"}).status_code == 400
    assert "（会議）会議の準備は前日だけでよい" in rules.active_rules("会議")
    assert "全体に効くルール" in rules.active_rules("通院")
    assert not any("会議の準備" in t for t in rules.active_rules("通院"))
    # 初期手本を使わない設定にすると、初期ルールも外れる
    client.put("/api/settings", json={"use_seed_examples": False})
    assert len(rules.active_rules("会議")) == 2


def test_rule_candidates_from_edits(client, fake):
    fake.rules_out = [
        {"text": "会議の議事録を作るTodoは不要", "category": "会議", "reason": "会議5件で削除"},
        {"text": "予定そのものはTodoにしない", "category": "全般", "reason": "重複"},   # 初期ルールと同じ → 除く
    ]
    for i in range(config.RULES_EXTRACT_EVERY - 1):
        _approve_with_edit(client, fake, i)
    assert rules.unchecked_edits() == config.RULES_EXTRACT_EVERY - 1
    assert not [x for x in client.get("/api/rules").json()["rules"] if x["status"] == "candidate"]

    _approve_with_edit(client, fake, 99)     # 5件目で自動的にルール案を作る
    for _ in range(100):
        cands = [x for x in client.get("/api/rules").json()["rules"] if x["status"] == "candidate"]
        if cands:
            break
        time.sleep(0.02)
    assert [(c["text"], c["category"]) for c in cands] == [("会議の議事録を作るTodoは不要", "会議")]
    assert rules.unchecked_edits() == 0
    prompt = next(m for m, s in fake.calls if "rules" in s.get("properties", {}))[-1]["content"]
    assert "「議事録を作る」を5回削除" in prompt

    # 案のままではTodo作成に使われない → 有効にすると使われる
    assert not any("会議の議事録を作るTodoは不要" in t for t in rules.active_rules("会議"))
    client.patch(f"/api/rules/{cands[0]['id']}", json={"status": "active"})
    _approve_with_edit(client, fake, 100)
    assert "（会議）会議の議事録を作るTodoは不要" in fake.last_todo_prompt()


def test_manual_extract_and_auto_off(client, fake):
    client.put("/api/settings", json={"rules_auto": False})
    fake.rules_out = [{"text": "通院の前日に保険証を確認する", "category": "通院", "reason": "追加3件"}]
    for i in range(config.RULES_EXTRACT_EVERY):
        _approve_with_edit(client, fake, i)
    time.sleep(0.1)
    assert not [x for x in client.get("/api/rules").json()["rules"] if x["status"] == "candidate"]
    added = client.post("/api/rules/extract").json()["added"]
    assert [a["text"] for a in added] == ["通院の前日に保険証を確認する"]
    rid = added[0]["id"]
    client.patch(f"/api/rules/{rid}", json={"status": "rejected"})
    # 却下したものは、同じ内容の案を再び作らない
    added = client.post("/api/rules/extract").json()["added"]
    assert added == []
    client.delete(f"/api/rules/{rid}")
    assert all(x["id"] != rid for x in client.get("/api/rules").json()["rules"])
