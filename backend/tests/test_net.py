"""ネット連携：足りない情報を調べる・家を出る時刻（経路）。通信先は偽物に差し替える。"""

import datetime as dt

import pytest
from conftest import ev, wait_done
from fastapi.testclient import TestClient

from app import digest, lookup, net, notify, security, store, travel


class FakeSearch:
    def __init__(self):
        self.queries = []
        self.fail = False

    def search(self, query, max_results):
        self.queries.append(query)
        if self.fail:
            raise net.NetError("Web検索（Ollama）のキーが正しくないか、利用登録がされていません")
        return [{"title": f"{query} の結果{i}", "url": f"https://example.com/{len(self.queries)}/{i}",
                 "content": "東京都文京区後楽1-3-61 開場17:00 開演18:00"} for i in range(2)]


def nav_route(*legs):
    """legs: (from_time, to_time) のリスト → NAVITIMEの応答の形"""
    items = []
    for f, t in legs:
        items.append({"summary": {"move": {"from_time": f + ":00+09:00", "to_time": t + ":00+09:00",
                                           "time": 40, "transit_count": 1, "fare": {"unit_0": 300}}},
                      "sections": [
                          {"type": "point", "name": "出発地"},
                          {"type": "move", "move": "walk", "time": 8, "from_time": f + ":00+09:00",
                           "to_time": f[:-2] + "18:00+09:00"},
                          {"type": "point", "name": "A駅"},
                          {"type": "move", "move": "local_train", "line_name": "〇〇線", "time": 25},
                          {"type": "point", "name": "B駅"},
                          {"type": "move", "move": "walk", "time": 7},
                          {"type": "point", "name": "到着地"}]})
    return {"items": items}


class FakeNavi:
    def __init__(self):
        self.addresses = {"東京都千代田区1-1": {"name": "東京都千代田区千代田1-1", "lat": 35.68, "lon": 139.75},
                          "東京都文京区後楽1-3-61": {"name": "東京都文京区後楽1丁目3-61", "lat": 35.70, "lon": 139.75}}
        self.calls = []
        self.response = nav_route(("2026-10-28T09:05", "2026-10-28T09:45"), ("2026-10-28T09:12", "2026-10-28T09:49"),
                                  ("2026-10-28T09:20", "2026-10-28T10:02"))

    def address(self, word):
        self.calls.append(("address", word))
        return self.addresses.get(word)

    def route(self, mode, start, goal, goal_time):
        self.calls.append(("route", mode, start, goal, goal_time))
        return self.response


@pytest.fixture()
def nfake(fake, monkeypatch):
    s, n = FakeSearch(), FakeNavi()
    monkeypatch.setattr(net, "search_client", s)
    monkeypatch.setattr(net, "navi_client", n)
    return s, n


def enable(client, home=True):
    r = client.put("/api/net", json={"enabled": True, "ollama_key": "ollama-xyz", "rapidapi_key": "rapid-abc",
                                     **({"home_address": "東京都千代田区1-1"} if home else {})})
    assert r.status_code == 200, r.text
    return r.json()


def make_event(client, fake, text="10/28 10時 〇〇クリニック", **kw):
    fake.events[text] = ev(kw.pop("title", "通院"), "2026-10-28", kw.pop("time", "10:00"), "通院", **kw)
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    return client.post(f"/api/proposals/{p['id']}/approve", json={"event": p["event"], "todos": []}).json()["event"]


# ---------------------------------------------------------------------------
def test_off_by_default_and_nothing_sent(client, nfake):
    s, n = nfake
    st = client.get("/api/net").json()
    assert st["enabled"] is False and st["ollama_key_set"] is False and st["log"] == []
    assert client.get("/api/meta").json()["net_enabled"] is False
    e = {"title": "ライブ", "start_date": "2026-10-28", "location": "東京ドーム"}
    # 検索語の確認だけなら通信しない
    assert client.post("/api/net/queries", json={"event": e}).json()["queries"] == ["東京ドーム 住所", "ライブ 東京ドーム 10月28日 開始時間"]
    r = client.post("/api/net/lookup", json={"event": e})
    assert r.status_code == 400 and "オフ" in r.json()["detail"]
    assert s.queries == [] and n.calls == []


def test_build_queries():
    assert lookup.build_queries({"title": "歯医者", "start_date": "2026-10-28", "start_time": "10:00",
                                 "location": "ヤマダ歯科", "address": "東京都…"}) == ["歯医者 ヤマダ歯科"]
    assert lookup.build_queries({"title": "〇〇展", "start_date": "2026-11-03"}) == ["〇〇展 場所", "〇〇展 11月3日 開始時間"]
    assert lookup.build_queries({"title": "提出", "start_date": "2026-11-03", "is_deadline": True}) == ["提出 場所"]


