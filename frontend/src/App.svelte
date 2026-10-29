<script>
  import { onMount } from 'svelte';
  import Widget from './components/Widget.svelte';
  import Main from './components/Main.svelte';
  import Login from './components/Login.svelte';
  import { api } from './lib/api.js';
  import { isTauri } from './lib/desktop.js';

  // #/widget → ウィジェット、#/main/<タブ> → メイン画面。
  // ハッシュがない場合、デスクトップ版ではウィンドウ名（widget / main）で決める
  const label = isTauri ? window.__TAURI_INTERNALS__?.metadata?.currentWindow?.label : null;
  const fallback = label === 'widget' ? '#/widget' : '#/main/today';
  let hash = $state(location.hash || fallback);
  $effect(() => {
    const on = () => (hash = location.hash || fallback);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  });
  const isWidget = $derived(hash.startsWith('#/widget'));
  const tab = $derived(hash.split('/')[2] || 'today');

  // スマホ（自宅LAN）から開いたときだけPINでのログインが必要
  let auth = $state(isTauri ? 'ok' : 'checking');
  onMount(() => {
    const need = () => (auth = 'login');
    window.addEventListener('auth-required', need);
    if (!isTauri) {
      api.authStatus()
        .then((s) => (auth = s.authenticated ? 'ok' : 'login'))
        .catch(() => (auth = 'ok'));   // バックエンドに届かない場合は、各画面でエラーを表示する
    }
    return () => window.removeEventListener('auth-required', need);
  });
</script>

{#if auth === 'login'}
  <Login onloggedin={() => (auth = 'ok')} />
{:else if auth === 'ok'}
  {#if isWidget}
    <Widget />
  {:else}
    <Main {tab} />
  {/if}
{/if}
