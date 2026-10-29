<script>
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import EventFields from './EventFields.svelte';
  import TodoRows from './TodoRows.svelte';
  import LookupBox from './LookupBox.svelte';
  import MapBox from './MapBox.svelte';

  let { proposal, categories = [], today, googleMode = 'off', defaultLocalOnly = false,
        onresolved = () => {}, onrefresh = () => {} } = $props();

  let ev = $state(null);
  let todos = $state([]);
  let lastStatus = null;
  let busy = $state(false);
  let error = $state('');
  let approvedMsg = $state('');

  // サーバーの状態が進んだときだけ、編集用の値を差し替える（編集中の内容は消さない）
  $effect(() => {
    const p = proposal;
    if (p.event && (ev === null || (lastStatus === 'reading'))) {
      ev = { ...p.event };
      if (p.kind === 'new' && ev.local_only === undefined) ev.local_only = defaultLocalOnly;
    }
    if (p.status === 'pending' && lastStatus !== 'pending') todos = p.todos.map((t) => ({ ...t }));
    lastStatus = p.status;
  });

  const reading = $derived(proposal.status === 'reading');
  const drafting = $derived(proposal.status === 'drafting_todos');
  const failed = $derived(proposal.status === 'error');
  const dateChanged = $derived(ev && proposal.event && ev.start_date !== proposal.event.start_date);
  const imported = $derived(proposal.kind === 'import');

  async function act(fn) {
    busy = true;
    error = '';
    try {
      await fn();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const approve = () => act(async () => {
    const r = await api.approve(proposal.id, ev, todos.filter((t) => t.title.trim()));
    approvedMsg = r.edited ? '登録しました。直した内容は次回の手本になります。' : '登録しました。';
    await notifyChanged();
    setTimeout(onresolved, 900);
  });
  const reject = () => act(async () => {
    await api.reject(proposal.id);
    await notifyChanged();
    onresolved();
  });
  const redraft = () => act(async () => {
    await api.redraft(proposal.id, ev);
    onrefresh();
  });
</script>

<article class="card" class:done={approvedMsg} class:imported aria-busy={reading || drafting}>
  {#if imported}
    <p class="input"><span class="pill medium">Googleから取り込んだ予定</span>
      <span class="faint">Todoを足して承認するか、不要なら「Todoは不要」を押してください。予定はどちらでも残ります。</span></p>
  {:else}
    <p class="input">{#if proposal.source === 'voice'}<span class="pill">音声</span>{/if}<span class="faint">{proposal.source === 'voice' ? '聞き取った内容' : '入力'}</span> {proposal.input_text}</p>
  {/if}

  {#if reading}
    <p class="working">予定を読み取っています…</p>
  {:else if failed && !ev}
    <p class="error-text">{proposal.error}</p>
    <div class="btns"><button onclick={reject} disabled={busy}>却下</button></div>
  {:else if ev}
    {#each proposal.questions as q}
      <p class="question" role="note">{q}</p>
    {/each}
    {#if proposal.warnings.includes('chinese')}
      <p class="question" role="note">文章に中国語が混ざっている可能性があります。表記を確認してください。</p>
    {/if}

    <EventFields bind:event={ev} {categories} idPrefix="p{proposal.id}"
      showLocalOnly={googleMode === 'two_way' && proposal.kind === 'new'} />
    <LookupBox event={ev} onapply={(f, v) => { ev[f] = v; }} />
    <MapBox place={ev.address || ev.location || ''} title={ev.title} />

    <div class="todo-head">
      <h3>準備のTodo</h3>
      {#if proposal.examples?.length}
        <span class="faint examples">
          手本: {proposal.examples.map((e) => `${e.text}${e.source === 'own' ? '（自分）' : ''}`).join('、')}
        </span>
      {/if}
    </div>
    {#if drafting}
      <p class="working">準備のTodoを考えています…</p>
    {:else}
      {#if proposal.error}<p class="error-text">{proposal.error}</p>{/if}
      <TodoRows bind:todos defaultDate={ev.start_date} {today} />
    {/if}

    {#if approvedMsg}
      <p class="ok" role="status">{approvedMsg}</p>
    {:else}
      <div class="btns">
        <button class="primary" onclick={approve} disabled={busy || drafting || !ev.title || !ev.start_date}>{imported ? 'Todoを登録' : '承認して登録'}</button>
        {#if dateChanged}
          <button onclick={redraft} disabled={busy || drafting}>日付に合わせてTodoを作り直す</button>
        {:else}
          <button onclick={redraft} disabled={busy || drafting}>Todoを作り直す</button>
        {/if}
        <button class="danger plain" onclick={reject} disabled={busy}>{imported ? 'Todoは不要' : '却下'}</button>
      </div>
    {/if}
    {#if error}<p class="error-text">{error}</p>{/if}
  {/if}
</article>

<style>
  .card {
    background: var(--paper-raised); border: 1px solid var(--rule); border-top: 3px solid var(--medium);
    border-radius: 0 0 var(--radius-m) var(--radius-m); padding: 14px 18px 16px; margin-bottom: 20px;
  }
  .card.done { border-top-color: var(--ok); }
  .card.imported { border-top-color: var(--ink-soft); }
  .input .pill { margin-right: 8px; }
  .input { margin: 0 0 10px; font-size: var(--step--1); }
  .input .faint { margin-right: 6px; }
  .working { color: var(--ink-soft); margin: 8px 0; }
  .working::before {
    content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--medium); margin-right: 8px; animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse { 50% { opacity: .25; } }
  .question {
    margin: 0 0 10px; padding: 6px 10px; background: var(--high-tint); color: var(--high);
    border-radius: var(--radius-s); font-size: var(--step--1);
  }
  .todo-head { display: flex; align-items: baseline; gap: 12px; margin: 16px 0 6px; }
  h3 { font-size: var(--step-0); color: var(--ink-soft); white-space: nowrap; }
  .examples { font-size: var(--step--1); }
  .btns { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .ok { color: var(--ok); margin: 12px 0 0; font-weight: 700; }
</style>
