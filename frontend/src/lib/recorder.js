// マイクで録音する。話し終わって少し黙ると自動で止まる。
// 録音はブラウザのメモリにだけ置き、PCのバックエンドへ送って文字にする（外部には送らない）。

const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm'];

export const MAX_SECONDS = 60;
const SPEECH_RMS = 0.03;        // これより大きい音を「話している」とみなす（実効値）
const END_SILENCE_MS = 1600;    // 話したあと、これだけ黙ったら止める
const NO_SPEECH_MS = 8000;      // 話し始めないまま、これだけたったらやめる

export function recordingSupported() {
  return typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
}

function friendlyError(e) {
  const name = e?.name ?? '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'マイクの使用が許可されていません。ブラウザやWindowsの設定（プライバシー > マイク）を確認してください';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'マイクが見つかりません';
  if (name === 'NotReadableError') return 'マイクを使えません（ほかのアプリが使っている可能性があります）';
  return `録音を始められませんでした（${name || e?.message || '不明'}）`;
}

/**
 * 録音を始める。
 * @param {{ onlevel?: (level:number, seconds:number, speaking:boolean) => void }} opts
 * @returns {Promise<{ done: Promise<Blob|null>, stop: () => void, cancel: () => void }>}
 *   done は録音（話さなかった・キャンセルしたときは null）
 */
export async function startRecording({ onlevel = () => {} } = {}) {
  if (!recordingSupported()) {
    throw new Error(window.isSecureContext === false
      ? 'このページではマイクを使えません（HTTPSで開いてください）'
      : 'このブラウザは録音に対応していません');
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) {
    throw new Error(friendlyError(e));
  }

  const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported?.(t));
  const rec = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 64000 } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };

  // 音の大きさを見て、話し終わりを判断する
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  const started = performance.now();
  let spoke = false;
  let speechMs = 0;
  let lastLoud = started;
  let lastTick = started;
  let cancelled = false;
  let timer = 0;
  let finished = false;

  const done = new Promise((resolve) => {
    rec.onstop = () => {
      cleanup();
      if (cancelled || !spoke || !chunks.length) resolve(null);
      else resolve(new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' }));
    };
  });

  function cleanup() {
    clearInterval(timer);
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  }

  function stop() {
    if (finished) return;
    finished = true;
    if (rec.state !== 'inactive') rec.stop();
  }

  function tick() {
    const now = performance.now();
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const level = Math.min(1, rms * 5);   // 表示用
    const loud = rms > SPEECH_RMS;
    if (loud) {
      speechMs += now - lastTick;
      if (speechMs > 250) spoke = true;
      lastLoud = now;
    }
    lastTick = now;
    const seconds = (now - started) / 1000;
    onlevel(level, seconds, loud);
    if (seconds >= MAX_SECONDS) return stop();
    if (spoke && now - lastLoud > END_SILENCE_MS) return stop();
    if (!spoke && now - started > NO_SPEECH_MS) return stop();
  }

  rec.start(250);
  timer = setInterval(tick, 50);   // 画面が裏にあっても止まらないよう、描画のタイミングには頼らない
  return {
    done,
    // 手で止めたときは、0.5秒以上録っていれば送る（無音ならPC側で「聞き取れなかった」になる）
    stop: () => { if (performance.now() - started > 500) spoke = true; stop(); },
    cancel: () => { cancelled = true; stop(); },
  };
}
