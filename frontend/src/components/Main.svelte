<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { onChanged, onNavigate } from '../lib/desktop.js';
  import { whileActive, setIdleSeconds } from '../lib/activity.js';
  import QuickInput from './QuickInput.svelte';
  import TodayView from './TodayView.svelte';
  import CalendarView from './CalendarView.svelte';
  import Approvals from './Approvals.svelte';
  import Settings from './Settings.svelte';
  import Rules from './Rules.svelte';

  let { tab = 'today' } = $props();
  let meta = $state(null);
  let metaError = $state('');
  let version = $state(0); // データが変わったら子の表示を読み直させる

  const TABS = [
    { id: 'today', label: '今日' },
    { id: 'week', label: '週' },
    { id: 'month', label: '月' },
    { id: 'approvals', label: '承認待ち' },
    { id: 'rules', label: 'ルール' },
    { id: 'settings', label: '設定' },
  ];

  async function logout() {
    try { await api.logout(); } finally { location.reload(); }
  }

  async function loadMeta() {
    try {
      meta = await api.meta();
      metaError = '';
      setIdleSeconds(meta.idle_seconds);
    } catch (e) {
      metaError = e.message;
    }
  }

  function go(id) {
    location.hash = `#/main/${id}`;
  }

  onMount(() => {
    loadMeta();
    // 操作中だけ15秒ごとに確認する（使っていない間・画面を隠している間は止める）
    const stopPoll = whileActive(loadMeta, 15000);
    const offs = [];
    onNavigate((t) => go(t)).then((u) => offs.push(u));
    onChanged(() => { version++; loadMeta(); }).then((u) => offs.push(u));
    return () => { stopPoll(); offs.forEach((u) => u()); };
  });

  function changed() {
    version++;
    loadMeta();
  }
</script>

<div class="shell">
  <nav aria-label="表示の切り替え">
    <div class="brand">予定チェッカー</div>
    <ul>
      {#each TABS as t}
        <li>
          <button class:active={tab === t.id} aria-current={tab === t.id ? 'page' : undefined} onclick={() => go(t.id)}>
            {t.label}
            {#if t.id === 'approvals' && meta?.pending_count}<span class="count num">{meta.pending_count}</span>{/if}
          </button>
        </li>
      {/each}
    </ul>
    {#if meta}
      {#if meta.local === false}
        <button class="logout" onclick={logout}>ログアウト</button>
      {/if}
      <p class="llm" class:ng={!meta.llm.ok} title={meta.llm.message}>
        <span class="dot" aria-hidden="true"></span>{meta.llm.ok ? 'LLM 準備OK' : meta.llm.message}
      </p>
    {/if}
  </nav>

  <main>
    <div class="input-bar">
      <QuickInput onsent={() => { changed(); go('approvals'); }} onchange={changed} />
      {#if metaError}<p class="error-text">{metaError}</p>{/if}
    </div>
    <div class="content">
      {#if tab === 'today'}
        <TodayView {version} onchange={changed} />
      {:else if tab === 'week' || tab === 'month'}
        {#key tab}
          <CalendarView mode={tab} {version} today={meta?.today} onchange={changed} />
        {/key}
      {:else if tab === 'approvals'}
        <Approvals categories={meta?.categories ?? []} today={meta?.today} googleMode={meta?.google_mode ?? 'off'}
          defaultLocalOnly={meta?.default_local_only ?? false} onchange={changed} />
      {:else if tab === 'rules'}
        <Rules categories={meta?.categories ?? []} />
      {:else if tab === 'settings'}
        <Settings local={meta?.local ?? true} onchange={changed} />
      {/if}
    </div>
  </main>
</div>

<style>
  .shell { display: grid; grid-template-columns: 168px 1fr; height: 100vh; position: relative; overflow: hidden; }
  nav {
    background: var(--ink); color: #dfe6f0;
    display: flex; flex-direction: column; padding: 16px 10px;
  }
  .brand { font-weight: 700; color: #fff; padding: 0 8px 16px; font-size: var(--step-1); }
  nav ul { list-style: none; margin: 0; padding: 0; flex: 1; }
  nav button {
    width: 100%; text-align: left; background: transparent; border: none; color: inherit;
    padding: 8px 10px; border-radius: var(--radius-s); display: flex; justify-content: space-between;
  }
  nav button:hover { background: rgba(255,255,255,.08); }
  nav button.active { background: var(--paper); color: var(--ink); font-weight: 700; }
  .count { background: var(--high); color: #fff; border-radius: 10px; padding: 0 7px; font-size: var(--step--1); }
  nav button.logout { color: #c5d0e0; font-size: var(--step--1); margin-bottom: 8px; width: auto; }
  .llm { font-size: var(--step--1); margin: 0; padding: 0 8px; display: flex; gap: 6px; align-items: center; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #6cc49a; flex: none; }
  .llm.ng .dot { background: #ff8a7a; }
  main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  .input-bar { padding: 14px 24px; background: var(--paper-raised); border-bottom: 1px solid var(--rule); }
  .input-bar p { margin: 6px 0 0; }
  .content { flex: 1; overflow: auto; padding: 20px 24px 32px; }
  @media (max-width: 720px) {
    .shell { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
    nav { flex-direction: row; align-items: center; padding: 8px; overflow-x: auto; }
    .brand, .llm { display: none; }
    nav ul { display: flex; gap: 4px; }
    nav button, nav button.logout { white-space: nowrap; width: auto; gap: 6px; }
    nav button.logout { margin: 0 0 0 4px; }
    .input-bar, .content { padding-left: 12px; padding-right: 12px; }
  }
</style>
