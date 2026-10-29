"""手本（過去に承認したTodo）の保存形式への変換と、似た手本の検索。"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from . import config, db
from .dates import norm_time, parse_date, to_minutes


# ---------------------------------------------------------------------------
# 承認したTodoを「予定からの相対表記」に変換（日付が変わっても使い回せるように）
# ---------------------------------------------------------------------------
def to_relative(event: dict, todos: list[dict]) -> list[dict]:
    ev_date = parse_date(event.get("start_date"))
    start = norm_time(event.get("start_time"))
    out = []
    for t in todos:
        due = parse_date(t.get("due_date"))
        days = (ev_date - due).days if ev_date and due else 0
        rel = {"title": t["title"], "days_before": max(days, 0),
               "priority": t.get("priority", "medium")}
        due_time = norm_time(t.get("due_time"))
        if due_time:
            if days == 0 and start and to_minutes(due_time) < to_minutes(start):
                rel["minutes_before_start"] = to_minutes(start) - to_minutes(due_time)
            else:
                rel["time"] = due_time
        out.append(rel)
    return out


# ---------------------------------------------------------------------------
# 似ている度合い（文字の2文字組の重なり）
# ---------------------------------------------------------------------------
def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[\s0-9０-９:：、。（）()・〇○]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def similarity(a: str, b: str) -> float:
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


# ---------------------------------------------------------------------------
# 手本の読み込み
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _seed_file() -> dict:
    try:
        return json.loads(config.SEED_EXAMPLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"rules": [], "examples": []}


def seed_rules() -> list[str]:
    return list(_seed_file().get("rules", []))


def seed_examples() -> list[dict]:
    return [dict(e, source="seed") for e in _seed_file().get("examples", [])]


def own_examples() -> list[dict]:
    with db.connect() as c:
        rs = c.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 500").fetchall()
    out = []
    for r in rs:
        out.append({"id": f"f{r['id']}", "text": r["input_text"], "category": r["category"],
                    "is_deadline": bool(r["is_deadline"]),
                    "todos": db.loads(r["todos_rel_json"], []),
                    "edited": bool(r["edited"]), "source": "own"})
    return out


def select_examples(event: dict, text: str, k: int = config.MAX_EXAMPLES) -> list[dict]:
    """自分の手本を優先して、似た手本を最大k件選ぶ。
    同じ種類の自分の手本がしきい値以上あれば、その種類では初期手本を使わない。"""
    cat = event.get("category")
    own = own_examples()
    pool = list(own)
    use_seed = db.get_settings().get("use_seed_examples", "1") == "1"
    own_same_cat = sum(1 for e in own if e["category"] == cat)
    if use_seed and own_same_cat < config.OWN_EXAMPLES_THRESHOLD:
        pool += seed_examples()

    query = f"{text} {event.get('title', '')}"
    scored = []
    seen_texts = set()
    for ex in pool:
        if ex["text"] in seen_texts:   # 同じ文の手本は新しい1件だけ
            continue
        seen_texts.add(ex["text"])
        sim = similarity(query, ex["text"])
        score = sim + (1.0 if ex["category"] == cat else 0.0)
        if ex["source"] == "own":
            score += 0.3 + (0.1 if ex.get("edited") else 0.0)
        scored.append((score, sim, ex))
    scored.sort(key=lambda x: -x[0])
    chosen = []
    for score, sim, ex in scored[:k]:
        if score <= 0.05:
            continue
        chosen.append(dict(ex, similarity=round(sim, 2), reference=sim < config.SIMILAR_THRESHOLD))
    return chosen


def active_rules(category: str | None = None) -> list[str]:
    """有効なルール（全般＋その種類）。中身は rules.py が管理する。"""
    from . import rules
    return rules.active_rules(category)
