<script>
  import { api } from '../lib/api.js';

  let { onloggedin = () => {} } = $props();
  let pin = $state('');
  let busy = $state(false);
  let error = $state('');

  async function submit(e) {
    e.preventDefault();
    if (!pin || busy) return;
    busy = true;
    error = '';
    try {
      await api.login(pin);
      pin = '';
      onloggedin();
    } catch (err) {
      error = err.message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="login grid-paper">
  <form class="card" onsubmit={submit}>
    <h1>予定チェッカー</h1>
    <p class="muted">PCで設定したPINを入力してください。</p>
    <label for="pin">PIN</label>
    <input id="pin" type="password" inputmode="numeric" autocomplete="current-password" bind:value={pin} disabled={busy} />
    <button class="primary" type="submit" disabled={busy || !pin}>{busy ? '確認中' : 'ログイン'}</button>
    {#if error}<p class="error-text" role="alert">{error}</p>{/if}
  </form>
</div>

<style>
  .login { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
  .card {
    width: min(360px, 100%); background: var(--paper-raised); border: 1px solid var(--rule);
    border-top: 3px solid var(--ink); border-radius: 0 0 var(--radius-m) var(--radius-m);
    padding: 24px; display: flex; flex-direction: column; gap: 8px;
  }
  h1 { font-size: var(--step-2); }
  p { margin: 0 0 8px; }
  label { font-size: var(--step--1); color: var(--ink-soft); }
  input { font-size: 20px; letter-spacing: .2em; padding: 8px 12px; }
  button { padding: 10px; font-size: var(--step-1); margin-top: 8px; }
  .error-text { margin: 4px 0 0; }
</style>
