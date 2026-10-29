<script>
  // 家を出る時刻（経路）。押したときだけ経路検索に送る
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';

  let { event, onchange = () => {} } = $props();
  let net = $state(null);
  let mode = $state(null);
  let busy = $state(false);
  let error = $state('');
  let confirming = $state(false);

  $effect(() => {
    if (net === null) {
      api.net().then((n) => { net = n; mode ??= event.travel?.mode ?? n.travel_mode; }).catch(() => (net = { enabled: false }));
    }
  });

  const tr = $derived(event.travel);
  const dest = $derived(event.address || event.location || '');
  const MODE = { transit: '電車・バス', car: '車' };
  const hm = (s) => (s ? s.slice(11, 16) : '');

  async function run() {
    busy = true;
    error = '';
    try {
      await api.route(event.id, mode);
      confirming = false;
      await notifyChanged();
      onchange();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function clear() {
    busy = true;
    try {
      await api.clearRoute(event.id);
      await notifyChanged();
      onchange();
    } finally {
      busy = false;
    }
  }
</script>

{#if net?.enabled && event.start_time}
  <section class="route">
    <h3>家を出る時刻</h3>
    {#if tr}
      <p class="leave"><span class="big num">{hm(tr.depart_at)}</span> に出発
        <span class="faint">→ {hm(tr.arrive_at)} 着（{MODE[tr.mode]}・約{tr.minutes}分{tr.transit_count ? `・乗換${tr.transit_count}回` : ''}{tr.fare ? `・${tr.fare}円` : ''}）</span>
      </p>
      <p class="faint small">開始 {event.start_time} の{tr.margin}分前（{hm(tr.goal_at)}）までに着く経路 ／ 目的地: {tr.dest_label}</p>
      {#if tr.steps?.length}
        <ol class="steps">
          {#each tr.steps as s}
            <li><span class="num t">{s.depart}</span>
              <span>{s.label}{s.line ? `（${s.line}）` : ''}{s.to ? ` → ${s.to}` : ''}</span>
              {#if s.minutes}<span class="faint num">{s.minutes}分</span>{/if}</li>
          {/each}
        </ol>
      {/if}
      <p class="faint small">{tr.checked_at} に調べた結果です。電車の遅れなどは反映されません。</p>
    {:else if !net.home_set}
      <p class="faint small">PCの「設定 > ネット連携」で自宅の住所を設定すると使えます。</p>
    {:else if !dest}
      <p class="faint small">場所か住所を入れると調べられます（「ネットで調べる」で住所を探せます）。</p>
    {/if}

    {#if net.home_set && dest}
      {#if confirming}
        <div class="confirm">
          <span class="seg" role="radiogroup" aria-label="移動手段">
            {#each Object.entries(MODE) as [k, label]}
              <label class:on={mode === k}><input type="radio" name="mode-{event.id}" value={k} bind:group={mode} />{label}</label>
            {/each}
          </span>
          <p class="faint small">送る内容: 自宅の位置・目的地「{dest}」・到着したい時刻（NAVITIMEの経路検索）。予定の名前は送りません。</p>
          <div class="btns">
            <button class="primary" onclick={run} disabled={busy}>{busy ? '調べています…' : '経路を調べる'}</button>
            <button class="plain" onclick={() => (confirming = false)}>やめる</button>
          </div>
        </div>
      {:else}
        <div class="btns">
          <button onclick={() => (confirming = true)}>{tr ? '調べ直す' : '何時に出ればいいか調べる'}</button>
          {#if tr}<button class="plain" onclick={clear} disabled={busy}>消す</button>{/if}
        </div>
      {/if}
    {/if}
    {#if error}<p class="error-text small">{error}</p>{/if}
  </section>
{/if}

<style>
  .route { margin-top: 18px; }
  h3 { font-size: var(--step--1); color: var(--ink-soft); margin-bottom: 4px; }
  p { margin: 4px 0; }
  .leave { font-size: var(--step-0); }
  .big { font-size: var(--step-2); font-weight: 700; }
  .small { font-size: var(--step--1); }
  .steps { margin: 6px 0; padding: 0; list-style: none; font-size: var(--step--1); border-left: 2px solid var(--rule); }
  .steps li { display: flex; gap: 8px; padding: 2px 0 2px 8px; }
  .t { color: var(--ink-soft); width: 3em; flex: none; }
  .btns { display: flex; gap: 6px; margin-top: 6px; }
  .confirm { padding: 8px 10px; border: 1px dashed var(--rule); border-radius: var(--radius-s); background: var(--paper); margin-top: 6px; }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; }
  .seg label { position: relative; padding: 3px 12px; cursor: pointer; font-size: var(--step--1); background: var(--paper-raised); }
  .seg label + label { border-left: 1px solid var(--rule); }
  .seg label.on { background: var(--ink); color: #fff; }
  .seg input { position: absolute; inset: 0; margin: 0; opacity: 0; pointer-events: none; }
  .seg label:focus-within { outline: 2px solid var(--ink); outline-offset: -2px; }
</style>