def test_settings_keys_home_and_phone(client, nfake):
    s, n = nfake
    st = enable(client)
    assert st["ollama_key_set"] and st["rapidapi_key_set"] and "ollama-xyz" not in str(st)
    assert st["home_label"] == "東京都千代田区千代田1-1" and st["home_set"] is True
    assert ("address", "東京都千代田区1-1") in n.calls
    assert any("自宅" in x["sent"] for x in st["log"])
    r = client.put("/api/net", json={"home_address": "どこか不明"})
    assert r.status_code == 400 and "見つかりません" in r.json()["detail"]
    assert client.put("/api/net", json={"rapidapi_key": "a b"}).status_code == 400
    assert client.put("/api/net", json={"arrive_margin_min": 500}).status_code == 400
    st = client.put("/api/net", json={"ollama_key": ""}).json()
    assert st["ollama_key_set"] is False
    # スマホからは設定を変えられず、住所や送信記録も見えない
    import app.security as sec
    with TestClient(client.app, client=("192.168.1.20", 5000), base_url="https://testserver") as phone:
        orig = sec.check_session
        sec.check_session = lambda t: True
        try:
            assert phone.put("/api/net", json={"enabled": False}).status_code == 403
            pst = phone.get("/api/net").json()
            assert pst["enabled"] is True and "home_address" not in pst and "log" not in pst
        finally:
            sec.check_session = orig


