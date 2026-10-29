// ウィジェットを画面の端に寄せたとき、使っていない間は小さなつまみにたたむ。
// ウィンドウの操作は win（下の形のオブジェクト）を通して行うので、Tauri なしでも動きを確かめられる。
//
// win = {
//   rect():     Promise<{x,y,w,h}>   今のウィンドウの位置と大きさ（物理ピクセル）
//   area():     Promise<{x,y,w,h}>   ウィンドウがある画面の作業領域（タスクバーを除く）
//   scale():    Promise<number>      拡大率
//   cursor():   Promise<{x,y}>       マウスの位置（画面座標）
//   setRect(r): Promise<void>        位置と大きさを変える
//   setMinSize(size|null): Promise<void>  最小サイズ（論理ピクセル）
//   onMoved(cb): Promise<unlisten>   ウィンドウが動いたとき
// }

export const SNAP = 14;              // 端からこの距離（論理px）以内なら「寄せた」とみなす
export const TAB_V = { w: 44, h: 104 };   // 左右の端のつまみ（論理px）
export const TAB_H = { w: 168, h: 38 };   // 上の端のつまみ
export const MIN_SIZE = { w: 260, h: 64 };
const OPEN_DELAY = 120;     // つまみにマウスを乗せてから開くまで
const CLOSE_DELAY = 900;    // ウィジェットからマウスが離れてからたたむまで
const TICK = 250;
const WAKE_LINGER = 1500;   // たたんだ状態で起こされたあと、マウスが来なければこの時間で確認をやめる

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** どの端に寄せているか（'left' | 'right' | 'top' | null） */
export function detectEdge(r, a, snap) {
  if (Math.abs(r.x - a.x) <= snap) return 'left';
  if (Math.abs(r.x + r.w - (a.x + a.w)) <= snap) return 'right';
  if (Math.abs(r.y - a.y) <= snap) return 'top';
  return null;
}

/** 端にぴったり付けた位置 */
export function snapRect(edge, r, a) {
  const y = clamp(r.y, a.y, a.y + a.h - r.h);
  const x = clamp(r.x, a.x, a.x + a.w - r.w);
  if (edge === 'left') return { ...r, x: a.x, y };
  if (edge === 'right') return { ...r, x: a.x + a.w - r.w, y };
  if (edge === 'top') return { ...r, x, y: a.y };
  return r;
}

/** たたんだときのつまみの位置と大きさ */
export function tabRect(edge, r, a, scale) {
  if (edge === 'top') {
    const w = Math.round(TAB_H.w * scale), h = Math.round(TAB_H.h * scale);
    return { x: clamp(Math.round(r.x + (r.w - w) / 2), a.x, a.x + a.w - w), y: a.y, w, h };
  }
  const w = Math.round(TAB_V.w * scale), h = Math.round(TAB_V.h * scale);
  const y = clamp(r.y, a.y, a.y + a.h - h);
  return { x: edge === 'left' ? a.x : a.x + a.w - w, y, w, h };
}

const inside = (p, r, pad = 2) => p.x >= r.x - pad && p.x < r.x + r.w + pad && p.y >= r.y - pad && p.y < r.y + r.h + pad;

/**
 * @param {object} win  上の形のウィンドウ操作
 * @param {{ isBusy?: () => boolean, onchange?: (collapsed: boolean, edge: string|null) => void,
 *          onsettle?: (rect) => void, now?: () => number }} opts
 *   onsettle: 動かし終わった位置（次回の起動で元の場所に出すため）
 */
