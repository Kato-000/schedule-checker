export const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];
export const PRIORITY_LABEL = { high: '高', medium: '中', low: '低' };
export const PRIORITIES = ['high', 'medium', 'low'];

export function parseISO(s) {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function toISO(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function addDays(iso, n) {
  const d = parseISO(iso);
  d.setDate(d.getDate() + n);
  return toISO(d);
}

/** 10/28（水） */
export function md(iso) {
  if (!iso) return '';
  const d = parseISO(iso);
  return `${d.getMonth() + 1}/${d.getDate()}（${WEEKDAYS[d.getDay()]}）`;
}

/** 今日から見た言い方（今日・明日・3日後・10/28（水）） */
export function relDay(iso, todayIso) {
  if (!iso) return '';
  if (!todayIso) return md(iso);   // 今日の日付をまだ読み込んでいないとき
  const diff = Math.round((parseISO(iso) - parseISO(todayIso)) / 86400000);
  if (diff === 0) return '今日';
  if (diff === 1) return '明日';
  if (diff === -1) return '昨日';
  if (diff < 0) return `${-diff}日前`;
  if (diff <= 6) return `${diff}日後`;
  return md(iso);
}

export function eventWhen(e) {
  const start = `${md(e.start_date)}${e.start_time ? ' ' + e.start_time : ''}`;
  if (e.end_date && e.end_date !== e.start_date) return `${start} 〜 ${md(e.end_date)}${e.end_time ? ' ' + e.end_time : ''}`;
  if (e.end_time) return `${start}〜${e.end_time}`;
  return start;
}
