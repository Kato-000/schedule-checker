// ウィジェットの自動たたみの動き（Tauri なしで、ウィンドウとマウスを偽物にして確かめる）
// 実行: node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAutoHide, detectEdge, tabRect } from '../src/lib/autohide.js';

function fakeWindow({ rect, area = { x: 0, y: 0, w: 1920, h: 1040 }, scale = 1.5 }) {
  const w = {
    r: { ...rect }, workArea: area, sf: scale, cursorPos: { x: 960, y: 500 }, minSize: 'config', moved: null, log: [],
    rect: async () => ({ ...w.r }),
    area: async () => w.workArea,
    scale: async () => w.sf,
    cursor: async () => w.cursorPos,
    setRect: async (r) => { w.r = { ...r }; w.log.push(r); },
    setMinSize: async (s) => { w.minSize = s; },
    onMoved: async (cb) => { w.moved = cb; return () => {}; },
  };
  return w;
}

function clock() {
  let t = 1000;
  return { now: () => t, add: (ms) => { t += ms; } };
}

async function run(ah, c, ms) {
  for (let i = 0; i < ms; i += 200) { c.add(200); await ah.tick(); }
}

test('どの端に寄せたか', () => {
  const a = { x: 0, y: 0, w: 1920, h: 1040 };
  assert.equal(detectEdge({ x: 5, y: 300, w: 480, h: 800 }, a, 21), 'left');
  assert.equal(detectEdge({ x: 1430, y: 300, w: 480, h: 800 }, a, 21), 'right');
  assert.equal(detectEdge({ x: 700, y: 10, w: 480, h: 800 }, a, 21), 'top');
  assert.equal(detectEdge({ x: 700, y: 100, w: 480, h: 800 }, a, 21), null);
  // 2台目の画面（左側にある）でも作業領域の座標で判断する
  assert.equal(detectEdge({ x: -1920, y: 100, w: 480, h: 800 }, { x: -1920, y: 0, w: 1920, h: 1040 }, 21), 'left');
});

test('右端に寄せる → マウスが離れるとつまみ → 乗せると元の大きさで開く', async () => {
  const c = clock();
  const w = fakeWindow({ rect: { x: 1430, y: 200, w: 480, h: 810 } });
  const events = [];
  const settled = [];
  const ah = createAutoHide(w, { interval: 0, now: c.now, onchange: (col, e) => events.push([col, e]), onsettle: (r) => settled.push(r) });
  await ah.start(true);
  assert.equal(ah.state.edge, 'right');
  assert.equal(w.r.x, 1920 - 480, '端にぴったり付ける');
  assert.deepEqual(settled.at(-1), { x: 1440, y: 200, w: 480, h: 810 });

  w.cursorPos = { x: 1600, y: 400 };   // ウィジェットの上
  await run(ah, c, 2000);
  assert.equal(ah.state.collapsed, false, 'マウスが乗っている間はたたまない');

  w.cursorPos = { x: 500, y: 400 };    // 離れる
  await run(ah, c, 600);
  assert.equal(ah.state.collapsed, false, 'すぐにはたたまない');
  await run(ah, c, 600);
  assert.equal(ah.state.collapsed, true);
  assert.equal(w.minSize, null);
  const tab = tabRect('right', { x: 1440, y: 200, w: 480, h: 810 }, w.workArea, 1.5);
  assert.deepEqual(w.r, tab);
  assert.equal(w.r.x + w.r.w, 1920, 'つまみは右端に付く');
  assert.equal(w.r.w, 66);

  assert.equal(ah.state.polling, false, 'たたんだら位置の確認を止める');
  // マウスが来ないまま起こされても、少しで止まる
  ah.wake();
  assert.equal(ah.state.polling, true);
  await run(ah, c, 1600);
  assert.equal(ah.state.polling, false);
  ah.wake();
  w.cursorPos = { x: w.r.x + 10, y: w.r.y + 10 };  // つまみに乗せる
  await run(ah, c, 400);
  assert.equal(ah.state.collapsed, false);
  assert.deepEqual(w.r, { x: 1440, y: 200, w: 480, h: 810 });
  assert.deepEqual(w.minSize, { w: 260, h: 64 });
  assert.deepEqual(events.map((e) => e[0]), [false, true, false]);
  ah.stop();
});

test('入力中・録音中はたたまない', async () => {
  const c = clock();
  let busy = true;
  const w = fakeWindow({ rect: { x: 0, y: 100, w: 480, h: 810 } });
  const ah = createAutoHide(w, { interval: 0, now: c.now, isBusy: () => busy });
  await ah.start(true);
  w.cursorPos = { x: 1500, y: 400 };
  await run(ah, c, 3000);
  assert.equal(ah.state.collapsed, false);
  busy = false;
  await run(ah, c, 1200);
  assert.equal(ah.state.collapsed, true);
  assert.equal(w.r.x, 0);
  ah.stop();
});

test('上の端はよこ長のつまみ。端から離すとたたまない。設定でOFFにすると開いて止まる', async () => {
  const c = clock();
  const w = fakeWindow({ rect: { x: 700, y: 4, w: 480, h: 810 } });
  const ah = createAutoHide(w, { interval: 0, now: c.now });
  await ah.start(true);
  assert.equal(ah.state.edge, 'top');
  w.cursorPos = { x: 100, y: 900 };
  await run(ah, c, 1200);
  assert.equal(ah.state.collapsed, true);
  assert.ok(w.r.w > w.r.h, 'よこ長');
  assert.equal(w.r.y, 0);

  await ah.setEnabled(false);
  assert.equal(ah.state.collapsed, false);
  assert.equal(ah.state.edge, null);
  assert.deepEqual(w.r, { x: 700, y: 0, w: 480, h: 810 });
  await run(ah, c, 3000);
  assert.equal(ah.state.collapsed, false, 'OFFの間はたたまない');
  ah.stop();
});

test('画面の中ほどに置いたときは何もしない', async () => {
  const c = clock();
  const w = fakeWindow({ rect: { x: 700, y: 120, w: 480, h: 810 } });
  const ah = createAutoHide(w, { interval: 0, now: c.now });
  await ah.start(true);
  w.cursorPos = { x: 10, y: 10 };
  await run(ah, c, 3000);
  assert.equal(ah.state.collapsed, false);
  assert.equal(w.log.length, 0, 'ウィンドウを動かさない');
  assert.equal(ah.state.polling, false, '端にないときは位置を確認しない');
  ah.stop();
});
