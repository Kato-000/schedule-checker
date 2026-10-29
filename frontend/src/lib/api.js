// バックエンドとの通信
// - デスクトップ版（Tauri）と開発サーバー: PCのバックエンド 127.0.0.1:8765
// - ブラウザでバックエンドから開いたとき（PCの :8765、スマホの :8766）: 同じ場所
import { isTauri } from './desktop.js';

const BASE = import.meta.env.VITE_API_BASE
  ?? (isTauri || location.port === '5173' ? 'http://127.0.0.1:8765' : '');

async function request(method, path, body) {
  let res;
  try {
    const raw = typeof Blob !== 'undefined' && body instanceof Blob;  // 録音はそのまま送る
    res = await fetch(BASE + path, {
      method,
      headers: body ? { 'Content-Type': raw ? (body.type || 'application/octet-stream') : 'application/json' } : undefined,
      body: body ? (raw ? body : JSON.stringify(body)) : undefined,
      credentials: 'same-origin',
    });
  } catch {
    throw new Error(isTauri || !BASE
      ? 'バックエンドに接続できません。PCでバックエンドが起動しているか確認してください。'
      : 'バックエンドに接続できません。start_backend.bat で起動しているか確認してください。');
  }
  if (!res.ok) {
    let detail = `エラー（${res.status}）`;
    let login = false;
    try {
      const j = await res.json();
      if (typeof j.detail === 'string') detail = j.detail;
      login = !!j.login;
    } catch { /* 本文なし */ }
    if (res.status === 401 && login) window.dispatchEvent(new Event('auth-required'));
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  meta: () => request('GET', '/api/meta'),
  today: () => request('GET', '/api/today'),
  digest: () => request('GET', '/api/digest'),
  runDigest: () => request('POST', '/api/digest/run'),

  authStatus: () => request('GET', '/api/auth/status'),
  login: (pin) => request('POST', '/api/auth/login', { pin }),
  logout: () => request('POST', '/api/auth/logout'),

  /** kind: event（予定）/ todo（予定に結びつかないTodo）、source: text / voice */
  propose: (text, { kind = 'event', source = 'text' } = {}) => request('POST', '/api/proposals', { text, kind, source }),
  proposals: () => request('GET', '/api/proposals'),
  approve: (id, event, todos) => request('POST', `/api/proposals/${id}/approve`, { event, todos }),
  reject: (id) => request('POST', `/api/proposals/${id}/reject`),
  redraft: (id, event) => request('POST', `/api/proposals/${id}/redraft`, { event }),
  resolve: (id, keep) => request('POST', `/api/proposals/${id}/resolve`, { keep }),

  holidays: (start, end) => request('GET', `/api/holidays?start=${start}&end=${end}`),
  events: (start, end) => request('GET', `/api/events?start=${start}&end=${end}`),
  event: (id) => request('GET', `/api/events/${id}`),
  updateEvent: (id, fields) => request('PATCH', `/api/events/${id}`, fields),
  deleteEvent: (id) => request('DELETE', `/api/events/${id}`),

  todos: (start, end) => request('GET', `/api/todos?start=${start}&end=${end}`),
  todo: (id) => request('GET', `/api/todos/${id}`),
  createTodo: (fields) => request('POST', '/api/todos', fields),
  quickTodo: (text) => request('POST', '/api/todos/quick', { text }),
  updateTodo: (id, fields) => request('PATCH', `/api/todos/${id}`, fields),
  deleteTodo: (id) => request('DELETE', `/api/todos/${id}`),

  rules: () => request('GET', '/api/rules'),
  addRule: (text, category) => request('POST', '/api/rules', { text, category }),
  updateRule: (id, fields) => request('PATCH', `/api/rules/${id}`, fields),
  deleteRule: (id) => request('DELETE', `/api/rules/${id}`),
  extractRules: () => request('POST', '/api/rules/extract'),

  settings: () => request('GET', '/api/settings'),
  saveSettings: (fields) => request('PUT', '/api/settings', fields),

  lan: () => request('GET', '/api/lan'),
  saveLan: (fields) => request('PUT', '/api/lan', fields),

  // ネット連携（ボタンを押したときだけ通信する）
  net: () => request('GET', '/api/net'),
  saveNet: (fields) => request('PUT', '/api/net', fields),
  netQueries: (event) => request('POST', '/api/net/queries', { event }),
  netLookup: (event, queries) => request('POST', '/api/net/lookup', { event, queries }),
  mapUrl: (fields) => request('POST', '/api/net/map', fields),
  route: (eid, mode) => request('POST', `/api/events/${eid}/route`, { mode }),
  clearRoute: (eid) => request('DELETE', `/api/events/${eid}/route`),

  openUrl: (url) => request('POST', '/api/open_url', { url }),
  warmLLM: () => request('POST', '/api/llm/warm'),
  warmVoice: () => request('POST', '/api/voice/warm'),
  voice: () => request('GET', '/api/voice'),
  saveVoice: (fields) => request('PUT', '/api/voice', fields),
  voiceDownload: (model) => request('POST', '/api/voice/download', { model }),
  voiceDelete: (model) => request('DELETE', `/api/voice/models/${model}`),
  transcribe: (blob) => request('POST', '/api/voice/transcribe', blob),

  google: () => request('GET', '/api/google'),
  saveGoogle: (fields) => request('PUT', '/api/google', fields),
  googleSecret: (content) => request('POST', '/api/google/client_secret', { content }),
  googleConnect: () => request('POST', '/api/google/connect'),
  googleDisconnect: () => request('POST', '/api/google/disconnect'),
  googleSync: () => request('POST', '/api/google/sync'),
};
