"""2段階処理: 段階A「予定の読み取り」→ 段階B「Todo作成」。
LLMの出力はここで必ず検査・補正してから使う。"""

from __future__ import annotations

import datetime as dt
import json
import re

from . import examples as ex_mod
from . import llm, prompts
from .dates import WEEKDAYS_JA, d_ja, from_minutes, norm_time, parse_date, to_minutes, today

PAST_WORDS = re.compile(r"昨日|一昨日|おととい|先週|先月|去年|昨年|日前|ました")
# 日本語に現れにくい中国語の語（「所以」「可以」は「場所以外」等で誤検出するので使わない）
CN_WORDS = ["以及", "的话", "或者", "我们", "你们", "这个", "那个", "没有", "什么", "怎么", "因为", "但是", "已经"]


def chinese_bits(s: str) -> list[str]:
    found = [w for w in CN_WORDS if w in s]
    for ch in s:
        if "一" <= ch <= "鿿":
            try:
                ch.encode("cp932")
            except UnicodeEncodeError:
                found.append(ch)
    return found


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


# ---------------------------------------------------------------------------
# 予定の補正
# ---------------------------------------------------------------------------
def normalize_event(ev: dict, base: dt.date) -> dict:
    out = {
        "title": (ev.get("title") or "").strip() or "（無題の予定）",
        "start_date": None,
        "start_time": norm_time(ev.get("start_time")),
        "end_date": None,
        "end_time": norm_time(ev.get("end_time")),
        "location": (ev.get("location") or None),
        "category": ev.get("category") if ev.get("category") in prompts.CATEGORIES else "私用",
        "is_deadline": bool(ev.get("is_deadline")),
    }
    sd = parse_date(ev.get("start_date")) or base
    out["start_date"] = sd.isoformat()
    ed = parse_date(ev.get("end_date"))
    if ed and ed >= sd:
        out["end_date"] = ed.isoformat()
    elif out["end_time"]:
        out["end_date"] = sd.isoformat()
    if out["end_date"] == out["start_date"] and out["end_time"] and out["start_time"] \
            and to_minutes(out["end_time"]) <= to_minutes(out["start_time"]):
        out["end_time"] = None
    return out


def is_past_mistake(event: dict, text: str, base: dt.date) -> bool:
    d = parse_date(event.get("start_date"))
    return d is not None and d < base and not PAST_WORDS.search(text)


def read_event(text: str, base: dt.date | None = None) -> dict:
    """段階A。今日より前の日付は1回だけLLMに直させ、直らなければ質問に回す。"""
    base = base or today()
    msgs = prompts.event_messages(text, base)
    a, sec = llm.client.chat(msgs, prompts.EVENT_SCHEMA)
    retried = needs_review = False
    if is_past_mistake(a.get("event", {}), text, base):
        retried = True
        msgs += [{"role": "assistant", "content": json.dumps(a, ensure_ascii=False)},
                 {"role": "user", "content":
                  f"start_date が今日（{d_ja(base)}）より前の {a['event'].get('start_date')} になっています。"
                  "早見表を見直し、今日以降の正しい日付で答え直してください。"}]
        try:
            a2, sec2 = llm.client.chat(msgs, prompts.EVENT_SCHEMA)
            a, sec = a2, sec + sec2
        except llm.LLMError:
            pass
        needs_review = is_past_mistake(a.get("event", {}), text, base)

    event = normalize_event(a.get("event", {}) or {}, base)
    questions = [q for q in (a.get("questions") or []) if isinstance(q, str) and q.strip()][:1]
    warnings = []
    if needs_review:
        questions.insert(0, f"日付が {event['start_date']} と過去になりました。正しい日付を確認してください。")
        warnings.append("past_date")
    if any(chinese_bits(s) for s in _strings(event)):
        warnings.append("chinese")
    return {"event": event, "questions": questions, "warnings": warnings,
            "retried": retried, "seconds": round(sec, 2)}


