<script>
  // Google Maps の地図を画面の中に表示する（外部ブラウザは開かない）。開いたときだけ Google に送る
  import { api } from '../lib/api.js';

  /** place: 場所・住所（地図に出すもの） */
  let { place = '', title = '' } = $props();

  let net = $state(null);
  let open = $state(false);
  let view = $state('place');      // place / search / transit / car
  let q = $state('');
  let url = $state('');
  let sent = $state('');
  let error = $state('');
  let busy = $state(false);

  $effect(() => {
    if (net === null) api.net().then((n) => (net = n)).catch(() => (net = { map_ready: false }));
  });

  async function show(v, query) {
    view = v;
    busy = true;
    error = '';
    try {
      const r = v === 'transit' || v === 'car'
        ? await api.mapUrl({ kind: 'directions', destination: place, mode: v })
        : await api.mapUrl({ kind: v, q: query });
      url = r.url;
      sent = r.sent;
      open = true;
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  function search(e) {
    e.preventDefault();
    if (q.trim()) show('search', q.trim());
  }
</script>

{#if net?.map_ready}
  <div class="map">
    {#if !open}
      <div class="btns">
        {#if place}
          <button type="button" class="plain go" onclick={() => show('place', place)} disabled={busy}>
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 15s5-4.6 5-8.5A5 5 0 0 0 3 6.5C3 10.4 8 15 8 15z" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="6.5" r="1.8" fill="currentColor"/></svg>
            地図で見る
          </button>
          {#if net.home_address_set}
            <button type="button" class="plain go" onclick={() => show('transit')} disabled={busy}>自宅からの経路（地図）</button>
          {/if}
        {/if}
        <form class="find" onsubmit={search}>
          <input bind:value={q} placeholder={place ? '地図で探す（例: 近くの駐車場）' : '地図で探す（例: 福岡 歯医者）'} aria-label="地図で探す" />
          <button type="submit" disabled={busy || !q.trim()}>探す</button>
        </form>
      </div>
    {:else}
      <div class="head">
        <span class="seg" role="tablist" aria-label="地図の表示">
          {#if place}
            <button type="button" role="tab" aria-selected={view === 'place'} class:on={view === 'place'} onclick={() => show('place', place)}>場所</button>
            {#if net.home_address_set}
              <button type="button" role="tab" aria-selected={view === 'transit'} class:on={view === 'transit'} onclick={() => show('transit')}>電車・バス</button>
              <button type="button" role="tab" aria-selected={view === 'car'} class:on={view === 'car'} onclick={() => show('car')}>車</button>
            {/if}
          {/if}
          {#if view === 'search'}<button type="button" role="tab" aria-selected="true" class="on">検索</button>{/if}
        </span>
        <form class="find" onsubmit={search}>
          <input bind:value={q} placeholder="地図で探す" aria-label="地図で探す" />
          <button type="submit" disabled={busy || !q.trim()}>探す</button>
        </form>
        <button type="button" class="plain small" onclick={() => { open = false; url = ''; }}>閉じる</button>
      </div>
      <iframe class="frame" src={url} title={title ? `${title} の地図` : '地図'}
        referrerpolicy="no-referrer-when-downgrade" allowfullscreen></iframe>
      <p class="faint small">Google に送った内容: {sent}</p>
    {/if}
    {#if error}<p class="error-text small">{error}</p>{/if}
  </div>
{/if}

<style>
  .map { margin-top: 10px; }
  .btns { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; }
  .go { display: inline-flex; gap: 6px; align-items: center; color: var(--medium); font-size: var(--step--1); padding: 2px 0; }
  .find { display: inline-flex; gap: 4px; flex: 1; min-width: 12em; }
  .find input { flex: 1; min-width: 0; font-size: var(--step--1); padding: 3px 8px; }
  .find button { font-size: var(--step--1); padding: 2px 10px; }
  .head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 6px; }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; }
  .seg button { border: none; border-radius: 0; padding: 3px 10px; font-size: var(--step--1); background: var(--paper-raised); }
  .seg button + button { border-left: 1px solid var(--rule); }
  .seg button.on { background: var(--ink); color: #fff; }
  .frame { width: 100%; height: 320px; border: 1px solid var(--rule); border-radius: var(--radius-s); display: block; background: var(--paper); }
  .small { font-size: var(--step--1); margin: 4px 0 0; }
</style>
