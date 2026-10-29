<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { isTauri, onChanged, openMain, setAlwaysOnTop, setWidgetHeight, hideCurrent,
    widgetWindowOps, restoreWidgetRect, saveWidgetRect } from '../lib/desktop.js';
  import { createAutoHide } from '../lib/autohide.js';
  import { whileActive, onIdleChange, setIdleSeconds } from '../lib/activity.js';
  import { WEEKDAYS, parseISO } from '../lib/format.js';
  import TodoItem from './TodoItem.svelte';
  import QuickInput from './QuickInput.svelte';

  let view = $state(null);
  let error = $state('');
  let pinned = $state(true);
  let folded = $state(false);
  let showWeek = $state(false);
  let showNoDue = $state(false);
  // 画面端での自動たたみ
  let collapsed = $state(false);
  let edge = $state(null);
  let autohide = null;
  // ブラウザで見た目を確かめる用（#/widget?dock=right など）
  const preview = !isTauri && /dock=(left|right|top)/.exec(location.hash)?.[1];
  if (preview) { collapsed = true; edge = preview; }

  const date = $derived(view ? parseISO(view.date) : null);
  const urgent = $derived(view ? [...view.overdue, ...view.due_today] : []);

  async function load() {
    try {
      view = await api.today();
      error = '';
    } catch (e) {
      error = e.message;
    }
  }

  // 入力中・録音中は、マウスが離れてもたたまない
  function isBusy() {
    const a = document.activeElement;
    if (document.hasFocus() && a && ['INPUT', 'TEXTAREA', 'SELECT'].includes(a.tagName)) return true;
    return !!document.querySelector('.mic[aria-pressed="true"], .voice-status');
  }

  async function setupAutohide() {
    try {
      await restoreWidgetRect();
      const s = await api.settings().catch(() => ({ widget_autohide: '1' }));
      setIdleSeconds(s.idle_seconds);
      autohide = createAutoHide(await widgetWindowOps(), {
        isBusy,
        onchange: (c, e) => { collapsed = c; edge = e; },
        onsettle: saveWidgetRect,
      });
      await autohide.start(s.widget_autohide === '1');
    } catch (e) {
      console.warn('自動たたみを使えません', e);
    }
  }

  async function reloadSettings() {
    if (!autohide) return;
    try {
      const s = await api.settings();
      await autohide.setEnabled(s.widget_autohide === '1');
    } catch { /* 次の機会に */ }
  }

  onMount(() => {
    // 角丸の外側を透明にする（Tauri の透明ウィンドウ用）
    document.documentElement.style.background = 'transparent';
    document.body.classList.add('widget-body');
    load();
    // 操作中だけ30秒ごとに読み直す。使っていない間は止め、マウスが来たらすぐ読み直す
    const stopPoll = whileActive(load, 30000);
    // 日付が変わったら、待機中でも1回だけ読み直す（タイマー1つ）
    let midnight = 0;
    const armMidnight = () => {
      const n = new Date();
      const next = new Date(n.getFullYear(), n.getMonth(), n.getDate() + 1, 0, 0, 5);
      midnight = setTimeout(() => { load(); armMidnight(); }, next - n);
    };
    armMidnight();
    // たたんだつまみにマウスが来たら、位置の確認を再開する
    const wake = () => autohide?.wake();
    document.addEventListener('pointerover', wake);
    document.addEventListener('pointermove', wake, { passive: true });
    let unlisten = () => {};
    onChanged(() => { load(); reloadSettings(); }).then((u) => (unlisten = u));
    if (isTauri) setupAutohide();
    return () => {
      stopPoll(); clearTimeout(midnight); unlisten(); autohide?.stop();
      document.removeEventListener('pointerover', wake);
      document.removeEventListener('pointermove', wake);
    };
  });

  async function togglePin() {
    pinned = !pinned;
    await setAlwaysOnTop(pinned);
  }

  async function toggleFold() {
    folded = !folded;
    await setWidgetHeight(folded ? 64 : 540);
  }
</script>

