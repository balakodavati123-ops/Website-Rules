/* A minimal stand-in for the dashboard platform's `dash` API, for local testing only.
   It feeds shape-correct sample answers through the page's real loaders and calcs. */
(function () {
  const A = window.__ANSWERS; const FILES = window.__FILES; const L = {}, C = {}, DRAW = {}; const PARAMS = { sym: 'INDI00012', iv: '15minute', lb: '7d', csym: 'BTCUSD', ctf: '1day' };
  const CALLS = new Set(Object.keys(A));
  const cache = {};
  function data(id) {
    if (cache[id] && !CALLS.has('candles') ) { /* no-op */ }
    if (FILES[id]) return { status: 'ok', data: FILES[id], columns: Object.keys(FILES[id][0] || {}), message: '', refreshing: false, meta: [] };
    if (CALLS.has(id)) { let ans = A[id]; if (typeof ans === 'function') ans = ans(PARAMS); let rows = ans; if (L[id]) { try { rows = L[id].fn({ answer: ans }); } catch (e) { return { status: 'error', data: [], message: id + ': ' + e.message }; } }
      return { status: 'ok', data: rows, columns: Object.keys((rows && rows[0]) || {}), message: '', refreshing: false, meta: [] }; }
    if (C[id]) { const ins = C[id].inputs.map((i) => { const d = data(i); return d.status === 'ok' ? d.data : []; }); try { const out = C[id].fn(...ins); return { status: 'ok', data: out, columns: Object.keys((Array.isArray(out) && out[0]) || {}), message: '' }; } catch (e) { return { status: 'error', data: null, message: 'calc ' + id + ': ' + e.message }; } }
    return { status: 'missing', data: [], message: id };
  }
  const runOne = (name, el) => { if (el.closest('[hidden]')) return; const spec = DRAW[name]; if (!spec) return;
    try { if (typeof spec === 'function') spec(el); else { if (!el.__made) el.__made = spec.mount ? spec.mount(el) : {}; spec.update(el, el.__made); } } catch (e) { window.__errors.push('draw ' + name + ': ' + (e.stack || e.message)); } };
  window.dash = {
    loader: (id, o) => { L[id] = o; }, calc: (id, o) => { C[id] = o; }, data,
    draw: (name, spec) => { if (spec !== undefined) DRAW[name] = spec; document.querySelectorAll('[data-draw="' + name + '"]').forEach((el) => runOne(name, el)); },
    onData: (fn) => fn(), params: () => ({ ...PARAMS }), setParams: (p) => { Object.assign(PARAMS, p); window.__rerun(); }, resetParams: () => {}, setLink: () => {}, refresh: () => {},
    colors: ['#4f8cff', '#2de3a5', '#ffb64a', '#ff5f75', '#a184ff', '#29d3ee', '#ff7ac6', '#8ea3c4'] };
  window.__rerun = () => Object.keys(DRAW).forEach((n) => document.querySelectorAll('[data-draw="' + n + '"]').forEach((el) => runOne(n, el)));
  window.__dataStatus = () => { const out = {}; Object.keys(A).concat(Object.keys(FILES), Object.keys(C)).forEach((id) => { const d = data(id); out[id] = d.status + (d.status === 'ok' ? ':' + (Array.isArray(d.data) ? d.data.length : typeof d.data) : ' ' + d.message); }); return out; };
  window.__errors = []; window.addEventListener('error', (e) => window.__errors.push('error: ' + e.message + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno));
})();