# ---------------------------------------------------------------------------
# Todoの補正
# ---------------------------------------------------------------------------
def normalize_todos(todos: list[dict], event: dict, base: dt.date) -> list[dict]:
    """期限を「今日以降・予定以前」に収め、当日の時刻は開始より前にする。重複は除く。"""
    ev_date = parse_date(event.get("start_date")) or base
    start = norm_time(event.get("start_time"))
    lo, hi = min(base, ev_date), ev_date
    out, seen = [], set()
    for t in todos:
        title = (t.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        d = parse_date(t.get("due_date")) or hi
        d = max(lo, min(hi, d))
        tm = norm_time(t.get("due_time"))
        if tm and d == ev_date and start and to_minutes(tm) >= to_minutes(start):
            tm = from_minutes(to_minutes(start) - 30)  # 開始より後ろなら開始30分前に寄せる
        pr = t.get("priority") if t.get("priority") in prompts.PRIORITIES else "medium"
        out.append({"title": title, "due_date": d.isoformat(), "due_time": tm, "priority": pr})
    return out[:6]


def draft_todos(text: str, event: dict, base: dt.date | None = None) -> dict:
    """段階B。似た手本とルールを添えてTodoを作る。"""
    base = base or today()
    chosen = ex_mod.select_examples(event, text)
    rules = ex_mod.active_rules(event.get("category"))
    llm_event = {k: event.get(k) for k in ("title", "start_date", "start_time", "end_date",
                                          "end_time", "location", "category", "is_deadline")}
    b, sec = llm.client.chat(prompts.todo_messages(text, llm_event, base, chosen, rules),
                             prompts.TODO_SCHEMA)
    todos = normalize_todos(b.get("todos", []) or [], event, base)
    warnings = ["chinese"] if any(chinese_bits(s) for s in _strings(todos)) else []
    return {"todos": todos, "warnings": warnings, "seconds": round(sec, 2),
            "examples": [{"id": e["id"], "text": e["text"], "source": e["source"],
                          "reference": e["reference"]} for e in chosen]}


# ---------------------------------------------------------------------------
# 予定に結びつかないTodo（1件）
# ---------------------------------------------------------------------------
def read_todo(text: str, base: dt.date | None = None) -> dict:
    """入力文からTodoを1件読み取る。期限が書かれていなければ期限なし。"""
    base = base or today()
    msgs = prompts.single_todo_messages(text, base)
    a, sec = llm.client.chat(msgs, prompts.SINGLE_TODO_SCHEMA)
    t = a.get("todo") or {}
    d = parse_date(t.get("due_date"))
    warnings = []
    if d and d < base and not PAST_WORDS.search(text):
        msgs += [{"role": "assistant", "content": json.dumps(a, ensure_ascii=False)},
                 {"role": "user", "content":
                  f"due_date が今日（{d_ja(base)}）より前の {t.get('due_date')} になっています。"
                  "早見表を見直し、今日以降の正しい日付か、期限がなければ null で答え直してください。"}]
        try:
            a2, sec2 = llm.client.chat(msgs, prompts.SINGLE_TODO_SCHEMA)
            t, sec = (a2.get("todo") or t), sec + sec2
            d = parse_date(t.get("due_date"))
        except llm.LLMError:
            pass
        if d and d < base:
            d = base
            warnings.append("past_date")
    tm = norm_time(t.get("due_time"))
    if tm and not d:
        d = base                      # 「15時までに」だけなら今日の15時
    title = (t.get("title") or "").strip() or text.strip()
    pr = t.get("priority") if t.get("priority") in prompts.PRIORITIES else "medium"
    todo = {"title": title[:200], "due_date": d.isoformat() if d else None, "due_time": tm if d else None,
            "priority": pr}
    if any(chinese_bits(s) for s in _strings(todo)):
        warnings.append("chinese")
    return {"todo": todo, "warnings": warnings, "seconds": round(sec, 2)}


TODAY_WEEKDAY = re.compile(r"(今日|本日)(は|が|、)?\s*([月火水木金土日])曜(日)?")


def fix_weekday(text: str, base: dt.date) -> str:
    """「今日は土曜日」のように、今日の曜日を間違えて書いていたら正しい曜日に直す。"""
    wd = WEEKDAYS_JA[base.weekday()]
    return TODAY_WEEKDAY.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}{wd}曜{m.group(4) or ''}", text)


def advise(base: dt.date, today_events, week_events, open_todos) -> dict:
    a, _ = llm.client.chat(prompts.advice_messages(base, today_events, week_events, open_todos),
                           prompts.ADVICE_SCHEMA)
    return {"summary": fix_weekday((a.get("summary") or "").strip(), base),
            "suggestions": [fix_weekday(s.strip(), base) for s in (a.get("suggestions") or [])
                            if isinstance(s, str) and s.strip()][:3]}
