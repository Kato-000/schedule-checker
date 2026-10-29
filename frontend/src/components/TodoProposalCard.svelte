<script>
  // 予定に結びつかないTodoの案（音声入力で「Todo」を選んでいたとき）
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { PRIORITIES, PRIORITY_LABEL, relDay } from '../lib/format.js';

  let { proposal, today, onresolved = () => {} } = $props();

  let t = $state(null);          // 編集中のTodo
  let noDue = $state(false);
  let busy = $state(false);
  let error = $state('');
  let approvedMsg = $state('');
  const uid = $derived(`tp${proposal.id}`);
  const reading = $derived(proposal.status === 'reading');

  // 読み取りが終わったときに一度だけ、編集用の値を用意する
  $effect(() => {
    if (proposal.status === 'pending' && t === null && proposal.todos?.length) {
      const s = proposal.todos[0];
      t = { title: s.title, due_date: s.due_date ?? today, due_time: s.due_time ?? '', priority: s.priority };
      noDue = !s.due_date;
    }
  });

  async function act(fn) {
    busy = true;
    error = '';
    try { await fn(); } catch (e) { error = e.message; } finally { busy = false; }
  }

  const approve = () => act(async () => {
    await api.approve(proposal.id, null, [{
      title: t.title.trim(), due_date: noDue ? null : t.due_date,
      due_time: noDue || !t.due_time ? null : t.due_time, priority: t.priority,
    }]);
    approvedMsg = 'Todoを登録しました。';
    await notifyChanged();
    setTimeout(onresolved, 900);
  });
  const reject = () => act(async () => {
    await api.reject(proposal.id);
    await notifyChanged();
    onresolved();
  });
</script>

<article class="card" class:done={approvedMsg} aria-busy={reading}>
  <p class="input">
    <span class="pill todo">Todo</span>
    {#if proposal.source === 'voice'}<span class="pill">音声</span>{/if}
    <span class="faint">聞き取った内容</span> {proposal.input_text}
  </p>

  {#if reading}
    <p class="working">期限と優先度を読み取っています…</p>
  {:else if t}
    {#if proposal.error}<p class="note" role="note">{proposal.error}。内容を確かめて直してください。</p>{/if}
    {#if proposal.warnings?.includes('past_date')}<p class="note" role="note">期限が過去の日付になったので、今日にしました。</p>{/if}
    <div class="fields">
      <label class="title">
        <span class="lbl">内容</span>
        <input id="{uid}-title" bind:value={t.title} autocomplete="off" />
      </label>
      <div class="row">
        <label><span class="lbl">期限</span>
          <input type="date" bind:value={t.due_date} disabled={noDue} />
        </label>
        <label><span class="lbl">時刻</span>
          <input type="time" bind:value={t.due_time} disabled={noDue} />
        </label>
        <label class="check"><input type="checkbox" bind:checked={noDue} />期限なし</label>
        {#if !noDue && t.due_date}<span class="faint rel">{relDay(t.due_date, today)}</span>{/if}
        <span class="prio" role="radiogroup" aria-label="優先度">
          {#each PRIORITIES as p}
            <label class="p p-{p}" class:on={t.priority === p}>
              <input type="radio" name="{uid}-prio" value={p} bind:group={t.priority} />{PRIORITY_LABEL[p]}
            </label>
          {/each}
        </span>
      </div>
    </div>
    {#if approvedMsg}
      <p class="ok" role="status">{approvedMsg}</p>
    {:else}
      <div class="btns">
        <button class="primary" onclick={approve} disabled={busy || !t.title.trim()}>承認して登録</button>
        <button class="danger plain" onclick={reject} disabled={busy}>却下</button>
      </div>
    {/if}
    {#if error}<p class="error-text">{error}</p>{/if}
  {/if}
</article>

<style>
  .card {
    background: var(--paper-raised); border: 1px solid var(--rule); border-top: 3px solid var(--ok);
    border-radius: 0 0 var(--radius-m) var(--radius-m); padding: 14px 18px 16px; margin-bottom: 20px;
  }
  .card.done { opacity: .8; }
  .input { margin: 0 0 10px; font-size: var(--step--1); display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
  .pill.todo { background: var(--ok); color: #fff; }
  .working { color: var(--ink-soft); margin: 8px 0; }
  .working::before {
    content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--ok); margin-right: 8px; animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse { 50% { opacity: .25; } }
  @media (prefers-reduced-motion: reduce) { .working::before { animation: none; } }
  .note {
    margin: 0 0 10px; padding: 6px 10px; background: var(--high-tint); color: var(--high);
    border-radius: var(--radius-s); font-size: var(--step--1);
  }
  .fields { display: flex; flex-direction: column; gap: 8px; }
  .lbl { display: block; font-size: var(--step--1); color: var(--ink-soft); margin-bottom: 2px; }
  .title input { width: 100%; box-sizing: border-box; }
  .row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
  .row input[type='date'] { width: 10em; }
  .row input[type='time'] { width: 7em; }
  .check { display: inline-flex; gap: 4px; align-items: center; font-size: var(--step--1); padding-bottom: 6px; }
  .rel { font-size: var(--step--1); padding-bottom: 6px; }
  .prio { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; margin-left: auto; }
  .p { position: relative; padding: 4px 12px; cursor: pointer; font-size: var(--step--1); background: var(--paper-raised); }
  .p input { position: absolute; inset: 0; margin: 0; opacity: 0; pointer-events: none; }
  .p + .p { border-left: 1px solid var(--rule); }
  .p.on.p-high { background: var(--high); color: #fff; }
  .p.on.p-medium { background: var(--medium); color: #fff; }
  .p.on.p-low { background: #5f6b7d; color: #fff; }
  .p:focus-within { outline: 2px solid var(--ink); outline-offset: -2px; }
  .btns { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .ok { color: var(--ok); margin: 12px 0 0; font-weight: 700; }
</style>
