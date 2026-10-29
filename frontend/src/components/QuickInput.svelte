<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { startRecording, recordingSupported, MAX_SECONDS } from '../lib/recorder.js';
  import { PRIORITY_LABEL, relDay, md } from '../lib/format.js';
  import TodoEditor from './TodoEditor.svelte';

  /** onsent: 予定の案を作り始めたら呼ばれる（承認画面へ移るなど）
   *  onchange: Todoを登録・変更したら呼ばれる（一覧の読み直し） */
  let { onsent = () => {}, onchange = () => {}, compact = false } = $props();
  let text = $state('');
  // 予定として入れるか、Todo（予定に結びつかない）として入れるか。窓ごとに前回の選択を覚える
  const MODE_KEY = `sc.quick.mode.${compact ? 'widget' : 'main'}`;
  let mode = $state(readMode());
  function readMode() {
    try { return localStorage.getItem(MODE_KEY) === 'todo' ? 'todo' : 'event'; } catch { return 'event'; }
  }
  function setMode(m) {
    mode = m;
    try { localStorage.setItem(MODE_KEY, m); } catch { /* 覚えられなくても動く */ }
    input?.focus();
  }
  // 登録したTodo（その場で直す・取り消すため）
  let added = $state(null);      // { todo, warnings, llm_error }
  let editingAdded = $state(false);
  let today = $state(null);
  let hideTimer = 0;
  let busy = $state(false);
  let error = $state('');
  let input;

  // 音声入力
  let voice = $state(null);            // /api/voice の結果
  let micState = $state('idle');       // idle / starting / recording / transcribing
  let level = $state(0);
  let seconds = $state(0);
  let session = null;
  const id = compact ? 'quick-w' : 'quick-m';

  const micReady = $derived(!!voice?.ready && recordingSupported());
  const micTitle = $derived(
    !recordingSupported() ? 'このページではマイクを使えません'
      : !voice ? '音声入力の状態を確認しています'
      : !voice.available ? '音声入力の部品が入っていません（setup_backend.bat を実行し直してください）'
      : !voice.ready ? 'PCの「設定 > 音声入力」でモデルを用意すると使えます'
      : micState === 'recording' ? '録音を止める'
      : mode === 'todo' ? '話してTodoを入れる（聞き取った内容はTodoの案として承認待ちに入ります）'
      : '話して予定を入れる（聞き取った内容は予定の案として承認待ちに入ります）');

  // 入力を始めたら、LLMのモデルを先に読み込んでおく（使わなければ設定の時間で自動的に外れる）
  let warmedAt = 0;
  function warm() {
    const t = Date.now();
    if (t - warmedAt < 20000) return;
    warmedAt = t;
    api.warmLLM().catch(() => {});
  }

  async function loadVoice() {
    try { voice = await api.voice(); } catch { voice = null; }
  }

  onMount(() => {
    loadVoice();
    return () => session?.cancel();
  });

  function showAdded(r) {
    added = r;
    editingAdded = false;
    clearTimeout(hideTimer);
    // 注意がなければ、しばらくしたら閉じる（直している間は閉じない）
    if (!r.llm_error && !r.warnings?.length) hideTimer = setTimeout(() => { if (!editingAdded) added = null; }, 15000);
  }

  async function undoAdded() {
    if (!added) return;
    try {
      await api.deleteTodo(added.todo.id);
      text = added.input ?? text;
      added = null;
      await notifyChanged();
      onchange();
    } catch (err) {
      error = err.message;
    }
  }

  async function send(value) {
    if (!value.trim() || busy) return;
    busy = true;
    error = '';
    try {
      if (mode === 'todo') {
        const [r, v] = await Promise.all([api.quickTodo(value.trim()), today ? null : api.meta().catch(() => null)]);
        if (v) today = v.today;
        text = '';
        showAdded(r);
        await notifyChanged();
        onchange(r.todo);
        return;
      }
      added = null;
      const p = await api.propose(value.trim());
      text = '';
      await notifyChanged();
      onsent(p);
    } catch (err) {
      error = err.message;
    } finally {
      busy = false;
    }
  }

  function submit(e) {
    e.preventDefault();
    send(text);
  }

  async function mic() {
    error = '';
    if (micState === 'recording') { session?.stop(); return; }
    if (micState !== 'idle') return;
    if (!micReady) { await loadVoice(); if (!micReady) { error = micTitle; return; } }
    micState = 'starting';
    api.warmVoice().catch(() => {});   // 話している間に文字起こしのモデルを読み込む
    warm();
    try {
      session = await startRecording({ onlevel: (l, s) => { level = l; seconds = s; } });
    } catch (e) {
      micState = 'idle';
      error = e.message;
      return;
    }
    micState = 'recording';
    const blob = await session.done;
    session = null;
    level = 0;
    if (!blob) { micState = 'idle'; error = '声が聞き取れませんでした。もう一度どうぞ'; return; }
    micState = 'transcribing';
    try {
      const r = await api.transcribe(blob);
      if (!r.text) { error = '声が聞き取れませんでした。もう一度どうぞ'; return; }
      // 聞き取った内容は確認せずにそのままLLMへ。結果は承認待ちで確認する
      added = null;
      const p = await api.propose(r.text, { kind: mode === 'todo' ? 'todo' : 'event', source: 'voice' });
      await notifyChanged();
      onsent(p);
    } catch (e) {
      error = e.message;
    } finally {
      micState = 'idle';
    }
  }

  function onkeydown(e) {
    if (e.key === 'Escape' && micState === 'recording') { session?.cancel(); }
  }
