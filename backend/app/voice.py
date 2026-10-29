"""音声入力の文字起こし（faster-whisper）。録音の受け取りから文字にするまで、すべてこのPCの中で行う。

- モデルは最初に1回だけダウンロードする（設定画面のボタン）。中身は公開されている音声認識モデルで、
  こちらから送るものはない。ダウンロード後は local_files_only で読み込み、通信しない
- GPUはLLM（Ollama）が使うので、既定はCPUで動かす
- 録音はメモリ上で文字にして、ファイルには残さない
- しばらく使わなければメモリから外す
"""

from __future__ import annotations

import io
import logging
import shutil
import threading
import time
from pathlib import Path

from . import config, db

log = logging.getLogger(__name__)

PROMPT_BASE = "予定の入力です。例：来週の水曜日15時から歯医者。金曜までに見積もりを提出。"
# 無音や雑音のときにWhisperが作りがちな決まり文句（これだけなら「聞き取れなかった」とする）
HALLUCINATIONS = ("ご視聴ありがとうございました", "チャンネル登録", "ありがとうございました",
                  "おやすみなさい", "字幕", "はい。", "では、また")


class VoiceError(RuntimeError):
    pass


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def model_name() -> str:
    m = db.get_settings().get("voice_model") or "large-v3-turbo"
    return m if m in config.VOICE_MODELS else "large-v3-turbo"


def model_dir(name: str) -> Path:
    return config.DATA_DIR / "models" / f"whisper-{name}"


def is_downloaded(name: str) -> bool:
    return (model_dir(name) / "model.bin").is_file()


def _dir_mb(p: Path) -> int:
    if not p.exists():
        return 0
    return int(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1024 / 1024)


# ---------------------------------------------------------------------------
# モデルのダウンロード
# ---------------------------------------------------------------------------
class _Download:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.error: str | None = None


_dl = _Download()


def _fetch(name: str, dest: Path) -> None:
    """公開モデルを dest に置く（テストでは差し替える）。"""
    from faster_whisper.utils import download_model
    download_model(name, output_dir=str(dest))


def _download_worker(name: str) -> None:
    final = model_dir(name)
    part = final.with_name(final.name + ".part")
    try:
        part.mkdir(parents=True, exist_ok=True)
        _fetch(name, part)
        if not (part / "model.bin").is_file():
            raise VoiceError("ダウンロードしたファイルが足りません")
        shutil.rmtree(part / ".cache", ignore_errors=True)
        if final.exists():
            shutil.rmtree(final)
        part.rename(final)
        log.info("文字起こしモデル %s を用意しました", name)
    except Exception as e:  # noqa: BLE001
        log.exception("モデルのダウンロードに失敗しました")
        _dl.error = f"ダウンロードできませんでした（{type(e).__name__}）。ネットにつながっているか確認して、もう一度お試しください"
    finally:
        with _dl.lock:
            _dl.name = None


def start_download(name: str) -> None:
    if name not in config.VOICE_MODELS:
        raise VoiceError("そのモデルは選べません")
    if not available():
        raise VoiceError("音声入力の部品が入っていません。setup_backend.bat を実行し直してください")
    with _dl.lock:
        if _dl.name:
            raise VoiceError("ダウンロード中です")
        _dl.name = name
        _dl.error = None
    threading.Thread(target=_download_worker, args=(name,), daemon=True).start()


def delete_model(name: str) -> None:
    if name not in config.VOICE_MODELS:
        raise VoiceError("そのモデルは選べません")
    with _dl.lock:
        if _dl.name == name:
            raise VoiceError("ダウンロード中です")
    engine.unload()
    shutil.rmtree(model_dir(name), ignore_errors=True)


# ---------------------------------------------------------------------------
# 文字起こし
# ---------------------------------------------------------------------------
def _load_model(path: Path):
    from faster_whisper import WhisperModel
    return WhisperModel(str(path), device=config.VOICE_DEVICE, compute_type=config.VOICE_COMPUTE_TYPE,
                        local_files_only=True)


