<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';

  let st = $state(null);
  let error = $state('');
  let msg = $state('');
  let busy = $state(false);
  let ollamaKey = $state('');
  let rapidKey = $state('');
  let mapsKey = $state('');
  let home = $state('');
  let margin = $state(10);
  let notifyMin = $state(15);

  async function load() {
    try {
      st = await api.net();
      home = st.home_address ?? '';
      margin = st.arrive_margin_min;
      notifyMin = st.leave_notify_min;
    } catch (e) {
      error = e.message;
    }
  }
  onMount(load);

  async function save(fields, done = '保存しました') {
    busy = true;
    error = msg = '';
    try {
      st = await api.saveNet(fields);
      msg = done;
      await notifyChanged();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const SERVICE = {
    ollama_search: 'Web検索', navitime_address: '住所検索',
    navitime_transit: '経路（電車・バス）', navitime_car: '経路（車）', google_maps: '地図',
  };
</script>

<section>
  <h2>ネット連携（調べもの・家を出る時刻）</h2>
  <p class="muted note">オンにすると、承認待ちや予定の画面に「ネットで調べる」「何時に出ればいいか調べる」のボタンが出ます。
    <strong>ボタンを押したときだけ</strong>通信し、送るのは検索語・住所・到着したい時刻だけです。予定の一覧やTodoは送りません。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if st}
    <label class="check">
      <input type="checkbox" checked={st.enabled} disabled={busy} onchange={(e) => save({ enabled: e.currentTarget.checked })} />
      ネット連携を使う
    </label>

    <div class="block">
      <h3>Web検索のキー（Ollama）</h3>
      <p class="muted note">足りない場所や時刻を調べるときに使います。ollama.com の無料アカウントで作ったAPIキーを入れてください。</p>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ ollama_key: ollamaKey }, 'キーを保存しました').then(() => (ollamaKey = '')); }}>
        <span class="state" class:ok={st.ollama_key_set}>{st.ollama_key_set ? '設定済み' : '未設定'}</span>
        <input type="password" bind:value={ollamaKey} placeholder={st.ollama_key_set ? '変えるときだけ入力' : 'APIキー'} autocomplete="off" aria-label="OllamaのAPIキー" />
        <button type="submit" disabled={busy || !ollamaKey.trim()}>保存</button>
        {#if st.ollama_key_set}<button type="button" class="plain" onclick={() => save({ ollama_key: '' }, 'キーを削除しました')}>削除</button>{/if}
      </form>
    </div>

    <div class="block">
      <h3>経路検索のキー（RapidAPI・NAVITIME）</h3>
      <p class="muted note">住所の位置と、電車・バス／車の経路を調べるときに使います。RapidAPI のキーを入れてください
        （NAVITIME の「Route(totalnavi)」「Route(car)」「Geocoding」の無料プランへの登録が必要です）。</p>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ rapidapi_key: rapidKey }, 'キーを保存しました').then(() => (rapidKey = '')); }}>
        <span class="state" class:ok={st.rapidapi_key_set}>{st.rapidapi_key_set ? '設定済み' : '未設定'}</span>
        <input type="password" bind:value={rapidKey} placeholder={st.rapidapi_key_set ? '変えるときだけ入力' : 'APIキー'} autocomplete="off" aria-label="RapidAPIのキー" />
        <button type="submit" disabled={busy || !rapidKey.trim()}>保存</button>
        {#if st.rapidapi_key_set}<button type="button" class="plain" onclick={() => save({ rapidapi_key: '' }, 'キーを削除しました')}>削除</button>{/if}
      </form>
    </div>

    <div class="block">
      <h3>地図のキー（Google Maps Embed API）</h3>
      <p class="muted note">予定や承認待ちの画面の中に Google マップの地図・検索結果・自宅からの経路を表示します（外部ブラウザは開きません）。
        Google Cloud で「Maps Embed API」を有効にして作ったAPIキーを入れてください（Maps Embed API は無料・回数無制限）。</p>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ maps_key: mapsKey }, 'キーを保存しました').then(() => (mapsKey = '')); }}>
        <span class="state" class:ok={st.maps_key_set}>{st.maps_key_set ? '設定済み' : '未設定'}</span>
        <input type="password" bind:value={mapsKey} placeholder={st.maps_key_set ? '変えるときだけ入力' : 'APIキー'} autocomplete="off" aria-label="Google MapsのAPIキー" />
        <button type="submit" disabled={busy || !mapsKey.trim()}>保存</button>
        {#if st.maps_key_set}<button type="button" class="plain" onclick={() => save({ maps_key: '' }, 'キーを削除しました')}>削除</button>{/if}
      </form>
    </div>

    <div class="block">
      <h3>自宅（経路の出発地）</h3>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ home_address: home }, '自宅の住所を確認して保存しました'); }}>
        <input class="addr" bind:value={home} placeholder="例: 東京都千代田区千代田1-1" aria-label="自宅の住所" />
        <button type="submit" disabled={busy || !st.enabled}>{st.rapidapi_key_set ? '確認して保存' : '保存'}</button>
      </form>
      {#if st.home_label}<p class="note ok">登録済み: {st.home_label}</p>
      {:else if st.home_address}<p class="note ok">登録済み（地図の経路で使います）</p>{/if}
      <p class="muted note">経路検索のキーがあるときは、保存するときに住所検索（NAVITIME）で位置を確かめ、経路を調べるときは住所ではなく位置（緯度・経度）を送ります。
        地図で自宅からの経路を表示するときは、住所がそのまま Google に送られます。</p>
    </div>

    <div class="block">
      <h3>家を出る時刻の決め方</h3>
      <div class="row">
        <span>ふだんの移動手段</span>
        <span class="seg" role="radiogroup" aria-label="ふだんの移動手段">
          {#each [['transit', '電車・バス'], ['car', '車']] as [k, label]}
            <label class:on={st.travel_mode === k}>
              <input type="radio" name="travel-mode" value={k} checked={st.travel_mode === k} onchange={() => save({ travel_mode: k })} />{label}
            </label>
          {/each}
        </span>
      </div>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ arrive_margin_min: Number(margin), leave_notify_min: Number(notifyMin) }); }}>
        <label for="net-margin">予定の</label>
        <input id="net-margin" class="num-in" type="number" min="0" max="120" bind:value={margin} />
        <span>分前に着く／</span>
        <label for="net-notify">家を出る</label>
        <input id="net-notify" class="num-in" type="number" min="0" max="120" bind:value={notifyMin} />
        <span>分前に通知（0で通知なし）</span>
        <button type="submit" disabled={busy}>保存</button>
      </form>
    </div>

    {#if msg}<p class="ok" role="status">{msg}</p>{/if}

    <details class="block">
      <summary>外に送った内容の記録（最近 {st.log.length} 件）</summary>
      {#if st.log.length}
        <ul class="log">
          {#each st.log as l (l.id)}
            <li class:ng={!l.ok}><span class="faint num">{l.at.slice(5, 16)}</span> <span class="svc">{SERVICE[l.service] ?? l.service}</span> {l.sent}{l.ok ? '' : '（失敗）'}</li>
          {/each}
        </ul>
      {:else}
        <p class="faint note">まだありません。</p>
      {/if}
    </details>
  {/if}
</section>

<style>
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  h2 { font-size: var(--step-0); margin-bottom: 4px; }
  h3 { font-size: var(--step--1); color: var(--ink-soft); margin: 0 0 4px; }
  p { margin: 0; }
  .note { font-size: var(--step--1); margin: 4px 0; }
  .block { margin-top: 14px; }
  .check { display: flex; gap: 6px; align-items: center; margin-top: 10px; font-weight: 700; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 4px 0; font-size: var(--step--1); }
  .row input[type='password'] { width: 16em; }
  .addr { flex: 1; min-width: 14em; }
  .num-in { width: 4.5em; }
  .state { font-size: var(--step--1); color: var(--ink-faint); min-width: 4.5em; }
  .state.ok, .ok { color: var(--ok); }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; }
  .seg label { position: relative; padding: 3px 12px; cursor: pointer; background: var(--paper-raised); }
  .seg label + label { border-left: 1px solid var(--rule); }
  .seg label.on { background: var(--ink); color: #fff; }
  .seg input { position: absolute; inset: 0; margin: 0; opacity: 0; pointer-events: none; }
  .seg label:focus-within { outline: 2px solid var(--ink); outline-offset: -2px; }
  summary { cursor: pointer; font-size: var(--step--1); }
  .log { list-style: none; margin: 6px 0 0; padding: 0; font-size: var(--step--1); max-height: 14em; overflow-y: auto; }
  .log li { padding: 2px 0; border-bottom: 1px solid var(--rule); overflow-wrap: anywhere; }
  .log li.ng { color: var(--high); }
  .svc { font-weight: 700; margin: 0 4px; }
</style>
