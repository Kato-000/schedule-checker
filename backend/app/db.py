"""SQLite。1ファイルで完結し、バックアップはファイルのコピーだけでよい。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    start_date    TEXT NOT NULL,          -- YYYY-MM-DD
    start_time    TEXT,                   -- HH:MM（なければ終日・締切）
    end_date      TEXT,
    end_time      TEXT,
    location      TEXT,
    category      TEXT NOT NULL DEFAULT '私用',
    is_deadline   INTEGER NOT NULL DEFAULT 0,
    memo          TEXT,
    source        TEXT NOT NULL DEFAULT 'local',   -- local / google（第2段階）
    google_event_id TEXT,
    local_only    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date);

CREATE TABLE IF NOT EXISTS todos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      INTEGER REFERENCES events(id) ON DELETE CASCADE,   -- 予定に結びつかないTodoはNULL
    title         TEXT NOT NULL,
    due_date      TEXT,                   -- 期限なしはNULL
    due_time      TEXT,
    priority      TEXT NOT NULL DEFAULT 'medium',  -- high / medium / low
    status        TEXT NOT NULL DEFAULT 'open',    -- open / done / skipped
    completed_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date, status);

-- LLMの案。承認されるまで予定・Todoには入らない
CREATE TABLE IF NOT EXISTS proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text    TEXT NOT NULL,
    status        TEXT NOT NULL,  -- reading / drafting_todos / pending / approved / rejected / error
    event_json    TEXT,
    todos_json    TEXT,
    questions_json TEXT,
    meta_json     TEXT,       -- 使った手本・警告・処理時間など
    error         TEXT,
    event_id      INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    decided_at    TEXT
);

-- 承認の記録。手本として使う（todos_rel_json は予定からの相対表記）
CREATE TABLE IF NOT EXISTS feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id   INTEGER,
    input_text    TEXT NOT NULL,
    category      TEXT NOT NULL,
    is_deadline   INTEGER NOT NULL DEFAULT 0,
    event_title   TEXT,
    original_json TEXT,       -- LLMの元の案
    final_json    TEXT,       -- 承認された最終版
    todos_rel_json TEXT NOT NULL,
    edited        INTEGER NOT NULL DEFAULT 0,
    diff_json     TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_cat ON feedback(category);

CREATE TABLE IF NOT EXISTS digests (
    date          TEXT PRIMARY KEY,
    content_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 第2段階で追加した表（既存のDBにもそのまま追加される）
SCHEMA_V2 = """
-- スマホ（自宅LAN）からのログイン
CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    expires_at    TEXT NOT NULL,
    user_agent    TEXT
);

-- 自分ルール（初期ルール・自動抽出の案・手で追加したもの）
CREATE TABLE IF NOT EXISTS rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    text          TEXT NOT NULL,
    category      TEXT,              -- NULL は全種類に適用
    status        TEXT NOT NULL,     -- candidate / active / rejected / disabled
    source        TEXT NOT NULL,     -- seed / auto / manual
    reason        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Googleとの同期の状態（同期トークンなど）
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ネット連携（調べもの・経路）で外に送った内容の記録。本人が確認できるように残す
CREATE TABLE IF NOT EXISTS net_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    service       TEXT NOT NULL,     -- ollama_search / navitime_address / navitime_transit / navitime_car
    sent          TEXT NOT NULL,     -- 送った内容（検索語・住所・到着時刻など）
    ok            INTEGER NOT NULL DEFAULT 1
);
"""

# 既存の表に足す列: (表, 列, 定義)
MIGRATIONS = [
    ("events", "google_etag", "TEXT"),
    ("events", "synced_at", "TEXT"),          # 最後にGoogleとそろえた時刻
    ("events", "needs_push", "INTEGER NOT NULL DEFAULT 0"),  # Googleへ送り直しが必要
    ("events", "push_error", "TEXT"),
    ("proposals", "kind", "TEXT NOT NULL DEFAULT 'new'"),  # new / import / conflict
    ("feedback", "rules_checked", "INTEGER NOT NULL DEFAULT 0"),
    ("events", "address", "TEXT"),            # 住所（経路を調べるとき使う。ネットで調べて入れることもある）
    ("events", "travel_json", "TEXT"),        # 最後に調べた経路（家を出る時刻など）
]

_init_lock = threading.Lock()
_initialized: set[str] = set()


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_V2)
    for table, col, decl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    _todos_due_optional(conn)


TODO_COLUMNS = "id, event_id, title, due_date, due_time, priority, status, completed_at, created_at, updated_at"


def _todos_due_optional(conn: sqlite3.Connection) -> None:
    """第3段階までの todos は期限が必須だった。期限なしのTodoを入れられるよう、表を作り直す（中身はそのまま）。"""
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(todos)")}
    if not info.get("due_date") or info["due_date"][3] == 0:   # [3] = notnull
        return
    create = SCHEMA.split("CREATE TABLE IF NOT EXISTS todos", 1)[1].split(";", 1)[0]
    conn.commit()                         # 途中の暗黙のトランザクションを閉じてから作り直す
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("CREATE TABLE todos_new" + create)
        conn.execute(f"INSERT INTO todos_new ({TODO_COLUMNS}) SELECT {TODO_COLUMNS} FROM todos")
        conn.execute("DROP TABLE todos")
        conn.execute("ALTER TABLE todos_new RENAME TO todos")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date, status)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _db_path() -> Path:
    return config.DB_PATH


def init_db() -> None:
    path = _db_path()
    with _init_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _migrate(conn)
            for k, v in config.DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        _initialized.add(str(path))


@contextmanager
def connect():
    path = _db_path()
    if str(path) not in _initialized:
        init_db()
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s: str | None, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


def get_settings() -> dict:
    with connect() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}


def set_setting(key: str, value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
