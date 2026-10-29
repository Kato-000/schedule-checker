"""Ollama（localhost）との通信。通信先は自分のPCだけ。"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class OllamaClient:
    """GPUは1つなので、呼び出しはロックで1件ずつ流す。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._warmed_at = -1e9

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            config.OLLAMA_URL + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, messages: list[dict], schema: dict) -> tuple[dict, float]:
        """JSONスキーマで出力を固定して呼び出し、(解析済みJSON, 秒数) を返す。"""
        body = {"model": config.OLLAMA_MODEL, "messages": messages, "format": schema,
                "think": False, "stream": False,
                # 使い終わったら設定の秒数（初期1分）でGPUから外す。ずっと載せたままにしない
                "keep_alive": f"{config.idle_seconds()}s",
                "options": {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX}}
        with self._lock:
            t0 = time.perf_counter()
            try:
                res = self._post("/api/chat", body, config.OLLAMA_TIMEOUT)
            except (urllib.error.URLError, OSError) as e:
                raise LLMError(f"Ollamaに接続できません（{e}）。Ollamaが起動しているか確認してください。") from e
            sec = time.perf_counter() - t0
        raw = res.get("message", {}).get("content", "")
        try:
            return json.loads(raw), sec
        except json.JSONDecodeError as e:
            raise LLMError(f"LLMの出力をJSONとして読めませんでした: {raw[:200]}") from e

    def warm(self) -> bool:
        """入力を始めたときに、先にモデルを読み込んでおく（待ち時間を短くする）。
        使わなければ設定の秒数で自動的に外れる。"""
        now = time.monotonic()
        if now - self._warmed_at < 20:
            return False
        self._warmed_at = now
        try:
            self._post("/api/generate", {"model": config.OLLAMA_MODEL, "keep_alive": f"{config.idle_seconds()}s"}, 120)
            return True
        except (urllib.error.URLError, OSError) as e:
            log.info("モデルの先読みに失敗: %s", e)
            return False

    def loaded(self) -> bool | None:
        """モデルが今GPUに載っているか（/api/ps）。分からなければ None。"""
        try:
            with urllib.request.urlopen(config.OLLAMA_URL + "/api/ps", timeout=3) as resp:
                names = [m.get("name", "").lower() for m in json.loads(resp.read()).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return None
        want = config.OLLAMA_MODEL.lower()
        return any(n in (want, want + ":latest") for n in names)

    def status(self) -> dict:
        try:
            req = urllib.request.Request(config.OLLAMA_URL + "/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                names = [m.get("name", "") for m in json.loads(resp.read()).get("models", [])]
        except (urllib.error.URLError, OSError):
            return {"ok": False, "message": "Ollamaに接続できません"}
        want = config.OLLAMA_MODEL.lower()
        if not any(n.lower() in (want, want + ":latest") for n in names):
            return {"ok": False, "message": f"モデル {config.OLLAMA_MODEL} が見つかりません（ollama pull が必要）"}
        loaded = self.loaded()
        return {"ok": True, "loaded": loaded,
                "message": f"{config.OLLAMA_MODEL}（{'読み込み済み' if loaded else '待機中'}）" if loaded is not None
                else f"{config.OLLAMA_MODEL} を使用中"}


# テストではこれを偽物に差し替える
client = OllamaClient()
