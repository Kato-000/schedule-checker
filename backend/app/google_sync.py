"""Googleカレンダー連携。

モード
  off      : 何もしない（初期値。完全ローカル）
  import   : Google → ローカルの取り込みだけ。新しい予定にはTodo案を作って承認待ちへ
  two_way  : 取り込み＋ローカルの予定をGoogleへ送る（「ローカル限定」の予定は送らない）

Todo・修正履歴・LLMの処理内容はGoogleに送らない。
Googleとの通信は GoogleClient にまとめてあり、テストでは偽物に差し替える。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from . import config, db
from .dates import norm_time, parse_date, today

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gsync")


class SyncTokenExpired(Exception):
    pass


class NotFoundOnGoogle(Exception):
    pass


class GoogleError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 認証情報の保存（Windowsの資格情報マネージャー。使えなければファイル）
# ---------------------------------------------------------------------------
def _token_file():
    return config.DATA_DIR / "google_token.json"


def save_token(token_json: str) -> None:
    try:
        import keyring
        keyring.set_password(config.KEYRING_SERVICE, "token", token_json)
        _token_file().unlink(missing_ok=True)
        return
    except Exception as e:  # noqa: BLE001
        log.warning("資格情報マネージャーに保存できないため、ファイルに保存します: %s", e)
    _token_file().write_text(token_json, encoding="utf-8")


def load_token() -> str | None:
    try:
        import keyring
        t = keyring.get_password(config.KEYRING_SERVICE, "token")
        if t:
            return t
    except Exception:  # noqa: BLE001
        pass
    f = _token_file()
    return f.read_text(encoding="utf-8") if f.exists() else None


def delete_token() -> None:
    try:
        import keyring
        keyring.delete_password(config.KEYRING_SERVICE, "token")
    except Exception:  # noqa: BLE001
        pass
    _token_file().unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Google API（本物）
# ---------------------------------------------------------------------------
class GoogleClient:
    def __init__(self, creds) -> None:
        from googleapiclient.discovery import build
        self._svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._cal = config.GOOGLE_CALENDAR_ID

    @staticmethod
    def _status(e) -> int:
        return getattr(e, "status_code", None) or getattr(getattr(e, "resp", None), "status", 0)

    def list_events(self, sync_token: str | None, time_min: str | None) -> tuple[list[dict], str | None]:
        from googleapiclient.errors import HttpError
        items, page = [], None
        while True:
            kw = {"calendarId": self._cal, "singleEvents": True, "showDeleted": True,
                  "maxResults": 250, "pageToken": page}
            if sync_token:
                kw["syncToken"] = sync_token
            else:
                kw["timeMin"] = time_min
            try:
                res = self._svc.events().list(**kw).execute()
            except HttpError as e:
                if self._status(e) == 410:
                    raise SyncTokenExpired() from e
                raise GoogleError(f"Googleから予定を取得できませんでした（{self._status(e)}）") from e
            items += res.get("items", [])
            page = res.get("nextPageToken")
            if not page:
                return items, res.get("nextSyncToken")

    def insert(self, body: dict) -> dict:
        from googleapiclient.errors import HttpError
        try:
            return self._svc.events().insert(calendarId=self._cal, body=body).execute()
        except HttpError as e:
            raise GoogleError(f"Googleに予定を登録できませんでした（{self._status(e)}）") from e

    def patch(self, event_id: str, body: dict) -> dict:
        from googleapiclient.errors import HttpError
        try:
            return self._svc.events().patch(calendarId=self._cal, eventId=event_id, body=body).execute()
        except HttpError as e:
            if self._status(e) in (404, 410):
                raise NotFoundOnGoogle() from e
            raise GoogleError(f"Googleの予定を更新できませんでした（{self._status(e)}）") from e

    def delete(self, event_id: str) -> None:
        from googleapiclient.errors import HttpError
        try:
            self._svc.events().delete(calendarId=self._cal, eventId=event_id).execute()
        except HttpError as e:
            if self._status(e) in (404, 410):
                return
            raise GoogleError(f"Googleの予定を削除できませんでした（{self._status(e)}）") from e


def _load_creds():
    raw = load_token()
    if not raw:
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(raw), config.GOOGLE_SCOPES)
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001
            raise GoogleError("Googleの認証の更新に失敗しました。設定画面から接続し直してください。") from e
        save_token(creds.to_json())
    return creds


# テストではこれを差し替える（引数なしで GoogleClient 互換のものを返す）
def make_client():
    creds = _load_creds()
    if not creds:
        raise GoogleError("Googleに接続されていません")
    return GoogleClient(creds)


# ---------------------------------------------------------------------------
# 接続（ブラウザでGoogleにログインして許可する）
# ---------------------------------------------------------------------------
_connect = {"state": "idle", "error": None}
_connect_lock = threading.Lock()


def start_connect() -> dict:
    if not config.GOOGLE_CLIENT_SECRET.exists():
        raise GoogleError("認証用のファイル（client_secret）がありません。設定画面から読み込んでください。")
    with _connect_lock:
        if _connect["state"] == "waiting":
            return dict(_connect)
        _connect.update(state="waiting", error=None)

    def run():
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(config.GOOGLE_CLIENT_SECRET), config.GOOGLE_SCOPES)
            creds = flow.run_local_server(
                port=0, open_browser=True, timeout_seconds=300,
                success_message="予定チェッカーとGoogleカレンダーの接続が完了しました。このページは閉じてかまいません。")
            save_token(creds.to_json())
            _connect.update(state="done", error=None)
            log.info("Googleカレンダーに接続しました")
        except Exception as e:  # noqa: BLE001
            _connect.update(state="error", error=f"接続できませんでした: {e}")
            log.warning("Google接続に失敗: %s", e)

    threading.Thread(target=run, name="google-connect", daemon=True).start()
    return dict(_connect)


def disconnect() -> None:
    delete_token()
    _set_state("sync_token", None)
    db.set_setting("google_mode", "off")


def save_client_secret(content: str) -> None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise GoogleError("JSONとして読めません。Google Cloud からダウンロードしたファイルを選んでください。") from e
    if "installed" not in data:
        raise GoogleError("「デスクトップアプリ」用のOAuthクライアントのファイルではありません。")
    config.GOOGLE_CLIENT_SECRET.parent.mkdir(parents=True, exist_ok=True)
    config.GOOGLE_CLIENT_SECRET.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 予定の変換
# ---------------------------------------------------------------------------
def _local_dt(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.astimezone() if d.tzinfo else d   # PCのタイムゾーンに直す


def from_google(g: dict) -> dict:
    """Googleの予定 → ローカルの予定の項目。"""
    s, e = g.get("start", {}), g.get("end", {})
    ev = {"title": (g.get("summary") or "（無題）").strip(), "location": g.get("location") or None,
          "start_time": None, "end_date": None, "end_time": None}
    if "date" in s:   # 終日（Googleの終了日は翌日＝含まない）
        ev["start_date"] = s["date"]
        last = parse_date(e.get("date")) - dt.timedelta(days=1) if e.get("date") else None
        if last and last.isoformat() > s["date"]:
            ev["end_date"] = last.isoformat()
    else:
        sd = _local_dt(s["dateTime"])
        ev["start_date"], ev["start_time"] = sd.date().isoformat(), sd.strftime("%H:%M")
        if e.get("dateTime"):
            ed = _local_dt(e["dateTime"])
            if ed > sd:
                ev["end_date"], ev["end_time"] = ed.date().isoformat(), ed.strftime("%H:%M")
    return ev


def _aware(date: str, time: str) -> str:
    return dt.datetime.fromisoformat(f"{date}T{time}:00").astimezone().isoformat()


def to_google(ev: dict) -> dict:
    """ローカルの予定 → Googleの予定（Todoやメモは送らない）。"""
    body = {"summary": ev["title"], "location": ev.get("location") or None}
    start = norm_time(ev.get("start_time"))
    if start:
        end_date = ev.get("end_date") or ev["start_date"]
        end_time = norm_time(ev.get("end_time"))
        if not end_time:   # 終了が未定なら1時間（締切は30分）
            dur = 30 if ev.get("is_deadline") else 60
            end_dt = dt.datetime.fromisoformat(f"{ev['start_date']}T{start}") + dt.timedelta(minutes=dur)
            end_date, end_time = end_dt.date().isoformat(), end_dt.strftime("%H:%M")
        body["start"] = {"dateTime": _aware(ev["start_date"], start)}
        body["end"] = {"dateTime": _aware(end_date, end_time)}
    else:
        last = parse_date(ev.get("end_date") or ev["start_date"])
        body["start"] = {"date": ev["start_date"]}
        body["end"] = {"date": (last + dt.timedelta(days=1)).isoformat()}
    return body


SYNC_FIELDS = ("title", "start_date", "start_time", "end_date", "end_time", "location")


def _same(local: dict, g_ev: dict) -> bool:
    return all((local.get(k) or None) == (g_ev.get(k) or None) for k in SYNC_FIELDS)


# ---------------------------------------------------------------------------
# 同期の状態
# ---------------------------------------------------------------------------
def _get_state(key: str):
    with db.connect() as c:
        r = c.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return db.loads(r["value"]) if r else None


def _set_state(key: str, value) -> None:
    with db.connect() as c:
        c.execute("INSERT INTO sync_state(key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, db.dumps(value)))


def queue_google_delete(google_event_id: str) -> None:
    pend = _get_state("pending_deletes") or []
    if google_event_id not in pend:
        pend.append(google_event_id)
    _set_state("pending_deletes", pend)


def mode() -> str:
    return db.get_settings().get("google_mode", "off")


def status() -> dict:
    with db.connect() as c:
        pending = c.execute("SELECT COUNT(*) FROM events WHERE needs_push = 1 AND local_only = 0").fetchone()[0]
        errors = c.execute("SELECT COUNT(*) FROM events WHERE push_error IS NOT NULL").fetchone()[0]
    return {"mode": mode(), "connected": bool(load_token()),
            "client_secret": config.GOOGLE_CLIENT_SECRET.exists(),
            "connect": dict(_connect), "last_sync": _get_state("last_sync"),
            "last_error": _get_state("last_error"), "pending_push": pending, "push_errors": errors,
            "default_local_only": db.get_settings().get("google_default_local_only") == "1",
            "sync_interval": sync_interval()}


def sync_interval() -> str:
    v = db.get_settings().get("google_sync_interval") or "15m"
    return v if v in config.GOOGLE_SYNC_INTERVALS else "15m"


def last_sync_time() -> dt.datetime | None:
    v = _get_state("last_sync")
    try:
        return dt.datetime.strptime(v, "%Y-%m-%d %H:%M:%S") if v else None
    except (TypeError, ValueError):
        return None


def set_mode(new_mode: str) -> None:
    if new_mode not in ("off", "import", "two_way"):
        raise GoogleError("モードが正しくありません")
    if new_mode != "off" and not load_token():
        raise GoogleError("先にGoogleに接続してください")
    old = mode()
    db.set_setting("google_mode", new_mode)
    if new_mode == "two_way" and old != "two_way":
        # 双方向にした時点で、これからの予定（ローカル限定以外）を送る対象にする
        since = (today() - dt.timedelta(days=7)).isoformat()
        with db.connect() as c:
            c.execute("UPDATE events SET needs_push = 1 WHERE source = 'local' AND local_only = 0 "
                      "AND google_event_id IS NULL AND COALESCE(end_date, start_date) >= ?", (since,))


# ---------------------------------------------------------------------------
# 同期の本体
# ---------------------------------------------------------------------------
def _events_by_gid(gids: list[str]) -> dict[str, dict]:
    if not gids:
        return {}
    out = {}
    with db.connect() as c:
        for i in range(0, len(gids), 500):
            chunk = gids[i:i + 500]
            q = ",".join("?" * len(chunk))
            for r in c.execute(f"SELECT * FROM events WHERE google_event_id IN ({q})", chunk):
                out[r["google_event_id"]] = dict(r)
    return out


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pull(client) -> dict:
    """Google → ローカル。"""
    from . import store
    stats = {"added": 0, "updated": 0, "deleted": 0, "conflicts": 0, "proposals": 0}
    token = _get_state("sync_token")
    time_min = None
    if not token:
        time_min = dt.datetime.combine(today() - dt.timedelta(days=config.GOOGLE_FIRST_SYNC_DAYS_BACK),
                                       dt.time()).astimezone().isoformat()
    try:
        items, next_token = client.list_events(token, time_min)
    except SyncTokenExpired:
        log.info("同期トークンが無効になったため、取り込み直します")
        _set_state("sync_token", None)
        return pull(client)

    first_sync = token is None
    locals_ = _events_by_gid([g["id"] for g in items if g.get("id")])
    horizon = (today() + dt.timedelta(days=config.GOOGLE_TODO_PROPOSAL_DAYS)).isoformat()

    for g in items:
        gid = g.get("id")
        local = locals_.get(gid)
        if g.get("status") == "cancelled":
            if not local:
                continue
            if local["needs_push"] or store.has_open_todos(local["id"]):
                store.create_conflict(local, None, gid)   # 消してよいか確認する
                stats["conflicts"] += 1
            else:
                store.delete_event(local["id"], from_google=True)
                stats["deleted"] += 1
            continue
        if "start" not in g:
            continue
        g_ev = from_google(g)
        if not local:
            eid = store.insert_google_event(g_ev, gid, g.get("etag"))
            stats["added"] += 1
            if today().isoformat() <= g_ev["start_date"] <= horizon:
                store.create_import_proposal(eid)
                stats["proposals"] += 1
            continue
        if g.get("etag") and g.get("etag") == local.get("google_etag"):
            continue
        if _same(local, g_ev):
            store.mark_synced(local["id"], g.get("etag"), clear_push=False)
        elif local["needs_push"]:
            store.create_conflict(local, g_ev, gid, g.get("etag"))
            stats["conflicts"] += 1
        else:
            store.apply_google_update(local["id"], g_ev, g.get("etag"))
            stats["updated"] += 1
    _set_state("sync_token", next_token)
    if first_sync:
        log.info("Googleから初回の取り込み: %s", stats)
    return stats


def push(client) -> dict:
    """ローカル → Google（双方向のときだけ）。"""
    from . import store
    stats = {"inserted": 0, "patched": 0, "deleted": 0, "errors": 0}
    pend = _get_state("pending_deletes") or []
    left = []
    for gid in pend:
        try:
            client.delete(gid)
            stats["deleted"] += 1
        except GoogleError:
            left.append(gid)
            stats["errors"] += 1
    _set_state("pending_deletes", left)

    with db.connect() as c:
        # 「どちらを残すか」の確認待ちの予定は、選ばれるまで送らない（Google側の変更を消さないため）
        rows = db.rows(c.execute(
            "SELECT * FROM events WHERE needs_push = 1 AND local_only = 0 AND id NOT IN "
            "(SELECT event_id FROM proposals WHERE kind = 'conflict' AND status = 'pending' "
            "AND event_id IS NOT NULL)"))
    for ev in rows:
        body = to_google(ev)
        try:
            if ev["google_event_id"]:
                try:
                    g = client.patch(ev["google_event_id"], body)
                    stats["patched"] += 1
                except NotFoundOnGoogle:   # Google側で消えていたら作り直す
                    g = client.insert(body)
                    stats["inserted"] += 1
            else:
                g = client.insert(body)
                stats["inserted"] += 1
            store.mark_pushed(ev["id"], g.get("id"), g.get("etag"))
        except GoogleError as e:
            store.mark_push_error(ev["id"], str(e))
            stats["errors"] += 1
    return stats


def sync_once() -> dict:
    m = mode()
    if m == "off":
        return {"skipped": "off"}
    try:
        client = make_client()
        result = {"pull": pull(client)}
        if m == "two_way":
            result["push"] = push(client)
        _set_state("last_sync", _now())
        _set_state("last_error", None)
        return result
    except GoogleError as e:
        _set_state("last_error", str(e))
        log.warning("Google同期に失敗: %s", e)
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - 想定外も記録して止めない
        _set_state("last_error", f"{type(e).__name__}: {e}")
        log.exception("Google同期で想定外のエラー")
        return {"error": str(e)}


def submit_sync() -> Future:
    return _executor.submit(sync_once)
