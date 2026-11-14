/* Live paper session. Starts when you press the button, then re-reads INDmoney every minute and lets
   the rules in ls_engine.js open, mark and close intraday paper trades by themselves, until 15:10.
   It lives in this open page only: closing or reloading the page ends the session and its book. */
(function () {
  const { el, inr, num, pct, cls, tag } = CD; const E = window.LSE;
  const L = (CD.LS = { on: false, timer: null, since: 0, book: { day: '', trades: [], seen: {}, seq: 0 }, note: '' });
  const FAST = ['indices', 'watch_live', 'm_gainers', 'm_losers', 'm_52high', 'm_active', 'm_upper', 'nifty_chain'], SLOW = ['news_live'];
  const MON = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };
  const ist = () => { const t = CD.istParts(); return { wd: t.wd, hhmm: String(t.h).padStart(2, '0') + ':' + String(t.m).padStart(2, '0') }; };
  const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
  const rd = (id) => { const d = dash.data(id); return d.status === 'ok' ? d.data : []; };

  const snapshot = () => { const rows = {}; const add = (r, o) => { if (r.symbol && o.price != null) rows[r.symbol] = Object.assign(rows[r.symbol] || {}, o, { symbol: r.symbol }); };
    ['m_gainers', 'm_losers', 'm_52high', 'm_active', 'm_upper'].forEach((id) => rd(id).forEach((r) => add(r, { price: r.price, chg_pct: r.chg_pct, day_high: r.day_high, day_low: r.day_low, volume: r.volume, circ_up: r.circ_up, circ_lo: r.circ_lo })));
    rd('watch_live').forEach((r) => add(r, { price: r.live, chg_pct: r.chg_pct, day_high: r.high, day_low: r.low, volume: r.volume, circ_up: r.upper, circ_lo: r.lower }));
    const news = {}; rd('news_live').forEach((n) => { if (n.rank === 0 || !news[n.symbol]) news[n.symbol] = { sentiment: n.sentiment, date: n.date }; });
    const ch = rd('nifty_chain'); const nifty = ch.length ? { chg_pct: ch[0].chg_pct, spot: ch[0].spot } : null;
    return { day: today(), hhmm: ist().hhmm, rows: Object.values(rows), news, nifty, chain: ch }; };

  const refresh = (ids) => ids.forEach((id) => { try { dash.refresh(id); } catch (e) { /* keeps its last answer */ } });
  const tick = () => { const t = ist(); if (['Sat', 'Sun'].includes(t.wd) || t.hhmm >= '15:35' || Date.now() - L.since > 7 * 3600000) { L.set(false); return; }
    if (t.hhmm >= '09:15' && t.hhmm < '15:35') { L.n = (L.n || 0) + 1; refresh(FAST); if (L.n % 5 === 1) refresh(SLOW); }
    dash.draw('ls_chip'); };
  L.set = (on) => { clearInterval(L.timer); L.timer = null; L.on = !!on; if (on) { L.since = Date.now(); L.n = 0; refresh(FAST.concat(SLOW)); L.timer = setInterval(tick, 60000); }
    document.querySelectorAll('#btn-ls').forEach((b) => b.setAttribute('aria-pressed', String(L.on))); dash.draw('ls_chip'); };
  document.querySelectorAll('#btn-ls').forEach((b) => b.addEventListener('click', () => L.set(!L.on)));
  document.querySelectorAll('#btn-lscopy').forEach((b) => b.addEventListener('click', () => { const r = L.book.trades.map((t) => [t.day, t.time, t.label, t.basis, t.entry, t.exit, t.pnl_rs, t.why].join(',')); CD.copy('day,time,trade,basis,entry,exit,pnl_rs,why\n' + r.join('\n'), b); }));

  const total = () => L.book.trades.reduce((a, t) => a + (t.status === 'OPEN' ? E.openPnl(t) : t.pnl_rs), 0);
  dash.draw('ls_chip', (c) => { const needs = FAST.concat(SLOW).map((id) => dash.data(id).status); const ready = needs.filter((s) => s === 'ok').length;
    if (L.on && ready >= 6) E.step(L.book, snapshot()); const open = L.book.trades.filter((t) => t.status === 'OPEN').length, p = total(), t = ist();
    ['live', 'wait', 'off'].forEach((k) => c.classList.toggle(k, k === (L.on ? 'live' : 'wait')));
    c.replaceChildren(el('i'), document.createTextNode(!L.on ? 'Live paper session: off' : t.hhmm >= '15:10' ? `Live paper session: closed for the day · ${p >= 0 ? '+' : '−'}${inr(Math.abs(p))}` : `LIVE PAPER · ${open} open · ${L.book.trades.length} today · ${p >= 0 ? '+' : '−'}${inr(Math.abs(p))}`));
    ['ls_kpi', 'ls_body', 'ls_stats', 'ls_status'].forEach((n) => dash.draw(n)); });

  dash.draw('ls_status', (p) => { const t = ist(); const closed = ['Sat', 'Sun'].includes(t.wd) || t.hhmm < '09:15' || t.hhmm >= '15:30';
    p.textContent = !L.on ? 'Press Start to begin. It re-reads INDmoney every minute and trades by the rules below until 15:10, as long as this page stays open.'
      : closed ? 'Session is on, but the NSE is closed: it will wait for the open (entries start at 09:20).' : `Running. Last read ${t.hhmm} IST. Entries 09:20 to 15:10, six trades at most, everything closed at 15:10.`; });
  dash.draw('ls_kpi', (b) => { const k = b.dataset.k, tr = L.book.trades; const closed = tr.filter((t) => t.status !== 'OPEN'); const p = total();
    b.textContent = k === 'n' ? String(tr.length) : k === 'open' ? String(tr.filter((t) => t.status === 'OPEN').length) : k === 'win' ? (closed.length ? Math.round((closed.filter((t) => t.pnl_rs > 0).length / closed.length) * 100) + '%' : '—') : (p > 0 ? '+' : p < 0 ? '−' : '') + inr(Math.abs(p), 0);
    if (k === 'pnl') { b.classList.toggle('up', p > 0); b.classList.toggle('down', p < 0); } });
  dash.draw('ls_body', (body) => { if (!L.book.trades.length) { const tr = el('tr'), td = el('td', 'dim', L.on ? 'No trade yet. The rules need a 2% move near the day high or low on real turnover.' : 'No trades. Start the session.'); td.colSpan = 7; tr.appendChild(td); body.replaceChildren(tr); return; }
    CD.fillTable(body, L.book.trades.slice().reverse(), [{ cls: 'num', render: (d) => d.time }, { render: (d) => d.label }, { cls: 'hs', render: (d) => d.basis }, { render: (d) => tag(d.status === 'OPEN' ? 'OPEN' : d.why === 'stop' ? 'STOPPED' : d.status, d.status === 'OPEN' ? 'b' : d.status === 'WIN' ? 'g' : 'r') },
      { cls: 'num r', render: (d) => num(d.entry, 2) }, { cls: 'num r', render: (d) => num(d.status === 'OPEN' ? d.last : d.exit, 2) }, { cls: 'num r', render: (d) => { const v = d.status === 'OPEN' ? E.openPnl(d) : d.pnl_rs; return el('span', cls(v), (v > 0 ? '+' : '') + inr(v, 0)); } }], 'id'); });
  dash.draw('ls_stats', (body) => { const s = E.stats(L.book); if (!s.length) { body.replaceChildren(); return; }
    CD.fillTable(body, s, [{ render: (d) => d.group }, { cls: 'num r', render: (d) => String(d.open) }, { cls: 'num r', render: (d) => String(d.closed) }, { cls: 'num r', render: (d) => (d.closed ? Math.round((d.wins / d.closed) * 100) + '%' : '—') }, { cls: 'num r', render: (d) => el('span', cls(d.pnl), (d.pnl > 0 ? '+' : '') + inr(d.pnl, 0)) }], 'group'); });
})();
