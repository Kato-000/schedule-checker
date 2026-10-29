// 操作の有無を見て、使っていない間は画面の定期更新を止める。
// - マウス・キー・タッチ・ホイール・画面の表示があれば「操作中」
// - 最後の操作から idleMs（初期 1 分）たつか、画面が隠れたら「待機中」
// - 待機中は whileActive で登録した定期処理を止め、操作が戻ったらすぐ1回実行して再開する
// 判定はタイマー1つだけで行い、待機中に何かを繰り返し動かすことはしない。

let idleMs = 60_000;
let last = Date.now();
let idle = false;
let idleTimer = 0;
const listeners = new Set();

function hidden() {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

function setIdle(v) {
  if (v === idle) return;
  idle = v;
  for (const cb of listeners) {
    try { cb(idle); } catch { /* 一つの失敗で止めない */ }
  }
}

function armTimer() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => setIdle(true), idleMs);
}

export function markActive() {
  last = Date.now();
  if (hidden()) return;
  setIdle(false);
  armTimer();
}

let lastMove = 0;
function onMove() {
  const t = Date.now();
  if (t - lastMove < 1000 && !idle) return;   // マウス移動は1秒に1回だけ数える
  lastMove = t;
  markActive();
}

if (typeof window !== 'undefined') {
  for (const ev of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'focus']) {
    window.addEventListener(ev, markActive, { passive: true, capture: true });
  }
  window.addEventListener('pointermove', onMove, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => {
    if (hidden()) { clearTimeout(idleTimer); setIdle(true); } else markActive();
  });
  armTimer();
}

export function isIdle() {
  return idle;
}

/** 待機に入るまでの時間（秒）。設定から変える */
export function setIdleSeconds(sec) {
  const ms = Math.max(15, Number(sec) || 60) * 1000;
  if (ms === idleMs) return;
  idleMs = ms;
  if (!idle) armTimer();
}

/** 操作中・待機中が切り替わったとき cb(idle) を呼ぶ。戻り値で解除 */
export function onIdleChange(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/**
 * 操作中だけ fn を ms ごとに実行する。待機から戻ったときはすぐ1回実行する。
 * @returns {() => void} 止める関数
 */
export function whileActive(fn, ms) {
  let timer = 0;
  const startTimer = () => { clearInterval(timer); timer = setInterval(() => { if (!idle) fn(); }, ms); };
  const off = onIdleChange((nowIdle) => {
    if (nowIdle) clearInterval(timer);
    else { fn(); startTimer(); }
  });
  if (!idle) startTimer();
  return () => { clearInterval(timer); off(); };
}
