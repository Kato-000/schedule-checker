"""予定チェッカーのバックエンド（FastAPI）。
PCのアプリ: 127.0.0.1:8765（HTTP、認証なし）
スマホ:     自宅LANから :8766（HTTPS、PINでログイン）"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fastapi.concurrency import run_in_threadpool

from . import config, db, digest, jobs, lan, llm, lookup, net, planner, rules, scheduler, secret_store, security, store, travel, voice
from . import google_sync as gs
from .dates import norm_time, parse_date, today
from .prompts import CATEGORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    rules.ensure_seeded()
    jobs.resume_unfinished()
    s = db.get_settings()
    if s.get("lan_enabled") == "1" and s.get("pin_hash"):
        lan.server.start(app)
    if config.ENABLE_SCHEDULER:
        scheduler.start()
    yield
    scheduler.shutdown()
    lan.server.stop()


app = FastAPI(title="予定チェッカー", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["*"])

PUBLIC_API = {"/api/auth/login", "/api/auth/status", "/api/health"}


@app.middleware("http")
async def access_control(request: Request, call_next):
    """PC（127.0.0.1）はそのまま。それ以外は自宅LANからのみ、かつPINでログイン済みのときだけ。"""
    host = request.client.host if request.client else None
    if security.is_local(host):
        return await call_next(request)
    if not security.is_lan(host):
        return JSONResponse({"detail": "自宅LANの外からは接続できません"}, status_code=403)
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API \
            and not security.check_session(request.cookies.get(config.SESSION_COOKIE)):
        return JSONResponse({"detail": "ログインしてください", "login": True}, status_code=401)
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def require_local(request: Request) -> None:
    """LANやGoogleの設定は、PCからだけ変えられる。"""
    if not security.is_local(request.client.host if request.client else None):
        raise HTTPException(403, "この設定はPCからだけ変更できます")


@app.exception_handler(store.NotFound)
async def _not_found(_: Request, e: store.NotFound):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(store.Invalid)
async def _invalid(_: Request, e: store.Invalid):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(rules.RuleError)
async def _rule_error(_: Request, e: rules.RuleError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(voice.VoiceError)
async def _voice_error(_: Request, e: voice.VoiceError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(net.NetError)
async def _net_error(_: Request, e: net.NetError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(gs.GoogleError)
async def _google_error(_: Request, e: gs.GoogleError):
    return JSONResponse({"detail": str(e)}, status_code=400)


def _date(s: str | None, default: dt.date | None = None) -> dt.date:
    d = parse_date(s) if s else default
    if d is None:
        raise HTTPException(400, f"日付の形式が正しくありません: {s}")
    return d


# ---------------------------------------------------------------------------
# ログイン（スマホ用）
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    pin: str


@app.get("/api/auth/status")
def auth_status(request: Request):
    host = request.client.host if request.client else None
    local = security.is_local(host)
    return {"local": local,
            "authenticated": local or security.check_session(request.cookies.get(config.SESSION_COOKIE))}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    host = request.client.host if request.client else "?"
    wait = security.locked_out(host)
    if wait:
        raise HTTPException(429, f"PINを続けて間違えたため、{(wait + 59) // 60}分ほど待ってからやり直してください")
    stored = db.get_settings().get("pin_hash")
    if not stored or not security.verify_pin(body.pin, stored):
        security.record_fail(host)
        raise HTTPException(401, "PINが違います")
    security.clear_fails(host)
    token = security.create_session(request.headers.get("user-agent"))
    response.set_cookie(config.SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400,
                        httponly=True, secure=True, samesite="strict")
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    security.delete_session(request.cookies.get(config.SESSION_COOKIE))
    response.delete_cookie(config.SESSION_COOKIE)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 入力と承認
# ---------------------------------------------------------------------------
class ProposalIn(BaseModel):
    text: str
    kind: str = "event"      # event（予定）/ todo（予定に結びつかないTodo）
    source: str = "text"     # text / voice（音声入力）


class ApproveIn(BaseModel):
    event: dict | None = None    # Todoの案では不要
    todos: list[dict] = []


class RedraftIn(BaseModel):
    event: dict


class ResolveIn(BaseModel):
    keep: str


@app.post("/api/proposals")
def create_proposal(body: ProposalIn):
    kind = {"event": "new", "todo": "todo"}.get(body.kind)
    if not kind:
        raise HTTPException(400, "案の種類が正しくありません")
    p = store.create_proposal(body.text, kind=kind, source=body.source)
    if kind == "todo":
        jobs.submit_todo_proposal(p["id"])
    else:
        jobs.submit_proposal(p["id"])
    return p


@app.get("/api/proposals")
def list_proposals():
    return store.list_proposals()


@app.get("/api/proposals/{pid}")
def get_proposal(pid: int):
    return store.get_proposal(pid)


@app.post("/api/proposals/{pid}/approve")
def approve(pid: int, body: ApproveIn):
    return store.approve_proposal(pid, body.event, body.todos)


@app.post("/api/proposals/{pid}/reject")
def reject(pid: int):
    return store.reject_proposal(pid)


@app.post("/api/proposals/{pid}/resolve")
def resolve(pid: int, body: ResolveIn):
    """PCとGoogleの両方で変わった予定の、どちらを残すか。"""
    return store.resolve_conflict(pid, body.keep)


@app.post("/api/proposals/{pid}/redraft")
def redraft(pid: int, body: RedraftIn):
    """予定を直したあとでTodoを作り直す（日付を直すとTodoの期限も変わるため）。"""
    p = store.get_proposal(pid)
    if p["status"] in ("approved", "rejected") or p["kind"] in ("conflict", "todo"):
        raise HTTPException(400, "この案はTodoを作り直せません")
    ev = store._clean_event(body.event)
    jobs.submit_redraft(pid, ev)
    return store.get_proposal(pid)


# ---------------------------------------------------------------------------
# 予定とTodo
# ---------------------------------------------------------------------------
@app.get("/api/events")
def list_events(start: str, end: str):
    return store.list_events(_date(start), _date(end))


@app.get("/api/holidays")
def get_holidays(start: str, end: str):
    """期間内の祝日 {"YYYY-MM-DD": "名前"}（カレンダーの色分け用）。"""
    s_, e_ = parse_date(start), parse_date(end)
    if not s_ or not e_ or e_ < s_ or (e_ - s_).days > 800:
        raise HTTPException(400, "期間が正しくありません")
    from .dates import holidays
    return holidays(s_, e_)


@app.get("/api/events/{eid}")
def get_event(eid: int):
    return store.get_event(eid)


@app.patch("/api/events/{eid}")
def update_event(eid: int, body: dict):
    return store.update_event(eid, body)


@app.delete("/api/events/{eid}")
def delete_event(eid: int):
    store.delete_event(eid)
    return {"ok": True}


@app.get("/api/todos")
def list_todos(start: str | None = None, end: str | None = None, status: str | None = None):
    return store.list_todos(parse_date(start) if start else None, parse_date(end) if end else None, status)


@app.get("/api/todos/{tid}")
def get_todo(tid: int):
    return store.get_todo(tid)


@app.post("/api/todos")
def create_todo(body: dict):
    return store.create_todo(body)


class QuickTodoIn(BaseModel):
    text: str


@app.post("/api/todos/quick")
def quick_todo(body: QuickTodoIn):
    """予定に結びつかないTodoを、入力文から1件登録する（承認なし。登録後に画面で直せる）。
    LLMが使えないときは、文をそのままタイトルにして期限なしで登録する。"""
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Todoの内容を入力してください")
    if len(text) > 500:
        raise HTTPException(400, "長すぎます（500文字まで）")
    try:
        r = jobs.submit(planner.read_todo, text).result(timeout=config.OLLAMA_TIMEOUT + 30)
        fields, warnings, llm_error = r["todo"], r["warnings"], None
    except Exception as e:  # noqa: BLE001 - LLMが使えなくても登録はする
        log.warning("Todoの読み取りに失敗: %s", e)
        fields = {"title": text[:200], "due_date": None, "due_time": None, "priority": "medium"}
        warnings, llm_error = [], str(e)
    return {"todo": store.create_todo(fields), "warnings": warnings, "llm_error": llm_error, "input": text}


@app.patch("/api/todos/{tid}")
def update_todo(tid: int, body: dict):
    return store.update_todo(tid, body)


@app.delete("/api/todos/{tid}")
def delete_todo(tid: int):
    store.delete_todo(tid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 今日・朝のまとめ
# ---------------------------------------------------------------------------
@app.get("/api/today")
def get_today(date: str | None = None):
    return store.today_view(_date(date, today()))


@app.get("/api/digest")
def get_digest(date: str | None = None):
    d = _date(date, today())
    return digest.get(d) or {"date": d.isoformat(), "missing": True}


@app.post("/api/digest/run")
def run_digest():
    """朝のまとめを今すぐ作り直す（LLMの処理と順番に並ぶ）。"""
    return jobs.submit(digest.generate).result(timeout=config.OLLAMA_TIMEOUT + 30)


@app.get("/api/meta")
def meta(request: Request):
    local = security.is_local(request.client.host if request.client else None)
    return {"categories": list(CATEGORIES), "today": today().isoformat(),
            "llm": llm.client.status(), "pending_count": store.pending_count(),
            "local": local, "google_mode": gs.mode(),
            "default_local_only": db.get_settings().get("google_default_local_only") == "1",
            "net_enabled": net.enabled(), "idle_seconds": config.idle_seconds()}


# ---------------------------------------------------------------------------
# 自分ルール
# ---------------------------------------------------------------------------
class RuleIn(BaseModel):
    text: str
    category: str | None = None


@app.get("/api/rules")
def list_rules():
    return {"rules": rules.list_rules(), "unchecked_edits": rules.unchecked_edits(),
            "extract_every": config.RULES_EXTRACT_EVERY}


@app.post("/api/rules")
def add_rule(body: RuleIn):
    return rules.add_rule(body.text, body.category)


@app.patch("/api/rules/{rid}")
def update_rule(rid: int, body: dict):
    return rules.update_rule(rid, body)


@app.delete("/api/rules/{rid}")
def delete_rule(rid: int):
    rules.delete_rule(rid)
    return {"ok": True}


@app.post("/api/rules/extract")
def extract_rules():
    """修正履歴から、今すぐルール案を作る。"""
    added = jobs.submit(rules.extract).result(timeout=config.OLLAMA_TIMEOUT + 30)
    return {"added": added}


# ---------------------------------------------------------------------------
# 設定（PCから）
# ---------------------------------------------------------------------------
SECRET_SETTINGS = {"pin_hash"}


@app.get("/api/settings")
def get_settings():
    return {k: v for k, v in db.get_settings().items() if k not in SECRET_SETTINGS}


@app.put("/api/settings")
def put_settings(body: dict):
    if "digest_time" in body:
        t = norm_time(body["digest_time"])
        if not t:
            raise HTTPException(400, "時刻は HH:MM で入力してください")
        db.set_setting("digest_time", t)
        scheduler.reschedule()
    if "idle_seconds" in body:
        try:
            v = int(body["idle_seconds"])
        except (TypeError, ValueError):
            raise HTTPException(400, "秒数は数字で入力してください")
        if not config.IDLE_MIN_SECONDS <= v <= config.IDLE_MAX_SECONDS:
            raise HTTPException(400, f"{config.IDLE_MIN_SECONDS}〜{config.IDLE_MAX_SECONDS}秒で入力してください")
        db.set_setting("idle_seconds", str(v))
    for key in ("digest_notify", "use_seed_examples", "rules_auto", "widget_autohide"):
        if key in body:
            db.set_setting(key, "1" if str(body[key]) in ("1", "true", "True") else "0")
    return get_settings()


class LanIn(BaseModel):
    enabled: bool | None = None
    pin: str | None = None


@app.get("/api/lan")
def lan_status(request: Request):
    require_local(request)
    return lan.server.status()


@app.put("/api/lan")
def lan_update(body: LanIn, request: Request):
    require_local(request)
    if body.pin is not None:
        err = security.validate_pin(body.pin)
        if err:
            raise HTTPException(400, err)
        db.set_setting("pin_hash", security.hash_pin(body.pin))
        security.delete_all_sessions()   # PINを変えたらスマホは全部ログアウト
    if body.enabled is not None:
        if body.enabled and not db.get_settings().get("pin_hash"):
            raise HTTPException(400, "先にPINを設定してください")
        db.set_setting("lan_enabled", "1" if body.enabled else "0")
        if body.enabled:
            lan.server.start(app)
        else:
            lan.server.stop()
            security.delete_all_sessions()
    return lan.server.status()


class GoogleIn(BaseModel):
    mode: str | None = None
    default_local_only: bool | None = None
    sync_interval: str | None = None    # 15m / 1h / 6h / daily / manual


class SecretIn(BaseModel):
    content: str


@app.get("/api/google")
def google_status(request: Request):
    require_local(request)
    return gs.status()


@app.put("/api/google")
def google_update(body: GoogleIn, request: Request):
    require_local(request)
    if body.default_local_only is not None:
        db.set_setting("google_default_local_only", "1" if body.default_local_only else "0")
    if body.sync_interval is not None:
        if body.sync_interval not in config.GOOGLE_SYNC_INTERVALS:
            raise HTTPException(400, "同期の間隔が正しくありません")
        db.set_setting("google_sync_interval", body.sync_interval)
        scheduler.reschedule_google()
    if body.mode is not None:
        gs.set_mode(body.mode)
        if body.mode != "off":
            gs.submit_sync()
    return gs.status()


@app.post("/api/google/client_secret")
def google_secret(body: SecretIn, request: Request):
    require_local(request)
    gs.save_client_secret(body.content)
    return gs.status()


@app.post("/api/google/connect")
def google_connect(request: Request):
    require_local(request)
    gs.start_connect()
    return gs.status()


@app.post("/api/google/disconnect")
def google_disconnect(request: Request):
    require_local(request)
    gs.disconnect()
    return gs.status()


@app.post("/api/google/sync")
def google_sync_now(request: Request):
    require_local(request)
    result = gs.submit_sync().result(timeout=180)
    return {"result": result, "status": gs.status()}


# ---------------------------------------------------------------------------
# 音声入力（PCの中で文字起こし）
# ---------------------------------------------------------------------------
@app.post("/api/llm/warm")
def llm_warm():
    """入力を始めたときに、LLMのモデルを先に読み込んでおく（裏で実行してすぐ返す）。"""
    warm = getattr(llm.client, "warm", None)
    if warm:
        threading.Thread(target=lambda: _safe(warm), daemon=True).start()
    return {"ok": True}


@app.post("/api/voice/warm")
def voice_warm():
    """録音を始めたときに、文字起こしのモデルを話している間に読み込んでおく。"""
    threading.Thread(target=lambda: _safe(voice.engine.warm), daemon=True).start()
    return {"ok": True}


def _safe(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        log.warning("先読みに失敗: %s", e)


@app.get("/api/voice")
def voice_status():
    return voice.status()


@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """録音（webm/ogg/mp4 など）をそのまま本文で受け取り、文字にして返す。録音は保存しない。"""
    size = int(request.headers.get("content-length") or 0)
    if size > config.VOICE_MAX_BYTES:
        raise HTTPException(413, "録音が長すぎます（1分まで）")
    data = await request.body()
    return await run_in_threadpool(voice.engine.transcribe, data)


class VoiceIn(BaseModel):
    model: str | None = None


@app.put("/api/voice")
def voice_update(body: VoiceIn, request: Request):
    require_local(request)
    if body.model is not None:
        if body.model not in config.VOICE_MODELS:
            raise HTTPException(400, "そのモデルは選べません")
        db.set_setting("voice_model", body.model)
        voice.engine.unload()
    return voice.status()


@app.post("/api/voice/download")
def voice_download(body: VoiceIn, request: Request):
    require_local(request)
    voice.start_download(body.model or voice.model_name())
    return voice.status()


@app.delete("/api/voice/models/{name}")
def voice_delete_model(name: str, request: Request):
    require_local(request)
    voice.delete_model(name)
    return voice.status()


# ---------------------------------------------------------------------------
# ネット連携（調べもの・経路）。ボタンを押したときだけ通信する
# ---------------------------------------------------------------------------
def _net_status(request: Request) -> dict:
    s = db.get_settings()
    local = security.is_local(request.client.host if request.client else None)
    out = {"enabled": s.get("net_enabled") == "1",
           "travel_mode": s.get("travel_mode") or "transit",
           "arrive_margin_min": int(s.get("arrive_margin_min") or 10),
           "leave_notify_min": int(s.get("leave_notify_min") or 0),
           "home_set": bool(travel.home()),
           "home_address_set": bool((s.get("home_address") or "").strip()),
           "map_ready": s.get("net_enabled") == "1" and bool(secret_store.get(net.MAPS_KEY))}
    if local:   # 住所・キーの有無・送信記録はPCの画面にだけ出す
        out.update({"home_address": s.get("home_address") or "", "home_label": s.get("home_label") or "",
                    "ollama_key_set": bool(secret_store.get(net.OLLAMA_KEY)),
                    "rapidapi_key_set": bool(secret_store.get(net.RAPIDAPI_KEY)),
                    "maps_key_set": bool(secret_store.get(net.MAPS_KEY)),
                    "log": net.recent_log()})
    return out


@app.get("/api/net")
def net_status(request: Request):
    return _net_status(request)


class NetIn(BaseModel):
    enabled: bool | None = None
    ollama_key: str | None = None        # 空文字で削除
    rapidapi_key: str | None = None      # 空文字で削除
    maps_key: str | None = None          # 空文字で削除（Google Maps Embed API）
    home_address: str | None = None      # 住所検索で位置を確かめてから保存（空文字で削除）
    travel_mode: str | None = None
    arrive_margin_min: int | None = None
    leave_notify_min: int | None = None


@app.put("/api/net")
def net_update(body: NetIn, request: Request):
    require_local(request)
    if body.enabled is not None:
        db.set_setting("net_enabled", "1" if body.enabled else "0")
    for value, name in ((body.ollama_key, net.OLLAMA_KEY), (body.rapidapi_key, net.RAPIDAPI_KEY),
                        (body.maps_key, net.MAPS_KEY)):
        if value is None:
            continue
        value = value.strip()
        if value:
            if len(value) > 300 or any(ch.isspace() for ch in value):
                raise HTTPException(400, "キーの形式が正しくありません")
            secret_store.set(name, value)
        else:
            secret_store.delete(name)
    if body.travel_mode is not None:
        if body.travel_mode not in travel.MODE_LABEL:
            raise HTTPException(400, "移動手段が正しくありません")
        db.set_setting("travel_mode", body.travel_mode)
    if body.arrive_margin_min is not None:
        if not 0 <= body.arrive_margin_min <= 120:
            raise HTTPException(400, "何分前に着きたいかは0〜120分で入れてください")
        db.set_setting("arrive_margin_min", str(body.arrive_margin_min))
    if body.leave_notify_min is not None:
        if not 0 <= body.leave_notify_min <= 120:
            raise HTTPException(400, "通知は0〜120分前で入れてください")
        db.set_setting("leave_notify_min", str(body.leave_notify_min))
    if body.home_address is not None:
        travel.set_home(body.home_address)
    return _net_status(request)


class LookupIn(BaseModel):
    event: dict
    queries: list[str] | None = None


@app.post("/api/net/queries")
def net_queries(body: LookupIn):
    """「ネットで調べる」で送る検索語（通信はしない）。画面で先に見せるため。"""
    return {"queries": lookup.build_queries(body.event), "enabled": net.enabled()}


@app.post("/api/net/lookup")
def net_lookup(body: LookupIn):
    """Web検索して、足りない情報の候補を返す（反映はしない）。結果を読むのはPCのLLM。"""
    net.require("search")
    return jobs.submit(lookup.run, body.event, body.queries).result(timeout=config.OLLAMA_TIMEOUT + 90)


class MapIn(BaseModel):
    kind: str                      # place / search / directions
    q: str | None = None
    destination: str | None = None
    mode: str | None = None        # transit / car / walk


@app.post("/api/net/map")
def net_map(body: MapIn):
    """画面に埋め込む Google Maps の地図のURL（外部ブラウザは開かない）。"""
    return net.map_url(body.kind, body.q, body.destination, body.mode)


class RouteIn(BaseModel):
    mode: str | None = None


@app.post("/api/events/{eid}/route")
def event_route(eid: int, body: RouteIn):
    """家を出る時刻を調べる（経路検索）。"""
    return travel.plan(eid, body.mode)


@app.delete("/api/events/{eid}/route")
def event_route_clear(eid: int):
    return travel.clear(eid)


class OpenUrlIn(BaseModel):
    url: str


@app.post("/api/open_url")
def open_url(body: OpenUrlIn, request: Request):
    """PCのアプリから、Googleマップや根拠のページをいつものブラウザで開く（アプリの画面の中では開けないため）。
    PCからだけ。http/https のURLだけ。"""
    require_local(request)
    from urllib.parse import urlparse
    u = urlparse(body.url.strip())
    if u.scheme not in ("http", "https") or not u.netloc or len(body.url) > 2000:
        raise HTTPException(400, "開けないURLです")
    import webbrowser
    if not webbrowser.open_new_tab(body.url.strip()):
        raise HTTPException(500, "ブラウザを開けませんでした")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------------------
# ビルド済みの画面（PCのブラウザ・スマホから開くとき用）
# ---------------------------------------------------------------------------
_dist = config.BASE_DIR.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_dist / "index.html")