</script>

<svelte:window {onkeydown} />

<form class="quick" class:compact onsubmit={submit}>
  <span class="mode" role="radiogroup" aria-label="入力の種類">
    <button type="button" role="radio" aria-checked={mode === 'event'} class:on={mode === 'event'}
      onclick={() => setMode('event')} title="予定として入れる（日時を読み取り、準備のTodoも考えます）">予定</button>
    <button type="button" role="radio" aria-checked={mode === 'todo'} class:on={mode === 'todo'}
      onclick={() => setMode('todo')} title="予定に結びつかないTodoとして入れる（すぐ登録します）">Todo</button>
  </span>
  <label class="sr-only" for={id}>{mode === 'todo' ? 'Todoを入力' : '予定を入力'}</label>
  <input
    {id}
    bind:this={input}
    bind:value={text}
    placeholder={micState === 'recording' ? '聞いています…' : micState === 'transcribing' ? '文字にしています…'
      : mode === 'todo'
        ? (compact ? 'Todo（例: 金曜までに見積もり）' : 'Todoを入力すると、期限と優先度を読み取ってすぐ登録します（例: 金曜までに見積もりを送る／牛乳を買う）')
        : (compact ? '予定（例: 来週水曜15時に歯医者）' : '予定を入力すると、日時を読み取って準備のTodoを作ります（例: 来週水曜15時に〇〇社でプレゼン）')}
    disabled={busy || micState === 'transcribing'}
    autocomplete="off"
    oninput={warm}
  />
  <button class="primary" type="submit" disabled={busy || !text.trim() || micState !== 'idle'}>{busy ? '送信中' : '追加'}</button>
  <button type="button" class="plain mic" class:ready={micReady} class:rec={micState === 'recording'}
    class:wait={micState === 'starting' || micState === 'transcribing'}
    style:--level={level}
    onclick={mic} title={micTitle} aria-label={micState === 'recording' ? '録音を止める' : '音声で入力'}
    aria-pressed={micState === 'recording'} disabled={micState === 'transcribing' || micState === 'starting'}>
    {#if micState === 'recording'}
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor"/></svg>
    {:else}
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="1.5" width="5" height="8" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M3 7.5a5 5 0 0 0 10 0M8 12.5v2" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>
    {/if}
  </button>
</form>
{#if micState === 'recording'}
  <p class="voice-status" role="status">
    <span class="bar" aria-hidden="true"><span style:width="{Math.round(level * 100)}%"></span></span>
    <span class="num sec">{Math.floor(seconds)}秒</span>
    {#if compact}
      <span>話し終わると止まります</span>
    {:else}
      <span class="long">聞いています。話し終わると自動で止まります（最長{MAX_SECONDS}秒・Escでやめる）</span>
      <span class="short">話し終わると止まります</span>
    {/if}
  </p>
{:else if micState === 'transcribing'}
  <p class="voice-status" role="status">文字にしています…（終わると承認待ちに送ります）</p>
{/if}
{#if error}<p class="error-text err" role="alert">{error}</p>{/if}
{#if added}
  <div class="added" role="status">
    {#if editingAdded}
      <TodoEditor todo={added.todo} today={today ?? added.todo.due_date ?? ''}
        oncancel={() => (editingAdded = false)}
        onsaved={(t) => { added = { ...added, todo: t, warnings: [], llm_error: null }; editingAdded = false; onchange(t); }} />
    {:else}
      <p class="line">
        <span class="ok-mark" aria-hidden="true">✓</span>
        <span class="lead">Todoを登録しました</span>
        <strong class="t">{added.todo.title}</strong>
        <span class="pill num">{added.todo.due_date
          ? `${today ? relDay(added.todo.due_date, today) : md(added.todo.due_date)}${added.todo.due_time ? ' ' + added.todo.due_time : ''}まで`
          : '期限なし'}</span>
        <span class="pill {added.todo.priority}">優先度 {PRIORITY_LABEL[added.todo.priority]}</span>
      </p>
      {#if added.llm_error}
        <p class="warn">LLMに接続できなかったので、入力した文のまま期限なしで登録しました。必要なら直してください。</p>
      {:else if added.warnings?.includes('past_date')}
        <p class="warn">期限が過去の日付になったので、今日にしました。</p>
      {/if}
      <p class="acts">
        <button type="button" class="plain" onclick={() => { editingAdded = true; clearTimeout(hideTimer); }}>直す</button>
        <button type="button" class="plain" onclick={undoAdded}>取り消す</button>
        <button type="button" class="plain close" onclick={() => (added = null)} aria-label="閉じる">×</button>
      </p>
    {/if}
  </div>
{/if}

<style>
  .quick { display: flex; gap: 6px; align-items: center; }
  .mode { display: inline-flex; flex: none; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; }
  .mode button {
    border: none; border-radius: 0; padding: 5px 10px; background: var(--paper-raised); color: var(--ink-soft);
    font-size: var(--step--1);
  }
  .mode button + button { border-left: 1px solid var(--rule); }
  .mode button.on { background: var(--ink); color: #fff; font-weight: 700; }
  .compact .mode button { padding: 4px 6px; }
  .added {
    margin-top: 8px; padding: 6px 8px; background: var(--paper-raised);
    border: 1px solid var(--rule); border-left: 3px solid var(--ok); border-radius: var(--radius-s);
    font-size: var(--step--1);
  }
  .added p { margin: 0; }
  .line { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
  .ok-mark { color: var(--ok); font-weight: 700; }
  .lead { color: var(--ink-soft); }
  .t { overflow-wrap: anywhere; }
  .warn { color: var(--high); margin-top: 4px !important; }
  .acts { display: flex; gap: 4px; margin-top: 4px !important; }
  .acts button { padding: 0 6px; font-size: var(--step--1); }
  .acts .close { margin-left: auto; }
  .compact + .added, .compact ~ .added { margin-top: 6px; }
  .quick input { flex: 1; min-width: 0; padding: 7px 10px; }
  .quick.compact input { padding: 5px 8px; font-size: var(--step--1); }
  .quick.compact button.primary { padding: 4px 8px; font-size: var(--step--1); }
  .mic {
    color: var(--ink-faint); display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px; padding: 0; border-radius: 50%; flex: none; position: relative;
  }
  .mic.ready { color: var(--ink); }
  .mic.ready:hover { background: var(--paper); }
  .mic.rec, .mic.rec:hover {
    color: #fff; background: var(--high);
    box-shadow: 0 0 0 calc(2px + var(--level, 0) * 8px) rgba(200, 60, 45, .25);
    transition: box-shadow .08s linear;
  }
  .mic.wait { color: var(--ink-soft); animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .mic.wait { animation: none; } .mic.rec { transition: none; } }
  .voice-status {
    margin: 6px 0 0; font-size: var(--step--1); color: var(--ink-soft);
    display: flex; align-items: center; gap: 8px;
  }
  .sec { white-space: nowrap; }
  .short { display: none; }
  @media (max-width: 720px) { .long { display: none; } .short { display: inline; } }
  .bar { width: 56px; height: 6px; background: var(--rule); border-radius: 3px; overflow: hidden; flex: none; }
  .bar span { display: block; height: 100%; background: var(--high); }
  .err { margin: 4px 0 0; font-size: var(--step--1); }
</style>
