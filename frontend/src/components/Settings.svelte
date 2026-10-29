<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { notifyChanged } from '../lib/desktop.js';
  import { setIdleSeconds } from '../lib/activity.js';
  import LanSettings from './LanSettings.svelte';
  import GoogleSettings from './GoogleSettings.svelte';
  import VoiceSettings from './VoiceSettings.svelte';
  import NetSettings from './NetSettings.svelte';

  let { local = true, onchange = () => {} } = $props();
  let s = $state(null);
  let time = $state('07:00');
  let idle = $state(60);
  let msg = $state('');
  let error = $state('');

  onMount(async () => {
    try {
      s = await api.settings();
      time = s.digest_time;
      idle = Number(s.idle_seconds || 60);
    } catch (e) {
      error = e.message;
    }
  });

  async function save(fields) {
    msg = error = '';
    try {
      s = await api.saveSettings(fields);
      time = s.digest_time;
      idle = Number(s.idle_seconds || 60);
      setIdleSeconds(idle);
      msg = '保存しました';
      notifyChanged();   // ウィジェットにも反映する
    } catch (e) {
      error = e.message;
    }
  }
</script>

<div class="settings">
  <h1>設定</h1>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if s}
    <section>
      <h2>朝のまとめ</h2>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ digest_time: time }); }}>
        <label for="digest-time">毎日作る時刻</label>
        <input id="digest-time" type="time" bind:value={time} />
        <button type="submit">保存</button>
      </form>
      <label class="check">
        <input type="checkbox" checked={s.digest_notify === '1'} onchange={(e) => save({ digest_notify: e.currentTarget.checked })} />
        Windowsの通知で知らせる
      </label>
    </section>

    <section>
      <h2>Todoの手本とルール</h2>
      <label class="check">
        <input type="checkbox" checked={s.use_seed_examples === '1'} onchange={(e) => save({ use_seed_examples: e.currentTarget.checked })} />
        初期手本と初期ルールを使う
      </label>
      <label class="check">
        <input type="checkbox" checked={s.rules_auto === '1'} onchange={(e) => save({ rules_auto: e.currentTarget.checked })} />
        承認時の修正から、自分ルールの案を自動で作る
      </label>
      <p class="muted note">自分で承認した記録が同じ種類で3件たまると、その種類では初期手本は使われなくなります。
        初期手本は backend フォルダの seed_examples.json で編集できます。</p>
    </section>
    {#if local}
      <section>
        <h2>ウィジェット</h2>
        <label class="check">
          <input type="checkbox" checked={s.widget_autohide === '1'} onchange={(e) => save({ widget_autohide: e.currentTarget.checked })} />
          画面の左右・上の端に寄せたら、使っていないときは自動でたたむ
        </label>
        <p class="muted note">たたむと、端に小さなつまみ（今日の日付と、今日までのTodoの数）だけが残ります。マウスを乗せると開きます。</p>
      </section>
    {/if}
    <section>
      <h2>動作の軽さ</h2>
      <form class="row" onsubmit={(e) => { e.preventDefault(); save({ idle_seconds: Number(idle) }); }}>
        <label for="idle-sec">操作がないまま</label>
        <input id="idle-sec" class="num-in" type="number" min="30" max="1800" step="10" bind:value={idle} />
        <span>秒たったら軽くする</span>
        <button type="submit">保存</button>
      </form>
      <p class="muted note">軽くすると、LLMと文字起こしのモデルをメモリ（GPU）から外し、画面の自動更新も止めます。
        マウスやキーを操作するとすぐ最新の表示に戻り、入力欄に文字を入れ始めた時点でLLMの読み込みを始めます。
        短くするほど軽くなりますが、久しぶりに使うときは読み込みに数秒〜十数秒かかります。</p>
    </section>
    {#if msg}<p class="ok" role="status">{msg}</p>{/if}

    {#if local}
      <VoiceSettings />
      <NetSettings />
      <LanSettings />
      <GoogleSettings {onchange} />
    {:else}
      <section>
        <h2>音声入力・ネット連携・スマホからの閲覧・Googleカレンダー連携</h2>
        <p class="muted note">これらの設定は、安全のためPCの画面からだけ変更できます。</p>
      </section>
    {/if}
  {/if}
</div>

<style>
  .settings { max-width: 680px; }
  h1 { font-size: var(--step-2); margin-bottom: 16px; }
  h2 { font-size: var(--step-0); margin-bottom: 8px; }
  section { padding: 16px 0; border-top: 1px solid var(--rule); }
  .row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
  .check { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
  .note { font-size: var(--step--1); margin: 6px 0 0; }
  .ok { color: var(--ok); }
  .num-in { width: 5.5em; }
</style>
