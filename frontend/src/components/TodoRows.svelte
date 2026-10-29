<script>
  // 承認前のTodoの編集行
  import { PRIORITIES, PRIORITY_LABEL, relDay } from '../lib/format.js';

  let { todos = $bindable(), defaultDate, today } = $props();

  function add() {
    todos = [...todos, { title: '', due_date: defaultDate ?? today, due_time: null, priority: 'medium' }];
  }
  function remove(i) {
    todos = todos.filter((_, j) => j !== i);
  }
</script>

{#if todos.length}
  <ul class="rows">
    {#each todos as t, i}
      <li class="tab-{t.priority}">
        <input class="title" bind:value={t.title} placeholder="やること" aria-label="やること" />
        <input type="date" bind:value={t.due_date} aria-label="期限の日付" />
        <input type="time" value={t.due_time ?? ''} oninput={(e) => (t.due_time = e.currentTarget.value || null)} aria-label="期限の時刻（任意）" />
        <select bind:value={t.priority} aria-label="優先度">
          {#each PRIORITIES as p}<option value={p}>優先度 {PRIORITY_LABEL[p]}</option>{/each}
        </select>
        <span class="rel faint num">{relDay(t.due_date, today)}</span>
        <button class="plain danger" onclick={() => remove(i)} aria-label="このTodoを削除">削除</button>
      </li>
    {/each}
  </ul>
{:else}
  <p class="faint none">Todoはありません。必要なら追加してください。</p>
{/if}
<button class="plain add" onclick={add}>＋ Todoを追加</button>

<style>
  .rows { list-style: none; margin: 0; padding: 0; }
  li {
    display: grid; grid-template-columns: 1fr 140px 116px 104px 56px auto; gap: 6px; align-items: center;
    background: var(--paper-raised); padding: 5px 6px 5px 8px; margin-bottom: 4px;
    border-radius: 0 var(--radius-s) var(--radius-s) 0;
  }
  .rel { font-size: var(--step--1); text-align: right; }
  .none { margin: 4px 0; }
  .add { color: var(--medium); margin-top: 2px; }
  @media (max-width: 760px) {
    li { grid-template-columns: 1fr 1fr; }
    .title { grid-column: 1 / -1; }
  }
</style>
