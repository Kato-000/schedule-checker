<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let st = $state(null);
  let pin = $state('');
  let pin2 = $state('');
  let error = $state('');
  let msg = $state('');
  let busy = $state(false);

  async function load() {
    try {
      st = await api.lan();
    } catch (e) {
      error = e.message;
    }
  }
  onMount(load);

  async function act(fields, done) {
    busy = true;
    error = msg = '';
    try {
      st = await api.saveLan(fields);
      msg = done;
      // 開く処理は少しかかるので、すぐ状態を確認し直す
      if (fields.enabled) setTimeout(load, 1500);
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  function savePin(e) {
    e.preventDefault();
    if (pin !== pin2) {
      error = '確認用のPINが一致しません';
      return;
    }
    act({ pin }, 'PINを保存しました。スマホは一度ログアウトされます。').then(() => { pin = pin2 = ''; });
  }
</script>

<section class="lan">
  <h2>スマホから開く（自宅LAN内）</h2>
  <p class="muted note">自宅のWi-Fiにつながったスマホから、同じ画面を開けるようにします。インターネットには公開しません。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if st}
    <ol class="steps">
      <li class:done={st.cert_ok}>
        <span class="mark" aria-hidden="true">{st.cert_ok ? '済' : '1'}</span>
        <div>
          <strong>証明書を作る</strong>
          {#if st.cert_ok}
            <p class="faint">作成済み</p>
          {:else}
            <p class="note">PCで <code>make_lan_cert.ps1</code> を実行し、表示された手順でスマホに証明書を入れてください。ファイアウォールは <code>allow_lan_firewall.ps1</code>（管理者として実行）で設定します。</p>
          {/if}
        </div>
      </li>
      <li class:done={st.pin_set}>
        <span class="mark" aria-hidden="true">{st.pin_set ? '済' : '2'}</span>
        <div>
          <strong>PINを決める</strong>
          <form class="pin" onsubmit={savePin}>
            <input type="password" bind:value={pin} placeholder={st.pin_set ? '新しいPIN' : 'PIN（6文字以上）'} autocomplete="new-password" aria-label="PIN" />
            <input type="password" bind:value={pin2} placeholder="もう一度" autocomplete="new-password" aria-label="PIN（確認）" />
            <button type="submit" disabled={busy || !pin}>{st.pin_set ? 'PINを変える' : 'PINを保存'}</button>
          </form>
        </div>
      </li>
      <li class:done={st.running}>
        <span class="mark" aria-hidden="true">{st.running ? '済' : '3'}</span>
        <div>
          <strong>スマホから開けるようにする</strong>
          <label class="check">
            <input type="checkbox" checked={st.enabled} disabled={busy || !st.pin_set}
              onchange={(e) => act({ enabled: e.currentTarget.checked }, e.currentTarget.checked ? 'スマホ用の入口を開きました' : 'スマホ用の入口を閉じました')} />
            オンにする
          </label>
          {#if st.enabled && st.error}<p class="error-text note">{st.error}</p>{/if}
          {#if st.running}
            <p class="note">スマホのブラウザで次のURLを開いてください:</p>
            <ul class="urls">{#each st.urls as u}<li class="num">{u}</li>{/each}</ul>
          {/if}
        </div>
      </li>
    </ol>
    {#if msg}<p class="ok" role="status">{msg}</p>{/if}
  {/if}
</section>

<style>
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  h2 { font-size: var(--step-0); margin-bottom: 4px; }
  .note { font-size: var(--step--1); margin: 4px 0 0; }
  .steps { list-style: none; margin: 12px 0 0; padding: 0; }
  .steps > li { display: flex; gap: 10px; padding: 8px 0; }
  .mark {
    flex: none; width: 24px; height: 24px; border-radius: 50%; border: 1.5px solid var(--ink-soft);
    display: inline-flex; align-items: center; justify-content: center; font-size: var(--step--1);
  }
  .done .mark { background: var(--ok); border-color: var(--ok); color: #fff; }
  p { margin: 0; }
  .pin { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
  .pin input { width: 150px; }
  .check { display: flex; gap: 6px; align-items: center; margin-top: 4px; }
  .urls { margin: 4px 0 0; padding-left: 1.2em; font-size: var(--step-1); font-weight: 700; }
  code { background: var(--low-tint); padding: 0 4px; border-radius: 3px; }
  .ok { color: var(--ok); margin-top: 6px; }
</style>
