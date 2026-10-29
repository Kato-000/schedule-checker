"""ネット連携（調べもの・経路）の通信。

- 初期値はOFF。設定でONにし、画面のボタンを押したときだけ通信する
- 送るのは「検索語」「住所」「出発地・目的地の位置と到着時刻」だけ。予定の一覧やTodoは送らない
- 送った内容は net_log に残し、設定画面で確認できる
- 通信は SearchClient / NaviClient にまとめてあり、テストでは偽物に差し替える
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from . import config, db, secret_store

log = logging.getLogger(__name__)

OLLAMA_KEY = "ollama_api_key"
RAPIDAPI_KEY = "rapidapi_key"
MAPS_KEY = "google_maps_embed_key"
MAPS_EMBED_URL = "https://www.google.com/maps/embed/v1/"


class NetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 設定と記録
# ---------------------------------------------------------------------------
def enabled() -> bool:
    return db.get_settings().get("net_enabled") == "1"


def require(feature: str) -> None:
    """feature: search / route"""
    if not enabled():
        raise NetError("ネット連携がオフです。PCの「設定 > ネット連携」でオンにしてください")
    if feature == "search" and not secret_store.get(OLLAMA_KEY):
        raise NetError("Web検索のキー（Ollama）が設定されていません。PCの「設定 > ネット連携」で設定してください")
    if feature == "route" and not secret_store.get(RAPIDAPI_KEY):
        raise NetError("経路検索のキー（RapidAPI）が設定されていません。PCの「設定 > ネット連携」で設定してください")
    if feature == "map" and not secret_store.get(MAPS_KEY):
        raise NetError("地図のキー（Google Maps）が設定されていません。PCの「設定 > ネット連携」で設定してください")


def record(service: str, sent: str, ok: bool = True) -> None:
    with db.connect() as c:
        c.execute("INSERT INTO net_log(service, sent, ok) VALUES (?,?,?)", (service, sent[:500], int(ok)))
        # 古い記録は300件を超えた分だけ消す
        c.execute("DELETE FROM net_log WHERE id NOT IN (SELECT id FROM net_log ORDER BY id DESC LIMIT 300)")


def recent_log(limit: int = 30) -> list[dict]:
    with db.connect() as c:
        return db.rows(c.execute("SELECT * FROM net_log ORDER BY id DESC LIMIT ?", (limit,)))


def _http(req: urllib.request.Request, service: str) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=config.NET_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        log.warning("%s: HTTP %s %s", service, e.code, body)
        if e.code in (401, 403):
            raise NetError(f"{SERVICE_NAMES.get(service, service)}のキーが正しくないか、"
                           "そのAPIの利用登録（無料プランの申し込み）がされていません") from e
        if e.code == 429:
            raise NetError(f"{SERVICE_NAMES.get(service, service)}の利用回数の上限に達しました。時間をおいてお試しください") from e
        if e.code == 400:
            raise NetError(f"{SERVICE_NAMES.get(service, service)}が条件を受け付けませんでした（{body[:80]}）") from e
        raise NetError(f"{SERVICE_NAMES.get(service, service)}でエラーが起きました（{e.code}）") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetError(f"{SERVICE_NAMES.get(service, service)}に接続できませんでした。インターネットの接続を確認してください") from e
    except json.JSONDecodeError as e:
        raise NetError(f"{SERVICE_NAMES.get(service, service)}から読めない応答が返りました") from e


SERVICE_NAMES = {
    "ollama_search": "Web検索（Ollama）",
    "navitime_address": "住所検索（NAVITIME）",
    "navitime_transit": "経路検索（NAVITIME・電車）",
    "navitime_car": "経路検索（NAVITIME・車）",
    "google_maps": "地図（Google Maps）",
}


# ---------------------------------------------------------------------------
# Web検索（Ollama）
# ---------------------------------------------------------------------------
class SearchClient:
    def search(self, query: str, max_results: int) -> list[dict]:
        key = secret_store.get(OLLAMA_KEY)
        body = json.dumps({"query": query, "max_results": max_results}).encode("utf-8")
        req = urllib.request.Request(config.OLLAMA_SEARCH_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        data = _http(req, "ollama_search")
        out = []
        for r in data.get("results") or []:
            out.append({"title": str(r.get("title") or ""), "url": str(r.get("url") or ""),
                        "content": str(r.get("content") or "")})
        return out


# ---------------------------------------------------------------------------
# 住所検索と経路（NAVITIME / RapidAPI）
# ---------------------------------------------------------------------------
class NaviClient:
    def _get(self, kind: str, params: dict, service: str) -> dict:
        host = config.NAVITIME_HOSTS[kind]
        url = f"https://{host}{config.NAVITIME_PATHS[kind]}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "X-RapidAPI-Key": secret_store.get(RAPIDAPI_KEY) or "", "X-RapidAPI-Host": host})
        return _http(req, service)

    def address(self, word: str) -> dict | None:
        """住所 → {"name", "lat", "lon"}。見つからなければ None。"""
        data = self._get("address", {"word": word, "limit": 3, "datum": "wgs84", "coord_unit": "degree"},
                         "navitime_address")
        for it in data.get("items") or []:
            c = it.get("coord") or {}
            if c.get("lat") is not None and c.get("lon") is not None:
                return {"name": it.get("name") or word, "lat": float(c["lat"]), "lon": float(c["lon"])}
        return None

    def route(self, mode: str, start: tuple[float, float], goal: tuple[float, float], goal_time: dt.datetime) -> dict:
        """到着時刻を指定して経路を調べ、NAVITIMEの応答をそのまま返す。"""
        params = {"start": f"{start[0]:.6f},{start[1]:.6f}", "goal": f"{goal[0]:.6f},{goal[1]:.6f}",
                  "goal_time": goal_time.strftime("%Y-%m-%dT%H:%M:%S"), "datum": "wgs84", "coord_unit": "degree"}
        if mode == "transit":
            params["limit"] = 3
            return self._get("transit", params, "navitime_transit")
        return self._get("car", params, "navitime_car")


search_client = SearchClient()
navi_client = NaviClient()


def search(query: str, max_results: int) -> list[dict]:
    require("search")
    try:
        res = search_client.search(query, max_results)
    except NetError:
        record("ollama_search", f"検索語: {query}", ok=False)
        raise
    record("ollama_search", f"検索語: {query}")
    return res


def geocode(word: str, purpose: str) -> dict | None:
    require("route")
    try:
        r = navi_client.address(word)
    except NetError:
        record("navitime_address", f"住所（{purpose}）: {word}", ok=False)
        raise
    record("navitime_address", f"住所（{purpose}）: {word}")
    return r


def route(mode: str, start: tuple[float, float], goal: tuple[float, float], goal_time: dt.datetime,
          goal_label: str) -> dict:
    require("route")
    service = "navitime_transit" if mode == "transit" else "navitime_car"
    sent = (f"出発: 自宅（{start[0]:.4f},{start[1]:.4f}） / 目的地: {goal_label}（{goal[0]:.4f},{goal[1]:.4f}） / "
            f"到着: {goal_time:%Y-%m-%d %H:%M}")
    try:
        r = navi_client.route(mode, start, goal, goal_time)
    except NetError:
        record(service, sent, ok=False)
        raise
    record(service, sent)
    return r


# ---------------------------------------------------------------------------
# 地図（Google Maps Embed API）。画面の中に地図を埋め込むためのURLを作る
# 地図を開いたときに、画面（WebView）から Google に検索語・住所が送られる
# ---------------------------------------------------------------------------
MAP_MODES = {"transit": "transit", "car": "driving", "walk": "walking"}


def map_url(kind: str, q: str | None = None, destination: str | None = None, mode: str | None = None) -> dict:
    """kind: place（場所を表示）/ search（検索結果）/ directions（自宅からの経路）"""
    require("map")
    params = {"key": secret_store.get(MAPS_KEY), "language": "ja", "region": "JP"}
    if kind in ("place", "search"):
        q = " ".join((q or "").split())[:120]
        if not q:
            raise NetError("地図で探す言葉を入れてください")
        params["q"] = q
        sent = f"{'検索' if kind == 'search' else '場所'}: {q}"
    elif kind == "directions":
        home = (db.get_settings().get("home_address") or "").strip()
        if not home:
            raise NetError("自宅の住所が設定されていません。PCの「設定 > ネット連携」で設定してください")
        destination = " ".join((destination or "").split())[:120]
        if not destination:
            raise NetError("場所か住所を入れてください")
        params.update({"origin": home, "destination": destination, "mode": MAP_MODES.get(mode or "transit", "transit")})
        sent = f"経路: 自宅（{home}） → {destination}（{'電車・バス' if params['mode'] == 'transit' else '車' if params['mode'] == 'driving' else '徒歩'}）"
    else:
        raise NetError("地図の種類が正しくありません")
    record("google_maps", sent)
    return {"url": MAPS_EMBED_URL + kind + "?" + urllib.parse.urlencode(params), "sent": sent}
