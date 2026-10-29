<script>
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { eventWhen } from '../lib/format.js';

  let { proposal, onresolved = () => {} } = $props();
  let busy = $state(false);
  let error = $state('');
  const deleted = $derived(proposal.google_deleted);

  async function choose(keep) {
    busy = true;
    error = '';
    try {
      await api.resolve(proposal.id, keep);
      await notifyChanged();
      onresolved();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

{#snippet side(label, e)}
  <div class="side">
    <h4>{label}</h4>
    {#if e}
      <p class="title">{e.title}</p>
      <p class="muted">{eventWhen(e)}</p>
      {#if e.location}<p class="faint">{e.location}</p>{/if}
    {:else}
      <p class="gone">削除されています</p>
    {/if}
  </div>
{/snippet}

<article class="card">
  <p class="lead">
    <span class="pill high">要確認</span>
    {deleted
      ? 'この予定はGoogleカレンダーで削除されましたが、PCには未完了のTodoや送信前の変更があります。'
      : 'この予定は、PCとGoogleカレンダーの両方で変更されました。残す方を選んでください。'}
  </p>
  <div class="sides">
    {@render side('このPC', proposal.event)}
    {@render side('Googleカレンダー', deleted ? null : proposal.google)}
  </div>
  <div class="btns">
    <button class="primary" onclick={() => choose('local')} disabled={busy}>
      {deleted ? 'PCに残す' : 'PCの内容を残す'}
    </button>
    <button onclick={() => choose('google')} disabled={busy}>
      {deleted ? 'PCからも削除する（Todoも消えます）' : 'Googleの内容にそろえる'}
    </button>
  </div>
  {#if error}<p class="error-text">{error}</p>{/if}
</article>

<style>
  .card {
    background: var(--paper-raised); border: 1px solid var(--rule); border-top: 3px solid var(--high);
    border-radius: 0 0 var(--radius-m) var(--radius-m); padding: 14px 18px 16px; margin-bottom: 20px;
  }
  .lead { margin: 0 0 12px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .sides { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .side { border: 1px solid var(--rule); border-radius: var(--radius-s); padding: 10px 12px; background: #fff; }
  h4 { margin: 0 0 6px; font-size: var(--step--1); color: var(--ink-soft); }
  p { margin: 0; }
  .title { font-weight: 700; }
  .gone { color: var(--high); }
  .btns { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  @media (max-width: 560px) { .sides { grid-template-columns: 1fr; } }
</style>
