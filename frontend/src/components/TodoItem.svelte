<script>
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { PRIORITY_LABEL, relDay } from '../lib/format.js';
  import TodoEditor from './TodoEditor.svelte';

  /** editable: 「直す」で内容・期限・優先度を直せる */
  let { todo, today, onchange = () => {}, compact = false, showEvent = true, ondelete = null, highlight = false,
    editable = false } = $props();
  let busy = $state(false);
  let editing = $state(false);
  const done = $derived(todo.status === 'done');
  const overdue = $derived(!done && !!todo.due_date && todo.due_date < today);

  async function toggle() {
    busy = true;
    try {
      await api.updateTodo(todo.id, { status: done ? 'open' : 'done' });
      await notifyChanged();
      onchange();
    } finally {
      busy = false;
    }
  }
</script>

<li class="todo tab-{todo.priority}" class:done class:compact class:highlight class:editing>
  {#if editing}
    <TodoEditor {todo} {today} oncancel={() => (editing = false)} onsaved={() => { editing = false; onchange(); }} />
  {:else}
  <label>
    <input type="checkbox" checked={done} disabled={busy} onchange={toggle} />
    <span class="title">{todo.title}</span>
  </label>
  <span class="meta">
    {#if showEvent && todo.event_title}<span class="faint ev">{todo.event_title}</span>{/if}
    {#if todo.due_date}
      <span class="pill {overdue ? 'high' : ''} num">
        {overdue ? '期限切れ ' : ''}{relDay(todo.due_date, today)}{todo.due_time ? ' ' + todo.due_time : ''}
      </span>
    {:else if !compact}
      <span class="pill faint">期限なし</span>
    {/if}
    {#if !compact}<span class="pill {todo.priority}">{PRIORITY_LABEL[todo.priority]}</span>{/if}
    {#if editable && !done}<button class="plain small" onclick={() => (editing = true)} aria-label="「{todo.title}」を直す">直す</button>{/if}
    {#if ondelete}<button class="plain danger del" onclick={ondelete} aria-label="「{todo.title}」を削除">削除</button>{/if}
  </span>
  {/if}
</li>

<style>
  .todo {
    list-style: none;
    display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;
    background: var(--paper-raised);
    padding: 6px 8px 6px 8px;
    border-radius: 0 var(--radius-s) var(--radius-s) 0;
    margin-bottom: 4px;
  }
  .todo.compact { padding: 4px 6px; font-size: var(--step--1); }
  label { display: flex; gap: 6px; align-items: flex-start; cursor: pointer; min-width: 0; }
  input { margin-top: 3px; flex: none; }
  .title { overflow-wrap: anywhere; }
  .done .title { text-decoration: line-through; color: var(--ink-faint); }
  .meta { display: flex; gap: 4px; align-items: center; flex: none; flex-wrap: wrap; justify-content: flex-end; }
  .highlight { outline: 2px solid var(--medium); }
  .del, .small { font-size: var(--step--1); padding: 0 4px; }
  .todo.editing { display: block; padding: 4px; }
  .ev { font-size: var(--step--1); max-width: 10em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
