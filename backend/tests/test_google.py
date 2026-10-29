"""Googleカレンダー連携: 取り込み・送信・ローカル限定・衝突・同期トークン切れ。"""

from conftest import ev, wait_done

from app import google_sync as gs



def flush():
    """同期の処理（別スレッド）が終わるのを待つ。"""
    return gs.submit_sync().result(timeout=5)


def events_titles(client, start="2026-10-01", end="2026-12-31"):
    return sorted(e["title"] for e in client.get("/api/events", params={"start": start, "end": end}).json())


# ---------------------------------------------------------------------------
def test_mode_requires_connection(client, fake):
    r = client.put("/api/google", json={"mode": "import"})
    assert r.status_code == 400 and "接続" in r.json()["detail"]
    assert client.get("/api/google").json()["mode"] == "off"
    assert gs.sync_once() == {"skipped": "off"}


def test_client_secret_validation(client, fake):
    assert client.post("/api/google/client_secret", json={"content": "not json"}).status_code == 400
    assert client.post("/api/google/client_secret", json={"content": '{"web": {}}'}).status_code == 400
    r = client.post("/api/google/client_secret", json={"content": '{"installed": {"client_id": "x"}}'})
    assert r.status_code == 200 and r.json()["client_secret"] is True


def test_conversion():
    timed = gs.from_google({"summary": "会議", "start": {"dateTime": "2026-10-28T15:00:00+09:00"},
                            "end": {"dateTime": "2026-10-28T16:30:00+09:00"}})
    assert (timed["start_date"], timed["start_time"], timed["end_time"]) == ("2026-10-28", "15:00", "16:30")
    allday = gs.from_google({"summary": "出張", "start": {"date": "2026-10-27"}, "end": {"date": "2026-10-30"}})
    assert (allday["start_date"], allday["start_time"], allday["end_date"]) == ("2026-10-27", None, "2026-10-29")
    one = gs.from_google({"summary": "休み", "start": {"date": "2026-10-27"}, "end": {"date": "2026-10-28"}})
    assert one["end_date"] is None

    body = gs.to_google({"title": "出張", "start_date": "2026-10-27", "end_date": "2026-10-29"})
    assert body["start"] == {"date": "2026-10-27"} and body["end"] == {"date": "2026-10-30"}
    body = gs.to_google({"title": "締切", "start_date": "2026-10-28", "start_time": "21:00", "is_deadline": True})
    assert body["start"]["dateTime"].startswith("2026-10-28T21:00:00")
    assert body["end"]["dateTime"].startswith("2026-10-28T21:30:00")
    # 送るのは予定の項目だけ（Todo・メモ・種類は送らない）
    assert set(body) == {"summary", "location", "start", "end"}


def test_import_mode(client, fake, gfake):
    gfake.add("a1", "歯医者", "2026-10-26T10:00", "2026-10-26T11:00", location="駅前歯科")
    gfake.add("a2", "大阪出張", "2026-10-27", "2026-10-30")
    gfake.add("a3", "先月の飲み会", "2026-09-30T19:00")          # 過去 → Todo案は作らない
    fake.events["歯医者（駅前歯科）"] = ev("歯医者", "2026-10-23", None, "通院")
    fake.todos["歯医者（駅前歯科）"] = [{"title": "診察券を用意する", "due_date": "2026-10-25", "priority": "high"}]

    gs.set_mode("import")   # 画面から切り替えると自動で1回同期するので、ここでは直接切り替える
    r = client.post("/api/google/sync").json()
    assert r["result"]["pull"]["added"] == 3 and r["result"]["pull"]["proposals"] == 2
    assert "push" not in r["result"]     # 取り込みのみ
    assert gfake.calls[0][1] is None and gfake.calls[0][2].startswith("2026-09-23")  # 初回は30日前から
    assert events_titles(client, "2026-09-01") == ["先月の飲み会", "大阪出張", "歯医者"]

    # 取り込んだ予定のTodo案（種類はLLMが判定、日時はGoogleのまま）
    props = [p for p in client.get("/api/proposals").json() if p["kind"] == "import"]
    p = wait_done(client, next(x["id"] for x in props if x["input_text"] == "歯医者（駅前歯科）"))
    assert p["event"]["category"] == "通院" and p["event"]["start_time"] == "10:00"
    assert p["todos"][0]["title"] == "診察券を用意する"
    res = client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": p["todos"]}).json()
    e = res["event"]
    assert e["source"] == "google" and e["category"] == "通院" and len(e["todos"]) == 1
    assert len(events_titles(client, "2026-09-01")) == 3    # 予定は増えない
    # 却下しても予定は残る
    other = next(x for x in client.get("/api/proposals").json() if x["kind"] == "import")
    wait_done(client, other["id"])
    client.post(f"/api/proposals/{other['id']}/reject")
    assert "大阪出張" in events_titles(client)

    # 2回目は同期トークンを使い、変更・削除を反映
    gfake.change("a2", summary="大阪・京都出張")
    gfake.cancel("a3")                     # Todoなし → そのまま削除
    gfake.cancel("a1")                     # 未完了のTodoあり → 消してよいか確認
    r = flush()["pull"]
    assert gfake.calls[-1][1] is not None
    assert r["updated"] == 1 and r["deleted"] == 1 and r["conflicts"] == 1
    assert events_titles(client, "2026-09-01") == ["大阪・京都出張", "歯医者"]
    conflict = next(x for x in client.get("/api/proposals").json() if x["kind"] == "conflict")
    assert conflict["google_deleted"] is True
    client.post(f"/api/proposals/{conflict['id']}/resolve", json={"keep": "google"})
    assert events_titles(client, "2026-09-01") == ["大阪・京都出張"]


