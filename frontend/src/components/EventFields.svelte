<script>
  // 予定の編集欄（承認画面と詳細パネルで共通）
  let { event = $bindable(), categories = [], idPrefix = 'ev', showLocalOnly = false } = $props();
  const cats = $derived(categories.length ? categories : [event.category]);
</script>

<div class="fields">
  <label class="wide">
    <span>予定</span>
    <input bind:value={event.title} id="{idPrefix}-title" />
  </label>
  <label>
    <span>日付</span>
    <input type="date" bind:value={event.start_date} />
  </label>
  <label>
    <span>開始</span>
    <input type="time" value={event.start_time ?? ''} oninput={(e) => (event.start_time = e.currentTarget.value || null)} />
  </label>
  <label>
    <span>終了日</span>
    <input type="date" value={event.end_date ?? ''} oninput={(e) => (event.end_date = e.currentTarget.value || null)} />
  </label>
  <label>
    <span>終了</span>
    <input type="time" value={event.end_time ?? ''} oninput={(e) => (event.end_time = e.currentTarget.value || null)} />
  </label>
  <label>
    <span>場所</span>
    <input value={event.location ?? ''} oninput={(e) => (event.location = e.currentTarget.value || null)} />
  </label>
  <label class="addr">
    <span>住所（経路を調べるときに使う）</span>
    <input value={event.address ?? ''} oninput={(e) => (event.address = e.currentTarget.value || null)}
      placeholder="例: 東京都文京区後楽1-3-61" />
  </label>
  <label>
    <span>種類</span>
    <select bind:value={event.category}>
      {#each cats as c}<option value={c}>{c}</option>{/each}
    </select>
  </label>
  <label class="check">
    <input type="checkbox" bind:checked={event.is_deadline} />
    <span>締切（この日時までに終える）</span>
  </label>
  {#if showLocalOnly}
    <label class="check">
      <input type="checkbox" bind:checked={event.local_only} />
      <span>ローカル限定（Googleに送らない）</span>
    </label>
  {/if}
</div>

<style>
  .fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 12px; }
  label { display: flex; flex-direction: column; gap: 2px; font-size: var(--step--1); color: var(--ink-soft); }
  label input, label select { color: var(--ink); font-size: var(--step-0); }
  .wide { grid-column: 1 / -1; }
  .addr { grid-column: span 3; }
  @media (max-width: 640px) { .addr { grid-column: 1 / -1; } }
  .wide input { font-size: var(--step-1); font-weight: 700; }
  .check { flex-direction: row; align-items: center; gap: 6px; grid-column: span 2; align-self: end; }
  @media (max-width: 640px) { .fields { grid-template-columns: 1fr 1fr; } }
</style>
