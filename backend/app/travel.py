"""家を出る時刻（経路）。予定の場所と開始時刻から「何時に出れば間に合うか」を調べる（NAVITIME）。

- 到着の目安 = 予定の開始時刻 − 「何分前に着きたいか」（設定）
- 電車・バス（transit）か車（car）。予定ごとに選べ、既定は設定のもの
- 結果は予定に保存し、今日の画面・ウィジェット・朝のまとめに出す。出発前に通知もする
"""

from __future__ import annotations

import datetime as dt
import logging

from . import db, net, notify, store
from .dates import today

log = logging.getLogger(__name__)
MODE_LABEL = {"transit": "電車・バス", "car": "車"}
MOVE_LABEL = {"walk": "徒歩", "car": "車", "bus": "バス", "domestic_flight": "飛行機", "ferry": "船",
              "superexpress_train": "新幹線", "sleeper_ultraexpress": "特急", "ultraexpress_train": "特急",
              "express_train": "急行", "rapid_train": "快速", "semiexpress_train": "準急", "local_train": "電車",
              "shuttle_bus": "バス", "highway_bus": "高速バス", "taxi": "タクシー", "cycle": "自転車"}


def _settings() -> dict:
    return db.get_settings()


def home() -> tuple[float, float] | None:
    s = _settings()
    try:
        return float(s["home_lat"]), float(s["home_lon"])
    except (KeyError, TypeError, ValueError):
        return None


def set_home(address: str) -> dict:
    """自宅の住所を確かめて位置を保存する（住所検索に住所を送る）。空なら消す。"""
    address = (address or "").strip()
    if not address:
        for k in ("home_address", "home_label", "home_lat", "home_lon"):
            db.set_setting(k, "")
        return {"home_address": "", "home_label": ""}
    from . import secret_store
    if not secret_store.get(net.RAPIDAPI_KEY):
        # 経路検索のキーがなければ、位置は確かめずに住所だけ保存する（地図の経路表示には使える）
        if not net.enabled():
            raise net.NetError("ネット連携がオフです。PCの「設定 > ネット連携」でオンにしてください")
        for k, v in (("home_address", address), ("home_label", ""), ("home_lat", ""), ("home_lon", "")):
            db.set_setting(k, v)
        return {"home_address": address, "home_label": ""}
    r = net.geocode(address, "自宅")
    if not r:
        raise net.NetError("その住所が見つかりませんでした。番地まで入れるか、表記を変えてお試しください")
    db.set_setting("home_address", address)
    db.set_setting("home_label", r["name"])
    db.set_setting("home_lat", f"{r['lat']:.6f}")
    db.set_setting("home_lon", f"{r['lon']:.6f}")
    return {"home_address": address, "home_label": r["name"]}


