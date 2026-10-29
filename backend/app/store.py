"""データの読み書きと、承認・Todo完了などの操作。"""

from __future__ import annotations

import datetime as dt

from . import db
from . import examples as ex_mod
from . import google_sync as gs
from .dates import norm_time, parse_date, today
from .planner import normalize_event, normalize_todos
from .prompts import PRIORITIES

EVENT_FIELDS = ("title", "start_date", "start_time", "end_date", "end_time",
                "location", "category", "is_deadline")


class NotFound(LookupError):
    pass


class Invalid(ValueError):
    pass


# ---------------------------------------------------------------------------
# 案（proposals）
# ---------------------------------------------------------------------------
def _proposal_out(r: dict) -> dict:
    meta = db.loads(r.get("meta_json"), {}) or {}
    return {"id": r["id"], "input_text": r["input_text"], "status": r["status"],
            "kind": r.get("kind") or "new",
            "google": meta.get("google"),       # 衝突のとき: Google側の内容（削除ならNone）
            "google_deleted": meta.get("google_deleted", False),
            "event": db.loads(r.get("event_json")),
            "todos": db.loads(r.get("todos_json"), []),
            "questions": db.loads(r.get("questions_json"), []),
            "warnings": meta.get("warnings", []),
            "examples": meta.get("examples", []),
            "seconds": {"event": meta.get("sec_event"), "todos": meta.get("sec_todos")},
            "source": meta.get("source", "text"),   # text / voice（音声入力）
            "error": r.get("error"), "event_id": r.get("event_id"),
            "created_at": r["created_at"], "decided_at": r.get("decided_at")}


def create_proposal(text: str, kind: str = "new", source: str = "text") -> dict:
    """kind: new（予定の案）/ todo（予定に結びつかないTodoの案）。source: text / voice"""
    text = (text or "").strip()
    if not text:
        raise Invalid("予定の文を入力してください" if kind == "new" else "Todoの文を入力してください")
    if kind not in ("new", "todo") or source not in ("text", "voice"):
        raise Invalid("案の種類が正しくありません")
    with db.connect() as c:
        cur = c.execute("INSERT INTO proposals(input_text, status, kind, meta_json) VALUES (?, 'reading', ?, ?)",
                        (text, kind, db.dumps({"source": source})))
        pid = cur.lastrowid
    return get_proposal(pid)


def get_proposal(pid: int) -> dict:
    with db.connect() as c:
        r = db.row(c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone())
    if not r:
        raise NotFound("案が見つかりません")
    return _proposal_out(r)


def list_proposals(statuses: tuple[str, ...] = ("reading", "drafting_todos", "pending", "error")) -> list[dict]:
    q = ",".join("?" * len(statuses))
    with db.connect() as c:
        rs = db.rows(c.execute(f"SELECT * FROM proposals WHERE status IN ({q}) ORDER BY id", statuses))
    return [_proposal_out(r) for r in rs]


def update_proposal(pid: int, **fields) -> None:
    meta_update = fields.pop("meta", None)
    sets, vals = [], []
    for k, v in fields.items():
        if k in ("event", "todos", "questions"):
            sets.append(f"{k}_json = ?")
            vals.append(db.dumps(v))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    with db.connect() as c:
        if meta_update is not None:
            r = c.execute("SELECT meta_json FROM proposals WHERE id = ?", (pid,)).fetchone()
            meta = db.loads(r["meta_json"] if r else None, {}) or {}
            meta.update(meta_update)
            sets.append("meta_json = ?")
            vals.append(db.dumps(meta))
        if sets:
            c.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE id = ?", (*vals, pid))


def pending_count() -> int:
    with db.connect() as c:
        return c.execute("SELECT COUNT(*) FROM proposals WHERE status IN "
                         "('reading','drafting_todos','pending','error')").fetchone()[0]


def _clean_event(ev: dict) -> dict:
    if not isinstance(ev, dict):
        raise Invalid("予定の形式が正しくありません")
    if not parse_date(ev.get("start_date")):
        raise Invalid("開始日を入力してください")
    for k in ("start_time", "end_time"):
        if ev.get(k) and not norm_time(ev.get(k)):
            raise Invalid(f"時刻の形式が正しくありません: {ev.get(k)}")
    out = normalize_event(ev, parse_date(ev["start_date"]))
    out["title"] = (ev.get("title") or "").strip() or out["title"]
    out["local_only"] = bool(ev.get("local_only"))
    out["address"] = (ev.get("address") or "").strip()[:200] or None
    return out


