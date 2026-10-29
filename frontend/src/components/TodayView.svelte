<script>
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { addDays, eventWhen, md, relDay } from '../lib/format.js';
  import TodoItem from './TodoItem.svelte';
  import EventPanel from './EventPanel.svelte';

  let { version = 0, onchange = () => {} } = $props();
  let view = $state(null);
  let week = $state([]);
  let digest = $state(null);
  let error = $state('');
  let running = $state(false);
  let selected = $state(null);   // 開いている予定（詳細パネル）
  const hm = (s) => (s ? s.slice(11, 16) : '');

  async function load() {
    try {
      view = await api.today();
      [week, digest] = await Promise.all([
        api.events(addDays(view.date, 1), addDays(view.date, 7)),
        api.digest(),
      ]);
      error = '';
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    version;
    load();
  });

  async function runDigest() {
    running = true;
    try {
      digest = await api.runDigest();
    } catch (e) {
      error = e.message;
    } finally {
      running = false;
    }
  }

  function changed() {
    load();
    onchange();
    notifyChanged();
  }
</script>

{#if error}
  <p class="error-text">{error}</p>
{/if}

{#if view}
  <div class="today">
    {#if selected}
      <EventPanel {selected} today={view.date} onclose={() => (selected = null)} onchange={changed} />
    {/if}
    <section class="note-card">
      <div class="note-head">
        <h1>{md(view.date)}</h1>
        <button class="plain small" onclick={runDigest} disabled={running}>
          {running ? 'まとめを作成中' : digest?.missing ? '朝のまとめを作る' : '朝のまとめを作り直す'}
        </button>
      </div>
      {#if digest && !digest.missing}
        <p class="summary">{digest.summary}</p>
        {#if digest.suggestions?.length}
          <h2>やったほうがいいこと</h2>
          <ul class="suggest">
            {#each digest.suggestions as s}<li>{s}</li>{/each}
          </ul>
        {/if}
        {#if digest.llm_error}<p class="faint small-text">LLMを使えなかったため、件数だけのまとめです。</p>{/if}
      {:else}
        <p class="faint">朝のまとめは設定の時刻に自動で作られます。</p>
      {/if}
    </section>

    <div class="cols">
      <div>
        <section>
          <h2>今日の予定</h2>
          {#if view.events.length}
            <ol class="timeline">
              {#each view.events as e (e.id)}
                <li>
                  <span class="time num">{e.start_time ?? (e.is_deadline ? '締切' : '終日')}</span>
                  <button class="ev" onclick={() => (selected = { kind: 'event', id: e.id })}>
                    <span class="title">{e.title}</span>
                    <span class="faint sub">{e.category}{e.location ? `・${e.location}` : ''}{e.end_time ? `・〜${e.end_time}` : ''}</span>
                    {#if e.travel}<span class="leave num">{hm(e.travel.depart_at)} に出発（{e.travel.mode === 'car' ? '車' : '電車・バス'}）</span>{/if}
                  </button>
                </li>
              {/each}
            </ol>
          {:else}
            <p class="faint">今日の予定はありません。</p>
          {/if}
        </section>

        <section>
          <h2>この1週間の予定</h2>
          {#if week.length}
            <ol class="timeline week">
              {#each week as e (e.id)}
                <li>
                  <span class="time num">{relDay(e.start_date, view.date)}</span>
                  <button class="ev" onclick={() => (selected = { kind: 'event', id: e.id })}>
                    <span class="title">{e.title}</span>
                    <span class="faint sub">{eventWhen(e)}・{e.category}</span>
                    {#if e.travel}<span class="leave num">{hm(e.travel.depart_at)} に出発</span>{/if}
                  </button>
                </li>
              {/each}
            </ol>
          {:else}
            <p class="faint">この先1週間の予定はありません。</p>
          {/if}
        </section>
      </div>

      <div>
        <section>
          <h2>今日までにやること</h2>
          {#if view.overdue.length + view.due_today.length}
            <ul class="todos">
              {#each [...view.overdue, ...view.due_today] as t (t.id)}
                <TodoItem todo={t} today={view.date} onchange={changed} editable />
              {/each}
            </ul>
          {:else}
            <p class="faint">今日が期限のTodoはありません。</p>
          {/if}
          {#if view.done_today.length}
            <details>
              <summary class="faint">今日完了した {view.done_today.length} 件</summary>
              <ul class="todos">
                {#each view.done_today as t (t.id)}
                  <TodoItem todo={t} today={view.date} onchange={changed} editable />
                {/each}
              </ul>
            </details>
          {/if}
        </section>

        <section>
          <h2>今週中にやること</h2>
          {#if view.this_week.length}
            <ul class="todos">
              {#each view.this_week as t (t.id)}
                <TodoItem todo={t} today={view.date} onchange={changed} editable />
              {/each}
            </ul>
          {:else}
            <p class="faint">今週が期限のTodoはありません。</p>
          {/if}
        </section>

        <section>
          <h2>期限なしのTodo</h2>
          {#if view.no_due?.length}
            <ul class="todos">
              {#each view.no_due as t (t.id)}
                <TodoItem todo={t} today={view.date} onchange={changed} editable />
              {/each}
            </ul>
          {:else}
            <p class="faint">入力欄を「Todo」にして、期限を書かずに入れたものがここに並びます。</p>
          {/if}
        </section>
      </div>
    </div>
  </div>
{/if}

<style>
  .today { max-width: 1040px; position: relative; }
  .ev { all: unset; cursor: pointer; display: block; flex: 1; border-radius: var(--radius-s); }
  .ev:hover .title { text-decoration: underline; }
  .ev:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .leave {
    display: inline-block; margin-top: 2px; padding: 0 8px; border-radius: 10px;
    background: var(--medium-tint); color: var(--medium); font-size: var(--step--1); font-weight: 700;
  }
  .note-card {
    background: var(--paper-raised); border: 1px solid var(--rule); border-top: 3px solid var(--ink);
    padding: 16px 20px; margin-bottom: 24px; border-radius: 0 0 var(--radius-m) var(--radius-m);
  }
  .note-head { display: flex; justify-content: space-between; align-items: baseline; }
  h1 { font-size: var(--step-2); }
  h2 { font-size: var(--step-0); color: var(--ink-soft); margin: 0 0 8px; }
  .summary { font-size: var(--step-1); margin: 8px 0 12px; max-width: 40em; }
  .suggest { margin: 0; padding-left: 1.2em; }
  .small, .small-text { font-size: var(--step--1); }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
  section { margin-bottom: 24px; }
  ul.todos { margin: 0; padding: 0; }
  .timeline { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--rule); }
  .timeline li { display: flex; gap: 12px; padding: 6px 0 6px 12px; position: relative; }
  .timeline li::before {
    content: ''; position: absolute; left: -5px; top: 13px; width: 8px; height: 8px;
    border-radius: 50%; background: var(--ink);
  }
  .timeline.week li::before { background: var(--paper); border: 2px solid var(--ink-soft); width: 4px; height: 4px; }
  .time { min-width: 3.6em; color: var(--ink-soft); }
  .title { display: block; font-weight: 700; }
  .sub { font-size: var(--step--1); }
  details { margin-top: 8px; }
  summary { cursor: pointer; font-size: var(--step--1); margin-bottom: 6px; }
  @media (max-width: 860px) { .cols { grid-template-columns: 1fr; gap: 0; } }
</style>