def _parse_time(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t.replace(tzinfo=None)   # 日本の時刻（+09:00）として扱う


def parse_route(data: dict, goal_time: dt.datetime, mode: str) -> dict:
    items = data.get("items") or []
    cands = []
    for it in items:
        mv = (it.get("summary") or {}).get("move") or {}
        f, t = _parse_time(mv.get("from_time")), _parse_time(mv.get("to_time"))
        if f and t:
            cands.append((f, t, it))
    if not cands:
        raise net.NetError("経路が見つかりませんでした")
    # 間に合う経路のうち、いちばん遅く出られるもの
    ok = [c for c in cands if c[1] <= goal_time + dt.timedelta(minutes=1)] or cands
    f, t, it = max(ok, key=lambda c: c[0])
    mv = it["summary"]["move"]
    steps = []
    last_point = None
    secs = it.get("sections") or []
    for i, sec in enumerate(secs):
        if sec.get("type") == "point":
            last_point = sec.get("name")
            continue
        if sec.get("type") != "move":
            continue
        nxt = next((s.get("name") for s in secs[i + 1:] if s.get("type") == "point"), None)
        kind = sec.get("move") or ""
        steps.append({
            "kind": kind, "label": MOVE_LABEL.get(kind, "移動"), "line": sec.get("line_name"),
            "from": last_point, "to": nxt, "minutes": sec.get("time"),
            "depart": (_parse_time(sec.get("from_time")) or f).strftime("%H:%M"),
            "arrive": (_parse_time(sec.get("to_time")) or t).strftime("%H:%M"),
        })
    fare = None
    fares = mv.get("fare")
    if isinstance(fares, dict):
        vals = [v for v in fares.values() if isinstance(v, (int, float))]
        fare = int(vals[0]) if vals else None
    return {"mode": mode, "depart_at": f.strftime("%Y-%m-%dT%H:%M"), "arrive_at": t.strftime("%Y-%m-%dT%H:%M"),
            "minutes": mv.get("time") or int((t - f).total_seconds() // 60),
            "transit_count": mv.get("transit_count"), "fare": fare, "steps": steps[:12]}


def plan(eid: int, mode: str | None = None) -> dict:
    ev = store.get_event(eid)
    s = _settings()
    mode = mode or s.get("travel_mode") or "transit"
    if mode not in MODE_LABEL:
        raise net.NetError("移動手段が正しくありません")
    if not ev.get("start_time"):
        raise net.NetError("開始時刻がない予定は、家を出る時刻を調べられません")
    start = home()
    if not start:
        raise net.NetError("自宅の住所が設定されていません。PCの「設定 > ネット連携」で設定してください")
    word = (ev.get("address") or ev.get("location") or "").strip()
    if not word:
        raise net.NetError("場所か住所を入れてください（「ネットで調べる」で住所を探せます）")
    margin = int(s.get("arrive_margin_min") or 10)
    goal_time = dt.datetime.fromisoformat(f"{ev['start_date']}T{ev['start_time']}") - dt.timedelta(minutes=margin)
    if goal_time < dt.datetime.combine(today(), dt.datetime.now().time()) - dt.timedelta(minutes=1):
        raise net.NetError("予定の時刻を過ぎているため、経路を調べられません")
    prev = ev.get("travel") or {}
    if prev.get("dest_word") == word and prev.get("dest_lat") is not None:
        dest = {"name": prev.get("dest_label") or word, "lat": prev["dest_lat"], "lon": prev["dest_lon"]}
    else:
        dest = net.geocode(word, "目的地")
        if not dest:
            raise net.NetError(f"「{word}」の位置が分かりませんでした。住所（番地まで）を入れるか、"
                               "「ネットで調べる」で住所を探してください")
    data = net.route(mode, start, (dest["lat"], dest["lon"]), goal_time, word)
    r = parse_route(data, goal_time, mode)
    r.update({"dest_word": word, "dest_label": dest["name"], "dest_lat": dest["lat"], "dest_lon": dest["lon"],
              "margin": margin, "goal_at": goal_time.strftime("%Y-%m-%dT%H:%M"),
              "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "notified": False})
    store.set_travel(eid, r)
    return store.get_event(eid)


def clear(eid: int) -> dict:
    store.get_event(eid)
    store.set_travel(eid, None)
    return store.get_event(eid)


def leave_reminders(now: dt.datetime | None = None) -> int:
    """出発の◯分前に通知する（スケジューラから1分ごと）。通知した件数を返す。"""
    now = now or dt.datetime.combine(today(), dt.datetime.now().time())
    try:
        before = int(_settings().get("leave_notify_min") or 0)
    except ValueError:
        before = 0
    if before <= 0:
        return 0
    n = 0
    for ev in store.list_events(now.date(), now.date()):
        tr = ev.get("travel")
        if not tr or tr.get("notified") or not tr.get("depart_at"):
            continue
        dep = dt.datetime.fromisoformat(tr["depart_at"])
        if dep - dt.timedelta(minutes=before) <= now < dep:
            mins = max(1, int((dep - now).total_seconds() // 60))
            notify.send(f"あと{mins}分で出発: {ev['title']}",
                        f"{dep:%H:%M}に出ると{tr['arrive_at'][11:16]}に着きます（{MODE_LABEL.get(tr['mode'], '')}・"
                        f"{ev['start_time']}開始）")
            tr["notified"] = True
            store.set_travel(ev["id"], tr)
            n += 1
    return n