def _clean_todos(todos: list[dict], require_due: bool = True) -> list[dict]:
    """require_due=False なら期限なし（None）も認める（予定に結びつかないTodo）。"""
    out = []
    for t in todos or []:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        raw = t.get("due_date")
        d = parse_date(raw) if raw else None
        if raw and not d:
            raise Invalid(f"Todo「{title}」の期限の形式が正しくありません")
        if not d and require_due:
            raise Invalid(f"Todo「{title}」の期限を入力してください")
        out.append({"title": title, "due_date": d.isoformat() if d else None,
                    "due_time": norm_time(t.get("due_time")) if d else None,
                    "priority": t.get("priority") if t.get("priority") in PRIORITIES else "medium"})
    return out


def _diff(orig_ev: dict, orig_todos: list[dict], ev: dict, todos: list[dict]) -> dict:
    changed = [k for k in EVENT_FIELDS if (orig_ev or {}).get(k) != ev.get(k)]
    o = {t["title"]: t for t in orig_todos or []}
    f = {t["title"]: t for t in todos}
    return {
        "event_fields": changed,
        "todos_added": [k for k in f if k not in o],
        "todos_removed": [k for k in o if k not in f],
        "todos_changed": [k for k in f if k in o and
                          any(f[k].get(x) != o[k].get(x) for x in ("due_date", "due_time", "priority"))],
    }


def _push_wanted(local_only: bool) -> bool:
    return gs.mode() == "two_way" and not local_only


def approve_proposal(pid: int, event: dict, todos: list[dict]) -> dict:
    p = get_proposal(pid)
    if p["status"] in ("approved", "rejected"):
        raise Invalid("この案はすでに処理済みです")
    if p["kind"] == "conflict":
        raise Invalid("変更の衝突は「どちらを残すか」を選んでください")
    if p["kind"] == "todo":
        return _approve_todo_proposal(p, todos)
    ev = _clean_event(event or {})
    tds = _clean_todos(todos)
    diff = _diff(p["event"], p["todos"], ev, tds)
    edited = any(diff.values())
    pushed = False
    with db.connect() as c:
        if p["kind"] == "import":
            # Googleから取り込み済みの予定。Todoを足し、直した項目があれば反映する
            eid = p["event_id"]
            cur = db.row(c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone())
            if not cur:
                raise NotFound("取り込んだ予定が見つかりません（Google側で削除された可能性があります）")
            changed_sync = any((cur.get(k) or None) != (ev.get(k) or None) for k in gs.SYNC_FIELDS)
            pushed = changed_sync and _push_wanted(False)
            c.execute("UPDATE events SET title=?, start_date=?, start_time=?, end_date=?, end_time=?, location=?, "
                      "address=COALESCE(?, address), category=?, is_deadline=?, needs_push=MAX(needs_push, ?), "
                      "updated_at=datetime('now','localtime') WHERE id=?",
                      (ev["title"], ev["start_date"], ev["start_time"], ev["end_date"], ev["end_time"],
                       ev["location"], ev["address"], ev["category"], int(ev["is_deadline"]), int(pushed), eid))
        else:
            pushed = _push_wanted(ev["local_only"])
            cur = c.execute(
                "INSERT INTO events(title, start_date, start_time, end_date, end_time, location, address, category, "
                "is_deadline, local_only, needs_push) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ev["title"], ev["start_date"], ev["start_time"], ev["end_date"], ev["end_time"],
                 ev["location"], ev["address"], ev["category"], int(ev["is_deadline"]), int(ev["local_only"]),
                 int(pushed)))
            eid = cur.lastrowid
        for t in tds:
            c.execute("INSERT INTO todos(event_id, title, due_date, due_time, priority) VALUES (?,?,?,?,?)",
                      (eid, t["title"], t["due_date"], t["due_time"], t["priority"]))
        # 承認の記録 = 次回からの手本
        c.execute(
            "INSERT INTO feedback(proposal_id, input_text, category, is_deadline, event_title, original_json, "
            "final_json, todos_rel_json, edited, diff_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, p["input_text"], ev["category"], int(ev["is_deadline"]), ev["title"],
             db.dumps({"event": p["event"], "todos": p["todos"]}), db.dumps({"event": ev, "todos": tds}),
             db.dumps(ex_mod.to_relative(ev, tds)), int(edited), db.dumps(diff)))
        c.execute("UPDATE proposals SET status='approved', event_id=?, decided_at=datetime('now','localtime') "
                  "WHERE id=?", (eid, pid))
    if pushed:
        gs.submit_sync()
    _after_approval(edited)
    return {"event": get_event(eid), "edited": edited, "diff": diff}


