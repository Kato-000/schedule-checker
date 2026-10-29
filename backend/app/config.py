"""設定。環境変数で上書きできる。"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# データの置き場所（既定は backend/data）
DATA_DIR = Path(os.environ.get("SC_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "schedule.db"
SEED_EXAMPLES_PATH = Path(os.environ.get("SC_SEED_EXAMPLES", BASE_DIR / "seed_examples.json"))

# バックエンドの待ち受け先。第1段階は自分のPCのみ（LAN公開は第2段階）
HOST = os.environ.get("SC_HOST", "127.0.0.1")
PORT = int(os.environ.get("SC_PORT", "8765"))

# Ollama
OLLAMA_URL = os.environ.get("SC_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("SC_OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_NUM_CTX = int(os.environ.get("SC_OLLAMA_NUM_CTX", "6144"))
OLLAMA_TIMEOUT = float(os.environ.get("SC_OLLAMA_TIMEOUT", "180"))

# 手本: 同じ種類で自分の手本がこの件数以上あれば、初期手本は使わない
OWN_EXAMPLES_THRESHOLD = 3
MAX_EXAMPLES = 3
# これより似ていない手本は「参考」として渡す
SIMILAR_THRESHOLD = 0.25

# 画面からの接続を許可する送信元（Tauri と開発用のVite）
CORS_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# 朝のまとめの定時処理（テストでは 0 にして止める）
ENABLE_SCHEDULER = os.environ.get("SC_SCHEDULER", "1") == "1"

# --- 自宅LANからのアクセス（第2段階） ---------------------------------------
# PCのアプリは 127.0.0.1:8765（HTTP）、スマホは LAN_PORT（HTTPS・PIN必須）
LAN_PORT = int(os.environ.get("SC_LAN_PORT", "8766"))
CERT_DIR = DATA_DIR / "certs"
CERT_FILE = CERT_DIR / "lan.pem"
KEY_FILE = CERT_DIR / "lan-key.pem"
SESSION_DAYS = 14             # ログインの有効期限
LOGIN_MAX_FAILS = 5           # この回数PINを間違えると…
LOGIN_LOCK_MINUTES = 15       # …この時間ログインできない
SESSION_COOKIE = "sc_session"

# --- Googleカレンダー連携（第2段階） ---------------------------------------
GOOGLE_CLIENT_SECRET = DATA_DIR / "google_client_secret.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
GOOGLE_CALENDAR_ID = "primary"
GOOGLE_SYNC_MINUTES = 15
# 自動同期の間隔（分）。daily は朝のまとめの少し前に1日1回、manual は自動で同期しない
GOOGLE_SYNC_INTERVALS = {"15m": 15, "1h": 60, "6h": 360, "daily": None, "manual": None}
GOOGLE_DAILY_BEFORE_DIGEST_MIN = 10
GOOGLE_FIRST_SYNC_DAYS_BACK = 30      # 初回は30日前から取り込む
GOOGLE_TODO_PROPOSAL_DAYS = 30        # この日数以内の新しい予定にだけTodo案を作る
KEYRING_SERVICE = "ScheduleChecker-Google"

# --- 自分ルール（第2段階） --------------------------------------------------
RULES_EXTRACT_EVERY = 5      # 修正ありの承認がこの件数たまったらルール案を作る

DEFAULT_SETTINGS = {
    "digest_time": "07:00",
    "digest_notify": "1",
    "use_seed_examples": "1",
    "lan_enabled": "0",
    "pin_hash": "",
    "google_mode": "off",               # off / import / two_way
    "google_default_local_only": "0",   # 新しい予定を最初から「ローカル限定」にするか
    "google_sync_interval": "15m",      # 自動同期の間隔: 15m / 1h / 6h / daily（朝のまとめの前） / manual
    "rules_auto": "1",
    "voice_model": "large-v3-turbo",    # 音声入力の文字起こしモデル
    "widget_autohide": "1",             # ウィジェットを画面端に寄せたら自動でたたむ
    "idle_seconds": "60",               # 操作がないまま何秒たったら軽くするか（モデルを外す・画面の更新を止める）
    # ネット連携（調べもの・経路）。初期値OFF。ボタンを押したときだけ通信する
    "net_enabled": "0",
    "home_address": "",                 # 経路の出発地（自宅の住所）
    "home_label": "",                   # 住所検索で見つかった表記
    "home_lat": "",
    "home_lon": "",
    "travel_mode": "transit",           # transit（電車・バス）/ car（車）
    "arrive_margin_min": "10",          # 予定の何分前に着きたいか
    "leave_notify_min": "15",           # 家を出る何分前に通知するか（0なら通知しない）
}

# ネット連携の通信先（RapidAPI の NAVITIME と Ollama のWeb検索）。変わったときは環境変数で上書きできる
OLLAMA_SEARCH_URL = os.environ.get("SC_OLLAMA_SEARCH_URL", "https://ollama.com/api/web_search")
NAVITIME_HOSTS = {
    "address": os.environ.get("SC_NAVI_GEO_HOST", "navitime-geocoding.p.rapidapi.com"),
    "transit": os.environ.get("SC_NAVI_TRANSIT_HOST", "navitime-route-totalnavi.p.rapidapi.com"),
    "car": os.environ.get("SC_NAVI_CAR_HOST", "navitime-route-car.p.rapidapi.com"),
}
NAVITIME_PATHS = {"address": "/address", "transit": "/route_transit", "car": "/route_car"}
NET_TIMEOUT = 20
LOOKUP_MAX_QUERIES = 2
LOOKUP_RESULTS_PER_QUERY = 4

# 音声入力（faster-whisper。PCの中で文字起こしする）
VOICE_MODELS = {
    "large-v3-turbo": {"label": "精度優先（約1.6GB）", "size_mb": 1620},
    "small": {"label": "速さ優先（約480MB）", "size_mb": 485},
}
VOICE_DEVICE = os.environ.get("SC_VOICE_DEVICE", "cpu")          # GPUはLLMが使うので既定はCPU
VOICE_COMPUTE_TYPE = os.environ.get("SC_VOICE_COMPUTE", "int8")
VOICE_MAX_BYTES = 12 * 1024 * 1024
VOICE_MAX_SECONDS = 65
IDLE_MIN_SECONDS, IDLE_MAX_SECONDS = 30, 1800


def idle_seconds() -> int:
    """操作がないまま何秒で軽くするか（設定）。LLMと文字起こしのモデルはこの時間で外す。"""
    from . import db
    try:
        v = int(db.get_settings().get("idle_seconds") or 60)
    except (TypeError, ValueError):
        v = 60
    return max(IDLE_MIN_SECONDS, min(IDLE_MAX_SECONDS, v))