def test_lookup_returns_candidates_only(client, nfake, fake):
    s, n = nfake
    enable(client, home=False)
    fake.lookup_out = {"place_name": "東京ドーム", "address": "東京都文京区後楽1-3-61", "start_time": "18:00",
                       "end_time": None, "hours": None, "source": 1, "note": None}
    e = {"title": "ライブ", "start_date": "2026-10-28", "start_time": None, "location": "東京ドーム"}
    shown = client.post("/api/net/queries", json={"event": e}).json()["queries"]
    # 画面に見せていない検索語は送らない
    r = client.post("/api/net/lookup", json={"event": e, "queries": shown + ["ほかの予定の名前"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert s.queries == shown
    fields = {c["field"]: c["value"] for c in body["candidates"]}
    assert fields == {"address": "東京都文京区後楽1-3-61", "start_time": "18:00"}   # 場所は同じなので候補にしない
    assert body["source"]["url"].startswith("https://example.com/")
    # 検索結果はPCのLLMが読む
    assert "東京都文京区後楽1-3-61" in fake.lookup_prompts[-1]
    log = client.get("/api/net").json()["log"]
    assert [x["sent"] for x in log[:2]] == [f"検索語: {q}" for q in reversed(shown)]
    # 何も反映されていない（予定はまだない）
    assert client.get("/api/events", params={"start": "2026-10-01", "end": "2026-11-30"}).json() == []


def test_lookup_error_is_reported(client, nfake):
    s, n = nfake
    enable(client, home=False)
    s.fail = True
    r = client.post("/api/net/lookup", json={"event": {"title": "ライブ", "start_date": "2026-10-28"}})
    assert r.status_code == 400 and "キー" in r.json()["detail"]
    assert client.get("/api/net").json()["log"][0]["ok"] == 0


def test_route_transit(client, nfake, fake):
    s, n = nfake
    enable(client)
    e = make_event(client, fake, location="東京都文京区後楽1-3-61")
    r = client.post(f"/api/events/{e['id']}/route", json={})
    assert r.status_code == 200, r.text
    tr = r.json()["travel"]
    # 10:00開始・10分前に着きたい → 9:50着。間に合う中でいちばん遅い 9:12発 を選ぶ
    assert tr["depart_at"] == "2026-10-28T09:12" and tr["arrive_at"] == "2026-10-28T09:49"
    assert tr["goal_at"] == "2026-10-28T09:50" and tr["mode"] == "transit" and tr["fare"] == 300
    assert [st["label"] for st in tr["steps"]] == ["徒歩", "電車", "徒歩"]
    assert tr["steps"][1]["line"] == "〇〇線" and tr["steps"][1]["from"] == "A駅" and tr["steps"][1]["to"] == "B駅"
    route_call = [c for c in n.calls if c[0] == "route"][-1]
    assert route_call[1] == "transit" and route_call[4] == dt.datetime(2026, 10, 28, 9, 50)
    assert route_call[2] == (35.68, 139.75) and route_call[3] == (35.70, 139.75)
    # 一覧・今日の画面でも見える
    assert client.get(f"/api/events/{e['id']}").json()["travel"]["depart_at"] == "2026-10-28T09:12"
    # 送った内容の記録（タイトルは送らない）
    sent = client.get("/api/net").json()["log"][0]["sent"]
    assert "到着: 2026-10-28 09:50" in sent and "通院" not in sent
    # 2回目は目的地の位置を覚えているので住所検索をしない
    n.calls.clear()
    client.post(f"/api/events/{e['id']}/route", json={"mode": "car"})
    assert [c[0] for c in n.calls] == ["route"] and n.calls[0][1] == "car"


def test_route_errors(client, nfake, fake):
    s, n = nfake
    enable(client, home=False)
    e = make_event(client, fake, location="東京都文京区後楽1-3-61")
    r = client.post(f"/api/events/{e['id']}/route", json={})
    assert r.status_code == 400 and "自宅" in r.json()["detail"]
    client.put("/api/net", json={"home_address": "東京都千代田区1-1"})
    e2 = make_event(client, fake, text="10/28 終日 休み", title="休み", time=None, location="東京都文京区後楽1-3-61")
    assert "開始時刻" in client.post(f"/api/events/{e2['id']}/route", json={}).json()["detail"]
    e3 = make_event(client, fake, text="10/28 10時 打ち合わせ", title="打ち合わせ")
    assert "場所か住所" in client.post(f"/api/events/{e3['id']}/route", json={}).json()["detail"]
    e4 = make_event(client, fake, text="10/28 10時 謎の店", title="謎の店", location="謎の店")
    assert "位置が分かりません" in client.post(f"/api/events/{e4['id']}/route", json={}).json()["detail"]
    client.put("/api/net", json={"enabled": False})
    assert "オフ" in client.post(f"/api/events/{e['id']}/route", json={}).json()["detail"]


def test_address_used_and_travel_cleared_on_change(client, nfake, fake):
    s, n = nfake
    enable(client)
    e = make_event(client, fake, location="東京ドーム")
    # 調べた住所を反映すると、住所で経路を調べる
    e = client.patch(f"/api/events/{e['id']}", json={"address": "東京都文京区後楽1-3-61"}).json()
    assert e["address"] == "東京都文京区後楽1-3-61"
    e = client.post(f"/api/events/{e['id']}/route", json={}).json()
    assert ("address", "東京都文京区後楽1-3-61") in n.calls and e["travel"]
    # 名前だけ変えても経路は残る。時刻を変えたら消える
    assert client.patch(f"/api/events/{e['id']}", json={"title": "野球観戦"}).json()["travel"]
    assert client.patch(f"/api/events/{e['id']}", json={"start_time": "13:00"}).json()["travel"] is None
    client.post(f"/api/events/{e['id']}/route", json={})
    assert client.delete(f"/api/events/{e['id']}/route").json()["travel"] is None


def test_address_from_proposal_is_saved(client, nfake, fake):
    text = "10/28 10時 ライブ"
    fake.events[text] = ev("ライブ", "2026-10-28", "10:00", "行事", location="東京ドーム")
    p = wait_done(client, client.post("/api/proposals", json={"text": text}).json()["id"])
    evd = dict(p["event"], address="東京都文京区後楽1-3-61")
    e = client.post(f"/api/proposals/{p['id']}/approve", json={"event": evd, "todos": []}).json()["event"]
    assert e["address"] == "東京都文京区後楽1-3-61"


def test_leave_reminder_once(client, nfake, fake):
    s, n = nfake
    enable(client)
    e = make_event(client, fake, location="東京都文京区後楽1-3-61")
    client.post(f"/api/events/{e['id']}/route", json={})
    notify.sent.clear()
    assert travel.leave_reminders(dt.datetime(2026, 10, 28, 8, 50)) == 0
    assert travel.leave_reminders(dt.datetime(2026, 10, 28, 8, 58)) == 1
    assert notify.sent[-1][0].startswith("あと14分で出発: 通院") and "09:12に出ると09:49に着きます" in notify.sent[-1][1]
    assert travel.leave_reminders(dt.datetime(2026, 10, 28, 9, 0)) == 0   # 1回だけ
    client.put("/api/net", json={"leave_notify_min": 0})
    assert travel.leave_reminders(dt.datetime(2026, 10, 28, 9, 5)) == 0


def test_digest_shows_departure(client, nfake, fake):
    s, n = nfake
    enable(client)
    e = make_event(client, fake, location="東京都文京区後楽1-3-61")
    client.post(f"/api/events/{e['id']}/route", json={})
    c = digest.build(dt.date(2026, 10, 28), use_llm=False)
    assert "・10:00 通院（09:12に出発）" in digest.notification_body(c)


def test_parse_route_falls_back_when_none_in_time():
    r = travel.parse_route(nav_route(("2026-10-28T09:30", "2026-10-28T10:05")), dt.datetime(2026, 10, 28, 9, 50), "car")
    assert r["depart_at"] == "2026-10-28T09:30" and r["mode"] == "car"
    with pytest.raises(net.NetError):
        travel.parse_route({"items": []}, dt.datetime(2026, 10, 28, 9, 50), "car")


def test_real_search_client_request_shape(fake, monkeypatch):
    """本物の SearchClient が送る中身（ローカルの偽サーバーで受ける）。"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app import config, secret_store
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            got["auth"] = self.headers.get("Authorization")
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            code = 401 if got["body"]["query"] == "bad" else 200
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"results": [{"title": "T", "url": "https://x", "content": "C"}]}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "OLLAMA_SEARCH_URL", f"http://127.0.0.1:{srv.server_port}/api/web_search")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    secret_store.set(net.OLLAMA_KEY, "k-123")
    try:
        r = net.SearchClient().search("東京ドーム 住所", 4)
        assert r == [{"title": "T", "url": "https://x", "content": "C"}]
        assert got == {"auth": "Bearer k-123", "body": {"query": "東京ドーム 住所", "max_results": 4}}
        with pytest.raises(net.NetError, match="キーが正しくない"):
            net.SearchClient().search("bad", 4)
    finally:
        srv.shutdown()


def test_open_url_only_from_pc_and_http(client, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open_new_tab", lambda u: opened.append(u) or True)
    url = "https://www.google.com/maps/search/?api=1&query=%E6%9D%B1%E4%BA%AC%E3%83%89%E3%83%BC%E3%83%A0"
    assert client.post("/api/open_url", json={"url": url}).json() == {"ok": True}
    assert opened == [url]
    for bad in ["file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "ms-settings:", "https://"]:
        assert client.post("/api/open_url", json={"url": bad}).status_code == 400
    import app.security as sec
    with TestClient(client.app, client=("192.168.1.20", 5000), base_url="https://testserver") as phone:
        orig = sec.check_session
        sec.check_session = lambda t: True
        try:
            assert phone.post("/api/open_url", json={"url": url}).status_code == 403
        finally:
            sec.check_session = orig
    assert opened == [url]


def test_map_embed_urls(client, nfake):
    import urllib.parse as up
    r = client.post("/api/net/map", json={"kind": "place", "q": "東京ドーム"})
    assert r.status_code == 400 and "オフ" in r.json()["detail"]
    client.put("/api/net", json={"enabled": True})
    r = client.post("/api/net/map", json={"kind": "place", "q": "東京ドーム"})
    assert r.status_code == 400 and "地図のキー" in r.json()["detail"]
    st = client.put("/api/net", json={"maps_key": "maps-123"}).json()
    assert st["maps_key_set"] is True and st["map_ready"] is True
    r = client.post("/api/net/map", json={"kind": "search", "q": "福岡  歯医者"}).json()
    u = up.urlparse(r["url"])
    assert u.netloc == "www.google.com" and u.path == "/maps/embed/v1/search"
    assert up.parse_qs(u.query) == {"key": ["maps-123"], "language": ["ja"], "region": ["JP"], "q": ["福岡 歯医者"]}
    # 経路は自宅の住所が必要。経路検索のキーがなくても住所だけ保存できる
    assert "自宅" in client.post("/api/net/map", json={"kind": "directions", "destination": "東京ドーム"}).json()["detail"]
    st = client.put("/api/net", json={"home_address": "福岡県福岡市西区元岡744"}).json()
    assert st["home_address_set"] is True and st["home_set"] is False
    r = client.post("/api/net/map", json={"kind": "directions", "destination": "東京ドーム", "mode": "car"}).json()
    qs = up.parse_qs(up.urlparse(r["url"]).query)
    assert qs["origin"] == ["福岡県福岡市西区元岡744"] and qs["destination"] == ["東京ドーム"] and qs["mode"] == ["driving"]
    assert client.post("/api/net/map", json={"kind": "streetview", "q": "x"}).status_code == 400
    log = [x["sent"] for x in client.get("/api/net").json()["log"]]
    assert "検索: 福岡 歯医者" in log and any(x.startswith("経路: 自宅（福岡県") for x in log)
