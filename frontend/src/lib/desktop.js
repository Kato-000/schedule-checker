// Tauri（デスクトップ）でだけ使う機能。ブラウザで開いたときは何もしないか、画面内で代用する。
export const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

/** メイン画面を開いて指定のタブを表示する */
export async function openMain(tab = 'today') {
  if (!isTauri) {
    location.hash = `#/main/${tab}`;
    return;
  }
  const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow');
  const { emitTo } = await import('@tauri-apps/api/event');
  const main = await WebviewWindow.getByLabel('main');
  if (!main) return;
  await main.show();
  await main.unminimize();
  await main.setFocus();
  await emitTo('main', 'navigate', tab);
}

/** 他の画面に「データが変わった」と知らせる（ウィジェットとメイン画面の表示をそろえる） */
export async function notifyChanged() {
  if (!isTauri) return;
  const { emit } = await import('@tauri-apps/api/event');
  await emit('data-changed');
}

export async function onChanged(cb) {
  if (!isTauri) return () => {};
  const { listen } = await import('@tauri-apps/api/event');
  return listen('data-changed', cb);
}

export async function onNavigate(cb) {
  if (!isTauri) return () => {};
  const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
  return getCurrentWebviewWindow().listen('navigate', (e) => cb(e.payload));
}

export async function hideCurrent() {
  if (!isTauri) return;
  const { getCurrentWindow } = await import('@tauri-apps/api/window');
  await getCurrentWindow().hide();
}

export async function setAlwaysOnTop(on) {
  if (!isTauri) return;
  const { getCurrentWindow } = await import('@tauri-apps/api/window');
  await getCurrentWindow().setAlwaysOnTop(on);
}

export async function setWidgetHeight(height) {
  if (!isTauri) return;
  const { getCurrentWindow, LogicalSize } = await import('@tauri-apps/api/window');
  const w = getCurrentWindow();
  const size = await w.innerSize();
  const scale = await w.scaleFactor();
  await w.setSize(new LogicalSize(size.width / scale, height));
}

/** ウィジェットの自動たたみ（lib/autohide.js）が使う、ウィンドウ操作 */
export async function widgetWindowOps() {
  const m = await import('@tauri-apps/api/window');
  const w = m.getCurrentWindow();
  return {
    async rect() {
      const [p, s] = await Promise.all([w.outerPosition(), w.outerSize()]);
      return { x: p.x, y: p.y, w: s.width, h: s.height };
    },
    async area() {
      const mon = (await m.currentMonitor()) ?? (await m.primaryMonitor());
      const wa = mon.workArea ?? { position: mon.position, size: mon.size };
      return { x: wa.position.x, y: wa.position.y, w: wa.size.width, h: wa.size.height };
    },
    scale: () => w.scaleFactor(),
    async cursor() {
      const p = await m.cursorPosition();
      return { x: p.x, y: p.y };
    },
    async setRect(r) {
      await w.setPosition(new m.PhysicalPosition(r.x, r.y));
      await w.setSize(new m.PhysicalSize(r.w, r.h));
    },
    setMinSize: (s) => w.setMinSize(s ? new m.LogicalSize(s.w, s.h) : null),
    onMoved: (cb) => w.onMoved(cb),
  };
}

const RECT_KEY = 'sc.widget.rect';

/** 前回の位置に戻す（その画面が今もつながっているときだけ）。保存先はこのアプリの中だけ */
export async function restoreWidgetRect() {
  if (!isTauri) return;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(RECT_KEY) ?? 'null'); } catch { /* 保存なし */ }
  if (!saved || !Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return;
  const m = await import('@tauri-apps/api/window');
  const mons = await m.availableMonitors();
  const cx = saved.x + 20, cy = saved.y + 20;
  const ok = mons.some((mo) => {
    const a = mo.workArea ?? { position: mo.position, size: mo.size };
    return cx >= a.position.x && cx < a.position.x + a.size.width && cy >= a.position.y && cy < a.position.y + a.size.height;
  });
  if (!ok) return;
  // 大きさは戻さない（たたんだ状態で保存されていることがあるため）
  await m.getCurrentWindow().setPosition(new m.PhysicalPosition(saved.x, saved.y));
}

export function saveWidgetRect(r) {
  try { localStorage.setItem(RECT_KEY, JSON.stringify(r)); } catch { /* 保存できなくても動作は続ける */ }
}

/** 外のページ（Googleマップ・検索結果など）をいつものブラウザで開く。
 *  PCのアプリの画面の中では開けないので、PCのバックエンドに開いてもらう。ブラウザ（スマホ）ではそのまま新しいタブで */
export async function openExternal(url) {
  if (isTauri) {
    const { api } = await import('./api.js');
    await api.openUrl(url);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}