{#if collapsed}
  <!-- 画面端のつまみ。マウスを乗せると開く -->
  <button class="tab tab-{edge}" onclick={() => autohide?.open()} aria-label="ウィジェットを開く"
    title="マウスを乗せると開きます">
    {#if date}
      {#if edge === 'top'}
        <span class="t-day num">{date.getDate()}<small>日（{WEEKDAYS[date.getDay()]}）</small></span>
        <span class="t-count" class:zero={!urgent.length}>Todo <b class="num">{urgent.length}</b></span>
        {#if view?.pending_count}<span class="t-pending" title="承認待ち">承認 <b class="num">{view.pending_count}</b></span>{/if}
      {:else}
        <span class="t-day num">{date.getDate()}</span>
        <span class="t-wd">{WEEKDAYS[date.getDay()]}</span>
        {#if urgent.length}
          <span class="t-count" title="今日までのTodo"><b class="num">{urgent.length}</b></span>
        {:else}
          <span class="t-none" title="今日までのTodoはありません">✓</span>
        {/if}
        {#if view?.pending_count}<span class="t-dot" title="承認待ちがあります"></span>{/if}
      {/if}
    {:else}
      <span class="t-day">…</span>
    {/if}
  </button>
{:else}
<div class="widget grid-paper" class:folded>
  <header data-tauri-drag-region>
    {#if date}
      <div class="day" data-tauri-drag-region>
        <span class="d num" data-tauri-drag-region>{date.getDate()}</span>
        <span class="wd" data-tauri-drag-region>
          <span class="w">{WEEKDAYS[date.getDay()]}曜日</span>
          <span class="m faint num">{date.getFullYear()}年{date.getMonth() + 1}月</span>
        </span>
      </div>
    {/if}
    <div class="actions">
      {#if view?.pending_count}
        <button class="badge" onclick={() => openMain('approvals')} title="承認待ちを開く">
          承認待ち <span class="num">{view.pending_count}</span>
        </button>
      {/if}
      <button class="plain icon" onclick={() => openMain('today')} title="メイン画面を開く" aria-label="メイン画面を開く">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M9 2.5h4.5V7M13.5 2.5 8 8M6.5 3.5h-4v10h10v-4" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>
      </button>
      {#if isTauri}
        <button class="plain icon" class:on={pinned} onclick={togglePin} title={pinned ? '最前面をやめる' : '最前面に固定'} aria-label="最前面の切り替え" aria-pressed={pinned}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 1.5h4l-.7 4 2.7 2.5H4L6.7 5.5zM8 8v6.5" fill={pinned ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.2"/></svg>
        </button>
        <button class="plain icon" onclick={toggleFold} title={folded ? '広げる' : 'たたむ'} aria-label={folded ? '広げる' : 'たたむ'}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d={folded ? 'M3 6l5 5 5-5' : 'M3 10l5-5 5 5'} fill="none" stroke="currentColor" stroke-width="1.4"/></svg>
        </button>
        <button class="plain icon" onclick={hideCurrent} title="隠す（タスクトレイから再表示）" aria-label="隠す">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>
        </button>
      {/if}
    </div>
  </header>

  {#if !folded}
    <div class="body">
      {#if error}
        <p class="error-text note">{error}</p>
      {:else if view}
        <section>
          <h2>今日の予定</h2>
          {#if view.events.length}
            <ul class="events">
              {#each view.events as e (e.id)}
                <li>
                  <button class="event" onclick={() => openMain('week')}>
                    <span class="time num">{e.start_time ?? (e.is_deadline ? '締切' : '終日')}</span>
                    <span class="title">{e.title}</span>
                    {#if e.travel}<span class="leave num" title="家を出る時刻">{e.travel.depart_at.slice(11, 16)}発</span>{/if}
                  </button>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="faint note">予定はありません</p>
          {/if}
        </section>

        <section>
          <h2>今日までにやること</h2>
          {#if urgent.length}
            <ul class="todos">
              {#each urgent as t (t.id)}
                <TodoItem todo={t} today={view.date} onchange={load} compact showEvent={false} />
              {/each}
            </ul>
          {:else}
            <p class="faint note">今日が期限のTodoはありません</p>
          {/if}
          {#if view.done_today.length}
            <p class="faint note done">今日 {view.done_today.length} 件完了</p>
          {/if}
        </section>

        {#if view.this_week.length}
          <section>
            <button class="plain more" onclick={() => (showWeek = !showWeek)} aria-expanded={showWeek}>
              今週中のTodo <span class="num">{view.this_week.length}</span> 件 {showWeek ? 'を閉じる' : 'を見る'}
            </button>
            {#if showWeek}
              <ul class="todos">
                {#each view.this_week as t (t.id)}
                  <TodoItem todo={t} today={view.date} onchange={load} compact showEvent={false} />
                {/each}
              </ul>
            {/if}
          </section>
        {/if}
        {#if view.no_due?.length}
          <section>
            <button class="plain more" onclick={() => (showNoDue = !showNoDue)} aria-expanded={showNoDue}>
              期限なしのTodo <span class="num">{view.no_due.length}</span> 件 {showNoDue ? 'を閉じる' : 'を見る'}
            </button>
            {#if showNoDue}
              <ul class="todos">
                {#each view.no_due as t (t.id)}
                  <TodoItem todo={t} today={view.date} onchange={load} compact showEvent={false} />
                {/each}
              </ul>
            {/if}
          </section>
        {/if}
      {:else}
        <p class="faint note">読み込み中</p>
      {/if}
    </div>

    <footer>
      <QuickInput compact onsent={() => openMain('approvals')} onchange={load} />
    </footer>
  {/if}
</div>
{/if}

<style>
  :global(body.widget-body) { background: transparent; }
  .widget {
    height: 100vh;
    display: flex; flex-direction: column;
    position: relative;
    border: 1px solid var(--rule);
    border-radius: var(--radius-m);
    overflow: hidden;
  }
  header {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 10px 10px 8px 14px;
    background: var(--paper-raised);
    border-bottom: 2px solid var(--ink);
    user-select: none;
  }
  .folded header { border-bottom: none; }
  .day { display: flex; align-items: center; gap: 8px; }
  .d { font-size: var(--step-4); line-height: 1; font-weight: 700; letter-spacing: -0.02em; }
  .folded .d { font-size: 28px; }
  .wd { display: flex; flex-direction: column; line-height: 1.3; }
  .w { font-weight: 700; }
  .m { font-size: var(--step--1); }
  .actions { display: flex; gap: 2px; align-items: center; }
  .icon { display: inline-flex; padding: 4px; color: var(--ink-soft); }
  .icon.on { color: var(--ink); }
  .badge {
    background: var(--high); border-color: var(--high); color: #fff;
    font-size: var(--step--1); padding: 2px 8px; margin-right: 4px; border-radius: 12px;
  }
  .body { flex: 1; overflow-y: auto; padding: 8px 12px 4px; }
  section { margin-bottom: 12px; }
  h2 { font-size: var(--step--1); color: var(--ink-soft); margin-bottom: 4px; }
  ul { margin: 0; padding: 0; }
  .events li { list-style: none; }
  .event {
    width: 100%; display: flex; gap: 10px; text-align: left;
    background: var(--paper-raised); border-color: transparent; border-left: 4px solid var(--ink);
    border-radius: 0 var(--radius-s) var(--radius-s) 0; margin-bottom: 4px; padding: 5px 8px;
  }
  .time { color: var(--ink-soft); min-width: 3.2em; }
  .title { overflow-wrap: anywhere; flex: 1; }
  .leave {
    flex: none; align-self: center; padding: 0 6px; border-radius: 10px; font-size: 11px; font-weight: 700;
    background: var(--medium-tint); color: var(--medium);
  }
  .note { margin: 0; font-size: var(--step--1); }
  .note.done { margin-top: 4px; color: var(--ok); }
  .more { font-size: var(--step--1); color: var(--ink-soft); padding-left: 0; margin-bottom: 4px; }
  footer { padding: 8px 10px 10px; background: var(--paper-raised); border-top: 1px solid var(--rule); }

  /* 画面端のつまみ */
  .tab {
    width: 100vw; height: 100vh; padding: 0; margin: 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
    background: var(--paper-raised); color: var(--ink);
    border: 1px solid var(--rule); box-sizing: border-box; position: relative; cursor: pointer;
  }
  .tab-left { border-left: none; border-right: 3px solid var(--ink); border-radius: 0 var(--radius-m) var(--radius-m) 0; }
  .tab-right { border-right: none; border-left: 3px solid var(--ink); border-radius: var(--radius-m) 0 0 var(--radius-m); }
  .tab-top {
    flex-direction: row; gap: 10px; border-top: none; border-bottom: 3px solid var(--ink);
    border-radius: 0 0 var(--radius-m) var(--radius-m);
  }
  .t-day { font-size: 20px; font-weight: 700; line-height: 1; letter-spacing: -0.02em; }
  .tab-top .t-day { font-size: 17px; }
  .t-day small { font-size: 11px; font-weight: 400; color: var(--ink-soft); letter-spacing: 0; }
  .t-wd { font-size: 11px; color: var(--ink-soft); line-height: 1; }
  .t-count {
    margin-top: 4px; min-width: 22px; padding: 1px 6px; border-radius: 10px;
    background: var(--high); color: #fff; font-size: 12px; line-height: 1.4; text-align: center;
  }
  .tab-top .t-count, .tab-top .t-pending { margin-top: 0; font-size: 12px; }
  .t-count.zero { background: var(--paper); color: var(--ink-soft); border: 1px solid var(--rule); }
  .t-count b, .t-pending b { font-weight: 700; }
  .t-pending { color: var(--high); }
  .t-none { margin-top: 4px; color: var(--ok); font-size: 13px; }
  .t-dot { position: absolute; top: 6px; right: 6px; width: 7px; height: 7px; border-radius: 50%; background: var(--high); }
  .tab-right .t-dot { right: auto; left: 8px; }
</style>