def _approve_todo_proposal(p: dict, todos: list[dict]) -> dict:
    """予定に結びつかないTodoの案。手本（feedback）には使わない。"""
    if p["status"] != "pending":
        raise Invalid("まだ読み取り中です")
    tds = _clean_todos(todos, require_due=False)
    if not tds:
        raise Invalid("Todoの内容を入力してください")
    orig = p["todos"]
    edited = [(t["title"], t["due_date"], t["due_time"], t["priority"]) for t in tds] != \
             [(t.get("title"), t.get("due_date"), t.get("due_time"), t.get("priority")) for t in orig]
    ids = []
    with db.connect() as c:
        for t in tds:
            cur = c.execute("INSERT INTO todos(event_id, title, due_date, due_time, priority) VALUES (NULL,?,?,?,?)",
                            (t["title"], t["due_date"], t["due_time"], t["priority"]))
            ids.append(cur.lastrowid)
        c.execute("UPDATE proposals SET status='approved', decided_at=datetime('now','localtime') WHERE id=?",
                  (p["id"],))
    return {"todos": [get_todo(i) for i in ids], "edited": edited, "event": None, "diff": {}}


def _after_approval(edited: bool) -> None:
    """修正ありの承認がたまったら、自分ルールの案づくりを予約する。"""
    if not edited:
        return
    from . import rules
    rules.maybe_extract()


def reject_proposal(pid: int) -> dict:
    p = get_proposal(pid)
    if p["kind"] == "conflict":
        raise Invalid("変更の衝突は「どちらを残すか」を選んでください")
    with db.connect() as c:
        c.execute("UPDATE proposals SET status='rejected', decided_at=datetime('now','localtime') WHERE id=?",
                  (pid,))
    return get_proposal(pid)


# ---------------------------------------------------------------------------
# 予定
# ---------------------------------------------------------------------------
def _event_out(r: dict, todos: list[dict] | None = None) -> dict:
    r = dict(r)
    r["travel"] = db.loads(r.pop("travel_json", None))   # 最後に調べた経路（家を出る時刻）
    r["is_deadline"] = bool(r["is_deadline"])
    r["local_only"] = bool(r["local_only"])
    if todos is not None:
        r["todos"] = todos
    return r


def _todo_out(r: dict) -> dict:
    return dict(r)


def get_event(eid: int) -> dict:
    with db.connect() as c:
        r = db.row(c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone())
        if not r:
            raise NotFound("予定が見つかりません")
        todos = db.rows(c.execute("SELECT * FROM todos WHERE event_id = ? ORDER BY due_date, due_time", (eid,)))
    return _event_out(r, [_todo_out(t) for t in todos])


def list_events(start: dt.date, end: dt.date) -> list[dict]:
    """期間に少しでも重なる予定（複数日の予定も含む）。"""
    with db.connect() as c:
        rs = db.rows(c.execute(
            "SELECT * FROM events WHERE start_date <= ? AND COALESCE(end_date, start_date) >= ? "
            "ORDER BY start_date, COALESCE(start_time, '00:00')", (end.isoformat(), start.isoformat())))
        ids = [r["id"] for r in rs]
        todos: dict[int, list] = {i: [] for i in ids}
        if ids:
            q = ",".join("?" * len(ids))
            for t in db.rows(c.execute(f"SELECT * FROM todos WHERE event_id IN ({q}) "
                                       "ORDER BY due_date, due_time", ids)):
                todos[t["event_id"]].append(_todo_out(t))
    return [_event_out(r, todos[r["id"]]) for r in rs]


