<script>
  // 「ネットで調べる」：送る検索語を先に見せ、押したときだけ検索する。結果は候補として出し、反映は本人が選ぶ
  import { api } from '../lib/api.js';
  import { openExternal } from '../lib/desktop.js';

  function follow(e, url) {
    e.preventDefault();
    openExternal(url).catch((err) => (error = err.message));
  }

  /** event: 今の予定（編集中の内容） / onapply(field, value): 候補を反映する */
  let { event, onapply = async () => {} } = $props();

  let stage = $state('closed');   // closed / confirm / searching / result
  let queries = $state([]);
  let result = $state(null);
  let applied = $state({});
  let error = $state('');
  let enabled = $state(null);

  // ネット連携がオフなら、ボタン自体を出さない
  $effect(() => {
    if (enabled === null) api.meta().then((m) => (enabled = !!m.net_enabled)).catch(() => (enabled = false));
  });

  async function open() {
    error = '';
    try {
      const r = await api.netQueries($state.snapshot(event));
      queries = r.queries;
      if (!queries.length) { error = '調べる手がかりがありません。予定の名前か場所を入れてください'; return; }
      stage = 'confirm';
    } catch (e) {
      error = e.message;
    }
  }

  async function search() {
    stage = 'searching';
    error = '';
    applied = {};
    try {
      result = await api.netLookup($state.snapshot(event), queries);
      stage = 'result';
    } catch (e) {
      error = e.message;
      stage = 'confirm';
    }
  }

  async function apply(c) {
    try {
      await onapply(c.field, c.value);
      applied = { ...applied, [c.field]: true };
    } catch (e) {
      error = e.message;
    }
  }
</script>

{#if enabled}
  <div class="lookup" class:open={stage !== 'closed'}>
    {#if stage === 'closed'}
      <button type="button" class="plain go" onclick={open}>
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.5"/></svg>
        ネットで場所や時刻を調べる
      </button>
    {:else}
      <div class="head">
        <strong>ネットで調べる</strong>
        <button type="button" class="plain small" onclick={() => { stage = 'closed'; result = null; }}>閉じる</button>
      </div>
      <p class="sent"><span class="faint">送る内容（検索語）:</span>
        {#each queries as q, i}<code>{q}</code>{#if i < queries.length - 1}<span class="faint">／</span>{/if}{/each}
      </p>
      {#if stage === 'confirm'}
        <p class="faint small">この検索語だけをWeb検索（Ollama）に送ります。日時やほかの予定は送りません。検索結果はこのPCのLLMが読みます。</p>
        <button type="button" class="primary" onclick={search}>この内容で検索する</button>
      {:else if stage === 'searching'}
        <p class="working">検索して、結果を読み取っています…</p>
      {:else if result}
        {#if result.candidates.length}
          <ul class="cands">
            {#each result.candidates as c (c.field)}
              <li>
                <span class="lbl">{c.label}</span>
                <span class="val">{c.value}</span>
                {#if applied[c.field]}
                  <span class="ok">反映しました</span>
                {:else}
                  <button type="button" class="small" onclick={() => apply(c)}>反映</button>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="faint">新しく分かったことはありませんでした。</p>
        {/if}
        {#if result.hours}<p class="small"><span class="faint">営業・受付時間:</span> {result.hours}</p>{/if}
        {#if result.note}<p class="small note">{result.note}</p>{/if}
        {#if result.source}
          <p class="small"><span class="faint">根拠:</span> <a href={result.source.url} target="_blank" rel="noreferrer noopener" onclick={(e) => follow(e, result.source.url)}>{result.source.title || result.source.url}</a></p>
        {/if}
        {#if result.sources?.length}
          <details class="small">
            <summary class="faint">検索結果 {result.sources.length} 件</summary>
            <ul class="srcs">
              {#each result.sources as s}<li><a href={s.url} target="_blank" rel="noreferrer noopener" onclick={(e) => follow(e, s.url)}>{s.title || s.url}</a></li>{/each}
            </ul>
          </details>
        {/if}
        <p class="faint small">ネットの情報なので、反映する前に確かめてください。</p>
      {/if}
    {/if}
    {#if error}<p class="error-text small">{error}</p>{/if}
  </div>
{/if}

<style>
  .lookup { margin: 10px 0 0; }
  .lookup.open { padding: 10px 12px; border: 1px dashed var(--rule); border-radius: var(--radius-s); background: var(--paper); }
  .go { display: inline-flex; gap: 6px; align-items: center; padding: 2px 0; color: var(--medium); font-size: var(--step--1); }
  .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .sent { margin: 0 0 6px; font-size: var(--step--1); display: flex; flex-wrap: wrap; gap: 4px; align-items: baseline; }
  code { background: var(--low-tint); padding: 0 6px; border-radius: 3px; }
  .small { font-size: var(--step--1); }
  p { margin: 4px 0; }
  .working { color: var(--ink-soft); }
  .cands { list-style: none; margin: 4px 0; padding: 0; }
  .cands li { display: flex; gap: 10px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--rule); }
  .lbl { width: 3em; color: var(--ink-soft); font-size: var(--step--1); flex: none; }
  .val { flex: 1; overflow-wrap: anywhere; }
  .ok { color: var(--ok); font-size: var(--step--1); }
  .note { color: var(--high); }
  .srcs { margin: 4px 0; padding-left: 1.2em; }
  .srcs a, .small a { overflow-wrap: anywhere; }
</style>
