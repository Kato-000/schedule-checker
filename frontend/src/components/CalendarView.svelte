<script>
  import { onMount } from 'svelte';
  import { Calendar } from '@fullcalendar/core';
  import jaLocale from '@fullcalendar/core/locales/ja';
  import dayGridPlugin from '@fullcalendar/daygrid';
  import timeGridPlugin from '@fullcalendar/timegrid';
  import { api } from '../lib/api.js';
  import { addDays, parseISO, toISO } from '../lib/format.js';
  import EventPanel from './EventPanel.svelte';

  let { mode = 'week', version = 0, today = null, onchange = () => {} } = $props();
  let el = $state(null);      // カレンダーを描く要素
  let calendar;
  let error = $state('');
  let selected = $state(null); // { kind: 'event' | 'todo', id }

  function toFcEvent(e) {
    const allDay = !e.start_time;
    const start = allDay ? e.start_date : `${e.start_date}T${e.start_time}`;
    let end;
    if (allDay) {
      end = e.end_date ? addDays(e.end_date, 1) : undefined;  // 終日の終わりは翌日（含まない）
    } else if (e.end_time || e.end_date) {
      end = `${e.end_date ?? e.start_date}T${e.end_time ?? e.start_time}`;
    }
    return {
      id: `e${e.id}`, title: e.title, start, end, allDay,
      classNames: ['sc-event', e.is_deadline ? 'sc-deadline' : ''],
      extendedProps: { kind: 'event', id: e.id },
    };
  }

  function toFcTodo(t) {
    return {
      id: `t${t.id}`, title: `${t.status === 'done' ? '✓' : '□'} ${t.title}`,
      start: t.due_date, allDay: true,
      classNames: ['sc-todo', `sc-${t.priority}`, t.status === 'done' ? 'sc-done' : ''],
      extendedProps: { kind: 'todo', id: t.id, eventId: t.event_id },
    };
  }

  // ---- 予定の読み込み（前後5週分をまとめて取り、少しずつずらしたときは読み直さない） ----
  let cache = null;   // { start, end, items }
  let holidays = $state({});   // 祝日 {"YYYY-MM-DD": "名前"}（PCの中で計算したもの）
  async function source(info, success, failure) {
    const start = toISO(info.start);
    const end = toISO(new Date(info.end.getTime() - 1));
    if (cache && cache.start <= start && end <= cache.end) {
      success(cache.items);
      return;
    }
    const from = addDays(start, -35);
    const to = addDays(end, 35);
    try {
      const [events, todos, hols] = await Promise.all([
        api.events(from, to), api.todos(from, to), api.holidays(from, to).catch(() => ({})),
      ]);
      holidays = { ...holidays, ...hols };
      error = '';
      cache = { start: from, end: to, items: [...events.map(toFcEvent), ...todos.map(toFcTodo)] };
      success(cache.items);
    } catch (e) {
      error = e.message;
      failure(e);
    }
  }

  function reload() {
    cache = null;
    calendar?.refetchEvents();
  }

  // ---- 表示範囲 ----
  // 週: 35日分を横に並べ、画面には7日分を出す。横スクロールで日が流れる
  // 月: 15週分を縦に並べ、画面には6週分を出す。縦スクロールで週が流れる
  // どちらも端に近づいたら、見えている位置はそのままで並べる範囲を付け替える
  const isMonth = mode === 'month';
  const SPAN = isMonth ? 15 : 35;       // 並べておく数（月は週、週は日）
  const CENTER = isMonth ? 5 : 14;      // 付け替えたとき、見えている最初の行・列を何番目に置くか
  const EDGE = isMonth ? 2 : 4;         // 端からこの数以内に来たら付け替える
  const VISIBLE = isMonth ? 6 : 7;      // 画面に出す数
  let title = $state('');
  let focusKey = $state('');            // 月表示で見ている月（YYYY-MM）。それ以外の日は薄く
  let scroller = $state(null);          // スクロールの枠
  let unit = 0;                         // 1列（週）・1行（月）の大きさ（px）
  let axisW = 48;                       // 週表示の時刻の列の幅（px）
  let rangeStart = null;                // 並べている最初の日
  let pendingIdx = null;                // 付け替えたあとに戻す位置（列・行の数）
  const todayISO = () => today ?? toISO(new Date());
  function sundayOf(isoDate) {
    const d = parseISO(isoDate);
    d.setDate(d.getDate() - d.getDay());
    return toISO(d);
  }

  const pos = () => (isMonth ? scroller.scrollTop : scroller.scrollLeft);
  const setPos = (v) => { if (isMonth) scroller.scrollTop = v; else scroller.scrollLeft = v; };
  const visibleIdx = () => (unit && scroller ? pos() / unit : CENTER);
  const dateAt = (i) => { const d = new Date(rangeStart); d.setDate(d.getDate() + (isMonth ? 7 * i : i)); return d; };

  function weekTitle(s) {
    const e = new Date(s);
    e.setDate(e.getDate() + 6);
    return s.getMonth() === e.getMonth()
      ? `${s.getFullYear()}年${s.getMonth() + 1}月${s.getDate()}日 – ${e.getDate()}日`
      : `${s.getFullYear()}年${s.getMonth() + 1}月${s.getDate()}日 – ${e.getMonth() + 1}月${e.getDate()}日`;
  }

  // 見出し（タイトル）と、月表示の「見ている月」を、今のスクロール位置から決める
  let titleRaf = 0;
  function updateTitle() {
    if (!rangeStart) return;
    cancelAnimationFrame(titleRaf);
    titleRaf = requestAnimationFrame(() => {
      const first = Math.round(visibleIdx());
      if (isMonth) {
        const mid = dateAt(first + 2);         // 6週のうち3週目の水曜あたりの月
        mid.setDate(mid.getDate() + 3);
        title = `${mid.getFullYear()}年${mid.getMonth() + 1}月`;
        focusKey = `${mid.getFullYear()}-${String(mid.getMonth() + 1).padStart(2, '0')}`;
      } else {
        title = weekTitle(dateAt(first));
      }
    });
  }

  function datesSet(info) {
    rangeStart = new Date(info.view.currentStart);
    if (pendingIdx !== null && unit && scroller) {
      const other = isMonth ? scroller.scrollLeft : scroller.scrollTop;   // もう一方の位置はそのまま
      setPos(pendingIdx * unit);
      requestAnimationFrame(() => { if (isMonth) scroller.scrollLeft = other; else scroller.scrollTop = other; });
      pendingIdx = null;
    }
    updateTitle();
  }

  // 大きさを「画面に週は7日・月は6週」に合わせる
  function layout() {
    if (!scroller || !calendar) return;
    const keep = unit ? visibleIdx() : null;
    if (isMonth) {
      const head = el.querySelector('.fc-col-header')?.getBoundingClientRect().height ?? 28;
      const h = Math.max(64, Math.floor((scroller.clientHeight - head) / VISIBLE) - 1);   // 1は罫線の分
      if (h === unit) return;
      unit = h;
      scroller.style.setProperty('--row-h', `${h}px`);
      scroller.style.setProperty('--head-h', `${Math.ceil(head)}px`);
      // 1日の欄に入るだけ予定を並べ、あふれた分は「他◯件」
      calendar.setOption('dayMaxEventRows', Math.max(1, Math.floor((h - 28) / 22)));
    } else {
      const ax = el.querySelector('.fc-col-header .fc-timegrid-axis');
      if (ax) axisW = Math.ceil(ax.getBoundingClientRect().width) || axisW;
      const w = Math.max(40, Math.floor((scroller.clientWidth - axisW) / VISIBLE));
      if (w === unit) return;
      unit = w;
      el.style.width = `${axisW + SPAN * unit}px`;
      scroller.style.setProperty('--axis-w', `${axisW}px`);
    }
    calendar.updateSize();
    setPos((keep ?? CENTER) * unit);
    updateTitle();
  }

  let settleTimer = 0;
  function onscroll() {
    if (!rangeStart) return;
    updateTitle();
    clearTimeout(settleTimer);
    settleTimer = setTimeout(recenter, 140);
  }
  function recenter() {
    if (!scroller || !calendar) return;   // 画面を離れたあと
    if (drag || glide) { clearTimeout(settleTimer); settleTimer = setTimeout(recenter, 140); return; }
    const idx = visibleIdx();
    const first = Math.round(idx);
    if (first >= EDGE && first <= SPAN - VISIBLE - EDGE) return;
    const shift = first - CENTER;
    pendingIdx = idx - shift;
    calendar.gotoDate(toISO(dateAt(shift)));
  }
  function scrollUnits(n) {
    scroller.scrollBy(isMonth ? { top: n * unit, behavior: 'smooth' } : { left: n * unit, behavior: 'smooth' });
  }
  // isoDate を含む週（月表示）・その日（週表示）を、見えている最初の行・列にする
  function goDate(isoDate) {
    const target = parseISO(isMonth ? sundayOf(isoDate) : isoDate);
    const days = Math.round((target - rangeStart) / 86400000);
    const i = isMonth ? Math.round(days / 7) : days;
    if (i >= 0 && i <= SPAN - VISIBLE) {
      scroller.scrollTo(isMonth ? { top: i * unit, behavior: 'smooth' } : { left: i * unit, behavior: 'smooth' });
    } else {
      pendingIdx = CENTER;
      const s = new Date(target);
      s.setDate(s.getDate() - (isMonth ? 7 * CENTER : CENTER));
      calendar.gotoDate(toISO(s));
    }
  }

  function step(n) {
    if (n) scrollUnits(n);
  }
  // ボタン：週は7日、月は前後の月の初めへ
  function page(dir) {
    if (!isMonth) { scrollUnits(7 * dir); return; }
    const [y, m] = focusKey.split('-').map(Number);
    goDate(toISO(new Date(y, m - 1 + dir, 1)));
  }
  function goToday() {
    const t = todayISO();
    goDate(isMonth ? t.slice(0, 8) + '01' : sundayOf(t));
  }

  let suppressClick = false;
  // ---- つかんで動かす（左ボタン・右ボタンどちらでも）。週は左右と上下、月は上下 ----
  const DRAG_START = 5;      // これだけ動いたらドラッグとみなす（それ未満はクリック）
  let drag = null;           // { x, y, left, top, moved, button, samples }
  let glide = 0;             // 手を離したあとの惰性スクロール
  function onDragDown(e) {
    if (e.pointerType !== 'mouse' || (e.button !== 0 && e.button !== 2)) return;
    // スクロールバーの上ではブラウザに任せる
    const r = scroller.getBoundingClientRect();
    if (e.clientX - r.left >= scroller.clientWidth || e.clientY - r.top >= scroller.clientHeight) return;
    cancelAnimationFrame(glide);
    glide = 0;
    drag = { x: e.clientX, y: e.clientY, left: scroller.scrollLeft, top: scroller.scrollTop, moved: false,
             button: e.button, samples: [[performance.now(), e.clientX, e.clientY]] };
  }
  function onDragMove(e) {
    if (!drag) return;
    const dx = isMonth ? 0 : e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < DRAG_START) return;
      drag.moved = true;
      scroller.setPointerCapture?.(e.pointerId);
      scroller.classList.add('dragging');
    }
    if (!isMonth) scroller.scrollLeft = drag.left - dx;
    scroller.scrollTop = drag.top - dy;
    drag.samples.push([performance.now(), e.clientX, e.clientY]);
    if (drag.samples.length > 6) drag.samples.shift();
  }
  function onDragUp(e) {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (!d.moved) return;          // 動かしていなければ普通のクリック（右ボタンならメニュー）
    scroller.releasePointerCapture?.(e.pointerId);
    suppressClick = true;          // ドラッグのあとのクリックで予定が開かないように
    setTimeout(() => (suppressClick = false), 0);
    // 離す直前の速さで少しすべらせる
    const [t0, x0, y0] = d.samples[0];
    const dt = Math.max(1, performance.now() - t0);
    let vx = isMonth ? 0 : -(e.clientX - x0) / dt;
    let vy = -(e.clientY - y0) / dt;
    if (performance.now() - d.samples[d.samples.length - 1][0] > 80) { vx = 0; vy = 0; }  // 止めてから離した
    let prev = performance.now();
    const tick = (now) => {
      const ms = now - prev;
      prev = now;
      scroller.scrollLeft += vx * ms;
      scroller.scrollTop += vy * ms;
      const k = Math.pow(0.995, ms);   // 少しずつ遅くする
      vx *= k; vy *= k;
      if (Math.abs(vx) > 0.02 || Math.abs(vy) > 0.02) glide = requestAnimationFrame(tick);
      else finishGlide();
    };
    if (Math.abs(vx) > 0.05 || Math.abs(vy) > 0.05) glide = requestAnimationFrame(tick);
    else finishGlide();
  }
  function finishGlide() {
    glide = 0;
    scroller.classList.remove('dragging');   // 日・週の区切りに合わせ直す
    clearTimeout(settleTimer);
    settleTimer = setTimeout(recenter, 140);
  }
  // カレンダーの上では右クリックのメニューを出さない（右ボタンでつかんで動かすため。
  // Windows は離したとき、ほかのOSは押したときにメニューが出るので、どちらでも出ないようにする）
  function oncontextmenu(e) {
    e.preventDefault();
  }

  function onclickcapture(e) {
    if (suppressClick) { e.stopPropagation(); e.preventDefault(); }
  }

  // ---- キーボード：← → ↑ ↓ で1日（月は1週）ずつ、PageUp/PageDown で7日（月は4週）ずつ ----
  function onkeydown(e) {
    if (selected || e.altKey || e.ctrlKey || e.metaKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    const keys = isMonth
      ? { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1, PageDown: 4, PageUp: -4 }
      : { ArrowRight: 1, ArrowLeft: -1, PageDown: 7, PageUp: -7 };
    if (keys[e.key]) { step(keys[e.key]); e.preventDefault(); }
  }

  onMount(() => {
    const t = todayISO();
    calendar = new Calendar(el, {
      plugins: [dayGridPlugin, timeGridPlugin],
      locale: jaLocale,
      views: {
        // 週: 35日分を横に並べ、画面には7日分（横スクロールで流れる）
        scWeek: { type: 'timeGrid', duration: { days: SPAN }, dateIncrement: { days: 1 }, dateAlignment: 'day' },
        // 月: 15週分を縦に並べ、画面には6週分（縦スクロールで流れる。日曜始まり）
        scMonth: { type: 'dayGrid', duration: { weeks: SPAN }, dateIncrement: { weeks: 1 }, dateAlignment: 'week' },
      },
      initialView: isMonth ? 'scMonth' : 'scWeek',
      initialDate: isMonth ? addDays(sundayOf(t.slice(0, 8) + '01'), -7 * CENTER) : addDays(sundayOf(t), -CENTER),
      firstDay: 0, // 日曜始まり（日〜土）
      // 週の列見出し：曜日と日付を2段にして、スマホの狭い列でも重ならないようにする
      dayHeaderContent: isMonth ? undefined : (arg) => {
        const d = arg.date;
        const wd = '日月火水木金土'[d.getDay()];
        return {
          html: `<span class="sc-wd">${wd}</span><span class="sc-md"><span class="sc-m">${d.getMonth() + 1}/</span>${d.getDate()}</span>`,
        };
      },
      dayHeaderFormat: isMonth ? { weekday: 'short' } : undefined,
      // 月表示: 1日には月を添える（見ている月以外を薄くするのは、スクロールに合わせて下の style で）
      dayCellContent: isMonth ? (arg) => {
        const d = arg.date.getDate();
        const m = arg.date.getMonth() + 1;
        // PCは「11月1日」「2日」、スマホは「11/1」「2」（幅が狭いので）
        const first = d === 1 ? `<span class="sc-first"><span class="sc-l">${m}月</span><span class="sc-s">${m}/</span></span>` : '';
        return { html: `${first}${d}<span class="sc-l">日</span>` };
      } : undefined,
      // 外側の枠でスクロールする（見出しは上に固定。週は時刻の列も左に固定）
      height: 'auto',
      stickyHeaderDates: true,
      expandRows: true,
      nowIndicator: true,
      slotMinTime: '06:00:00',
      slotMaxTime: '24:00:00',
      dayMaxEventRows: isMonth ? 3 : true,
      eventDisplay: isMonth ? 'block' : 'auto',
      allDayText: '終日',
      headerToolbar: false,
      events: source,
      datesSet,
      eventClick: (info) => {
        const p = info.event.extendedProps;
        selected = p.kind === 'todo' && p.eventId ? { kind: 'event', id: p.eventId, todoId: p.id } : { kind: p.kind, id: p.id };
      },
    });
    calendar.render();
    el.addEventListener('click', onclickcapture, true);
    requestAnimationFrame(layout);
    const ro = new ResizeObserver(() => layout());
    ro.observe(scroller);
    return () => {
      ro.disconnect();
      clearTimeout(settleTimer);
      cancelAnimationFrame(glide);
      cancelAnimationFrame(titleRaf);
      el.removeEventListener('click', onclickcapture, true);
      calendar.destroy();
    };
  });

  $effect(() => {
    version;
    reload();
  });

  // 祝日の色と名前（日付ごとのスタイルを作る。カレンダーを描き直さずに反映できる）
  const holidayCss = $derived(Object.entries(holidays).map(([d, name]) => {
    const n = name.replace(/["\\]/g, '');
    const cell = `.cal .fc-daygrid-day[data-date="${d}"]`;
    const col = `.cal .fc-timegrid-col[data-date="${d}"]:not(.fc-day-today)`;
    const head = `.cal .fc-col-header-cell[data-date="${d}"]`;
    const wkCell = `.cal.wk .fc-daygrid-day[data-date="${d}"]:not(.fc-day-today)`;
    return `.cal.mo .fc-daygrid-day[data-date="${d}"]:not(.fc-day-today){background:var(--sun-bg)!important}${col},${wkCell}{background:var(--sun-wash)!important}`
      + `${cell} .fc-daygrid-day-number{color:var(--high)!important}`
      + `${cell} .fc-daygrid-day-top::after{content:"${n}"}`
      + `${head} .sc-wd,${head} .sc-md{color:var(--high)}`
      + `${head} .fc-col-header-cell-cushion::after{content:"${n}"}`;
  }).join(''));

  function changed() {
    reload();
    onchange();
  }
</script>

<svelte:window {onkeydown} />

<div class="cal-wrap" class:month={isMonth}>
  <div class="bar">
    <span class="nav">
      <button class="icon" onclick={() => page(-1)} aria-label={isMonth ? '前の月' : '前の週'} title={isMonth ? '前の月' : '7日前'}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
      </button>
      <button onclick={goToday}>今日</button>
      <button class="icon" onclick={() => page(1)} aria-label={isMonth ? '次の月' : '次の週'} title={isMonth ? '次の月' : '7日後'}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
      </button>
    </span>
    <h2 class="title num" aria-live="polite">{title}</h2>
    <span class="hint faint">
      {isMonth ? 'スクロール・ドラッグ・上下スワイプで前後の週へ' : '横スクロール・ドラッグ（Shift+ホイール・左右スワイプ）で前後の日へ'}
    </span>
  </div>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if isMonth && focusKey}
    <!-- 見ている月以外の日を薄くする（スクロールに合わせて切り替え）。土日は色を残す -->
    {@html `<style>.mo .fc-daygrid-day[data-date^="${focusKey}"]:not(.fc-day-sat):not(.fc-day-sun){background:var(--paper-raised)}.mo .fc-daygrid-day[data-date^="${focusKey}"] .fc-daygrid-day-number{color:var(--ink)}.mo .fc-daygrid-day.fc-day-sun[data-date^="${focusKey}"] .fc-daygrid-day-number{color:var(--high)}.mo .fc-daygrid-day.fc-day-sat[data-date^="${focusKey}"] .fc-daygrid-day-number{color:var(--sat-ink)}</style>`}
  {/if}
  {#if holidayCss}
    <!-- 祝日：日曜と同じ色にして、名前を添える -->
    {@html `<style>${holidayCss}</style>`}
  {/if}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="scroller" class:vert={isMonth} bind:this={scroller} {onscroll} {oncontextmenu}
    onpointerdown={onDragDown} onpointermove={onDragMove} onpointerup={onDragUp} onpointercancel={onDragUp}>
    <div class="cal" class:wk={!isMonth} class:mo={isMonth} bind:this={el}></div>
  </div>
  {#if selected}
    <EventPanel {selected} {today} onclose={() => (selected = null)} onchange={changed} />
  {/if}
</div>

<style>
  .cal-wrap { position: relative; height: 100%; min-height: 560px; display: flex; flex-direction: column; }
  /* スクロールの枠。週は縦横（見出しは上、時刻の列は左に固定）、月は縦（曜日の見出しは上に固定） */
  .scroller {
    flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; cursor: grab;
    scroll-snap-type: x proximity; scroll-padding-left: var(--axis-w, 48px);
    border: 1px solid var(--rule); background: var(--paper-raised);
  }
  .scroller.vert { overflow-x: hidden; scroll-snap-type: y proximity; scroll-padding-top: var(--head-h, 28px); }
  .scroller:global(.dragging) { cursor: grabbing; scroll-snap-type: none; user-select: none; }
  .scroller :global(.fc-event) { cursor: pointer; }
  .cal { user-select: none; }   /* ドラッグで動かすので文字は選択しない */
  .wk { min-width: 100%; }
  /* 月：1週の高さを「画面に6週」に合わせる。見ている月以外は薄く（見ている月は上の style で戻す） */
  .mo :global(.fc-scrollgrid) { border: none; }
  .mo :global(.fc-scroller-harness),
  .mo :global(.fc-scroller),
  .mo :global(.fc-view-harness),
  .mo :global(.fc-view) { overflow: visible !important; }
  .mo :global(.fc-daygrid-body tr) { height: var(--row-h, 96px); }
  .mo :global(.fc-daygrid-day-frame) { height: var(--row-h, 96px); min-height: 0 !important; overflow: hidden; }
  .mo :global(.fc-daygrid-body tr td:first-child) { scroll-snap-align: start; }
  .mo :global(.fc-daygrid-day) { background: var(--paper); }
  .mo :global(.fc-daygrid-day .fc-daygrid-day-number) { color: var(--ink-faint); }
  .mo :global(.fc-daygrid-day.fc-day-today) { background: var(--fc-today-bg-color) !important; }
  .mo :global(.fc-scrollgrid-section-sticky > *) { z-index: 7; background: var(--paper-raised); }
  .wk :global(.fc-scrollgrid) { border: none; }
  /* FullCalendar の内側の枠ははみ出しを切るので、固定表示（sticky）が外側の枠に効くよう解除する */
  .wk :global(.fc-scroller-harness),
  .wk :global(.fc-scroller),
  .wk :global(.fc-view-harness),
  .wk :global(.fc-view) { overflow: visible !important; }
  .wk :global(.fc-col-header-cell) { scroll-snap-align: start; }
  /* 時刻の列を、横に流れてくる予定より手前に出す（FullCalendar の重なり順を上書き） */
  .wk :global(.fc-timegrid-slots),
  .wk :global(.fc-timegrid-axis-chunk > table) { z-index: auto !important; }
  .wk :global(.fc-timegrid-axis),
  .wk :global(.fc-timegrid-slot-label) {
    position: sticky !important; left: 0; z-index: 5 !important; background: var(--paper-raised);
  }
  .wk :global(.fc-col-header .fc-timegrid-axis) { z-index: 6 !important; }
  /* 予定の層にある時刻の列は空なので透明に（今の時刻の矢印だけ見せる） */
  .wk :global(.fc-timegrid-cols .fc-timegrid-axis) { background: transparent; }
  .wk :global(.fc-scrollgrid-section-sticky > *) { z-index: 7; background: var(--paper-raised); }
  .bar { display: flex; align-items: center; gap: 16px; margin-bottom: 10px; flex-wrap: wrap; }
  .nav { display: inline-flex; }
  .nav button { border-radius: 0; margin-left: -1px; font-size: var(--step--1); padding: 4px 10px; }
  .nav button:first-child { border-radius: var(--radius-s) 0 0 var(--radius-s); margin-left: 0; }
  .nav button:last-child { border-radius: 0 var(--radius-s) var(--radius-s) 0; }
  .nav .icon { display: inline-flex; align-items: center; padding: 4px 8px; }
  .title { font-size: var(--step-2); font-weight: 700; margin: 0; min-width: 9em; }
  .hint { font-size: var(--step--1); margin-left: auto; }

  .cal-wrap :global(.fc) {
    --fc-border-color: var(--rule);
    --fc-page-bg-color: var(--paper-raised);
    --fc-neutral-bg-color: var(--paper);
    --fc-today-bg-color: rgba(47, 93, 158, .08);
    --fc-now-indicator-color: var(--high);
    --fc-event-bg-color: var(--ink);
    --fc-event-border-color: var(--ink);
    --fc-button-bg-color: var(--paper-raised);
    --fc-button-border-color: var(--rule);
    --fc-button-text-color: var(--ink);
    --fc-button-hover-bg-color: var(--paper);
    --fc-button-hover-border-color: var(--ink-soft);
    --fc-button-active-bg-color: var(--ink);
    --fc-button-active-border-color: var(--ink);
    font-size: var(--step--1);
  }
  .cal-wrap :global(.sc-first) { font-weight: 700; margin-right: 1px; }
  /* 休みの日：土曜は青、日曜と祝日は赤みのある色。週・月どちらでも */
  .cal-wrap { --sun-bg: #fcefed; --sat-bg: #edf3fb; --sat-ink: #2f6db5;
    --sun-wash: rgba(214, 72, 52, 0.07); --sat-wash: rgba(47, 109, 181, 0.07); }
  .mo :global(.fc-daygrid-day.fc-day-sun:not(.fc-day-today)) { background: var(--sun-bg); }
  .mo :global(.fc-daygrid-day.fc-day-sat:not(.fc-day-today)) { background: var(--sat-bg); }
  .mo :global(.fc-col-header-cell.fc-day-sun) { color: var(--high); }
  .mo :global(.fc-col-header-cell.fc-day-sat) { color: var(--sat-ink); }
  /* 週は時刻の線が見えるよう半透明で重ねる */
  .wk :global(.fc-timegrid-col.fc-day-sun:not(.fc-day-today)),
  .wk :global(.fc-daygrid-day.fc-day-sun:not(.fc-day-today)) { background: var(--sun-wash); }
  .wk :global(.fc-timegrid-col.fc-day-sat:not(.fc-day-today)),
  .wk :global(.fc-daygrid-day.fc-day-sat:not(.fc-day-today)) { background: var(--sat-wash); }
  .wk :global(.fc-col-header-cell.fc-day-sun .sc-md) { color: var(--high); }
  .wk :global(.fc-col-header-cell.fc-day-sat .sc-md) { color: var(--sat-ink); }
  /* 祝日の名前（月は日付の左、週は日付の下） */
  .cal-wrap :global(.fc-daygrid-day-top::after) {
    flex: 1; min-width: 0; padding: 4px 0 0 4px; font-size: 10px; color: var(--high);
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  }
  .cal-wrap :global(.fc-col-header-cell-cushion::after) {
    font-size: 10px; color: var(--high); max-width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  }
  .cal-wrap :global(.sc-s) { display: none; }
  /* 表示の最初の日に付く「月の始まり」の強調はやめ、1日だけ月を添える */
  .cal-wrap :global(.fc .fc-daygrid-month-start) { font-size: inherit; font-weight: inherit; }
  .cal-wrap :global(.fc-event) { cursor: pointer; }
  .cal-wrap :global(.fc-col-header-cell-cushion) { display: flex; flex-direction: column; align-items: center; line-height: 1.25; padding: 4px 2px; }
  .cal-wrap :global(.sc-wd) { font-size: .85em; color: var(--ink-soft); }
  .cal-wrap :global(.sc-md) { font-weight: 700; white-space: nowrap; }
  .cal-wrap :global(.fc-day-sun .sc-wd) { color: var(--high); }
  .cal-wrap :global(.fc-day-sat .sc-wd) { color: #2f6db5; }
  @media (max-width: 720px) {
    .cal-wrap :global(.sc-m) { display: none; } /* スマホでは日付の数字だけ */
    .cal-wrap :global(.sc-l) { display: none; }
    .cal-wrap :global(.sc-s) { display: inline; }
    .cal-wrap :global(.fc-daygrid-day-top::after),
    .cal-wrap :global(.fc-col-header-cell-cushion::after) { font-size: 9px; }
    .title { font-size: var(--step-1); min-width: 0; }
    .hint { width: 100%; margin-left: 0; }
    .cal-wrap :global(.fc .fc-timegrid-axis-cushion),
    .cal-wrap :global(.fc .fc-timegrid-slot-label-cushion) { padding: 0 2px; }
  }
  .cal-wrap :global(.sc-deadline) { background: var(--high); border-color: var(--high); }
  .cal-wrap :global(.fc .sc-todo) {
    background: var(--paper-raised); color: var(--ink); border: none; border-left: 3px solid var(--medium);
  }
  .cal-wrap :global(.fc .sc-todo .fc-event-title),
  .cal-wrap :global(.fc .sc-todo .fc-event-main) { color: var(--ink); }
  .cal-wrap :global(.fc .sc-high) { border-left-color: var(--high); }
  .cal-wrap :global(.fc .sc-low) { border-left-color: var(--low); }
  .cal-wrap :global(.fc .sc-done) { opacity: .55; }
  .cal-wrap :global(.fc .sc-done .fc-event-title) { text-decoration: line-through; }
</style>
