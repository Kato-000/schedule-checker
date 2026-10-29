"""LLMの処理をバックグラウンドで1件ずつ実行する。
段階Aが終わった時点で状態を drafting_todos にするので、画面は予定を先に表示できる。"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from . import llm, planner, store

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")


def _read_and_draft(pid: int) -> None:
    p = store.get_proposal(pid)
    try:
        a = planner.read_event(p["input_text"])
    except Exception as e:  # noqa: BLE001 - 失敗は案に記録して画面に出す
        log.exception("段階Aに失敗 (proposal %s)", pid)
        store.update_proposal(pid, status="error", error=_message(e))
        return
    store.update_proposal(pid, status="drafting_todos", event=a["event"], questions=a["questions"],
                          meta={"warnings": a["warnings"], "retried": a["retried"], "sec_event": a["seconds"]})
    _draft(pid, p["input_text"], a["event"], a["warnings"])


def _draft(pid: int, text: str, event: dict, warnings: list[str]) -> None:
    try:
        b = planner.draft_todos(text, event)
    except Exception as e:  # noqa: BLE001
        log.exception("段階Bに失敗 (proposal %s)", pid)
        # 予定は読めているので承認はできる。Todoは手で足すか、作り直してもらう
        store.update_proposal(pid, status="pending", todos=[],
                              error="Todoを作れませんでした: " + _message(e))
        return
    store.update_proposal(pid, status="pending", todos=b["todos"], error=None,
                          meta={"warnings": sorted(set(warnings + b["warnings"])),
                                "examples": b["examples"], "sec_todos": b["seconds"]})


def _import(pid: int) -> None:
    """Googleから取り込んだ予定。日時はGoogleのものを使い、種類と締切かどうかだけLLMに判定させる。"""
    p = store.get_proposal(pid)
    event = dict(p["event"])
    try:
        a = planner.read_event(p["input_text"])
        event["category"] = a["event"]["category"]
        event["is_deadline"] = a["event"]["is_deadline"]
        store.update_proposal(pid, event=event)
    except Exception as e:  # noqa: BLE001 - 判定できなくてもTodo作成は続ける
        log.warning("取り込んだ予定の種類を判定できませんでした (proposal %s): %s", pid, e)
    _draft(pid, p["input_text"], event, [])


def _read_todo(pid: int) -> None:
    """予定に結びつかないTodoの案。読み取れなくても、文のままの案にして承認できるようにする。"""
    p = store.get_proposal(pid)
    try:
        r = planner.read_todo(p["input_text"])
    except Exception as e:  # noqa: BLE001
        log.exception("Todoの読み取りに失敗 (proposal %s)", pid)
        store.update_proposal(pid, status="pending", error="期限と優先度を読み取れませんでした: " + _message(e),
                              todos=[{"title": p["input_text"][:200], "due_date": None, "due_time": None,
                                      "priority": "medium"}])
        return
    store.update_proposal(pid, status="pending", todos=[r["todo"]], error=None,
                          meta={"warnings": r["warnings"], "sec_todos": r["seconds"]})


def submit_todo_proposal(pid: int) -> Future:
    return _executor.submit(_read_todo, pid)


def submit_import(pid: int) -> Future:
    return _executor.submit(_import, pid)


def _redraft(pid: int, event: dict) -> None:
    p = store.get_proposal(pid)
    _draft(pid, p["input_text"], event, [w for w in p["warnings"] if w != "chinese"])


def _message(e: Exception) -> str:
    return str(e) if isinstance(e, llm.LLMError) else f"{type(e).__name__}: {e}"


def submit_proposal(pid: int) -> Future:
    return _executor.submit(_read_and_draft, pid)


def submit_redraft(pid: int, event: dict) -> Future:
    store.update_proposal(pid, status="drafting_todos", event=event, todos=[], error=None)
    return _executor.submit(_redraft, pid, event)


def submit(fn, *args) -> Future:
    return _executor.submit(fn, *args)


def resume_unfinished() -> int:
    """処理中にバックエンドが止まった案を、起動時にやり直す。"""
    n = 0
    for p in store.list_proposals(("reading", "drafting_todos")):
        if p["kind"] == "import":
            submit_import(p["id"])
        elif p["kind"] == "todo":
            submit_todo_proposal(p["id"])
        elif p["status"] == "drafting_todos" and p["event"]:
            submit_redraft(p["id"], p["event"])
        else:
            store.update_proposal(p["id"], status="reading")
            submit_proposal(p["id"])
        n += 1
    if n:
        log.info("途中だった案 %d 件の処理を再開します", n)
    return n
