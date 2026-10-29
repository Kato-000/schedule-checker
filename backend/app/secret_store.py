"""APIキーなどの保存先。Windowsの資格情報マネージャーに置き、使えない環境ではファイルに置く。"""

from __future__ import annotations

import json
import logging

from . import config

log = logging.getLogger(__name__)


def _file():
    return config.DATA_DIR / "secrets.json"


def _read_file() -> dict:
    f = _file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_file(d: dict) -> None:
    f = _file()
    if d:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d), encoding="utf-8")
    else:
        f.unlink(missing_ok=True)


def get(name: str) -> str | None:
    try:
        import keyring
        v = keyring.get_password(config.KEYRING_SERVICE, name)
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return _read_file().get(name)


def set(name: str, value: str) -> None:  # noqa: A001 - 小さなモジュールなので組み込みの名前を使う
    d = _read_file()
    try:
        import keyring
        keyring.set_password(config.KEYRING_SERVICE, name, value)
        if name in d:
            d.pop(name)
            _write_file(d)
        return
    except Exception as e:  # noqa: BLE001
        log.warning("資格情報マネージャーに保存できないため、ファイルに保存します: %s", e)
    d[name] = value
    _write_file(d)


def delete(name: str) -> None:
    try:
        import keyring
        keyring.delete_password(config.KEYRING_SERVICE, name)
    except Exception:  # noqa: BLE001
        pass
    d = _read_file()
    if name in d:
        d.pop(name)
        _write_file(d)
