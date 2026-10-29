<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let st = $state(null);
  let error = $state('');
  let msg = $state('');
  let busy = $state(false);
  let poll = 0;

  async function load() {
    try {
      st = await api.voice();
      error = '';
    } catch (e) {
      error = e.message;
    }
    clearTimeout(poll);
    if (st?.downloading) poll = setTimeout(load, 1000);
  }
  onMount(() => { load(); return () => clearTimeout(poll); });

  async function act(fn, done) {
    busy = true;
    error = msg = '';
    try {
      st = await fn();
      msg = done;
      if (st?.downloading) { clearTimeout(poll); poll = setTimeout(load, 1000); }
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const current = $derived(st?.models.find((m) => m.id === st.model));
  const dlModel = $derived(st?.models.find((m) => m.id === st?.downloading));
  const pct = $derived(dlModel ? Math.min(99, Math.round((st.progress_mb / dlModel.size_mb) * 100)) : 0);
</script>

<section>
  <h2>音声入力</h2>
  <p class="muted note">入力欄のマイクボタンで、話した内容を文字にします。文字にする処理はこのPCの中で行い、録音は保存しません。
    最初に1回だけ、文字起こしのモデル（公開されている音声認識モデル）をダウンロードします。</p>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if st}
    {#if !st.available}
      <p class="warn">音声入力の部品が入っていません。バックエンドを止めて <code>setup_backend.bat</code> を実行し直してください。</p>
    {:else}
      <fieldset disabled={busy || !!st.downloading}>
        <legend class="sr-only">文字起こしのモデル</legend>
        {#each st.models as m (m.id)}
          <label class="model">
            <input type="radio" name="voice-model" value={m.id} checked={st.model === m.id}
              onchange={() => act(() => api.saveVoice({ model: m.id }), 'モデルを切り替えました')} />
            <span class="label">{m.label}</span>
            <span class="state" class:ok={m.downloaded}>{m.downloaded ? 'ダウンロード済み' : '未ダウンロード'}</span>
            {#if m.downloaded}
              <button type="button" class="plain small" onclick={() => act(() => api.voiceDelete(m.id), '削除しました')}>削除</button>
            {/if}
          </label>
        {/each}
      </fieldset>

      {#if st.downloading}
        <div class="progress" role="status">
          <span class="bar" aria-hidden="true"><span style:width="{pct}%"></span></span>
          ダウンロード中… <span class="num">{st.progress_mb} / 約{dlModel?.size_mb} MB</span>
        </div>
      {:else if current && !current.downloaded}
        <p class="row">
          <button class="primary" onclick={() => act(() => api.voiceDownload(st.model), 'ダウンロードを始めました')} disabled={busy}>
            {current.label.replace(/（.*）/, '')}のモデルをダウンロード（約{current.size_mb}MB）
          </button>
        </p>
      {:else if st.ready}
        <p class="ok">使えます。入力欄のマイクボタンを押して話してください。</p>
      {/if}
      {#if st.error}<p class="error-text">{st.error}</p>{/if}

      <p class="muted note">聞き取った内容は、そのままLLMに渡して承認待ちに入れます（入力欄で「Todo」を選んでいればTodoの案、「予定」なら予定の案）。
        聞き間違いは承認待ちで直してください。</p>
      <p class="muted note">文字起こしはCPUで行います（GPUはLLMが使うため）。精度優先のモデルは、10秒ほどの話で数秒かかります。
        使わないまま10分たつとメモリから外し、次に使うときに読み込み直します。</p>
    {/if}
    {#if msg}<p class="ok" role="status">{msg}</p>{/if}
  {/if}
</section>

<style>
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  h2 { font-size: var(--step-0); margin-bottom: 4px; }
  p { margin: 0; }
  .note { font-size: var(--step--1); margin: 6px 0 0; }
  fieldset { border: none; padding: 0; margin: 10px 0 6px; }
  .model { display: flex; gap: 8px; align-items: center; padding: 4px 0; flex-wrap: wrap; }
  .label { min-width: 11em; }
  .state { font-size: var(--step--1); color: var(--ink-faint); }
  .state.ok { color: var(--ok); }
  .small { font-size: var(--step--1); padding: 0 6px; }
  .row { margin: 6px 0; }
  .progress { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: var(--step--1); }
  .bar { width: 160px; height: 8px; background: var(--rule); border-radius: 4px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--ink); transition: width .3s; }
  .ok { color: var(--ok); margin-top: 6px; }
  .warn { color: var(--high); }
  code { background: var(--low-tint); padding: 0 4px; border-radius: 3px; }
</style>