def test_two_way_push_and_local_only(client, fake, gfake):
    client.put("/api/google", json={"mode": "two_way"})
    flush()
    for text, lo in (("来週水曜15時にプレゼン", False), ("明日10時に通院", True)):
        fake.events[text] = ev(text[:6], "2026-10-28", "15:00", "プレゼン")
        p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
        client.post(f"/api/proposals/{p['id']}/approve",
                    json={"event": dict(p["event"], local_only=lo), "todos": [
                        {"title": "資料を作る", "due_date": "2026-10-26"}]})
    flush()
    inserts = [c for c in gfake.calls if c[0] == "insert"]
    assert len(inserts) == 1                              # ローカル限定は送らない
    assert inserts[0][2]["summary"] == "来週水曜15"
    assert "資料" not in str(inserts[0][2])               # Todoは送らない
    events = client.get("/api/events", params={"start": "2026-10-28", "end": "2026-10-28"}).json()
    pushed = next(e for e in events if not e["local_only"])
    assert pushed["google_event_id"] and pushed["needs_push"] == 0
    assert client.get("/api/google").json()["pending_push"] == 0

    # 取り込み直しても重複しない
    flush()
    assert len(client.get("/api/events", params={"start": "2026-10-28", "end": "2026-10-28"}).json()) == 2

    # 変更 → patch、ローカル限定にする → Googleから削除、削除 → delete
    client.patch(f"/api/events/{pushed['id']}", json={"start_time": "16:00"})
    flush()
    assert gfake.calls[-1][0] in ("patch", "list")
    assert any(c[0] == "patch" for c in gfake.calls)
    gid = pushed["google_event_id"]
    client.patch(f"/api/events/{pushed['id']}", json={"local_only": True})
    flush()
    assert ("delete", gid) in gfake.calls
    assert client.get(f"/api/events/{pushed['id']}").json()["google_event_id"] is None
    # ローカル限定を外すと、また送られる
    client.patch(f"/api/events/{pushed['id']}", json={"local_only": False})
    flush()
    new_gid = client.get(f"/api/events/{pushed['id']}").json()["google_event_id"]
    assert new_gid and new_gid != gid
    client.delete(f"/api/events/{pushed['id']}")
    flush()
    assert ("delete", new_gid) in gfake.calls


def test_push_error_is_retried(client, fake, gfake):
    client.put("/api/google", json={"mode": "two_way"})
    flush()
    gfake.fail = True
    fake.events["月末までに精算"] = ev("精算", "2026-10-31", None, "手続き", True)
    p = wait_done(client, client.post("/api/proposals", json={"text": "月末までに精算"}).json()["id"])
    client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []})
    flush()
    st = client.get("/api/google").json()
    assert st["pending_push"] == 1 and st["push_errors"] == 1
    gfake.fail = False
    flush()
    st = client.get("/api/google").json()
    assert st["pending_push"] == 0 and st["push_errors"] == 0


def test_conflict_both_changed(client, fake, gfake):
    gfake.add("c1", "定例会議", "2026-10-29T10:00", "2026-10-29T11:00")
    client.put("/api/google", json={"mode": "two_way"})
    flush()
    local = client.get("/api/events", params={"start": "2026-10-29", "end": "2026-10-29"}).json()[0]
    gfake.calls.clear()
    # PCで変えた直後（まだ送る前）にGoogleでも変わった。送る前の状態を作るため、自動同期を一時的に止める
    orig = gs.submit_sync
    gs.submit_sync = lambda: type("F", (), {"result": lambda self, timeout=None: None})()
    try:
        client.patch(f"/api/events/{local['id']}", json={"start_time": "13:00"})
    finally:
        gs.submit_sync = orig
    gfake.change("c1", start={"dateTime": "2026-10-29T14:00:00+09:00"}, end={"dateTime": "2026-10-29T15:00:00+09:00"})
    r = flush()
    assert r["pull"]["conflicts"] == 1
    c = next(x for x in client.get("/api/proposals").json() if x["kind"] == "conflict")
    assert c["event"]["start_time"] == "13:00" and c["google"]["start_time"] == "14:00"
    # 衝突中は送らない（両方の予定を残したまま、選ぶまで待つ）
    assert not any(x[0] == "patch" for x in gfake.calls)
    assert client.post(f"/api/proposals/{c['id']}/approve", json={"event": c["event"]}).status_code == 400

    client.post(f"/api/proposals/{c['id']}/resolve", json={"keep": "local"})
    flush()
    assert gfake.events["c1"]["start"]["dateTime"].startswith("2026-10-29T13:00")
    assert client.get(f"/api/events/{local['id']}").json()["start_time"] == "13:00"


def test_sync_token_expired_resyncs(client, fake, gfake):
    gfake.add("t1", "ジム", "2026-10-30T19:00")
    client.put("/api/google", json={"mode": "import"})
    flush()
    gfake.token_expired = True
    gfake.add("t2", "散髪", "2026-10-31T11:00")
    r = flush()
    assert "error" not in r and r["pull"]["added"] == 1
    assert events_titles(client) == ["ジム", "散髪"]


def test_switch_to_two_way_sends_upcoming_local_events(client, fake, gfake):
    for text, date in (("来週の会議", "2026-10-28"), ("先月の会議", "2026-09-10")):
        fake.events[text] = ev(text, date, "10:00", "会議")
        p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
        client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []})
    client.put("/api/google", json={"mode": "two_way"})
    flush()
    sent = [c[2]["summary"] for c in gfake.calls if c[0] == "insert"]
    assert sent == ["来週の会議"]       # 過去の予定までは送らない


def test_disconnect(client, fake, gfake):
    client.put("/api/google", json={"mode": "import"})
    st = client.post("/api/google/disconnect").json()
    assert st["connected"] is False and st["mode"] == "off"
