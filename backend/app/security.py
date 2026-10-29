"""スマホ（自宅LAN）からの接続の認証。PCのアプリ（127.0.0.1）からは不要。"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time

from . import config, db

PBKDF2_ITER = 200_000


# ---------------------------------------------------------------------------
# PIN
# ---------------------------------------------------------------------------
def validate_pin(pin: str) -> str | None:
    """問題があればその理由を返す。"""
    if not pin or len(pin) < 6:
        return "PINは6文字以上にしてください"
    if len(pin) > 64:
        return "PINは64文字以内にしてください"
    if len(set(pin)) == 1 or pin in ("123456", "1234567", "12345678", "654321"):
        return "推測されやすいPINは使えません"
    return None


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2${PBKDF2_ITER}${salt.hex()}${h.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# 接続元
# ---------------------------------------------------------------------------
def is_local(host: str | None) -> bool:
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def is_lan(host: str | None) -> bool:
    """自宅LAN（プライベートアドレス）からの接続か。"""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private and not ip.is_loopback


# ---------------------------------------------------------------------------
# PINの試行回数の制限（総当たり対策）
# ---------------------------------------------------------------------------
_fail_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def locked_out(host: str) -> int:
    """ロック中なら残り秒数、そうでなければ0。"""
    window = config.LOGIN_LOCK_MINUTES * 60
    now = time.time()
    with _fail_lock:
        recent = [t for t in _fails.get(host, []) if now - t < window]
        _fails[host] = recent
        if len(recent) >= config.LOGIN_MAX_FAILS:
            return int(window - (now - recent[0])) + 1
    return 0


def record_fail(host: str) -> None:
    with _fail_lock:
        _fails.setdefault(host, []).append(time.time())


def clear_fails(host: str) -> None:
    with _fail_lock:
        _fails.pop(host, None)


# ---------------------------------------------------------------------------
# セッション（Cookieの値はハッシュにして保存）
# ---------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    expires = dt.datetime.now() + dt.timedelta(days=config.SESSION_DAYS)
    with db.connect() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (dt.datetime.now().isoformat(),))
        c.execute("INSERT INTO sessions(token_hash, expires_at, user_agent) VALUES (?,?,?)",
                  (_hash_token(token), expires.isoformat(), (user_agent or "")[:200]))
    return token


def check_session(token: str | None) -> bool:
    if not token:
        return False
    with db.connect() as c:
        r = c.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (_hash_token(token),)).fetchone()
    return bool(r) and r["expires_at"] > dt.datetime.now().isoformat()


def delete_session(token: str | None) -> None:
    if token:
        with db.connect() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


def delete_all_sessions() -> None:
    with db.connect() as c:
        c.execute("DELETE FROM sessions")
