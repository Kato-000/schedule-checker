<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import ProposalCard from './ProposalCard.svelte';
  import ConflictCard from './ConflictCard.svelte';
  import TodoProposalCard from './TodoProposalCard.svelte';
  import { isIdle, onIdleChange } from '../lib/activity.js';

  let { categories = [], today, googleMode = 'off', defaultLocalOnly = false, onchange = () => {} } = $props();
  let list = $state([]);
  let loaded = $state(false);
  let error = $state('');
  let timer;

  const working = $derived(list.some((p) => p.status === 'reading' || p.status === 'drafting_todos'));

  async function load() {
    try {
      list = await api.proposals();
      loaded = true;
      error = '';
    } catch (e) {
      error = e.message;
    }
    clearTimeout(timer);
    // LLMが処理中のあいだは細かく確認し、終わったらゆっくりにする。使っていない間は止める
    if (!isIdle()) timer = setTimeout(load, working ? 1200 : 8000);
  }

  onMount(() => {
    load();
    const off = onIdleChange((idle) => { if (idle) clearTimeout(timer); else load(); });
    return () => { clearTimeout(timer); off(); };
  });

  function resolved() {
    load();
    onchange();
  }
</script>

<div class="approvals">
  <h1>承認待ち</h1>
  <p class="muted lead">LLMが作った案です。違うところを直してから承認してください。直した内容は、次に似た予定を入れたときの手本になります。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if loaded && !list.length}
    <p class="empty">承認待ちの案はありません。上の欄に予定を入力すると、ここに案が届きます。</p>
  {/if}
  {#each list as p (p.id)}
    {#if p.kind === 'conflict'}
      <ConflictCard proposal={p} onresolved={resolved} />
    {:else if p.kind === 'todo'}
      <TodoProposalCard proposal={p} {today} onresolved={resolved} />
    {:else}
      <ProposalCard proposal={p} {categories} {today} {googleMode} {defaultLocalOnly} onresolved={resolved} onrefresh={load} />
    {/if}
  {/each}
</div>

<style>
  .approvals { max-width: 920px; }
  h1 { font-size: var(--step-2); }
  .lead { margin: 4px 0 20px; max-width: 46em; }
  .empty {
    padding: 32px; text-align: center; color: var(--ink-soft);
    border: 1px dashed var(--rule); border-radius: var(--radius-m);
  }
</style>