def update_event(eid: int, fields: dict) -> dict:
    cur = get_event(eid)
    merged = {k: fields.get(k, cur.get(k)) for k in (*EVENT_FIELDS, "local_only", "address")}
    ev = _clean_event(merged)
    # 日時や場所が変わったら、調べた経路は使えないので消す
    travel_stale = any((cur.get(k) or None) != (ev.get(k) or None)
                       for k in ("start_date", "start_time", "location", "address"))
    memo = fields.get("memo", cur.get("memo"))
    gid = cur["google_event_id"]
    # Googleから来た予定は「ローカル限定」にできない（Google側にあるため）
    local_only = ev["local_only"] if cur["source"] == "local" else False
    synced_changed = any((cur.get(k) or None) != (ev.get(k) or None) for k in gs.SYNC_FIELDS)
    needs_push = cur["needs_push"]
    if local_only and gid:
        # ローカル限定にした → Googleからは消す
        if gs.mode() == "two_way":
            gs.queue_google_delete(gid)
        gid, needs_push = None, 0
    elif not local_only and (synced_changed or (cur["local_only"] and not local_only)):
        needs_push = 1 if _push_wanted(False) else needs_push
    with db.connect() as c:
        c.execute("UPDATE events SET title=?, start_date=?, start_time=?, end_date=?, end_time=?, location=?, "
                  "address=?, category=?, is_deadline=?, memo=?, local_only=?, google_event_id=?, needs_push=?, "
                  "updated_at=datetime('now','localtime') WHERE id=?",
                  (ev["title"], ev["start_date"], ev["start_time"], ev["end_date"], ev["end_time"],
                   ev["location"], ev["address"], ev["category"], int(ev["is_deadline"]), memo, int(local_only),
                   gid, int(needs_push), eid))
        if travel_stale:
            c.execute("UPDATE events SET travel_json = NULL WHERE id = ?", (eid,))
    if gs.mode() == "two_way" and (needs_push or (local_only and cur["google_event_id"])):
        gs.submit_sync()
    return get_event(eid)


def set_travel(eid: int, travel: dict | None) -> None:
    with db.connect() as c:
        c.execute("UPDATE events SET travel_json = ? WHERE id = ?", (db.dumps(travel) if travel else None, eid))


def delete_event(eid: int, from_google: bool = False) -> None:
    cur = get_event(eid)
    if not from_google and cur["google_event_id"] and gs.mode() == "two_way":
        gs.queue_google_delete(cur["google_event_id"])
        gs.submit_sync()
    with db.connect() as c:
        c.execute("DELETE FROM events WHERE id = ?", (eid,))


# ---------------------------------------------------------------------------
# Googleとの同期で使う操作
# ---------------------------------------------------------------------------
def has_open_todos(eid: int) -> bool:
    with db.connect() as c:
        return c.execute("SELECT COUNT(*) FROM todos WHERE event_id = ? AND status = 'open'",
                         (eid,)).fetchone()[0] > 0


def insert_google_event(g_ev: dict, gid: str, etag: str | None) -> int:
    with db.connect() as c:
        cur = c.execute(
            "INSERT INTO events(title, start_date, start_time, end_date, end_time, location, category, is_deadline, "
            "source, google_event_id, google_etag, synced_at) "
            "VALUES (?,?,?,?,?,?,'私用',0,'google',?,?,datetime('now','localtime'))",
            (g_ev["title"], g_ev["start_date"], g_ev["start_time"], g_ev["end_date"], g_ev["end_time"],
             g_ev["location"], gid, etag))
        return cur.lastrowid


def apply_google_update(eid: int, g_ev: dict, etag: str | None) -> None:
    with db.connect() as c:
        # 日時か場所が変わったら、調べた経路は消す（右辺は更新前の値で評価される）
        c.execute("UPDATE events SET travel_json = CASE WHEN start_date = ? AND IFNULL(start_time, '') = IFNULL(?, '') "
                  "AND IFNULL(location, '') = IFNULL(?, '') THEN travel_json ELSE NULL END, "
                  "title=?, start_date=?, start_time=?, end_date=?, end_time=?, location=?, "
                  "google_etag=?, synced_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
                  "WHERE id=?",
                  (g_ev["start_date"], g_ev["start_time"], g_ev["location"],
                   g_ev["title"], g_ev["start_date"], g_ev["start_time"], g_ev["end_date"], g_ev["end_time"],
                   g_ev["location"], etag, eid))