export function createAutoHide(win, { isBusy = () => false, onchange = () => {}, onsettle = () => {}, now = () => Date.now(), interval = TICK } = {}) {
  const st = {
    enabled: false, edge: null, collapsed: false, saved: null,
    ignoreMovesUntil: 0, insideSince: 0, outsideSince: 0, moveTimer: 0, timer: 0, unlisten: () => {}, working: false,
    polling: false, wokeAt: 0,
  };

  // マウス位置の確認（ポーリング）は必要なときだけ動かす:
  //  - 端に寄せて開いているとき（離れたらたたむため）
  //  - たたんだつまみにマウスが来たとき（wake から少しの間だけ）
  // 端に寄せていない・たたんでいて触られていないときは止めて、何もしない
  function setPolling(on) {
    if (on === st.polling) return;
    st.polling = on;
    if (!interval) return;          // テストでは手で tick を呼ぶ
    if (on) st.timer = setInterval(tick, interval);
    else clearInterval(st.timer);
  }
  const wantPolling = () => st.enabled && !!st.edge && !st.collapsed;

  async function updateEdge() {
    if (st.collapsed) return;
    const [r, a, s] = await Promise.all([win.rect(), win.area(), win.scale()]);
    const edge = st.enabled ? detectEdge(r, a, SNAP * s) : null;
    st.edge = edge;
    onchange(false, edge);
    let final = r;
    if (edge) {
      final = snapRect(edge, r, a);
      if (final.x !== r.x || final.y !== r.y) {
        st.ignoreMovesUntil = now() + 500;
        await win.setRect(final);
      }
    }
    onsettle(final);
    setPolling(wantPolling());
  }

  async function collapse() {
    const [r, a, s] = await Promise.all([win.rect(), win.area(), win.scale()]);
    st.saved = r;
    st.collapsed = true;
    st.ignoreMovesUntil = now() + 600;
    onchange(true, st.edge);           // 先につまみの表示にしてから小さくする
    await win.setMinSize(null);
    await win.setRect(tabRect(st.edge, r, a, s));
    setPolling(false);                 // たたんだら確認を止める（つまみに触れると wake で再開）
  }

  async function expand() {
    const a = await win.area();
    const r = snapRect(st.edge, st.saved, a);
    st.collapsed = false;
    st.ignoreMovesUntil = now() + 600;
    await win.setRect(r);
    await win.setMinSize(MIN_SIZE);
    onchange(false, st.edge);
    setPolling(wantPolling());
  }

  async function tick() {
    if (st.working || !st.enabled || !st.edge) return;
    st.working = true;
    try {
      const [p, r] = await Promise.all([win.cursor(), win.rect()]);
      const t = now();
      if (inside(p, r)) {
        st.outsideSince = 0;
        if (st.collapsed) {
          st.insideSince ||= t;
          if (t - st.insideSince >= OPEN_DELAY) { st.insideSince = 0; await expand(); }
        }
      } else {
        st.insideSince = 0;
        if (st.collapsed) {
          // 起こされたがマウスが来ない → 確認をやめる
          if (t - st.wokeAt >= WAKE_LINGER) setPolling(false);
        } else {
          if (isBusy()) { st.outsideSince = 0; return; }
          st.outsideSince ||= t;
          if (t - st.outsideSince >= CLOSE_DELAY) { st.outsideSince = 0; await collapse(); }
        }
      }
    } catch {
      /* 一時的な失敗は次の回にまかせる */
    } finally {
      st.working = false;
    }
  }

  return {
    get state() { return { enabled: st.enabled, edge: st.edge, collapsed: st.collapsed, polling: st.polling }; },
    tick,
    async start(enabled) {
      st.enabled = enabled;
      st.unlisten = await win.onMoved(() => {
        if (now() < st.ignoreMovesUntil) return;
        clearTimeout(st.moveTimer);
        st.moveTimer = setTimeout(() => { updateEdge().catch(() => {}); }, 400);  // 動かし終わってから判断
      });
      await updateEdge();
    },
    /** ウィジェットの画面にマウスが来たとき（たたんだつまみに触れたときなど）に呼ぶ */
    wake() {
      if (!st.enabled || !st.edge) return;
      st.wokeAt = now();
      setPolling(true);
    },
    async setEnabled(on) {
      st.enabled = on;
      if (!on && st.collapsed) await expand();
      await updateEdge();
    },
    /** 端以外の操作（ボタンなど）で今すぐ開く */
    async open() { if (st.collapsed) await expand(); },
    stop() {
      setPolling(false);
      clearInterval(st.timer);
      clearTimeout(st.moveTimer);
      st.unlisten();
    },
  };
}
