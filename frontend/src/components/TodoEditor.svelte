<script>
  // Todoの内容・期限・優先度を直す小さなフォーム
  import { untrack } from 'svelte';
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { PRIORITIES, PRIORITY_LABEL } from '../lib/format.js';

  let { todo, today, onsaved = () => {}, oncancel = () => {} } = $props();
  // 開いたときの内容から編集を始める（あとで元のTodoが読み直されても、入力中の内容は変えない）
  const t0 = untrack(() => ({ ...todo, today }));
  const uid = `te-${t0.id}`;
  // 予定に結びつくTodoは期限が必須
  const canClear = !t0.event_id;

  let title = $state(t0.title);
  let noDue = $state(!t0.due_date);
  let date = $state(t0.due_date ?? t0.today);
  let time = $state(t0.due_time ?? '');
  let priority = $state(t0.priority);
  let busy = $state(false);
  let error = $state('');

  async function save(e) {
    e.preventDefault();
    if (!title.trim()) { error = '内容を入力してください'; return; }
    busy = true;
    error = '';
    try {
      const t = await api.updateTodo(t0.id, {
        title: title.trim(),
        due_date: noDue ? null : date,
        due_time: noDue || !time ? null : time,
        priority,
      });
      await notifyChanged();
      onsaved(t);
    } catch (err) {
      error = err.message;
    } finally {
      busy = false;
    }
  }
</script>

<form class="editor" onsubmit={save}>
  <label class="sr-only" for="{uid}-title">内容</label>
  <input id="{uid}-title" class="title" bind:value={title} autocomplete="off" />
  <div class="row">
    <label class="sr-only" for="{uid}-date">期限</label>
    <input id="{uid}-date" type="date" bind:value={date} disabled={noDue} />
    <label class="sr-only" for="{uid}-time">時刻</label>
    <input id="{uid}-time" type="time" bind:value={time} disabled={noDue} title="時刻（なくてもよい）" />
    {#if canClear}
      <label class="check"><input type="checkbox" bind:checked={noDue} />期限なし</label>
    {/if}
  </div>
  <div class="row">
    <span class="prio" role="radiogroup" aria-label="優先度">
      {#each PRIORITIES as p}
        <label class="p p-{p}" class:on={priority === p}>
          <input type="radio" name="{uid}-prio" value={p} bind:group={priority} />{PRIORITY_LABEL[p]}
        </label>
      {/each}
    </span>
    <span class="btns">
      <button type="button" class="plain" onclick={oncancel}>やめる</button>
      <button class="primary" type="submit" disabled={busy}>保存</button>
    </span>
  </div>
  {#if error}<p class="error-text">{error}</p>{/if}
</form>

<style>
  .editor { display: flex; flex-direction: column; gap: 6px; padding: 8px; background: var(--paper); border: 1px solid var(--rule); border-radius: var(--radius-s); }
  .title { width: 100%; box-sizing: border-box; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .row input[type='date'] { width: 9.5em; }
  .row input[type='time'] { width: 6.5em; }
  .check { display: inline-flex; gap: 4px; align-items: center; font-size: var(--step--1); }
  .prio { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius-s); overflow: hidden; }
  .p { position: relative; padding: 2px 10px; cursor: pointer; font-size: var(--step--1); background: var(--paper-raised); }
  .p input { position: absolute; inset: 0; margin: 0; opacity: 0; pointer-events: none; }
  .p + .p { border-left: 1px solid var(--rule); }
  .p.on.p-high { background: var(--high); color: #fff; }
  .p.on.p-medium { background: var(--medium); color: #fff; }
  .p.on.p-low { background: #5f6b7d; color: #fff; }
  .p:focus-within { outline: 2px solid var(--ink); outline-offset: -2px; }
  .btns { margin-left: auto; display: inline-flex; gap: 4px; }
  .error-text { margin: 0; font-size: var(--step--1); }
</style>
