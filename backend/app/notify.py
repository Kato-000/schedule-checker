"""Windowsのトースト通知。Windows以外やライブラリがない環境ではログに出すだけ。"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

APP_ID = "予定チェッカー"
sent: list[tuple[str, str]] = []  # テスト用に送った内容を残す


def send(title: str, body: str) -> bool:
    sent.append((title, body))
    if sys.platform != "win32":
        log.info("通知（Windows以外のため表示なし）: %s / %s", title, body)
        return False
    try:
        from winotify import Notification  # type: ignore
    except ImportError:
        log.warning("winotify が入っていないため通知を出せません（pip install winotify）")
        return False
    try:
        Notification(app_id=APP_ID, title=title, msg=body[:250], duration="long").show()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("通知に失敗: %s", e)
        return False