def mark_synced(eid: int, etag: str | None, clear_push: bool = True) -> None:
    with db.connect() as c:
        c.execute("UPDATE events SET google_etag=?, synced_at=datetime('now','localtime')"
                  + (", needs_push=0, push_error=NULL" if clear_push else "") + " WHERE id=?", (etag, eid))


def mark_pushed(eid: int, gid: str | None, etag: str | None) -> None:
    with db.connect() as c:
        c.execute("UPDATE events SET google_event_id=COALESCE(?, google_event_id), google_etag=?, needs_push=0, "
                  "push_error=NULL, synced_at=datetime('now','localtime') WHERE id=?", (gid, etag, eid))


def mark_push_error(eid: int, msg: str) -> None:
    with db.connect() as c:
        c.execute("UPDATE events SET push_error=? WHERE id=?", (msg[:300], eid))


def create_import_proposal(eid: int) -> int:
    """Googleから来た新しい予定に、Todo案を作って承認待ちに出す。"""
    from . import jobs
    ev = get_event(eid)
    text = ev["title"] + (f"（{ev['location']}）" if ev.get("location") else "")
    event = {k: ev[k] for k in EVENT_FIELDS}
    with db.connect() as c:
        cur = c.execute("INSERT INTO proposals(input_text, status, kind, event_json, event_id, meta_json) "
                        "VALUES (?, 'drafting_todos', 'import', ?, ?, ?)",
                        (text, db.dumps(event), eid, db.dumps({"warnings": []})))
        pid = cur.lastrowid
    jobs.submit_import(pid)
    return pid


def create_conflict(local: dict, g_ev: dict | None, gid: str, etag: str | None = None) -> int:
    """PCとGoogleの両方で変わった（またはGoogleで消えた）予定。どちらを残すか選んでもらう。"""
    with db.connect() as c:
        dup = c.execute("SELECT id FROM proposals WHERE kind='conflict' AND event_id=? AND status='pending'",
                        (local["id"],)).fetchone()
        meta = {"google": g_ev, "google_deleted": g_ev is None, "google_etag": etag, "warnings": []}
        event = {k: local.get(k) for k in EVENT_FIELDS}
        event["is_deadline"] = bool(event["is_deadline"])
        if dup:
            c.execute("UPDATE proposals SET meta_json=?, event_json=? WHERE id=?",
                      (db.dumps(meta), db.dumps(event), dup["id"]))
            return dup["id"]
        cur = c.execute("INSERT INTO proposals(input_text, status, kind, event_json, event_id, meta_json) "
                        "VALUES (?, 'pending', 'conflict', ?, ?, ?)",
                        (local["title"], db.dumps(event), local["id"], db.dumps(meta)))
        return cur.lastrowid


def resolve_conflict(pid: int, keep: str) -> dict:
    p = get_proposal(pid)
    if p["kind"] != "conflict" or p["status"] != "pending":
        raise Invalid("この案は衝突の確認ではありません")
    if keep not in ("local", "google"):
        raise Invalid("keep は local か google を指定してください")
    with db.connect() as c:
        meta = db.loads(c.execute("SELECT meta_json FROM proposals WHERE id=?", (pid,)).fetchone()[0], {})
    eid = p["event_id"]
    try:
        get_event(eid)
    except NotFound:
        eid = None
    if eid:
        if p["google_deleted"]:
            if keep == "google":
                delete_event(eid, from_google=True)
            else:
                # Googleでは消えたが、PCには残す
                with db.connect() as c:
                    c.execute("UPDATE events SET google_event_id=NULL, google_etag=NULL, source='local', "
                              "needs_push=? WHERE id=?", (int(_push_wanted(False)), eid))
        elif keep == "google":
            apply_google_update(eid, p["google"], meta.get("google_etag"))
            mark_synced(eid, meta.get("google_etag"))
        else:
            with db.connect() as c:
                c.execute("UPDATE events SET google_etag=?, needs_push=? WHERE id=?",
                          (meta.get("google_etag"), int(_push_wanted(False)), eid))
    with db.connect() as c:
        c.execute("UPDATE proposals SET status='approved', decided_at=datetime('now','localtime') WHERE id=?",
                  (pid,))
    if gs.mode() == "two_way":
        gs.submit_sync()
    return get_proposal(pid)


