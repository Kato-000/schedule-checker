<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let { categories = [] } = $props();
  let data = $state(null);
  let error = $state('');
  let msg = $state('');
  let busy = $state(false);
  let editing = $state(null);       // { id, text, category }
  let newRule = $state({ text: '', category: '' });

  const candidates = $derived(data ? data.rules.filter((r) => r.status === 'candidate') : []);
  const active = $derived(data ? data.rules.filter((r) => r.status === 'active') : []);
  const disabled = $derived(data ? data.rules.filter((r) => r.status === 'disabled') : []);
  const SOURCE = { seed: '初期ルール', auto: '修正から作成', manual: '手で追加' };

  async function load() {
    try {
      data = await api.rules();
      error = '';
    } catch (e) {
      error = e.message;
    }
  }
  onMount(load);

  async function act(fn, done = '') {
    busy = true;
    error = msg = '';
    try {
      await fn();
      msg = done;
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const setStatus = (r, status, done) => act(() => api.updateRule(r.id, { status }), done);
  const saveEdit = () => act(async () => {
    await api.updateRule(editing.id, { text: editing.text, category: editing.category || null });
    editing = null;
  }, '保存しました');
  const remove = (r) => act(() => api.deleteRule(r.id), '削除しました');
  const add = () => act(async () => {
    await api.addRule(newRule.text, newRule.category || null);
    newRule = { text: '', category: '' };
  }, '追加しました');
  const extract = () => act(async () => {
    const r = await api.extractRules();
    msg = r.added.length ? `ルール案を ${r.added.length} 件作りました` : '新しいルール案は見つかりませんでした';
  });
</script>

{#snippet ruleRow(r, actions)}
  <li class="rule" class:cand={r.status === 'candidate'}>
    {#if editing?.id === r.id}
      <div class="edit">
        <input bind:value={editing.text} aria-label="ルールの内容" />
        <select bind:value={editing.category} aria-label="対象の種類">
          <option value="">全般</option>
          {#each categories as c}<option value={c}>{c}</option>{/each}
        </select>
        <button class="primary" onclick={saveEdit} disabled={busy}>保存</button>
        <button onclick={() => (editing = null)}>やめる</button>
      </div>
    {:else}
      <div class="body">
        <p class="text">{r.text}</p>
        <p class="meta faint">
          <span class="pill">{r.category ?? '全般'}</span>
          {SOURCE[r.source] ?? r.source}{r.reason ? `・根拠: ${r.reason}` : ''}
        </p>
      </div>
      <div class="actions">{@render actions(r)}</div>
    {/if}
  </li>
{/snippet}

<div class="rules">
  <h1>自分ルール</h1>
  <p class="muted lead">Todoを作るときにLLMへ渡すルールです。承認時に直した内容から、くり返し出てくる傾向をルールの案にします。案は確認してから有効にしてください。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if msg}<p class="ok" role="status">{msg}</p>{/if}

  {#if data}
    <section>
      <div class="head">
        <h2>確認待ちの案</h2>
        <span class="faint small">修正ありの承認 {data.unchecked_edits} / {data.extract_every} 件で自動作成</span>
        <button class="plain small" onclick={extract} disabled={busy}>今すぐ案を作る</button>
      </div>
      {#if candidates.length}
        <ul>
          {#each candidates as r (r.id)}
            {@render ruleRow(r, candActions)}
          {/each}
        </ul>
      {:else}
        <p class="faint">確認待ちの案はありません。</p>
      {/if}
    </section>

    <section>
      <h2>有効なルール</h2>
      {#if active.length}
        <ul>
          {#each active as r (r.id)}
            {@render ruleRow(r, activeActions)}
          {/each}
        </ul>
      {:else}
        <p class="faint">有効なルールはありません。</p>
      {/if}
      <form class="add" onsubmit={(e) => { e.preventDefault(); if (newRule.text.trim()) add(); }}>
        <input bind:value={newRule.text} placeholder="ルールを追加（例: 通院の前日に保険証を確認する）" aria-label="追加するルール" />
        <select bind:value={newRule.category} aria-label="対象の種類">
          <option value="">全般</option>
          {#each categories as c}<option value={c}>{c}</option>{/each}
        </select>
        <button type="submit" disabled={busy || !newRule.text.trim()}>追加</button>
      </form>
    </section>

    {#if disabled.length}
      <section>
        <h2>止めているルール</h2>
        <ul>
          {#each disabled as r (r.id)}
            {@render ruleRow(r, disabledActions)}
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</div>

{#snippet candActions(r)}
  <button class="primary" onclick={() => setStatus(r, 'active', '有効にしました')} disabled={busy}>有効にする</button>
  <button onclick={() => (editing = { id: r.id, text: r.text, category: r.category ?? '' })}>直す</button>
  <button class="plain danger" onclick={() => setStatus(r, 'rejected', '却下しました')} disabled={busy}>却下</button>
{/snippet}

{#snippet activeActions(r)}
  <button onclick={() => (editing = { id: r.id, text: r.text, category: r.category ?? '' })}>直す</button>
  <button onclick={() => setStatus(r, 'disabled', '止めました')} disabled={busy}>止める</button>
  {#if r.source !== 'seed'}<button class="plain danger" onclick={() => remove(r)} disabled={busy}>削除</button>{/if}
{/snippet}

{#snippet disabledActions(r)}
  <button onclick={() => setStatus(r, 'active', '有効にしました')} disabled={busy}>再開</button>
  {#if r.source !== 'seed'}<button class="plain danger" onclick={() => remove(r)} disabled={busy}>削除</button>{/if}
{/snippet}

<style>
  .rules { max-width: 860px; }
  h1 { font-size: var(--step-2); }
  .lead { margin: 4px 0 16px; max-width: 46em; }
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  h2 { font-size: var(--step-0); margin-bottom: 8px; }
  .head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .small { font-size: var(--step--1); }
  ul { list-style: none; margin: 0; padding: 0; }
  .rule {
    display: flex; justify-content: space-between; gap: 12px; align-items: center;
    background: var(--paper-raised); border-left: 4px solid var(--ink); padding: 8px 10px; margin-bottom: 6px;
    border-radius: 0 var(--radius-s) var(--radius-s) 0;
  }
  .rule.cand { border-left-color: var(--medium); background: var(--medium-tint); }
  .body { min-width: 0; }
  .text { margin: 0; overflow-wrap: anywhere; }
  .meta { margin: 2px 0 0; font-size: var(--step--1); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .actions { display: flex; gap: 4px; flex: none; }
  .edit { display: grid; grid-template-columns: 1fr 110px auto auto; gap: 6px; width: 100%; }
  .add { display: grid; grid-template-columns: 1fr 110px auto; gap: 6px; margin-top: 10px; }
  .ok { color: var(--ok); }
  @media (max-width: 640px) {
    .rule { flex-direction: column; align-items: stretch; }
    .edit, .add { grid-template-columns: 1fr 1fr; }
    .edit input, .add input { grid-column: 1 / -1; }
  }
</style>
