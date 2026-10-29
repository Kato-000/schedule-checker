<script>
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { eventWhen, PRIORITIES, PRIORITY_LABEL } from '../lib/format.js';
  import EventFields from './EventFields.svelte';
  import TodoItem from './TodoItem.svelte';
  import LookupBox from './LookupBox.svelte';
  import RouteBox from './RouteBox.svelte';
  import MapBox from './MapBox.svelte';

  let { selected, today, onclose = () => {}, onchange = () => {} } = $props();
  let event = $state(null);
  let todo = $state(null);       // 予定に結びつかないTodoを開いたとき
  let draft = $state(null);      // 編集中の予定
  let categories = $state([]);
  let googleMode = $state('off');
  let error = $state('');
  let saving = $state(false);
  let newTodo = $state({ title: '', due_date: '', priority: 'medium' });

  async function load() {
    error = '';
    try {
      if (!categories.length) {
        const m = await api.meta();
        categories = m.categories;
        googleMode = m.google_mode;
      }
      if (selected.kind === 'event') {
        event = await api.event(selected.id);
        todo = null;
        newTodo = { title: '', due_date: event.start_date, priority: 'medium' };
      } else {
        todo = await api.todo(selected.id);
        event = null;
      }
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    selected;
    draft = null;
    load();
  });

  async function done(fn) {
    saving = true;
    error = '';
    try {
      await fn();
      await notifyChanged();
      onchange();
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  const saveEvent = () => done(async () => { await api.updateEvent(event.id, draft); draft = null; });
  const addTodo = () => done(async () => {
    await api.createTodo({ ...newTodo, event_id: event.id });
  });
  const removeTodo = (id) => done(() => api.deleteTodo(id));

  async function removeEvent() {
    if (!confirm(`「${event.title}」とそのTodoを削除します。よろしいですか？`)) return;
    await done(() => api.deleteEvent(event.id));
    onclose();
  }
  async function removeLooseTodo() {
    await done(() => api.deleteTodo(todo.id));
    onclose();
  }
</script>

<aside class="panel" aria-label="予定の詳細">
  <div class="head">
    <h2>{event ? '予定' : 'Todo'}</h2>
    <button class="plain" onclick={onclose} aria-label="閉じる">閉じる</button>
  </div>
  {#if error}<p class="error-text">{error}</p>{/if}

  {#if event}
    {#if draft}
      <EventFields bind:event={draft} {categories} idPrefix="panel"
        showLocalOnly={googleMode === 'two_way' && event.source === 'local'} />
      <div class="btns">
        <button class="primary" onclick={saveEvent} disabled={saving}>保存</button>
        <button onclick={() => (draft = null)}>やめる</button>
      </div>
    {:else}
      <h3>{event.title}</h3>
      <p class="muted when">{eventWhen(event)}</p>
      <p class="tags">
        <span class="pill">{event.category}</span>
        {#if event.is_deadline}<span class="pill high">締切</span>{/if}
        {#if event.location}<span class="pill">{event.location}</span>{/if}
        {#if event.source === 'google'}<span class="pill medium">Googleから</span>
        {:else if event.local_only}<span class="pill">ローカル限定</span>
        {:else if event.google_event_id}<span class="pill medium">Googleと同期</span>{/if}
        {#if event.needs_push && !event.local_only && googleMode === 'two_way'}<span class="pill">送信待ち</span>{/if}
      </p>
      {#if event.address}<p class="small addr">{event.address}</p>{/if}
      {#if event.push_error}<p class="error-text small">Googleへ送れませんでした: {event.push_error}</p>{/if}
      {#if event.source === 'google' && googleMode === 'import'}
        <p class="faint small">取り込みのみの設定なので、ここで変えた内容はGoogleには送られず、Google側の変更で上書きされます。</p>
      {/if}
      <div class="btns">
        <button onclick={() => (draft = { ...event })}>編集</button>
        <button class="danger" onclick={removeEvent} disabled={saving}>削除</button>
      </div>
      <LookupBox {event} onapply={async (f, v) => {
        await api.updateEvent(event.id, { [f]: v });
        await notifyChanged();
        onchange();
        await load();
      }} />
      <RouteBox {event} onchange={() => done(async () => {})} />
      {#key event.id}
        <MapBox place={event.address || event.location || ''} title={event.title} />
      {/key}
    {/if}

    <h2 class="sub">準備のTodo</h2>
    {#if event.todos.length}
      <ul class="todos">
        {#each event.todos as t (t.id)}
          <TodoItem todo={t} {today} showEvent={false} highlight={selected.todoId === t.id} editable
            onchange={() => done(async () => {})} ondelete={() => removeTodo(t.id)} />
        {/each}
      </ul>
    {:else}
      <p class="faint">Todoはありません。</p>
    {/if}
    <form class="add" onsubmit={(e) => { e.preventDefault(); if (newTodo.title.trim()) addTodo(); }}>
      <input bind:value={newTodo.title} placeholder="Todoを追加" aria-label="追加するTodo" />
      <input type="date" bind:value={newTodo.due_date} aria-label="期限" />
      <select bind:value={newTodo.priority} aria-label="優先度">
        {#each PRIORITIES as p}<option value={p}>{PRIORITY_LABEL[p]}</option>{/each}
      </select>
      <button type="submit" disabled={saving || !newTodo.title.trim()}>追加</button>
    </form>
  {:else if todo}
    <ul class="todos"><TodoItem {todo} {today} editable onchange={() => done(async () => {})} /></ul>
    <p class="faint small">予定に結びつかないTodoです。</p>
    <div class="btns"><button class="danger" onclick={removeLooseTodo}>削除</button></div>
  {/if}
</aside>

<style>
  .panel {
    position: absolute; top: 0; right: 0; bottom: 0; width: min(420px, 100%); z-index: 10;
    background: var(--paper); border-left: 2px solid var(--ink);
    padding: 16px; overflow-y: auto; box-shadow: -8px 0 24px rgba(31, 47, 74, .12);
  }
  .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  h2 { font-size: var(--step--1); color: var(--ink-soft); }
  h2.sub { margin: 20px 0 6px; }
  h3 { font-size: var(--step-2); }
  .when { margin: 4px 0; }
  .tags { display: flex; gap: 4px; margin: 4px 0 8px; flex-wrap: wrap; }
  .small { font-size: var(--step--1); margin: 4px 0; }
  .btns { display: flex; gap: 6px; margin-top: 10px; }
  .todos { margin: 0; padding: 0; }
  .add { display: grid; grid-template-columns: 1fr 130px 56px auto; gap: 4px; margin-top: 8px; }
</style>