# ---------------------------------------------------------------------------
# Todo
# ---------------------------------------------------------------------------
def _todos_query(where: str, args: tuple) -> list[dict]:
    with db.connect() as c:
        rs = db.rows(c.execute(
            "SELECT t.*, e.title AS event_title, e.start_date AS event_date, e.start_time AS event_time "
            f"FROM todos t LEFT JOIN events e ON e.id = t.event_id WHERE {where} "
            "ORDER BY t.due_date, CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "COALESCE(t.due_time, '99:99')", args))
    return rs


def list_todos(start: dt.date | None = None, end: dt.date | None = None, status: str | None = None) -> list[dict]:
    conds, args = ["1=1"], []
    if start:
        conds.append("t.due_date >= ?")
        args.append(start.isoformat())
    if end:
        conds.append("t.due_date <= ?")
        args.append(end.isoformat())
    if status:
        conds.append("t.status = ?")
        args.append(status)
    return _todos_query(" AND ".join(conds), tuple(args))


def get_todo(tid: int) -> dict:
    rs = _todos_query("t.id = ?", (tid,))
    if not rs:
        raise NotFound("Todoが見つかりません")
    return rs[0]


def create_todo(fields: dict) -> dict:
    t = _clean_todos([fields], require_due=bool(fields.get("event_id")))
    if not t:
        raise Invalid("Todoの内容を入力してください")
    t = t[0]
    eid = fields.get("event_id")
    if eid:
        get_event(int(eid))
    with db.connect() as c:
        cur = c.execute("INSERT INTO todos(event_id, title, due_date, due_time, priority) VALUES (?,?,?,?,?)",
                        (eid, t["title"], t["due_date"], t["due_time"], t["priority"]))
    return get_todo(cur.lastrowid)


def update_todo(tid: int, fields: dict) -> dict:
    cur = get_todo(tid)
    merged = {k: fields.get(k, cur.get(k)) for k in ("title", "due_date", "due_time", "priority")}
    t = _clean_todos([merged], require_due=bool(cur.get("event_id")))
    if not t:
        raise Invalid("Todoの内容を入力してください")
    t = t[0]
    status = fields.get("status", cur["status"])
    if status not in ("open", "done", "skipped"):
        raise Invalid("状態が正しくありません")
    completed = cur["completed_at"]
    if status == "done" and cur["status"] != "done":
        completed = f"{today().isoformat()} {dt.datetime.now():%H:%M:%S}"   # today() は試験用の日付にも従う
    elif status != "done":
        completed = None
    with db.connect() as c:
        c.execute("UPDATE todos SET title=?, due_date=?, due_time=?, priority=?, status=?, completed_at=?, "
                  "updated_at=datetime('now','localtime') WHERE id=?",
                  (t["title"], t["due_date"], t["due_time"], t["priority"], status, completed, tid))
    return get_todo(tid)


def delete_todo(tid: int) -> None:
    get_todo(tid)
    with db.connect() as c:
        c.execute("DELETE FROM todos WHERE id = ?", (tid,))


# ---------------------------------------------------------------------------
# 今日の一覧（ウィジェットと朝のまとめで使う）
# ---------------------------------------------------------------------------
def today_view(day: dt.date | None = None) -> dict:
    day = day or today()
    week_end = day + dt.timedelta(days=7)
    events = list_events(day, day)
    open_todos = _todos_query("t.status = 'open' AND t.due_date <= ?", (week_end.isoformat(),))
    iso = day.isoformat()
    # 期限なしのTodoは、今日完了したものを「今日完了」に数える
    done_today = _todos_query("t.status = 'done' AND (t.due_date = ? OR "
                              "(t.due_date IS NULL AND substr(t.completed_at, 1, 10) = ?))", (iso, iso))
    no_due = _todos_query("t.status = 'open' AND t.due_date IS NULL", ())
    return {
        "date": iso,
        "events": events,
        "overdue": [t for t in open_todos if t["due_date"] < iso],
        "due_today": [t for t in open_todos if t["due_date"] == iso],
        "this_week": [t for t in open_todos if t["due_date"] > iso],
        "no_due": no_due,                 # 期限なし（予定に結びつかないTodoなど）
        "done_today": done_today,
        "pending_count": pending_count(),
    }
