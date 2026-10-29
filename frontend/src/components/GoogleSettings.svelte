<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let { onchange = () => {} } = $props();
  let st = $state(null);
  let error = $state('');
  let msg = $state('');
  let busy = $state(false);
  let poll;

  const MODES = [
    { id: 'off', label: 'OFF', note: '完全にローカルで使う（初期値）' },
    { id: 'import', label: '取り込みのみ', note: 'Googleの予定をこちらに取り込む。こちらの予定は送らない' },
    { id: 'two_way', label: '双方向', note: 'こちらの予定もGoogleへ送る。「ローカル限定」にした予定は送らない' },
  ];

  const INTERVALS = [
    ['15m', '15分ごと'], ['1h', '1時間ごと'], ['6h', '6時間ごと'],
    ['daily', '1日1回（朝のまとめの前）'], ['manual', '自動で同期しない（手動だけ）'],
  ];

  async function load() {
    try {
      st = await api.google();
      error = '';
      clearTimeout(poll);
      if (st.connect.state === 'waiting') poll = setTimeout(load, 2000);
    } catch (e) {
      error = e.message;
    }
  }
  onMount(() => { load(); return () => clearTimeout(poll); });

  async function act(fn, done = '') {
    busy = true;
    error = msg = '';
    try {
      st = await fn();
      msg = done;
      onchange();
      if (st.connect?.state === 'waiting') poll = setTimeout(load, 2000);
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function pickFile(e) {
    const file = e.currentTarget.files?.[0];
    if (!file) return;
    const text = await file.text();
    await act(() => api.googleSecret(text), '認証用のファイルを読み込みました');
    e.currentTarget.value = '';
  }

  const connect = () => act(() => api.googleConnect(), 'ブラウザが開きます。Googleにログインして許可してください。');
  const setMode = (mode) => act(() => api.saveGoogle({ mode }), mode === 'off' ? '連携をOFFにしました' : '同期を始めました');
  const setDefaultLocal = (v) => act(() => api.saveGoogle({ default_local_only: v }), '保存しました');
  const syncNow = () => act(async () => {
    const r = await api.googleSync();
    if (r.result?.error) throw new Error(r.result.error);
    const p = r.result?.pull ?? {};
    msg = `取り込み: 追加 ${p.added ?? 0}・変更 ${p.updated ?? 0}・削除 ${p.deleted ?? 0}` +
      (r.result?.push ? ` ／ 送信: ${r.result.push.inserted + r.result.push.patched} 件` : '');
    return r.status;
  });
  async function disconnect() {
    if (!confirm('Googleとの接続を解除します。取り込んだ予定はこのPCに残ります。よろしいですか？')) return;
    await act(() => api.googleDisconnect(), '接続を解除しました');
  }
</script>

<section>
  <h2>Googleカレンダー連携</h2>
  <p class="muted note">送るのは予定（タイトル・日時・場所）だけです。Todo・修正の記録・LLMの処理内容は送りません。
    手順の詳細は README の「Googleカレンダー連携の準備」を見てください。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if st}
    <ol class="steps">
      <li class:done={st.client_secret}>
        <span class="mark" aria-hidden="true">{st.client_secret ? '済' : '1'}</span>
        <div>
          <strong>認証用のファイルを読み込む</strong>
          <p class="note">Google Cloud で作った「デスクトップアプリ」のOAuthクライアントのJSONファイルを選びます。</p>
          <input type="file" accept=".json,application/json" onchange={pickFile} disabled={busy} aria-label="認証用のJSONファイル" />
        </div>
      </li>
      <li class:done={st.connected}>
        <span class="mark" aria-hidden="true">{st.connected ? '済' : '2'}</span>
        <div>
          <strong>Googleに接続する</strong>
          {#if st.connected}
            <p class="faint">接続済み <button class="plain small" onclick={disconnect} disabled={busy}>接続を解除</button></p>
          {:else if st.connect.state === 'waiting'}
            <p class="note">ブラウザでGoogleにログインし、カレンダーへのアクセスを許可してください…</p>
          {:else}
            <button onclick={connect} disabled={busy || !st.client_secret}>Googleに接続</button>
            {#if st.connect.error}<p class="error-text note">{st.connect.error}</p>{/if}
          {/if}
        </div>
      </li>
      <li class:done={st.mode !== 'off'}>
        <span class="mark" aria-hidden="true">{st.mode !== 'off' ? '済' : '3'}</span>
        <div>
          <strong>連携のしかたを選ぶ</strong>
          <div class="modes" role="radiogroup" aria-label="連携のしかた">
            {#each MODES as m}
              <label class="mode" class:sel={st.mode === m.id}>
                <input type="radio" name="gmode" checked={st.mode === m.id} disabled={busy || (!st.connected && m.id !== 'off')}
                  onchange={() => setMode(m.id)} />
                <span><strong>{m.label}</strong><span class="faint">{m.note}</span></span>
              </label>
            {/each}
          </div>
          {#if st.mode === 'two_way'}
            <label class="check">
              <input type="checkbox" checked={st.default_local_only} onchange={(e) => setDefaultLocal(e.currentTarget.checked)} />
              新しい予定は最初から「ローカル限定」（Googleに送らない）にする
            </label>
          {/if}
        </div>
      </li>
    </ol>

    {#if st.mode !== 'off'}
      <div class="status">
        <p class="note">
          最後の同期: {st.last_sync ?? 'まだ'}
          {#if st.pending_push}・送信待ち {st.pending_push} 件{/if}
        </p>
        <div class="row interval">
          <label for="g-interval">自動で同期する間隔</label>
          <select id="g-interval" value={st.sync_interval} disabled={busy}
            onchange={(e) => act(() => api.saveGoogle({ sync_interval: e.currentTarget.value }), '同期の間隔を変えました')}>
            {#each INTERVALS as [v, label]}<option value={v}>{label}</option>{/each}
          </select>
        </div>
        <p class="muted note">
          {#if st.sync_interval === 'daily'}朝のまとめの10分前に1日1回同期します（まとめにGoogleの予定が入るように）。PCを起動したときにその日まだ同期していなければ、起動後すぐに1回同期します。
          {:else if st.sync_interval === 'manual'}自動では同期しません。「今すぐ同期」を押したときだけ同期します。
          {:else}PCが起動している間、この間隔で同期します。{/if}
          {#if st.mode === 'two_way'}こちらで作った・直した予定は、間隔にかかわらずすぐGoogleに送ります。{/if}
        </p>
        {#if st.last_error}<p class="error-text note">前回の同期でエラー: {st.last_error}</p>{/if}
        {#if st.push_errors}<p class="error-text note">Googleへ送れなかった予定が {st.push_errors} 件あります（次の同期で再送します）</p>{/if}
        <button onclick={syncNow} disabled={busy}>{busy ? '同期中' : '今すぐ同期'}</button>
      </div>
    {/if}
    {#if msg}<p class="ok" role="status">{msg}</p>{/if}
  {/if}
</section>

<style>
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  h2 { font-size: var(--step-0); margin-bottom: 4px; }
  .note { font-size: var(--step--1); margin: 4px 0 0; }
  p { margin: 0; }
  .steps { list-style: none; margin: 12px 0 0; padding: 0; }
  .steps > li { display: flex; gap: 10px; padding: 8px 0; }
  .steps > li > div { min-width: 0; flex: 1; }
  .mark {
    flex: none; width: 24px; height: 24px; border-radius: 50%; border: 1.5px solid var(--ink-soft);
    display: inline-flex; align-items: center; justify-content: center; font-size: var(--step--1);
  }
  .done .mark { background: var(--ok); border-color: var(--ok); color: #fff; }
  input[type=file] { margin-top: 6px; font-size: var(--step--1); max-width: 100%; }
  .modes { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
  .mode {
    display: flex; gap: 8px; align-items: flex-start; padding: 6px 10px; border: 1px solid var(--rule);
    border-radius: var(--radius-s); background: var(--paper-raised); cursor: pointer;
  }
  .mode.sel { border-color: var(--ink); }
  .mode input { margin-top: 4px; }
  .mode span { display: flex; flex-direction: column; }
  .mode .faint { font-size: var(--step--1); }
  .check { display: flex; gap: 6px; align-items: center; margin-top: 8px; font-size: var(--step--1); }
  .status { margin-top: 12px; padding: 10px 12px; background: var(--paper-raised); border-radius: var(--radius-s); }
  .status button { margin-top: 8px; }
  .small { font-size: var(--step--1); }
  .ok { color: var(--ok); margin-top: 6px; }
  .interval { display: flex; gap: 8px; align-items: center; margin: 6px 0 2px; font-size: var(--step--1); }
</style>
