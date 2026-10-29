import os
import time

os.environ["SC_TODAY"] = "2026-10-23"   # 金曜日
os.environ["SC_SCHEDULER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, examples, llm, notify  # noqa: E402


class FakeLLM:
    """プロンプトの種類（スキーマ）を見て、決めた答えを返す偽のLLM。"""

    def __init__(self):
        self.calls = []
        self.events = {}        # 入力文 → event（またはeventのリスト=呼ぶたびに順に返す）
        self.todos = {}         # 入力文 → todos
        self.fail_event = False
        self.fail_todos = False
        self.advice = {"summary": "今日は予定が1件です。", "suggestions": ["来週の資料に目を通す"]}
        self.rules_out = []     # ルール抽出の答え
        self.default_category = "私用"   # 登録していない入力（Googleから来た予定など）の種類
        self.single = {}        # 入力文 → todo（単体Todoの読み取り。リストなら呼ぶたびに順に返す）
        self.fail_single = False
        self.lookup_out = {"place_name": None, "address": None, "start_time": None, "end_time": None,
                           "hours": None, "source": None, "note": None}
        self.lookup_prompts = []

    def chat(self, messages, schema):
        self.calls.append((messages, schema))
        user = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
        props = schema.get("properties", {})
        if "rules" in props:
            return {"rules": [dict(r) for r in self.rules_out]}, 0.1
        if "hours" in props:      # ネットで調べた結果の読み取り
            self.lookup_prompts.append(messages[-1]["content"])
            return dict(self.lookup_out), 0.1
        if "todo" in props:
            if self.fail_single:
                raise llm.LLMError("Ollamaに接続できません（テスト）")
            text = messages[1]["content"].split("入力: ")[-1]
            t = self.single.get(text) or {"title": text, "due_date": None, "due_time": None, "priority": "medium"}
            if isinstance(t, list):
                t = t.pop(0) if len(t) > 1 else t[0]
            return {"todo": dict(t)}, 0.1
        if "event" in props:
            if self.fail_event:
                raise llm.LLMError("Ollamaに接続できません（テスト）")
            text = messages[1]["content"].split("入力: ")[-1]
            ev = self.events.get(text) or {"title": text, "start_date": "2026-10-23", "start_time": None,
                                           "end_date": None, "end_time": None, "location": None,
                                           "category": self.default_category, "is_deadline": False}
            if isinstance(ev, list):
                ev = ev.pop(0) if len(ev) > 1 else ev[0]
            return {"event": dict(ev), "questions": []}, 0.1
        if "todos" in props:
            if self.fail_todos:
                raise llm.LLMError("タイムアウト（テスト）")
            text = user.split("元の入力: ")[1].split("\n")[0]
            return {"todos": [dict(t) for t in self.todos.get(text, [])]}, 0.1
        if "suggestions" in props:
            if self.advice is None:
                raise llm.LLMError("失敗（テスト）")
            return dict(self.advice), 0.1
        raise AssertionError("unknown schema")

    def last_todo_prompt(self):
        for messages, schema in reversed(self.calls):
            if "todos" in schema.get("properties", {}):
                return messages[-1]["content"]
        return None

    def status(self):
        return {"ok": True, "message": "fake"}

    def warm(self):
        self.warmed = getattr(self, "warmed", 0) + 1
        return True


class FakeGoogle:
    """偽のGoogleカレンダー。etag は更新のたびに変わる。"""

    def __init__(self):
        self.events = {}          # id → event
        self.seq = 0
        self.token_expired = False
        self.calls = []
        self.fail = False

    def _etag(self):
        self.seq += 1
        return f'"e{self.seq}"'

    def add(self, gid, summary, start, end=None, location=None, status="confirmed"):
        """start/end は 'YYYY-MM-DD' か 'YYYY-MM-DDTHH:MM'。"""
        def t(s):
            return {"date": s} if len(s) == 10 else {"dateTime": s + ":00+09:00"}
        ev = {"id": gid, "status": status, "summary": summary, "start": t(start),
              "end": t(end or start), "etag": self._etag()}
        if location:
            ev["location"] = location
        self.events[gid] = ev
        return ev

    def change(self, gid, **fields):
        self.events[gid].update(fields)
        self.events[gid]["etag"] = self._etag()

    def cancel(self, gid):
        self.events[gid] = {"id": gid, "status": "cancelled", "etag": self._etag()}

    def list_events(self, sync_token, time_min):
        from app import google_sync as gs
        self.calls.append(("list", sync_token, time_min))
        if sync_token and self.token_expired:
            self.token_expired = False
            raise gs.SyncTokenExpired()
        return list(self.events.values()), f"tok{self.seq}"

    def insert(self, body):
        from app import google_sync as gs
        if self.fail:
            raise gs.GoogleError("送信エラー（テスト）")
        gid = f"g{len(self.events) + 100}"
        ev = dict(body, id=gid, status="confirmed", etag=self._etag())
        self.events[gid] = ev
        self.calls.append(("insert", gid, body))
        return ev

    def patch(self, gid, body):
        from app import google_sync as gs
        if gid not in self.events or self.events[gid].get("status") == "cancelled":
            raise gs.NotFoundOnGoogle()
        self.events[gid].update(body)
        self.events[gid]["etag"] = self._etag()
        self.calls.append(("patch", gid, body))
        return self.events[gid]

    def delete(self, gid):
        self.calls.append(("delete", gid))
        if gid in self.events:
            self.cancel(gid)


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", tmp_path / "client_secret.json")
    monkeypatch.setattr(config, "CERT_FILE", tmp_path / "certs" / "lan.pem")
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "certs" / "lan-key.pem")
    examples._seed_file.cache_clear()
    # APIキーは資格情報マネージャーではなくメモリに置く
    from app import secret_store
    secrets = {}
    monkeypatch.setattr(secret_store, "get", lambda n: secrets.get(n))
    monkeypatch.setattr(secret_store, "set", lambda n, v: secrets.__setitem__(n, v))
    monkeypatch.setattr(secret_store, "delete", lambda n: secrets.pop(n, None))
    f = FakeLLM()
    monkeypatch.setattr(llm, "client", f)
    notify.sent.clear()
    # Googleの認証情報は資格情報マネージャーではなくメモリに置く
    from app import google_sync as gs
    tokens = {}
    monkeypatch.setattr(gs, "save_token", lambda t: tokens.__setitem__("t", t))
    monkeypatch.setattr(gs, "load_token", lambda: tokens.get("t"))
    monkeypatch.setattr(gs, "delete_token", lambda: tokens.pop("t", None))
    from app import security
    security._fails.clear()
    db.init_db()
    return f


@pytest.fixture()
def gfake(fake, monkeypatch):
    """Googleに接続済みの状態と、偽のGoogleカレンダー。"""
    from app import google_sync as gs
    g = FakeGoogle()
    gs.save_token("dummy-token")
    monkeypatch.setattr(gs, "make_client", lambda: g)
    return g


@pytest.fixture()
def client(fake):
    from app.main import app
    with TestClient(app) as c:
        yield c


def wait_done(client, pid, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        p = client.get(f"/api/proposals/{pid}").json()
        if p["status"] not in ("reading", "drafting_todos"):
            return p
        time.sleep(0.02)
    raise AssertionError("処理が終わりませんでした")


def ev(title, date, time=None, category="私用", deadline=False, **kw):
    return {"title": title, "start_date": date, "start_time": time, "end_date": kw.get("end_date"),
            "end_time": kw.get("end_time"), "location": kw.get("location"), "category": category,
            "is_deadline": deadline}