def _decode(data: bytes):
    """ブラウザの録音（webm/opus、iPhoneはmp4/aac）を16kHz・モノラルの波形にする。
    faster-whisper 付属の decode_audio は新しい av（PyAV 16以降）で動かないので、av を直接使う。"""
    import av
    import numpy as np

    chunks = []
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    with av.open(io.BytesIO(data), mode="r") as container:
        if not container.streams.audio:
            raise VoiceError("録音に音声が入っていません")
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class Engine:
    def __init__(self) -> None:
        self.lock = threading.Lock()   # CPUを食うので1件ずつ
        self.model = None
        self.name: str | None = None
        self.last_used = 0.0
        self._timer: threading.Timer | None = None

    def _get(self, name: str):
        if self.model is None or self.name != name:
            self.model = None
            log.info("文字起こしモデル %s を読み込みます", name)
            self.model = _load_model(model_dir(name))
            self.name = name
        return self.model

    def _schedule_unload(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(config.idle_seconds(), self._idle_unload)
        self._timer.daemon = True
        self._timer.start()

    def _idle_unload(self) -> None:
        with self.lock:
            if time.time() - self.last_used >= config.idle_seconds() - 1:
                self.model = None
                self.name = None
                log.info("文字起こしモデルをメモリから外しました")

    def unload(self) -> None:
        with self.lock:
            self.model = None
            self.name = None

    def warm(self) -> bool:
        """録音を始めたときに、話している間に読み込んでおく。使わなければ設定の秒数で外す。"""
        name = model_name()
        if not available() or not is_downloaded(name):
            return False
        with self.lock:
            self._get(name)
            self.last_used = time.time()
        self._schedule_unload()
        return True

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def transcribe(self, data: bytes) -> dict:
        name = model_name()
        if not is_downloaded(name):
            raise VoiceError("文字起こしのモデルがまだありません。設定の「音声入力」でダウンロードしてください")
        if not data:
            raise VoiceError("録音が空です")
        if len(data) > config.VOICE_MAX_BYTES:
            raise VoiceError("録音が長すぎます（1分まで）")
        try:
            audio = _decode(data)
        except Exception as e:  # noqa: BLE001
            raise VoiceError("録音を読み込めませんでした") from e
        seconds = len(audio) / 16000
        if seconds > config.VOICE_MAX_SECONDS:
            raise VoiceError("録音が長すぎます（1分まで）")
        if seconds < 0.3:
            raise VoiceError("録音が短すぎます")
        started = time.time()
        with self.lock:
            model = self._get(name)
            segments, _info = model.transcribe(
                audio, language="ja", task="transcribe", beam_size=5,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False, initial_prompt=build_prompt(),
                without_timestamps=True)
            text = "".join(s.text for s in segments).strip()
            self.last_used = time.time()
        self._schedule_unload()
        text = clean(text)
        return {"text": text, "seconds": round(seconds, 1), "elapsed": round(time.time() - started, 1)}


engine = Engine()


def build_prompt() -> str:
    """最近の予定の名前を手がかりに渡す（固有名詞の聞き取りがよくなる）。"""
    with db.connect() as conn:
        rs = conn.execute("SELECT title FROM events ORDER BY id DESC LIMIT 60").fetchall()
    words: list[str] = []
    for r in rs:
        t = (r["title"] or "").strip()
        if t and t not in words and len(t) <= 20:
            words.append(t)
    prompt = PROMPT_BASE
    for w in words:
        if len(prompt) + len(w) + 1 > 200:
            break
        prompt += w + "。"
    return prompt


def clean(text: str) -> str:
    t = text.strip().strip("「」 　")
    bare = t.rstrip("。.！!")
    if not bare or any(bare == h.rstrip("。") or (h in bare and len(bare) <= len(h) + 4) for h in HALLUCINATIONS):
        return ""
    return t


def status() -> dict:
    name = model_name()
    downloading = _dl.name
    return {
        "available": available(),
        "model": name,
        "models": [{"id": k, "label": v["label"], "size_mb": v["size_mb"], "downloaded": is_downloaded(k)}
                   for k, v in config.VOICE_MODELS.items()],
        "ready": available() and is_downloaded(name),
        "downloading": downloading,
        "progress_mb": _dir_mb(model_dir(downloading).with_name(f"whisper-{downloading}.part")) if downloading else 0,
        "error": _dl.error,
        "loaded": engine.loaded,
        "device": config.VOICE_DEVICE,
    }
