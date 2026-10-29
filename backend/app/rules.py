"""自分ルール。承認時の修正からLLMがルール案を作り、ユーザーが確認してから有効にする。"""

from __future__ import annotations

import logging
from collections import Counter

from . import config, db, llm, prompts
from .examples import seed_rules, similarity

log = logging.getLogger(__name__)
CATEGORY_ALL = None


class RuleError(ValueError):
    pass


def ensure_seeded() -> None:
    """初期ルールを表に入れる（初回だけ）。"""
    with db.connect() as c:
        if c.execute("SELECT COUNT(*) FROM rules WHERE source = 'seed'").fetchone()[0]:
            return
        for text in seed_rules():
            c.execute("INSERT INTO rules(text, category, status, source) VALUES (?, NULL, 'active', 'seed')", (text,))


def list_rules() -> list[dict]:
    ensure_seeded()
    with db.connect() as c:
        return db.rows(c.execute(
            "SELECT * FROM rules ORDER BY CASE status WHEN 'candidate' THEN 0 WHEN 'active' THEN 1 "
            "WHEN 'disabled' THEN 2 ELSE 3 END, id DESC"))


def active_rules(category: str | None = None) -> list[str]:
    """Todo作成に渡すルール。全般のルールと、その種類のルール。"""
    ensure_seeded()
    use_seed = db.get_settings().get("use_seed_examples", "1") == "1"
    with db.connect() as c:
        rs = db.rows(c.execute("SELECT * FROM rules WHERE status = 'active' AND (category IS NULL OR category = ?) "
                               "ORDER BY category IS NULL DESC, id", (category,)))
    return [(f"（{r['category']}）" if r["category"] else "") + r["text"]
            for r in rs if use_seed or r["source"] != "seed"]


def _clean(text: str, category: str | None) -> tuple[str, str | None]:
    text = (text or "").strip()
    if not text:
        raise RuleError("ルールの内容を入力してください")
    if len(text) > 200:
        raise RuleError("ルールは200文字以内にしてください")
    if category in ("", "全般"):
        category = None
    if category is not None and category not in prompts.CATEGORIES:
        raise RuleError("種類が正しくありません")
    return text, category


def add_rule(text: str, category: str | None) -> dict:
    text, category = _clean(text, category)
    with db.connect() as c:
        cur = c.execute("INSERT INTO rules(text, category, status, source) VALUES (?, ?, 'active', 'manual')",
                        (text, category))
    return get_rule(cur.lastrowid)


def get_rule(rid: int) -> dict:
    with db.connect() as c:
        r = db.row(c.execute("SELECT * FROM rules WHERE id = ?", (rid,)).fetchone())
    if not r:
        raise RuleError("ルールが見つかりません")
    return r


def update_rule(rid: int, fields: dict) -> dict:
    cur = get_rule(rid)
    text, category = _clean(fields.get("text", cur["text"]),
                            fields.get("category", cur["category"]) if "category" in fields else cur["category"])
    status = fields.get("status", cur["status"])
    if status not in ("candidate", "active", "rejected", "disabled"):
        raise RuleError("状態が正しくありません")
    with db.connect() as c:
        c.execute("UPDATE rules SET text=?, category=?, status=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (text, category, status, rid))
    return get_rule(rid)


def delete_rule(rid: int) -> None:
    get_rule(rid)
    with db.connect() as c:
        c.execute("DELETE FROM rules WHERE id = ?", (rid,))


# ---------------------------------------------------------------------------
# 修正履歴からルール案を作る
# ---------------------------------------------------------------------------
def unchecked_edits() -> int:
    with db.connect() as c:
        return c.execute("SELECT COUNT(*) FROM feedback WHERE edited = 1 AND rules_checked = 0").fetchone()[0]


def maybe_extract() -> bool:
    if db.get_settings().get("rules_auto", "1") != "1":
        return False
    if unchecked_edits() < config.RULES_EXTRACT_EVERY:
        return False
    from . import jobs
    jobs.submit(extract)
    return True


def _evidence(limit: int = 20) -> tuple[str, list[int]]:
    with db.connect() as c:
        rs = db.rows(c.execute("SELECT * FROM feedback WHERE edited = 1 ORDER BY rules_checked, id DESC LIMIT ?",
                               (limit,)))
    removed = Counter()
    lines = []
    for r in rs:
        d = db.loads(r["diff_json"], {}) or {}
        final = db.loads(r["final_json"], {}) or {}
        orig = db.loads(r["original_json"], {}) or {}
        parts = []
        if d.get("todos_removed"):
            parts.append("削除: " + "、".join(d["todos_removed"]))
            for t in d["todos_removed"]:
                removed[(r["category"], t)] += 1
        if d.get("todos_added"):
            parts.append("追加: " + "、".join(d["todos_added"]))
        for title in d.get("todos_changed", []):
            o = next((t for t in orig.get("todos", []) if t["title"] == title), {})
            f = next((t for t in final.get("todos", []) if t["title"] == title), {})
            parts.append(f"変更: {title}（期限 {o.get('due_date')}→{f.get('due_date')}、"
                         f"優先度 {o.get('priority')}→{f.get('priority')}）")
        if d.get("event_fields"):
            parts.append("予定の項目を修正: " + "、".join(d["event_fields"]))
        ev_date = (final.get("event") or {}).get("start_date")
        lines.append(f"- [{r['category']}] 「{r['input_text']}」（予定日 {ev_date}）: " + " / ".join(parts))
    repeated = [f"- [{cat}] 「{t}」を{n}回削除" for (cat, t), n in removed.most_common() if n >= 2]
    text = "修正の記録（新しい順）:\n" + "\n".join(lines)
    if repeated:
        text += "\n\nくり返し削除されたTodo:\n" + "\n".join(repeated)
    return text, [r["id"] for r in rs]


def _duplicate(a: str, b: str) -> bool:
    """ほぼ同じ内容か。短い方の文がほとんど長い方に含まれていても重複とみなす。"""
    from .examples import _bigrams
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return False
    contained = len(x & y) / min(len(x), len(y))
    return similarity(a, b) > 0.6 or contained > 0.75


def extract() -> list[dict]:
    """LLMにルール案を作らせ、重複を除いて「案」として保存する。"""
    ensure_seeded()
    evidence, ids = _evidence()
    if not ids:
        return []
    existing = list_rules()
    known = "\n".join(f"- {r['text']}（{'却下済み' if r['status'] == 'rejected' else '既存'}）" for r in existing)
    msgs = [{"role": "system", "content": prompts.RULES_SYSTEM},
            {"role": "user", "content": f"{evidence}\n\n既にあるルール:\n{known or 'なし'}"}]
    out, _ = llm.client.chat(msgs, prompts.RULES_SCHEMA)
    added = []
    with db.connect() as c:
        for r in (out.get("rules") or [])[:3]:
            text = (r.get("text") or "").strip()
            if not text or any(_duplicate(text, e["text"]) for e in existing + added):
                continue
            cat = r.get("category")
            cat = None if cat in (None, "", "全般") or cat not in prompts.CATEGORIES else cat
            cur = c.execute("INSERT INTO rules(text, category, status, source, reason) "
                            "VALUES (?, ?, 'candidate', 'auto', ?)", (text, cat, (r.get("reason") or "")[:200]))
            added.append({"id": cur.lastrowid, "text": text, "category": cat})
        q = ",".join("?" * len(ids))
        c.execute(f"UPDATE feedback SET rules_checked = 1 WHERE id IN ({q})", ids)
    if added:
        log.info("自分ルールの案を %d 件作りました", len(added))
    return added
