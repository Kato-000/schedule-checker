"""音声入力：モデルの用意、文字起こしAPI、設定。モデル本体は偽物に差し替える。"""

import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app import config, voice


class FakeModel:
    def __init__(self, text="来週水曜15時から歯医者"):
        self.text = text
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append((len(audio), kw))
        return iter([SimpleNamespace(text=self.text)]), SimpleNamespace(language="ja")


@pytest.fixture()
def vfake(fake, monkeypatch):
    """モデルはダウンロード済み・音声は1.5秒の無音として扱う。"""
    m = FakeModel()
    d = voice.model_dir("large-v3-turbo")
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    monkeypatch.setattr(voice, "_load_model", lambda path: m)
    monkeypatch.setattr(voice, "_decode", lambda data: np.zeros(24000, dtype=np.float32))
    monkeypatch.setattr(voice, "available", lambda: True)
    voice.engine.unload()
    return m


def test_status_without_model(client, monkeypatch):
    monkeypatch.setattr(voice, "available", lambda: True)
    s = client.get("/api/voice").json()
    assert s["ready"] is False and s["model"] == "large-v3-turbo"
    assert {m["id"] for m in s["models"]} == {"large-v3-turbo", "small"}
    r = client.post("/api/voice/transcribe", content=b"abc", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 400 and "ダウンロード" in r.json()["detail"]


def test_transcribe_uses_recent_titles_as_hint(client, vfake, fake):
    from app import db
    with db.connect() as conn:
        conn.execute("INSERT INTO events(title, start_date) VALUES ('ヤマダ歯科', '2026-10-20')")
    r = client.post("/api/voice/transcribe", content=b"webm-bytes", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "来週水曜15時から歯医者" and body["seconds"] == 1.5
    kw = vfake.calls[0][1]
    assert kw["language"] == "ja" and kw["vad_filter"] is True
    assert "ヤマダ歯科" in kw["initial_prompt"]
    assert client.get("/api/voice").json()["loaded"] is True


def test_hallucination_on_silence_becomes_empty(client, vfake):
    vfake.text = "ご視聴ありがとうございました"
    r = client.post("/api/voice/transcribe", content=b"x")
    assert r.json()["text"] == ""
    vfake.text = "打ち合わせのお礼を送る。ありがとうございました"
    assert client.post("/api/voice/transcribe", content=b"x").json()["text"].startswith("打ち合わせ")


def test_too_long_and_empty(client, vfake, monkeypatch):
    assert client.post("/api/voice/transcribe", content=b"").status_code == 400
    monkeypatch.setattr(voice, "_decode", lambda data: np.zeros(16000 * 70, dtype=np.float32))
    r = client.post("/api/voice/transcribe", content=b"x")
    assert r.status_code == 400 and "長すぎ" in r.json()["detail"]
    monkeypatch.setattr(config, "VOICE_MAX_BYTES", 10)
    assert client.post("/api/voice/transcribe", content=b"x" * 20).status_code == 413


def test_broken_audio(client, vfake, monkeypatch):
    def bad(data):
        raise ValueError("bad")
    monkeypatch.setattr(voice, "_decode", bad)
    r = client.post("/api/voice/transcribe", content=b"x")
    assert r.status_code == 400 and "読み込めません" in r.json()["detail"]


def test_download_and_switch_model(client, fake, monkeypatch):
    monkeypatch.setattr(voice, "available", lambda: True)
    fetched = []
    gate = threading.Event()   # ダウンロード中の状態を確かめてから終わらせる

    def fetch(name, dest):
        fetched.append(name)
        gate.wait(5)
        (dest / ".cache").mkdir()
        (dest / "model.bin").write_bytes(b"m" * 10)
        (dest / "tokenizer.json").write_text("{}")
    monkeypatch.setattr(voice, "_fetch", fetch)
    r = client.post("/api/voice/download", json={"model": "small"})
    assert r.status_code == 200 and r.json()["downloading"] == "small"
    assert client.post("/api/voice/download", json={"model": "small"}).status_code == 400   # 二重には始めない
    gate.set()
    for _ in range(100):
        s = client.get("/api/voice").json()
        if not s["downloading"]:
            break
        time.sleep(0.02)
    assert fetched == ["small"] and s["error"] is None
    assert voice.is_downloaded("small") and not (voice.model_dir("small") / ".cache").exists()
    assert not voice.model_dir("small").with_name("whisper-small.part").exists()
    s = client.put("/api/voice", json={"model": "small"}).json()
    assert s["ready"] is True and s["model"] == "small"
    s = client.delete("/api/voice/models/small").json()
    assert s["ready"] is False


def test_download_failure_is_reported(client, fake, monkeypatch):
    monkeypatch.setattr(voice, "available", lambda: True)

    def fetch(name, dest):
        raise ConnectionError("offline")
    monkeypatch.setattr(voice, "_fetch", fetch)
    client.post("/api/voice/download", json={"model": "small"})
    for _ in range(100):
        s = client.get("/api/voice").json()
        if not s["downloading"]:
            break
        time.sleep(0.02)
    assert "ダウンロードできませんでした" in s["error"] and not voice.is_downloaded("small")


def test_voice_settings_only_from_pc(fake, monkeypatch):
    from fastapi.testclient import TestClient
    from app import security
    from app.main import app
    monkeypatch.setattr(security, "check_session", lambda t: True)
    with TestClient(app, client=("192.168.1.20", 50000)) as phone:
        assert phone.put("/api/voice", json={"model": "small"}).status_code == 403
        assert phone.post("/api/voice/download", json={"model": "small"}).status_code == 403
        assert phone.get("/api/voice").status_code == 200   # スマホでも使える（文字起こしはPCで行う）


def test_idle_unload(client, vfake, monkeypatch):
    monkeypatch.setattr(config, "idle_seconds", lambda: 0.05)
    client.post("/api/voice/transcribe", content=b"x")
    time.sleep(0.3)
    assert voice.engine.loaded is False


def test_settings_toggles(client):
    s = client.put("/api/settings", json={"widget_autohide": False}).json()
    assert s["widget_autohide"] == "0"


# ---- 本物の faster-whisper で、ブラウザの録音形式を読めるか（モデルは使わない） ----
needs_real = pytest.mark.skipif(not voice.available() or not shutil.which("ffmpeg"),
                                reason="faster-whisper または ffmpeg がない")


@needs_real
@pytest.mark.parametrize("ext,codec", [("webm", "libopus"), ("ogg", "libopus"), ("mp4", "aac")])
def test_real_decode_browser_formats(tmp_path, ext, codec):
    f = tmp_path / f"rec.{ext}"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-ac", "1", "-ar", "48000", "-c:a", codec, str(f)], check=True)
    audio = voice._decode(f.read_bytes())
    assert abs(len(audio) / 16000 - 2.0) < 0.15


def test_idle_seconds_setting_and_warm(client, vfake, fake, monkeypatch):
    from app import llm
    assert client.get("/api/meta").json()["idle_seconds"] == 60
    assert client.put("/api/settings", json={"idle_seconds": 10}).status_code == 400
    assert client.put("/api/settings", json={"idle_seconds": 120}).json()["idle_seconds"] == "120"
    assert config.idle_seconds() == 120
    # 先読みは裏で動き、すぐ返る
    assert client.post("/api/llm/warm").json() == {"ok": True}
    assert client.post("/api/voice/warm").json() == {"ok": True}
    for _ in range(50):
        if voice.engine.loaded and getattr(fake, "warmed", 0):
            break
        time.sleep(0.02)
    assert voice.engine.loaded and fake.warmed == 1


def test_llm_keep_alive_follows_idle(monkeypatch, fake):
    """本物の OllamaClient が送る keep_alive（設定の秒数）。"""
    from app import db, llm
    sent = []
    c = llm.OllamaClient()
    monkeypatch.setattr(c, "_post", lambda path, body, timeout: sent.append((path, body)) or {"message": {"content": "{}"}})
    db.set_setting("idle_seconds", "90")
    c.chat([{"role": "user", "content": "x"}], {"type": "object"})
    assert sent[-1][1]["keep_alive"] == "90s"
    assert c.warm() is True and sent[-1] == ("/api/generate", {"model": config.OLLAMA_MODEL, "keep_alive": "90s"})
    assert c.warm() is False   # 20秒以内は2回目を送らない
